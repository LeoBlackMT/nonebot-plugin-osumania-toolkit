from __future__ import annotations

import math
from typing import Any

import numpy as np

from ...file.osu_file_parser import osu_file
from .exceptions import NotManiaError, ParseError, UnsupportedKeyError
from .shared import load_osu_chart, normalize_cvt_flags


NOTE_NOTHING = 0
NOTE_NORMAL = 1
NOTE_HOLD_HEAD = 2
NOTE_HOLDBODY = 3
NOTE_HOLD_TAIL = 4


def f32(value: float) -> float:
    return float(np.float32(value))


def round_to_even(value: float) -> float:
    if not math.isfinite(value):
        return value
    return float(round(value))


def keys_on_left_hand(keymode: int) -> int:
    if keymode in (3, 4):
        return 2
    if keymode in (5, 6):
        return 3
    if keymode in (7, 8):
        return 4
    if keymode in (9, 10):
        return 5
    raise ValueError(f"Invalid keymode {keymode}")


def is_playable_note_type(note_type: int) -> bool:
    return note_type in (NOTE_NORMAL, NOTE_HOLD_HEAD)


def is_row_empty(row: list[int]) -> bool:
    for note_type in row:
        if note_type not in (NOTE_NOTHING, NOTE_HOLDBODY):
            return False
    return True


def _apply_conversion_flag(parser: osu_file, cvt_flag: Any) -> None:
    in_enabled, ho_enabled, _ = normalize_cvt_flags(cvt_flag)
    if in_enabled:
        parser.mod_IN()
    elif ho_enabled:
        parser.mod_HO()


def _build_rows_from_chart(chart: osu_file) -> list[dict[str, Any]]:
    key_count = int(chart.column_count)
    if key_count < 3 or key_count > 10:
        return []

    row_map: dict[int, list[int]] = {}
    hold_spans: list[tuple[int, int, int]] = []

    for col, start, end, note_type in zip(chart.columns, chart.note_starts, chart.note_ends, chart.note_types):
        key = int(col)
        start_time = int(start)
        end_time = int(end)
        raw_type = int(note_type) or 0
        is_long_note = (raw_type & 128) != 0

        if key < 0 or key >= key_count:
            continue

        start_row = row_map.setdefault(start_time, [0] * key_count)
        if is_long_note:
            start_row[key] = NOTE_HOLD_HEAD
            if end_time > start_time:
                tail_time = max(start_time + 1, end_time)
                end_row = row_map.setdefault(tail_time, [0] * key_count)
                end_row[key] = NOTE_HOLD_TAIL
                hold_spans.append((key, start_time, end_time))
        else:
            start_row[key] = NOTE_NORMAL

    sorted_times = sorted(row_map.keys())
    for key, start_time, end_time in hold_spans:
        for time_ms in sorted_times:
            if time_ms <= start_time or time_ms >= end_time:
                continue
            row = row_map[time_ms]
            if row[key] == NOTE_NOTHING:
                row[key] = NOTE_HOLDBODY

    rows: list[dict[str, Any]] = []
    for time_ms in sorted_times:
        row = row_map[time_ms]
        if not is_row_empty(row):
            rows.append({"time": int(time_ms), "data": row})
    return rows


def build_interlude_rows(source: Any, cvt_flag: Any = None) -> tuple[int, list[dict[str, Any]]]:
    chart = load_osu_chart(source)
    _apply_conversion_flag(chart, cvt_flag)
    rows = _build_rows_from_chart(chart)
    return int(chart.column_count), rows


