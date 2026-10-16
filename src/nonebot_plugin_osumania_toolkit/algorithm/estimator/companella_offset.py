"""Companella 系统性偏移 —— ``js/estimator/companellaOffset.js`` 的直译。

在 Companella（移植算法）输出之后应用，不改算法本体。依据（详见 JS 侧
``docs/features/companella-offset.md``）：

    - Mania Tracker 行为数据集（4.84M plays）中，Mixed 路由为 Companella 的 4K 谱面
      （>=8 玩家，n=5621 chart×rate）系统性低估：``play-implied − Companella 数值``
      整体均值 +0.443。这不是某张图的问题，而是该移植算法与数据分布之间的整体尺度差。
    - **该尺度差按层级并不恒定**：level < 2.5 段只有 +0.19，level >= 3.5 段升到 +0.804，
      差一个量级。常数版严格分组 CV MAE 改善 −5.22%；两段 + 1.0 宽线性过渡做到 −10.20%。
    - rate 无系统依赖（1.0x / 1.5x 几乎一致，0.75x 样本少且 HT 侧本身不稳定），只做层级。

为什么只作用于 RC 侧（LN 侧偏移 = 0）：行为数据集对 LN 侧谱面的判定量是 **LN 半段**，
而 Companella 的数值是 **RC 半段**，二者不同量纲，跨量纲之差不能当作偏移使用。LN 侧
现有修正由 ``ln_correction.py`` 承担。

为什么按"Companella 权重"缩放：本偏移刻画的是 **Companella 分量**的尺度差，因此只应
作用于输出值中属于 Companella 的那一部分。低难段的 0.5/0.5 Azusa⊕Companella 融合值
只有一半来自 Companella，全额施加会把修正量放大到实际所需的约两倍。

应用点：``mixed.apply_companella_to_mixed_result``，与 ``ln_correction`` 同处
Companella 输出之后。修正对象为 Companella 侧数值；estDiff 由修正后数值重派生
（numeric 与标签同源）。
"""

from __future__ import annotations

import math
from typing import Any

from .rc import numeric_to_rc_label
from .shared import js_fixed, js_number

# RC 侧偏移（numeric 单位，作用在"纯 Companella 分量"上；正值为上调，
# Companella 原本低估）。
# 两段值 + 1.0 宽的线性过渡：硬阶梯（同一对分段值、无过渡）的 CV 与之等价
# （0.8166 vs 0.8178），但会在过渡点造出约 0.6 的输出跳变——同一张图换个小数位
# 就跳半级，用户可见；斜坡把它抹平。
COMPANELLA_OFFSET_RC_LOW = 0.19
COMPANELLA_OFFSET_RC_HIGH = 0.804
COMPANELLA_OFFSET_RC_RAMP_START = 2.5
COMPANELLA_OFFSET_RC_RAMP_WIDTH = 1.0


def compute_companella_offset(side: Any, level: Any) -> float:
    """返回给定侧 / 层级上的 Companella 偏移量（未按权重缩放）。

    只有 RC 侧有值（LN 侧见模块说明），未知侧、LN 侧与非有限 level 一律返回 0。

    :param side: 谱面侧（"RC" / "LN"）
    :param level: 层级查找键：**Companella 自身输出的数值**（分段值就是在纯 Companella
        行上按该值拟合的）。``None`` 视为"未提供"（JS 侧的 ``undefined``）⇒ 返回 0；
        JS 对未提供的 level 走 ``Number(undefined) → NaN`` ⇒ 同样不施加偏移。
    """
    if side != "RC":
        return 0.0
    if level is None:
        return 0.0
    lv = js_number(level)
    if not math.isfinite(lv):
        return 0.0
    t = max(
        0.0,
        min(
            1.0, (lv - COMPANELLA_OFFSET_RC_RAMP_START) / COMPANELLA_OFFSET_RC_RAMP_WIDTH
        ),
    )
    return (
        COMPANELLA_OFFSET_RC_LOW
        + (COMPANELLA_OFFSET_RC_HIGH - COMPANELLA_OFFSET_RC_LOW) * t
    )


def apply_companella_offset(
    numeric: Any,
    rc_label: Any,
    side: Any,
    level: Any,
    companella_weight: Any = 1,
) -> dict[str, Any]:
    """对 Companella 侧数值应用系统性偏移校正。

    :param numeric: 当前数值（纯 Companella 或融合值）
    :param rc_label: 当前 RC 段标签（estDiff 的 RC 半边）
    :param side: 谱面侧（"RC" / "LN"）
    :param level: 层级查找键：Companella 自身输出的数值
    :param companella_weight: 该数值中 Companella 的权重（0~1，默认 1）。
        低难 0.5/0.5 融合路径传 0.5。
    :return: ``{"numeric", "rcLabel", "applied", "offset"}``；未修正时原样返回
        （applied=False，保证不受影响的行逐位不变）
    """
    try:
        weight = float(companella_weight)
    except (TypeError, ValueError):
        weight = 0.0
    scaled = compute_companella_offset(side, level) * (
        weight if math.isfinite(weight) else 0.0
    )

    # 仅在输入本身是有效有限数（非 null / 空串 / 布尔）且缩放后偏移为正时生效。
    if numeric is None or numeric == "" or isinstance(numeric, bool):
        return {"numeric": numeric, "rcLabel": rc_label, "applied": False, "offset": 0.0}
    n = js_number(numeric)
    if not (scaled > 0) or not math.isfinite(n):
        return {"numeric": numeric, "rcLabel": rc_label, "applied": False, "offset": 0.0}

    corrected = js_fixed(n + scaled, 2)
    return {
        "numeric": corrected,
        "rcLabel": numeric_to_rc_label(corrected),
        "applied": True,
        "offset": scaled,
    }
