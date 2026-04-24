from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

try:
    import onnxruntime as ort  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    ort = None

from ..ett.calc import OfficialRunnerError, compute_difficulties
from .exceptions import ParseError, UnsupportedKeyError
from .interlude import estimate_interlude_star_from_chart
from .rc import clamp, estimate_sunny_numeric
from .shared import load_osu_chart
from .sunny import estimate_sunny_result


DAN_LABELS = [
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "Emik Zeta",
    "Thaumiel Eta",
    "CloverWisp Theta",
    "iota",
    "kappa",
]

VARIANT_TEXT = {
    "--": "low",
    "-": "mid/low",
    "": "mid",
    "+": "mid/high",
    "++": "high",
}

FEATURE_COUNT = 10
MIN_DAN = 1.0
MAX_DAN = 20.0

_MODEL_PATH = Path(__file__).with_name("companella_model.onnx")
_MODEL_SESSION: Any = None
_MODEL_LOAD_FAILED = False


def _capitalize_label(label: Any) -> str:
    text = str(label or "?").strip()
    if not text:
        return "?"
    if text.isdigit():
        return text
    return " ".join(part[:1].upper() + part[1:].lower() for part in text.split())


def _build_display_difficulty(label: Any, variant: str) -> str:
    variant_text = VARIANT_TEXT.get(variant, VARIANT_TEXT[""])
    capped_label = _capitalize_label(label)
    if capped_label.isdigit():
        return f"Reform {capped_label} {variant_text}"
    return f"{capped_label} {variant_text}"


def _parse_prediction(raw_value: float) -> tuple[int, str]:
    if raw_value < MIN_DAN:
        return 0, "--"
    if raw_value >= MAX_DAN:
        return 19, "++"

    dan_level = int(clamp(round(raw_value), 1, 20))
    dan_index = dan_level - 1
    offset = raw_value - dan_level

    if offset <= -0.3:
        variant = "--"
    elif offset <= -0.1:
        variant = "-"
    elif offset < 0.1:
        variant = ""
    elif offset < 0.3:
        variant = "+"
    else:
        variant = "++"

    return dan_index, variant


def _extract_first_numeric_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return math.nan
        return _extract_first_numeric_value(value.reshape(-1)[0])
    if isinstance(value, (list, tuple)) and value:
        return _extract_first_numeric_value(value[0])
    if value and isinstance(value, dict):
        if "data" in value:
            return _extract_first_numeric_value(value["data"])
        if "cpuData" in value:
            return _extract_first_numeric_value(value["cpuData"])
    return math.nan


def _normalize_msd_input(msd_values: Any) -> dict[str, float]:
    input_value = msd_values if isinstance(msd_values, dict) else {}
    return {
        "overall": float(input_value.get("Overall", math.nan)),
        "stream": float(input_value.get("Stream", math.nan)),
        "jumpstream": float(input_value.get("Jumpstream", math.nan)),
        "handstream": float(input_value.get("Handstream", math.nan)),
        "stamina": float(input_value.get("Stamina", math.nan)),
        "jackspeed": float(input_value.get("JackSpeed", math.nan)),
        "chordjack": float(input_value.get("Chordjack", math.nan)),
        "technical": float(input_value.get("Technical", math.nan)),
    }


def _fallback_msd_values(sunny_star: float, interlude_star: float) -> dict[str, float]:
    base = estimate_sunny_numeric(sunny_star)
    if base is None:
        base = max(0.0, float(sunny_star) if math.isfinite(sunny_star) else 0.0)
    mix = (base + (interlude_star if math.isfinite(interlude_star) else base)) / 2.0
    return {
        "Overall": mix,
        "Stream": mix * 0.98,
        "Jumpstream": mix * 0.95,
        "Handstream": mix * 0.94,
        "Stamina": mix * 1.03,
        "JackSpeed": mix * 0.92,
        "Chordjack": mix * 0.90,
        "Technical": mix * 0.96,
    }


def _get_model_session() -> Any:
    global _MODEL_SESSION, _MODEL_LOAD_FAILED
    if _MODEL_LOAD_FAILED:
        return None
    if _MODEL_SESSION is not None:
        return _MODEL_SESSION
    if ort is None or not _MODEL_PATH.exists():
        _MODEL_LOAD_FAILED = True
        return None

    try:
        _MODEL_SESSION = ort.InferenceSession(str(_MODEL_PATH), providers=["CPUExecutionProvider"])
        return _MODEL_SESSION
    except Exception:
        _MODEL_LOAD_FAILED = True
        return None


