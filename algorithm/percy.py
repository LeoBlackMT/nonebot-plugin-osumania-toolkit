import asyncio

from PIL import Image
from typing import Tuple

class LNImageError(Exception):
    """自定义异常"""
    pass

def find_background_upwards(img, bg, col, start_y):
    """在指定列从start_y向上寻找背景色像素，返回y坐标"""
    for y in range(start_y, -1, -1):
        px = img.getpixel((col, y))
        if px == bg or px[3] == 0:
            return y
    raise LNImageError(f"在列 {col} 从 y={start_y} 向上未找到背景色像素。")

def parse_percy_cmd(cmd_text: str) -> Tuple:
    """
    解析percy命令参数
    
    参数:
        cmd_text: str, 命令文本
    
    返回:
        tuple: (新投皮程度d, lazer模式标记, 错误信息)
    """
    cmd_parts = cmd_text.split()
    err_msg = []

    d = None
    lzr_flag = False

    for part in cmd_parts:
        token = part.lower()
        if token in ("lazer", "lzr"):
            lzr_flag = True
            continue

        # 仅允许非负整数作为 d 参数；出现多个数字时使用第一个
        if part.isdigit():
            if d is None:
                d = int(part)
            continue

        if part.startswith("-") and part[1:].isdigit():
            err_msg.append("投皮程度参数必须是非负整数（≥0）。")

    return d, lzr_flag, err_msg

def normalize_height(img, target_h, bg):
    """标准化图片高度至32800px

    Args:
        img (PIL.Image): 要标准化高度的图片
        target_h (int): 目标高度
        bg (tuple): 背景色(RGBA)

    Returns:
        PIL.Image: 标准化高度后的图片
    """
    w, h = img.size
    if h == target_h:
        return img
    if h > target_h:
        return img.crop((0, 0, w, target_h))
    else:
        need = target_h - h
        new_img = Image.new("RGBA", (w, target_h), bg)
        new_img.paste(img, (0, 0))
        y_offset = h
        while y_offset < target_h:
            take = min(need, h)
            bottom_slice = img.crop((0, h - take, w, h))
            new_img.paste(bottom_slice, (0, y_offset))
            y_offset += take
            need -= take
        return new_img

def get_current_d(image_path):
    """返回当前图片的投机取巧程度 d

    Args:
        image_path (Path): 图片路径

    Raises:
        LNImageError: 图片结构错误

    Returns:
        int: 投机取巧程度 d
    """
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size
    bg = img.getpixel((0, 0))
    a_true = None
    for y in range(h):
        for x in range(w):
            if img.getpixel((x, y)) != bg:
                a_true = y
                break
        if a_true is not None:
            break
    if a_true is None:
        raise LNImageError("未找到非背景色像素，图片可能全为背景。")
    mid_y = h // 2
    x1 = None
    for x in range(w):
        if img.getpixel((x, mid_y)) != bg:
            x1 = x
            break
    if x1 is None:
        raise LNImageError("在左侧中点未能找到非背景色像素。")
    x2 = None
    for x in range(w-1, -1, -1):
        if img.getpixel((x, mid_y)) != bg:
            x2 = x
            break
    if x2 is None:
        raise LNImageError("在右侧中点未能找到非背景色像素。")
    y1 = find_background_upwards(img, bg, x1, mid_y)
    y2 = find_background_upwards(img, bg, x2, mid_y)
    y = max(y1, y2)

    return a_true

