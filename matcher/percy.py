import asyncio
import os

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.exception import FinishedException

from ..file.file import safe_filename, download_file, cleanup_temp_file, get_file_url
from ..algorithm.percy import get_current_d, process_ln_image, parse_percy_cmd, LNImageError

from nonebot_plugin_localstore import get_plugin_cache_dir

CACHE_DIR = get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

percy = on_command("percy", aliases={"投皮"}, block=True)

@percy.handle()
async def handle_percy(bot: Bot, event: MessageEvent):
    if not event.reply:
        await percy.finish("请回复一条包含图片文件的消息。")

    reply = event.reply
    img_seg = None
    for seg in reply.message:
        if seg.type == "file":
            img_seg = seg
            break
        if seg.type == "image":
            img_seg = seg
            break

    if not img_seg:
        await percy.finish("回复的消息中没有找到图片文件。")
        
    cmd_text = event.get_plaintext().strip()
    d, lzr_flag, err_msg = parse_percy_cmd(cmd_text)
    if err_msg:
        await percy.finish(f"命令参数错误：{', '.join(err_msg)}")
        
    mode_text = "Lazer)约" if lzr_flag else "Stable)"

    # 使用辅助函数获取文件信息
    file_info = await get_file_url(bot, img_seg)
    if not file_info:
        await percy.finish("无法获取图片信息。请确保机器人有权限访问该图片，或者图片有效。")

    file_name, file_url = file_info
    file_name = os.path.basename(file_name)
    if not file_name.lower().endswith(".png"):
        await percy.finish("请回复 .png 格式的图片。")

    safe_name = safe_filename(file_name)
    file_path = CACHE_DIR / safe_name
    output_path = CACHE_DIR / f"processed_{safe_name}"

    try:
        success = await download_file(file_url, file_path)
        if not success:
            await percy.send("图片下载失败，请稍后重试。")
            return

        if d is None:
            current_d = get_current_d(file_path)
            current_d = (current_d + 75) if lzr_flag else current_d
            if current_d is not None:
                await percy.send(f"当前图片投机取巧程度({mode_text}为{current_d}px。")
                return
            else:
                await percy.send("无法识别当前图片的投机取巧程度。")
                return
        
        await process_ln_image(file_path, d, lzr_flag, output_path)

        # 先按普通图片发送，失败则降级为文件发送
        try:
            await percy.send(MessageSegment.image(output_path.resolve().as_uri()), at_sender=True)
        except Exception:
            file_seg = MessageSegment("file", {
                "file": output_path.resolve().as_uri(),
                "name": output_path.name,
            })
            await percy.send(file_seg, at_sender=True)

    except FinishedException:
        pass
    except LNImageError as e:
        await percy.send(f"图片结构不正确：{str(e)}")
    except Exception as e:
        await percy.send(f"处理过程中发生错误: {str(e)}")

    finally:
        asyncio.create_task(cleanup_temp_file(file_path))
        if output_path and output_path.exists():
            asyncio.create_task(cleanup_temp_file(output_path))