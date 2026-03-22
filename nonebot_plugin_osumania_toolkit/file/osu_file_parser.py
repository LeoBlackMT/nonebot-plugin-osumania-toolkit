import numpy as np
import bisect

from nonebot.log import logger

def string_to_int(s):
    return int(float(s))

def collect_data(data, new_datum):
    data.append(new_datum)


class osu_file:
    def __init__(self, file_path):
        self.file_path = file_path
        self.od = -1
        self.column_count = -1
        self.columns = []
        self.note_starts = []
        self.note_ends = []
        self.note_types = [] # 1 for normal note, 128 for hold note
        self.GameMode = None
        self.status = "init"
        self.LN_ratio = 0.0
        self.note_times = {}
        self.meta_data = {}
        self.breaks = []
        self.object_intervals = []
        self.timing_points = []  # list[tuple[int, float]] -> (time_ms, beat_length_ms)

    def get_parsed_data(self):
        return [self.column_count,
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
                self.object_intervals
                ]
    
    def process(self):
        with open(self.file_path, "r", encoding='utf-8') as f:
            lines = f.readlines()  # 一次性读取所有行，避免迭代器问题

        i = 0
        in_metadata_section = False
        in_events_section = False
        in_timing_section = False
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # 解析 [metadata] 部分
            if line == "[Metadata]":
                in_metadata_section = True
                i += 1
                continue
            if line == "[Events]":
                in_events_section = True
                i += 1
                continue
            if line == "[TimingPoints]":
                in_timing_section = True
                i += 1
                continue
            elif line.startswith("[") and line.endswith("]"):
                in_metadata_section = False
                in_events_section = False
                in_timing_section = False

            if in_metadata_section:
                if ":" in line:
                    key, value = line.split(":", 1)
                    self.meta_data[key.strip()] = value.strip()

            if in_events_section:
                self.parse_event_line(line)

            if in_timing_section:
                self.parse_timing_point_line(line)

            if "OverallDifficulty:" in line:
                try:
                    self.od = float(line.split(':')[1].strip())
                except:
                    pass

            if "CircleSize:" in line:
                try:
                    cs = line.split(':')[1].strip()
                    self.column_count = 10 if cs == '0' else string_to_int(cs)
                except:
                    pass
            
            if "Mode:" in line:
                try:
                    mode = line.split(':')[1].strip()
                    self.GameMode = mode
                    if mode != '3':
                        self.status = "NotMania"
                except:
                    pass

            if "[HitObjects]" in line:
                i += 1
                while i < len(lines):
                    obj_line = lines[i].strip()
                    if not obj_line:  # 跳过空行
                        i += 1
                        continue
                    self.parse_hit_object(obj_line)
                    i += 1
                break

            i += 1
        self.LN_ratio = self.get_LN_ratio()
        self.note_times = self.get_note_times()
        self.object_intervals = self.get_object_intervals()
        if not self.timing_points:
            self.timing_points = [(0, 500.0)]
        self.timing_points.sort(key=lambda x: x[0])
        if self.status not in {"Fail", "NotMania"}:
            self.status = "OK"
        logger.debug(f"谱面物件总数: {len(self.note_starts)}")
        logger.debug(f"谱面最后物件时间: {max(self.note_starts) if self.note_starts else 0} ms")
        logger.debug(f"谱面物件时间样本（前10个）：{str(self.note_starts[:10])}")
        logger.debug(f"谱面物件时间样本（后10个）：{str(self.note_starts[-10:])}")
        # logger.debug("各列物件数量：", {col: len(times) for col, times in self.note_times.items()})

    def parse_event_line(self, event_line):
        if not event_line or event_line.startswith("//"):
            return

        params = [part.strip() for part in event_line.split(",")]
        if len(params) < 3:
            return

        if params[0] not in {"2", "Break"}:
            return

        try:
            break_start = int(float(params[1]))
            break_end = int(float(params[2]))
        except (TypeError, ValueError):
            return

        if break_end > break_start:
            self.breaks.append([break_start, break_end])

    def parse_hit_object(self, object_line):
        params = object_line.split(",")
        if len(params) < 5:
            return

        try:
            x = string_to_int(params[0])
            column_width = int(512 / self.column_count) if self.column_count > 0 else 1
            column = int(x / column_width)
            self.columns.append(column)

            note_start = int(params[2])
            self.note_starts.append(note_start)

            note_type = int(params[3])
            self.note_types.append(note_type)

            # mania 普通 note 通常只有 5 段；LN 会在第 6 段携带结束时间。
            # note_type 的 bit 7 表示 hold (LN)。
            if (note_type & 128) != 0 and len(params) >= 6:
                last_param_chunk = params[5].split(":")
                note_end = int(last_param_chunk[0])
            else:
                note_end = note_start
            self.note_ends.append(note_end)
        except Exception as e:
            self.status = "Fail"

    def parse_timing_point_line(self, timing_line):
        if not timing_line or timing_line.startswith("//"):
            return
        parts = [p.strip() for p in timing_line.split(",")]
        if len(parts) < 2:
            return
        try:
            t = int(float(parts[0]))
            beat_length = float(parts[1])
            uninherited = int(parts[6]) if len(parts) > 6 and parts[6] else 1
            if uninherited == 1 and beat_length > 0:
                self.timing_points.append((t, beat_length))
        except Exception:
            return

    def get_beat_length_at(self, time_ms: float) -> float:
        if not self.timing_points:
            return 500.0
        times = [tp[0] for tp in self.timing_points]
        idx = bisect.bisect_right(times, int(time_ms)) - 1
        if idx < 0:
            return self.timing_points[0][1]
        return self.timing_points[idx][1]
    
    def get_LN_ratio(self):
        # 计算 LN 比例
        total_notes = len(self.note_types)
        if total_notes == 0:
            return 0.0
        ln_count = sum(1 for t in self.note_types if (t & 128) != 0)
        return ln_count / total_notes
    
    def get_column_count(self):
        return self.column_count
    
    def get_note_times(self):
        note_times = {}
        for col, t in zip(self.columns, self.note_starts):
            note_times.setdefault(col, []).append(t)
        for col in note_times:
            note_times[col].sort()
        return note_times

    def get_object_intervals(self):
        if not self.note_starts:
            return []

        sorted_starts = sorted(int(start) for start in self.note_starts)
        intervals = []
        prev_start = None
        for start_time in sorted_starts:
            interval = 0 if prev_start is None else start_time - prev_start
            intervals.append([start_time, interval])
            prev_start = start_time

        intervals.sort(key=lambda item: (-item[1], item[0]))
        return intervals
    
    def mod_IN(self):
        # 官方 ManiaModInvert 等价逻辑：
        # 1) 对每列收集事件点（普通键头、LN头、LN尾）并排序。
        # 2) 对每对相邻事件生成一条 LN。
        # 3) LN 时长 = max(delta/2, delta - beatLength/4)，beatLength 取后一事件时刻。
        notes_by_col = {}
        for col, start, end, ntype in zip(self.columns, self.note_starts, self.note_ends, self.note_types):
            notes_by_col.setdefault(col, []).append((start, end, ntype))

        new_objects = []
        for col, notes in notes_by_col.items():
            locations = []
            for start, end, ntype in notes:
                if (ntype & 128) != 0:
                    locations.append(float(start))
                    locations.append(float(end))
                else:
                    locations.append(float(start))

            locations.sort()
            for i in range(len(locations) - 1):
                start_time = locations[i]
                next_time = locations[i + 1]
                duration = next_time - start_time
                beat_length = self.get_beat_length_at(next_time)
                duration = max(duration / 2.0, duration - beat_length / 4.0)
                end_time = start_time + duration
                end_time_int = int(round(end_time))
                start_time_int = int(round(start_time))
                if end_time_int <= start_time_int:
                    end_time_int = start_time_int + 1
                new_objects.append((start_time_int, col, end_time_int))

        new_objects.sort(key=lambda x: (x[0], x[1]))

        self.columns = [obj[1] for obj in new_objects]
        self.note_starts = [obj[0] for obj in new_objects]
        self.note_types = [128 for _ in new_objects]
        self.note_ends = [obj[2] for obj in new_objects]
        self.breaks = []
        self.LN_ratio = self.get_LN_ratio()
        self.note_times = self.get_note_times()
        self.object_intervals = self.get_object_intervals()

    def mod_HO(self):
        # 转米处理 (No LN)
        # 将所有长按键转换为普通按键，即将 note_types 中值为 128 的项改为 1，并将 note_ends 中对应项的值改为 0.
        for i in range(len(self.note_types)):
            if (self.note_types[i] & 128) != 0:
                self.note_types[i] = 1
                self.note_ends[i] = 0
        self.LN_ratio = self.get_LN_ratio()
        self.note_times = self.get_note_times()
        self.object_intervals = self.get_object_intervals()