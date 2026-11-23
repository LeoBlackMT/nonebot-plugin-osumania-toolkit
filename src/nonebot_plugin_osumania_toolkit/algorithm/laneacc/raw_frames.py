from __future__ import annotations

import math

from .chart import LaneChart
from .windows import Windows
from .events import LaneEvent


def _mirror_mask(mask: int, keys: int) -> int:
    out = 0
    for col in range(keys):
        if mask & (1 << col):
            out |= 1 << (keys - 1 - col)
    return out


def frames_to_sv1_events(
    chart: LaneChart,
    frames: list[tuple[float, int]],
    windows: Windows,
    mods: list[str] | tuple[str, ...] = (),
    speed_rate: float = 1.0,
    force_drops: set[int] | None = None,
    max_time: float = math.inf,
) -> list[LaneEvent]:
    """把绝对谱面时间的原始帧转换为 Stable V1 等价事件（源 ``rawFrames.js``）。"""
    del speed_rate  # ReplayFrame.Time 已是谱面时间；保留参数与源签名对齐
    keys = chart.column_count
    force_drop_set = force_drops or set()
    mods_upper = {str(mod).upper() for mod in mods}
    mirror = "MR" in mods_upper

    press: list[list[float]] = [[] for _ in range(keys)]
    release: list[list[float]] = [[] for _ in range(keys)]
    prev = 0
    for time_ms, raw_mask in frames:
        try:
            time_value = float(time_ms)
            mask = int(raw_mask) & 0xFFFFFFFF
        except (TypeError, ValueError):
            continue
        if mirror:
            mask = _mirror_mask(mask, keys)
        changed = mask ^ prev
        if changed:
            for col in range(keys):
                bit = 1 << col
                if changed & bit:
                    (press if mask & bit else release)[col].append(time_value)
        prev = mask

    by_column: list[list[int]] = [[] for _ in range(keys)]
    for note in range(chart.note_count):
        by_column[int(chart.columns[note])].append(note)
    for notes in by_column:
        notes.sort(key=lambda note: float(chart.note_starts[note]))

    events: list[tuple[float, int, int, LaneEvent]] = []

    def push(time_value: float, col: int, order: int, event: LaneEvent) -> None:
        if time_value > max_time + 1:
            return
        event.time = float(time_value)
        events.append((time_value, col, order, event))

    for col in range(keys):
        notes = by_column[col]
        press_times = press[col]
        release_times = release[col]
        press_index = 0
        release_index = 0
        for position, note in enumerate(notes):
            start = float(chart.note_starts[note])
            end = float(chart.note_ends[note]) if chart.is_hold[note] else start
            if start > max_time + windows.miss:
                break
            while (
                press_index < len(press_times)
                and press_times[press_index] < start - windows.miss
            ):
                press_index += 1
            press_time: float | None = None
            if (
                press_index < len(press_times)
                and press_times[press_index] <= start + windows.ok
            ):
                press_time = press_times[press_index]
                press_index += 1
            if press_time is None and start + windows.miss > max_time:
                continue
            head_offset = 0.0 if press_time is None else press_time - start
            push(
                start + head_offset,
                col,
                0,
                LaneEvent(
                    col=col,
                    result=1 if press_time is None else 6,
                    offset=head_offset,
                    part="head-miss" if press_time is None else "head",
                ),
            )
            if not bool(chart.is_hold[note]):
                continue

            anchor = start if press_time is None else press_time
            while (
                release_index < len(release_times)
                and release_times[release_index] < anchor - 5.0
            ):
                release_index += 1
            release_time: float | None = None
            if (
                release_index < len(release_times)
                and release_times[release_index] <= end + windows.ok
            ):
                release_time = release_times[release_index]
                release_index += 1
            tail_offset = 0.0 if release_time is None else release_time - end
            natural_drop = release_time is None or tail_offset < -windows.meh
            forced = (
                note in force_drop_set
                and release_time is not None
                and tail_offset < -windows.meh
            )
            tail_result = 50 if forced else (1 if natural_drop else 6)
            tail_time = end + tail_offset
            if tail_time > max_time + 1:
                continue
            if tail_result == 50:
                push(
                    tail_time,
                    col,
                    1,
                    LaneEvent(col=col, result=1, offset=tail_offset, part="tail"),
                )
                push(
                    tail_time,
                    col,
                    2,
                    LaneEvent(col=col, result=50, offset=tail_offset, part="tail-force"),
                )
            else:
                push(
                    tail_time,
                    col,
                    1,
                    LaneEvent(
                        col=col, result=tail_result, offset=tail_offset, part="tail"
                    ),
                )
                if tail_result == 1:
                    push(
                        tail_time,
                        col,
                        2,
                        LaneEvent(
                            col=col, result=15, offset=tail_offset, part="tail-drop"
                        ),
                    )
                    push(
                        tail_time,
                        col,
                        3,
                        LaneEvent(
                            col=col, result=13, offset=tail_offset, part="tail-drop"
                        ),
                    )
                else:
                    push(
                        tail_time,
                        col,
                        2,
                        LaneEvent(col=col, result=14, offset=0.0, part="tail-hold"),
                    )
                    push(
                        tail_time,
                        col,
                        3,
                        LaneEvent(
                            col=col, result=14, offset=tail_offset, part="tail-hold"
                        ),
                    )

    events.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in events]