def _calculate_note_ratings(rate: float, note_rows: list[dict[str, Any]]) -> list[list[dict[str, float]]]:
    if not note_rows:
        return []

    rate_value = rate if math.isfinite(rate) and rate > 0 else 1.0
    keys = len(note_rows[0]["data"])
    hand_split = keys_on_left_hand(keys)

    data: list[list[dict[str, float]]] = [
        [
            {"J": 0.0, "SL": 0.0, "SR": 0.0, "Total": 0.0}
            for _ in range(keys)
        ]
        for _ in range(len(note_rows))
    ]

    first_time = float(note_rows[0]["time"] or 0)
    last_note_in_column = [first_time - 1_000_000.0 for _ in range(keys)]

    def ms_to_jack_bpm(delta: float) -> float:
        value = f32(15000.0 / delta) if delta > 0 else f32(230.0)
        return value if value < 230.0 else f32(230.0)

    def ms_to_stream_bpm(delta: float) -> float:
        x = f32(0.02 * delta)
        if not math.isfinite(x) or x <= 0:
            return 0.0
        value = f32((300.0 / x) - (300.0 / (x ** 10.0) / 10.0))
        return value if value > 0 else 0.0

    def jack_compensation(jack_delta: float, stream_delta: float) -> float:
        ratio = jack_delta / stream_delta if stream_delta else 0.0
        if not math.isfinite(ratio) or ratio <= 0:
            return 0.0
        compensated = math.sqrt(max(0.0, math.log2(ratio)))
        return min(1.0, compensated)

    def note_difficulty_total(note: dict[str, float]) -> float:
        return f32(
            (
                (6.0 * (max(note["SL"], 0.0) ** 0.5)) ** 3.0
                + (6.0 * (max(note["SR"], 0.0) ** 0.5)) ** 3.0
                + (note["J"] ** 3.0)
            ) ** (1.0 / 3.0)
        )

    for i, row in enumerate(note_rows):
        time = float(row["time"])
        row_data = row["data"]

        for k in range(keys):
            note_type = row_data[k]
            if not is_playable_note_type(note_type):
                continue

            jack_delta = (time - last_note_in_column[k]) / rate_value
            item = data[i][k]
            item["J"] = ms_to_jack_bpm(jack_delta)

            hand_lo = 0 if k < hand_split else hand_split
            hand_hi = (hand_split - 1) if k < hand_split else (keys - 1)

            sl = 0.0
            sr = 0.0

            for hand_k in range(hand_lo, hand_hi + 1):
                if hand_k == k:
                    continue

                trill_delta = (time - last_note_in_column[hand_k]) / rate_value
                trill_value = ms_to_stream_bpm(trill_delta) * jack_compensation(jack_delta, trill_delta)
                if hand_k < k:
                    sl = max(sl, trill_value)
                else:
                    sr = max(sr, trill_value)

            item["SL"] = f32(sl)
            item["SR"] = f32(sr)
            item["Total"] = note_difficulty_total(item)

        for k in range(keys):
            if is_playable_note_type(row_data[k]):
                last_note_in_column[k] = time

    return data


def _calculate_variety(rate: float, note_rows: list[dict[str, Any]], note_difficulties: list[list[dict[str, float]]]) -> list[int]:
    if not note_rows:
        return []

    rate_value = rate if math.isfinite(rate) and rate > 0 else 1.0
    keys = len(note_rows[0]["data"])
    buckets: dict[int, int] = {}
    front = 0
    back = 0
    output: list[int] = []

    for i, row in enumerate(note_rows):
        now = float(row["time"])

        while front < len(note_rows) and note_rows[front]["time"] < now + 750.0 * rate_value:
            front_row = note_rows[front]["data"]
            for k in range(keys):
                if not is_playable_note_type(front_row[k]):
                    continue
                strain_bucket = int(round(note_difficulties[front][k]["Total"] / 5.0))
                buckets[strain_bucket] = buckets.get(strain_bucket, 0) + 1
            front += 1

        while back < i and note_rows[back]["time"] < now - 750.0 * rate_value:
            back_row = note_rows[back]["data"]
            for k in range(keys):
                if not is_playable_note_type(back_row[k]):
                    continue
                strain_bucket = int(round(note_difficulties[back][k]["Total"] / 5.0))
                next_count = buckets.get(strain_bucket, 0) - 1
                if next_count <= 0:
                    buckets.pop(strain_bucket, None)
                else:
                    buckets[strain_bucket] = next_count
            back += 1

        output.append(len(buckets))

    return output


