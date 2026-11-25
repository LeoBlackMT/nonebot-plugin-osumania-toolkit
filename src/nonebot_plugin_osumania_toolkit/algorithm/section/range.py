from __future__ import annotations

import re
from dataclasses import dataclass

_TIME_TOKEN_RE = re.compile(
    r"^(?:\d+(?::\d{1,2}){0,2}(?:\.\d+)?|\d+(?:\.\d+)?(?:ms|s)?)$"
)
_RANGE_SEP_RE = re.compile(r"\s*[-~]\s*")


@dataclass(slots=True)
class SectionSpec:
    """一次区间分析的输入与换算结果（全部为毫秒）。"""

    start_playback_ms: int
    end_playback_ms: int
    start_chart_ms: int
    end_chart_ms: int
    rate: float

    @property
    def duration_playback_ms(self) -> int:
        return self.end_playback_ms - self.start_playback_ms

    @property
    def duration_chart_ms(self) -> int:
        return self.end_chart_ms - self.start_chart_ms


def parse_time_token(token: str) -> int:
    """把 ``1:30`` / ``90`` / ``90s`` / ``90000ms`` 解析为毫秒。"""
    text = str(token or "").strip().lower()
    if not text or not _TIME_TOKEN_RE.match(text):
        raise ValueError(f"无法解析时间: {token}")
    if text.endswith("ms"):
        value = float(text[:-2])
        return int(round(value))
    if text.endswith("s"):
        value = float(text[:-1])
        return int(round(value * 1000.0))
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            minutes, seconds = parts
            return int(round((float(minutes) * 60.0 + float(seconds)) * 1000.0))
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(
                round(
                    (float(hours) * 3600.0 + float(minutes) * 60.0 + float(seconds))
                    * 1000.0
                )
            )
        raise ValueError(f"无法解析时间: {token}")
    return int(round(float(text) * 1000.0))


def parse_section_range(text: str, speed_rate: float = 1.0) -> SectionSpec:
    """解析 ``start-end``（播放时间），并换算为谱面时间。"""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("区间不能为空，格式: 1:30-2:10")
    if raw.startswith("-"):
        raise ValueError("区间起点不能为负数，格式: 1:30-2:10")
    parts = _RANGE_SEP_RE.split(raw, maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("区间格式错误，格式: 1:30-2:10")

    start_playback_ms = parse_time_token(parts[0])
    end_playback_ms = parse_time_token(parts[1])
    if end_playback_ms <= start_playback_ms:
        raise ValueError("区间终点必须晚于起点")

    try:
        rate = float(speed_rate)
    except (TypeError, ValueError):
        rate = 1.0
    if not rate > 0.0:
        rate = 1.0

    return SectionSpec(
        start_playback_ms=start_playback_ms,
        end_playback_ms=end_playback_ms,
        start_chart_ms=int(round(start_playback_ms * rate)),
        end_chart_ms=int(round(end_playback_ms * rate)),
        rate=rate,
    )
