from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any

from ...parser.osu_file_parser import osu_file
from .exceptions import NotManiaError, ParseError


class NoteType:
    NOTHING = 0
    NORMAL = 1
    HOLDHEAD = 2
    HOLDBODY = 3
    HOLDTAIL = 4


def f32(value: float) -> float:
    return float(value)


def round_to_even(value: float) -> int:
    return int(round(float(value)))


def create_empty_row(key_count: int) -> list[int]:
    return [NoteType.NOTHING for _ in range(int(key_count))]


def is_playable_note_type(note_type: int) -> bool:
    return note_type in {NoteType.NORMAL, NoteType.HOLDHEAD}


def is_row_empty(row: list[int]) -> bool:
    for note_type in row:
        if note_type not in {NoteType.NOTHING, NoteType.HOLDBODY}:
            return False
    return True


def keys_on_left_hand(keymode: int) -> int:
    match int(keymode):
        case 3 | 4:
            return 2
        case 5 | 6:
            return 3
        case 7 | 8:
            return 4
        case 9 | 10:
            return 5
        case _:
            raise ValueError(f"Invalid keymode {keymode}")


def _build_rows_from_parser(chart: osu_file) -> list[dict[str, Any]]:
    parsed_rows = list(getattr(chart, "note_rows", []) or [])
    rows: list[dict[str, Any]] = []
    for time_ms, data in parsed_rows:
        rows.append({"time": float(time_ms), "data": list(data)})
    return rows


def _normalize_cvt_flag(cvt_flag: Any) -> str | None:
    normalized = str(cvt_flag or "").strip().upper()
    if normalized in {"IN", "HO"}:
        return normalized
    return None


def _apply_conversion_flag(chart: osu_file, cvt_flag: Any) -> None:
    normalized = _normalize_cvt_flag(cvt_flag)
    if normalized == "IN" and hasattr(chart, "modIN"):
        chart.modIN()
    elif normalized == "HO" and hasattr(chart, "modHO"):
        chart.modHO()


def _resolve_source_path(source: Any) -> Path:
    if isinstance(source, Path):
        return source
    if isinstance(source, str):
        text = source
        if "[HitObjects]" in text and ("\n" in text or "\r" in text):
            temp = tempfile.NamedTemporaryFile("w", suffix=".osu", delete=False, encoding="utf-8-sig")
            try:
                temp.write(text)
                temp.flush()
                return Path(temp.name)
            finally:
                temp.close()
        return Path(text)
    path_value = getattr(source, "file_path", None)
    if path_value:
        return Path(str(path_value))
    raise TypeError("Unsupported Interlude source. Provide osu text or a chart path.")


def build_interlude_rows(source: Any, cvt_flag: Any = None) -> dict[str, Any]:
    temp_path: Path | None = None
    path = _resolve_source_path(source)
    if path.exists() and path.is_file() and path.suffix.lower() == ".osu":
        chart = osu_file(str(path))
        chart.process()
    else:
        temp_path = path if path.exists() and path.is_file() else None
        chart = osu_file(str(path))
        chart.process()

    try:
        if chart.status == "NotMania":
            raise NotManiaError("Beatmap mode is not mania")
        if chart.status == "Fail":
            raise ParseError("Beatmap parse failed")

        _apply_conversion_flag(chart, cvt_flag)

        key_count = int(getattr(chart, "column_count", 0) or 0)
        if key_count < 3 or key_count > 10:
            return {"keyCount": key_count, "rows": []}

        rows = _build_rows_from_parser(chart)
        return {"keyCount": key_count, "rows": rows}
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def note_difficulty_total(note: dict[str, float]) -> float:
    return f32(
        math.pow(
            math.pow(6.0 * math.pow(note["SL"], 0.5), 3.0)
            + math.pow(6.0 * math.pow(note["SR"], 0.5), 3.0)
            + math.pow(note["J"], 3.0),
            1.0 / 3.0,
        )
    )


