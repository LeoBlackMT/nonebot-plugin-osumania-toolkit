import asyncio
from pathlib import Path
from nonebot import require

require("nonebot_plugin_htmlkit")
from nonebot_plugin_htmlkit import template_to_pic

_FUTURE_NOT_READY_TEXT = "Future object is not initialized"
_MAPVIEW_RENDER_LOCK = asyncio.Lock()

async def _render_mapview_card_once(template_dir: Path, data: dict) -> bytes:
    return await template_to_pic(
        template_path=template_dir,
        template_name="mapview.html",
        templates=data,
        max_width=475,
        device_height=490,
        allow_refit=False,
    )

async def render_analysis_card(TEMPLATE_DIR: Path, data: dict) -> bytes:
    # 使用串行渲染避免并发竞争触发 htmlkit future 初始化竞态。
    async with _MAPVIEW_RENDER_LOCK:
        last_future_error: Exception | None = None

        for attempt in range(3):
            try:
                return await _render_mapview_card_once(TEMPLATE_DIR, data)
            except Exception as exc:
                if _FUTURE_NOT_READY_TEXT not in str(exc):
                    raise
                last_future_error = exc
                await asyncio.sleep(0.05 * (attempt + 1))

        # 保留一次最终重试，兼容极端延迟初始化场景。
        try:
            return await _render_mapview_card_once(TEMPLATE_DIR, data)
        except Exception as exc:
            if _FUTURE_NOT_READY_TEXT in str(exc) and last_future_error is not None:
                raise RuntimeError("htmlkit 渲染器尚未完成初始化，请稍后重试。") from last_future_error
            raise