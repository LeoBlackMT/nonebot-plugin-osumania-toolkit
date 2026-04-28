from __future__ import annotations

import bisect
from pathlib import Path
from typing import Optional

from nonebot.log import logger

# 参考实现路径：
# - prelude/src/Gameplay/Scoring/HitMechanics.fs
# - prelude/src/Gameplay/Scoring/Scoring.fs


NOTE_NORMAL = 1
NOTE_HOLD_HEAD = 2
NOTE_HOLD_TAIL = 3


def string_to_int(value: str) -> int:
    """
    summary:
        将字符串安全转换为整数。
    Args:
        value: 待转换字符串。
    Returns:
        转换后的整数。
    """
    return int(float(value))


def collect_data(data: list, new_datum) -> None:
    """
    summary:
        兼容旧接口的简单追加函数。
    Args:
        data: 目标列表。
        new_datum: 待追加项。
    Returns:
        无。
    """
    data.append(new_datum)


class osu_file:
    """
    summary:
        解析 .osu 谱面并提供与旧版本兼容的数据字段，同时导出 Interlude 风格 note row 表示。
    Args:
        file_path: 谱面路径。
        assume_replay_times_scaled: 兼容参数，占位不用。
        keep_float_times: 兼容参数，占位不用。
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
        self.assume_replay_times_scaled = assume_replay_times_scaled
        self.keep_float_times = keep_float_times
        self.log_level_override = log_level_override

        self.od = -1.0
        self.column_count = -1
        self.columns: list[int] = []
        self.note_starts: list[int] = []
        self.note_ends: list[int] = []
        self.note_types: list[int] = []
        self.GameMode: str | None = None
        self.status = "init"
        self.error_message = ""

        self.LN_ratio = 0.0
        self.note_times: dict[int, list[int]] = {}
        self.meta_data: dict[str, str] = {}
        self.breaks: list[list[int]] = []
        self.object_intervals: list[list[int]] = []
        self.timing_points: list[tuple[int, float]] = []
        self.note_rows: list[tuple[int, list[int]]] = []
        self._timing_index: list[int] = []

    def _reset_collections(self) -> None:
        self.columns.clear()
        self.note_starts.clear()
        self.note_ends.clear()
        self.note_types.clear()
        self.note_times.clear()
        self.meta_data.clear()
        self.breaks.clear()
        self.object_intervals.clear()
        self.timing_points.clear()
        self.note_rows.clear()
        self._timing_index.clear()

    def _read_lines(self, path: Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="ignore").splitlines()

    def _finalize(self) -> None:
        self.LN_ratio = self.get_LN_ratio()
        self.note_times = self.get_note_times()
        self.object_intervals = self.get_object_intervals()

        if not self.timing_points:
            self.timing_points = [(0, 500.0)]
        self.timing_points.sort(key=lambda item: item[0])
        self._timing_index = [item[0] for item in self.timing_points]

        self.note_rows = self._build_note_rows()

        if self.status not in {"Fail", "NotMania"}:
            self.status = "OK"

        logger.debug(f"谱面物件总数: {len(self.note_starts)}")
        logger.debug(f"谱面最后物件时间: {max(self.note_starts) if self.note_starts else 0} ms")
        logger.debug(f"谱面物件时间样本（前10个）：{str(self.note_starts[:10])}")
        logger.debug(f"谱面物件时间样本（后10个）：{str(self.note_starts[-10:])}")

    def _build_note_rows(self) -> list[tuple[int, list[int]]]:
        if self.column_count <= 0:
            return []

        event_map: dict[int, list[tuple[int, int]]] = {}
        for col, start, end, note_type in zip(
            self.columns, self.note_starts, self.note_ends, self.note_types
        ):
            if col < 0 or col >= self.column_count:
                continue

            if (note_type & 128) != 0:
                tail_time = max(start + 1, end)
                event_map.setdefault(start, []).append((col, NOTE_HOLD_HEAD))
                event_map.setdefault(tail_time, []).append((col, NOTE_HOLD_TAIL))
            else:
                event_map.setdefault(start, []).append((col, NOTE_NORMAL))

        rows: list[tuple[int, list[int]]] = []
        for time_ms in sorted(event_map.keys()):
            row = [0] * self.column_count
            for col, note_kind in event_map[time_ms]:
                if 0 <= col < self.column_count:
                    row[col] = max(row[col], note_kind)
            rows.append((int(time_ms), row))
        return rows

    def get_parsed_data(self):
        """
            兼容旧版本的数组式返回。
        """
        return [
            self.column_count,
            self.columns,
            self.note_starts,
            self.note_ends,
            self.note_types,
            self.od,
            self.GameMode,
            self.status,
            self.LN_ratio,
            self.meta_data,
            self.breaks,
            self.object_intervals,
        ]

    def process(self) -> None:
        """
        summary:
            解析 .osu 内容并填充对象字段。
        """
        self._reset_collections()
        self.status = "init"
        self.error_message = ""

        path = Path(self.file_path)
        if not path.exists() or not path.is_file():
            self.status = "Fail"
            self.error_message = "谱面文件不存在"
            logger.warning(f"谱面文件不存在: {self.file_path}")
            return

        try:
            lines = self._read_lines(path)
        except Exception as exc:
            self.status = "Fail"
            self.error_message = f"读取失败: {exc}"
            logger.error(f"读取谱面失败: {exc}")
            return

        section = ""
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                continue

            if section == "metadata" and ":" in line:
                key, value = line.split(":", 1)
                self.meta_data[key.strip()] = value.strip()

            if section == "events":
                self.parse_event_line(line)
            elif section == "timingpoints":
                self.parse_timing_point_line(line)
            elif section == "hitobjects":
                self.parse_hit_object(line)

            if ":" in line:
                self._parse_key_value_line(line)

        self._finalize()

    def _parse_key_value_line(self, line: str) -> None:
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        try:
            if key == "OverallDifficulty":
                self.od = float(value)
            elif key == "CircleSize":
                self.column_count = 10 if value == "0" else string_to_int(value)
            elif key == "Mode":
                self.GameMode = value
                if value != "3":
                    self.status = "NotMania"
        except Exception:
            return

    def parse_event_line(self, event_line: str) -> None:
        """
        summary:
            解析 [Events] 中的 break 行。
        Args:
            event_line: 原始行文本。
        Returns:
            无。
        """
        if not event_line or event_line.startswith("//"):
            return

        params = [part.strip() for part in event_line.split(",")]
        if len(params) < 3 or params[0] not in {"2", "Break"}:
            return

        try:
            break_start = int(float(params[1]))
            break_end = int(float(params[2]))
        except (TypeError, ValueError):
            return

        if break_end > break_start:
            self.breaks.append([break_start, break_end])

    def parse_hit_object(self, object_line: str) -> None:
        """
        summary:
            解析 [HitObjects] 单行并写入列、起止时间、类型。
        Args:
            object_line: HitObject 原始文本。
        Returns:
            无。
        """
        if not object_line or object_line.startswith("//"):
            return

        params = object_line.split(",")
        if len(params) < 5:
            return

        try:
            x = string_to_int(params[0])
            if self.column_count > 0:
                column = int((x * self.column_count) / 512)
                column = max(0, min(column, self.column_count - 1))
            else:
                column = 0

            note_start = int(float(params[2]))
            note_type = int(params[3])
            note_end = note_start

            if (note_type & 128) != 0 and len(params) >= 6:
                end_token = params[5].split(":", 1)[0]
                note_end = int(float(end_token))
                if note_end < note_start:
                    note_end = note_start

            self.columns.append(column)
            self.note_starts.append(note_start)
            self.note_types.append(note_type)
            self.note_ends.append(note_end)
        except Exception:
            self.status = "Fail"
            self.error_message = "HitObject 解析失败"

    def parse_timing_point_line(self, timing_line: str) -> None:
        """
        summary:
            解析 [TimingPoints]，仅保留红线（uninherited=1）。
        Args:
            timing_line: TimingPoint 原始文本。
        Returns:
            无。
        """
        if not timing_line or timing_line.startswith("//"):
            return

        parts = [part.strip() for part in timing_line.split(",")]
        if len(parts) < 2:
            return

        try:
            time_ms = int(float(parts[0]))
            beat_length = float(parts[1])
            uninherited = int(parts[6]) if len(parts) > 6 and parts[6] else 1
            if uninherited == 1 and beat_length > 0:
                self.timing_points.append((time_ms, beat_length))
        except Exception:
            return

    def get_beat_length_at(self, time_ms: float) -> float:
        """
        summary:
            获取给定时刻生效的 beatLength(ms)。
        Args:
            time_ms: 查询时间。
        Returns:
            beatLength 数值。
        """
        if not self.timing_points:
            return 500.0

        if not self._timing_index:
            self._timing_index = [item[0] for item in self.timing_points]

        idx = bisect.bisect_right(self._timing_index, int(time_ms)) - 1
        if idx < 0:
            return self.timing_points[0][1]
        return self.timing_points[idx][1]

    def get_LN_ratio(self) -> float:
        """
        summary:
            计算 LN 占比。
        Args:
            无。
        Returns:
            LN 数量 / 物件总量。
        """
        total_notes = len(self.note_types)
        if total_notes == 0:
            return 0.0
        ln_count = sum(1 for note_type in self.note_types if (note_type & 128) != 0)
        return ln_count / total_notes

    def get_column_count(self) -> int:
        """
        summary:
            获取列数。
        Args:
            无。
        Returns:
            列数。
        """
        return self.column_count

    def get_note_times(self) -> dict[int, list[int]]:
        """
        summary:
            获取每列起始 note 时间数组。
        Args:
            无。
        Returns:
            列到时间列表的映射。
        """
        note_times: dict[int, list[int]] = {}
        for col, start in zip(self.columns, self.note_starts):
            note_times.setdefault(col, []).append(start)
        for col in note_times:
            note_times[col].sort()
        return note_times

    def get_object_intervals(self) -> list[list[int]]:
        """
        summary:
            计算物件间隔并按间隔降序排序（保持旧行为）。
        Args:
            无。
        Returns:
            [起始时间, 与上一个物件的间隔] 列表。
        """
        if not self.note_starts:
            return []

        sorted_starts = sorted(int(start) for start in self.note_starts)
        intervals: list[list[int]] = []
        prev_start: int | None = None
        for start_time in sorted_starts:
            interval = 0 if prev_start is None else start_time - prev_start
            intervals.append([start_time, interval])
            prev_start = start_time

        intervals.sort(key=lambda item: (-item[1], item[0]))
        return intervals

    def mod_IN(self) -> None:
        """
        summary:
            将谱面转换为反键。
        Args:
            无。
        Returns:
            无。
        """
        notes_by_col: dict[int, list[tuple[int, int, int]]] = {}
        for col, start, end, note_type in zip(
            self.columns, self.note_starts, self.note_ends, self.note_types
        ):
            notes_by_col.setdefault(col, []).append((start, end, note_type))

        new_objects: list[tuple[int, int, int]] = []
        for col, notes in notes_by_col.items():
            locations: list[float] = []
            for start, end, note_type in notes:
                locations.append(float(start))
                if (note_type & 128) != 0:
                    locations.append(float(end))

            locations.sort()
            for idx in range(len(locations) - 1):
                start_time = locations[idx]
                next_time = locations[idx + 1]
                duration = next_time - start_time
                if duration <= 0:
                    continue

                beat_length = self.get_beat_length_at(next_time)
                duration = max(duration / 2.0, duration - beat_length / 4.0)
                start_time_int = int(round(start_time))
                end_time_int = int(round(start_time + duration))
                if end_time_int <= start_time_int:
                    end_time_int = start_time_int + 1
                new_objects.append((start_time_int, col, end_time_int))

        new_objects.sort(key=lambda item: (item[0], item[1]))

        self.columns = [item[1] for item in new_objects]
        self.note_starts = [item[0] for item in new_objects]
        self.note_ends = [item[2] for item in new_objects]
        self.note_types = [128 for _ in new_objects]

        self.breaks = []
        self.LN_ratio = self.get_LN_ratio()
        self.note_times = self.get_note_times()
        self.object_intervals = self.get_object_intervals()
        self.note_rows = self._build_note_rows()

    def mod_HO(self) -> None:
        """
        summary:
            将所有 LN 转为普通 note（去除长按尾判定）。
        Args:
            无。
        Returns:
            无。
        """
        for idx in range(len(self.note_types)):
            if (self.note_types[idx] & 128) != 0:
                self.note_types[idx] = 1
                self.note_ends[idx] = 0

        self.LN_ratio = self.get_LN_ratio()
        self.note_times = self.get_note_times()
        self.object_intervals = self.get_object_intervals()
        self.note_rows = self._build_note_rows()

    def to_interlude_notes(self) -> tuple[list[tuple[int, list[int]]], int, list[tuple[int, float]]]:
        """
        summary:
            导出 Interlude 兼容的谱面核心结构。
        Args:
            无。
        Returns:
            (note_rows, keys, timing_points)。
        """
        return self.note_rows, max(0, self.column_count), list(self.timing_points)

    def to_TimeArray(self) -> list[tuple[int, list[int]]]:
        """
        summary:
            导出 TimeArray 等价表示。
        Args:
            无。
        Returns:
            按时间排序的 (time_ms, note_row) 列表。
        """
        return list(self.note_rows)

    def to_hitflagdata(self) -> list[tuple[int, list[int]]]:
        """
        summary:
            导出可映射到 HitFlagData 的 NoteRow 数据。
        Args:
            无。
        Returns:
            与 to_TimeArray 相同结构。
        """
        return self.to_TimeArray()