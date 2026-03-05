import numpy as np

from ..file.osr_file_parser import osr_file
from ..file.osu_file_parser import osu_file



def findkey(x = 0):
    keyset = [0 for i in range(18)]
    (a, keyset[0]) = (x//2, x%2)
    j = 1
    while a != 0:
        (a, keyset[j]) = (a//2, a%2)
        j += 1
    return np.array(keyset)

def string_to_int(s):
    return int(float(s))

def collect_data(data, new_datum):
    data.append(new_datum)

def match_notes_and_presses(osu: osu_file, osr: osr_file):
    """
    匹配物件和按下事件，返回匹配的列表。
    参数:
        osu: osu文件实例
        osr: osr文件实例
    返回:
        list of (col, delta_t) 差值列表
        list of (col, note_time, press_time) 详细匹配对（可选）
    """
    # 按列整理按下事件
    note_times_by_col = osu.note_times
    press_events = osr.press_events
    max_diff = 188 - 3 * osu.od
    press_by_col = {}
    for col, t in press_events:
        press_by_col.setdefault(col, []).append(t)
    for col in press_by_col:
        press_by_col[col].sort()

    delta_list = []
    matched_pairs = []  # 详细对
    for col in note_times_by_col:
        notes = note_times_by_col[col]
        presses = press_by_col.get(col, [])
        i = j = 0
        while i < len(notes) and j < len(presses):
            diff = presses[j] - notes[i]
            if abs(diff) <= max_diff:
                delta_list.append((col, diff))
                matched_pairs.append((col, notes[i], presses[j]))
                i += 1
                j += 1
            elif presses[j] < notes[i] - max_diff:
                j += 1
            else:
                i += 1
    return delta_list, matched_pairs