from __future__ import annotations

import math
from typing import Any


GREEK_BY_INDEX = [
    "Alpha",
    "Beta",
    "Gamma",
    "Delta",
    "Epsilon",
    "Emik Zeta",
    "Thaumiel Eta",
    "CloverWisp Theta",
    "Iota",
    "Kappa",
]

RC_TIER_CANDIDATES = (
    {"suffix": "low", "offset": -0.4},
    {"suffix": "mid/low", "offset": -0.2},
    {"suffix": "mid", "offset": 0.0},
    {"suffix": "mid/high", "offset": 0.2},
    {"suffix": "high", "offset": 0.4},
)

DAN_MEANS = {
    "Alpha": 6.562,
    "Beta": 6.957,
    "Gamma": 7.459,
    "Delta": 7.939,
    "Epsilon": 9.095,
    "Zeta": 9.473,
    "Eta": 10.162,
    "Theta": 10.782,
}


def _precompute_dan_boundaries() -> tuple[tuple[float, float], ...]:
    means = [DAN_MEANS[name] for name in DAN_MEANS]
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

    return tuple(boundaries)


DAN_BOUNDARIES = _precompute_dan_boundaries()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _get_value(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _extract_star(result: Any) -> float:
    if isinstance(result, (int, float)):
        return float(result)
    value = _get_value(result, "star")
    try:
        star = float(value)
    except (TypeError, ValueError):
        return math.nan
    return star if math.isfinite(star) else math.nan


def format_rc_base_label(base: int) -> str:
    if base <= 0:
        intro_level = int(clamp(base + 3, 1, 3))
        return f"Intro {intro_level}"

    if base <= 10:
        return f"Reform {base}"

    greek_index = int(clamp(base - 11, 0, len(GREEK_BY_INDEX) - 1))
    return GREEK_BY_INDEX[greek_index]


def numeric_to_rc_label(numeric: float) -> str:
    value = float(numeric)
    if not math.isfinite(value):
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
    value = float(star)
    if not math.isfinite(value):
        return {"label": "Unknown", "numeric": None}

    if value < DAN_BOUNDARIES[0][0]:
        return {"label": f"< {list(DAN_MEANS.keys())[0]} Low", "numeric": None}

    if value >= DAN_BOUNDARIES[-1][1]:
        return {"label": f"> {list(DAN_MEANS.keys())[-1]} High", "numeric": None}

    order = list(DAN_MEANS.keys())
    for index, (lower, upper) in enumerate(DAN_BOUNDARIES):
        if lower <= value < upper:
            t_raw = (value - lower) / (upper - lower)
            t = max(0.0, min(t_raw, 1.0))
            numeric = round(11 + index + t, 2)

            if t < 1 / 3:
                label = f"{order[index]} Low"
            elif t < 2 / 3:
                label = f"{order[index]} Mid"
            else:
                label = f"{order[index]} High"

            if index == 5:
                label = f"Emik {label}"
            elif index == 6:
                label = f"Thaumiel {label}"
            elif index == 7:
                label = f"CloverWisp {label}"

            return {"label": label, "numeric": numeric}

    return {"label": "Unknown", "numeric": None}


def estimate_daniel_numeric(result: Any) -> float | None:
    numeric = _get_value(result, "numericDifficulty")
    try:
        numeric_value = float(numeric)
    except (TypeError, ValueError):
        numeric_value = math.nan
    if math.isfinite(numeric_value):
        return round(numeric_value, 2)

    star = _extract_star(result)
    if not math.isfinite(star):
        return None

    daniel = estimate_daniel_dan(star)
    return daniel["numeric"]


def estimate_sunny_numeric(result: Any) -> float | None:
    star = _extract_star(result)
    if not math.isfinite(star):
        return None

    numeric = 2.85 + 1.33 * star
    return round(clamp(numeric, -2.0, 20.0), 2)
