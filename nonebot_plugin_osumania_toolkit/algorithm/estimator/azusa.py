from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from typing import Any

from ..ett.calc import OfficialRunnerError, compute_difficulties
from .daniel import estimate_daniel_result
from .exceptions import UnsupportedKeyError
from .interlude import estimate_interlude_star_from_chart
from .rc import clamp, estimate_daniel_numeric, estimate_sunny_numeric, numeric_to_rc_label
from .shared import load_osu_chart
from .sunny import estimate_sunny_result


AZUSA_CONFIG = SimpleNamespace(
    rcLnRatioLimit=0.18,
    minNotes=80,
    rowToleranceMs=2,
    quantiles={
        "q99": 0.99,
        "q97": 0.97,
        "q94": 0.94,
    },
    skillWeights={
        "speed": 0.38,
        "stamina": 0.26,
        "chord": 0.18,
        "tech": 0.18,
    },
    localPower=2.15,
    postPower=3.4,
    decayWindowsMs=(140, 280, 560, 980),
    decayWeights=(0.34, 0.30, 0.22, 0.14),
    rcBlendWeights={
        "azusaResidual": 0.05,
        "sunnyResidual": 0.15,
        "lowRangeLift": 0.40,
        "danielFallback": 0.75,
        "azusaFallback": 0.20,
        "sunnyFallback": 0.08,
        "globalOffset": -0.50,
    },
)

AZUSA_CALIBRATION_LOW_BLOCKS = (
    (1.9220, 1.9220, 1.0000),
    (2.3660, 2.7684, 1.6667),
    (2.8394, 2.8394, 2.0000),
    (2.8584, 3.7162, 2.3333),
    (3.7798, 3.7798, 3.0000),
    (3.8667, 3.8667, 3.0000),
    (4.2067, 5.2039, 4.3333),
    (5.2506, 5.7713, 5.0667),
    (5.8603, 6.1512, 5.3333),
    (6.3292, 6.8785, 6.0000),
    (7.1715, 7.3617, 6.2000),
    (7.4079, 7.8734, 7.2000),
    (8.0160, 8.4003, 8.2500),
    (8.4133, 8.4133, 9.0000),
    (8.9031, 9.4775, 9.5667),
    (9.6488, 9.6488, 10.0000),
    (9.8301, 9.8301, 10.3000),
)

AZUSA_CALIBRATION_HIGH_BLOCKS = (
    (11.4336, 11.4336, 10.4000),
    (11.4436, 11.4436, 10.5000),
    (11.6012, 11.6665, 10.6500),
    (11.6696, 12.2317, 11.5000),
    (12.3295, 12.3919, 11.7500),
    (12.5238, 12.5238, 12.0000),
    (12.5318, 12.8329, 12.1400),
    (12.8605, 12.9781, 12.2800),
    (12.9868, 13.1170, 12.7800),
    (13.2003, 13.4418, 12.7857),
    (13.4660, 13.5829, 12.9250),
    (13.6044, 13.9924, 13.3667),
    (14.0583, 14.0583, 13.4000),
    (14.0795, 14.2266, 13.4600),
    (14.2346, 14.2346, 13.6000),
    (14.2414, 14.2414, 13.7000),
    (14.2903, 14.2903, 14.0000),
    (14.3258, 14.4760, 14.1200),
    (14.5365, 14.6006, 14.1333),
    (14.7269, 14.8716, 14.1333),
    (15.0048, 15.0048, 14.4000),
    (15.0521, 15.0521, 14.4000),
    (15.0521, 15.0521, 14.4000),
    (15.0950, 15.0950, 14.4000),
    (15.2335, 15.2335, 14.4000),
    (15.2388, 15.5821, 14.7385),
    (15.6977, 15.7002, 14.8500),
    (15.7535, 16.1593, 15.0667),
    (16.2009, 16.2958, 15.1000),
    (16.3172, 16.4748, 15.7600),
    (16.5620, 16.9083, 15.9833),
    (16.9485, 16.9485, 16.0000),
    (17.0216, 17.3799, 16.1000),
    (17.4616, 17.4616, 16.4000),
    (17.5167, 17.5167, 16.4000),
    (17.5306, 17.9077, 16.6400),
    (18.1973, 18.1973, 17.2000),
    (18.2026, 18.2026, 17.2000),
    (18.4562, 19.3477, 17.9500),
)

