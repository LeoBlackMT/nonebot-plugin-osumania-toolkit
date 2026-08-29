"""批量结果图片拼接为长图（QQ 官方适配器替代合并转发）。"""
from __future__ import annotations

import io
import math

from PIL import Image as PILImage


def merge_images_to_grid(
    images: list[bytes], max_cols: int = 2, padding: int = 10
) -> bytes:
    """将多张图片拼接为网格长图，超 8MB 自动转 JPEG。"""
    if not images:
        return b""
    if len(images) == 1:
        return images[0]

    # 读取所有图片并统一尺寸
    pil_images: list[PILImage.Image] = []
    for img_bytes in images:
        pil_images.append(PILImage.open(io.BytesIO(img_bytes)))
    max_w = max(img.width for img in pil_images)
    max_h = max(img.height for img in pil_images)

    # 计算网格行列数
    cols = min(max_cols, len(images))
    rows = math.ceil(len(images) / cols)

    # 创建画布
    canvas_w = max_w * cols + padding * (cols + 1)
    canvas_h = max_h * rows + padding * (rows + 1)
    canvas = PILImage.new("RGB", (canvas_w, canvas_h), (255, 255, 255))

    # 按网格粘贴
    for idx, img in enumerate(pil_images):
        row, col = divmod(idx, cols)
        x = padding + col * (max_w + padding)
        y = padding + row * (max_h + padding)
        # 居中放置
        x_off = (max_w - img.width) // 2
        y_off = (max_h - img.height) // 2
        canvas.paste(img, (x + x_off, y + y_off))

    # 优先 PNG
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    if len(png_bytes) <= 8 * 1024 * 1024:
        return png_bytes

    # 超 8MB 转 JPEG
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=88)
    return buf.getvalue()
