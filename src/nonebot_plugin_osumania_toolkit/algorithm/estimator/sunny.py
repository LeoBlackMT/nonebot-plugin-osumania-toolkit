from __future__ import annotations

from typing import Any

from ..rework.xxy_algorithm import calculate as calculate_sunny
from ...data.intervals import sr_intervals_data
from .exceptions import NotManiaError, ParseError
from .shared import resolve_chart_path


def _interval_lookup(sr: float, table: list[tuple[float, float, str]], fallback_label: str) -> str:
    """对齐 js reworkEstimatorUtils.intervalLookup：表内命中返回名字；
    低于首项/高于末项时用表端点名构造 '< name' / '> name'；其余（表内空隙）回退。"""
    for lower, upper, name in table:
        if lower <= sr <= upper:
            return name
    if sr < table[0][0]:
        return f"< {table[0][2]}"
    if sr > table[-1][1]:
        return f"> {table[-1][2]}"
    return fallback_label


def est_diff(sr: float, ln_ratio: float, column_count: int) -> str:
    if column_count == 4:
        rc_diff = _interval_lookup(sr, sr_intervals_data.RC_intervals_4K, "Unknown RC difficulty")
        if ln_ratio < 0.15:
            return rc_diff
        ln_diff = _interval_lookup(sr, sr_intervals_data.LN_intervals_4K, "Unknown LN difficulty")
        return f"{rc_diff} || {ln_diff}"

    if column_count == 6:
        rc_diff = _interval_lookup(sr, sr_intervals_data.RC_intervals_6K, "Unknown RC difficulty")
        if ln_ratio < 0.15:
            return rc_diff
        ln_diff = _interval_lookup(sr, sr_intervals_data.LN_intervals_6K, "Unknown LN difficulty")
        return f"{rc_diff} || {ln_diff}"

    if column_count == 7:
        rc_diff = _interval_lookup(sr, sr_intervals_data.RC_intervals_7K, "Unknown RC difficulty")
        if ln_ratio < 0.15:
            return rc_diff
        ln_diff = _interval_lookup(sr, sr_intervals_data.LN_intervals_7K, "Unknown LN difficulty")
        return f"{rc_diff} || {ln_diff}"

    return "Unsupported"


def build_sunny_result(star: float, ln_ratio: float, column_count: int, *, graph: Any = None) -> dict[str, Any]:
    return {
        "star": float(star),
        "lnRatio": float(ln_ratio),
        "columnCount": int(column_count),
        "estDiff": est_diff(float(star), float(ln_ratio), int(column_count)),
        "numericDifficulty": None,
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

    if result == -1:
        raise ParseError("Beatmap parse failed")
    if result == -2:
        raise NotManiaError("Beatmap mode is not mania")

    star, ln_ratio, column_count = result
    return build_sunny_result(float(star), float(ln_ratio), int(column_count))
