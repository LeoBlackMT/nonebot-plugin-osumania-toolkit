from __future__ import annotations

from dataclasses import dataclass

_KEEP_AS_IS_SECTIONS = {
    "[General]",
    "[Editor]",
    "[Metadata]",
    "[Difficulty]",
    "[Colours]",
}
_SECTION_EVENTS = "[Events]"
_SECTION_TIMING = "[TimingPoints]"
_SECTION_OBJECTS = "[HitObjects]"
_TIMING_UNINHERITED_INDEX = 6


@dataclass(slots=True)
class SliceResult:
    text: str
    object_count: int
    timing_point_count: int


def _is_section_header(line: str) -> bool:
    return line.startswith("[") and line.endswith("]")


def _parse_timing_point(line: str) -> tuple[int, bool] | None:
    parts = line.split(",")
    if len(parts) < 2:
        return None
    try:
        time_ms = float(parts[0])
        beat_length = float(parts[1])
    except (TypeError, ValueError):
        return None
    if not (time_ms == time_ms and beat_length == beat_length):
        return None
    uninherited = True
    if len(parts) > _TIMING_UNINHERITED_INDEX and parts[_TIMING_UNINHERITED_INDEX]:
        try:
            uninherited = int(parts[_TIMING_UNINHERITED_INDEX]) == 1
        except ValueError:
            uninherited = True
    return int(time_ms), uninherited


def _parse_object_window(line: str) -> tuple[int, int] | None:
    parts = line.split(",")
    if len(parts) < 4:
        return None
    try:
        start = int(float(parts[2]))
        note_type = int(parts[3])
    except (TypeError, ValueError):
        return None
    end = start
    if (note_type & 128) != 0 and len(parts) >= 6:
        try:
            end = int(float(str(parts[5]).split(":", 1)[0]))
        except (TypeError, ValueError):
            end = start
    return start, end


def _parse_break_window(line: str) -> tuple[int, int] | None:
    parts = line.split(",")
    if len(parts) < 3:
        return None
    head = parts[0].strip()
    if head not in {"2", "Break"}:
        return None
    try:
        start = int(float(parts[1]))
        end = int(float(parts[2]))
    except (TypeError, ValueError):
        return None
    return start, end


def _select_timing_points(
    all_timing: list[tuple[int, bool, str]], range_start: int, range_end: int
) -> list[tuple[int, bool, str]]:
    if not all_timing:
        return []

    keep_indexes: set[int] = set()
    last_uninherited_before = -1
    last_inherited_before = -1
    first_uninherited = -1

    for index, (time_ms, uninherited, _raw) in enumerate(all_timing):
        if uninherited and first_uninherited < 0:
            first_uninherited = index
        if range_start <= time_ms <= range_end:
            keep_indexes.add(index)
            continue
        if time_ms < range_start:
            if uninherited:
                last_uninherited_before = index
            else:
                last_inherited_before = index

    if last_uninherited_before >= 0:
        keep_indexes.add(last_uninherited_before)
    elif first_uninherited >= 0:
        keep_indexes.add(first_uninherited)
    if last_inherited_before >= 0:
        keep_indexes.add(last_inherited_before)

    return [
        all_timing[index]
        for index in sorted(
            keep_indexes,
            key=lambda item: (all_timing[item][0], item),
        )
    ]


def slice_osu_text_by_time_range(
    raw_text: str,
    start_ms: int,
    end_ms: int,
) -> SliceResult:
    """按区间截取 ``.osu`` 文本；规则对齐源项目 ``osuTimeSlice.js``。"""
    text = str(raw_text or "")
    try:
        a = int(start_ms)
        b = int(end_ms)
    except (TypeError, ValueError):
        return SliceResult(text=text, object_count=0, timing_point_count=0)

    range_start = min(a, b)
    range_end = max(a, b)

    sections: list[tuple[str, list[str]]] = []
    current_header = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        if _is_section_header(line):
            if current_header or current_lines:
                sections.append((current_header, current_lines))
            current_header = line.strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_header or current_lines:
        sections.append((current_header, current_lines))

    all_timing: list[tuple[int, bool, str]] = []
    for header, lines in sections:
        if header != _SECTION_TIMING:
            continue
        for line in lines:
            parsed = _parse_timing_point(line)
            if parsed is not None:
                all_timing.append((parsed[0], parsed[1], line))

    output: list[str] = []
    object_count = 0
    timing_point_count = 0

    for header, lines in sections:
        if header:
            output.append(header)

        if header == _SECTION_TIMING:
            kept = _select_timing_points(all_timing, range_start, range_end)
            for _time_ms, _uninherited, raw in kept:
                output.append(raw)
            timing_point_count += len(kept)
            continue

        if header == _SECTION_OBJECTS:
            for line in lines:
                if not line.strip():
                    continue
                window = _parse_object_window(line)
                if window is None:
                    output.append(line)
                    continue
                obj_start, obj_end = window
                if obj_start <= range_end and obj_end >= range_start:
                    output.append(line)
                    object_count += 1
            continue

        if header == _SECTION_EVENTS:
            for line in lines:
                if not line.strip():
                    continue
                window = _parse_break_window(line)
                if window is None:
                    output.append(line)
                    continue
                if window[0] <= range_end and window[1] >= range_start:
                    output.append(line)
            continue

        if header and header not in _KEEP_AS_IS_SECTIONS:
            for line in lines:
                if line.strip():
                    output.append(line)
            continue

        output.extend(lines)

    while output and not output[-1]:
        output.pop()

    return SliceResult(
        text="\n".join(output) + "\n",
        object_count=object_count,
        timing_point_count=timing_point_count,
    )
