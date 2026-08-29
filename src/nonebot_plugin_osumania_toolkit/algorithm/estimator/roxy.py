"""Roxy RC 估计器 —— ``js/estimator/roxyEstimator.js`` 的逐段直译。

数值、门控顺序、特征顺序以 JS 源码为准；入口把 canonicalize 后的文本写入
临时 .osu 再解析，参照估计器复用同一临时路径。结果 dict 键名与 JS 一致。
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from collections.abc import Callable
from typing import Any, NamedTuple

from ...data.roxy_meta_model import (
    ROXY_META_BETA,
    ROXY_META_FEATURE_NAMES,
    ROXY_META_MEAN,
    ROXY_META_SCALE,
)
from ...parser.osu_file_parser import osu_file
from .rc import numeric_to_rc_label

try:  # shared.js_fixed 缺失时退回私有等价实现
    from .shared import js_fixed
except ImportError:  # pragma: no cover
    from decimal import ROUND_HALF_UP, Decimal

    def js_fixed(x: float, d: int = 2) -> float:
        """与 algorithm.estimator.shared.js_fixed 相同的 JS toFixed 语义。"""
        return float(Decimal(x).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# 常量 (JS L8-102)
# ---------------------------------------------------------------------------

ROXY_CONFIG: dict[str, Any] = {
    "rcLnRatioLimit": 0.18,
    "minNotes": 80,
    "rowToleranceMs": 2,
    "entropyWindowMs": 750,
    "npsWindowsMs": [250, 500, 1000, 4000],
    "sectionMs": 400,
    "sectionDecay": 0.9,
    "sectionEmaAlpha": 0.15,
    "correctionClamp": 1.25,
    "rawMap": {"p02": 3.9947, "p98": 7.5454},
    "streamWeights": {
        "speed": 0.22,
        "handStream": 0.18,
        "jack": 0.16,
        "chordjack": 0.16,
        "tech": 0.12,
        "stamina": 0.11,
        "course": 0.05,
    },
    "streams": {
        "speed": {"burstTau": 220, "staminaTau": 1600, "burstMix": 0.78},
        "handStream": {"burstTau": 260, "staminaTau": 2200, "burstMix": 0.80},
        "jack": {"burstTau": 300, "staminaTau": 1800, "burstMix": 0.88},
        "chordjack": {"burstTau": 260, "staminaTau": 2400, "burstMix": 0.82},
        "tech": {"burstTau": 450, "staminaTau": 3200, "burstMix": 0.70},
        "stamina": {"burstTau": 1200, "staminaTau": 10000, "burstMix": 0.58},
        "course": {"burstTau": 30000, "staminaTau": 120000, "burstMix": 0.35},
    },
    # JS L40-74: 33 个 isotonic 结点整表
    "isotonicKnots": [
        [-2.6250, 2.4444],
        [-2.5000, 2.9000],
        [-2.1782, 3.2000],
        [-1.6429, 3.4667],
        [-0.8081, 4.9333],
        [-0.5781, 5.0000],
        [-0.3751, 5.1250],
        [0.0878, 5.7000],
        [0.5414, 7.3500],
        [0.7248, 9.6000],
        [1.2435, 9.7625],
        [2.2100, 9.8379],
        [3.3439, 10.3810],
        [4.1521, 10.8619],
        [4.6770, 12.2111],
        [7.5944, 12.8954],
        [10.3796, 12.9333],
        [10.7539, 13.1211],
        [11.2944, 13.1733],
        [12.4106, 13.4225],
        [13.3667, 13.7143],
        [14.0177, 14.0761],
        [15.2659, 14.1489],
        [16.4144, 14.3000],
        [16.9566, 14.3174],
        [17.5080, 14.6000],
        [17.9004, 14.8917],
        [18.1870, 15.0000],
        [18.5160, 15.0636],
        [19.5870, 15.2889],
        [20.2551, 15.6111],
        [21.0298, 16.0000],
        [21.3373, 16.5833],
    ],
}

STREAM_NAMES: list[str] = list(ROXY_CONFIG["streamWeights"].keys())
STREAM_INPUT_BY_NAME: dict[str, str] = {
    "speed": "speedIn",
    "handStream": "handIn",
    "jack": "jackIn",
    "chordjack": "chordjackIn",
    "tech": "techIn",
    "stamina": "staminaIn",
    "course": "courseIn",
}

ROXY_THETA_HIGH_NUMERIC = 18.4
ROXY_THETA_HIGH_LABEL = "> CloverWisp Theta high"
ROXY_NUMERIC_OUTPUT_MAX = 30
ROXY_OD_NEUTRAL = 9
ROXY_CANONICAL_FIRST_OBJECT_MS = 1000
# Azusa 融合: finalNumeric 与 pred_Azusa 按 0.4/0.6 加权 (偏向 Roxy)。JS L95。
ROXY_AZUSA_FUSION_WEIGHT = 0.4
# 高难聚焦: < Alpha 与 >= Zeta high 不输出有效 numeric (JS L99-102)。
ROXY_SCOPE_MIN = 11
ROXY_SCOPE_MIN_LABEL = "< Alpha Low"
ROXY_SCOPE_MAX = 17
ROXY_SCOPE_MAX_LABEL = "> Emik Zeta high"

# JS L987-1027
ROXY_META_ALGOS: list[str] = ["Azusa", "Sunny", "Daniel", "Roxy"]
ROXY_REFERENCE_BUCKET_SIZE = 1.0
ROXY_DISABLED_META_REFERENCES = {"Sunny"}
ROXY_REFERENCE_GAP_FEATURE_MEAN: list[float] = [
    0.07809006,
    0.29256211,
    -0.02192547,
    0.26793478,
    0.32663043,
    0.04266659,
    0.02789153,
    0.00078517,
    0.14369285,
    -0.51494749,
]
ROXY_REFERENCE_GAP_FEATURE_SCALE: list[float] = [
    0.34015787,
    0.32576873,
    2.49325258,
    0.22364344,
    0.29159975,
    0.17146345,
    0.19191325,
    0.00597972,
    0.19899545,
    1.40898167,
]
ROXY_REFERENCE_GAP_BETA: list[float] = [
    -0.0060869565,
    0.0605011303,
    -0.1187884725,
    -0.0070736868,
    -0.0590087101,
    0.1468674261,
    0.0562217676,
    -0.1003859899,
    0.1116677492,
    -0.0281818287,
    0.0297534048,
]
ROXY_REFERENCE_GAP_CORRECTION_SCALE = 0.33


class _CanonicalTiming(NamedTuple):
    text: str
    speed_rate: float
    first_time: float | None
    applied: bool

# ---------------------------------------------------------------------------
# 基础工具 (JS L143-320)
# ---------------------------------------------------------------------------


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _safe_div(a: float, b: float, fallback: float = 0.0) -> float:
    if not math.isfinite(a) or not math.isfinite(b) or abs(b) < 1e-9:
        return fallback
    return a / b


def _to_float(value: Any) -> float:
    """近似 JS ``Number(value)``: 数值原样, 字符串走 :func:`_js_number`, 其余 NaN。"""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _js_number(value)
    return math.nan


_JS_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _js_number(value: Any) -> float:
    """JS ``Number()`` 对谱面字段的语义: 空白串 -> 0, 十进制字面量可解, 否则 NaN。

    已知偏差: 十六进制/"Infinity"/下划线数字等罕见字面量不支持 (谱面不会出现)。
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return math.nan
    text = str(value).strip()
    if text == "":
        return 0.0
    match = _JS_NUMBER_RE.fullmatch(text)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return math.nan
    return math.nan


def _number_or_zero(value: Any) -> float:
    """JS ``Number(x) || 0``。"""
    numeric = _to_float(value)
    return numeric if math.isfinite(numeric) else 0.0


def _fmt4(value: Any) -> float | None:
    """JS ``fmt4``: 有限数取 toFixed(4), 否则 null。"""
    numeric = _to_float(value)
    if not math.isfinite(numeric):
        return None
    return js_fixed(numeric, 4)


def _gate(value: float, minimum: float, maximum: float) -> float:
    return _clamp(_safe_div(value - minimum, maximum - minimum, 0.0), 0.0, 1.0)


def _inverse_gate(value: float, minimum: float, maximum: float) -> float:
    return _clamp(_safe_div(maximum - value, maximum - minimum, 0.0), 0.0, 1.0)


def _strain_rate(dt: float, base: float, offset: float, power: float) -> float:
    combined = _to_float(dt) + float(offset)
    if math.isnan(combined):  # JS: Math.max(16, NaN) -> NaN -> !isFinite -> 0
        return 0.0
    effective = max(16.0, combined)
    value = (float(base) / effective) ** float(power)
    return min(8.0, value) if math.isfinite(value) else 0.0


def _decay_state(state: float, inp: float, dt: float, tau: float) -> float:
    dt_f = _to_float(dt)
    delta = dt_f if math.isfinite(dt_f) and dt_f > 0 else 0.0
    decay = math.exp(-delta / float(tau))
    return state * decay + inp


