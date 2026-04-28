from __future__ import annotations

import datetime
import lzma
import struct
import numpy as np

from collections import Counter
from typing import Optional
from nonebot.log import logger

from ..data import file_parser_data

# 参考实现路径：
# - prelude/src/Gameplay/Replays/ReplayFormat.fs
# - osu.Game.Rulesets.Osu/Replays/OsuAutoGeneratorBase.cs
# - osu.Game/Rulesets/UI/ReplayRecorder.cs


def read_uleb128(data: bytes, offset: int) -> tuple[int, int]:
    """
    summary:
        读取 ULEB128 无符号整数。
    Args:
        data: 原始字节序列。
        offset: 起始偏移。
    Returns:
        (解析值, 新偏移)。
    """
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("Unexpected EOF while reading ULEB128")
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
        if shift > 35:
            raise ValueError("ULEB128 value is too large")
    return result, offset


def read_string(data: bytes, offset: int) -> tuple[str, int]:
    """
    summary:
        读取 osu! 回放字符串（0x0B + uleb128 + utf8）。
    Args:
        data: 原始字节序列。
        offset: 起始偏移。
    Returns:
        (字符串, 新偏移)。
    """
    if offset >= len(data):
        return "", offset

    flag = data[offset]
    offset += 1
    if flag == 0x00:
        return "", offset
    if flag != 0x0B:
        return "", offset

    try:
        length, offset = read_uleb128(data, offset)
    except ValueError:
        return "", offset

    if offset + length > len(data):
        return "", offset

    value = data[offset : offset + length].decode("utf-8", errors="replace")
    return value, offset + length


def findkey(x: int = 0) -> np.ndarray:
    """
    summary:
        将位掩码转换为固定 18 轨按键数组。
    Args:
        x: 按键位掩码。
    Returns:
        长度为 18 的 0/1 numpy 数组。
    """
    return np.array([(x >> i) & 1 for i in range(18)], dtype=np.int8)


class ReplayEvent:
    """兼容旧代码的 replay event 对象。"""

    def __init__(self, time_delta: int, keys: int):
        self.time_delta = time_delta
        self.keys = keys


class ReplayCursor:
    """
    summary:
        IReplay 风格游标，支持 HasNext/GetNext/EnumerateRecentFrames/GetFullReplay。
    Args:
        replay_data: 绝对时间序列 [(time_ms, bitmask)]。
    Returns:
        无。
    """

    def __init__(self, replay_data: list[tuple[float, int]]):
        self._replay_data = list(replay_data)
        self._idx = 0

    def HasNext(self, time_ms: float) -> bool:
        """
        summary:
            判断是否还有时间戳不晚于给定时间的帧可读。
        Args:
            time_ms: 当前时间。
        Returns:
            是否可读取下一帧。
        """
        return self._idx < len(self._replay_data) and self._replay_data[self._idx][0] <= time_ms

    def GetNext(self) -> tuple[float, int] | None:
        """
        summary:
            读取并推进到下一帧。
        Args:
            无。
        Returns:
            下一帧或 None。
        """
        if self._idx >= len(self._replay_data):
            return None
        item = self._replay_data[self._idx]
        self._idx += 1
        return item

    def EnumerateRecentFrames(self, time_ms: float, window_ms: float = 1000.0) -> list[tuple[float, int]]:
        """
        summary:
            返回 time_ms 前 window_ms 范围内的帧。
        Args:
            time_ms: 当前时间。
            window_ms: 回看窗口。
        Returns:
            帧列表。
        """
        begin = time_ms - max(0.0, window_ms)
        return [item for item in self._replay_data if begin <= item[0] <= time_ms]

    def GetFullReplay(self) -> list[tuple[float, int]]:
        """
        summary:
            返回完整回放帧序列。
        Args:
            无。
        Returns:
            帧列表拷贝。
        """
        return list(self._replay_data)


