import numpy as np

from ..algorithm.utils import string_to_int, collect_data

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

    def get_parsed_data(self):
        return [self.column_count,
                self.columns,
                self.note_starts,
                self.note_ends,
                self.note_types,
                self.od,
                self.GameMode,
                self.status,
                self.LN_ratio
                ]
    
    def process(self):
        with open(self.file_path, "r", encoding='utf-8') as f:
            lines = f.readlines()  # 一次性读取所有行，避免迭代器问题

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

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

    def parse_hit_object(self, object_line):
        params = object_line.split(",")
        if len(params) < 6:
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

            last_param_chunk = params[5].split(":")
            note_end = int(last_param_chunk[0])
            self.note_ends.append(note_end)
        except Exception as e:
            self.status = "Fail"
    
    def get_LN_ratio(self):
        # 计算 LN 比例
        total_notes = len(self.note_types)
        if total_notes == 0:
            return 0.0
        ln_count = sum(1 for t in self.note_types if t == 128)
        return ln_count / total_notes
    
    def get_note_times(self):
        note_times = {}
        for col, t in zip(self.columns, self.note_starts):
            note_times.setdefault(col, []).append(t)
        for col in note_times:
            note_times[col].sort()
        return note_times
    
    def mod_IN(self, gap: float = 150, ln_as_hit_thres: float = 100):
        # 反键处理 (Full LN)
        # 将解析出的列/时间列表按照 reamber.algorithms.generate.full_ln 中的算法进行转换。
        # gap: 相邻按键之间的间隔时间阈值；
        # ln_as_hit_thres: 如果计算出的 ln 长度小于该阈值，则将该按键当作普通 note 处理。
        #
        # 算法流程：
        #   1. 按列将笔记分组并按时间排序。
        #   2. 对于每一列的每个笔记，计算与下一条笔记的时间差 diff。
        #   3. 如果 diff 为 NaN(即本列最后一条)，则保持原有类型；
        #      否则计算 inv_length = diff - gap，若 inv_length >= ln_as_hit_thres，
        #      生成一个长度为 inv_length 的 LN，否则将其转为 hit。
        #   4. 用计算出的列/时间/类型列表替换原有数据。

        # 先按列分组原始数据
        notes_by_col = {}
        for col, start, end, ntype in zip(
            self.columns, self.note_starts, self.note_ends, self.note_types
        ):
            # 长按键的长度为 end-start，普通按键记为 NaN
            length = float(np.nan) if ntype != 128 else end - start
            notes_by_col.setdefault(col, []).append((start, length))

        new_cols = []
        new_starts = []
        new_ends = []
        new_types = []

        # 对每一列分别处理
        for col, notes in notes_by_col.items():
            notes.sort(key=lambda x: x[0])  # 按 offset 排序
            offsets = [n[0] for n in notes]
            lengths = [n[1] for n in notes]

            for idx, offset in enumerate(offsets):
                length = lengths[idx]
                # 计算与下一条笔记的时间差
                if idx + 1 < len(offsets):
                    diff = offsets[idx + 1] - offset
                else:
                    diff = np.nan

                if np.isnan(diff):
                    # 列末尾，保持原类型
                    if np.isnan(length):
                        new_cols.append(col)
                        new_starts.append(offset)
                        new_types.append(1)
                        new_ends.append(offset)
                    else:
                        new_cols.append(col)
                        new_starts.append(offset)
                        new_types.append(128)
                        new_ends.append(offset + length)
                    continue

                inv_len = diff - gap
                if inv_len >= ln_as_hit_thres:
                    # 产生一个长度为 inv_len 的 LN
                    new_cols.append(col)
                    new_starts.append(offset)
                    new_types.append(128)
                    new_ends.append(offset + inv_len)
                else:
                    # 当作 hit 处理
                    new_cols.append(col)
                    new_starts.append(offset)
                    new_types.append(1)
                    new_ends.append(offset)

        # 将 parser 的字段替换成新生成的数据
        self.columns = new_cols
        self.note_starts = new_starts
        self.note_types = new_types
        self.note_ends = new_ends

    def mod_HO(self):
        # 转米处理 (No LN)
        # 将所有长按键转换为普通按键，即将 note_types 中值为 128 的项改为 1，并将 note_ends 中对应项的值改为 0.
        for i in range(len(self.note_types)):
            if self.note_types[i] == 128:
                self.note_types[i] = 1
                self.note_ends[i] = 0