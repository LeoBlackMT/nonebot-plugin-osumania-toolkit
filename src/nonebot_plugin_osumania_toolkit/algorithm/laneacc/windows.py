from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class Windows:
    od: float
    perfect: float
    great: float
    good: float
    ok: float
    meh: float
    miss: float


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _numeric_od(base_od: float, od_flag: object) -> float:
    if od_flag is None or od_flag == "":
        return _clamp(float(base_od or 0.0), -15.0, 15.0)
    try:
        return _clamp(float(od_flag), -15.0, 15.0)
    except (TypeError, ValueError):
        return _clamp(float(base_od or 0.0), -15.0, 15.0)


def compute_windows(
    base_od: float,
    speed_rate: float = 1.0,
    mods: list[str] | tuple[str, ...] = (),
    od_flag: object = None,
) -> Windows:
    """osu!stable mania V1 六窗（源项目 ``computeWindows`` 直译）。"""
    od = _numeric_od(base_od, od_flag)
    try:
        rate = float(speed_rate)
    except (TypeError, ValueError):
        rate = 1.0
    if not rate > 0.0:
        rate = 1.0
    upper_mods = {str(mod).upper() for mod in mods}
    multiplier = 1.4 if "HR" in upper_mods else (1.0 / 1.4 if "EZ" in upper_mods else 1.0)
    total_multiplier = rate / multiplier
    inv = 10.0 - _clamp(od, 0.0, 10.0)

    def scale(value: float) -> int:
        return math.trunc(value * total_multiplier)

    return Windows(
        od=od,
        perfect=float(scale(16.0)),
        great=float(scale(34.0 + 3.0 * inv)),
        good=float(scale(67.0 + 3.0 * inv)),
        ok=float(scale(97.0 + 3.0 * inv)),
        meh=float(scale(121.0 + 3.0 * inv)),
        miss=float(scale(158.0 + 3.0 * inv)),
    )
