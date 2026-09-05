from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from ..rework.xxy_algorithm import calculate as calculate_sunny
from ...data.intervals import sr_intervals_data
from .exceptions import NotManiaError, ParseError
from .shared import resolve_chart_path

# 同一谱面（路径 + mtime + 大小）在同一组参数下的 sunny 结果 memo：
# mapview/mixed/daniel 兜底等场景存在同参数重复计算，缓存后直接复用。
_SUNNY_CACHE_MAX = 32
_sunny_cache: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_sunny_cache_lock = threading.Lock()


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


def _sunny_cache_key(path: Any, speed_rate: Any, od_flag: Any, cvt_flag: Any) -> tuple[Any, ...] | None:
    """缓存键：路径 + mtime + 大小 + 计算参数；stat 失败（文件已消失）则不缓存。"""
    try:
        st = path.stat()
    except OSError:
        return None
    cvt_key: Any = tuple(cvt_flag) if isinstance(cvt_flag, (list, tuple)) else cvt_flag
    try:
        rate_key = float(speed_rate)
    except (TypeError, ValueError):
        rate_key = speed_rate
    return (str(path), st.st_mtime_ns, st.st_size, rate_key, od_flag, cvt_key)


def _sunny_cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    with _sunny_cache_lock:
        cached = _sunny_cache.get(key)
        if cached is not None:
            _sunny_cache.move_to_end(key)
        return cached


def _sunny_cache_put(key: tuple[Any, ...], value: dict[str, Any]) -> None:
    with _sunny_cache_lock:
        _sunny_cache[key] = value
        _sunny_cache.move_to_end(key)
        while len(_sunny_cache) > _SUNNY_CACHE_MAX:
            _sunny_cache.popitem(last=False)


def estimate_sunny_result(
    source: Any,
    speed_rate: float = 1.0,
    od_flag: Any = None,
    cvt_flag: Any = None,
    *,
    chart: Any = None,
) -> dict[str, Any]:
    path_source = chart if chart is not None else source
    path = resolve_chart_path(path_source)

    cache_key = _sunny_cache_key(path, speed_rate, od_flag, cvt_flag)
    if cache_key is not None:
        cached = _sunny_cache_get(cache_key)
        if cached is not None:
            return dict(cached)

    result = calculate_sunny(str(path), speed_rate, od_flag, cvt_flag, chart=chart)

    if result == -1:
        raise ParseError("Beatmap parse failed")
    if result == -2:
        raise NotManiaError("Beatmap mode is not mania")

    star, ln_ratio, column_count = result
    built = build_sunny_result(float(star), float(ln_ratio), int(column_count))
    if cache_key is not None:
        _sunny_cache_put(cache_key, built)
    return dict(built)
