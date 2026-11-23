from __future__ import annotations

from typing import Any
from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class LaneChart:
    column_count: int
    od: float
    note_count: int
    note_starts: np.ndarray
    note_ends: np.ndarray
    columns: np.ndarray
    is_hold: np.ndarray
    slot_note: np.ndarray
    slot_part: np.ndarray
    slot_start: np.ndarray
    slot_count: np.ndarray


def build_lane_chart(chart: Any) -> LaneChart:
    """从 ``osu_file`` 构建 LaneAcc 需要的定长数组模型。"""
    column_count = int(getattr(chart, "column_count", 0) or 0)
    if column_count < 4 or column_count > 18:
        raise ValueError("LaneAcc 仅支持 4–18K 谱面")
    columns = np.asarray(getattr(chart, "columns", []) or [], dtype=np.int32)
    starts = np.asarray(getattr(chart, "note_starts", []) or [], dtype=np.float64)
    ends = np.asarray(getattr(chart, "note_ends", []) or [], dtype=np.float64)
    types = np.asarray(getattr(chart, "note_types", []) or [], dtype=np.int32)
    note_count = min(len(columns), len(starts), len(ends), len(types))
    if note_count <= 0:
        raise ValueError("LaneAcc 谱面没有物件")
    columns = columns[:note_count]
    starts = starts[:note_count]
    ends = ends[:note_count]
    types = types[:note_count]
    is_hold = (types & 128) != 0

    slots_by_col: list[list[tuple[int, int, float]]] = [[] for _ in range(column_count)]
    for note in range(note_count):
        col = int(columns[note])
        if col < 0 or col >= column_count:
            raise ValueError("LaneAcc 谱面列号越界")
        slots_by_col[col].append((note, 0, float(starts[note])))
        if bool(is_hold[note]):
            slots_by_col[col].append((note, 1, float(ends[note])))

    total_slots = sum(len(items) for items in slots_by_col)
    slot_note = np.empty(total_slots, dtype=np.int32)
    slot_part = np.empty(total_slots, dtype=np.uint8)
    slot_start = np.empty(column_count + 1, dtype=np.int32)
    slot_count = np.empty(column_count, dtype=np.int32)

    cursor = 0
    for col, items in enumerate(slots_by_col):
        items.sort(key=lambda item: (item[2], item[1]))
        slot_start[col] = cursor
        slot_count[col] = len(items)
        for note, part, _time in items:
            slot_note[cursor] = note
            slot_part[cursor] = part
            cursor += 1
    slot_start[column_count] = cursor

    od = float(getattr(chart, "od", 8.0) or 8.0)
    return LaneChart(
        column_count=column_count,
        od=od,
        note_count=note_count,
        note_starts=starts,
        note_ends=ends,
        columns=columns,
        is_hold=is_hold,
        slot_note=slot_note,
        slot_part=slot_part,
        slot_start=slot_start,
        slot_count=slot_count,
    )


def hand_groups(
    column_count: int, space_mode: str = "independent"
) -> dict[str, tuple[int, int] | None]:
    """4K–18K 左右手分组；奇数键中列默认独立、不计入左右手。"""
    mid = column_count // 2
    odd = column_count % 2 == 1
    if odd and space_mode == "independent":
        return {
            "left": (0, mid),
            "space": (mid, mid + 1),
            "right": (mid + 1, column_count),
        }
    if odd and space_mode == "left":
        return {"left": (0, mid + 1), "space": None, "right": (mid + 1, column_count)}
    if odd and space_mode == "right":
        return {"left": (0, mid), "space": None, "right": (mid, column_count)}
    return {"left": (0, mid), "space": None, "right": (mid, column_count)}
