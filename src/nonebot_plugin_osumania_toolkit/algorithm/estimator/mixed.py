"""Mixed 估计器 —— ``js/estimator/mixedEstimator.js`` 的逐段直译。

路由链与 JS 一致：RC 模式先 Roxy（未开 IN 且无显式 OD 时按
``shouldEvaluateAzusaRcPreference``/``shouldPreferAzusaRcResult`` 评估是否换路
Azusa；Roxy 不可用走 Azusa→Daniel）；LN/Mix 保持 Sunny 组合，4K 且 star<9 时
产出 ``mixedCompanellaPlan`` 由上层应用，否则尝试 Daniel 替换 RC 段。

与 JS 的结构性差异仅一处：Python 解析器是路径式的，Roxy 入口吃谱面文本，
RC 分支先以 utf-8-sig 读出文本再调用。
"""

from __future__ import annotations

import re
import math
from typing import Any

from .rc import numeric_to_rc_label
from .shared import js_fixed, normalize_cvt_flags, resolve_chart_path

MIXED_SUPPORTED_KEYS = {4, 6, 7}

# JS L8-17: Roxy→Azusa 换路的两组阈值（screen 预筛用宽阈值，最终判定用严阈值）。
# JS L9-19: 低难段（Roxy scope-out 或 Sunny star<9）RC 部分的 Azusa⊕Companella 融合。
# 两个近似独立的低难估计器取平均以降低方差（与 Roxy 内部 Azusa 融合同一机制族）；
# 离线探针显示 w∈[0.4,0.7] 结果平坦，取对称 0.5，避免拟合基准分布。
RC_AZUSA_COMPANELLA_FUSION_WEIGHT = 0.5
# Companella 仅覆盖低难段：Sunny 星数达到该值以上不再参与 RC 融合。
LOW_BAND_COMPANELLA_STAR_MAX = 9
# 融合作用域：仅当 Azusa 的 RC 数值自身低于 Alpha 边界（低难主张成立）时融合。
# 一致性门控（|Azusa−Companella| ≤ 1.0）经真实运行验证会误杀大量有益融合
# （净收益 -4.89 → -2.87 MAE 点），已移除：分歧大小无法区分方向对错，
# 净效应由权重平坦性保证。
RC_FUSION_LOW_BAND_MAX = 11

AZUSA_RC_PREFERENCE = {
    "balancedHandScreenMaxBias": 0.006,
    "balancedHandMaxBias": 0.003,
    "azusaHigherScreenMinDelta": 0.25,
    "azusaHigherMinDelta": 0.4,
    "anchorHeavyScreenMinRate": 0.72,
    "anchorHeavyMinRate": 0.78,
    "azusaLowerScreenMaxDelta": -0.55,
    "azusaLowerMaxDelta": -0.7,
}