def _predict_raw_value(features: list[float]) -> float:
    session = _get_model_session()
    if session is not None:
        try:
            input_name = session.get_inputs()[0].name
            input_tensor = np.asarray(features, dtype=np.float32).reshape(1, FEATURE_COUNT)
            outputs = session.run(None, {input_name: input_tensor})
            output_value = outputs[0] if outputs else None
            raw_value = _extract_first_numeric_value(output_value)
            if math.isfinite(raw_value):
                return raw_value
        except Exception:
            pass

    overall, stream, jumpstream, handstream, stamina, jackspeed, chordjack, technical, interlude, sunny = features
    value = (
        0.24 * overall
        + 0.14 * stream
        + 0.11 * jumpstream
        + 0.11 * handstream
        + 0.10 * stamina
        + 0.09 * jackspeed
        + 0.08 * chordjack
        + 0.08 * technical
        + 0.10 * interlude
        + 0.05 * sunny
    )
    return clamp((value / 1.25) + 1.0, MIN_DAN, MAX_DAN)


def estimate_companella_result(
    source: Any,
    speed_rate: float = 1.0,
    cvt_flag: Any = None,
    *,
    sunny_result: dict[str, Any] | None = None,
    chart: Any = None,
    msd_values: dict[str, float] | None = None,
    interlude_star: float | None = None,
) -> dict[str, Any]:
    current_chart = chart or load_osu_chart(source)
    if int(current_chart.column_count) != 4:
        raise UnsupportedKeyError("Companella only supports 4K")

    if sunny_result is None:
        sunny_result = estimate_sunny_result(source, speed_rate, None, cvt_flag)

    sunny_star = float(sunny_result.get("star", math.nan))
    if not math.isfinite(sunny_star):
        sunny_star = 0.0

    if interlude_star is None:
        interlude_star = estimate_interlude_star_from_chart(current_chart, speed_rate, cvt_flag)
    if not math.isfinite(interlude_star):
        interlude_star = sunny_star

    if msd_values is None:
        try:
            msd_values = compute_difficulties(current_chart, music_rate=speed_rate, keycount=4, score_goal=0.93)
        except OfficialRunnerError:
            msd_values = None

    normalized = _normalize_msd_input(msd_values)
    if not math.isfinite(normalized["overall"]):
        fallback = _fallback_msd_values(sunny_star, interlude_star)
        normalized = _normalize_msd_input(fallback)

    if not math.isfinite(normalized["stream"]):
        fallback = _fallback_msd_values(sunny_star, interlude_star)
        normalized = _normalize_msd_input(fallback)

    features = [
        normalized["overall"],
        normalized["stream"],
        normalized["jumpstream"],
        normalized["handstream"],
        normalized["stamina"],
        normalized["jackspeed"],
        normalized["chordjack"],
        normalized["technical"],
        float(interlude_star),
        sunny_star,
    ]

    if any(not math.isfinite(value) for value in features):
        fallback = _fallback_msd_values(sunny_star, interlude_star)
        normalized = _normalize_msd_input(fallback)
        features = [
            normalized["overall"],
            normalized["stream"],
            normalized["jumpstream"],
            normalized["handstream"],
            normalized["stamina"],
            normalized["jackspeed"],
            normalized["chordjack"],
            normalized["technical"],
            float(interlude_star),
            sunny_star,
        ]

    raw_model_value = _predict_raw_value(features)
    shifted_raw_value = clamp(raw_model_value, MIN_DAN, MAX_DAN) + 1
    dan_index, variant = _parse_prediction(shifted_raw_value)
    label = DAN_LABELS[dan_index] if 0 <= dan_index < len(DAN_LABELS) else "?"

    rounded_raw = round(shifted_raw_value, 2)
    rounded_center = round(shifted_raw_value)
    confidence = max(0.0, 1.0 - abs(shifted_raw_value - rounded_center) * 2.0)

    return {
        "estDiff": _build_display_difficulty(label, variant),
        "numericDifficulty": rounded_raw,
        "numericDifficultyHint": None,
        "danLabel": label,
        "variant": variant,
        "confidence": confidence,
        "rawModelOutput": rounded_raw,
        "columnCount": 4,
        "lnRatio": float(sunny_result.get("lnRatio", 0.0)),
    }
