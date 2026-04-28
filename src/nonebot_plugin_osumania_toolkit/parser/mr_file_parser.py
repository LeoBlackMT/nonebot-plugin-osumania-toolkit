from __future__ import annotations

import os
import struct
from typing import List, Optional, Tuple

from nonebot.log import logger

from .osr_file_parser import ReplayCursor, ReplayEvent

# 参考实现路径：
# - prelude/src/Gameplay/Replays/ReplayFormat.fs


class mr_file:
    """
    summary:
        解析 Malody .mr 回放并导出 Interlude 兼容的 replay 结构。
    Args:
        file_path: .mr 文件路径。
        assume_replay_times_scaled: 兼容参数，占位不用（.mr 默认视为 chart 时间）。
        keep_float_times: 是否保留浮点时间。
        log_level_override: 兼容参数，占位不用。
    Returns:
        无。
    """

    def __init__(
        self,
        file_path: str,
        assume_replay_times_scaled: Optional[bool] = None,
        keep_float_times: bool = True,
        log_level_override: Optional[str] = None,
    ):
        self.file_path = str(file_path)
        self.status = "init"
        self.error_message = ""

        self.assume_replay_times_scaled = assume_replay_times_scaled
        self.keep_float_times = keep_float_times
        self.log_level_override = log_level_override

        self.magic = ""
        self.version = (0, 0, 0)
        self.beatmap_md5 = ""
        self.difficulty_name = ""
        self.song_title = ""
        self.song_artist = ""

        self.score = 0
        self.max_combo = 0
        self.best_count = 0
        self.cool_count = 0
        self.good_count = 0
        self.miss_count = 0
        self.unknown_count = 0
        self.mods_flags = 0
        self.rank = 0
        self.timestamp = 0

        self.actions: list[tuple[int, int, int]] = []

        self.speed_factor = 1.0
        self.corrector = 1.0

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

        try:
            self._parse()
            if self.status == "OK":
                self._build_replay_views()
        except Exception as exc:
            self.status = "ParseError"
            self.error_message = str(exc)
            logger.error(f"初始化 mr_file 失败: {exc}")

    def _read_int32(self, data: bytes, offset: int) -> tuple[int, int]:
        if offset + 4 > len(data):
            raise ValueError("文件过早结束，无法读取 int32")
        value = struct.unpack_from("<i", data, offset)[0]
        return value, offset + 4

    def _read_byte(self, data: bytes, offset: int) -> tuple[int, int]:
        if offset + 1 > len(data):
            raise ValueError("文件过早结束，无法读取 byte")
        return data[offset], offset + 1

    def _read_string(self, data: bytes, offset: int) -> Tuple[str, int]:
        length, offset = self._read_int32(data, offset)

        if length < 0:
            logger.warning(f"字符串长度为负: {length}，按空字符串处理")
            return "", offset
        if length == 0:
            return "", offset
        if length > 1_000_000:
            raise ValueError(f"字符串长度异常: {length}")
        if offset + length > len(data):
            raise ValueError("文件过早结束，字符串数据不完整")

        raw = data[offset : offset + length]
        offset += length
        try:
            return raw.decode("utf-8"), offset
        except UnicodeDecodeError:
            logger.warning("检测到非UTF-8字符串，已使用 replace 策略解码")
            return raw.decode("utf-8", errors="replace"), offset

    def _parse(self) -> None:
        if not os.path.exists(self.file_path):
            self.status = "FileNotFound"
            self.error_message = "文件不存在"
            logger.error(f"文件不存在: {self.file_path}")
            return

        if not self.file_path.lower().endswith(".mr"):
            self.status = "InvalidFileType"
            self.error_message = "扩展名不是 .mr"
            logger.error(f"文件不是 .mr 格式: {self.file_path}")
            return

        file_size = os.path.getsize(self.file_path)
        if file_size < 100:
            self.status = "FileTooSmall"
            self.error_message = "文件过小"
            logger.error(f"文件过小: {file_size} 字节")
            return

        with open(self.file_path, "rb") as f:
            data = f.read()
        if len(data) < 100:
            self.status = "ParseError"
            self.error_message = "文件数据过少"
            logger.error("文件数据过少")
            return

        offset = 0
        try:
            self.magic, offset = self._read_string(data, offset)
            if self.magic != "mr format head":
                self.status = "InvalidMagic"
                self.error_message = f"无效文件头: {self.magic}"
                logger.error(f"无效文件头: {self.magic}")
                return

            patch, offset = self._read_byte(data, offset)
            minor, offset = self._read_byte(data, offset)
            major, offset = self._read_byte(data, offset)
            _, offset = self._read_byte(data, offset)
            self.version = (major, minor, patch)
            if major > 4 or minor > 3:
                logger.warning(f"不常见版本: v{major}.{minor}.{patch}")

            self.beatmap_md5, offset = self._read_string(data, offset)
            self.difficulty_name, offset = self._read_string(data, offset)
            self.song_title, offset = self._read_string(data, offset)
            self.song_artist, offset = self._read_string(data, offset)

            self.score, offset = self._read_int32(data, offset)
            self.max_combo, offset = self._read_int32(data, offset)
            self.best_count, offset = self._read_int32(data, offset)
            self.cool_count, offset = self._read_int32(data, offset)
            self.good_count, offset = self._read_int32(data, offset)
            self.miss_count, offset = self._read_int32(data, offset)
            self.unknown_count, offset = self._read_int32(data, offset)
            self.mods_flags, offset = self._read_int32(data, offset)
            self.rank, offset = self._read_int32(data, offset)

            data_magic, offset = self._read_string(data, offset)
            if data_magic != "mr data":
                self.status = "InvalidDataMagic"
                self.error_message = f"无效数据段标识: {data_magic}"
                logger.error(f"无效数据段标识: {data_magic}")
                return

            _, offset = self._read_int32(data, offset)

            action_count, offset = self._read_int32(data, offset)
            if action_count < 0:
                self.status = "InvalidActionCount"
                self.error_message = f"动作数量非法: {action_count}"
                logger.error(f"动作数量非法: {action_count}")
                return
            if action_count > 1_000_000:
                logger.warning(f"动作数量异常大: {action_count}")

            _, offset = self._read_byte(data, offset)
            self.timestamp, offset = self._read_int32(data, offset)
            _, offset = self._read_int32(data, offset)

            invalid_actions = 0
            parsed_actions: list[tuple[int, int, int]] = []
            for idx in range(action_count):
                time_ms, offset = self._read_int32(data, offset)
                action, offset = self._read_byte(data, offset)
                column, offset = self._read_byte(data, offset)

                if action not in (1, 2):
                    invalid_actions += 1
                    logger.warning(f"动作{idx + 1}: 无效 action={action}")
                    continue
                if column >= 18:
                    invalid_actions += 1
                    logger.warning(f"动作{idx + 1}: 无效 column={column}")
                    continue
                if time_ms < 0:
                    invalid_actions += 1
                    logger.warning(f"动作{idx + 1}: 负时间戳 {time_ms}")
                    continue

                parsed_actions.append((time_ms, action, column))

            self.actions = parsed_actions
            if invalid_actions > 0:
                logger.warning(f"发现 {invalid_actions} 个无效动作")

            if not self.actions:
                self.status = "NoValidActions"
                self.error_message = "没有有效动作"
                logger.error("没有有效动作")
                return

            self.status = "OK"
            logger.debug(f"成功解析 .mr 文件: {len(self.actions)} 个动作")

        except ValueError as exc:
            self.status = "ParseError"
            self.error_message = str(exc)
            logger.error(f"解析 .mr 失败: {exc}")
        except struct.error as exc:
            self.status = "StructError"
            self.error_message = str(exc)
            logger.error(f"二进制解析失败: {exc}")
        except UnicodeDecodeError as exc:
            self.status = "UnicodeError"
            self.error_message = str(exc)
            logger.error(f"字符串解码失败: {exc}")

    def _build_replay_views(self) -> None:
        # .mr 常见时间戳即 1.0 chart 时间，但仍保留 real/chart 双字段统一接口。
        actions = sorted(self.actions, key=lambda item: item[0])
        if not actions:
            return

        current_state = [False] * 18
        pressed_start = [None] * 18

        prev_time = None
        intervals_raw: list[float] = []
        replay_data: list[tuple[float, int]] = []
        play_data: list[ReplayEvent] = []

        press_events_real_float: list[tuple[int, float]] = []
        press_times_real_float: list[float] = []
        pressset_real: list[list[float]] = [[] for _ in range(18)]

        for time_ms, action, col in actions:
            t = float(time_ms)

            if action == 1:
                if not current_state[col]:
                    current_state[col] = True
                    pressed_start[col] = t
                    press_times_real_float.append(t)
                    press_events_real_float.append((col, t))
            elif action == 2:
                if current_state[col]:
                    current_state[col] = False
                    if pressed_start[col] is not None:
                        duration = t - float(pressed_start[col])
                        if duration >= 0:
                            pressset_real[col].append(duration)
                    pressed_start[col] = None

            keys_mask = 0
            for idx in range(18):
                if current_state[idx]:
                    keys_mask |= (1 << idx)

            if prev_time is None:
                delta = t
            else:
                delta = max(0.0, t - prev_time)
            prev_time = t

            intervals_raw.append(delta)
            replay_data.append((t, keys_mask))
            play_data.append(ReplayEvent(int(round(delta)), keys_mask))

        self.pressset_raw = pressset_real
        self.intervals_raw = intervals_raw
        self.press_events_raw = press_events_real_float
        self.press_times_raw = press_times_real_float
        self.replay_data_real = replay_data
        self.play_data = play_data

        self.corrector = 1.0
        self.speed_factor = 1.0

        self.press_times_real_float = list(self.press_times_raw)
        self.press_events_real_float = list(self.press_events_raw)
        self.press_times_real = [int(round(t)) for t in self.press_times_real_float]
        self.press_events_real = [(c, int(round(t))) for c, t in self.press_events_real_float]

        self.press_times_chart_float = list(self.press_times_real_float)
        self.press_events_chart_float = list(self.press_events_real_float)
        self.press_times_chart = list(self.press_times_real)
        self.press_events_chart = list(self.press_events_real)
        self.replay_data_chart = list(self.replay_data_real)

        self.intervals = [int(round(v)) for v in self.intervals_raw]
        self.pressset = [
            [int(round(d)) for d in durations] if durations else []
            for durations in self.pressset_raw
        ]

        self.press_times_float = list(self.press_times_chart_float)
        self.press_events_float = list(self.press_events_chart_float)
        self.press_times = list(self.press_times_chart)
        self.press_events = list(self.press_events_chart)

        if not self.keep_float_times:
            self.press_times_real_float = [float(t) for t in self.press_times_real]
            self.press_events_real_float = [(c, float(t)) for c, t in self.press_events_real]
            self.press_times_chart_float = [float(t) for t in self.press_times_chart]
            self.press_events_chart_float = [(c, float(t)) for c, t in self.press_events_chart]
            self.press_times_float = [float(t) for t in self.press_times]
            self.press_events_float = [(c, float(t)) for c, t in self.press_events]

    def to_interlude_replay(
        self,
        use_chart_time: bool = True,
        compressed: bool = False,
    ) -> list[tuple[float, int]] | str:
        """
        summary:
            导出 Interlude 可用 ReplayData。
        Args:
            use_chart_time: True 使用 chart 时间。
            compressed: True 返回压缩文本。
        Returns:
            ReplayData 列表或压缩字符串。
        """
        replay = self.replay_data_chart if use_chart_time else self.replay_data_real
        if not compressed:
            return list(replay)
        return self.compress_replay_data(replay)

    @staticmethod
    def compress_replay_data(replay_data: list[tuple[float, int]]) -> str:
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

    def as_IReplay(self, use_chart_time: bool = True) -> ReplayCursor:
        """
        summary:
            导出 IReplay 风格游标对象。
        Args:
            use_chart_time: True 使用 chart 时间线。
        Returns:
            ReplayCursor。
        """
        replay = self.replay_data_chart if use_chart_time else self.replay_data_real
        return ReplayCursor(replay)

    def get_data(self):
        """
        summary:
            获取解析结果字典。
        Args:
            无。
        Returns:
            数据字典。
        """
        return {
            "status": self.status,
            "magic": self.magic,
            "version": self.version,
            "beatmap_md5": self.beatmap_md5,
            "difficulty_name": self.difficulty_name,
            "song_title": self.song_title,
            "song_artist": self.song_artist,
            "score": self.score,
            "max_combo": self.max_combo,
            "best_count": self.best_count,
            "cool_count": self.cool_count,
            "good_count": self.good_count,
            "miss_count": self.miss_count,
            "unknown_count": self.unknown_count,
            "mods_flags": self.mods_flags,
            "rank": self.rank,
            "timestamp": self.timestamp,
            "actions": self.actions,
            "corrector": self.corrector,
            "speed_factor": self.speed_factor,
            "pressset": self.pressset,
            "pressset_raw": self.pressset_raw,
            "intervals": self.intervals,
            "intervals_raw": self.intervals_raw,
            "press_times": self.press_times,
            "press_times_float": self.press_times_float,
            "press_times_raw": self.press_times_raw,
            "press_events": self.press_events,
            "press_events_float": self.press_events_float,
            "press_events_raw": self.press_events_raw,
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
        }

    def get_summary(self) -> dict:
        """
        summary:
            获取结果摘要。
        Args:
            无。
        Returns:
            摘要字典。
        """
        return {
            "status": self.status,
            "player": "Malody Player",
            "song": f"{self.song_title} - {self.song_artist}",
            "difficulty": self.difficulty_name,
            "score": self.score,
            "accuracy": self.calculate_accuracy(),
            "max_combo": self.max_combo,
            "judge": {
                "best": self.best_count,
                "cool": self.cool_count,
                "good": self.good_count,
                "miss": self.miss_count,
            },
            "mods": self.get_mods_list(),
            "action_count": len(self.actions),
            "timestamp": self.timestamp,
        }

    def calculate_accuracy(self) -> float:
        """
        summary:
            计算 Malody acc。
        Args:
            无。
        Returns:
            acc。
        """
        total_notes = self.best_count + self.cool_count + self.good_count + self.miss_count
        if total_notes == 0:
            return 0.0
        accuracy = (
            (self.best_count * 100 + self.cool_count * 75 + self.good_count * 40)
            / (total_notes * 100)
            * 100
        )
        return round(accuracy, 2)

    def get_mods_list(self) -> List[str]:
        """
        summary:
            按位掩码解析 Malody mods。
        Args:
            无。
        Returns:
            mod 名称列表。
        """
        mods: list[str] = []
        mod_mapping = {
            1: "Fair",
            2: "Luck",
            3: "Flip",
            4: "Const",
            5: "Dash",
            6: "Rush",
            7: "Hide",
            9: "Slow",
            10: "Death",
        }
        for bit, mod_name in mod_mapping.items():
            if self.mods_flags & (1 << (bit - 1)):
                mods.append(mod_name)
        return mods

    def is_valid(self) -> bool:
        """
        summary:
            判断对象是否可用。
        Args:
            无。
        Returns:
            是否有效。
        """
        return self.status == "OK" and len(self.actions) > 0

    def get_action_stats(self) -> dict:
        """
        summary:
            统计动作分布。
        Args:
            无。
        Returns:
            统计字典。
        """
        if not self.actions:
            return {}

        times = [a[0] for a in self.actions]
        action_values = [a[1] for a in self.actions]
        columns = [a[2] for a in self.actions]

        return {
            "total_actions": len(self.actions),
            "key_down_count": action_values.count(1),
            "key_up_count": action_values.count(2),
            "min_time": min(times) if times else 0,
            "max_time": max(times) if times else 0,
            "duration_ms": max(times) - min(times) if len(times) >= 2 else 0,
            "unique_columns": len(set(columns)),
            "column_distribution": {col: columns.count(col) for col in set(columns)},
        }