def _number(value: Any) -> float:
    """JS ``Number()`` 等价：不可转时返回 NaN（不抛错）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def mode_tag_from_ln_ratio(ln_ratio: float) -> str:
    if not math.isfinite(ln_ratio):
        return "Mix"
    if ln_ratio <= 0.15:
        return "RC"
    if ln_ratio >= 0.9:
        return "LN"
    return "Mix"


def split_difficulty_parts(value: Any) -> dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {"rc": "-", "ln": "-"}

    parts = [part.strip() for part in text.split("||") if part.strip()]
    if len(parts) >= 2:
        return {"rc": parts[0], "ln": parts[1]}

    return {"rc": parts[0] if parts else text, "ln": parts[0] if parts else text}


def compose_difficulty_from_rc_ln(rc_label: Any, ln_label: Any, ln_ratio: Any) -> str:
    rc = str(rc_label or "").strip()
    ln = str(ln_label or "").strip()
    ratio = float(ln_ratio) if isinstance(ln_ratio, (int, float)) else math.nan

    if not math.isfinite(ratio) or ratio < 0.15:
        return rc or ln or "-"

    if not rc:
        return ln or "-"
    if not ln:
        return rc
    return f"{rc} || {ln}"


def is_daniel_too_low_difficulty(value: Any) -> bool:
    text = str(value or "").strip()
    return re.match(r"^<\s*alpha\b", text, flags=re.IGNORECASE) is not None


def can_use_rc_result(result: Any) -> bool:
    """JS ``canUseRcResult`` 直译（cc==4 && estDiff 可用 && numeric 存在）。"""
    if not isinstance(result, dict) or not result:
        return False

    # Number(result.columnCount) !== 4（NaN 自然落空）。
    if _number(result.get("columnCount")) != 4:
        return False

    est_diff = str(result.get("estDiff") or "").strip()
    if not est_diff or re.match(r"^Invalid\b", est_diff, flags=re.IGNORECASE):
        return False

    # Roxy 高难聚焦的 scope 边界（"< Alpha Low" / "> Emik Zeta high"）返回
    # numericDifficulty null，视为不可用，路由到 Azusa（低难）。
    numeric = result.get("numericDifficulty")
    if numeric is None or numeric == "":
        return False

    return True


def can_use_daniel_result(result: Any) -> bool:
    if not result:
        return False
    if _number(result.get("columnCount")) != 4:
        return False
    return not is_daniel_too_low_difficulty(result.get("estDiff"))


def result_numeric_value(result: Any) -> float | None:
    raw = result.get("numericDifficulty") if isinstance(result, dict) else None
    value = _number(raw)
    return value if math.isfinite(value) else None


def roxy_unquantized_numeric(result: Any) -> float | None:
    """Roxy 的 debug.finalNumeric 是全部后处理之后的连续值，比保留 2 位的
    numericDifficulty 更精确，换路判定基于它可避免舍入导致的 delta 抖动。"""
    debug = result.get("debug") if isinstance(result, dict) else None
    raw = debug.get("finalNumeric") if isinstance(debug, dict) else None
    if raw is not None and raw != "":
        value = _number(raw)
        if math.isfinite(value):
            return value
    return result_numeric_value(result)


def _debug_stat_value(result: Any, name: str) -> float | None:
    debug = result.get("debug") if isinstance(result, dict) else None
    stats = debug.get("stats") if isinstance(debug, dict) else None
    raw = stats.get(name) if isinstance(stats, dict) else None
    value = _number(raw)
    return value if math.isfinite(value) else None


def _debug_reference_value(result: Any, name: str) -> float | None:
    debug = result.get("debug") if isinstance(result, dict) else None
    meta = debug.get("meta") if isinstance(debug, dict) else None
    references = meta.get("references") if isinstance(meta, dict) else None
    raw = references.get(name) if isinstance(references, dict) else None
    value = _number(raw)
    return value if math.isfinite(value) else None


def should_evaluate_azusa_rc_preference(roxy_result: Any) -> bool:
    """JS ``shouldEvaluateAzusaRcPreference`` 直译（screen 预筛，宽阈值）。"""
    if not can_use_rc_result(roxy_result):
        return False

    roxy_numeric = roxy_unquantized_numeric(roxy_result)
    azusa_reference = _debug_reference_value(roxy_result, "Azusa")
    hand_bias = _debug_stat_value(roxy_result, "handBias")
    anchor_rate = _debug_stat_value(roxy_result, "anchorRate")
    if roxy_numeric is None or azusa_reference is None:
        return False

    delta = azusa_reference - roxy_numeric
    balanced_hand_candidate = (
        hand_bias is not None
        and hand_bias <= AZUSA_RC_PREFERENCE["balancedHandScreenMaxBias"]
        and delta >= AZUSA_RC_PREFERENCE["azusaHigherScreenMinDelta"]
    )
    anchor_heavy_candidate = (
        anchor_rate is not None
        and anchor_rate >= AZUSA_RC_PREFERENCE["anchorHeavyScreenMinRate"]
        and delta <= AZUSA_RC_PREFERENCE["azusaLowerScreenMaxDelta"]
    )

    # 跨界规则：Roxy 输出已到 11+ 而 Azusa 参考低于 11（见 shouldPreferAzusaRcResult）。
    crossing_candidate = roxy_numeric >= 11 and azusa_reference < 11

    return balanced_hand_candidate or anchor_heavy_candidate or crossing_candidate


def should_prefer_azusa_rc_result(roxy_result: Any, azusa_result: Any) -> bool:
    """JS ``shouldPreferAzusaRcResult`` 直译（最终判定，严阈值）。"""
    if not can_use_rc_result(roxy_result) or not can_use_rc_result(azusa_result):
        return False

    roxy_numeric = roxy_unquantized_numeric(roxy_result)
    azusa_numeric = result_numeric_value(azusa_result)
    hand_bias = _debug_stat_value(roxy_result, "handBias")
    anchor_rate = _debug_stat_value(roxy_result, "anchorRate")
    if roxy_numeric is None or azusa_numeric is None:
        return False

    delta = azusa_numeric - roxy_numeric
    balanced_hand_azusa_lift = (
        hand_bias is not None
        and hand_bias <= AZUSA_RC_PREFERENCE["balancedHandMaxBias"]
        and delta >= AZUSA_RC_PREFERENCE["azusaHigherMinDelta"]
    )
    anchor_heavy_roxy_damp = (
        anchor_rate is not None
        and anchor_rate >= AZUSA_RC_PREFERENCE["anchorHeavyMinRate"]
        and delta <= AZUSA_RC_PREFERENCE["azusaLowerMaxDelta"]
    )

    # 跨界规则：Roxy 输出已到 11+（Alpha 上界）而 Azusa 仍低于 11。
    crossing_lift = roxy_numeric >= 11 and azusa_numeric < 11

    return balanced_hand_azusa_lift or anchor_heavy_roxy_damp or crossing_lift


def build_low_band_companella_plan(
    rc_result: dict[str, Any],
    ln_ratio: Any,
    ln_difficulty: Any,
    on_disagree: str,
) -> dict[str, Any]:
    """JS ``buildLowBandCompanellaPlan`` 直译。

    低难段融合计划：plan 携带 Azusa 的 RC 基准值（fuseRc），
    ``apply_companella_to_mixed_result`` 在 Companella 结果到达后做 0.5/0.5 融合。
    ``on_disagree`` 指定门控未通过时保留哪一侧（该分支改动前的原赢家），
    保证融合只在两参考一致且都主张低难时生效，其余行为与改动前一致。
    """
    return {
        "lnRatio": ln_ratio,
        "lnDifficulty": ln_difficulty,
        "fuseRc": True,
        "onDisagree": on_disagree,
        "rcEstDiff": rc_result.get("estDiff"),
        "rcNumeric": result_numeric_value(rc_result),
        "rcNumericHint": rc_result.get("numericDifficultyHint", None),
    }


def apply_companella_to_mixed_result(
    mixed_result: dict[str, Any], companella_result: dict[str, Any]
) -> dict[str, Any]:
    """JS ``applyCompanellaToMixedResult`` 直译（含低难 fuseRc 融合路径）。"""
    plan = mixed_result.get("mixedCompanellaPlan")
    if not plan:
        return mixed_result

    # 低难融合路径：Companella 与计划携带的 Azusa RC 基准做固定权重平均，
    # estDiff 由融合数值重新派生（numeric 与 estDiff 保持同源）。
    # 门控：仅当 Azusa 数值低于 Alpha（低难主张成立）时融合；未通过时回落
    # onDisagree 指定的原赢家（RC 分支为 Azusa，Mix 分支为 Companella），
    # 行为与改动前一致。
    if plan.get("fuseRc"):
        rc_numeric = _number(plan.get("rcNumeric"))
        companella_numeric = _number(
            companella_result.get("numericDifficulty") if companella_result else None
        )
        if not math.isfinite(rc_numeric) or not math.isfinite(companella_numeric):
            return mixed_result

        if rc_numeric >= RC_FUSION_LOW_BAND_MAX:
            if plan.get("onDisagree") == "companella":
                return {
                    **mixed_result,
                    "estDiff": compose_difficulty_from_rc_ln(
                        companella_result.get("estDiff"),
                        plan.get("lnDifficulty"),
                        plan.get("lnRatio"),
                    ),
                    "numericDifficulty": companella_result.get("numericDifficulty"),
                    "numericDifficultyHint": companella_result.get(
                        "numericDifficultyHint"
                    ),
                    "mixedCompanellaPlan": None,
                }
            return mixed_result

        weight = RC_AZUSA_COMPANELLA_FUSION_WEIGHT
        # JS toFixed(2) 半进位语义（Decimal HALF_UP）。
        fused = js_fixed(
            rc_numeric * weight + companella_numeric * (1 - weight), 2
        )
        return {
            **mixed_result,
            "estDiff": compose_difficulty_from_rc_ln(
                numeric_to_rc_label(fused),
                plan.get("lnDifficulty"),
                plan.get("lnRatio"),
            ),
            "numericDifficulty": fused,
            "numericDifficultyHint": None,
            "mixedCompanellaPlan": None,
        }

    return {
        **mixed_result,
        "estDiff": compose_difficulty_from_rc_ln(
            companella_result.get("estDiff"),
            plan.get("lnDifficulty"),
            plan.get("lnRatio"),
        ),
        "numericDifficulty": companella_result.get("numericDifficulty"),
        "numericDifficultyHint": companella_result.get("numericDifficultyHint"),
        "mixedCompanellaPlan": None,
    }


def _read_osu_text(source: Any) -> str | None:
    """路径源 → 谱面文本（utf-8-sig 与 osu_file_parser 同源）。"""
    try:
        return resolve_chart_path(source).read_text(encoding="utf-8-sig")
    except Exception:  # noqa: BLE001 - 与 JS tryRunXxxFallback 的 catch 同语义
        return None


def _try_run_roxy_fallback(
    source: Any,
    speed_rate: float,
    od_flag: Any,
    cvt_flag: Any,
    sunny_result: dict[str, Any] | None,
    chart: Any = None,
    marathon_correction: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    # Roxy 入口吃谱面文本，此分支始终按文本路径自建解析。
    # 注意：不可向 roxy 传共享 chart——roxy 的 canonicalize 会把首音平移到
    # 1000ms（时间原点改变），若 meta 参照基于未平移的原始 chart 计算，
    # floor 边界/几何会与 JS（恒用 canonicalize 后文本自解析）分歧。
    try:
        from .roxy import run_roxy_estimator_from_text

        osu_text = _read_osu_text(source)
        if osu_text is None:
            return None
        return run_roxy_estimator_from_text(
            osu_text,
            speed_rate,
            od_flag,
            cvt_flag,
            precomputed_sunny_result=sunny_result,
            marathon_correction=marathon_correction,
        )
    except Exception:  # noqa: BLE001
        return None


def _try_run_azusa_fallback(
    source: Any,
    speed_rate: float,
    od_flag: Any,
    cvt_flag: Any,
    sunny_result: dict[str, Any] | None,
    chart: Any = None,
    marathon_correction: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        from .azusa import estimate_azusa_result

        return estimate_azusa_result(
            source,
            speed_rate,
            od_flag,
            cvt_flag,
            sunny_result=sunny_result,
            force_sunny_reference_ho=False,
            chart=chart,
            marathon_correction=marathon_correction,
        )
    except Exception:  # noqa: BLE001
        return None


def _try_run_daniel_fallback(
    source: Any,
    speed_rate: float,
    od_flag: Any,
    cvt_flag: Any,
    sunny_result: dict[str, Any] | None = None,
    chart: Any = None,
) -> dict[str, Any] | None:
    try:
        from .daniel import estimate_daniel_result

        return estimate_daniel_result(
            source, speed_rate, od_flag, cvt_flag, sunny_result=sunny_result, chart=chart
        )
    except Exception:  # noqa: BLE001
        return None


def _ensure_sunny_result(
    source: Any,
    speed_rate: float,
    od_flag: Any,
    cvt_flag: Any,
    sunny_result: dict[str, Any] | None,
    chart: Any = None,
) -> dict[str, Any]:
    if sunny_result is not None:
        return sunny_result
    from .sunny import estimate_sunny_result

    return estimate_sunny_result(source, speed_rate, od_flag, cvt_flag, chart=chart)


def estimate_mixed_result(
    source: Any,
    speed_rate: float = 1.0,
    od_flag: Any = None,
    cvt_flag: Any = None,
    sunny_result: dict[str, Any] | None = None,
    *,
    chart: Any = None,
    marathon_correction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """JS ``runMixedEstimatorFromText`` 直译。

    本函数只产出 ``mixedCompanellaPlan``，不内联应用 Companella —— 上层
    （mapview）负责按 plan 调用 ``estimate_companella_result`` +
    ``apply_companella_to_mixed_result``，对应 JS app 层的
    ``applyCompanellaToMixedResult`` 消费流程。

    ``marathon_correction``（{durationS, ettValues}）为马拉松时长修正通道，
    沿 JS options.marathonCorrection 透传给 Roxy/Azusa 子估算器。
    """
    sunny = _ensure_sunny_result(
        source, speed_rate, od_flag, cvt_flag, sunny_result, chart
    )
    actual_algorithm = "Sunny"
    column_count = _number(sunny.get("columnCount"))
    if not math.isfinite(column_count) or column_count not in MIXED_SUPPORTED_KEYS:
        return {
            **sunny,
            "mixedCompanellaPlan": None,
            "actualEstimatorAlgorithm": actual_algorithm,
        }

    in_enabled, ho_enabled, _ = normalize_cvt_flags(cvt_flag)
    ln_ratio = float(sunny.get("lnRatio", 0.0))
    mixed_mode_tag = "RC" if ho_enabled else mode_tag_from_ln_ratio(ln_ratio)

    if mixed_mode_tag == "RC" and column_count != 4:
        return {
            **sunny,
            "mixedCompanellaPlan": None,
            "actualEstimatorAlgorithm": actual_algorithm,
        }

    selected_result: dict[str, Any] = dict(sunny)
    est_diff = str(sunny.get("estDiff", "-"))
    numeric_difficulty = sunny.get("numericDifficulty")
    numeric_difficulty_hint = sunny.get("numericDifficultyHint")
    companella_plan: dict[str, Any] | None = None

    if mixed_mode_tag == "RC":
        roxy_result = _try_run_roxy_fallback(
            source, speed_rate, od_flag, cvt_flag, sunny, chart=chart,
            marathon_correction=marathon_correction,
        )
        if can_use_rc_result(roxy_result):
            selected_result = roxy_result
            actual_algorithm = "Roxy"
            est_diff = str(roxy_result.get("estDiff", est_diff))
            numeric_difficulty = roxy_result.get("numericDifficulty")
            numeric_difficulty_hint = roxy_result.get("numericDifficultyHint")

            has_explicit_od = od_flag is not None
            if (
                not in_enabled
                and not has_explicit_od
                and should_evaluate_azusa_rc_preference(roxy_result)
            ):
                azusa_result = _try_run_azusa_fallback(
                    source, speed_rate, od_flag, cvt_flag, sunny, chart,
                    marathon_correction=marathon_correction,
                )
                if should_prefer_azusa_rc_result(roxy_result, azusa_result):
                    selected_result = azusa_result
                    actual_algorithm = "Azusa"
                    est_diff = str(azusa_result.get("estDiff", est_diff))
                    numeric_difficulty = azusa_result.get("numericDifficulty")
                    numeric_difficulty_hint = azusa_result.get("numericDifficultyHint")
        elif not in_enabled:
            # 传 chart 复用已解析谱面，避免 azusa 内部对同一文件重复解析。
            azusa_result = _try_run_azusa_fallback(
                source, speed_rate, od_flag, cvt_flag, sunny, chart=chart,
                marathon_correction=marathon_correction,
            )
            if can_use_rc_result(azusa_result):
                selected_result = azusa_result
                actual_algorithm = "Azusa"
                est_diff = str(azusa_result.get("estDiff", est_diff))
                numeric_difficulty = azusa_result.get("numericDifficulty")
                numeric_difficulty_hint = azusa_result.get("numericDifficultyHint")
                # 低难段（Roxy scope-out 且 Sunny star<9）：RC 数值升级为
                # Azusa⊕Companella 融合；门控未通过或 Companella 失败时，
                # 本结果（纯 Azusa）兜底——与改动前行为一致。
                if _number(sunny.get("star")) < LOW_BAND_COMPANELLA_STAR_MAX:
                    sunny_parts = split_difficulty_parts(sunny.get("estDiff"))
                    companella_plan = build_low_band_companella_plan(
                        azusa_result,
                        ln_ratio,
                        sunny_parts["ln"],
                        "azusa",
                    )
            else:
                daniel_result = _try_run_daniel_fallback(
                    source, speed_rate, od_flag, cvt_flag, sunny, chart=chart
                )
                if can_use_daniel_result(daniel_result):
                    selected_result = daniel_result
                    actual_algorithm = "Daniel"
                    est_diff = str(daniel_result.get("estDiff", est_diff))
                    numeric_difficulty = daniel_result.get("numericDifficulty")
                    numeric_difficulty_hint = daniel_result.get("numericDifficultyHint")
    else:
        sunny_parts = split_difficulty_parts(sunny.get("estDiff"))
        ln_ratio = float(sunny.get("lnRatio", 0.0))
        ln_difficulty = sunny_parts["ln"]
        rc_difficulty = sunny_parts["rc"]
        rc_numeric_difficulty = sunny.get("numericDifficulty")
        rc_numeric_difficulty_hint = sunny.get("numericDifficultyHint")

        if column_count == 4:
            if _number(sunny.get("star")) < LOW_BAND_COMPANELLA_STAR_MAX:
                # JS L334-356：低难 4K 的 RC 段以 Azusa 为基准与 Companella
                # 融合（0.5/0.5）；Azusa 无效时保留纯 Companella 行为。
                azusa_result = _try_run_azusa_fallback(
                    source, speed_rate, od_flag, cvt_flag, sunny, chart
                )
                if can_use_rc_result(azusa_result):
                    rc_difficulty = str(azusa_result.get("estDiff", rc_difficulty))
                    rc_numeric_difficulty = azusa_result.get("numericDifficulty")
                    rc_numeric_difficulty_hint = azusa_result.get(
                        "numericDifficultyHint"
                    )
                    actual_algorithm = "Azusa"
                    companella_plan = build_low_band_companella_plan(
                        azusa_result, ln_ratio, ln_difficulty, "companella"
                    )
                else:
                    companella_plan = {
                        "lnRatio": ln_ratio,
                        "lnDifficulty": ln_difficulty,
                    }
                    actual_algorithm = "Companella"
            else:
                daniel_result = _try_run_daniel_fallback(
                    source, speed_rate, od_flag, cvt_flag, sunny, chart=chart
                )
                if can_use_daniel_result(daniel_result):
                    rc_difficulty = str(daniel_result.get("estDiff", rc_difficulty))
                    rc_numeric_difficulty = daniel_result.get("numericDifficulty")
                    rc_numeric_difficulty_hint = daniel_result.get(
                        "numericDifficultyHint"
                    )
                    actual_algorithm = "Daniel"

        est_diff = compose_difficulty_from_rc_ln(rc_difficulty, ln_difficulty, ln_ratio)
        numeric_difficulty = rc_numeric_difficulty
        numeric_difficulty_hint = rc_numeric_difficulty_hint

    forced_ln_ratio = 0.0 if ho_enabled else _number(selected_result.get("lnRatio"))
    if not math.isfinite(forced_ln_ratio):
        forced_ln_ratio = 0.0

    return {
        **selected_result,
        "lnRatio": forced_ln_ratio,
        "estDiff": est_diff,
        "numericDifficulty": numeric_difficulty,
        "numericDifficultyHint": numeric_difficulty_hint,
        "mixedCompanellaPlan": companella_plan,
        "actualEstimatorAlgorithm": actual_algorithm,
    }
