from __future__ import annotations

from typing import Any

from ...file.data import sr_intervals_data
from ..xxy_algorithm import calculate as calculate_sunny
from .exceptions import NotManiaError, ParseError
from .rc import estimate_sunny_numeric
from .shared import resolve_chart_path


def est_diff(sr: float, ln_ratio: float, column_count: int) -> str:
    if column_count == 4:
        rc_diff = None
        for lower, upper, name in sr_intervals_data.RC_intervals_4K:
            if lower <= sr <= upper:
                rc_diff = name
                break
        if rc_diff is None:
            if sr < 1.502:
                rc_diff = "< Intro 1 low"
            elif sr > 11.129:
                rc_diff = "> Theta high"
            else:
                rc_diff = "未知RC难度"

        if ln_ratio < 0.1:
            return f"{rc_diff}"

        ln_diff = None
        for lower, upper, name in sr_intervals_data.LN_intervals_4K:
            if lower <= sr <= upper:
                ln_diff = name
                break
        if ln_diff is None:
            if sr < 4.832:
                ln_diff = "< LN 5 mid"
            elif sr > 9.589:
                ln_diff = "> LN 17 high"
            else:
                ln_diff = "未知LN难度"

        if ln_ratio > 0.9:
            return f"{ln_diff}"

        return f"{rc_diff} || {ln_diff}"

    if column_count == 6:
        rc_diff = None
        for lower, upper, name in sr_intervals_data.RC_intervals_6K:
            if lower <= sr <= upper:
                rc_diff = name
                break
        if rc_diff is None:
            if sr < 3.430:
                rc_diff = "< Regular 0 low"
            elif sr > 7.965:
                rc_diff = "> Regular 9 high"
            else:
                rc_diff = "未知RC难度"

        if ln_ratio < 0.1:
            return f"{rc_diff}"

        ln_diff = None
        for lower, upper, name in sr_intervals_data.LN_intervals_6K:
            if lower <= sr <= upper:
                ln_diff = name
                break
        if ln_diff is None:
            if sr < 3.530:
                ln_diff = "< LN 0 low"
            elif sr > 9.700:
                ln_diff = "> LN Finish high"
            else:
                ln_diff = "未知LN难度"

        if ln_ratio > 0.9:
            return f"{ln_diff}"

        return f"{rc_diff} || {ln_diff}"

    if column_count == 7:
        rc_diff = None
        for lower, upper, name in sr_intervals_data.RC_intervals_7K:
            if lower <= sr <= upper:
                rc_diff = name
                break
        if rc_diff is None:
            if sr < 3.5085:
                rc_diff = "< Regular 0 low"
            elif sr > 10.544:
                rc_diff = "> Regular Stellium high"
            else:
                rc_diff = "未知RC难度"

        if ln_ratio < 0.1:
            return f"{rc_diff}"

        ln_diff = None
        for lower, upper, name in sr_intervals_data.LN_intervals_7K:
            if lower <= sr <= upper:
                ln_diff = name
                break
        if ln_diff is None:
            if sr < 4.836:
                ln_diff = "< LN 3 low"
            elif sr > 10.666:
                ln_diff = "> LN Stellium high"
            else:
                ln_diff = "未知LN难度"

        if ln_ratio > 0.9:
            return f"{ln_diff}"

        return f"{rc_diff} || {ln_diff}"

    return "Unsupported"


def build_sunny_result(
    star: float,
    ln_ratio: float,
    column_count: int,
    *,
    graph: Any = None,
) -> dict[str, Any]:
    return {
        "star": float(star),
        "lnRatio": float(ln_ratio),
        "columnCount": int(column_count),
        "estDiff": est_diff(float(star), float(ln_ratio), int(column_count)),
        "numericDifficulty": estimate_sunny_numeric(float(star)),
        "numericDifficultyHint": None,
        "graph": graph,
    }


def estimate_sunny_result(
    source: Any,
    speed_rate: float = 1.0,
    od_flag: Any = None,
    cvt_flag: Any = None,
) -> dict[str, Any]:
    path = resolve_chart_path(source)
    result = calculate_sunny(str(path), speed_rate, od_flag, cvt_flag)

    if isinstance(result, (int, float)):
        if result == -1:
            raise ParseError("Beatmap parse failed")
        if result == -2:
            raise NotManiaError("Beatmap mode is not mania")
        raise ParseError(f"UnknownCalculateResult: {result}")

    star, ln_ratio, column_count = result
    return build_sunny_result(star, ln_ratio, column_count)
