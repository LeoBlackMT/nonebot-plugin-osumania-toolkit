from pathlib import Path
from nonebot import require

require("nonebot_plugin_htmlkit")
from nonebot_plugin_htmlkit import template_to_pic  # type: ignore[import-not-found]

async def render_ett_card(template_dir: Path, data: dict) -> bytes:
    card_height = int(data.get("card_height", 520))
    card_height = max(460, min(card_height, 560))

    image_bytes = await template_to_pic(
        template_path=template_dir,
        template_name="ett.html",
        templates=data,
        max_width=475,
        device_height=card_height,
        allow_refit=False,
    )
    return image_bytes