def calculate_note_ratings(rate: float, note_rows: list[dict[str, Any]]) -> list[list[dict[str, float]]]:
    if not note_rows:
        return []

    rate_value = rate if math.isfinite(rate) and rate > 0 else 1.0
    keys = len(note_rows[0]["data"])
    hand_split = keys_on_left_hand(keys)

    data = [
        [
            {"J": 0.0, "SL": 0.0, "SR": 0.0, "Total": 0.0}
            for _ in range(keys)
        ]
        for _ in range(len(note_rows))
    ]

    first_time = float(note_rows[0]["time"] or 0)
    last_note_in_column = [first_time - 1000000.0 for _ in range(keys)]

    for i, row in enumerate(note_rows):
        time = float(row["time"])
        for k in range(keys):
            note_type = int(row["data"][k])
            if not is_playable_note_type(note_type):
                continue

            jack_delta = (time - last_note_in_column[k]) / rate_value
            item = data[i][k]
            item["J"] = min(230.0, f32(15000.0 / jack_delta)) if jack_delta > 0 else 0.0

            hand_lo = 0 if k < hand_split else hand_split
            hand_hi = (hand_split - 1) if k < hand_split else (keys - 1)

            sl = 0.0
            sr = 0.0
            for hand_k in range(hand_lo, hand_hi + 1):
                if hand_k == k:
                    continue

                trill_delta = (time - last_note_in_column[hand_k]) / rate_value
                x = 0.02 * trill_delta
                if not math.isfinite(x) or x <= 0:
                    trill_value = 0.0
                else:
                    trill_value = (300.0 / x) - (300.0 / math.pow(x, 10.0) / 10.0)
                    if trill_value < 0:
                        trill_value = 0.0
                ratio = jack_delta / trill_delta if trill_delta > 0 else 0.0
                comp = math.sqrt(max(0.0, math.log2(ratio))) if ratio > 0 else 0.0
                comp = min(1.0, comp)
                trill_value *= comp
                if hand_k < k:
                    sl = max(sl, trill_value)
                else:
                    sr = max(sr, trill_value)

            item["SL"] = f32(sl)
            item["SR"] = f32(sr)
            item["Total"] = note_difficulty_total(item)

        for k in range(keys):
            if is_playable_note_type(int(row["data"][k])):
                last_note_in_column[k] = time

    return data


def calculate_variety(rate: float, note_rows: list[dict[str, Any]], note_difficulties: list[list[dict[str, float]]]) -> list[int]:
    if not note_rows:
        return []

    rate_value = rate if math.isfinite(rate) and rate > 0 else 1.0
    keys = len(note_rows[0]["data"])
    buckets: dict[int, int] = {}
    front = 0
    back = 0
    output: list[int] = []

    while front < len(note_rows):
        now = float(note_rows[front]["time"])
        while front < len(note_rows) and float(note_rows[front]["time"]) < now + 750.0 * rate_value:
            front_row = note_rows[front]["data"]
            for k in range(keys):
                if not is_playable_note_type(int(front_row[k])):
                    continue
                strain_bucket = round_to_even((float(note_difficulties[front][k]["Total"]) or 0.0) / 5.0)
                buckets[strain_bucket] = buckets.get(strain_bucket, 0) + 1
            front += 1

        while back < front - 1 and float(note_rows[back]["time"]) < now - 750.0 * rate_value:
            back_row = note_rows[back]["data"]
            for k in range(keys):
                if not is_playable_note_type(int(back_row[k])):
                    continue
                strain_bucket = round_to_even((float(note_difficulties[back][k]["Total"]) or 0.0) / 5.0)
                next_value = buckets.get(strain_bucket, 0) - 1
                if next_value <= 0:
                    buckets.pop(strain_bucket, None)
                else:
                    buckets[strain_bucket] = next_value
            back += 1

        output.append(len(buckets))

    return output


def _create_strain_function(half_life: float):
    decay_rate = math.log(0.5) / half_life

    def strain(value: float, input_value: float, delta: float) -> float:
        clamped_delta = min(200.0, delta)
        decay = math.exp(decay_rate * clamped_delta)
        time_cap_decay = math.exp(decay_rate * (delta - 200.0)) if delta > 200.0 else 1.0
        a = value * time_cap_decay
        b = input_value * input_value * 0.01626
        return f32(b - (b - a) * decay)

    return strain


_strain_burst = _create_strain_function(1575.0)
_strain_stamina = _create_strain_function(60000.0)


def calculate_finger_strains(rate: float, note_rows: list[dict[str, Any]], note_difficulty: list[list[dict[str, float]]]) -> list[dict[str, Any]]:
    if not note_rows:
        return []

    rate_value = rate if math.isfinite(rate) and rate > 0 else 1.0
    keys = len(note_rows[0]["data"])
    last_note_in_column = [0.0 for _ in range(keys)]
    strain_v1 = [0.0 for _ in range(keys)]
    output: list[dict[str, Any]] = []

    for i, row in enumerate(note_rows):
        offset = float(row["time"])
        notes_v1 = [0.0 for _ in range(keys)]
        row_strain_v1 = [0.0 for _ in range(keys)]

        for k in range(keys):
            if not is_playable_note_type(int(row["data"][k])):
                continue

            notes_v1[k] = float(note_difficulty[i][k]["Total"]) or 0.0
            strain_v1[k] = _strain_burst(strain_v1[k], notes_v1[k], (offset - last_note_in_column[k]) / rate_value)
            row_strain_v1[k] = strain_v1[k]
            last_note_in_column[k] = offset

        output.append({"NotesV1": notes_v1, "StrainV1Notes": row_strain_v1})

    return output


