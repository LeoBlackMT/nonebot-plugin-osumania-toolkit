import asyncio
import json
import hashlib
from pathlib import Path
from collections import OrderedDict
from nonebot import require

require("nonebot_plugin_htmlkit")
from nonebot_plugin_htmlkit import html_to_pic

from ._template_cache import get_template_env

_FUTURE_NOT_READY_TEXT = "Future object is not initialized"
_MAPVIEW_RENDER_LOCK = asyncio.Lock()

# 渲染结果缓存：同一份模板数据（同一张谱面、同一组参数、同一版模板）直接复用 PNG。
# htmlkit 每次都要走一遍浏览器排版/截图，重复请求（改群、重发、图包重传）命中后
# 可省掉整段渲染时间；键里带模板文件 mtime，换模板自动失效。
_IMAGE_CACHE_MAX = 32
_image_cache: OrderedDict[tuple[str, int, str], bytes] = OrderedDict()


def _template_stamp(template_dir: Path) -> int:
    try:
        return (template_dir / "mapview.html").stat().st_mtime_ns
    except OSError:
        return 0


def _image_cache_key(template_dir: Path, data: dict) -> tuple[str, int, str]:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return (str(template_dir), _template_stamp(template_dir), digest)


async def _render_mapview_card_once(template_dir: Path, data: dict) -> bytes:
    template = get_template_env(template_dir).get_template("mapview.html")
    html = await template.render_async(**data)
    return await html_to_pic(
        html=html,
        base_url=f"file://{template_dir.as_posix()}/",
        max_width=475,
        device_height=490,
        allow_refit=False,
    )


async def render_analysis_card(TEMPLATE_DIR: Path, data: dict) -> bytes:
    cache_key = _image_cache_key(TEMPLATE_DIR, data)
    cached = _image_cache.get(cache_key)
    if cached is not None:
        _image_cache.move_to_end(cache_key)
        return cached

    # 使用串行渲染避免并发竞争触发 htmlkit future 初始化竞态。
    async with _MAPVIEW_RENDER_LOCK:
        # 双重检查：等待渲染锁期间可能已被同参数的另一个请求写入。
        cached = _image_cache.get(cache_key)
        if cached is not None:
            _image_cache.move_to_end(cache_key)
            return cached

        last_future_error: Exception | None = None

        for attempt in range(3):
            try:
                image = await _render_mapview_card_once(TEMPLATE_DIR, data)
                _image_cache[cache_key] = image
                _image_cache.move_to_end(cache_key)
                while len(_image_cache) > _IMAGE_CACHE_MAX:
                    _image_cache.popitem(last=False)
                return image
            except Exception as exc:
                if _FUTURE_NOT_READY_TEXT not in str(exc):
                    raise
                last_future_error = exc
                await asyncio.sleep(0.05 * (attempt + 1))

        # 保留一次最终重试，兼容极端延迟初始化场景。
        try:
            image = await _render_mapview_card_once(TEMPLATE_DIR, data)
        except Exception as exc:
            if _FUTURE_NOT_READY_TEXT in str(exc) and last_future_error is not None:
                raise RuntimeError(
                    "htmlkit 渲染器尚未完成初始化，请稍后重试。"
                ) from last_future_error
            raise
        _image_cache[cache_key] = image
        _image_cache.move_to_end(cache_key)
        while len(_image_cache) > _IMAGE_CACHE_MAX:
            _image_cache.popitem(last=False)
        return image
