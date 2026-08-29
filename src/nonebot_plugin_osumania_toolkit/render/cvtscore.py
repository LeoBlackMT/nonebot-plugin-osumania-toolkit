import asyncio

from pathlib import Path
from typing import Any, Optional
from nonebot import require

require("nonebot_plugin_htmlkit")
from nonebot_plugin_htmlkit import html_to_pic

from ._template_cache import get_template_env

_FUTURE_NOT_READY_TEXT = "Future object is not initialized"
_CVTSCORE_RENDER_LOCK = asyncio.Lock()
_CVTSCORE_TEMPLATE_NAME = "cvtscore.html"

async def _render_cvtscore_card_once(template_dir: Path, data: dict[str, Any]) -> bytes:
    # try:
    #     card_height = int(data.get("card_height", 400))
    # except Exception:
    #     card_height = 400
    # card_height = min(620, max(450, card_height))
    card_height = 400

    template = get_template_env(template_dir).get_template(_CVTSCORE_TEMPLATE_NAME)
    html = await template.render_async(**data)
    return await html_to_pic(
        html=html,
        base_url=f"file://{template_dir.as_posix()}/",
        max_width=475,
        device_height=card_height,
        allow_refit=False,
    )


async def render_cvtscore_card(data: dict[str, Any], template_dir: Path | None = None) -> bytes:

    async with _CVTSCORE_RENDER_LOCK:
        last_future_error: Exception | None = None

        for attempt in range(3):
            try:
                return await _render_cvtscore_card_once(template_dir, data)
            except Exception as exc:
                if _FUTURE_NOT_READY_TEXT not in str(exc):
                    raise
                last_future_error = exc
                await asyncio.sleep(0.05 * (attempt + 1))

        try:
            return await _render_cvtscore_card_once(template_dir, data)
        except Exception as exc:
            if _FUTURE_NOT_READY_TEXT in str(exc) and last_future_error is not None:
                raise RuntimeError("htmlkit renderer is not ready, please retry later.") from last_future_error
            raise