def calculate_hand_strains(rate: float, note_rows: list[dict[str, Any]], note_difficulty: list[list[dict[str, float]]]) -> list[dict[str, Any]]:
    if not note_rows:
        return []

    rate_value = rate if math.isfinite(rate) and rate > 0 else 1.0
    keys = len(note_rows[0]["data"])
    hand_split = keys_on_left_hand(keys)
    last_note_in_column = [[0.0, 0.0, 0.0] for _ in range(keys)]
    output: list[dict[str, Any]] = []

    for i, row in enumerate(note_rows):
        offset = float(row["time"])
        left_hand_burst = 0.0
        left_hand_stamina = 0.0
        right_hand_burst = 0.0
        right_hand_stamina = 0.0
        strains = [0.0 for _ in range(keys)]

        for k in range(keys):
            if not is_playable_note_type(int(row["data"][k])):
                continue

            d = float(note_difficulty[i][k]["Total"]) or 0.0
            if k < hand_split:
                for hand_k in range(hand_split):
                    prev_burst, prev_stamina, prev_time = last_note_in_column[hand_k]
                    left_hand_burst = max(left_hand_burst, _strain_burst(prev_burst, d, (offset - prev_time) / rate_value))
                    left_hand_stamina = max(left_hand_stamina, _strain_stamina(prev_stamina, d, (offset - prev_time) / rate_value))
            else:
                for hand_k in range(hand_split, keys):
                    prev_burst, prev_stamina, prev_time = last_note_in_column[hand_k]
                    right_hand_burst = max(right_hand_burst, _strain_burst(prev_burst, d, (offset - prev_time) / rate_value))
                    right_hand_stamina = max(right_hand_stamina, _strain_stamina(prev_stamina, d, (offset - prev_time) / rate_value))

        for k in range(keys):
            if not is_playable_note_type(int(row["data"][k])):
                continue
            if k < hand_split:
                last_note_in_column[k] = [left_hand_burst, left_hand_stamina, offset]
                strains[k] = f32(left_hand_burst * 0.875 + left_hand_stamina * 0.125)
            else:
                last_note_in_column[k] = [right_hand_burst, right_hand_stamina, offset]
                strains[k] = f32(right_hand_burst * 0.875 + right_hand_stamina * 0.125)

        output.append({"Strains": strains, "Left": [left_hand_burst, left_hand_stamina], "Right": [right_hand_burst, right_hand_stamina]})

    return output


def weighted_overall_difficulty(data: list[float]) -> float:
    values = sorted(float(v) for v in (data or []))
    if not values:
        return 0.0

    length = float(len(values))
    weight = 0.0
    total = 0.0
    for i, value in enumerate(values):
        x = max(0.0, (float(i) + 2500.0 - length) / 2500.0)
        w = 0.002 + math.pow(x, 4.0)
        weight += w
        total += value * w

    if not math.isfinite(weight) or weight <= 0:
        return 0.0

    transformed = math.pow(total / weight, 0.6) * 0.4056
    return f32(transformed) if math.isfinite(transformed) else 0.0


def calculate_interlude_difficulty(rate: float, note_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not note_rows:
        return {"noteDifficulty": [], "strains": [], "variety": [], "hands": [], "overall": 0.0}

    note_difficulty = calculate_note_ratings(rate, note_rows)
    variety = calculate_variety(rate, note_rows, note_difficulty)
    strains = calculate_finger_strains(rate, note_rows, note_difficulty)
    hands = calculate_hand_strains(rate, note_rows, note_difficulty)

    strain_values: list[float] = []
    for row in strains:
        for value in row.get("StrainV1Notes", []) or []:
            numeric = float(value) or 0.0
            if numeric > 0.0:
                strain_values.append(numeric)

    overall = weighted_overall_difficulty(strain_values)
    return {"noteDifficulty": note_difficulty, "strains": strains, "variety": variety, "hands": hands, "overall": overall}


def calculate_interlude_star(source: Any, rate: float = 1.0, cvt_flag: Any = None) -> float:
    resolved_rate = rate if math.isfinite(rate) and rate > 0 else 1.0
    built = build_interlude_rows(source, cvt_flag)
    difficulty = calculate_interlude_difficulty(resolved_rate, built["rows"])
    overall = float(difficulty.get("overall", 0.0))
    return overall if math.isfinite(overall) else 0.0


def estimate_interlude_star_from_chart(source: Any, rate: float = 1.0, cvt_flag: Any = None) -> float:
    return calculate_interlude_star(source, rate, cvt_flag)
