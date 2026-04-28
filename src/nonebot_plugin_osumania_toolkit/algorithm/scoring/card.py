"""Cvtscore card data builder and chart/replay validation."""
from __future__ import annotations

from typing import Any, Optional

from ...parser.mr_file_parser import mr_file
from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import osu_file
from ...parser.ruleset_file_parser import ruleset_file
from .convert import _format_grade, _format_lamp, _format_accuracy_percent, _visible_warnings


def _normalize_argb_color(color: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(color, list) or len(color) != 4:
        return None

    channels: list[int] = []
    for value in color:
        if not isinstance(value, int):
            return None
        channels.append(min(255, max(0, value)))

    return channels[0], channels[1], channels[2], channels[3]


def _rgba_css_from_argb(
    color: Any,
    *,
    alpha_scale: float,
    alpha_floor: float,
    fallback: str,
) -> str:
    argb = _normalize_argb_color(color)
    if argb is None:
        return fallback

    a, r, g, b = argb
    alpha = min(1.0, max(alpha_floor, (a / 255.0) * alpha_scale))
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


def _srgb_to_linear(channel: int) -> float:
    value = channel / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _relative_luminance_from_argb(color: Any) -> float | None:
    argb = _normalize_argb_color(color)
    if argb is None:
        return None

    _, r, g, b = argb
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def _text_color_for_argb(color: Any) -> str:
    lum = _relative_luminance_from_argb(color)
    if lum is None:
        return "#f5f7ff"
    return "#0f1424" if lum >= 0.62 else "#f5f7ff"


def _find_named_color(items: Any, name: str) -> Any:
    if not isinstance(items, list):
        return None

    target = str(name or "").strip().lower()
    if not target:
        return None

    for item in items:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("Name", "")).strip().lower()
        if item_name == target:
            return item.get("Color")
    return None


def _build_judgement_rows(score: dict[str, Any], rs: ruleset_file) -> list[dict[str, Any]]:
    counts = score.get("judgement_counts", [])
    if not isinstance(counts, list):
        counts = []

    judgements = rs.raw_data.get("Judgements", []) if isinstance(rs.raw_data, dict) else []
    if not isinstance(judgements, list):
        return []

    rows: list[dict[str, Any]] = []
    for idx, judgement in enumerate(judgements):
        if not isinstance(judgement, dict):
            continue

        name = str(judgement.get("Name", f"J{idx}"))
        count = 0
        if idx < len(counts):
            try:
                count = int(counts[idx])
            except Exception:
                count = 0

        color = judgement.get("Color")
        rows.append(
            {
                "name": name,
                "count": str(max(0, count)),
                "bg": _rgba_css_from_argb(
                    color,
                    alpha_scale=0.35,
                    alpha_floor=0.16,
                    fallback="rgba(255, 255, 255, 0.14)",
                ),
                "border": _rgba_css_from_argb(
                    color,
                    alpha_scale=0.9,
                    alpha_floor=0.34,
                    fallback="rgba(255, 255, 255, 0.30)",
                ),
                "text": _text_color_for_argb(color),
                "swatch": _rgba_css_from_argb(
                    color,
                    alpha_scale=1.0,
                    alpha_floor=0.7,
                    fallback="rgba(255, 255, 255, 0.85)",
                ),
            }
        )

    return rows


def _format_combo_text(score: dict[str, Any]) -> str:
    combo = score.get("combo", {}) if isinstance(score.get("combo"), dict) else {}
    best_combo = int(combo.get("best_combo", 0) or 0)
    combo_breaks = int(combo.get("combo_breaks", 0) or 0)
    return f"{best_combo} ({combo_breaks}X)"


