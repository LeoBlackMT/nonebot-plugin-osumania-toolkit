from __future__ import annotations

import math
from dataclasses import dataclass

from .chart import LaneChart
from .windows import Windows
from .events import LaneEvent

_RELEASE_LENIENCE = 1.5


def _js_round(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def _difficulty_range(od: float, minimum: float, middle: float, maximum: float) -> float:
    if od > 5.0:
        return middle + (maximum - middle) * ((od - 5.0) / 5.0)
    if od < 5.0:
        return middle + (middle - minimum) * ((od - 5.0) / 5.0)
    return middle


def stable_v2_windows(
    od: float,
    speed_rate: float = 1.0,
    mods: list[str] | tuple[str, ...] = (),
) -> Windows:
    """Stable ScoreV2 六窗（源 ``stableV2.js:stableV2Windows``）。"""
    try:
        clamped = min(10.0, max(0.0, float(od)))
    except (TypeError, ValueError):
        clamped = 8.0
    upper_mods = {str(mod).upper() for mod in mods}
    try:
        rate = float(speed_rate)
    except (TypeError, ValueError):
        rate = 1.0
    if not rate > 0.0:
        rate = (
            1.5
            if {"DT", "NC"} & upper_mods
            else (0.75 if {"HT", "DC"} & upper_mods else 1.0)
        )
    difficulty = 1.4 if "HR" in upper_mods else (1.0 / 1.4 if "EZ" in upper_mods else 1.0)
    total = rate / difficulty

    def scale(value: float) -> float:
        return math.floor(value * total) + 0.5

    return Windows(
        od=clamped,
        perfect=scale(_difficulty_range(clamped, 22.4, 19.4, 13.9)),
        great=scale(_difficulty_range(clamped, 64.0, 49.0, 34.0)),
        good=scale(_difficulty_range(clamped, 97.0, 82.0, 67.0)),
        ok=scale(_difficulty_range(clamped, 127.0, 112.0, 97.0)),
        meh=scale(_difficulty_range(clamped, 151.0, 136.0, 121.0)),
        miss=scale(_difficulty_range(clamped, 188.0, 173.0, 158.0)),
    )


def _judgment_for_offset(offset: float, windows: Windows) -> int:
    delta = abs(_js_round(offset))
    if delta <= windows.perfect:
        return 1
    if delta <= windows.great:
        return 2
    if delta <= windows.good:
        return 3
    if delta <= windows.ok:
        return 4
    if delta <= windows.meh:
        return 5
    if delta <= windows.miss:
        return 6
    return 0


def _head_judgment(offset: float, windows: Windows) -> int:
    rounded = _js_round(offset)
    if rounded >= math.floor(windows.ok):
        return 6 if rounded <= windows.miss else 0
    return _judgment_for_offset(offset, windows)


def _tail_judgment(offset: float, windows: Windows) -> int:
    delta = abs(_js_round(offset))
    if delta <= math.floor(windows.perfect) * _RELEASE_LENIENCE:
        return 1
    if delta <= math.floor(windows.great) * _RELEASE_LENIENCE:
        return 2
    if delta <= math.floor(windows.good) * _RELEASE_LENIENCE:
        return 3
    if offset >= math.floor(windows.ok) * _RELEASE_LENIENCE:
        return 6
    if delta <= math.floor(windows.ok) * _RELEASE_LENIENCE:
        return 4
    if delta <= math.floor(windows.meh) * _RELEASE_LENIENCE:
        return 5
    if delta <= math.floor(windows.miss) * _RELEASE_LENIENCE:
        return 6
    return 0


def _cap_to_meh(judgment: int) -> int:
    return 5 if judgment < 5 else judgment


def _raw_judgment_for_offset(offset: float, windows: Windows) -> int:
    delta = abs(offset)
    if delta <= windows.perfect:
        return 1
    if delta <= windows.great:
        return 2
    if delta <= windows.good:
        return 3
    if delta <= windows.ok:
        return 4
    if delta <= windows.meh:
        return 5
    if delta <= windows.miss:
        return 6
    return 0


@dataclass(slots=True)
class Segment:
    start: float
    end: float | None


def _mirror_mask(mask: int, keys: int) -> int:
    out = 0
    for col in range(keys):
        if mask & (1 << col):
            out |= 1 << (keys - 1 - col)
    return out


def _build_column_segments(
    chart: LaneChart,
    frames: list[tuple[float, int]],
    mirror: bool = False,
) -> list[list[Segment]]:
    segments: list[list[Segment]] = [[] for _ in range(chart.column_count)]
    active: list[float | None] = [None] * chart.column_count
    for time_ms, raw_mask in frames:
        try:
            time_value = float(time_ms)
            mask = int(raw_mask) & 0xFFFFFFFF
        except (TypeError, ValueError):
            continue
        if mirror:
            mask = _mirror_mask(mask, chart.column_count)
        for col in range(chart.column_count):
            down = bool(mask & (1 << col))
            if down and active[col] is None:
                active[col] = time_value
            elif not down and active[col] is not None:
                segments[col].append(Segment(start=active[col], end=time_value))
                active[col] = None
    for col in range(chart.column_count):
        if active[col] is not None:
            segments[col].append(Segment(start=active[col], end=None))
    return segments


def _build_column_note_lists(chart: LaneChart) -> list[list[int]]:
    lists: list[list[int]] = [[] for _ in range(chart.column_count)]
    for note in range(chart.note_count):
        lists[int(chart.columns[note])].append(note)
    return lists


def _lazer_tail_from(
    segments: list[Segment],
    start_index: int,
    end: float,
    windows: Windows,
    head_missed: bool,
    cutoff: float,
) -> tuple[int, float] | None:
    tail_deadline = end + windows.miss * _RELEASE_LENIENCE
    body_break = False
    for index in range(start_index, len(segments)):
        segment = segments[index]
        if segment.end is None:
            if cutoff == math.inf:
                return 6, 0.0
            return None
        if segment.end > tail_deadline:
            return 6, segment.end - end
        raw = _raw_judgment_for_offset((segment.end - end) / _RELEASE_LENIENCE, windows)
        if raw:
            judgment = _cap_to_meh(raw) if head_missed or body_break else raw
            return judgment, segment.end - end
        if segment.end >= tail_deadline:
            return 6, segment.end - end
        body_break = True
        next_segment = segments[index + 1] if index + 1 < len(segments) else None
        if next_segment is None or next_segment.start > tail_deadline:
            return 6, 0.0
    return None


def _lazer_regrab_tail(
    segments: list[Segment],
    cursor: int,
    notes: list[int],
    note_position: int,
    note_starts,
    end: float,
    windows: Windows,
) -> tuple[int, float] | None:
    tail_deadline = end + windows.miss * _RELEASE_LENIENCE
    for index in range(cursor, len(segments)):
        segment = segments[index]
        if segment.start > end + windows.meh:
            break
        if segment.end is None or segment.end > tail_deadline:
            break
        next_alive_start: float | None = None
        for next_position in range(note_position + 1, len(notes)):
            later = float(note_starts[notes[next_position]])
            if segment.start <= later + windows.meh:
                next_alive_start = later
                break
        if next_alive_start is not None:
            if segment.start >= next_alive_start:
                continue
            if next_alive_start - segment.start <= windows.meh and end < next_alive_start:
                break
        raw = _raw_judgment_for_offset((segment.end - end) / _RELEASE_LENIENCE, windows)
        if not raw:
            continue
        return _cap_to_meh(raw), segment.end - end
    return None


def _lazer_judged_events(
    chart: LaneChart,
    frames: list[tuple[float, int]],
    windows: Windows,
    cutoff: float,
    mirror: bool,
) -> list[LaneEvent]:
    segments = _build_column_segments(chart, frames, mirror)
    notes_by_column = _build_column_note_lists(chart)
    events: list[LaneEvent] = []

    def push(
        col: int, judgment: int, offset: float, part: str, note: int, time_value: float
    ) -> None:
        if not judgment:
            return
        events.append(
            LaneEvent(
                col=col,
                result=7 - judgment,
                offset=offset,
                time=time_value,
                part=part,
            )
        )

    tail_window = windows.miss * _RELEASE_LENIENCE
    for col in range(chart.column_count):
        column_segments = segments[col]
        notes = notes_by_column[col]
        cursor = 0
        for position, note in enumerate(notes):
            note_time = float(chart.note_starts[note])
            end = float(chart.note_ends[note])
            hold = bool(chart.is_hold[note])
            next_time = (
                float(chart.note_starts[notes[position + 1]])
                if position + 1 < len(notes)
                else math.inf
            )
            if note_time > cutoff + windows.miss:
                break
            while (
                cursor < len(column_segments)
                and column_segments[cursor].start < note_time - windows.miss
            ):
                cursor += 1
            matched = -1
            head_judgment = 0
            for index in range(cursor, len(column_segments)):
                segment = column_segments[index]
                if segment.start >= next_time:
                    break
                if segment.start > note_time + windows.meh:
                    break
                judgment = _raw_judgment_for_offset(segment.start - note_time, windows)
                if judgment:
                    matched = index
                    head_judgment = judgment
                    break
            if matched < 0:
                head_deadline = min(note_time + windows.meh, next_time)
                if cutoff < head_deadline:
                    break
                push(col, 6, 0.0, "head-miss", note, note_time)
                if not hold:
                    continue
                if cutoff < end + tail_window:
                    break
                regrab = _lazer_regrab_tail(
                    column_segments,
                    cursor,
                    notes,
                    position,
                    chart.note_starts,
                    end,
                    windows,
                )
                if regrab is not None:
                    push(col, regrab[0], regrab[1], "hold-tail", note, note_time)
                else:
                    push(col, 6, 0.0, "hold-tail", note, note_time)
                continue
            segment = column_segments[matched]
            push(
                col,
                head_judgment,
                segment.start - note_time,
                "hold-head" if hold else "tap",
                note,
                note_time,
            )
            cursor = matched + 1
            if not hold:
                continue
            tail = _lazer_tail_from(
                column_segments,
                matched,
                end,
                windows,
                head_judgment == 6,
                cutoff,
            )
            if tail is None:
                break
            push(col, tail[0], tail[1], "hold-tail", note, note_time)
    return events


def frames_to_stable_v2_events(
    chart: LaneChart,
    frames: list[tuple[float, int]],
    *,
    od_flag: float | None = None,
    mods: list[str] | tuple[str, ...] = (),
    speed_rate: float = 1.0,
    cutoff: float = math.inf,
    judgement_mode: str = "stable",
    head_miss_notes: set[int] | None = None,
) -> list[LaneEvent]:
    """源 ``framesToStableV2Events`` 直译；``judgement_mode`` 支持 stable/lazer。"""
    if not chart.note_count or not frames:
        return []
    od = float(od_flag) if od_flag is not None else float(chart.od)
    windows = stable_v2_windows(od, speed_rate, mods)
    upper_mods = {str(mod).upper() for mod in mods}
    mirror = "MR" in upper_mods
    if judgement_mode == "lazer":
        return _lazer_judged_events(chart, frames, windows, cutoff, mirror)

    tail_window = windows.miss * _RELEASE_LENIENCE
    head_misses = head_miss_notes or set()
    segments = _build_column_segments(chart, frames, mirror)
    seg_cursor = [0] * chart.column_count

    next_start = [math.inf] * chart.note_count
    last_by_col = [-1] * chart.column_count
    for index in range(chart.note_count):
        column = int(chart.columns[index])
        if last_by_col[column] >= 0:
            next_start[last_by_col[column]] = float(chart.note_starts[index])
        last_by_col[column] = index

    events: list[LaneEvent] = []

    def push(
        col: int, judgment: int, offset: float, part: str, note: int, time_value: float
    ) -> None:
        if not judgment:
            return
        events.append(
            LaneEvent(
                col=col,
                result=7 - judgment,
                offset=offset,
                time=time_value,
                part=part,
            )
        )

    for index in range(chart.note_count):
        note_time = float(chart.note_starts[index])
        end = float(chart.note_ends[index])
        col = int(chart.columns[index])
        hold = bool(chart.is_hold[index])
        if note_time > cutoff + windows.miss:
            continue
        column_segments = segments[col]
        while seg_cursor[col] < len(column_segments):
            candidate = column_segments[seg_cursor[col]]
            too_early = candidate.start < note_time - windows.miss or (
                candidate.end is not None and candidate.end < note_time - windows.miss
            )
            if not too_early:
                break
            seg_cursor[col] += 1
        segment = (
            column_segments[seg_cursor[col]]
            if seg_cursor[col] < len(column_segments)
            else None
        )
        has_head = (
            segment is not None
            and segment.start >= note_time - windows.miss
            and segment.start <= note_time + windows.meh
            and segment.start < next_start[index]
        )
        if not has_head:
            if cutoff == math.inf or note_time + windows.miss < cutoff:
                push(col, 6, 0.0, "head-miss", index, note_time)
                if hold:
                    push(col, 6, 0.0, "tail-miss", index, note_time)
            continue
        forced_head_miss = index in head_misses
        if forced_head_miss:
            push(col, 6, 0.0, "head-miss", index, note_time)
        else:
            push(
                col,
                _head_judgment(segment.start - note_time, windows),
                segment.start - note_time,
                "hold-head" if hold else "tap",
                index,
                note_time,
            )
        seg_cursor[col] += 1
        if not hold:
            continue

        def push_tail(judgment: int, offset: float) -> None:
            push(
                col,
                5 if forced_head_miss and judgment < 5 else judgment,
                offset,
                "hold-tail",
                index,
                note_time,
            )

        if end > cutoff + tail_window:
            continue
        tail_end = segment.end
        regrabs = 0
        while (
            seg_cursor[col] < len(column_segments)
            and column_segments[seg_cursor[col]].start < end - 10.0
        ):
            tail_end = column_segments[seg_cursor[col]].end
            seg_cursor[col] += 1
            regrabs += 1
        if regrabs > 0:
            break_offset = None if segment.end is None else segment.end - end
            judgment = (
                _tail_judgment(break_offset, windows) or 5
                if break_offset is not None and break_offset >= -windows.meh
                else 5
            )
            push_tail(judgment, break_offset or 0.0)
        elif tail_end is None:
            if cutoff == math.inf or cutoff >= end + windows.meh:
                push_tail(1, 0.0)
        elif tail_end - end > windows.meh:
            push_tail(1, 0.0)
        else:
            push_tail(_tail_judgment(tail_end - end, windows), tail_end - end)
    return events
