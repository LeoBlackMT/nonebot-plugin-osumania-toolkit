from __future__ import annotations

import math
import threading
from typing import Any
from pathlib import Path
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal

from ...parser.osu_file_parser import osu_file

# 已解析谱面缓存（路径 + mtime + 大小 为键）。clone 成本（~0.1ms）远低于重新解析
# （~30ms），命中时一律返回 clone，调用方的改写（mod_IN/HO 等）不会污染缓存。
_CHART_CACHE_MAX = 4
_chart_cache: OrderedDict[tuple[str, int, int], osu_file] = OrderedDict()
_chart_cache_lock = threading.Lock()


def js_fixed(x: float, d: int = 2) -> float:
    """JS ``Number(x.toFixed(d))`` 语义（Decimal HALF_UP，平局向 +∞）。"""
    return float(Decimal(x).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def js_number(value: Any) -> float:
    """JS ``Number()`` 等价（不可转时返回 NaN，不抛错）。

    与 Python ``float()`` 的关键差异都在"非数值输入"上，且都会影响对拍结果：
    ``None`` → **0**（不是 NaN）、``True``/``False`` → 1/0、空白串 → 0。
    这是 JS 侧 ``Number(null) === 0`` 的经典语义，本仓库在 Roxy 融合处已踩过一次；
    凡是对 JS ``Number(...)`` 的直译都必须走本函数，不要用 ``float()`` 代替。
    """
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def normalize_cvt_flags(value: Any) -> tuple[bool, bool, str]:
    normalized = str(value or "").strip().upper()
    return ("IN" in normalized, "HO" in normalized, normalized)


def resolve_chart_path(source: Any) -> Path:
    if isinstance(source, Path):
        return source

    if isinstance(source, str):
        return Path(source)

    path_value = getattr(source, "file_path", None)
    if path_value:
        return Path(str(path_value))

    raise TypeError("Unsupported chart source; expected a file path or Path-like object")


def load_osu_chart(source: Any) -> osu_file:
    path = resolve_chart_path(source)
    cache_key = None
    try:
        st = path.stat()
        cache_key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        cache_key = None

    if cache_key is not None:
        with _chart_cache_lock:
            master = _chart_cache.get(cache_key)
            if master is not None:
                _chart_cache.move_to_end(cache_key)
                return master.clone()

    chart = osu_file(str(path))
    chart.process()

    if cache_key is not None:
        with _chart_cache_lock:
            _chart_cache[cache_key] = chart.clone()
            _chart_cache.move_to_end(cache_key)
            while len(_chart_cache) > _CHART_CACHE_MAX:
                _chart_cache.popitem(last=False)
    return chart