def _piecewise_linear(x: float, knots: list[list[float]]) -> float:
    value = _to_float(x)
    if not math.isfinite(value) or not knots:
        return value
    if value <= knots[0][0]:
        return knots[0][1]
    last = len(knots) - 1
    if value >= knots[last][0]:
        return knots[last][1]
    for i in range(last):
        x0, y0 = knots[i]
        x1, y1 = knots[i + 1]
        if value >= x0 and value <= x1:
            return y0 + _safe_div((value - x0) * (y1 - y0), x1 - x0, 0.0)
    return value


def _linear_map(value: float, x0: float, x1: float, y0: float, y1: float) -> float:
    return y0 + _safe_div((value - x0) * (y1 - y0), x1 - x0, 0.0)


def _quantile_from_sorted(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    t = _clamp(q, 0.0, 1.0) * (len(sorted_values) - 1)
    left = math.floor(t)
    right = min(len(sorted_values) - 1, left + 1)
    w = t - left
    return sorted_values[left] * (1 - w) + sorted_values[right] * w


def _quantile(values: list[float], q: float) -> float:
    finite = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v))
    return _quantile_from_sorted(finite, q)


def _power_mean(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    acc = 0.0
    for value in values:
        acc += max(0.0, value) ** p
    return (acc / len(values)) ** (1 / p)


def _top_tail_mean(sorted_values: list[float], ratio: float) -> float:
    if not sorted_values:
        return 0.0
    count = max(1, math.ceil(len(sorted_values) * ratio))
    total = sum(sorted_values[len(sorted_values) - count:])
    return total / count


def _bit_count4(mask: int) -> int:
    value = mask & 15
    value = value - ((value >> 1) & 5)
    value = (value & 3) + ((value >> 2) & 3)
    return value


def _entropy_from_counts(counts: list[int], total: float, normalizer: float) -> float:
    if not math.isfinite(total) or total <= 0:
        return 0.0
    entropy = 0.0
    for count in counts:
        if count <= 0:
            continue
        p = count / total
        entropy -= p * math.log2(p)
    return _clamp(entropy / normalizer, 0.0, 1.0)


# ---------------------------------------------------------------------------
# OD 归一化与判定窗口变换 (JS L156-226)
# ---------------------------------------------------------------------------


def _normalize_od_flag(od_flag: Any) -> float | int | str | None:
    raw = od_flag
    if raw is None or raw == "":
        return None
    # JS 数值不分 int/float; 这里保留 int 形态, 使 computeOdDetails 的
    # String(odFlag) 序列化一致 (JS String(8) === "8" 而非 "8.0")。
    if isinstance(raw, bool):
        pass  # 与 JS 非数值类型同路: 落到字符串解析
    elif isinstance(raw, int):
        return raw
    elif isinstance(raw, float):
        return raw if math.isfinite(raw) else None

    text = str(raw).strip()
    if not text:
        return None
    upper = text.upper()
    if upper == "HR" or upper == "EZ":
        return upper

    # JS parseFloat: 取前导数字
    match = re.match(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text)
    if match:
        token = match.group(0)
        try:
            numeric = float(token)
        except ValueError:
            return None
        if not math.isfinite(numeric):
            return None
        if re.fullmatch(r"[+-]?\d+", token):
            return int(numeric)
        return numeric
    return None


def _normalize_cvt_flag(cvt_flag: Any) -> str | None:
    normalized = str(cvt_flag or "").strip().upper()
    if normalized == "HO" or normalized == "IN":
        return normalized
    return None


def _sunny_judgement_window_from_od(od: Any) -> float | None:
    value = _to_float(od)
    if not math.isfinite(value):
        return None
    raw = 0.3 * math.sqrt(max(1e-6, (64.5 - math.ceil(value * 3)) / 500))
    return min(raw, 0.6 * (raw - 0.09) + 0.09)


def _resolve_roxy_od(base_od: Any, od_flag: Any) -> float:
    base_f = _to_float(base_od)
    base = base_f if math.isfinite(base_f) else 8.0
    if od_flag is None:
        return base
    if od_flag == "HR":
        return 6.462 + (0.715 * base)
    if od_flag == "EZ":
        return -20.761 + (2.566 * base)
    numeric = _to_float(od_flag)
    return numeric if math.isfinite(numeric) else base


def _compute_od_details(base_od: Any, od_flag: Any) -> dict[str, Any]:
    base_f = _to_float(base_od)
    base = base_f if math.isfinite(base_f) else 8.0
    effective = _resolve_roxy_od(base, od_flag)
    base_window = _sunny_judgement_window_from_od(ROXY_OD_NEUTRAL)
    effective_window = _sunny_judgement_window_from_od(effective)
    pressure_ratio = (
        _clamp(base_window / effective_window, 0.55, 1.85)
        if (
            base_window is not None
            and effective_window is not None
            and effective_window > 1e-9
        )
        else 1.0
    )
    return {
        "base": base,
        "neutral": ROXY_OD_NEUTRAL,
        "effective": effective,
        "flag": None if od_flag is None else str(od_flag),
        "baseWindow": base_window,
        "effectiveWindow": effective_window,
        "pressureRatio": pressure_ratio,
    }


def _compute_od_correction(od_details: dict[str, Any] | None, numeric: Any) -> float:
    if od_details is None or od_details.get("flag") is None:
        return 0.0

    ratio = _to_float(od_details.get("pressureRatio"))
    if not math.isfinite(ratio) or abs(ratio - 1) < 1e-6:
        return 0.0

    difficulty_gate = _gate(_to_float(numeric), 6.0, 18.0)
    high_difficulty_gate = _gate(_to_float(numeric), 14.0, 18.4)
    correction = math.log(ratio) * (
        3.20 + (1.90 * difficulty_gate) + (0.60 * high_difficulty_gate)
    )
    return _clamp(correction, -2.20, 2.20)


# ---------------------------------------------------------------------------
# 谱面文本规范化 (JS L337-459)
# ---------------------------------------------------------------------------


def _parse_osu_csv_line(line: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in line:
        if ch == '"':
            in_quote = not in_quote
            current.append(ch)
        elif ch == "," and not in_quote:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _detect_first_hit_object_time(osu_text: Any) -> float | None:
    lines = re.split(r"\r?\n", str(osu_text or ""))
    section = ""
    first = math.inf

    for line in lines:
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("//"):
            continue
        if trimmed.startswith("[") and trimmed.endswith("]"):
            section = trimmed
            continue
        if section != "[HitObjects]":
            continue

        parts = _parse_osu_csv_line(line)
        time_value = _js_number(parts[2]) if len(parts) > 2 else math.nan
        if math.isfinite(time_value):
            first = min(first, time_value)

    return first if math.isfinite(first) else None


def _canonicalize_osu_timing(osu_text: str, speed_rate: Any) -> _CanonicalTiming:
    rate = _to_float(speed_rate)
    first_time = _detect_first_hit_object_time(osu_text)
    if not math.isfinite(rate) or rate <= 0 or first_time is None:
        return _CanonicalTiming(
            text=osu_text, speed_rate=rate, first_time=first_time, applied=False
        )

    first_scaled = first_time / rate

    def scale_time(raw: str) -> str:
        numeric = _js_number(raw)
        if not math.isfinite(numeric):
            return raw
        scaled = (numeric / rate) - first_scaled + ROXY_CANONICAL_FIRST_OBJECT_MS
        return str(math.floor(scaled))

    def scale_beat_length(raw: str) -> str:
        numeric = _js_number(raw)
        if not math.isfinite(numeric) or numeric <= 0:
            return raw
        # JS: String(Number((numeric / rate).toFixed(12)))
        return str(float(f"{numeric / rate:.12f}"))

    section = ""
    out: list[str] = []
    for line in re.split(r"\r?\n", str(osu_text)):
        trimmed = line.strip()
        if trimmed.startswith("[") and trimmed.endswith("]"):
            section = trimmed
            out.append(line)
            continue
        if not trimmed or trimmed.startswith("//"):
            out.append(line)
            continue

        if section == "[TimingPoints]":
            parts = _parse_osu_csv_line(line)
            if len(parts) > 0:
                parts[0] = scale_time(parts[0])
                if len(parts) > 1:
                    parts[1] = scale_beat_length(parts[1])
                out.append(",".join(parts))
                continue

        if section == "[Events]":
            parts = _parse_osu_csv_line(line)
            if len(parts) > 0 and str(parts[0] or "").strip() == "2" and len(parts) >= 3:
                parts[1] = scale_time(parts[1])
                parts[2] = scale_time(parts[2])
                out.append(",".join(parts))
                continue

        if section == "[HitObjects]":
            parts = _parse_osu_csv_line(line)
            if len(parts) >= 5:
                parts[2] = scale_time(parts[2])
                obj_type = int(_number_or_zero(parts[3]))
                if (obj_type & 128) != 0 and len(parts) > 5 and parts[5]:
                    object_params = str(parts[5]).split(":")
                    object_params[0] = scale_time(object_params[0])
                    parts[5] = ":".join(object_params)
                out.append(",".join(parts))
                continue

        out.append(line)

    return _CanonicalTiming(
        text="\n".join(out), speed_rate=1, first_time=first_time, applied=True
    )


# ---------------------------------------------------------------------------
# 行构建 / NPS / 活跃统计 (JS L461-572)
# ---------------------------------------------------------------------------


def _build_tap_rows(
    parsed: osu_file, speed_rate: float, tolerance_ms: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    taps: list[dict[str, Any]] = []
    columns = parsed.columns if isinstance(parsed.columns, list) else []
    starts = parsed.note_starts if isinstance(parsed.note_starts, list) else []
    types = parsed.note_types if isinstance(parsed.note_types, list) else []

    for i in range(len(columns)):
        raw_type = int(_number_or_zero(types[i])) if i < len(types) else 0
        if (raw_type & 128) != 0:
            continue

        column = _js_number(columns[i])
        start = _js_number(starts[i]) if i < len(starts) else math.nan
        if (
            not math.isfinite(column)
            or column < 0
            or column > 3
            or not math.isfinite(start)
        ):
            continue

        taps.append({"t": start / speed_rate, "c": column})

    taps.sort(key=lambda tap: (tap["t"], tap["c"]))

    rows: list[dict[str, Any]] = []
    i = 0
    while i < len(taps):
        start_time = taps[i]["t"]
        j = i
        mask = 0
        row_size = 0

        while j < len(taps) and abs(taps[j]["t"] - start_time) <= tolerance_ms:
            bit = 1 << int(taps[j]["c"])
            if (mask & bit) == 0:
                row_size += 1
            mask |= bit
            j += 1

        left_mask = mask & 0b0011
        right_mask = mask & 0b1100
        rows.append(
            {
                "t": start_time,
                "mask": mask,
                "rowSize": row_size,
                "leftCount": _bit_count4(left_mask),
                "rightCount": _bit_count4(right_mask),
                "handMask": [left_mask, right_mask],
            }
        )
        i = j

    return taps, rows


def _compute_nps_rows(rows: list[dict[str, Any]], tap_times: list[float]) -> None:
    windows = ROXY_CONFIG["npsWindowsMs"]
    starts = [0] * len(windows)
    end = 0

    for row in rows:
        while end < len(tap_times) and tap_times[end] <= row["t"] + 1e-9:
            end += 1

        row["nps"] = {}
        for w, window_ms in enumerate(windows):
            min_time = row["t"] - window_ms
            while starts[w] < len(tap_times) and tap_times[starts[w]] <= min_time:
                starts[w] += 1
            row["nps"][window_ms] = (end - starts[w]) / (window_ms / 1000)


def _compute_activity_stats(rows: list[dict[str, Any]], tap_count: int) -> dict[str, Any]:
    if len(rows) < 2:
        return {
            "inactiveMs": 0,
            "breakCount": 0,
            "activeDurationSec": 1,
            "breakDensity": 0,
            "avgNps": tap_count,
        }

    inactive_ms = 0
    break_count = 0
    for i in range(1, len(rows)):
        gap = rows[i]["t"] - rows[i - 1]["t"]
        if gap > 1000:
            inactive_ms += gap - 1000
            break_count += 1

    duration_ms = max(1, rows[-1]["t"] - rows[0]["t"] - inactive_ms)
    active_duration_sec = duration_ms / 1000
    return {
        "inactiveMs": inactive_ms,
        "breakCount": break_count,
        "activeDurationSec": active_duration_sec,
        "breakDensity": break_count / max(active_duration_sec / 60, 1),
        "avgNps": tap_count / max(active_duration_sec, 1),
    }


# ---------------------------------------------------------------------------
# 流聚合 (JS L574-638)
# ---------------------------------------------------------------------------


def _summarize_stream(values: list[float]) -> dict[str, float]:
    finite_sorted = sorted(
        v for v in values if isinstance(v, (int, float)) and math.isfinite(v)
    )
    if not finite_sorted:
        return {
            "q50": 0.0,
            "q75": 0.0,
            "q90": 0.0,
            "q97": 0.0,
            "tailMean": 0.0,
            "powerMean": 0.0,
            "aggregate": 0.0,
        }

    q50 = _quantile_from_sorted(finite_sorted, 0.50)
    q75 = _quantile_from_sorted(finite_sorted, 0.75)
    q90 = _quantile_from_sorted(finite_sorted, 0.90)
    q97 = _quantile_from_sorted(finite_sorted, 0.97)
    tail_mean = _top_tail_mean(finite_sorted, 0.04)
    pm = _power_mean(finite_sorted, 2.4)
    aggregate = (
        (0.30 * q97)
        + (0.22 * q90)
        + (0.18 * tail_mean)
        + (0.15 * q75)
        + (0.10 * pm)
        + (0.05 * q50)
    )
    return {
        "q50": q50,
        "q75": q75,
        "q90": q90,
        "q97": q97,
        "tailMean": tail_mean,
        "powerMean": pm,
        "aggregate": aggregate,
    }


def _compute_section_aggregate(
    rows: list[dict[str, Any]], local_raw: list[float]
) -> float:
    if not rows or not local_raw:
        return 0.0

    first_time = rows[0]["t"]
    section_max: dict[int, float] = {}
    smoothed_raw = _number_or_zero(local_raw[0])
    for i, row in enumerate(rows):
        section = max(0, math.floor((row["t"] - first_time) / ROXY_CONFIG["sectionMs"]))
        raw = _number_or_zero(local_raw[i])
        smoothed_raw += ROXY_CONFIG["sectionEmaAlpha"] * (raw - smoothed_raw)
        section_max[section] = max(section_max.get(section, 0.0), smoothed_raw)

    values = sorted(
        (v for v in section_max.values() if math.isfinite(v) and v > 0), reverse=True
    )
    if not values:
        return 0.0

    weight = 1.0
    total = 0.0
    weight_total = 0.0
    for value in values:
        total += value * weight
        weight_total += weight
        weight *= ROXY_CONFIG["sectionDecay"]

    return _safe_div(total, weight_total, 0.0)


# ---------------------------------------------------------------------------
# 七流曲线 (JS L640-898)
# ---------------------------------------------------------------------------


def _compute_roxy_curve(
    rows: list[dict[str, Any]], taps: list[dict[str, Any]], activity: dict[str, Any]
) -> dict[str, Any]:
    streams: dict[str, list[float]] = {}
    states: dict[str, dict[str, float]] = {}
    for name in STREAM_NAMES:
        streams[name] = []
        states[name] = {"burst": 0.0, "stamina": 0.0}

    last_column_time: list[float] = [math.nan] * 4
    last_hand_time: list[float] = [math.nan] * 2
    prev_hand_mask = [0, 0]
    hand_stamina = [0.0, 0.0]
    column_counts = [0, 0, 0, 0]
    dt_same_values: list[float] = []
    dt_hand_values: list[float] = []
    local_raw: list[float] = []

    mask_counts = [0] * 16
    transition_counts = [0] * 256
    entropy_queue: list[tuple[float, int, int]] = []
    entropy_back = 0
    mask_total = 0
    transition_total = 0

    prev_row_time = rows[0]["t"] - 1000 if rows else 0
    prev_dt_row = 1000
    prev_mask = 0
    left_load = 0
    right_load = 0
    chord_rows = 0
    three_rows = 0
    overlap_sum = 0.0
    rotation_sum = 0
    eligible_hand_events = 0
    anchor_row_strength_sum = 0.0
    fast_jack_strength_sum = 0.0

    for i, row in enumerate(rows):
        dt_row = max(1, row["t"] - prev_row_time) if i > 0 else 1000
        row["dtRow"] = dt_row

        left_mask, right_mask = row["handMask"]
        hand_masks = [left_mask, right_mask]
        dt_hand: list[float] = [math.nan, math.nan]
        rotation = [0, 0]
        overlap_events = 0

        for h in range(2):
            if hand_masks[h] == 0:
                continue
            if math.isfinite(last_hand_time[h]):
                dt_hand[h] = max(1, row["t"] - last_hand_time[h])
                dt_hand_values.append(dt_hand[h])
                eligible_hand_events += 1
                if (hand_masks[h] & prev_hand_mask[h]) == 0 and prev_hand_mask[h] != 0:
                    rotation[h] = 1
                    rotation_sum += 1
                if (hand_masks[h] & prev_hand_mask[h]) != 0:
                    overlap_events += 1

        same_hand_overlap = overlap_events / 2
        overlap_sum += same_hand_overlap

        dt_same: list[float] = [math.nan] * 4
        jack_max = 0.0
        anchor_row = 0.0
        for c in range(4):
            if (row["mask"] & (1 << c)) == 0:
                continue
            column_counts[c] += 1
            if math.isfinite(last_column_time[c]):
                dt_same[c] = max(1, row["t"] - last_column_time[c])
                dt_same_values.append(dt_same[c])
                anchor_row = max(anchor_row, _inverse_gate(dt_same[c], 220, 260))
                fast_jack_strength_sum += _inverse_gate(dt_same[c], 120, 150)
                jack_max = max(jack_max, _strain_rate(dt_same[c], 185, 35, 1.18))
        anchor_row_strength_sum += anchor_row

        left_load += row["leftCount"]
        right_load += row["rightCount"]
        if row["rowSize"] >= 2:
            chord_rows += 1
        if row["rowSize"] >= 3:
            three_rows += 1

        mask_counts[row["mask"]] += 1
        mask_total += 1
        transition_code = -1
        if i > 0:
            transition_code = (prev_mask << 4) | row["mask"]
            transition_counts[transition_code] += 1
            transition_total += 1
        entropy_queue.append((row["t"], row["mask"], transition_code))
        while (
            entropy_back < len(entropy_queue)
            and entropy_queue[entropy_back][0] < row["t"] - ROXY_CONFIG["entropyWindowMs"]
        ):
            old_t, old_mask, old_transition = entropy_queue[entropy_back]
            mask_counts[old_mask] -= 1
            mask_total -= 1
            if old_transition >= 0:
                transition_counts[old_transition] -= 1
                transition_total -= 1
            entropy_back += 1

        entropy750 = _entropy_from_counts(mask_counts, mask_total, 4)
        transition_entropy750 = _entropy_from_counts(
            transition_counts, transition_total, 8
        )
        row_chord = (row["rowSize"] - 1) / 3
        same_hand_chord = (
            max(0, row["leftCount"] - 1) + max(0, row["rightCount"] - 1)
        ) / 2

        hand_rates: list[float] = []
        for h in range(2):
            if hand_masks[h] == 0:
                continue
            hand_dt = dt_hand[h] if math.isfinite(dt_hand[h]) else 1000
            hand_rate = _strain_rate(hand_dt, 180, 40, 1.08)
            hand_rates.append(hand_rate)
            hand_stamina[h] = _decay_state(hand_stamina[h], hand_rate, hand_dt, 8000)
        for h in range(2):
            if hand_masks[h] != 0:
                continue
            hand_stamina[h] = _decay_state(hand_stamina[h], 0, dt_row, 8000)

        hand_max = max(hand_rates) if hand_rates else 0.0
        hand_mean = sum(hand_rates) / len(hand_rates) if hand_rates else 0.0
        speed_in = (
            (0.55 * _strain_rate(dt_row, 155, 30, 1.06))
            + (0.30 * hand_max)
            + (0.15 * hand_mean)
        )
        jack_in = jack_max * (1 + 0.20 * row_chord + 0.15 * anchor_row)
        hand_in = 0.0
        for h in range(2):
            if hand_masks[h] == 0:
                continue
            hand_dt = dt_hand[h] if math.isfinite(dt_hand[h]) else 1000
            hand_in = max(
                hand_in,
                (0.70 * _strain_rate(hand_dt, 180, 38, 1.10))
                + (0.30 * rotation[h] * _strain_rate(hand_dt, 205, 45, 1.05)),
            )

        body = max(0, row["rowSize"] - 2) * _strain_rate(dt_row, 150, 80, 0.85)
        # JS L784 的 chordIn 同样未被 inputs 引用 (源码死代码), 直译保留。
        chord_in = (  # noqa: F841
            row_chord * (1 + 0.18 * speed_in) + 0.22 * same_hand_chord + body
        )
        chordjack_in = row_chord * (
            (0.55 * jack_in) + (0.30 * same_hand_overlap) + (0.15 * hand_in)
        )
        rhythm_chaos = (
            min(2, abs(math.log2((dt_row + 24) / (prev_dt_row + 24)))) / 2 if i > 0 else 0
        )
        tech_in = (
            (0.32 * rhythm_chaos)
            + (0.24 * entropy750)
            + (0.24 * transition_entropy750)
            + (0.20 * (1 if row["mask"] != prev_mask else 0))
        )
        max_hand_stamina = max(hand_stamina[0], hand_stamina[1])
        stamina_in = (
            (0.40 * math.log1p(row["nps"].get(1000) or 0) / math.log(24))
            + (0.35 * math.log1p(row["nps"].get(4000) or 0) / math.log(24))
            + (0.25 * max_hand_stamina)
        )
        course_in = stamina_in * _gate(activity["activeDurationSec"], 90, 300) * (
            1 - 0.25 * _gate(activity["breakDensity"], 0.006, 0.018)
        )

        inputs = {
            "speedIn": speed_in,
            "handIn": hand_in,
            "jackIn": jack_in,
            "chordjackIn": chordjack_in,
            "techIn": tech_in,
            "staminaIn": stamina_in,
            "courseIn": course_in,
        }

        for name in STREAM_NAMES:
            stream_config = ROXY_CONFIG["streams"][name]
            inp = _number_or_zero(inputs[STREAM_INPUT_BY_NAME[name]])
            state = states[name]
            state["burst"] = _decay_state(
                state["burst"], inp, dt_row, stream_config["burstTau"]
            )
            state["stamina"] = _decay_state(
                state["stamina"], inp, dt_row, stream_config["staminaTau"]
            )
            value = stream_config["burstMix"] * state["burst"] + (
                1 - stream_config["burstMix"]
            ) * state["stamina"]
            streams[name].append(value)

        raw = 0.0
        for name in STREAM_NAMES:
            raw += ROXY_CONFIG["streamWeights"][name] * streams[name][-1]
        local_raw.append(raw)

        row["metrics"] = {
            "rowChord": row_chord,
            "sameHandOverlap": same_hand_overlap,
            "rotation": rotation,
            "entropy750": entropy750,
            "transitionEntropy750": transition_entropy750,
            "anchorRow": anchor_row,
            "localRaw": raw,
        }

        for c in range(4):
            if (row["mask"] & (1 << c)) != 0:
                last_column_time[c] = row["t"]
        for h in range(2):
            if hand_masks[h] != 0:
                last_hand_time[h] = row["t"]
                prev_hand_mask[h] = hand_masks[h]

        prev_row_time = row["t"]
        prev_dt_row = dt_row
        prev_mask = row["mask"]

    stream_summaries: dict[str, dict[str, float]] = {}
    weighted_agg = 0.0
    for name in STREAM_NAMES:
        summary = _summarize_stream(streams[name])
        stream_summaries[name] = summary
        weighted_agg += ROXY_CONFIG["streamWeights"][name] * summary["aggregate"]

    section_agg = _compute_section_aggregate(rows, local_raw)
    q97_local = _quantile(local_raw, 0.97)
    q75_local = _quantile(local_raw, 0.75)
    peak_to_sustain_gap = _clamp(
        _safe_div(q97_local - q75_local, max(q97_local, 1e-6), 0.0), 0.0, 1.0
    )
    finite_same_count = len(dt_same_values)
    max_column_count = max(column_counts)
    min_column_count = min(column_counts)

    stats: dict[str, Any] = {
        **activity,
        "chordRate": chord_rows / max(len(rows), 1),
        "threeRate": three_rows / max(len(rows), 1),
        "overlapRate": overlap_sum / max(len(rows), 1),
        "rotationRate": rotation_sum / max(eligible_hand_events, 1),
        "sameHandQ10": _quantile(dt_hand_values, 0.10),
        "fastJackRate": fast_jack_strength_sum / max(finite_same_count, 1),
        "anchorRate": anchor_row_strength_sum / max(len(rows), 1),
        "anchorImbalance": (max_column_count - min_column_count) / max(len(taps), 1),
        "leftLoad": left_load,
        "rightLoad": right_load,
        "handBias": abs(left_load - right_load) / max(left_load, right_load, 1e-6),
        "peakToSustainGap": peak_to_sustain_gap,
        "columnCounts": column_counts,
        "rows": len(rows),
        "taps": len(taps),
    }

    return {
        "streams": streams,
        "streamSummaries": stream_summaries,
        "weightedAgg": weighted_agg,
        "sectionAgg": section_agg,
        "localRaw": local_raw,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# 九项修正与数值化 (JS L900-985)
# ---------------------------------------------------------------------------


def _compute_corrections(stats: dict[str, Any]) -> dict[str, float]:
    low_cj = (
        0.75
        * _gate(stats["chordRate"], 0.48, 0.68)
        * _gate(stats["overlapRate"], 0.75, 1.25)
        * (1 - _gate(stats["avgNps"], 19, 23))
        * (1 - _gate(stats["anchorImbalance"], 0.06, 0.12))
    )
    high_stream = (
        0.65
        * _gate(stats["rotationRate"], 0.68, 0.86)
        * _inverse_gate(stats["sameHandQ10"], 100, 130)
        * (1 - _gate(stats["chordRate"], 0.25, 0.42))
        * (1 - _gate(stats["overlapRate"], 0.65, 0.95))
    )
    high_cj_damp = (
        -0.55
        * _gate(stats["chordRate"], 0.78, 0.90)
        * _gate(stats["threeRate"], 0.18, 0.38)
        * (1 - _gate(stats["fastJackRate"], 0.55, 0.75))
    )
    course_break_damp = (
        -0.70
        * _gate(stats["activeDurationSec"], 240, 480)
        * _gate(stats["breakDensity"], 0.006, 0.018)
        * _gate(stats["peakToSustainGap"], 0.35, 0.75)
        * _inverse_gate(stats["avgNps"], 12, 18)
    )
    course_sustain_lift = (
        0.30
        * _gate(stats["activeDurationSec"], 240, 600)
        * _inverse_gate(stats["breakDensity"], 0.004, 0.012)
        * _inverse_gate(stats["peakToSustainGap"], 0.15, 0.45)
        * _gate(stats["avgNps"], 15, 21)
    )
    dense_js_lift = (
        0.35
        * _gate(stats["chordRate"], 0.35, 0.52)
        * _gate(stats["rotationRate"], 0.62, 0.80)
        * _inverse_gate(stats["sameHandQ10"], 90, 125)
    )
    dense_js_damp = (
        -0.25
        * _gate(stats["chordRate"], 0.58, 0.75)
        * _inverse_gate(stats["rotationRate"], 0.45, 0.62)
    )
    anchor_lift = (
        0.30
        * _gate(stats["anchorRate"], 0.18, 0.38)
        * _gate(stats["fastJackRate"], 0.25, 0.55)
        * (1 - _gate(stats["chordRate"], 0.65, 0.85))
    )
    hand_bias_lift = (
        0.25
        * _gate(stats["handBias"], 0.25, 0.55)
        * _gate(stats["avgNps"], 12, 20)
    )
    raw_sum = (
        low_cj
        + high_stream
        + high_cj_damp
        + course_break_damp
        + course_sustain_lift
        + dense_js_lift
        + dense_js_damp
        + anchor_lift
        + hand_bias_lift
    )
    total = _clamp(
        raw_sum,
        -ROXY_CONFIG["correctionClamp"],
        ROXY_CONFIG["correctionClamp"],
    )

    return {
        "lowCj": low_cj,
        "highStream": high_stream,
        "highCjDamp": high_cj_damp,
        "courseBreakDamp": course_break_damp,
        "courseSustainLift": course_sustain_lift,
        "denseJsLift": dense_js_lift,
        "denseJsDamp": dense_js_damp,
        "anchorLift": anchor_lift,
        "handBiasLift": hand_bias_lift,
        "rawSum": raw_sum,
        "total": total,
    }


def _compute_roxy_numeric(curve: dict[str, Any]) -> dict[str, Any]:
    raw_agg = (0.80 * curve["weightedAgg"]) + (0.20 * curve["sectionAgg"])
    log_raw = math.log1p(max(0.0, raw_agg))
    pre_numeric = _clamp(
        _linear_map(
            log_raw,
            ROXY_CONFIG["rawMap"]["p02"],
            ROXY_CONFIG["rawMap"]["p98"],
            -2,
            20,
        ),
        -2.5,
        21,
    )
    corrections = _compute_corrections(curve["stats"])
    raw_numeric = pre_numeric + corrections["total"]
    numeric = _clamp(_piecewise_linear(raw_numeric, ROXY_CONFIG["isotonicKnots"]), -2, 20)

    return {
        "rawAgg": raw_agg,
        "logRaw": log_raw,
        "preNumeric": pre_numeric,
        "corrections": corrections,
        "rawNumeric": raw_numeric,
        "numeric": numeric,
    }


# RC 标签互转（rcDifficultyFormat.js 私有直译）

_RC_GREEK_BASE_MAP = {
    "alpha": 11,
    "beta": 12,
    "gamma": 13,
    "delta": 14,
    "epsilon": 15,
    "zeta": 16,
    "eta": 17,
    "theta": 18,
    "iota": 19,
    "kappa": 20,
}


def _parse_tier_adjustment(text_lower: str) -> float:
    if re.search(r"\bmid\s*[/-]\s*high\b|\bmidhigh\b", text_lower, re.IGNORECASE):
        return 0.2
    if re.search(r"\bmid\s*[/-]\s*low\b|\bmidlow\b", text_lower, re.IGNORECASE):
        return -0.2
    if re.search(r"\blow\b", text_lower, re.IGNORECASE):
        return -0.4
    if re.search(r"\bhigh\b", text_lower, re.IGNORECASE):
        return 0.4
    if re.search(r"\bmid\b", text_lower, re.IGNORECASE):
        return 0.0
    return 0.0


def _rc_label_to_numeric(label: Any) -> float | None:
    primary = str(label or "").split("||")[0]
    primary = re.sub(r"\s+", " ", primary).strip()
    if not primary or re.search(r"[<>]", primary):
        return None

    text_lower = primary.lower()
    base: float | None = None

    intro = re.search(r"\bintro\s*([123])\b", text_lower, re.IGNORECASE)
    if intro:
        base = float(int(intro.group(1)) - 3)

    if base is None:
        numbered = re.search(
            r"\b(?:reform|rework|regular)\s*(-?\d+(?:\.\d+)?)\b",
            text_lower,
            re.IGNORECASE,
        )
        if numbered:
            base = float(numbered.group(1))

    if base is None and (
        re.search(r"\bfinish\b", text_lower, re.IGNORECASE)
        or re.search(r"\bstellium\b", text_lower, re.IGNORECASE)
    ):
        base = 10.0

    if base is None:
        for word, value in _RC_GREEK_BASE_MAP.items():
            if re.search(rf"\b{word}\b", text_lower, re.IGNORECASE):
                base = float(value)
                break

    if base is None:
        plain = re.search(r"(^|\s)(-?\d+(?:\.\d+)?)(\s|$)", text_lower)
        if plain:
            base = float(plain.group(2))

    if base is None or not math.isfinite(base):
        return None
    return base + _parse_tier_adjustment(text_lower)


def _numeric_to_roxy_rc_label(numeric: Any) -> str:
    value = _to_float(numeric)
    if math.isfinite(value) and value > ROXY_THETA_HIGH_NUMERIC:
        return ROXY_THETA_HIGH_LABEL
    return numeric_to_rc_label(value)


# ---------------------------------------------------------------------------
# 元模型参照预测 (JS L1029-1203)
# ---------------------------------------------------------------------------


def _to_feature_number(value: Any) -> float:
    numeric = _to_float(value)
    return numeric if math.isfinite(numeric) else 0.0


def _rounded_feature(value: Any) -> float:
    numeric = _to_float(value)
    return js_fixed(numeric, 4) if math.isfinite(numeric) else 0.0


def _quantize_feature(value: Any, step: Any) -> float:
    numeric = _to_float(value)
    size = _to_float(step)
    if not math.isfinite(numeric) or not math.isfinite(size) or size <= 0:
        return 0.0
    # JS Math.round: 半值向 +inf
    return js_fixed(math.floor(numeric / size + 0.5) * size, 4)


def _result_numeric(result: Any) -> float | None:
    raw_numeric = result.get("numericDifficulty") if isinstance(result, dict) else None
    if raw_numeric is not None and raw_numeric != "":
        numeric = _to_float(raw_numeric)
        if math.isfinite(numeric):
            return numeric
    est_diff = result.get("estDiff") if isinstance(result, dict) else None
    return _rc_label_to_numeric(est_diff)


def _safe_reference(run: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    try:
        result = run()
        if result:
            return result
        return {
            "star": math.nan,
            "estDiff": "Invalid: Empty reference result",
            "numericDifficulty": None,
        }
    except Exception:
        return {
            "star": math.nan,
            "estDiff": "Invalid: Reference estimator failed",
            "numericDifficulty": None,
        }


def _stabilize_high_reference_predictions(
    predictions: dict[str, Any], structural_numeric: Any
) -> dict[str, Any]:
    azusa = _to_float(predictions.get("Azusa"))
    if not math.isfinite(azusa) or azusa < 16.8:
        return predictions

    roxy = _to_float(predictions.get("Roxy"))
    structural = _to_float(structural_numeric)
    finite_high_references = sorted(
        _to_float(predictions[algo])
        for algo in ("Azusa", "Sunny", "Daniel")
        if predictions.get(algo) is not None
        and math.isfinite(_to_float(predictions.get(algo)))
    )
    reference_median = (
        finite_high_references[len(finite_high_references) // 2]
        if finite_high_references
        else azusa
    )
    support = max(
        roxy if math.isfinite(roxy) else -math.inf,
        structural if math.isfinite(structural) else -math.inf,
    )
    fallback = max(
        support if math.isfinite(support) else azusa - 0.35,
        azusa - 0.35,
        reference_median - 0.10,
    )
    stabilized = dict(predictions)

    for algo in ("Sunny", "Daniel"):
        value = stabilized.get(algo)
        if value is None or not math.isfinite(_to_float(value)):
            stabilized[algo] = fallback

    return stabilized


def _build_reference_predictions(
    source: str,
    speed_rate: float,
    od_flag: Any,
    cvt_flag: Any,
    structural_numeric: Any,
    *,
    precomputed_sunny_result: dict[str, Any] | None = None,
    precomputed_daniel_result: dict[str, Any] | None = None,
    chart: Any = None,
) -> dict[str, Any]:
    # JS L1167-1203 直译（wantsGraph 恒为 False，graph 不产出）。
    from .azusa import estimate_azusa_result
    from .daniel import estimate_daniel_result
    from .sunny import estimate_sunny_result

    sunny_result = (
        precomputed_sunny_result
        if precomputed_sunny_result
        else _safe_reference(
            lambda: estimate_sunny_result(
                source, speed_rate, od_flag, cvt_flag, chart=chart
            )
        )
    )
    daniel_result = precomputed_daniel_result or _safe_reference(
        lambda: estimate_daniel_result(source, speed_rate, od_flag, cvt_flag, chart=chart)
    )
    azusa_result = _safe_reference(
        lambda: estimate_azusa_result(
            source,
            speed_rate,
            od_flag,
            cvt_flag,
            sunny_result=sunny_result,
            daniel_result=daniel_result,
            force_sunny_reference_ho=False,
            chart=chart,
        )
    )

    structural_value = _to_float(structural_numeric)
    predictions = _stabilize_high_reference_predictions(
        {
            "Azusa": _result_numeric(azusa_result),
            "Sunny": _result_numeric(sunny_result),
            "Daniel": _result_numeric(daniel_result),
            "Roxy": structural_value if math.isfinite(structural_value) else None,
        },
        structural_numeric,
    )
    for algo in ROXY_DISABLED_META_REFERENCES:
        predictions[algo] = None

    return predictions


# ---------------------------------------------------------------------------
# 111 维元特征与 ridge 头 (JS L1205-1348, roxyMetaModel.generated.js)
# ---------------------------------------------------------------------------


def _build_roxy_meta_features(
    reference_predictions: dict[str, Any],
    numeric_details: dict[str, Any],
    curve: dict[str, Any],
    structural_numeric: Any,
) -> list[float]:
    feature_map: dict[str, float] = {}
    finite_predictions: list[float] = []
    normalized_predictions: dict[str, float] = {}

    fallback_candidates: list[float] = []
    for algo in ROXY_META_ALGOS:
        raw_value = reference_predictions.get(algo)
        numeric = _to_float(raw_value)
        if raw_value is not None and math.isfinite(numeric):
            fallback_candidates.append(
                _quantize_feature(numeric, ROXY_REFERENCE_BUCKET_SIZE)
            )
    structural_value = _to_float(structural_numeric)
    if not fallback_candidates and math.isfinite(structural_value):
        fallback_candidates.append(
            _quantize_feature(structural_value, ROXY_REFERENCE_BUCKET_SIZE)
        )
    fallback_candidates.sort()
    fallback_prediction = (
        fallback_candidates[len(fallback_candidates) // 2] if fallback_candidates else 0.0
    )

    for algo in ROXY_META_ALGOS:
        value = reference_predictions.get(algo)
        has_value = value is not None and math.isfinite(_to_float(value))
        normalized_value = (
            _quantize_feature(value, ROXY_REFERENCE_BUCKET_SIZE)
            if has_value
            else fallback_prediction
        )
        normalized_predictions[algo] = normalized_value
        feature_map[f"pred_{algo}"] = _to_feature_number(normalized_value)
        feature_map[f"has_{algo}"] = 1.0 if has_value else 0.0
        finite_predictions.append(normalized_value)

    if not finite_predictions:
        finite_predictions.append(0.0)
    finite_predictions.sort()
    pred_min = finite_predictions[0]
    pred_max = finite_predictions[-1]
    pred_mean = sum(finite_predictions) / len(finite_predictions)
    pred_median = finite_predictions[len(finite_predictions) // 2]
    feature_map["pred_min"] = _to_feature_number(pred_min)
    feature_map["pred_max"] = _to_feature_number(pred_max)
    feature_map["pred_mean"] = _to_feature_number(pred_mean)
    feature_map["pred_median"] = _to_feature_number(pred_median)
    feature_map["pred_range"] = _to_feature_number(pred_max - pred_min)

    pairs = [
        ("Azusa", "Daniel"),
        ("Azusa", "Sunny"),
        ("Azusa", "Roxy"),
        ("Daniel", "Sunny"),
        ("Daniel", "Roxy"),
        ("Sunny", "Roxy"),
    ]
    for left, right in pairs:
        diff = _to_feature_number(normalized_predictions[left]) - _to_feature_number(
            normalized_predictions[right]
        )
        feature_map[f"diff_{left}_{right}"] = _to_feature_number(diff)
        feature_map[f"absdiff_{left}_{right}"] = _to_feature_number(abs(diff))

    feature_map["roxy_logRaw"] = _rounded_feature(numeric_details["logRaw"])
    feature_map["roxy_rawAgg"] = _rounded_feature(numeric_details["rawAgg"])
    feature_map["roxy_preNumeric"] = _rounded_feature(numeric_details["preNumeric"])
    feature_map["roxy_rawNumeric"] = _rounded_feature(numeric_details["rawNumeric"])
    feature_map["roxy_finalNumeric"] = _rounded_feature(structural_numeric)

    for name in (
        "lowCj",
        "highStream",
        "highCjDamp",
        "courseBreakDamp",
        "courseSustainLift",
        "denseJsLift",
        "denseJsDamp",
        "anchorLift",
        "handBiasLift",
        "total",
    ):
        feature_map[f"corr_{name}"] = _rounded_feature(
            numeric_details["corrections"][name]
        )

    for stream in (
        "speed", "handStream", "jack", "chordjack",
        "tech", "stamina", "course",
    ):
        summary = curve["streamSummaries"].get(stream) or {}
        for key in ("aggregate", "q97", "q90", "q75", "q50", "tailMean", "powerMean"):
            feature_map[f"{stream}_{key}"] = _rounded_feature(summary.get(key))

    stats = curve["stats"]
    for name in (
        "activeDurationSec",
        "breakCount",
        "breakDensity",
        "avgNps",
        "chordRate",
        "threeRate",
        "overlapRate",
        "rotationRate",
        "sameHandQ10",
        "fastJackRate",
        "anchorRate",
        "anchorImbalance",
        "handBias",
        "peakToSustainGap",
        "rows",
        "taps",
    ):
        feature_map[f"stat_{name}"] = _rounded_feature(stats.get(name))

    avg_nps = _to_feature_number(stats.get("avgNps"))
    active_duration = _to_feature_number(stats.get("activeDurationSec"))
    chord_rate = _to_feature_number(stats.get("chordRate"))
    fast_jack_rate = _to_feature_number(stats.get("fastJackRate"))
    overlap_rate = _to_feature_number(stats.get("overlapRate"))
    rotation_rate = _to_feature_number(stats.get("rotationRate"))
    same_hand_q10 = _to_feature_number(stats.get("sameHandQ10"))
    break_density = _to_feature_number(stats.get("breakDensity"))
    peak_gap = _to_feature_number(stats.get("peakToSustainGap"))
    feature_map["logAvgNps"] = _to_feature_number(math.log1p(max(0.0, avg_nps)))
    feature_map["logDuration"] = _to_feature_number(math.log1p(max(0.0, active_duration)))
    feature_map["chordFast"] = _to_feature_number(chord_rate * fast_jack_rate)
    feature_map["chordOverlap"] = _to_feature_number(chord_rate * overlap_rate)
    feature_map["rotationInvQ10"] = _to_feature_number(
        rotation_rate / (same_hand_q10 + 1)
    )
    feature_map["breakPeak"] = _to_feature_number(break_density * peak_gap)

    return [_to_feature_number(feature_map.get(name)) for name in ROXY_META_FEATURE_NAMES]


def evaluate_roxy_meta_model(features: Any) -> float:
    """JS ``evaluateRoxyMetaModel``: 标准化 ridge 头, 长度不符返回 NaN。"""
    if (
        not isinstance(features, (list, tuple))
        or len(features) != len(ROXY_META_FEATURE_NAMES)
    ):
        return math.nan
    value = ROXY_META_BETA[0]
    for i in range(len(ROXY_META_FEATURE_NAMES)):
        scale = ROXY_META_SCALE[i] if ROXY_META_SCALE[i] else 1
        value += ROXY_META_BETA[i + 1] * (
            (_to_float(features[i]) - ROXY_META_MEAN[i]) / scale
        )
    return _clamp(value, -2, 30)


# ---------------------------------------------------------------------------
# 高难结构地板 / 参照差修正 / Azusa 融合 (JS L1046-1441)
# ---------------------------------------------------------------------------


def _stream_aggregate(stream_summaries: dict[str, Any], name: str) -> float:
    value = stream_summaries.get(name) if isinstance(stream_summaries, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, dict):
        return _to_feature_number(value.get("aggregate"))
    return 0.0


def _compute_high_reference_structural_floor(
    reference_predictions: dict[str, Any],
    numeric_details: dict[str, Any],
    curve: dict[str, Any],
    od_correction: float,
) -> dict[str, Any] | None:
    azusa = (
        _to_float(reference_predictions.get("Azusa"))
        if reference_predictions
        else math.nan
    )
    if not math.isfinite(azusa) or azusa < 17.0:
        return None
    sunny_raw = reference_predictions.get("Sunny")
    daniel_raw = reference_predictions.get("Daniel")
    has_sunny = sunny_raw is not None and math.isfinite(_to_float(sunny_raw))
    has_daniel = daniel_raw is not None and math.isfinite(_to_float(daniel_raw))

    stats = curve.get("stats") or {}
    streams_summary = curve.get("streamSummaries") or {}
    avg_nps = _to_feature_number(stats.get("avgNps"))
    chord_rate = _to_feature_number(stats.get("chordRate"))
    same_hand_q10 = _to_feature_number(stats.get("sameHandQ10"))
    if avg_nps < 25 or chord_rate < 0.70 or same_hand_q10 > 95:
        return None

    density_gate = _gate(avg_nps, 27, 38)
    chord_gate = _gate(chord_rate, 0.78, 0.92)
    three_gate = _gate(_to_feature_number(stats.get("threeRate")), 0.45, 0.72)
    jack_gate = _gate(_stream_aggregate(streams_summary, "jack"), 17.5, 21.8)
    chordjack_gate = _gate(_stream_aggregate(streams_summary, "chordjack"), 12.4, 15.6)
    fast_hand_gate = _inverse_gate(same_hand_q10, 70, 110)
    duration_gate = _gate(_to_feature_number(stats.get("activeDurationSec")), 50, 100)
    raw_gate = _gate(_to_feature_number(numeric_details.get("rawNumeric")), 6, 17)
    pressure = _clamp(
        (0.20 * density_gate)
        + (0.14 * chord_gate)
        + (0.10 * three_gate)
        + (0.20 * jack_gate)
        + (0.16 * chordjack_gate)
        + (0.14 * fast_hand_gate)
        + (0.06 * duration_gate),
        0,
        1,
    )

    pressure_gate = _gate(pressure, 0.22, 0.46)
    azusa_gate = _gate(azusa, 17.0, 18.0)
    missing_reference_ratio = ((0 if has_sunny else 1) + (0 if has_daniel else 1)) / 2
    missing_reference_boost = (
        missing_reference_ratio * _gate(pressure, 0.25, 0.40) * _gate(azusa, 17.5, 18.2)
    )
    activation = _clamp((pressure_gate * azusa_gate) + missing_reference_boost, 0, 1)
    if activation <= 0:
        return None

    confidence = pressure_gate * _gate(azusa, 17.0, 20.0)
    reference_floor = azusa - (0.45 - (0.25 * confidence))
    structural_floor = (
        16.65 + (1.55 * confidence) + (0.35 * raw_gate) + (0.25 * _gate(avg_nps, 35, 45))
    )
    od_adjustment_value = _to_float(od_correction)
    if math.isnan(od_adjustment_value) or od_adjustment_value == 0:
        od_adjustment_value = 0.0
    od_adjustment = min(0.0, od_adjustment_value) * 0.25
    structural_target = structural_floor + od_adjustment
    reference_target = max(reference_floor, structural_floor) + od_adjustment
    floor = structural_target + ((reference_target - structural_target) * activation)

    return {
        "floor": _clamp(floor, 16.8, min(18.65, azusa + 0.30)),
        "activation": activation,
        "missingReferenceBoost": missing_reference_boost,
        "pressure": pressure,
        "confidence": confidence,
        "referenceFloor": reference_floor,
        "structuralFloor": structural_floor,
        "referenceTarget": reference_target,
    }


def _compute_reference_gap_correction(
    reference_predictions: dict[str, Any],
    structural_numeric: Any,
    base_numeric: Any,
    stats: dict[str, Any],
) -> float:
    base = _to_float(base_numeric)
    if not math.isfinite(base):
        return 0.0

    azusa_raw = reference_predictions.get("Azusa") if reference_predictions else None
    daniel_raw = reference_predictions.get("Daniel") if reference_predictions else None
    has_azusa = azusa_raw is not None and math.isfinite(_to_float(azusa_raw))
    has_daniel = daniel_raw is not None and math.isfinite(_to_float(daniel_raw))
    if not has_azusa and not has_daniel:
        return 0.0

    azusa = _to_float(azusa_raw) if has_azusa else base
    daniel = _to_float(daniel_raw) if has_daniel else base
    structural_value = _to_float(structural_numeric)
    structural = structural_value if math.isfinite(structural_value) else base
    azusa_gap = azusa - base
    daniel_gap = daniel - base
    structural_gap = structural - base
    chord_rate = _to_feature_number(stats.get("chordRate"))
    rotation_rate = _to_feature_number(stats.get("rotationRate"))
    same_hand_q10 = _to_feature_number(stats.get("sameHandQ10"))
    avg_nps_gate = _gate(_to_feature_number(stats.get("avgNps")), 12, 24)
    gap_features = [
        azusa_gap,
        daniel_gap,
        structural_gap,
        abs(azusa_gap),
        abs(daniel_gap),
        azusa_gap * chord_rate,
        azusa_gap * rotation_rate,
        azusa_gap / (same_hand_q10 + 1),
        daniel_gap * chord_rate,
        structural_gap * avg_nps_gate,
    ]

    value = ROXY_REFERENCE_GAP_BETA[0]
    for i in range(len(gap_features)):
        scale = ROXY_REFERENCE_GAP_FEATURE_SCALE[i] or 1
        value += ROXY_REFERENCE_GAP_BETA[i + 1] * (
            (gap_features[i] - ROXY_REFERENCE_GAP_FEATURE_MEAN[i]) / scale
        )
    return _clamp(value, -0.30, 0.30) * ROXY_REFERENCE_GAP_CORRECTION_SCALE


def _compute_azusa_high_gap_lift(
    reference_predictions: dict[str, Any], base_numeric: Any
) -> float:
    base = _to_float(base_numeric)
    azusa = (
        _to_float(reference_predictions.get("Azusa"))
        if reference_predictions
        else math.nan
    )
    if not math.isfinite(base) or not math.isfinite(azusa):
        return 0.0
    return 0.05 * _gate(azusa - base, 0.35, 0.95)


def _compute_azusa_fusion(
    reference_predictions: dict[str, Any], final_numeric: float
) -> float:
    azusa = (
        _to_float(reference_predictions.get("Azusa"))
        if reference_predictions
        else math.nan
    )
    base = _to_float(final_numeric)
    if not math.isfinite(azusa) or not math.isfinite(base):
        return float(final_numeric)
    fused = base + (azusa - base) * ROXY_AZUSA_FUSION_WEIGHT
    return js_fixed(fused, 2)


# ---------------------------------------------------------------------------
# 结果构造器 (JS L104-141)
# ---------------------------------------------------------------------------


def _build_error_result(
    code: str, message: str, ln_ratio: Any = 0.0, column_count: Any = 0
) -> dict[str, Any]:
    ln_f = _to_float(ln_ratio)
    cc_f = _to_float(column_count)
    return {
        "star": math.nan,
        "lnRatio": ln_f if math.isfinite(ln_f) else 0,
        "columnCount": int(cc_f) if math.isfinite(cc_f) else 0,
        "estDiff": f"Invalid: {message}",
        "numericDifficulty": None,
        "numericDifficultyHint": code,
        "graph": None,
        "rawNumericDifficulty": None,
        "debug": {
            "code": code,
            "message": message,
        },
    }


def _build_scope_result(
    label: str,
    code: str,
    structural_numeric: float,
    raw_numeric: Any,
    *,
    ln_ratio: Any = 0.0,
    column_count: Any = 0,
    notes: Any = None,
    rows: Any = None,
) -> dict[str, Any]:
    ln_f = _to_float(ln_ratio)
    cc_f = _to_float(column_count)
    raw_f = _to_float(raw_numeric)
    return {
        "star": js_fixed(3.4 + 0.38 * structural_numeric, 4),
        "lnRatio": ln_f if math.isfinite(ln_f) else 0,
        "columnCount": int(cc_f) if math.isfinite(cc_f) else 0,
        "estDiff": label,
        "numericDifficulty": None,
        "numericDifficultyHint": code,
        "graph": None,
        "rawNumericDifficulty": js_fixed(raw_f, 4) if math.isfinite(raw_f) else None,
        "debug": {
            "code": code,
            "message": (
                f"Roxy RC scope {label}"
                f" (structural {float(structural_numeric):.2f})"
            ),
            "structuralNumeric": _fmt4(structural_numeric),
            "notes": notes,
            "rows": rows,
        },
    }


# ---------------------------------------------------------------------------
# 主流程 (JS L1443-1658)
# ---------------------------------------------------------------------------


def run_roxy_estimator_from_text(
    osu_text: Any,
    speed_rate: float = 1.0,
    od_flag: Any = None,
    cvt_flag: Any = None,
    *,
    precomputed_sunny_result: dict[str, Any] | None = None,
    chart: Any = None,
) -> dict[str, Any]:
    """JS ``runRoxyEstimatorFromText`` 直译。

    ``precomputed_sunny_result`` 与 JS options 同名项对应; 与 JS L1522 一致,
    meta 阶段总是将其清空后由参照流程自行计算 (参数仅为签名兼容保留)。
    Python 解析器是路径式的: canonicalize 后的文本先写入临时 .osu。
    """
    try:
        if not isinstance(osu_text, str) or len(osu_text.strip()) == 0:
            return _build_error_result("EmptyInput", "Beatmap text is empty")

        rate = 1.0 if speed_rate is None else _to_float(speed_rate)
        if not math.isfinite(rate) or rate <= 0:
            return _build_error_result("InvalidSpeedRate", "Invalid speed rate")

        od_flag_norm = _normalize_od_flag(od_flag)
        timing = _canonicalize_osu_timing(osu_text, rate)
        analysis_text = timing.text
        analysis_speed_rate = timing.speed_rate

        # 总是自建解析实例（未实现 JS 的 canShareParsed 共享优化）。
        cvt = _normalize_cvt_flag(cvt_flag)

        fd, tmp_path = tempfile.mkstemp(suffix=".osu", prefix="roxy_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(analysis_text)

            parser = osu_file(tmp_path)
            parser.process()
            if cvt == "HO":
                parser.mod_HO()
            elif cvt == "IN":
                parser.mod_IN()

            od_details = _compute_od_details(parser.od, od_flag_norm)

            ln_ratio = _number_or_zero(parser.LN_ratio)
            column_count = int(_number_or_zero(parser.column_count))

            if parser.status == "Fail":
                return _build_error_result(
                    "ParseFailed", "Beatmap parse failed", ln_ratio, column_count
                )
            if parser.status == "NotMania":
                return _build_error_result(
                    "NotMania", "Beatmap mode is not mania", ln_ratio, column_count
                )
            if column_count != 4:
                return _build_error_result(
                    "UnsupportedKeys", "Roxy only supports 4K", ln_ratio, column_count
                )
            if ln_ratio > ROXY_CONFIG["rcLnRatioLimit"]:
                return _build_error_result(
                    "UnsupportedLN",
                    f"Roxy RC scope rejects LN ratio {float(ln_ratio) * 100:.1f}%",
                    ln_ratio,
                    column_count,
                )

            taps, rows = _build_tap_rows(
                parser, analysis_speed_rate, ROXY_CONFIG["rowToleranceMs"]
            )
            if len(taps) < ROXY_CONFIG["minNotes"] or len(rows) < 2:
                return _build_error_result(
                    "TooFewNotes", "Not enough RC tap notes", ln_ratio, column_count
                )

            tap_times = [tap["t"] for tap in taps]
            _compute_nps_rows(rows, tap_times)
            activity = _compute_activity_stats(rows, len(taps))
            curve = _compute_roxy_curve(rows, taps, activity)
            numeric_details = _compute_roxy_numeric(curve)
            structural_numeric = js_fixed(numeric_details["numeric"], 2)

            # meta 阶段: odFlag 强制中性 9, precomputed sunny 清空 (JS L1519-1523)。
            meta_predictions = _build_reference_predictions(
                tmp_path,
                analysis_speed_rate,
                ROXY_OD_NEUTRAL,
                cvt_flag,
                structural_numeric,
                chart=chart,
            )
            meta_features = _build_roxy_meta_features(
                meta_predictions, numeric_details, curve, structural_numeric
            )
            meta_numeric = evaluate_roxy_meta_model(meta_features)

            base_unguarded_numeric = (
                meta_numeric if math.isfinite(meta_numeric) else structural_numeric
            )
            structural_backstop_strength = (
                _gate(structural_numeric, 12.25, 14.0)
                if math.isfinite(structural_numeric)
                else 0.0
            )
            structural_backstop = (
                structural_numeric - 0.15 if structural_backstop_strength > 0 else None
            )
            structural_backstop_gap = (
                structural_backstop - base_unguarded_numeric
                if structural_backstop is not None
                else 0.0
            )
            structural_backstop_applied = (
                structural_backstop is not None
                and structural_backstop_gap > 0
                and structural_backstop_gap <= 0.35
            )
            if structural_backstop_applied:
                base_unguarded_numeric += (
                    structural_backstop - base_unguarded_numeric
                ) * structural_backstop_strength

            od_correction = _compute_od_correction(od_details, base_unguarded_numeric)
            unguarded_numeric = _clamp(
                base_unguarded_numeric + od_correction, -2, ROXY_NUMERIC_OUTPUT_MAX
            )

            high_reference_floor = _compute_high_reference_structural_floor(
                meta_predictions, numeric_details, curve, od_correction
            )
            if high_reference_floor is not None:
                unguarded_numeric = max(unguarded_numeric, high_reference_floor["floor"])

            reference_gap_correction = (
                _compute_reference_gap_correction(
                    meta_predictions,
                    structural_numeric,
                    unguarded_numeric,
                    curve["stats"],
                )
                if od_details["flag"] is None
                else 0.0
            )
            unguarded_numeric = _clamp(
                unguarded_numeric + reference_gap_correction, -2, ROXY_NUMERIC_OUTPUT_MAX
            )

            azusa_high_gap_lift = (
                _compute_azusa_high_gap_lift(meta_predictions, unguarded_numeric)
                if od_details["flag"] is None
                else 0.0
            )
            unguarded_numeric = _clamp(
                unguarded_numeric + azusa_high_gap_lift, -2, ROXY_NUMERIC_OUTPUT_MAX
            )

            final_numeric = _compute_azusa_fusion(
                meta_predictions, js_fixed(unguarded_numeric, 2)
            )

            if final_numeric < ROXY_SCOPE_MIN:
                return _build_scope_result(
                    ROXY_SCOPE_MIN_LABEL,
                    "BelowScope",
                    final_numeric,
                    numeric_details["rawNumeric"],
                    ln_ratio=ln_ratio,
                    column_count=column_count,
                    notes=len(taps),
                    rows=len(rows),
                )
            if final_numeric >= ROXY_SCOPE_MAX:
                return _build_scope_result(
                    ROXY_SCOPE_MAX_LABEL,
                    "AboveScope",
                    final_numeric,
                    numeric_details["rawNumeric"],
                    ln_ratio=ln_ratio,
                    column_count=column_count,
                    notes=len(taps),
                    rows=len(rows),
                )

            est_diff = _numeric_to_roxy_rc_label(final_numeric)

            return {
                "star": js_fixed(3.4 + 0.38 * final_numeric, 4),
                "lnRatio": ln_ratio,
                "columnCount": column_count,
                "estDiff": est_diff,
                "numericDifficulty": final_numeric,
                "numericDifficultyHint": "roxy-meta-ridge-v3",
                "graph": None,
                "rawNumericDifficulty": js_fixed(numeric_details["rawNumeric"], 4),
                "debug": {
                    "notes": len(taps),
                    "rows": len(rows),
                    "rawAgg": _fmt4(numeric_details["rawAgg"]),
                    "logRaw": _fmt4(numeric_details["logRaw"]),
                    "preNumeric": _fmt4(numeric_details["preNumeric"]),
                    "rawNumeric": _fmt4(numeric_details["rawNumeric"]),
                    "structuralNumeric": _fmt4(structural_numeric),
                    "metaNumeric": _fmt4(meta_numeric),
                    "baseUnguardedNumeric": _fmt4(base_unguarded_numeric),
                    "structuralBackstop": {
                        "applied": bool(structural_backstop_applied),
                        "floor": _fmt4(structural_backstop),
                        "strength": _fmt4(structural_backstop_strength),
                    },
                    "unguardedNumeric": _fmt4(unguarded_numeric),
                    "finalNumeric": _fmt4(final_numeric),
                    "highReferenceStructuralFloor": (
                        {key: _fmt4(value) for key, value in high_reference_floor.items()}
                        if high_reference_floor is not None
                        else None
                    ),
                    "od": {
                        "flag": od_details["flag"],
                        "base": _fmt4(od_details["base"]),
                        "neutral": _fmt4(od_details["neutral"]),
                        "effective": _fmt4(od_details["effective"]),
                        "baseWindow": _fmt4(od_details["baseWindow"]),
                        "effectiveWindow": _fmt4(od_details["effectiveWindow"]),
                        "pressureRatio": _fmt4(od_details["pressureRatio"]),
                        "correction": _fmt4(od_correction),
                    },
                    "referenceGapCorrection": _fmt4(reference_gap_correction),
                    "azusaHighGapLift": _fmt4(azusa_high_gap_lift),
                    "speedRateMode": {
                        "mode": "time-scale-only",
                        "speedRate": _fmt4(rate),
                        "analysisSpeedRate": _fmt4(analysis_speed_rate),
                        "canonicalFirstObjectMs": ROXY_CANONICAL_FIRST_OBJECT_MS,
                        "originalFirstObjectMs": _fmt4(timing.first_time),
                        "canonicalized": bool(timing.applied),
                    },
                    "meta": {
                        "featureCount": len(ROXY_META_FEATURE_NAMES),
                        "references": {
                            key: _fmt4(value) for key, value in meta_predictions.items()
                        },
                    },
                    "stats": {
                        key: (list(value) if isinstance(value, list) else _fmt4(value))
                        for key, value in curve["stats"].items()
                    },
                    "corrections": {
                        key: _fmt4(value)
                        for key, value in numeric_details["corrections"].items()
                    },
                    "streams": {
                        name: {
                            inner_key: _fmt4(inner_value)
                            for inner_key, inner_value in summary.items()
                        }
                        for name, summary in curve["streamSummaries"].items()
                    },
                },
            }
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001 - 与 JS catch-all 一致
        return _build_error_result("RoxyError", str(exc) or "Roxy estimator failed")
