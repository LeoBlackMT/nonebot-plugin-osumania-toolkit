from pathlib import Path
from nonebot import require

require("nonebot_plugin_htmlkit")
from nonebot_plugin_htmlkit import html_to_pic  # type: ignore[import-not-found]

from ._template_cache import get_template_env

async def render_ett_card(template_dir: Path, data: dict) -> bytes:
    card_height = int(data.get("card_height", 520))
    card_height = max(460, min(card_height, 560))

    template = get_template_env(template_dir).get_template("ett.html")
    html = await template.render_async(**data)
    image_bytes = await html_to_pic(
        html=html,
        base_url=f"file://{template_dir.as_posix()}/",
        max_width=475,
        device_height=card_height,
        allow_refit=False,
    )
    return image_bytes