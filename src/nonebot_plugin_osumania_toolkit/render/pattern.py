import asyncio

from nonebot import require

require("nonebot_plugin_htmlkit")
from nonebot_plugin_htmlkit import template_to_pic

from pathlib import Path
from typing import Any

_TEMPLATE_NAME = "pattern.html"
_PATTERN_RENDER_LOCK = asyncio.Lock()
_FUTURE_NOT_READY_TEXT = "Future object is not initialized"

def default_template_dir() -> Path:
    """Resolve default template directory from this file's location."""
    return Path(__file__).resolve().parents[1] / "templates"


async def _render_pattern_card_once(template_dir: Path, data: dict[str, Any]) -> bytes:
    return await template_to_pic(
        template_path=template_dir,
        template_name=_TEMPLATE_NAME,
        templates=data,
        max_width=475,
        device_height=520,
        allow_refit=False,
    )


async def render_pattern_card(data: dict[str, Any], template_dir: Path | None = None) -> bytes:

    async with _PATTERN_RENDER_LOCK:
        last_future_error: Exception | None = None

        for attempt in range(3):
            try:
                return await _render_pattern_card_once(template_dir, data)
            except Exception as exc:
                if _FUTURE_NOT_READY_TEXT not in str(exc):
                    raise
                last_future_error = exc
                await asyncio.sleep(0.05 * (attempt + 1))

        try:
            return await _render_pattern_card_once(template_dir, data)
        except Exception as exc:
            if _FUTURE_NOT_READY_TEXT in str(exc) and last_future_error is not None:
                raise RuntimeError("htmlkit renderer is not ready, please retry later.") from last_future_error
            raise