def _calculate_finger_strains(rate: float, note_rows: list[dict[str, Any]], note_difficulty: list[list[dict[str, float]]]) -> list[dict[str, Any]]:
    if not note_rows:
        return []

    rate_value = rate if math.isfinite(rate) and rate > 0 else 1.0
    keys = len(note_rows[0]["data"])
    last_note_in_column = [0.0 for _ in range(keys)]
    strain_v1 = [0.0 for _ in range(keys)]
    output: list[dict[str, Any]] = []

    def strain_burst(value: float, input_value: float, delta: float) -> float:
        decay_rate = math.log(0.5) / 1575.0
        clamped_delta = min(200.0, delta)
        decay = math.exp(decay_rate * clamped_delta)
        time_cap_decay = math.exp(decay_rate * (delta - 200.0)) if delta > 200.0 else 1.0
        a = value * time_cap_decay
        b = input_value * input_value * 0.01626
        return b - (b - a) * decay

    for i, row in enumerate(note_rows):
        offset = float(row["time"])
        notes_v1 = [0.0 for _ in range(keys)]
        row_strain_v1 = [0.0 for _ in range(keys)]

        for k in range(keys):
            if not is_playable_note_type(row["data"][k]):
                continue

            notes_v1[k] = float(note_difficulty[i][k]["Total"] or 0.0)
            strain_v1[k] = strain_burst(strain_v1[k], notes_v1[k], (offset - last_note_in_column[k]) / rate_value)
            row_strain_v1[k] = strain_v1[k]
            last_note_in_column[k] = offset

        output.append({"NotesV1": notes_v1, "StrainV1Notes": row_strain_v1})

    return output


def _calculate_hand_strains(rate: float, note_rows: list[dict[str, Any]], note_difficulty: list[list[dict[str, float]]]) -> list[dict[str, Any]]:
    if not note_rows:
        return []

    rate_value = rate if math.isfinite(rate) and rate > 0 else 1.0
    keys = len(note_rows[0]["data"])
    hand_split = keys_on_left_hand(keys)
    last_note_in_column = [[0.0, 0.0, 0.0] for _ in range(keys)]
    output: list[dict[str, Any]] = []

    def strain_function(half_life: float):
        decay_rate = math.log(0.5) / half_life

        def inner(value: float, input_value: float, delta: float) -> float:
            clamped_delta = min(200.0, delta)
            decay = math.exp(decay_rate * clamped_delta)
            time_cap_decay = math.exp(decay_rate * (delta - 200.0)) if delta > 200.0 else 1.0
            a = value * time_cap_decay
            b = input_value * input_value * 0.01626
            return b - (b - a) * decay

        return inner

    strain_burst = strain_function(1575.0)
    strain_stamina = strain_function(60000.0)

    for i, row in enumerate(note_rows):
        offset = float(row["time"])
        left_hand_burst = 0.0
        left_hand_stamina = 0.0
        right_hand_burst = 0.0
        right_hand_stamina = 0.0
        strains = [0.0 for _ in range(keys)]

        for k in range(keys):
            if not is_playable_note_type(row["data"][k]):
                continue

            d = float(note_difficulty[i][k]["Total"] or 0.0)

            if k < hand_split:
                for hand_k in range(hand_split):
                    prev_burst, prev_stamina, prev_time = last_note_in_column[hand_k]
                    left_hand_burst = max(left_hand_burst, strain_burst(prev_burst, d, (offset - prev_time) / rate_value))
                    left_hand_stamina = max(left_hand_stamina, strain_stamina(prev_stamina, d, (offset - prev_time) / rate_value))
            else:
                for hand_k in range(hand_split, keys):
                    prev_burst, prev_stamina, prev_time = last_note_in_column[hand_k]
                    right_hand_burst = max(right_hand_burst, strain_burst(prev_burst, d, (offset - prev_time) / rate_value))
                    right_hand_stamina = max(right_hand_stamina, strain_stamina(prev_stamina, d, (offset - prev_time) / rate_value))

        for k in range(keys):
            if not is_playable_note_type(row["data"][k]):
                continue

            if k < hand_split:
                last_note_in_column[k] = [left_hand_burst, left_hand_stamina, offset]
                strains[k] = f32(left_hand_burst * 0.875 + left_hand_stamina * 0.125)
            else:
                last_note_in_column[k] = [right_hand_burst, right_hand_stamina, offset]
                strains[k] = f32(right_hand_burst * 0.875 + right_hand_stamina * 0.125)

        output.append({"Strains": strains, "Left": [left_hand_burst, left_hand_stamina], "Right": [right_hand_burst, right_hand_stamina]})

    return output


