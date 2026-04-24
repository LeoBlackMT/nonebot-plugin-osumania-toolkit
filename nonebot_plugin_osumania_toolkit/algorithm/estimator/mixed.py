from __future__ import annotations

import math
from typing import Any

from .shared import normalize_cvt_flags


MIXED_SUPPORTED_KEYS = {4, 6, 7}


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
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return True
    return numeric < 1.0


def can_use_azusa_result(result: Any) -> bool:
    if not result:
        return False
    if int(result.get("columnCount", 0) or 0) != 4:
        return False
    est_diff = str(result.get("estDiff", "")).strip()
    if not est_diff or est_diff.lower().startswith("invalid"):
        return False
    numeric = result.get("numericDifficulty")
    return isinstance(numeric, (int, float)) and math.isfinite(float(numeric))


def can_use_daniel_result(result: Any) -> bool:
    if not result:
        return False
    if int(result.get("columnCount", 0) or 0) != 4:
        return False
    numeric = result.get("numericDifficulty")
    if not isinstance(numeric, (int, float)) or not math.isfinite(float(numeric)):
        return False
    return not is_daniel_too_low_difficulty(numeric)


def apply_companella_to_mixed_result(mixed_result: dict[str, Any], companella_result: dict[str, Any]) -> dict[str, Any]:
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


def _ensure_sunny_result(
    source: Any,
    speed_rate: float,
    od_flag: Any,
    cvt_flag: Any,
    sunny_result: dict[str, Any] | None,
) -> dict[str, Any]:
    if sunny_result is not None:
        return sunny_result
    from .sunny import estimate_sunny_result

    return estimate_sunny_result(source, speed_rate, od_flag, cvt_flag)


def estimate_mixed_result(
    source: Any,
    speed_rate: float = 1.0,
    od_flag: Any = None,
    cvt_flag: Any = None,
    sunny_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sunny = _ensure_sunny_result(source, speed_rate, od_flag, cvt_flag, sunny_result)
    column_count = int(sunny.get("columnCount", 0) or 0)
    if column_count not in MIXED_SUPPORTED_KEYS:
        return {**sunny, "mixedCompanellaPlan": None}

    in_enabled, ho_enabled, _ = normalize_cvt_flags(cvt_flag)
    ln_ratio = float(sunny.get("lnRatio", 0.0))
    mixed_mode_tag = "RC" if ho_enabled else mode_tag_from_ln_ratio(ln_ratio)

    if mixed_mode_tag == "RC" and column_count != 4:
        return {**sunny, "mixedCompanellaPlan": None}

    selected_result = dict(sunny)
    est_diff = str(sunny.get("estDiff", "-")).strip()
    numeric_difficulty = sunny.get("numericDifficulty")
    numeric_difficulty_hint = sunny.get("numericDifficultyHint")
    companella_plan: dict[str, Any] | None = None

    if mixed_mode_tag == "RC":
        if not in_enabled:
            try:
                from .azusa import estimate_azusa_result

                azusa_result = estimate_azusa_result(source, speed_rate, od_flag, cvt_flag, sunny_result=sunny)
            except Exception:
                azusa_result = None

            if can_use_azusa_result(azusa_result):
                selected_result = azusa_result
                est_diff = str(azusa_result.get("estDiff", est_diff))
                numeric_difficulty = azusa_result.get("numericDifficulty")
                numeric_difficulty_hint = azusa_result.get("numericDifficultyHint")
            else:
                try:
                    from .daniel import estimate_daniel_result

                    daniel_result = estimate_daniel_result(source, speed_rate, od_flag, cvt_flag, sunny_result=sunny)
                except Exception:
                    daniel_result = None

                if can_use_daniel_result(daniel_result):
                    selected_result = daniel_result
                    est_diff = str(daniel_result.get("estDiff", est_diff))
                    numeric_difficulty = daniel_result.get("numericDifficulty")
                    numeric_difficulty_hint = daniel_result.get("numericDifficultyHint")
    else:
        sunny_parts = split_difficulty_parts(sunny.get("estDiff"))
        ln_difficulty = sunny_parts["ln"]
        rc_difficulty = sunny_parts["rc"]
        rc_numeric_difficulty = sunny.get("numericDifficulty")
        rc_numeric_difficulty_hint = sunny.get("numericDifficultyHint")

        if column_count == 4:
            try:
                if float(sunny.get("star", 0.0)) < 9:
                    companella_plan = {
                        "lnRatio": ln_ratio,
                        "lnDifficulty": ln_difficulty,
                    }
                else:
                    from .daniel import estimate_daniel_result

                    daniel_result = estimate_daniel_result(source, speed_rate, od_flag, cvt_flag, sunny_result=sunny)
                    if can_use_daniel_result(daniel_result):
                        rc_difficulty = str(daniel_result.get("estDiff", rc_difficulty))
                        rc_numeric_difficulty = daniel_result.get("numericDifficulty")
                        rc_numeric_difficulty_hint = daniel_result.get("numericDifficultyHint")
            except Exception:
                pass

        est_diff = compose_difficulty_from_rc_ln(rc_difficulty, ln_difficulty, ln_ratio)
        numeric_difficulty = rc_numeric_difficulty
        numeric_difficulty_hint = rc_numeric_difficulty_hint

    forced_ln_ratio = 0 if ho_enabled else float(selected_result.get("lnRatio", 0.0))
    if not math.isfinite(forced_ln_ratio):
        forced_ln_ratio = 0.0

    mixed_result = {
        **selected_result,
        "lnRatio": forced_ln_ratio,
        "estDiff": est_diff,
        "numericDifficulty": numeric_difficulty,
        "numericDifficultyHint": numeric_difficulty_hint,
        "mixedCompanellaPlan": companella_plan,
    }

    if companella_plan:
        try:
            from .companella import estimate_companella_result

            companella_result = estimate_companella_result(
                source,
                speed_rate,
                cvt_flag,
                sunny_result=sunny,
            )
            mixed_result = apply_companella_to_mixed_result(mixed_result, companella_result)
        except Exception:
            mixed_result["mixedCompanellaPlan"] = None

    return mixed_result
