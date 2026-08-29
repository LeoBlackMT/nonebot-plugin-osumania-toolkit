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

from .shared import resolve_chart_path, normalize_cvt_flags

MIXED_SUPPORTED_KEYS = {4, 6, 7}

# JS L8-17: Roxy→Azusa 换路的两组阈值（screen 预筛用宽阈值，最终判定用严阈值）。
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


def apply_companella_to_mixed_result(
    mixed_result: dict[str, Any], companella_result: dict[str, Any]
) -> dict[str, Any]:
    plan = mixed_result.get("mixedCompanellaPlan")
    if not plan:
        return mixed_result

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
) -> dict[str, Any] | None:
    # Roxy 入口吃谱面文本，此分支始终按文本路径自建解析。
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
            chart=chart,
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
        )
    except Exception:  # noqa: BLE001
        return None


def _try_run_daniel_fallback(
    source: Any,
    speed_rate: float,
    od_flag: Any,
    cvt_flag: Any,
    chart: Any = None,
) -> dict[str, Any] | None:
    try:
        from .daniel import estimate_daniel_result

        return estimate_daniel_result(source, speed_rate, od_flag, cvt_flag, chart=chart)
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
) -> dict[str, Any]:
    """JS ``runMixedEstimatorFromText`` 直译。

    本函数只产出 ``mixedCompanellaPlan``，不内联应用 Companella —— 上层
    （mapview）负责按 plan 调用 ``estimate_companella_result`` +
    ``apply_companella_to_mixed_result``，对应 JS app 层的
    ``applyCompanellaToMixedResult`` 消费流程。
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
            source, speed_rate, od_flag, cvt_flag, sunny, chart=chart
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
                    source, speed_rate, od_flag, cvt_flag, sunny, chart
                )
                if should_prefer_azusa_rc_result(roxy_result, azusa_result):
                    selected_result = azusa_result
                    actual_algorithm = "Azusa"
                    est_diff = str(azusa_result.get("estDiff", est_diff))
                    numeric_difficulty = azusa_result.get("numericDifficulty")
                    numeric_difficulty_hint = azusa_result.get("numericDifficultyHint")
        elif not in_enabled:
            azusa_result = _try_run_azusa_fallback(
                source, speed_rate, od_flag, cvt_flag, sunny
            )
            if can_use_rc_result(azusa_result):
                selected_result = azusa_result
                actual_algorithm = "Azusa"
                est_diff = str(azusa_result.get("estDiff", est_diff))
                numeric_difficulty = azusa_result.get("numericDifficulty")
                numeric_difficulty_hint = azusa_result.get("numericDifficultyHint")
            else:
                daniel_result = _try_run_daniel_fallback(
                    source, speed_rate, od_flag, cvt_flag, chart
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
            if _number(sunny.get("star")) < 9:
                companella_plan = {
                    "lnRatio": ln_ratio,
                    "lnDifficulty": ln_difficulty,
                }
                actual_algorithm = "Companella"
            else:
                daniel_result = _try_run_daniel_fallback(
                    source, speed_rate, od_flag, cvt_flag, chart
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
