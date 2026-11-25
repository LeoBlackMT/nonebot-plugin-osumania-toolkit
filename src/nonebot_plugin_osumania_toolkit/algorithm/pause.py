from __future__ import annotations

from typing import Any


def format_mmss(value_ms: float) -> str:
    total_seconds = max(0, int(round(float(value_ms) / 1000.0)))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _playback_rate(osr_obj: Any) -> float:
    value = getattr(osr_obj, "score_info_speed_rate", None)
    if value is None:
        value = getattr(osr_obj, "speed_factor", 1.0)
    try:
        rate = float(value)
    except (TypeError, ValueError):
        rate = 1.0
    return rate if rate > 0 else 1.0


def format_pause_line(
    osr_obj: Any,
    osu_obj: Any = None,
    *,
    margin_ms: int = 500,
) -> str | None:
    """把 `.osr` 的暂停数据格式化为一行；无数据返回 None。"""
    if osr_obj is None:
        return None
    if not bool(getattr(osr_obj, "pause_available", False)):
        count = int(getattr(osr_obj, "pause_count", 0) or 0)
        if count > 0:
            return f"暂停次数: {count}（无时间戳）"
        return None

    pauses = [int(value) for value in (getattr(osr_obj, "pauses", []) or [])]
    rate = _playback_rate(osr_obj)
    lower = float("-inf")
    upper = float("inf")
    if osu_obj is not None:
        starts = getattr(osu_obj, "note_starts", []) or []
        ends = getattr(osu_obj, "note_ends", []) or []
        if starts:
            lower = float(min(starts))
        if ends:
            upper = float(max(ends) - margin_ms)
        elif starts:
            upper = float(max(starts) - margin_ms)

    filtered = [pause / rate for pause in pauses if lower <= pause < upper and pause >= 0]
    if not filtered:
        return "暂停次数: 0"
    positions = " / ".join(format_mmss(value) for value in filtered)
    return f"暂停次数: {len(filtered)}（{positions}）"