def _weighted_overall_difficulty(values: list[float]) -> float:
    sorted_values = sorted(float(v) for v in values)
    if not sorted_values:
        return 0.0

    length = float(len(sorted_values))
    weight = 0.0
    total = 0.0

    def weighting_curve(x: float) -> float:
        return 0.002 + (x ** 4.0)

    for i, value in enumerate(sorted_values):
        x = max(0.0, (float(i) + 2500.0 - length) / 2500.0)
        w = weighting_curve(x)
        weight += w
        total += value * w

    if not math.isfinite(weight) or weight <= 0:
        return 0.0

    transformed = ((total / weight) ** 0.6) * 0.4056
    return f32(transformed) if math.isfinite(transformed) else 0.0


def calculate_interlude_difficulty(rate: float, note_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not note_rows:
        return {"noteDifficulty": [], "strains": [], "variety": [], "hands": [], "overall": 0.0}

    note_difficulty = _calculate_note_ratings(rate, note_rows)
    variety = _calculate_variety(rate, note_rows, note_difficulty)
    strains = _calculate_finger_strains(rate, note_rows, note_difficulty)
    hands = _calculate_hand_strains(rate, note_rows, note_difficulty)

    strain_values: list[float] = []
    for row in strains:
        for value in row.get("StrainV1Notes", []):
            v = float(value) if value is not None else 0.0
            if v > 0.0:
                strain_values.append(v)

    overall = _weighted_overall_difficulty(strain_values)
    return {
        "noteDifficulty": note_difficulty,
        "strains": strains,
        "variety": variety,
        "hands": hands,
        "overall": float(overall) if math.isfinite(overall) else 0.0,
    }


def estimate_interlude_star_from_chart(chart: osu_file, rate: float = 1.0, cvt_flag: Any = None) -> float:
    _apply_conversion_flag(chart, cvt_flag)
    rows = _build_rows_from_chart(chart)
    if not rows:
        return 0.0
    difficulty = calculate_interlude_difficulty(rate, rows)
    overall = float(difficulty.get("overall", 0.0))
    return overall if math.isfinite(overall) else 0.0


def estimate_interlude_star(source: Any, rate: float = 1.0, cvt_flag: Any = None) -> float:
    chart = load_osu_chart(source)
    return estimate_interlude_star_from_chart(chart, rate, cvt_flag)


def estimate_interlude_result(source: Any, rate: float = 1.0, cvt_flag: Any = None) -> dict[str, Any]:
    chart = load_osu_chart(source)
    _apply_conversion_flag(chart, cvt_flag)
    rows = _build_rows_from_chart(chart)
    difficulty = calculate_interlude_difficulty(rate, rows)
    return {
        "keyCount": int(chart.column_count),
        "rows": rows,
        "difficulty": difficulty,
        "overall": float(difficulty.get("overall", 0.0)),
    }