def _is_visible_badge_value(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized not in {"", "none", "无"}


def _build_judgement_bar_rows(score: dict[str, Any], rs: ruleset_file) -> list[dict[str, Any]]:
    counts = score.get("judgement_counts", [])
    if not isinstance(counts, list):
        counts = []

    judgements = rs.raw_data.get("Judgements", []) if isinstance(rs.raw_data, dict) else []
    if not isinstance(judgements, list):
        return []

    normalized: list[tuple[str, int, Any]] = []
    max_count = 0

    for idx, judgement in enumerate(judgements):
        if not isinstance(judgement, dict):
            continue

        name = str(judgement.get("Name", f"J{idx}"))
        count = 0
        if idx < len(counts):
            try:
                count = max(0, int(counts[idx]))
            except Exception:
                count = 0

        max_count = max(max_count, count)
        normalized.append((name, count, judgement.get("Color")))

    if max_count <= 0:
        max_count = 1

    rows: list[dict[str, Any]] = []
    for name, count, color in normalized:
        width = 0.0 if count <= 0 else min(100.0, max(6.0, count / max_count * 100.0))
        rows.append(
            {
                "name": name,
                "count": str(count),
                "width": f"{width:.1f}%",
                "track": _rgba_css_from_argb(
                    color,
                    alpha_scale=0.26,
                    alpha_floor=0.12,
                    fallback="rgba(75, 90, 128, 0.34)",
                ),
                "fill": _rgba_css_from_argb(
                    color,
                    alpha_scale=1.0,
                    alpha_floor=0.62,
                    fallback="rgba(85, 200, 255, 0.82)",
                ),
                "count_bg": _rgba_css_from_argb(
                    color,
                    alpha_scale=0.34,
                    alpha_floor=0.16,
                    fallback="rgba(255, 255, 255, 0.14)",
                ),
                "count_border": _rgba_css_from_argb(
                    color,
                    alpha_scale=0.9,
                    alpha_floor=0.34,
                    fallback="rgba(255, 255, 255, 0.30)",
                ),
                "count_text": _text_color_for_argb(color),
            }
        )

    return rows


def _resolve_cvtscore_card_height(use_bar_chart: bool, row_count: int) -> int:
    safe_rows = max(1, int(row_count))
    if use_bar_chart:
        return int(min(580, max(460, 380 + safe_rows * 20)))
    return int(min(600, max(470, 400 + safe_rows * 14)))


def _build_score_section(
    title: str,
    score: dict[str, Any],
    rs: ruleset_file,
    *,
    prefer_bar_chart: bool,
) -> dict[str, Any]:
    grade_name = _format_grade(score)
    lamp_name = _format_lamp(score)

    grades = rs.raw_data.get("Grades", []) if isinstance(rs.raw_data, dict) else []
    lamps = rs.raw_data.get("Lamps", []) if isinstance(rs.raw_data, dict) else []

    grade_color = _find_named_color(grades, grade_name)
    lamp_color = _find_named_color(lamps, lamp_name)

    warnings = _visible_warnings(score)
    chip_rows = _build_judgement_rows(score, rs)
    bar_rows = _build_judgement_bar_rows(score, rs)

    # 估算条形图高度，超出可用空间时回退到原 chip 形式。
    estimated_bar_height = len(bar_rows) * 30
    use_bar_chart = bool(prefer_bar_chart and bar_rows and estimated_bar_height <= 250)
    card_height = _resolve_cvtscore_card_height(
        use_bar_chart=use_bar_chart,
        row_count=len(bar_rows) if use_bar_chart else len(chip_rows),
    )

    show_grade = _is_visible_badge_value(grade_name)
    show_lamp = _is_visible_badge_value(lamp_name)

    return {
        "title": title,
        "grade": grade_name if show_grade else "",
        "grade_bg": _rgba_css_from_argb(
            grade_color,
            alpha_scale=0.36,
            alpha_floor=0.16,
            fallback="rgba(255, 255, 255, 0.14)",
        ),
        "grade_border": _rgba_css_from_argb(
            grade_color,
            alpha_scale=0.9,
            alpha_floor=0.34,
            fallback="rgba(255, 255, 255, 0.30)",
        ),
        "grade_text": _text_color_for_argb(grade_color),
        "show_grade": show_grade,
        "lamp": lamp_name if show_lamp else "",
        "lamp_bg": _rgba_css_from_argb(
            lamp_color,
            alpha_scale=0.36,
            alpha_floor=0.16,
            fallback="rgba(135, 155, 190, 0.18)",
        ),
        "lamp_border": _rgba_css_from_argb(
            lamp_color,
            alpha_scale=0.9,
            alpha_floor=0.34,
            fallback="rgba(135, 155, 190, 0.35)",
        ),
        "lamp_text": _text_color_for_argb(lamp_color),
        "show_lamp": show_lamp,
        "accuracy": _format_accuracy_percent(score, rs),
        "combo": _format_combo_text(score),
        "judgements": chip_rows,
        "judgement_bars": bar_rows,
        "use_bar_chart": use_bar_chart,
        "card_height": card_height,
        "warnings_text": "；".join(warnings[:2]),
    }


def build_cvtscore_card_data(
    *,
    source_info: dict[str, Any],
    target_info: dict[str, Any],
    source_ruleset: ruleset_file,
    target_ruleset: ruleset_file,
    source_score: dict[str, Any],
    target_score: dict[str, Any],
) -> dict[str, Any]:
    target_section = _build_score_section(
        "Converted Score",
        target_score,
        target_ruleset,
        prefer_bar_chart=True,
    )

    return {
        "status_text": "Conversion Complete",
        "source_display": str(source_info.get("display", "Unknown")),
        "target_display": str(target_info.get("display", "Unknown")),
        "target": target_section,
        "card_height": int(target_section.get("card_height", 500)),
    }


def validate_replay_status(
    replay_kind: str,
    osr_obj: Optional[osr_file] = None,
    mr_obj: Optional[mr_file] = None,
) -> Optional[str]:
    if replay_kind.lower() == "osr":
        if osr_obj is None:
            return "osr 回放对象为空。"
        status = str(getattr(osr_obj, "status", ""))
        if status == "NotMania":
            return "该回放不是 Mania 模式。"
        if status == "tooFewKeys":
            return "有效轨道数量过少，无法计算。"
        if status != "OK":
            return f"回放状态异常: {status}"
        return None

    if replay_kind.lower() == "mr":
        if mr_obj is None:
            return "mr 回放对象为空。"
        status = str(getattr(mr_obj, "status", ""))
        if status != "OK":
            return f"mr 回放状态异常: {status}"
        return None

    return f"不支持的回放类型: {replay_kind}"


def validate_chart_status(osu_obj: osu_file) -> Optional[str]:
    status = str(getattr(osu_obj, "status", ""))
    if status == "NotMania":
        return "该谱面不是 Mania 模式。"
    if status != "OK":
        return f"谱面状态异常: {status}"
    return None
