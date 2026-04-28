from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import onnxruntime as ort
import numpy as np

from .interlude import calculate_interlude_star
from ..ett.calc import compute_difficulties
from .exceptions import UnsupportedKeyError
from .shared import load_osu_chart, resolve_chart_path
from .sunny import estimate_sunny_result


DAN_LABELS = [
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "alpha", "beta", "gamma", "delta", "epsilon",
    "Emik Zeta", "Thaumiel Eta", "CloverWisp Theta", "iota", "kappa",
]

FEATURE_COUNT = 10
MIN_DAN = 1.0
MAX_DAN = 20.0
VARIANT_TEXT = {"--": "low", "-": "mid/low", "": "mid", "+": "mid/high", "++": "high"}

_SESSION: ort.InferenceSession | None = None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _resolve_model_path() -> Path:
    candidates = [
        Path(__file__).resolve().parent / "dan_model.onnx",
        # 未来可以支持更多候选路径，例如用户自定义路径或环境变量指定路径
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Companella ONNX model not found")


def _extract_first_numeric_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, np.generic):
        return float(value)
    if isinstance(value, np.ndarray):
        flattened = value.reshape(-1)
        if flattened.size:
            return _extract_first_numeric_value(flattened[0])
    if isinstance(value, (list, tuple)) and value:
        return _extract_first_numeric_value(value[0])
    if hasattr(value, "data"):
        return _extract_first_numeric_value(getattr(value, "data"))
    if hasattr(value, "cpuData"):
        return _extract_first_numeric_value(getattr(value, "cpuData"))
    try:
        return float(value)
    except Exception:
        return math.nan


def _parse_prediction(raw_value: float) -> tuple[int, str]:
    if raw_value < MIN_DAN:
        return 0, "--"
    if raw_value >= MAX_DAN:
        return 19, "++"

    dan_level = int(_clamp(round(raw_value), 1, 20))
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


def _capitalize_label(label: Any) -> str:
    text = str(label or "?").strip()
    if not text:
        return "?"
    if text.isdigit():
        return text
    return " ".join(part[:1].upper() + part[1:].lower() for part in text.split())


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


def _build_display_difficulty(label: str, variant: str) -> str:
    variant_text = VARIANT_TEXT.get(variant, VARIANT_TEXT[""])
    capped_label = _capitalize_label(label)
    if capped_label.isdigit():
        return f"Reform {capped_label} {variant_text}"
    return f"{capped_label} {variant_text}"


def _get_session() -> ort.InferenceSession:
    global _SESSION
    if _SESSION is not None:
        return _SESSION

    model_path = _resolve_model_path()
    _SESSION = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    return _SESSION


def classify_companella_difficulty(
    *,
    msd_values: Any = None,
    interlude_star: Any = None,
    sunny_star: Any = None,
) -> dict[str, Any]:
    normalized = _normalize_msd_input(msd_values)
    interlude_value = float(interlude_star)
    sunny_value = float(sunny_star)

    features = [
        normalized["overall"],
        normalized["stream"],
        normalized["jumpstream"],
        normalized["handstream"],
        normalized["stamina"],
        normalized["jackspeed"],
        normalized["chordjack"],
        normalized["technical"],
        interlude_value,
        sunny_value,
    ]

    if len(features) != FEATURE_COUNT or any(not math.isfinite(v) for v in features):
        raise ValueError("Companella requires valid MSD, InterludeSR, and Sunny SR values")

    session = _get_session()
    input_name = session.get_inputs()[0].name
    input_tensor = np.array(features, dtype=np.float32).reshape(1, FEATURE_COUNT)
    outputs = session.run(None, {input_name: input_tensor})
    raw_model_value = _extract_first_numeric_value(outputs[0] if outputs else math.nan)
    if not math.isfinite(raw_model_value):
        raise ValueError("Companella model output is invalid")

    shifted_raw_value = _clamp(raw_model_value, MIN_DAN, MAX_DAN) + 1.0
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
    }


def _resolve_source_for_analysis(source: Any) -> Path:
    if isinstance(source, Path):
        return source
    if isinstance(source, str):
        return resolve_chart_path(source)
    return resolve_chart_path(source)


def estimate_companella_result(
    source: Any,
    speed_rate: float = 1.0,
    cvt_flag: Any = None,
    *,
    sunny_result: dict[str, Any] | None = None,
    interlude_star: float | None = None,
    msd_values: dict[str, float] | None = None,
) -> dict[str, Any]:
    sunny_result = sunny_result or estimate_sunny_result(source, speed_rate, None, cvt_flag)
    if int(sunny_result.get("columnCount", 0) or 0) != 4:
        raise UnsupportedKeyError("Companella only supports 4K maps")

    if interlude_star is None:
        interlude_star = calculate_interlude_star(source, speed_rate, cvt_flag)

    if msd_values is None:
        chart = load_osu_chart(_resolve_source_for_analysis(source))
        msd_values = compute_difficulties(chart, music_rate=speed_rate, keycount=4)

    companella = classify_companella_difficulty(
        msd_values=msd_values,
        interlude_star=interlude_star,
        sunny_star=sunny_result.get("star"),
    )

    return {
        **sunny_result,
        "estDiff": companella["estDiff"],
        "numericDifficulty": companella["numericDifficulty"],
        "numericDifficultyHint": companella["numericDifficultyHint"],
    }
