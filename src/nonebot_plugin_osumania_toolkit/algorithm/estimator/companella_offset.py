"""Companella 系统性偏移 —— ``js/estimator/companellaOffset.js`` 的直译。

在 Companella（移植算法）输出之后应用，不改算法本体。

**实装范围（实机测试后收敛）：只保留低段。** ``level < 2.5 → +0.19``，其余一律 0；
曾与之并列的 4K LN 后修正（``ln_correction``，+0.5 门控）与层级完整版的斜坡/高段一起
在实机测试后移除——它们把实机难度过分拉高。

依据（详见 JS 侧 ``docs/features/companella-offset.md``）：

    - Mania Tracker 行为数据集（4.84M plays）中，Mixed 路由为 Companella 的 4K 谱面
      （>=8 玩家，n=5621 chart×rate）系统性低估：``play-implied − Companella 数值``
      整体均值 +0.443，且按层级并不恒定（level < 2.5 段真实残余 +0.054，level >= 3.0
      段升到 +0.804，差一个量级）。
    - 层级完整版在 benchmark 与实机两个裁判上都被否决，故只保留两裁判都不反对的低段。

为什么只作用于 RC 侧（LN 侧偏移 = 0）：行为数据集对 LN 侧谱面的判定量是 **LN 半段**，
而 Companella 的数值是 **RC 半段**，二者不同量纲，跨量纲之差不能当作偏移使用。

为什么按"Companella 权重"缩放：本偏移刻画的是 **Companella 分量**的尺度差，因此只应
作用于输出值中属于 Companella 的那一部分。低难段的 0.5/0.5 Azusa⊕Companella 融合值
只有一半来自 Companella，全额施加会把修正量放大到实际所需的约两倍。

应用点：``mixed.apply_companella_to_mixed_result``，在 Companella 输出之后。
修正对象为 Companella 侧数值；estDiff 由修正后数值重派生（numeric 与标签同源）。
"""

from __future__ import annotations

import math
from typing import Any

from .rc import numeric_to_rc_label
from .shared import js_fixed, js_number

# RC 侧偏移（numeric 单位，作用在"纯 Companella 分量"上；正值为上调，
# Companella 原本低估）。只在低段（level < LOW_BAND_MAX）施加：这是行为数据集与
# 实机表现都不反对的唯一一段。
# 注意 +0.19 来自 PR 描述（历史拟合对 level < 3.0 的均值）；level < 2.5 段的真实
# 残余是 +0.054，故本值对低段有意过修正 0.136——项目所有者在实机测试后的取舍，
# 见 JS 侧文档 §2.5。
COMPANELLA_OFFSET_RC_LOW = 0.19
COMPANELLA_OFFSET_RC_LOW_BAND_MAX = 2.5


def compute_companella_offset(side: Any, level: Any) -> float:
    """返回给定侧 / 层级上的 Companella 偏移量（未按权重缩放）。

    只有 RC 侧低段（``level < 2.5``）有值；未知侧、LN 侧、非有限 level 与低段之外
    一律返回 0。

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
    if not math.isfinite(lv) or lv >= COMPANELLA_OFFSET_RC_LOW_BAND_MAX:
        return 0.0
    return COMPANELLA_OFFSET_RC_LOW


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
    weight_ok = weight if math.isfinite(weight) else 0.0
    scaled = compute_companella_offset(side, level) * weight_ok

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
