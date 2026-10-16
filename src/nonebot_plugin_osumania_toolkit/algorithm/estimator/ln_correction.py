"""4K LN 主导谱面的数值后修正 —— ``js/estimator/lnCorrection.js`` 的直译。

在 Companella（移植算法）输出之后应用，不改算法本体。依据（详见 JS 侧
``docs/features/ln-correction.md``）：

    - benchmark ln 行（102 条）：Mixed 数值 bias +1.02（低估）；
    - Mania Tracker 4K LN 侧（行为数据）：+0.2~0.5 低估。

取保守幅度 0.5（纯 benchmark 最优值 >=0.8 未采纳，避免小样本/单源过拟合），由 lnRatio
渐进门控：<=0.375 不触发、0.55 起全量。

应用点：``mixed.apply_companella_to_mixed_result``（Companella 结果合并处，4K 计划必经
此路）。修正对象为 RC 字段数值；estDiff 由修正后数值重派生（numeric 与标签同源）。
"""

from __future__ import annotations

import math
from typing import Any

from .rc import numeric_to_rc_label
from .shared import js_fixed, js_number

LN_CORRECTION_MAGNITUDE = 0.5
LN_CORRECTION_RAMP_LO = 0.375
LN_CORRECTION_RAMP_HI = 0.55


def compute_ln_ratio_correction(ln_ratio: Any) -> float:
    """计算 lnRatio 门控下的 4K LN 修正量（numeric 单位）。返回 0 表示不修正。

    上界 1.5 排除 forceSunnyWindow 的 4e65 哨兵（该路径不触发修正）。
    """
    r = js_number(ln_ratio)
    if not (r > LN_CORRECTION_RAMP_LO and r <= 1.5):
        return 0.0
    t = min(
        1.0, (r - LN_CORRECTION_RAMP_LO) / (LN_CORRECTION_RAMP_HI - LN_CORRECTION_RAMP_LO)
    )
    return LN_CORRECTION_MAGNITUDE * t


def apply_ln_correction_to_rc_fields(
    numeric: Any, rc_label: Any, ln_ratio: Any
) -> dict[str, Any]:
    """对 RC 字段应用 4K LN 后修正。

    注意 JS 侧**没有**像 companella_offset 那样的输入守卫：``Number(null) === 0``，
    所以 ``numeric=None`` 在此会被当成 0 再叠加修正量（JS 与 Python 一致）。保持这条
    直译而不是"顺手加守卫"，否则两侧在缺失输入上会分叉。

    :param numeric: 当前 numericDifficulty
    :param rc_label: 当前 RC 段标签（estDiff 的 RC 半边）
    :param ln_ratio: 谱面 lnRatio
    :return: ``{"numeric", "rcLabel", "applied"}``；未修正时原样返回（applied=False，
        保证非 LN 行逐位不变）
    """
    corr = compute_ln_ratio_correction(ln_ratio)
    n = js_number(numeric)
    if not (corr > 0) or not math.isfinite(n):
        return {"numeric": numeric, "rcLabel": rc_label, "applied": False}
    corrected = js_fixed(n + corr, 2)
    return {
        "numeric": corrected,
        "rcLabel": numeric_to_rc_label(corrected),
        "applied": True,
    }