def _process_ln_image_sync(image_path, user_d, lzr=False, output_path=None):
    """处理ln图片

    Args:
        image_path (Path): 图片路径
        user_d (int): 用户指定的投机取巧程度
        lzr (bool, optional): 是否使用Lazer模式. Defaults to False.
        output_path (Path, optional): 输出图片路径. Defaults to None.

    Raises:
        LNImageError: 图片结构错误

    Returns:
        PIL.Image: 处理后的图片
    """
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size
    bg = img.getpixel((0, 0))

    a_true = None
    for y in range(h):
        for x in range(w):
            if img.getpixel((x, y)) != bg:
                a_true = y
                break
        if a_true is not None:
            break
    if a_true is None:
        raise LNImageError("未找到非背景色像素，图片可能全为背景。")

    mid_y = h // 2
    x1 = None
    for x in range(w):
        if img.getpixel((x, mid_y)) != bg:
            x1 = x
            break
    if x1 is None:
        raise LNImageError("在左侧中点未能找到非背景色像素。")
    x2 = None
    for x in range(w-1, -1, -1):
        if img.getpixel((x, mid_y)) != bg:
            x2 = x
            break
    if x2 is None:
        raise LNImageError("在右侧中点未能找到非背景色像素。")

    y1 = find_background_upwards(img, bg, x1, mid_y)
    y2 = find_background_upwards(img, bg, x2, mid_y)
    y = max(y1, y2)

    if y > a_true:
        if lzr:
            a_target = max(0, user_d - 75)
        else:
            a_target = user_d

        tail_h = y - a_true + 1
        y_target = a_target + tail_h - 1

        tail_region = img.crop((x1, a_true, x2 + 1, y + 1))
        body_region = None
        if y + 1 < h:
            body_region = img.crop((x1, y + 1, x2 + 1, h))
        body_h = body_region.height if body_region else 0

        fill_region = None
        body_new = body_region
        if y_target < y:
            gap = y - y_target
            if body_h == 0:
                raise LNImageError("需要填充间隙，但面身不存在，无法截取。")
            if gap > body_h:
                raise LNImageError("需要填充的间隙大于面身高度，无法单次截取。")
            fill_region = body_region.crop((0, 0, x2 - x1 + 1, gap))
            if body_h - gap > 0:
                body_new = body_region.crop((0, gap, x2 - x1 + 1, body_h))
            else:
                body_new = None
        elif y_target > y:
            overlap = y_target - y
            if body_h == 0:
                raise LNImageError("需要丢弃重叠部分，但面身不存在。")
            if overlap >= body_h:
                body_new = None
            else:
                body_new = body_region.crop((0, overlap, x2 - x1 + 1, body_h))
        else:
            pass

        tail_h = tail_region.height
        fill_h = fill_region.height if fill_region else 0
        body_new_h = body_new.height if body_new else 0
        total_h = a_target + tail_h + fill_h + body_new_h

        new_img = Image.new("RGBA", (w, total_h), bg)
        new_img.paste(tail_region, (x1, a_target))
        if fill_region:
            new_img.paste(fill_region, (x1, a_target + tail_h))
        if body_new:
            new_img.paste(body_new, (x1, a_target + tail_h + fill_h))

    else:
        if lzr:
            new_top = max(0, user_d - 75)
        else:
            new_top = user_d
        body_region = img.crop((x1, a_true, x2 + 1, h))
        body_h = body_region.height
        delta = new_top - a_true
        if delta > 0:
            gap = delta
            if gap > body_h:
                fill_region = body_region
                body_new = None
                new_img_h = new_top + gap
                new_img = Image.new("RGBA", (w, new_top + body_h), bg)
                new_img.paste(fill_region, (x1, new_top))
            else:
                fill_region = body_region.crop((0, 0, x2 - x1 + 1, gap))
                remaining_region = body_region.crop((0, gap, x2 - x1 + 1, body_h))
                new_img_h = new_top + body_h
                new_img = Image.new("RGBA", (w, new_img_h), bg)
                new_img.paste(fill_region, (x1, new_top))
                new_img.paste(remaining_region, (x1, new_top + gap))
        elif delta < 0:
            cut = -delta
            if cut >= body_h:
                new_img = Image.new("RGBA", (w, 0), bg)
                new_img = Image.new("RGBA", (w, 1), bg)
            else:
                remaining_region = body_region.crop((0, cut, x2 - x1 + 1, body_h))
                new_top_actual = max(0, new_top)
                new_img_h = new_top_actual + (body_h - cut)
                new_img = Image.new("RGBA", (w, new_img_h), bg)
                new_img.paste(remaining_region, (x1, new_top_actual))
        else:
            new_img = Image.new("RGBA", (w, h), bg)
            new_img.paste(body_region, (x1, a_true))

    if lzr:
        new_img = normalize_height(new_img, 32800, bg)

    if output_path:
        new_img.save(str(output_path))
    return new_img


async def process_ln_image(image_path, user_d, lzr=False, output_path=None):
    """异步处理ln图片，避免阻塞事件循环。"""
    return await asyncio.to_thread(
        _process_ln_image_sync,
        image_path,
        user_d,
        lzr,
        output_path,
    )