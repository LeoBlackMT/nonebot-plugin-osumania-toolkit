from __future__ import annotations

from typing import Any

from ..rework.daniel_algorithm import calculate_daniel
from .exceptions import NotManiaError, ParseError
from .rc import estimate_daniel_dan
from .shared import resolve_chart_path
from .sunny import estimate_sunny_result


def estimate_daniel_result(
    source: Any,
    speed_rate: float = 1.0,
    od_flag: Any = None,
    cvt_flag: Any = None,
    *,
    sunny_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = resolve_chart_path(source)
    daniel_raw = calculate_daniel(str(path), speed_rate, od_flag, with_graph=False)

    if daniel_raw == -1:
        raise ParseError("Beatmap parse failed")
    if daniel_raw == -2:
        raise NotManiaError("Beatmap mode is not mania")
    if daniel_raw == -3:
        # Unsupported keys → fall back to Sunny
        if sunny_result is None:
            sunny_result = estimate_sunny_result(source, speed_rate, od_flag, cvt_flag)
        return sunny_result

    sr, ln_ratio, column_count = daniel_raw

    if column_count != 4:
        if sunny_result is None:
            sunny_result = estimate_sunny_result(source, speed_rate, od_flag, cvt_flag)
        return {
            **sunny_result,
            "star": float(sr),
            "lnRatio": float(ln_ratio),
            "columnCount": int(column_count),
        }

    daniel = estimate_daniel_dan(float(sr))
    numeric = daniel["numeric"]
    est_diff = daniel["label"]
    hint = "N/A" if numeric is None else None

    return {
        "star": float(sr),
        "lnRatio": float(ln_ratio),
        "columnCount": int(column_count),
        "estDiff": est_diff,
        "numericDifficulty": round(float(numeric), 2) if numeric is not None else None,
        "numericDifficultyHint": hint,
        "graph": None,
    }
