from __future__ import annotations

import math
from typing import Any
from ...data import estimator_data

GREEK_BY_INDEX = estimator_data.GREEK_BY_INDEX
RC_TIER_CANDIDATES = estimator_data.RC_TIER_CANDIDATES
DAN_MEANS = estimator_data.DAN_MEANS


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _safe_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def format_rc_base_label(base: int) -> str:
    if base <= 0:
        intro_level = int(clamp(base + 3, 1, 3))
        return f"Intro {intro_level}"

    if base <= 10:
        return f"Reform {base}"

    greek_index = int(clamp(base - 11, 0, len(GREEK_BY_INDEX) - 1))
    return GREEK_BY_INDEX[greek_index]


def numeric_to_rc_label(numeric: float) -> str:
    value = _safe_float(numeric)
    if value is None:
        return "Invalid"

    clamped = clamp(value, -2.4, 20.4)
    best_match: dict[str, Any] | None = None

    for base in range(-2, 21):
        for tier in RC_TIER_CANDIDATES:
            center_value = base + float(tier["offset"])
            distance = abs(clamped - center_value)
            if best_match is None or distance < float(best_match["distance"]):
                best_match = {
                    "base": base,
                    "suffix": tier["suffix"],
                    "distance": distance,
                }

    if best_match is None:
        return "Invalid"

    return f"{format_rc_base_label(int(best_match['base']))} {best_match['suffix']}"


def estimate_daniel_dan(star: float) -> dict[str, Any]:
    value = _safe_float(star)
    if value is None:
        return {"label": "Unknown", "numeric": None}

    dan_order = list(DAN_MEANS.keys())
    means = [DAN_MEANS[name] for name in dan_order]

    boundaries: list[tuple[float, float]] = []
    for index, mean in enumerate(means):
        if index > 0:
            lower = (means[index - 1] + mean) / 2
        else:
            lower = mean - ((((means[1] + mean) / 2) - mean))

        if index < len(means) - 1:
            upper = (mean + means[index + 1]) / 2
        else:
            upper = mean + ((mean - means[index - 1]) / 2)

        boundaries.append((lower, upper))

    if value < boundaries[0][0]:
        return {"label": f"< {dan_order[0]} Low", "numeric": None}

    if value >= boundaries[-1][1]:
        return {"label": f"> {dan_order[-1]} High", "numeric": None}

    for index, (lower, upper) in enumerate(boundaries):
        if lower <= value < upper:
            t_raw = (value - lower) / (upper - lower)
            t = max(0.0, min(t_raw, 1.0))
            numeric = round(11 + index + t, 2)

            if t < 1 / 3:
                label = f"{dan_order[index]} Low"
            elif t < 2 / 3:
                label = f"{dan_order[index]} Mid"
            else:
                label = f"{dan_order[index]} High"

            if index == 5:
                label = f"Emik {label}"
            elif index == 6:
                label = f"Thaumiel {label}"
            elif index == 7:
                label = f"CloverWisp {label}"

            return {"label": label, "numeric": numeric}

    return {"label": "Unknown", "numeric": None}


def estimate_daniel_numeric(result: Any) -> float | None:
    numeric_raw = None
    if isinstance(result, dict):
        numeric_raw = result.get("numericDifficulty")
    else:
        numeric_raw = getattr(result, "numericDifficulty", None)

    numeric = _safe_float(numeric_raw)
    if numeric is not None:
        return round(numeric, 2)

    star_value = None
    if isinstance(result, dict):
        star_value = result.get("star")
    else:
        star_value = getattr(result, "star", None)

    star = _safe_float(star_value)
    if star is None:
        return None

    if star >= 6.56:
        normalized = clamp((star - 6.56) / 0.58, 0.0, 9.99)
        return round(11.0 + normalized, 2)

    low_part = -2.0 + 13.0 * math.pow(clamp(star / 6.56, 0.0, 1.0), 1.72)
    return round(low_part, 2)


def estimate_sunny_numeric(result: Any) -> float | None:
    star_value = None
    if isinstance(result, dict):
        star_value = result.get("star")
    else:
        star_value = getattr(result, "star", None)

    star = _safe_float(star_value)
    if star is None:
        return None

    numeric = 2.85 + 1.33 * star
    return round(clamp(numeric, -2.0, 20.0), 2)
