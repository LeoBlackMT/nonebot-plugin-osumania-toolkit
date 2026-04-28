import os
import asyncio
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.log import logger

from ..parser.osr_file_parser import osr_file

from ..render.lifebar import plot_life
from ..file.path import safe_filename
from ..api.download import download_file, get_file_url
from ..file.cleanup import cleanup_temp_file

from ..file.cache import CACHE_DIR
CACHE_DIR.mkdir(parents=True, exist_ok=True)

lifebar = on_command("lifebar", aliases={"血条", "life"})

@lifebar.handle()
async def handle_lifebar(bot: Bot, event: MessageEvent):
    if not event.reply:
        await lifebar.finish("请回复一条包含 .osr 文件的消息。")

    reply = event.reply
    file_seg = None
    for seg in reply.message:
        if seg.type == "file":
            file_seg = seg
            break

    if not file_seg:
        await lifebar.finish("回复的消息中没有找到文件。")

    # 使用辅助函数获取文件信息
    file_info = await get_file_url(bot, file_seg)
    if not file_info:
        await lifebar.finish("无法获取文件信息。请确保机器人有权限访问该文件，或者文件链接有效。")

    file_name, file_url = file_info
    file_name = os.path.basename(file_name)
    if not file_name.lower().endswith(".osr"):
        await lifebar.finish("请回复 .osr 格式的回放文件。")
    if file_name.lower().endswith(".mr"):
        await lifebar.finish("该命令不支持Malody格式的回放文件。")

    await lifebar.send(f"已收到文件：{file_name}，请稍候...")

    safe_name = safe_filename(file_name)
    file_path = CACHE_DIR / safe_name

    try:
        success = await download_file(file_url, file_path)
        if not success:
            await lifebar.send("文件下载失败，请稍后重试。")
            return

        data = await asyncio.to_thread(osr_file, file_path)
        await asyncio.to_thread(data.process)
        match data.status:
            case "NotMania":
                await lifebar.send("该回放不是 Mania 模式。")
                return
            case "tooFewKeys":
                await lifebar.send("有效轨道数量过少，无法分析。")
                return
            case "init":
                await lifebar.send("回放尚未process。")
                return
            case _:
                pass
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, plot_life, data, str(CACHE_DIR)
        )
        
        output_path = result
        await lifebar.send(MessageSegment.image(f"file://{output_path}"))
        
    except Exception as e:
        logger.exception("处理回放时出错")
        await lifebar.send(f"处理过程中发生错误：{type(e).__name__}: {e}")

    finally:
        if file_path and file_path.exists():
            asyncio.create_task(cleanup_temp_file(file_path))
        if output_path and Path(output_path).exists():
            asyncio.create_task(cleanup_temp_file(Path(output_path)))
    return