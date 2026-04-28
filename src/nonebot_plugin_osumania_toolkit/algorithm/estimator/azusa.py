from __future__ import annotations

import math

from .daniel import estimate_daniel_result
from .exceptions import UnsupportedKeyError
from .rc import estimate_daniel_numeric as _rc_estimate_daniel_numeric
from .rc import estimate_sunny_numeric as _rc_estimate_sunny_numeric
from .rc import numeric_to_rc_label
from .shared import load_osu_chart
from .sunny import estimate_sunny_result
from ...data import estimator_data

# ============================================================
# Constants (exact match with JS AZUSA_CONFIG and calibration data)
# ============================================================

AZUSA_CONFIG = estimator_data.AZUSA_CONFIG
GREEK_BY_INDEX = estimator_data.GREEK_BY_INDEX
RC_TIER_CANDIDATES = estimator_data.RC_TIER_CANDIDATES
AZUSA_CALIBRATION_LOW_BLOCKS = estimator_data.AZUSA_CALIBRATION_LOW_BLOCKS
AZUSA_CALIBRATION_HIGH_BLOCKS = estimator_data.AZUSA_CALIBRATION_HIGH_BLOCKS
AZUSA_ISOTONIC_POINTS = estimator_data.AZUSA_ISOTONIC_POINTS


# ============================================================
# Helper functions
# ============================================================

