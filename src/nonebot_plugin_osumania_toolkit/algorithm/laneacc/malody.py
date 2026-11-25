from __future__ import annotations

from typing import Any
from dataclasses import dataclass

from .chart import LaneChart

_MALODY_WEIGHTS = (100.0, 75.0, 40.0, 0.0)  # BEST / COOL / GOOD / MISS
_MOBILE_WINDOWS = (45.0, 85.0, 130.0, 170.0)  # 4.3.7 mobile default (Judge C)


def _malody_rate(mods_flags: int) -> float:
    flags = int(mods_flags or 0)
    if flags & (1 << 5):  # Rush
        return 1.5
    if flags & (1 << 4):  # Dash
        return 1.2
    if flags & (1 << 8):  # Slow
        return 0.8
    return 1.0


@dataclass(slots=True)
class MalodyLaneResult:
    lanes: list[dict]
    overall: dict
    warnings: list[str]
    rate: float


def _grade_offset(offset: float, windows: tuple[float, float, float, float]) -> int:
    delta = abs(float(offset))
    if delta <= windows[0]:
        return 0
    if delta <= windows[1]:
        return 1
    if delta <= windows[2]:
        return 2
    return 3


def analyze_malody_lanes(mr_obj: Any, chart: LaneChart) -> MalodyLaneResult:
    """用 .mr 头四档做 Overall，用动作帧 + 移动端 C 窗重建分轨。"""
    rate = _malody_rate(getattr(mr_obj, "mods_flags", 0))
    windows = tuple(value * rate for value in _MOBILE_WINDOWS)
    mirror = bool(int(getattr(mr_obj, "mods_flags", 0) or 0) & (1 << 2))

    press_by_col: list[list[float]] = [[] for _ in range(chart.column_count)]
    for time_ms, action, column in getattr(mr_obj, "actions", []) or []:
        if int(action) != 1:
            continue
        col = int(column)
        if mirror:
            col = chart.column_count - 1 - col
        if 0 <= col < chart.column_count:
            press_by_col[col].append(float(time_ms))
    for presses in press_by_col:
        presses.sort()

    lane_counts = [[0, 0, 0, 0] for _ in range(chart.column_count)]
    cursor = [0] * chart.column_count
    by_column: list[list[int]] = [[] for _ in range(chart.column_count)]
    for note in range(chart.note_count):
        by_column[int(chart.columns[note])].append(note)
    for notes in by_column:
        notes.sort(key=lambda note: float(chart.note_starts[note]))

    for col, notes in enumerate(by_column):
        presses = press_by_col[col]
        for note in notes:
            start = float(chart.note_starts[note])
            index = cursor[col]
            while index < len(presses) and presses[index] < start - windows[3]:
                index += 1
            if index < len(presses) and presses[index] <= start + windows[3]:
                lane_counts[col][_grade_offset(presses[index] - start, windows)] += 1
                cursor[col] = index + 1
            else:
                lane_counts[col][3] += 1
                cursor[col] = index

    lanes: list[dict] = []
    for col, counts in enumerate(lane_counts):
        judged = sum(counts)
        points = sum(count * weight for count, weight in zip(counts, _MALODY_WEIGHTS))
        lanes.append(
            {
                "column": col,
                "counts": counts,
                "judged": judged,
                "miss": counts[3],
                "points": points,
                "acc": (points / judged) if judged > 0 else None,
                "max_combo": 0,
            }
        )

    header_counts = [
        int(getattr(mr_obj, "best_count", 0) or 0),
        int(getattr(mr_obj, "cool_count", 0) or 0),
        int(getattr(mr_obj, "good_count", 0) or 0),
        int(getattr(mr_obj, "miss_count", 0) or 0),
    ]
    header_total = sum(header_counts)
    header_points = sum(
        count * weight for count, weight in zip(header_counts, _MALODY_WEIGHTS)
    )
    header_acc = (header_points / header_total) if header_total > 0 else None

    reconstructed = [0, 0, 0, 0]
    for counts in lane_counts:
        for index in range(4):
            reconstructed[index] += counts[index]
    warnings: list[str] = []
    if header_total > 0 and reconstructed != header_counts:
        diff = [reconstructed[i] - header_counts[i] for i in range(4)]
        warnings.append(
            "分轨为动作帧重建，与回放头计数存在差异 "
            f"(BEST/COOL/GOOD/MISS: {diff[0]:+d}/{diff[1]:+d}/{diff[2]:+d}/{diff[3]:+d})"
        )

    return MalodyLaneResult(
        lanes=lanes,
        overall={
            "counts": header_counts,
            "judged": header_total,
            "miss": header_counts[3],
            "acc": header_acc,
            "source": "header",
        },
        warnings=warnings,
        rate=rate,
    )