class _BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def read_byte(self) -> int:
        if self.offset + 1 > len(self.data):
            raise ValueError("Unexpected EOF while reading byte")
        value = self.data[self.offset]
        self.offset += 1
        return value

    def read_int16(self) -> int:
        if self.offset + 2 > len(self.data):
            raise ValueError("Unexpected EOF while reading int16")
        value = struct.unpack_from("<h", self.data, self.offset)[0]
        self.offset += 2
        return value

    def read_int32(self) -> int:
        if self.offset + 4 > len(self.data):
            raise ValueError("Unexpected EOF while reading int32")
        value = struct.unpack_from("<i", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_int64(self) -> int:
        if self.offset + 8 > len(self.data):
            raise ValueError("Unexpected EOF while reading int64")
        value = struct.unpack_from("<q", self.data, self.offset)[0]
        self.offset += 8
        return value

    def read_bytes(self, n: int) -> bytes:
        if n < 0:
            raise ValueError("Negative byte length")
        if self.offset + n > len(self.data):
            raise ValueError("Unexpected EOF while reading bytes")
        value = self.data[self.offset : self.offset + n]
        self.offset += n
        return value

    def read_osu_string(self) -> str:
        value, new_offset = read_string(self.data, self.offset)
        self.offset = new_offset
        return value


class osr_file:
    """
    summary:
        解析 .osr 回放，保留 real/chart 双时间线并兼容旧字段。
    Args:
        file_path: 回放文件路径。
        assume_replay_times_scaled: None=自动；True=按速度模组反缩放到 chart 时间；False=不缩放。
        keep_float_times: 是否保留浮点毫秒时间。
        log_level_override: 兼容参数，占位不用。
        allow_force_no_scale: 强制不进行速度反缩放。
    Returns:
        无。
    """

    def __init__(
        self,
        file_path: str,
        assume_replay_times_scaled: Optional[bool] = None,
        keep_float_times: bool = True,
        log_level_override: Optional[str] = None,
        allow_force_no_scale: bool = False,
    ):
        self.file_path = str(file_path)
        self.status = "init"
        self.error_message = ""
        self.assume_replay_times_scaled = assume_replay_times_scaled
        self.keep_float_times = keep_float_times
        self.log_level_override = log_level_override
        self.allow_force_no_scale = allow_force_no_scale

        self._init_derived_attrs()

        try:
            with open(self.file_path, "rb") as f:
                data = f.read()
        except Exception as exc:
            self.status = "ParseError"
            self.error_message = f"读取失败: {exc}"
            logger.error(f"读取回放文件失败: {exc}")
            return

        self._parse_header(data)
        if self.status not in {"init", "OK", "NotMania"}:
            return
        if self.status == "NotMania":
            return

        self.judge = {
            "320": self.gekis,
            "300": self.number_300s,
            "200": self.katus,
            "100": self.number_100s,
            "50": self.number_50s,
            "0": self.misses,
        }

        total_objects = (
            self.gekis
            + self.number_300s
            + self.katus
            + self.number_100s
            + self.number_50s
            + self.misses
        )
        if total_objects > 0:
            self.acc = (
                (
                    (self.gekis + self.number_300s) * 300
                    + self.katus * 200
                    + self.number_100s * 100
                    + self.number_50s * 50
                )
                / (total_objects * 300)
                * 100
            )
        else:
            self.acc = 0.0

        self.ratio = self.gekis / self.number_300s if self.number_300s > 0 else 0.0
        if self.status == "init":
            self.status = "OK"

    def _init_derived_attrs(self) -> None:
        self.pressset = [[] for _ in range(18)]
        self.pressset_raw = [[] for _ in range(18)]

        self.intervals: list[int] = []
        self.intervals_raw: list[float] = []

        self.press_times: list[int] = []
        self.press_times_float: list[float] = []
        self.press_times_raw: list[float] = []

        self.press_events: list[tuple[int, int]] = []
        self.press_events_float: list[tuple[int, float]] = []
        self.press_events_raw: list[tuple[int, float]] = []

        self.press_times_real: list[int] = []
        self.press_times_real_float: list[float] = []
        self.press_events_real: list[tuple[int, int]] = []
        self.press_events_real_float: list[tuple[int, float]] = []

        self.press_times_chart: list[int] = []
        self.press_times_chart_float: list[float] = []
        self.press_events_chart: list[tuple[int, int]] = []
        self.press_events_chart_float: list[tuple[int, float]] = []

        self.play_data: list[ReplayEvent] = []
        self.replay_data_real: list[tuple[float, int]] = []
        self.replay_data_chart: list[tuple[float, int]] = []

        self.sample_rate = float("inf")
        self.fft_analysis_result = None

        self.acc = 0.0
        self.ratio = 0.0
        self.corrector = 1.0
        self.speed_factor = 1.0
        self.scale_applied = False
        self.judge = {"320": 0, "300": 0, "200": 0, "100": 0, "50": 0, "0": 0}

        self.mod = 0
        self.mods = ["None"]
        self.score = 0
        self.max_combo = 0
        self.is_perfect_combo = False

        self.timestamp = datetime.datetime.min
        self.life_bar_graph = ""
        self.game_mode = 3
        self.game_version = 0
        self.beatmap_hash = ""
        self.player_name = ""
        self.replay_hash = ""
        self.replay_id = 0
        self.extra_mod_data = None
        self.compressed_data = b""

        self.number_300s = 0
        self.number_100s = 0
        self.number_50s = 0
        self.gekis = 0
        self.katus = 0
        self.misses = 0

    def _parse_header(self, data: bytes) -> None:
        reader = _BinaryReader(data)
        try:
            self.game_mode = reader.read_byte()
            if self.game_mode != 3:
                self.status = "NotMania"
                return

            self.game_version = reader.read_int32()
            self.beatmap_hash = reader.read_osu_string()
            self.player_name = reader.read_osu_string()
            self.replay_hash = reader.read_osu_string()

            self.number_300s = reader.read_int16()
            self.number_100s = reader.read_int16()
            self.number_50s = reader.read_int16()
            self.gekis = reader.read_int16()
            self.katus = reader.read_int16()
            self.misses = reader.read_int16()

            self.score = reader.read_int32()
            self.max_combo = reader.read_int16()
            self.is_perfect_combo = reader.read_byte() != 0

            self.mod = reader.read_int32()
            self.mods = self._parse_mods(self.mod)

            self.life_bar_graph = reader.read_osu_string()
            ticks = reader.read_int64()
            self.timestamp = self._ticks_to_datetime(ticks)

            replay_data_length = reader.read_int32()
            self.compressed_data = reader.read_bytes(replay_data_length)

            if reader.remaining >= 8:
                self.replay_id = reader.read_int64()
            else:
                self.replay_id = 0

            self.extra_mod_data = None
        except Exception as exc:
            self.status = "ParseError"
            self.error_message = f"头部解析失败: {exc}"
            logger.error(f"解析 .osr 文件头失败: {exc}")

    def _ticks_to_datetime(self, ticks: int) -> datetime.datetime:
        try:
            return datetime.datetime.min + datetime.timedelta(microseconds=ticks / 10)
        except Exception:
            return datetime.datetime.min

    def _parse_frame(self, frame: str) -> tuple[float, int] | None:
        if not frame:
            return None
        parts = frame.split("|")
        if len(parts) < 4:
            return None

        try:
            time_delta = float(parts[0])
            x_val = float(parts[1])
        except Exception:
            return None

        # -12345 是 osu! 回放结束哨兵，按官方格式直接跳过。
        if time_delta == -12345:
            return None

        # 与 prelude 的解码语义对齐：
        # 1) 保留负 time_delta（例如开头的预滚动帧），不能裁成 0；
        # 2) 不基于 x/y 特判丢帧，按状态变化再由后续逻辑去重。
        return time_delta, int(x_val)

    def _build_speed_factor(self) -> float:
        """
        .osr 速度模组映射：
        - DoubleTime(64) / Nightcore(512) -> 1.5
        - HalfTime(256) -> 0.75
        Daycore 在多数实现中等价于 HT 速率，本解析器按 0.75 处理。
        """
        try:
            mod_int = int(self.mod)
        except Exception:
            return 1.0

        if (mod_int & 64) or (mod_int & 512):
            return 1.5
        if mod_int & 256:
            return 0.75
        return 1.0

    def _resolve_scale_mode(self) -> bool:
        if self.allow_force_no_scale:
            if self.speed_factor != 1.0:
                logger.warning("检测到速度模组但已启用 allow_force_no_scale，保留原始时间作为 chart 时间。")
            return False

        if self.assume_replay_times_scaled is True:
            return True
        if self.assume_replay_times_scaled is False:
            if self.speed_factor != 1.0:
                logger.warning("已显式关闭时间反缩放，chart 时间将与 real 时间一致。")
            return False

        if self.speed_factor != 1.0:
            return True
        return False

    def _estimate_sample_rate(self, intervals_ms: list[float]) -> float:
        if not intervals_ms:
            return float("inf")

        valid = [i for i in intervals_ms if 0 < i <= 100]
        if not valid:
            valid = [i for i in intervals_ms if i > 0]
        if not valid:
            return float("inf")

        rounded = [int(round(i)) for i in valid if i > 0]
        if not rounded:
            return float("inf")

        counts = Counter(rounded)
        common_intervals = counts.most_common(3)
        total_count = sum(c for _, c in common_intervals)
        if total_count <= 0:
            return float("inf")

        weighted_interval = sum(interval * c for interval, c in common_intervals) / total_count
        median_interval = sorted(rounded)[len(rounded) // 2]
        avg_interval = min(weighted_interval, float(median_interval))
        if avg_interval <= 0:
            return float("inf")

        sample_rate = 1000.0 / avg_interval
        common_rates = [60, 120, 144, 240, 360, 480, 1000]
        closest_rate = min(common_rates, key=lambda r: abs(r - sample_rate))
        if abs(closest_rate - sample_rate) < 5:
            sample_rate = float(closest_rate)
        elif sample_rate > 1000:
            sample_rate = 1000.0
        return sample_rate

    def _apply_time_conversion(self, scale: bool) -> None:
        self.scale_applied = scale
        if scale and self.speed_factor != 0:
            self.corrector = 1.0 / self.speed_factor
        else:
            self.corrector = 1.0

        # real 时间线
        self.press_times_real_float = list(self.press_times_raw)
        self.press_events_real_float = list(self.press_events_raw)
        self.press_times_real = [int(round(t)) for t in self.press_times_real_float]
        self.press_events_real = [(col, int(round(t))) for col, t in self.press_events_real_float]

        # chart 时间线
        self.press_times_chart_float = [float(t * self.corrector) for t in self.press_times_real_float]
        self.press_events_chart_float = [
            (col, float(t * self.corrector)) for col, t in self.press_events_real_float
        ]
        self.press_times_chart = [int(round(t)) for t in self.press_times_chart_float]
        self.press_events_chart = [(col, int(round(t))) for col, t in self.press_events_chart_float]

        self.replay_data_chart = [
            (float(t * self.corrector), mask) for t, mask in self.replay_data_real
        ]

        # 旧字段兼容：默认保持 chart 时间作为匹配时间线
        self.press_times_float = list(self.press_times_chart_float)
        self.press_events_float = list(self.press_events_chart_float)
        self.press_times = list(self.press_times_chart)
        self.press_events = list(self.press_events_chart)

        self.intervals = [int(round(v * self.corrector)) for v in self.intervals_raw]
        self.pressset = [
            [int(round(d * self.corrector)) for d in durations] if durations else []
            for durations in self.pressset_raw
        ]

        if not self.keep_float_times:
            self.press_times_real_float = [float(t) for t in self.press_times_real]
            self.press_events_real_float = [(c, float(t)) for c, t in self.press_events_real]
            self.press_times_chart_float = [float(t) for t in self.press_times_chart]
            self.press_events_chart_float = [(c, float(t)) for c, t in self.press_events_chart]
            self.press_times_float = [float(t) for t in self.press_times]
            self.press_events_float = [(c, float(t)) for c, t in self.press_events]

    def process(self) -> None:
        """
        summary:
            解压 replay 帧并构建实时时间线与 chart 时间线。
        Args:
            无。
        Returns:
            无。
        """
        if self.status not in ["OK", "init"]:
            return
        if not self.compressed_data:
            self.status = "ParseError"
            self.error_message = "回放主体为空"
            return

        try:
            replay_text = lzma.decompress(self.compressed_data).decode("ascii", errors="ignore")
        except Exception as exc:
            self.status = "ParseError"
            self.error_message = f"LZMA解压失败: {exc}"
            logger.error(f"LZMA解压失败: {exc}")
            return

        current_time_real = 0.0
        onset = np.zeros(18, dtype=np.int8)
        timeset_real = np.zeros(18, dtype=np.float64)

        intervals_real: list[float] = []
        press_events_real_float: list[tuple[int, float]] = []
        press_times_real_float: list[float] = []
        pressset_real: list[list[float]] = [[] for _ in range(18)]
        play_data: list[ReplayEvent] = []
        replay_data_real: list[tuple[float, int]] = []

        for frame in replay_text.split(","):
            parsed = self._parse_frame(frame)
            if parsed is None:
                continue

            delta_ms, keys_mask = parsed
            current_time_real += delta_ms
            intervals_real.append(delta_ms)

            r_onset = findkey(keys_mask)
            for idx, pressed in enumerate(r_onset):
                if onset[idx] == 0 and pressed == 1:
                    press_times_real_float.append(current_time_real)
                    press_events_real_float.append((idx, current_time_real))

            timeset_real += onset * delta_ms
            for idx, pressed in enumerate(r_onset):
                if onset[idx] != 0 and pressed == 0:
                    duration = float(timeset_real[idx])
                    if duration >= 0:
                        pressset_real[idx].append(duration)
                    timeset_real[idx] = 0.0

            onset = r_onset
            play_data.append(ReplayEvent(int(round(delta_ms)), keys_mask))
            replay_data_real.append((current_time_real, keys_mask))

        self.play_data = play_data
        self.intervals_raw = intervals_real
        self.press_events_raw = press_events_real_float
        self.press_times_raw = press_times_real_float
        self.pressset_raw = pressset_real
        self.replay_data_real = replay_data_real

        self.speed_factor = self._build_speed_factor()
        self._apply_time_conversion(scale=self._resolve_scale_mode())
        self.sample_rate = self._estimate_sample_rate(self.intervals_raw)

        all_durations: list[int] = []
        for col_data in self.pressset:
            all_durations.extend(col_data)
        self.fft_analysis_result = self._perform_fft_analysis(all_durations) if all_durations else None

        valid_pressset = [column for column in self.pressset if len(column) > 5]
        if len(valid_pressset) < 2:
            self.status = "tooFewKeys"
        else:
            self.status = "OK"

        logger.debug(f"按下事件总数(len(self.press_events)): {len(self.press_events)}")
        logger.debug(f"按下事件总数(len(self.press_times))：{len(self.press_times)}")
        logger.debug(f"按下事件时间样本（前10个）：{str(self.press_times[:10])}")
        logger.debug(f"按下事件时间样本（后10个）：{str(self.press_times[-10:])}")

    def convert_times(self, scale: bool = True) -> None:
        """
        summary:
            手动切换 chart 时间转换策略。
        Args:
            scale: True=按速度模组反缩放；False=保持 real 与 chart 一致。
        Returns:
            无。
        """
        if not self.replay_data_real:
            return
        self._apply_time_conversion(scale=bool(scale))

    @staticmethod
    def compress_replay_data(replay_data: list[tuple[float, int]]) -> str:
        """
        summary:
            将绝对时间 replay 数据压缩为 osu 文本帧串。
        Args:
            replay_data: [(time_ms, bitmask)]。
        Returns:
            逗号拼接帧文本。
        """
        if not replay_data:
            return ""

        out: list[str] = []
        prev = 0.0
        for time_ms, mask in replay_data:
            delta = float(time_ms) - prev
            if delta < 0:
                delta = 0.0
            out.append(f"{delta:.3f}|{int(mask)}|0|0")
            prev = float(time_ms)
        return ",".join(out)

    @staticmethod
    def decompress_replay_data(replay_text: str) -> list[tuple[float, int]]:
        """
        summary:
            将 osu 文本帧串解析为绝对时间 replay 数据。
        Args:
            replay_text: 帧文本。
        Returns:
            [(time_ms, bitmask)]。
        """
        current = 0.0
        out: list[tuple[float, int]] = []
        for frame in replay_text.split(","):
            parts = frame.split("|")
            if len(parts) < 4:
                continue
            try:
                delta = float(parts[0])
                mask = int(float(parts[1]))
            except Exception:
                continue
            if delta == -12345:
                continue
            current += max(0.0, delta)
            out.append((current, mask))
        return out

    def to_interlude_replay(
        self,
        use_chart_time: bool = True,
        compressed: bool = False,
    ) -> list[tuple[float, int]] | str:
        """
        summary:
            导出 Interlude 兼容的 ReplayData。
        Args:
            use_chart_time: True 使用 chart 时间，False 使用 real 时间。
            compressed: True 返回压缩文本，False 返回列表。
        Returns:
            ReplayData 列表或压缩字符串。
        """
        replay = self.replay_data_chart if use_chart_time else self.replay_data_real
        if compressed:
            return self.compress_replay_data(replay)
        return list(replay)

    def as_IReplay(self, use_chart_time: bool = True) -> ReplayCursor:
        """
        summary:
            导出 IReplay 风格游标对象。
        Args:
            use_chart_time: True 使用 chart 时间线。
        Returns:
            ReplayCursor 实例。
        """
        replay = self.replay_data_chart if use_chart_time else self.replay_data_real
        return ReplayCursor(replay)

    def get_data(self):
        """
        summary:
            返回回放解析结果，兼容旧字段并补充 real/chart 字段。
        Args:
            无。
        Returns:
            数据字典。
        """
        data = {
            "status": self.status,
            "player_name": self.player_name,
            "mod": self.mod,
            "corrector": getattr(self, "corrector", 1.0),
            "mods": self.mods,
            "score": self.score,
            "accuracy": self.acc,
            "ratio": self.ratio,
            "pressset": self.pressset,
            "press_times": self.press_times,
            "press_times_float": self.press_times_float,
            "press_events": self.press_events,
            "press_events_float": self.press_events_float,
            "press_times_real": self.press_times_real,
            "press_times_real_float": self.press_times_real_float,
            "press_events_real": self.press_events_real,
            "press_events_real_float": self.press_events_real_float,
            "press_times_chart": self.press_times_chart,
            "press_times_chart_float": self.press_times_chart_float,
            "press_events_chart": self.press_events_chart,
            "press_events_chart_float": self.press_events_chart_float,
            "replay_data_real": self.replay_data_real,
            "replay_data_chart": self.replay_data_chart,
            "fft_analysis": None,
            "intervals": self.intervals,
            "intervals_raw": self.intervals_raw,
            "life_bar_graph": self.life_bar_graph,
            "sample_rate": self.sample_rate,
            "timestamp": self.timestamp,
            "file_path": self.file_path,
            "judge": self.judge,
            "speed_factor": self.speed_factor,
            "scale_applied": self.scale_applied,
        }

        if self.fft_analysis_result:
            data["fft_analysis"] = self.fft_analysis_result
        return data

    def is_valid(self) -> bool:
        """
        summary:
            判断回放是否处于可用状态。
        Args:
            无。
        Returns:
            是否有效。
        """
        return self.status in {"OK", "tooFewKeys"}

    def get_summary(self) -> dict:
        """
        summary:
            获取轻量摘要信息。
        Args:
            无。
        Returns:
            摘要字典。
        """
        return {
            "status": self.status,
            "player_name": self.player_name,
            "mods": self.mods,
            "score": self.score,
            "accuracy": round(float(self.acc), 4),
            "sample_rate": self.sample_rate,
            "press_count": len(self.press_events),
        }

    def _perform_fft_analysis(self, durations: list[int]) -> dict:
        if not durations:
            return {
                "peak_frequency": 0,
                "conclusion": "无有效数据",
                "local_snr": 0,
                "global_snr": 0,
                "is_valid_peak": False,
            }

        try:
            from scipy.fft import fft, fftfreq
        except ImportError:
            logger.warning("scipy 未安装，无法使用FFT分析")
            return {
                "peak_frequency": 0,
                "conclusion": "scipy未安装，无法进行FFT分析",
                "local_snr": 0,
                "global_snr": 0,
                "is_valid_peak": False,
            }

        fs = 1000
        n_points = 1024

        signal = np.zeros(n_points, dtype=np.float64)
        counts = Counter(int(round(d)) for d in durations if 0 < d < n_points)
        for ms, count in counts.items():
            signal[ms] = count
        signal = signal - np.mean(signal)

        yf = fft(signal)
        xf = fftfreq(n_points, 1 / fs)[: n_points // 2]
        amplitude = 2.0 / n_points * np.abs(yf[0 : n_points // 2])

        mask = (xf >= 10) & (xf <= 500)
        search_xf = xf[mask]
        search_amp = amplitude[mask]
        if len(search_amp) == 0:
            return {
                "peak_frequency": 0,
                "conclusion": "在10-500Hz范围内未检测到有效峰值",
                "local_snr": 0,
                "global_snr": 0,
                "is_valid_peak": False,
            }

        peak_idx_in_search = int(np.argmax(search_amp))
        est_hz = float(search_xf[peak_idx_in_search])
        max_val = float(search_amp[peak_idx_in_search])

        abs_idx = int(np.argmin(np.abs(xf - est_hz)))
        is_invalid_peak = False
        if abs_idx > 0 and amplitude[abs_idx - 1] > amplitude[abs_idx] and est_hz < 25:
            is_invalid_peak = True

        local_mask = (xf > est_hz - 15) & (xf < est_hz + 15)
        local_avg = float(np.mean(amplitude[local_mask])) if np.any(local_mask) else 0.0
        local_snr = max_val / local_avg if local_avg > 0 else 0.0

        global_avg = float(np.mean(search_amp)) if len(search_amp) else 0.0
        global_snr = max_val / global_avg if global_avg > 0 else 0.0

        if is_invalid_peak or local_snr < 1.7 or global_snr < 3.8 or est_hz > 492:
            conclusion = f">=500Hz (表现接近记录上限，检测峰值: {est_hz:.1f}Hz)"
            is_valid = False
        else:
            conclusion = f"检测到显著峰值: {est_hz:.1f}Hz"
            is_valid = True

        return {
            "peak_frequency": est_hz,
            "conclusion": conclusion,
            "local_snr": float(local_snr),
            "global_snr": float(global_snr),
            "is_valid_peak": is_valid,
        }

    def _parse_mods(self, mod_value: int) -> list[str]:
        if mod_value == 0:
            return ["None"]

        mods: list[str] = []
        for bit_value, mod_name in file_parser_data.MOD_MAPPING.items():
            if bit_value == 0:
                continue
            if mod_value & bit_value:
                mods.append(mod_name)

        if "Nightcore" in mods and "DoubleTime" in mods:
            mods.remove("DoubleTime")
        return mods