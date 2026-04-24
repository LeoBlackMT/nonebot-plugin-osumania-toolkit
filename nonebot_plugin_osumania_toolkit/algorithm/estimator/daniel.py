from __future__ import annotations

import math
from typing import Any

from .exceptions import UnsupportedKeyError
from .rc import estimate_daniel_dan, estimate_daniel_numeric, numeric_to_rc_label
from .sunny import estimate_sunny_result


def estimate_daniel_result(
    source: Any,
    speed_rate: float = 1.0,
    od_flag: Any = None,
    cvt_flag: Any = None,
    *,
    sunny_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if sunny_result is None:
        sunny_result = estimate_sunny_result(source, speed_rate, od_flag, cvt_flag)

    column_count = int(sunny_result.get("columnCount", 0) or 0)
    if column_count != 4:
        raise UnsupportedKeyError("Daniel fallback only applies to 4K maps in the mixed pipeline")

    daniel = estimate_daniel_dan(float(sunny_result.get("star", math.nan)))
    numeric = estimate_daniel_numeric({"star": sunny_result.get("star")})
    if numeric is None:
        numeric = float(sunny_result.get("numericDifficulty") or 0.0)
        est_diff = str(sunny_result.get("estDiff") or numeric_to_rc_label(float(numeric)))
        hint = "N/A"
    else:
        est_diff = daniel["label"]
        hint = None

    return {
        **sunny_result,
        "numericDifficulty": round(float(numeric), 2),
        "numericDifficultyHint": hint,
        "estDiff": est_diff,
        "rawNumericDifficulty": round(float(numeric), 4),
    }