AZUSA_ISOTONIC_POINTS = (
    (1.2900, 1),
    (1.2900, 1),
    (1.3900, 1),
    (1.3900, 1),
    (1.4700, 1),
    (1.4700, 1),
    (1.9000, 2),
    (1.9000, 2),
    (2.0600, 2),
    (2.2200, 2),
    (2.3200, 2),
    (2.3200, 2),
    (2.5100, 3),
    (2.5100, 3),
    (2.9000, 3.3333333333333335),
    (2.9800, 3.3333333333333335),
    (4.0100, 4),
    (4.0100, 4),
    (4.5100, 4),
    (4.5100, 4),
    (4.8300, 4.2),
    (4.8300, 4.2),
    (4.9400, 5),
    (4.9400, 5),
    (5.0400, 5),
    (5.0400, 5),
    (5.2000, 5),
    (5.2000, 5),
    (5.2800, 5),
    (5.2800, 5),
    (5.3300, 5.666666666666667),
    (5.5900, 5.666666666666667),
    (5.7700, 6),
    (5.7700, 6),
    (5.8700, 6),
    (5.8700, 6),
    (5.8700, 6),
    (5.8700, 6),
    (6.0700, 6.6),
    (6.0700, 6.6),
    (6.3300, 6.733333333333333),
    (6.9200, 6.733333333333333),
    (7.1100, 7),
    (7.1100, 7),
    (7.4600, 8.3),
    (8.0500, 8.3),
    (8.2500, 8.333333333333334),
    (8.4800, 8.333333333333334),
    (9.3200, 9.183333333333334),
    (9.6200, 9.183333333333334),
    (9.6400, 9.5),
    (9.7100, 9.5),
    (9.9800, 10.325),
    (10.1500, 10.325),
    (10.3000, 10.37142857142857),
    (10.9900, 10.37142857142857),
    (11.0000, 10.9),
    (11.0400, 10.9),
    (11.0700, 11.22857142857143),
    (11.3600, 11.22857142857143),
    (11.4500, 11.866666666666667),
    (11.7400, 11.866666666666667),
    (11.9300, 12.0875),
    (12.2000, 12.0875),
    (12.2900, 12.466666666666667),
    (12.5200, 12.466666666666667),
    (12.5600, 12.5),
    (12.6400, 12.5),
    (12.7400, 12.56),
    (12.9200, 12.56),
    (12.9800, 12.6),
    (12.9800, 12.6),
    (12.9900, 12.7),
    (12.9900, 12.7),
    (13.0000, 13),
    (13.0000, 13),
    (13.0400, 13.266666666666667),
    (13.2800, 13.266666666666667),
    (13.2900, 13.533333333333333),
    (13.3300, 13.533333333333333),
    (13.3400, 13.55),
    (13.3600, 13.55),
    (13.4000, 13.62),
    (13.5600, 13.62),
    (13.7200, 13.8),
    (13.7200, 13.8),
    (13.9500, 14),
    (13.9500, 14),
    (14.0200, 14),
    (14.0200, 14),
    (14.0500, 14.05),
    (14.2000, 14.05),
    (14.2100, 14.199999999999998),
    (14.3400, 14.199999999999998),
    (14.3700, 14.266666666666666),
    (14.3700, 14.266666666666666),
    (14.4400, 14.4),
    (14.4400, 14.4),
    (14.4400, 14.4),
    (14.4400, 14.4),
    (14.4700, 14.5),
    (14.4700, 14.5),
    (14.5200, 14.674999999999999),
    (14.6700, 14.674999999999999),
    (14.8000, 14.825),
    (14.9000, 14.825),
    (14.9300, 15),
    (15.1500, 15),
    (15.3100, 15.2),
    (15.3500, 15.2),
    (15.3700, 15.666666666666666),
    (15.5300, 15.666666666666666),
    (15.5400, 15.675),
    (15.7200, 15.675),
    (15.7200, 15.8),
    (15.7200, 15.8),
    (15.7500, 15.9),
    (15.7500, 15.9),
    (15.7800, 16),
    (16.0700, 16),
    (16.0900, 16.266666666666666),
    (16.1500, 16.266666666666666),
    (16.3500, 16.4),
    (16.3500, 16.4),
    (16.3500, 16.4),
    (16.3500, 16.4),
    (16.4100, 16.4),
    (16.5100, 16.4),
    (16.5300, 16.533333333333335),
    (16.6500, 16.533333333333335),
    (17.5500, 17.2),
    (17.5500, 17.2),
    (17.6800, 17.2),
    (17.6800, 17.2),
    (17.9100, 17.95),
    (18.0200, 17.95),
)