def _clamp_scalar(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _safe_float(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _safe_div(a, b, fallback=0.0):
    if not math.isfinite(a) or not math.isfinite(b) or abs(b) < 1e-9:
        return fallback
    return a / b


def _quantile_from_sorted(sorted_values, q):
    if not sorted_values:
        return 0.0
    t = _clamp_scalar(float(q), 0.0, 1.0) * (len(sorted_values) - 1)
    left = int(t)
    right = min(len(sorted_values) - 1, left + 1)
    w = t - left
    return sorted_values[left] * (1.0 - w) + sorted_values[right] * w


def _power_mean(values, p):
    if not values:
        return 0.0
    acc = 0.0
    for v in values:
        acc += math.pow(max(v, 0.0), p)
    return math.pow(acc / len(values), 1.0 / p)


def _exp_decay_factor(dt_ms, tau_ms):
    if not math.isfinite(dt_ms) or dt_ms <= 0:
        return 1.0
    return math.exp(-dt_ms / tau_ms)


def _interpolate_calibration(x, knots):
    if not math.isfinite(x) or len(knots) < 2:
        return x
    if x <= knots[0][0]:
        return knots[0][1]
    last = len(knots) - 1
    if x >= knots[last][0]:
        return knots[last][1]
    for i in range(last):
        x0, y0 = knots[i][0], knots[i][1]
        x1, y1 = knots[i + 1][0], knots[i + 1][1]
        if x0 <= x <= x1:
            return y0 + _safe_div((x - x0) * (y1 - y0), x1 - x0, 0.0)
    return x


def _interpolate_calibration_blocks(x, blocks):
    if not math.isfinite(x) or not blocks:
        return x
    if x <= blocks[0][0]:
        return blocks[0][2]
    for i in range(len(blocks)):
        x0, x1, y = blocks[i]
        if x0 <= x <= x1:
            return y
        if i < len(blocks) - 1:
            next_block = blocks[i + 1]
            nx0 = next_block[0]
            if x1 < x < nx0:
                t = _safe_div(x - x1, nx0 - x1, 0.0)
                return y * (1.0 - t) + next_block[2] * t
    return blocks[-1][2]


def _has_daniel_native_numeric(result):
    if result is None:
        return False
    raw = result.get("numericDifficulty") if isinstance(result, dict) else getattr(result, "numericDifficulty", None)
    if isinstance(raw, (int, float)):
        return math.isfinite(raw)
    if isinstance(raw, str) and raw.strip():
        v = _safe_float(raw)
        return v is not None
    return False


def _estimate_daniel_numeric(result):
    if result is None:
        return None
    numeric_raw = result.get("numericDifficulty") if isinstance(result, dict) else getattr(result, "numericDifficulty", None)
    if isinstance(numeric_raw, (int, float)) and math.isfinite(numeric_raw):
        return float(numeric_raw)
    if isinstance(numeric_raw, str) and numeric_raw.strip():
        v = _safe_float(numeric_raw)
        if v is not None:
            return v
    return _rc_estimate_daniel_numeric(result)


def _estimate_sunny_numeric(result):
    return _rc_estimate_sunny_numeric(result)


# ============================================================
# Tap note construction
# ============================================================

def _build_tap_notes(parsed_data):
    column_count, columns, note_starts, note_ends, note_types, *_ = parsed_data
    taps = []
    for i in range(len(columns)):
        col = int(columns[i])
        t = int(note_starts[i])
        if not (0 <= col < column_count):
            continue
        taps.append({
            "t": float(t),
            "c": col,
            "hand": 0 if col < 2 else 1,
            "rowSize": 1,
        })
    taps.sort(key=lambda n: (n["t"], n["c"]))
    return taps


def _annotate_rows(taps, tolerance_ms):
    if not taps:
        return
    row_start = 0
    for i in range(1, len(taps) + 1):
        should_flush = i == len(taps) or abs(taps[i]["t"] - taps[row_start]["t"]) > tolerance_ms
        if not should_flush:
            continue
        row_size = i - row_start
        for j in range(row_start, i):
            taps[j]["rowSize"] = row_size
        row_start = i


# ============================================================
# Difficulty curve
# ============================================================

def _skill_from_states(states, weights):
    s = 0.0
    for i in range(len(states)):
        s += states[i] * weights[i]
    return s


def _build_difficulty_curve(taps):
    n_windows = len(AZUSA_CONFIG["decayWindowsMs"])
    states = {
        "speed": [0.0] * n_windows,
        "stamina": [0.0] * n_windows,
        "chord": [0.0] * n_windows,
        "tech": [0.0] * n_windows,
    }
    last_by_column = [-1e9, -1e9, -1e9, -1e9]
    last_by_hand = [-1e9, -1e9]
    density250 = []
    density500 = []
    jack_raw_series = []
    column_counts = [0, 0, 0, 0]
    chord_note_count = 0
    cursor250 = 0
    cursor500 = 0
    local_vals = []
    speed_series = []
    stamina_series = []
    chord_series = []
    tech_series = []
    times = []
    prev_time = taps[0]["t"] if taps else 0.0
    prev_any1 = -1e9
    prev_any2 = -1e9
    prev_col = 0

    for i in range(len(taps)):
        note = taps[i]
        t = note["t"]
        c = note["c"]
        column_counts[c] += 1
        if note["rowSize"] >= 2:
            chord_note_count += 1

        dt_global = 0.0 if i == 0 else max(0.0, t - prev_time)
        dt_same = max(0.0, t - last_by_column[c])
        dt_hand = max(0.0, t - last_by_hand[note["hand"]])
        dt_any = max(0.0, t - prev_any1)

        while cursor250 < i and t - taps[cursor250]["t"] > 250:
            cursor250 += 1
        while cursor500 < i and t - taps[cursor500]["t"] > 500:
            cursor500 += 1

        d250 = (i - cursor250 + 1) / 0.25
        d500 = (i - cursor500 + 1) / 0.5
        density250.append(d250)
        density500.append(d500)

        jack = math.pow(190.0 / (dt_same + 35.0), 1.16)
        jack_raw_series.append(jack)
        stream = math.pow(170.0 / (dt_any + 30.0), 1.07)
        hand_stream = math.pow(185.0 / (dt_hand + 42.0), 1.08)

        movement = abs(c - prev_col) / 3.0
        rhythm_ratio = _safe_div(max(dt_any, 1.0), max(t - prev_any2, 1.0), 1.0)
        rhythm_chaos = abs(math.log2(_clamp_scalar(rhythm_ratio, 0.2, 5.0)))

        row_chord = max(0, note["rowSize"] - 1)
        chord = math.pow(row_chord + 1, 1.22) - 1.0

        speed_input = 0.54 * stream + 0.28 * hand_stream + 0.18 * jack
        stamina_input = 0.48 * (d500 / 11.0) + 0.27 * (d250 / 15.0) + 0.25 * stream
        chord_input = chord * (1.0 + 0.22 * min(1.5, stream))
        tech_input = 0.45 * rhythm_chaos + 0.30 * movement + 0.25 * (1.0 + 0.3 * row_chord if row_chord > 0 else 0.0)

        for j in range(n_windows):
            tau = AZUSA_CONFIG["decayWindowsMs"][j]
            decay = _exp_decay_factor(dt_global, tau)
            states["speed"][j] = states["speed"][j] * decay + speed_input
            states["stamina"][j] = states["stamina"][j] * decay + stamina_input
            states["chord"][j] = states["chord"][j] * decay + chord_input
            states["tech"][j] = states["tech"][j] * decay + tech_input

        dw = AZUSA_CONFIG["decayWeights"]
        speed_skill = _skill_from_states(states["speed"], dw)
        stamina_skill = _skill_from_states(states["stamina"], dw)
        chord_skill = _skill_from_states(states["chord"], dw)
        tech_skill = _skill_from_states(states["tech"], dw)

        p = AZUSA_CONFIG["localPower"]
        sw = AZUSA_CONFIG["skillWeights"]
        combined = math.pow(
            (
                sw["speed"] * math.pow(max(speed_skill, 0.0), p)
                + sw["stamina"] * math.pow(max(stamina_skill, 0.0), p)
                + sw["chord"] * math.pow(max(chord_skill, 0.0), p)
                + sw["tech"] * math.pow(max(tech_skill, 0.0), p)
            )
            / (sw["speed"] + sw["stamina"] + sw["chord"] + sw["tech"]),
            1.0 / p,
        )

        local_vals.append(combined)
        speed_series.append(speed_skill)
        stamina_series.append(stamina_skill)
        chord_series.append(chord_skill)
        tech_series.append(tech_skill)
        times.append(t)

        prev_any2 = prev_any1
        prev_any1 = t
        prev_time = t
        prev_col = c
        last_by_column[c] = t
        last_by_hand[note["hand"]] = t

    return {
        "local": local_vals,
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


# ============================================================
# Compute Azusa numeric from curve
# ============================================================

def _compute_azusa_numeric_from_curve(curve, note_count):
    local_vals = curve["local"]
    if not local_vals:
        return 0.0

    def summarize(values):
        sorted_vals = sorted(values)
        q97 = _quantile_from_sorted(sorted_vals, 0.97)
        q94 = _quantile_from_sorted(sorted_vals, 0.94)
        q90 = _quantile_from_sorted(sorted_vals, 0.90)
        q75 = _quantile_from_sorted(sorted_vals, 0.75)
        q50 = _quantile_from_sorted(sorted_vals, 0.50)
        tail_count = max(8, int(len(sorted_vals) * 0.04))
        tail_slice = sorted_vals[-tail_count:]
        tail_mean = sum(tail_slice) / len(tail_slice) if tail_slice else 0.0
        pm = _power_mean(values, 2.6)
        return {"q97": q97, "q94": q94, "q90": q90, "q75": q75, "q50": q50, "tailMean": tail_mean, "pm": pm}

    speed = summarize(curve["speedSeries"])
    stamina = summarize(curve["staminaSeries"])
    chord = summarize(curve["chordSeries"])
    tech = summarize(curve["techSeries"])

    density250 = _power_mean(curve["density250"], 1.18)
    density500 = _power_mean(curve["density500"], 1.12)
    length_boost = math.log1p(note_count / 140.0)

    peak_blend = (
        0.26 * speed["q97"]
        + 0.24 * stamina["q97"]
        + 0.18 * chord["q97"]
        + 0.12 * tech["q97"]
        + 0.07 * speed["q90"]
        + 0.05 * stamina["q90"]
        + 0.03 * chord["q90"]
        + 0.02 * tech["q90"]
    )

    sustain_blend = (
        0.20 * speed["q75"]
        + 0.18 * stamina["q75"]
        + 0.11 * chord["q75"]
        + 0.08 * tech["q75"]
        + 0.12 * speed["tailMean"]
        + 0.10 * stamina["tailMean"]
        + 0.06 * chord["tailMean"]
        + 0.05 * tech["tailMean"]
    )

    density_blend = 0.14 * math.log1p(density250) + 0.22 * math.log1p(density500)
    mid_blend = 0.18 * speed["q50"] + 0.15 * stamina["q50"] + 0.10 * chord["q50"] + 0.08 * tech["q50"]

    raw = 0.58 * peak_blend + 0.24 * sustain_blend + 0.10 * density_blend + 0.08 * mid_blend + 0.06 * length_boost
    scaled = 0.82 + 0.41 * raw

    max_column = max(curve["columnCounts"])
    anchor_imbalance = _safe_div((max_column / max(note_count, 1)) - 0.25, 0.75, 0.0)
    chord_rate = _safe_div(curve["chordNoteCount"], max(note_count, 1), 0.0)
    jack_sorted = sorted(curve["jackRawSeries"])
    jack_q95 = _quantile_from_sorted(jack_sorted, 0.95)

    jack_anchor_boost = _clamp_scalar(
        1.65
        * max(0.0, anchor_imbalance)
        * max(0.0, 1.0 - (1.85 * chord_rate))
        * max(0.0, jack_q95 - 2.2),
        0.0,
        2.2,
    )

    low_jack_boost = _clamp_scalar(
        1.1
        * _clamp_scalar((12.2 - scaled) / 4.5, 0.0, 1.0)
        * max(0.0, anchor_imbalance - 0.08)
        * max(0.0, jack_q95 - 1.7)
        * (0.9 + 0.6 * max(0.0, 0.22 - chord_rate)),
        0.0,
        1.35,
    )

    corrected = scaled + jack_anchor_boost + low_jack_boost
    return _clamp_scalar(corrected, -2.0, 20.0)


# ============================================================
# Blend components (RC blend)
# ============================================================

def _resolve_rc_blend_components(primary_numeric, daniel_numeric, sunny_numeric, curve_hints=None):
    primary = primary_numeric if (primary_numeric is not None and math.isfinite(primary_numeric)) else None
    daniel = daniel_numeric if (daniel_numeric is not None and math.isfinite(daniel_numeric)) else None
    sunny = sunny_numeric if (sunny_numeric is not None and math.isfinite(sunny_numeric)) else None

    if daniel is None and primary is None and sunny is None:
        return {"value": None, "lowGateSource": None, "lowGate": None, "highGate": None, "lowBase": None, "highBase": None}

    low_gate_source = daniel if daniel is not None else (sunny if sunny is not None else (primary if primary is not None else 0.0))
    low_gate = _clamp_scalar((9.61 - low_gate_source) / 4.94, 0.0, 1.0)
    high_gate = 1.0 - low_gate

    # lowBase
    low_base = None
    if sunny is not None:
        value = -8.317 + 1.536 * sunny
        if primary is not None:
            value += 0.011 * primary
        if daniel is not None:
            value += 0.049 * daniel

        if low_gate > 0:
            primary_part = max(0.0, primary - 10.4) if primary is not None else 0.0
            sunny_part = max(0.0, sunny - 9.84)
            low_sunny_convex = math.pow(max(0.0, 7.935 - sunny), 2.0)
            value += low_gate * (0.442 * sunny_part + 0.016 * primary_part + 0.235 * low_sunny_convex)

        low_base = value

    # highBase
    high_base = None
    d_use = daniel if daniel is not None else (sunny if sunny is not None else primary)
    if d_use is not None:
        primary_use = primary if primary is not None else d_use
        sunny_use = sunny if sunny is not None else d_use

        value = 0.809 * d_use + 0.057 * primary_use + 0.165 * sunny_use + 0.183

        high_mask = _clamp_scalar((low_gate_source - 14.83) / 2.667, 0.0, 1.0)
        if high_mask > 0:
            value += high_mask * (
                -0.154 * max(0.0, primary_use - d_use)
                + 0.081 * max(0.0, sunny_use - d_use)
            )

        if curve_hints is not None:
            anchor_imb = curve_hints.get("anchorImbalance")
            chord_rt = curve_hints.get("chordRate")
            jack_q95_val = curve_hints.get("jackQ95")
            if (
                anchor_imb is not None and math.isfinite(anchor_imb)
                and chord_rt is not None and math.isfinite(chord_rt)
                and jack_q95_val is not None and math.isfinite(jack_q95_val)
            ):
                anchor_lift = _clamp_scalar(
                    0.96
                    * max(0.0, jack_q95_val - 2.08)
                    * max(0.0, 0.24 - chord_rt)
                    * max(0.0, anchor_imb - 0.10),
                    0.0,
                    0.88,
                )
                value += anchor_lift

        high_base = value

    low_lift = max(0.0, 9.889 - low_gate_source) * 0.257 if math.isfinite(low_gate_source) else 0.0

    if low_base is None and high_base is None:
        return {"value": None, "lowGateSource": low_gate_source, "lowGate": low_gate, "highGate": high_gate, "lowBase": low_base, "highBase": high_base}

    if low_base is None:
        return {"value": high_base, "lowGateSource": low_gate_source, "lowGate": low_gate, "highGate": high_gate, "lowBase": low_base, "highBase": high_base}

    if high_base is None:
        return {"value": low_base + low_lift, "lowGateSource": low_gate_source, "lowGate": low_gate, "highGate": high_gate, "lowBase": low_base, "highBase": high_base}

    return {
        "value": (low_base * low_gate) + ((high_base + low_lift) * high_gate),
        "lowGateSource": low_gate_source,
        "lowGate": low_gate,
        "highGate": high_gate,
        "lowBase": low_base,
        "highBase": high_base,
    }


# ============================================================
# Calibration pipeline
# ============================================================

def _calibrate_azusa_numeric(value, low_gate=None, high_gate=None):
    numeric = float(value) if math.isfinite(float(value)) else float("nan")
    if not math.isfinite(numeric):
        return numeric

    low = _interpolate_calibration_blocks(numeric, AZUSA_CALIBRATION_LOW_BLOCKS)
    high = _interpolate_calibration_blocks(numeric, AZUSA_CALIBRATION_HIGH_BLOCKS)

    lg = _clamp_scalar(float(low_gate), 0.0, 1.0) if (low_gate is not None and math.isfinite(float(low_gate))) else None
    hg = _clamp_scalar(float(high_gate), 0.0, 1.0) if (high_gate is not None and math.isfinite(float(high_gate))) else None

    if lg is None and hg is None:
        return low if numeric < 11.0 else high

    low_weight = lg if lg is not None else max(0.0, 1.0 - (hg if hg is not None else 0.0))
    high_weight = hg if hg is not None else max(0.0, 1.0 - low_weight)
    weight_sum = low_weight + high_weight
    if weight_sum <= 1e-6:
        return low if numeric < 11.0 else high

    return ((low_weight * low) + (high_weight * high)) / weight_sum


def _calibrate_azusa_output_numeric(value):
    numeric = float(value)
    if not math.isfinite(numeric):
        return numeric
    return _interpolate_calibration(numeric, AZUSA_ISOTONIC_POINTS)


def _compute_curve_gap_residual(base_numeric, blend_details, curve_stats, primary_numeric, sunny_numeric, daniel_numeric):
    x = float(base_numeric)
    if not math.isfinite(x):
        return 0.0

    high_gate = _clamp_scalar(float(blend_details.get("highGate", 0.0)), 0.0, 1.0) if blend_details else 0.0
    primary = float(primary_numeric) if (primary_numeric is not None and math.isfinite(float(primary_numeric))) else x
    sunny = float(sunny_numeric) if (sunny_numeric is not None and math.isfinite(float(sunny_numeric))) else x
    daniel = float(daniel_numeric) if (daniel_numeric is not None and math.isfinite(float(daniel_numeric))) else x
    ds = daniel - sunny
    sp = sunny - primary

    anchor_imbalance = float(curve_stats.get("anchorImbalance", 0.0)) if curve_stats else 0.0
    chord_rate = float(curve_stats.get("chordRate", 0.0)) if curve_stats else 0.0
    jack_q95 = float(curve_stats.get("jackQ95", 0.0)) if curve_stats else 0.0

    residual = (
        4.335282
        + (-0.170459 * x)
        + (-1.622303 * max(0.0, 11.0 - x))
        + (1.328125 * max(0.0, 12.5 - x))
        + (-0.042829 * max(0.0, 14.0 - x))
        + (-0.834997 * high_gate)
        + (3.060352 * high_gate * max(0.0, 11.0 - x))
        + (-1.744638 * high_gate * max(0.0, 12.5 - x))
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

    return _clamp_scalar(residual, -1.2, 1.2)


def _compute_post_output_curve_gap_residual(base_numeric, blend_details, curve_stats, primary_numeric, sunny_numeric, daniel_numeric):
    x = float(base_numeric)
    if not math.isfinite(x):
        return 0.0

    high_gate = _clamp_scalar(float(blend_details.get("highGate", 0.0)), 0.0, 1.0) if blend_details else 0.0
    primary = float(primary_numeric) if (primary_numeric is not None and math.isfinite(float(primary_numeric))) else x
    sunny = float(sunny_numeric) if (sunny_numeric is not None and math.isfinite(float(sunny_numeric))) else x
    daniel = float(daniel_numeric) if (daniel_numeric is not None and math.isfinite(float(daniel_numeric))) else x
    ds = daniel - sunny
    sp = sunny - primary

    anchor_imbalance = float(curve_stats.get("anchorImbalance", 0.0)) if curve_stats else 0.0
    chord_rate = float(curve_stats.get("chordRate", 0.0)) if curve_stats else 0.0
    jack_q95 = float(curve_stats.get("jackQ95", x)) if curve_stats else x

    residual = 0.4 * (
        0.979895
        + (0.053556 * x)
        + (-1.050405 * max(0.0, 11.0 - x))
        + (0.942552 * max(0.0, 12.5 - x))
        + (0.048841 * max(0.0, 14.0 - x))
        + (-1.636218 * high_gate)
        + (0.956025 * high_gate * max(0.0, 11.0 - x))
        + (-0.975188 * high_gate * max(0.0, 12.5 - x))
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

    return _clamp_scalar(residual, -1.0, 1.0)


# ============================================================
# Main entry point
# ============================================================

def estimate_azusa_result(
    source,
    speed_rate=1.0,
    od_flag=None,
    cvt_flag=None,
    *,
    sunny_result=None,
    daniel_result=None,
    with_graph=False,
    force_sunny_reference_ho=True,
):
    chart = load_osu_chart(source)
    if int(chart.column_count) != 4:
        raise UnsupportedKeyError("Azusa only supports 4K")

    parsed_data = chart.get_parsed_data()
    column_count = int(parsed_data[0])
    ln_ratio = float(getattr(chart, "LN_ratio", 0.0) or 0.0)

    # Build tap notes
    taps = _build_tap_notes(parsed_data)
    if len(taps) < AZUSA_CONFIG["minNotes"]:
        return {
            "star": float("nan"),
            "lnRatio": ln_ratio,
            "columnCount": column_count,
            "estDiff": f"Invalid: Insufficient notes for stable estimate ({len(taps)})",
            "numericDifficulty": None,
            "numericDifficultyHint": "TooShort",
            "graph": None,
            "rawNumericDifficulty": None,
            "debug": {"code": "TooShort", "message": f"Insufficient notes for stable estimate ({len(taps)})"},
        }

    time_scale = 1.0 / speed_rate if speed_rate != 0 else 1.0
    if time_scale != 1.0:
        scaled_taps = [{**n, "t": n["t"] * time_scale} for n in taps]
    else:
        scaled_taps = taps

    _annotate_rows(scaled_taps, AZUSA_CONFIG["rowToleranceMs"] * time_scale)

    # Build curve and compute primary numeric
    curve = _build_difficulty_curve(scaled_taps)
    primary_numeric = _compute_azusa_numeric_from_curve(curve, len(taps))

    max_column = max(curve["columnCounts"])
    anchor_imbalance = _safe_div((max_column / max(len(taps), 1)) - 0.25, 0.75, 0.0)
    chord_rate = _safe_div(curve["chordNoteCount"], max(len(taps), 1), 0.0)
    jack_sorted = sorted(curve["jackRawSeries"])
    jack_q95 = _quantile_from_sorted(jack_sorted, 0.95)

    # Resolve Sunny
    if sunny_result is None:
        sunny_result = estimate_sunny_result(source, speed_rate, od_flag, "HO" if force_sunny_reference_ho else cvt_flag)
    sunny_numeric = _estimate_sunny_numeric(sunny_result)

    # Resolve Daniel
    daniel_has_native_numeric = False
    daniel_numeric = None
    if daniel_result is not None:
        daniel_numeric = _estimate_daniel_numeric(daniel_result)
        daniel_has_native_numeric = _has_daniel_native_numeric(daniel_result)
    else:
        try:
            daniel_result = estimate_daniel_result(source, speed_rate, od_flag, cvt_flag, sunny_result=sunny_result)
            daniel_numeric = _estimate_daniel_numeric(daniel_result)
            daniel_has_native_numeric = _has_daniel_native_numeric(daniel_result)
        except Exception:
            daniel_numeric = None
            daniel_result = None
            daniel_has_native_numeric = False

    # danielNumericForBlend logic
    daniel_numeric_for_blend = daniel_numeric
    if not daniel_has_native_numeric and daniel_numeric is not None and math.isfinite(daniel_numeric):
        high_signal = max(
            primary_numeric if math.isfinite(primary_numeric) else float("-inf"),
            sunny_numeric if (sunny_numeric is not None and math.isfinite(sunny_numeric)) else float("-inf"),
            daniel_numeric,
        )

        if high_signal < 14.0:
            speed_delta = speed_rate - 1.0
            fallback_scale = (
                _clamp_scalar((-speed_delta) * 0.43, 0.0, 1.0)
                if speed_delta < 0
                else _clamp_scalar(speed_delta * 0.35, 0.0, 1.0)
            )
            daniel_numeric_for_blend = daniel_numeric * fallback_scale

    # Blend
    blend_details = _resolve_rc_blend_components(
        primary_numeric, daniel_numeric_for_blend, sunny_numeric,
        {"anchorImbalance": anchor_imbalance, "chordRate": chord_rate, "jackQ95": jack_q95},
    )
    numeric_difficulty = blend_details["value"]

    # Calibration pipeline
    calibrated_numeric = _calibrate_azusa_numeric(numeric_difficulty, blend_details.get("lowGate"), blend_details.get("highGate"))

    curve_gap_residual = _compute_curve_gap_residual(
        calibrated_numeric, blend_details,
        {"anchorImbalance": anchor_imbalance, "chordRate": chord_rate, "jackQ95": jack_q95},
        primary_numeric, sunny_numeric, daniel_numeric_for_blend,
    )
    pre_output_numeric = _clamp_scalar(float(calibrated_numeric) + curve_gap_residual, -2.0, 20.0)

    output_numeric = _calibrate_azusa_output_numeric(pre_output_numeric)

    post_curve_gap_residual = _compute_post_output_curve_gap_residual(
        output_numeric, blend_details,
        {"anchorImbalance": anchor_imbalance, "chordRate": chord_rate, "jackQ95": jack_q95},
        primary_numeric, sunny_numeric, daniel_numeric_for_blend,
    )
    final_numeric = _clamp_scalar(float(output_numeric) + post_curve_gap_residual, -2.0, 20.0)

    est_diff = numeric_to_rc_label(final_numeric)

    return {
        "star": round(3.4 + 0.38 * final_numeric, 4),
        "lnRatio": ln_ratio,
        "columnCount": column_count,
        "estDiff": est_diff,
        "numericDifficulty": round(final_numeric, 2),
        "numericDifficultyHint": "azusa-rc-v1",
        "graph": sunny_result.get("graph") if with_graph else None,
        "rawNumericDifficulty": round(primary_numeric, 4),
        "debug": {
            "primaryNumeric": round(primary_numeric, 4),
            "blendNumeric": round(numeric_difficulty, 4) if (numeric_difficulty is not None and math.isfinite(numeric_difficulty)) else None,
            "danielNumeric": round(daniel_numeric, 4) if (daniel_numeric is not None and math.isfinite(daniel_numeric)) else None,
            "danielNumericForBlend": round(daniel_numeric_for_blend, 4) if (daniel_numeric_for_blend is not None and math.isfinite(daniel_numeric_for_blend)) else None,
            "danielHasNativeNumeric": daniel_has_native_numeric,
            "sunnyNumeric": round(sunny_numeric, 4) if (sunny_numeric is not None and math.isfinite(sunny_numeric)) else None,
            "notes": len(taps),
            "calibratedNumeric": round(calibrated_numeric, 4) if (calibrated_numeric is not None and math.isfinite(calibrated_numeric)) else None,
            "curveStats": {
                "anchorImbalance": round(anchor_imbalance, 4) if math.isfinite(anchor_imbalance) else None,
                "chordRate": round(chord_rate, 4) if math.isfinite(chord_rate) else None,
                "jackQ95": round(jack_q95, 4) if math.isfinite(jack_q95) else None,
            },
            "curveGapResidual": round(curve_gap_residual, 4) if math.isfinite(curve_gap_residual) else None,
            "outputNumeric": round(output_numeric, 4) if math.isfinite(output_numeric) else None,
            "postCurveGapResidual": round(post_curve_gap_residual, 4) if math.isfinite(post_curve_gap_residual) else None,
            "finalNumeric": round(final_numeric, 4) if math.isfinite(final_numeric) else None,
            "blend": {
                "lowGateSource": f"{blend_details.get('lowGateSource'):.4f}" if (blend_details.get('lowGateSource') is not None and math.isfinite(blend_details['lowGateSource'])) else None,
                "lowGate": f"{blend_details.get('lowGate'):.4f}" if (blend_details.get('lowGate') is not None and math.isfinite(blend_details['lowGate'])) else None,
                "highGate": f"{blend_details.get('highGate'):.4f}" if (blend_details.get('highGate') is not None and math.isfinite(blend_details['highGate'])) else None,
                "lowBase": f"{blend_details.get('lowBase'):.4f}" if (blend_details.get('lowBase') is not None and math.isfinite(blend_details['lowBase'])) else None,
                "highBase": f"{blend_details.get('highBase'):.4f}" if (blend_details.get('highBase') is not None and math.isfinite(blend_details['highBase'])) else None,
            },
        },
    }