def _to_fixed(value: float, digits: int) -> float:
    if not math.isfinite(value):
        return value
    quant = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def _safe_numeric(value: Any, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def safe_div(a: float, b: float, fallback: float = 0.0) -> float:
    if not math.isfinite(a) or not math.isfinite(b) or abs(b) < 1e-9:
        return fallback
    return a / b


def quantile_from_sorted(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0

    t = clamp(_safe_numeric(q, 0.0), 0.0, 1.0) * (len(sorted_values) - 1)
    left = math.floor(t)
    right = min(len(sorted_values) - 1, left + 1)
    weight = t - left
    return (sorted_values[left] * (1 - weight)) + (sorted_values[right] * weight)


def power_mean(values: list[float], power: float) -> float:
    if not values:
        return 0.0

    acc = 0.0
    for value in values:
        acc += math.pow(max(value, 0.0), power)
    return math.pow(acc / len(values), 1 / power)


def build_tap_notes(chart) -> list[dict[str, Any]]:
    taps: list[dict[str, Any]] = []
    columns = chart.columns or []
    starts = chart.note_starts or []

    for index in range(len(columns)):
        column = _safe_numeric(columns[index], math.nan)
        time = _safe_numeric(starts[index], math.nan)
        if not math.isfinite(column) or not math.isfinite(time):
            continue

        taps.append({"t": time, "c": int(column), "hand": 0 if column < 2 else 1, "rowSize": 1})

    taps.sort(key=lambda item: (item["t"], item["c"]))
    return taps


def annotate_rows(taps: list[dict[str, Any]], tolerance_ms: float) -> None:
    if not taps:
        return

    row_start = 0
    for index in range(1, len(taps) + 1):
        should_flush = index == len(taps) or abs(taps[index]["t"] - taps[row_start]["t"]) > tolerance_ms
        if not should_flush:
            continue

        row_size = index - row_start
        for sub_index in range(row_start, index):
            taps[sub_index]["rowSize"] = row_size
        row_start = index


def exp_decay_factor(dt_ms: float, tau_ms: float) -> float:
    if not math.isfinite(dt_ms) or dt_ms <= 0:
        return 1.0
    return math.exp(-dt_ms / tau_ms)


def skill_from_states(states: list[float]) -> float:
    total = 0.0
    for index, value in enumerate(states):
        total += value * AZUSA_CONFIG.decayWeights[index]
    return total


def build_difficulty_curve(taps: list[dict[str, Any]]) -> dict[str, Any]:
    states = {
        "speed": [0.0 for _ in AZUSA_CONFIG.decayWindowsMs],
        "stamina": [0.0 for _ in AZUSA_CONFIG.decayWindowsMs],
        "chord": [0.0 for _ in AZUSA_CONFIG.decayWindowsMs],
        "tech": [0.0 for _ in AZUSA_CONFIG.decayWindowsMs],
    }

    last_by_column = [-1e9, -1e9, -1e9, -1e9]
    last_by_hand = [-1e9, -1e9]

    density250: list[float] = []
    density500: list[float] = []
    jack_raw_series: list[float] = []
    column_counts = [0, 0, 0, 0]
    chord_note_count = 0
    cursor250 = 0
    cursor500 = 0

    local: list[float] = []
    speed_series: list[float] = []
    stamina_series: list[float] = []
    chord_series: list[float] = []
    tech_series: list[float] = []
    times: list[float] = []

    prev_time = taps[0]["t"] if taps else 0.0
    prev_any1 = -1e9
    prev_any2 = -1e9
    prev_col = 0

    for index, note in enumerate(taps):
        time = note["t"]
        column = note["c"]
        hand = note["hand"]
        row_size = note["rowSize"]

        column_counts[column] += 1
        if row_size >= 2:
            chord_note_count += 1

        dt_global = 0.0 if index == 0 else max(0.0, time - prev_time)
        dt_same = max(0.0, time - last_by_column[column])
        dt_hand = max(0.0, time - last_by_hand[hand])
        dt_any = max(0.0, time - prev_any1)

        while cursor250 < index and time - taps[cursor250]["t"] > 250:
            cursor250 += 1
        while cursor500 < index and time - taps[cursor500]["t"] > 500:
            cursor500 += 1

        density250.append((index - cursor250 + 1) / 0.25)
        density500.append((index - cursor500 + 1) / 0.5)

        jack = math.pow(190 / (dt_same + 35), 1.16)
        jack_raw_series.append(jack)
        stream = math.pow(170 / (dt_any + 30), 1.07)
        hand_stream = math.pow(185 / (dt_hand + 42), 1.08)

        movement = abs(column - prev_col) / 3
        rhythm_ratio = safe_div(max(dt_any, 1), max(time - prev_any2, 1), 1)
        rhythm_chaos = abs(math.log2(clamp(rhythm_ratio, 0.2, 5)))

        row_chord = max(0, row_size - 1)
        chord = math.pow(row_chord + 1, 1.22) - 1

        speed_input = 0.54 * stream + 0.28 * hand_stream + 0.18 * jack
        stamina_input = 0.48 * (density500[-1] / 11) + 0.27 * (density250[-1] / 15) + 0.25 * stream
        chord_input = chord * (1 + 0.22 * min(1.5, stream))
        tech_input = 0.45 * rhythm_chaos + 0.30 * movement + 0.25 * (1 + 0.3 * row_chord if row_chord > 0 else 0)

        for state_index, tau in enumerate(AZUSA_CONFIG.decayWindowsMs):
            decay = exp_decay_factor(dt_global, tau)
            states["speed"][state_index] = states["speed"][state_index] * decay + speed_input
            states["stamina"][state_index] = states["stamina"][state_index] * decay + stamina_input
            states["chord"][state_index] = states["chord"][state_index] * decay + chord_input
            states["tech"][state_index] = states["tech"][state_index] * decay + tech_input

        speed_skill = skill_from_states(states["speed"])
        stamina_skill = skill_from_states(states["stamina"])
        chord_skill = skill_from_states(states["chord"])
        tech_skill = skill_from_states(states["tech"])

        power = AZUSA_CONFIG.localPower
        combined = math.pow(
            (
                AZUSA_CONFIG.skillWeights["speed"] * math.pow(max(speed_skill, 0.0), power)
                + AZUSA_CONFIG.skillWeights["stamina"] * math.pow(max(stamina_skill, 0.0), power)
                + AZUSA_CONFIG.skillWeights["chord"] * math.pow(max(chord_skill, 0.0), power)
                + AZUSA_CONFIG.skillWeights["tech"] * math.pow(max(tech_skill, 0.0), power)
            )
            / (
                AZUSA_CONFIG.skillWeights["speed"]
                + AZUSA_CONFIG.skillWeights["stamina"]
                + AZUSA_CONFIG.skillWeights["chord"]
                + AZUSA_CONFIG.skillWeights["tech"]
            ),
            1 / power,
        )

        local.append(combined)
        speed_series.append(speed_skill)
        stamina_series.append(stamina_skill)
        chord_series.append(chord_skill)
        tech_series.append(tech_skill)
        times.append(time)

        prev_any2 = prev_any1
        prev_any1 = time
        prev_time = time
        prev_col = column
        last_by_column[column] = time
        last_by_hand[hand] = time

    return {
        "local": local,
        "speedSeries": speed_series,
        "staminaSeries": stamina_series,
        "chordSeries": chord_series,
        "techSeries": tech_series,
        "times": times,
        "density250": density250,
        "density500": density500,
        "jackRawSeries": jack_raw_series,
        "columnCounts": column_counts,
        "chordNoteCount": chord_note_count,
    }


def compute_azusa_numeric_from_curve(curve: dict[str, Any], note_count: int) -> float:
    local = curve["local"]
    if not local:
        return 0.0

    def summarize(values: list[float]) -> dict[str, float]:
        sorted_values = sorted(values)
        q97 = quantile_from_sorted(sorted_values, 0.97)
        q94 = quantile_from_sorted(sorted_values, 0.94)
        q90 = quantile_from_sorted(sorted_values, 0.90)
        q75 = quantile_from_sorted(sorted_values, 0.75)
        q50 = quantile_from_sorted(sorted_values, 0.50)
        tail_count = max(8, math.floor(len(sorted_values) * 0.04))
        tail_slice = sorted_values[-tail_count:]
        tail_mean = sum(tail_slice) / len(tail_slice)
        pm = power_mean(values, 2.6)
        return {
            "q97": q97,
            "q94": q94,
            "q90": q90,
            "q75": q75,
            "q50": q50,
            "tailMean": tail_mean,
            "pm": pm,
        }

    speed = summarize(curve["speedSeries"])
    stamina = summarize(curve["staminaSeries"])
    chord = summarize(curve["chordSeries"])
    tech = summarize(curve["techSeries"])

    density250 = power_mean(curve["density250"], 1.18)
    density500 = power_mean(curve["density500"], 1.12)
    length_boost = math.log1p(note_count / 140)

    peak_blend = (
        (0.26 * speed["q97"])
        + (0.24 * stamina["q97"])
        + (0.18 * chord["q97"])
        + (0.12 * tech["q97"])
        + (0.07 * speed["q90"])
        + (0.05 * stamina["q90"])
        + (0.03 * chord["q90"])
        + (0.02 * tech["q90"])
    )

    sustain_blend = (
        (0.20 * speed["q75"])
        + (0.18 * stamina["q75"])
        + (0.11 * chord["q75"])
        + (0.08 * tech["q75"])
        + (0.12 * speed["tailMean"])
        + (0.10 * stamina["tailMean"])
        + (0.06 * chord["tailMean"])
        + (0.05 * tech["tailMean"])
    )

    density_blend = (0.14 * math.log1p(density250)) + (0.22 * math.log1p(density500))
    mid_blend = (0.18 * speed["q50"]) + (0.15 * stamina["q50"]) + (0.10 * chord["q50"]) + (0.08 * tech["q50"])

    raw = (0.58 * peak_blend) + (0.24 * sustain_blend) + (0.10 * density_blend) + (0.08 * mid_blend) + (0.06 * length_boost)
    scaled = 0.82 + (0.41 * raw)

    max_column = max(curve["columnCounts"])
    anchor_imbalance = safe_div((max_column / max(note_count, 1)) - 0.25, 0.75, 0)
    chord_rate = safe_div(curve["chordNoteCount"], max(note_count, 1), 0)
    jack_sorted = sorted(curve["jackRawSeries"])
    jack_q95 = quantile_from_sorted(jack_sorted, 0.95)

    jack_anchor_boost = clamp(
        1.65
        * max(0.0, anchor_imbalance)
        * max(0.0, 1 - (1.85 * chord_rate))
        * max(0.0, jack_q95 - 2.2),
        0,
        2.2,
    )

    low_jack_boost = clamp(
        1.1
        * clamp((12.2 - scaled) / 4.5, 0, 1)
        * max(0.0, anchor_imbalance - 0.08)
        * max(0.0, jack_q95 - 1.7)
        * (0.9 + (0.6 * max(0.0, 0.22 - chord_rate))),
        0,
        1.35,
    )

    corrected = scaled + jack_anchor_boost + low_jack_boost
    return clamp(corrected, -2, 20)


def resolve_rc_blend_components(
    primary_numeric: float | None,
    daniel_numeric: float | None,
    sunny_numeric: float | None,
    curve_hints: dict[str, float] | None = None,
) -> dict[str, Any]:
    primary = primary_numeric if primary_numeric is not None and math.isfinite(primary_numeric) else None
    daniel = daniel_numeric if daniel_numeric is not None and math.isfinite(daniel_numeric) else None
    sunny = sunny_numeric if sunny_numeric is not None and math.isfinite(sunny_numeric) else None

    if daniel is None and primary is None and sunny is None:
        return {
            "value": None,
            "lowGateSource": None,
            "lowGate": None,
            "highGate": None,
            "lowBase": None,
            "highBase": None,
        }

    low_gate_source = daniel if daniel is not None else (sunny if sunny is not None else (primary if primary is not None else 0))
    low_gate = clamp((9.61 - low_gate_source) / 4.94, 0, 1)
    high_gate = 1 - low_gate

    low_base = None
    if sunny is not None:
        value = (-8.317) + (1.536 * sunny)
        if primary is not None:
            value += 0.011 * primary
        if daniel is not None:
            value += 0.049 * daniel

        if low_gate > 0:
            primary_part = max(0.0, primary - 10.4) if primary is not None else 0.0
            sunny_part = max(0.0, sunny - 9.84)
            low_sunny_convex = math.pow(max(0.0, 7.935 - sunny), 2)
            value += low_gate * ((0.442 * sunny_part) + (0.016 * primary_part) + (0.235 * low_sunny_convex))

        low_base = value

    high_base = None
    d_use = daniel if daniel is not None else (sunny if sunny is not None else primary)
    if d_use is not None:
        primary_use = primary if primary is not None else d_use
        sunny_use = sunny if sunny is not None else d_use

        value = (0.809 * d_use) + (0.057 * primary_use) + (0.165 * sunny_use) + 0.183

        high_mask = clamp((low_gate_source - 14.83) / 2.667, 0, 1)
        if high_mask > 0:
            value += high_mask * ((-0.154 * max(0.0, primary_use - d_use)) + (0.081 * max(0.0, sunny_use - d_use)))

        anchor_imbalance = curve_hints.get("anchorImbalance") if curve_hints else None
        chord_rate = curve_hints.get("chordRate") if curve_hints else None
        jack_q95 = curve_hints.get("jackQ95") if curve_hints else None
        if anchor_imbalance is not None and chord_rate is not None and jack_q95 is not None:
            anchor_lift = clamp(
                0.96
                * max(0.0, jack_q95 - 2.08)
                * max(0.0, 0.24 - chord_rate)
                * max(0.0, anchor_imbalance - 0.10),
                0,
                0.88,
            )
            value += anchor_lift

        high_base = value

    low_lift = max(0.0, 9.889 - low_gate_source) * 0.257 if math.isfinite(low_gate_source) else 0.0

    if low_base is None and high_base is None:
        return {
            "value": None,
            "lowGateSource": low_gate_source,
            "lowGate": low_gate,
            "highGate": high_gate,
            "lowBase": low_base,
            "highBase": high_base,
        }

    if low_base is None:
        value = high_base
    elif high_base is None:
        value = low_base + low_lift
    else:
        value = (low_base * low_gate) + ((high_base + low_lift) * high_gate)

    return {
        "value": value,
        "lowGateSource": low_gate_source,
        "lowGate": low_gate,
        "highGate": high_gate,
        "lowBase": low_base,
        "highBase": high_base,
    }


def interpolate_calibration(value: float, knots: tuple[tuple[float, float], ...]) -> float:
    x = float(value)
    if not math.isfinite(x) or len(knots) < 2:
        return x

    if x <= knots[0][0]:
        return knots[0][1]

    last = len(knots) - 1
    if x >= knots[last][0]:
        return knots[last][1]

    for index in range(last):
        x0, y0 = knots[index]
        x1, y1 = knots[index + 1]
        if x0 <= x <= x1:
            return y0 + safe_div((x - x0) * (y1 - y0), x1 - x0, 0)

    return x


def interpolate_calibration_blocks(value: float, blocks: tuple[tuple[float, float, float], ...]) -> float:
    x = float(value)
    if not math.isfinite(x) or not blocks:
        return x

    if x <= blocks[0][0]:
        return blocks[0][2]

    for index, (x0, x1, y) in enumerate(blocks):
        if x0 <= x <= x1:
            return y

        if index < len(blocks) - 1:
            next_x0 = blocks[index + 1][0]
            if x > x1 and x < next_x0:
                t = safe_div(x - x1, next_x0 - x1, 0)
                return (y * (1 - t)) + (blocks[index + 1][2] * t)

    return blocks[-1][2]


def calibrate_azusa_numeric(value: float, low_gate: float | None = None, high_gate: float | None = None) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        return numeric

    low = interpolate_calibration_blocks(numeric, AZUSA_CALIBRATION_LOW_BLOCKS)
    high = interpolate_calibration_blocks(numeric, AZUSA_CALIBRATION_HIGH_BLOCKS)

    lg = clamp(float(low_gate), 0, 1) if low_gate is not None and math.isfinite(low_gate) else None
    hg = clamp(float(high_gate), 0, 1) if high_gate is not None and math.isfinite(high_gate) else None

    if lg is None and hg is None:
        return low if numeric < 11 else high

    low_weight = lg if lg is not None else max(0.0, 1 - (hg if hg is not None else 0))
    high_weight = hg if hg is not None else max(0.0, 1 - low_weight)
    weight_sum = low_weight + high_weight
    if weight_sum <= 1e-6:
        return low if numeric < 11 else high

    return ((low_weight * low) + (high_weight * high)) / weight_sum


def calibrate_azusa_output_numeric(value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        return numeric

    return interpolate_calibration(numeric, AZUSA_ISOTONIC_POINTS)


def compute_curve_gap_residual_correction(
    base_numeric: float,
    blend_details: dict[str, Any],
    curve_stats: dict[str, float],
    primary_numeric: float | None,
    sunny_numeric: float | None,
    daniel_numeric: float | None,
) -> float:
    x = float(base_numeric)
    if not math.isfinite(x):
        return 0.0

    high_gate = clamp(blend_details.get("highGate", 0) or 0, 0, 1)
    primary = primary_numeric if primary_numeric is not None and math.isfinite(primary_numeric) else x
    sunny = sunny_numeric if sunny_numeric is not None and math.isfinite(sunny_numeric) else x
    daniel = daniel_numeric if daniel_numeric is not None and math.isfinite(daniel_numeric) else x
    ds = daniel - sunny
    sp = sunny - primary
    anchor_imbalance = curve_stats.get("anchorImbalance", 0) or 0
    chord_rate = curve_stats.get("chordRate", 0) or 0
    jack_q95 = curve_stats.get("jackQ95", 0) or 0

    residual = (
        4.335282
        + (-0.170459 * x)
        + (-1.622303 * max(0, 11 - x))
        + (1.328125 * max(0, 12.5 - x))
        + (-0.042829 * max(0, 14 - x))
        + (-0.834997 * high_gate)
        + (3.060352 * high_gate * max(0, 11 - x))
        + (-1.744638 * high_gate * max(0, 12.5 - x))
        + (0.409922 * ds)
        + (0.041072 * sp)
        + (-0.388231 * high_gate * ds)
        + (-0.170185 * high_gate * sp)
        + (3.466868 * anchor_imbalance)
        + (-1.743778 * chord_rate)
        + (-0.094758 * jack_q95)
        + (2.626366 * anchor_imbalance * jack_q95)
        + (1.836357 * chord_rate * jack_q95)
        + (-2.612648 * high_gate * anchor_imbalance)
        + (-2.493596 * high_gate * chord_rate)
    )

    return clamp(residual, -1.2, 1.2)


def compute_post_output_curve_gap_residual_correction(
    base_numeric: float,
    blend_details: dict[str, Any],
    curve_stats: dict[str, float],
    primary_numeric: float | None,
    sunny_numeric: float | None,
    daniel_numeric: float | None,
) -> float:
    x = float(base_numeric)
    if not math.isfinite(x):
        return 0.0

    high_gate = clamp(blend_details.get("highGate", 0) or 0, 0, 1)
    primary = primary_numeric if primary_numeric is not None and math.isfinite(primary_numeric) else x
    sunny = sunny_numeric if sunny_numeric is not None and math.isfinite(sunny_numeric) else x
    daniel = daniel_numeric if daniel_numeric is not None and math.isfinite(daniel_numeric) else x
    anchor_imbalance = curve_stats.get("anchorImbalance", 0) or 0
    chord_rate = curve_stats.get("chordRate", 0) or 0
    jack_q95 = curve_stats.get("jackQ95", x) or x

    ds = daniel - sunny
    sp = sunny - primary

    residual = 0.4 * (
        0.979895
        + (0.053556 * x)
        + (-1.050405 * max(0, 11 - x))
        + (0.942552 * max(0, 12.5 - x))
        + (0.048841 * max(0, 14 - x))
        + (-1.636218 * high_gate)
        + (0.956025 * high_gate * max(0, 11 - x))
        + (-0.975188 * high_gate * max(0, 12.5 - x))
        + (0.195107 * ds)
        + (-0.064291 * sp)
        + (-0.231542 * high_gate * ds)
        + (0.082201 * high_gate * sp)
        + (-0.634013 * anchor_imbalance)
        + (-0.490303 * chord_rate)
        + (-0.135176 * jack_q95)
        + (-0.992539 * anchor_imbalance * jack_q95)
        + (-0.164219 * chord_rate * jack_q95)
        + (-1.027392 * high_gate * anchor_imbalance)
        + (0.961530 * high_gate * chord_rate)
    )

    return clamp(residual, -1.0, 1.0)


def estimate_azusa_result(
    source: Any,
    speed_rate: float = 1.0,
    od_flag: Any = None,
    cvt_flag: Any = None,
    *,
    sunny_result: dict[str, Any] | None = None,
    daniel_result: dict[str, Any] | None = None,
    with_graph: bool = False,
    force_sunny_reference_ho: bool = True,
) -> dict[str, Any]:
    chart = load_osu_chart(source)
    if int(chart.column_count) != 4:
        raise UnsupportedKeyError("Azusa only supports 4K")

    if sunny_result is None:
        sunny_cvt_flag = "HO" if force_sunny_reference_ho else cvt_flag
        sunny_result = estimate_sunny_result(source, speed_rate, od_flag, sunny_cvt_flag)

    sunny_star = _safe_numeric(sunny_result.get("star"), math.nan)
    if not math.isfinite(sunny_star):
        sunny_star = 0.0

    sunny_numeric = estimate_sunny_numeric(sunny_result)
    if sunny_numeric is None:
        sunny_numeric = 0.0

    if daniel_result is None:
        try:
            daniel_result = estimate_daniel_result(source, speed_rate, od_flag, cvt_flag, sunny_result=sunny_result)
        except Exception:
            daniel_result = None

    daniel_numeric = estimate_daniel_numeric(daniel_result) if daniel_result is not None else None
    if daniel_numeric is None:
        daniel_numeric = sunny_numeric

    interlude_star = estimate_interlude_star_from_chart(chart, speed_rate, cvt_flag)
    if not math.isfinite(interlude_star):
        interlude_star = sunny_star

    try:
        msd_values = compute_difficulties(chart, music_rate=speed_rate, keycount=4, score_goal=0.93)
        overall = _safe_numeric(msd_values.get("Overall", sunny_numeric), sunny_numeric)
        stream = _safe_numeric(msd_values.get("Stream", overall), overall)
        jumpstream = _safe_numeric(msd_values.get("Jumpstream", overall), overall)
        handstream = _safe_numeric(msd_values.get("Handstream", overall), overall)
        stamina = _safe_numeric(msd_values.get("Stamina", overall), overall)
        jackspeed = _safe_numeric(msd_values.get("JackSpeed", overall), overall)
        chordjack = _safe_numeric(msd_values.get("Chordjack", overall), overall)
        technical = _safe_numeric(msd_values.get("Technical", overall), overall)
    except OfficialRunnerError:
        overall = sunny_numeric
        stream = sunny_numeric * 0.98
        jumpstream = sunny_numeric * 0.95
        handstream = sunny_numeric * 0.94
        stamina = sunny_numeric * 1.03
        jackspeed = sunny_numeric * 0.92
        chordjack = sunny_numeric * 0.90
        technical = sunny_numeric * 0.96

    taps = build_tap_notes(chart)
    if len(taps) < AZUSA_CONFIG.minNotes:
        raise UnsupportedKeyError("Azusa only supports 4K maps with at least 80 notes")

    annotate_rows(taps, AZUSA_CONFIG.rowToleranceMs)
    curve = build_difficulty_curve(taps)
    primary_numeric = compute_azusa_numeric_from_curve(curve, len(taps))

    max_column = max(curve["columnCounts"]) if curve["columnCounts"] else 0
    anchor_imbalance = safe_div((max_column / max(len(taps), 1)) - 0.25, 0.75, 0)
    chord_rate = safe_div(curve["chordNoteCount"], max(len(taps), 1), 0)
    jack_q95 = quantile_from_sorted(sorted(curve["jackRawSeries"]), 0.95)

    blend_details = resolve_rc_blend_components(
        primary_numeric,
        daniel_numeric,
        sunny_numeric,
        {"anchorImbalance": anchor_imbalance, "chordRate": chord_rate, "jackQ95": jack_q95},
    )
    numeric_difficulty = blend_details["value"]
    calibrated_numeric = calibrate_azusa_numeric(numeric_difficulty, blend_details["lowGate"], blend_details["highGate"])
    curve_gap_residual = compute_curve_gap_residual_correction(
        calibrated_numeric,
        blend_details,
        {"anchorImbalance": anchor_imbalance, "chordRate": chord_rate, "jackQ95": jack_q95},
        primary_numeric,
        sunny_numeric,
        daniel_numeric,
    )
    pre_output_numeric = clamp(_safe_numeric(calibrated_numeric, 0.0) + curve_gap_residual, -2, 20)
    output_numeric = calibrate_azusa_output_numeric(pre_output_numeric)
    post_curve_gap_residual = compute_post_output_curve_gap_residual_correction(
        output_numeric,
        blend_details,
        {"anchorImbalance": anchor_imbalance, "chordRate": chord_rate, "jackQ95": jack_q95},
        primary_numeric,
        sunny_numeric,
        daniel_numeric,
    )
    final_numeric = clamp(_safe_numeric(output_numeric, 0.0) + post_curve_gap_residual, -2, 20)

    return {
        "star": _to_fixed(3.4 + 0.38 * final_numeric, 4),
        "lnRatio": _safe_numeric(chart.LN_ratio, 0.0),
        "columnCount": int(chart.column_count),
        "estDiff": numeric_to_rc_label(final_numeric),
        "numericDifficulty": _to_fixed(final_numeric, 2),
        "numericDifficultyHint": "azusa-rc-v1",
        "graph": sunny_result.get("graph") if with_graph else None,
        "rawNumericDifficulty": _to_fixed(primary_numeric, 4),
        "debug": {
            "primaryNumeric": _to_fixed(primary_numeric, 4),
            "blendNumeric": _to_fixed(numeric_difficulty, 4) if numeric_difficulty is not None and math.isfinite(numeric_difficulty) else None,
            "danielNumeric": _to_fixed(daniel_numeric, 4) if daniel_numeric is not None and math.isfinite(daniel_numeric) else None,
            "sunnyNumeric": _to_fixed(sunny_numeric, 4) if sunny_numeric is not None and math.isfinite(sunny_numeric) else None,
            "notes": len(taps),
            "calibratedNumeric": _to_fixed(calibrated_numeric, 4) if math.isfinite(calibrated_numeric) else None,
            "curveStats": {
                "anchorImbalance": _to_fixed(anchor_imbalance, 4) if math.isfinite(anchor_imbalance) else None,
                "chordRate": _to_fixed(chord_rate, 4) if math.isfinite(chord_rate) else None,
                "jackQ95": _to_fixed(jack_q95, 4) if math.isfinite(jack_q95) else None,
            },
            "curveGapResidual": _to_fixed(curve_gap_residual, 4) if math.isfinite(curve_gap_residual) else None,
            "outputNumeric": _to_fixed(output_numeric, 4) if math.isfinite(output_numeric) else None,
            "postCurveGapResidual": _to_fixed(post_curve_gap_residual, 4) if math.isfinite(post_curve_gap_residual) else None,
            "finalNumeric": _to_fixed(final_numeric, 4) if math.isfinite(final_numeric) else None,
            "blend": {
                "lowGateSource": f"{blend_details['lowGateSource']:.4f}" if blend_details.get("lowGateSource") is not None and math.isfinite(blend_details["lowGateSource"]) else None,
                "lowGate": f"{blend_details['lowGate']:.4f}" if blend_details.get("lowGate") is not None and math.isfinite(blend_details["lowGate"]) else None,
                "highGate": f"{blend_details['highGate']:.4f}" if blend_details.get("highGate") is not None and math.isfinite(blend_details["highGate"]) else None,
                "lowBase": f"{blend_details['lowBase']:.4f}" if blend_details.get("lowBase") is not None and math.isfinite(blend_details["lowBase"]) else None,
                "highBase": f"{blend_details['highBase']:.4f}" if blend_details.get("highBase") is not None and math.isfinite(blend_details["highBase"]) else None,
            },
        },
    }