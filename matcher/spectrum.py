import os
import asyncio
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.log import logger

from ..file.osr_file_parser import osr_file
from ..file.mr_file_parser import mr_file

from ..file.draw import plot_spectrum
from ..file.file import safe_filename, download_file, cleanup_temp_file
from ..algorithm.convert import convert_mr_to_osr


from nonebot_plugin_localstore import get_plugin_cache_dir

CACHE_DIR = get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

spectrum = on_command("spectrum", aliases={"频谱"})

@spectrum.handle()
async def handle_spectrum(event: MessageEvent):
    if not event.reply:
        await spectrum.finish("请回复一条包含回放文件的消息。")

    reply = event.reply
    file_seg = None
    for seg in reply.message:
        if seg.type == "file":
            file_seg = seg
            break

    if not file_seg:
        await spectrum.finish("回复的消息中没有找到文件。")

    file_name = file_seg.data.get("file", "")
    file_url = file_seg.data.get("url", "")
    
    if not file_name:
        await spectrum.finish("无法获取文件名。")
    if not file_url:
        await spectrum.finish("无法获取文件下载链接。")
    file_name = os.path.basename(file_name)
    if not (file_name.lower().endswith(".osr") or file_name.lower().endswith(".mr")) :
        await spectrum.finish("请回复 .osr 或 .mr 格式的回放文件。")
    if not file_url:
        await spectrum.finish("无法获取文件下载链接。")
    
    await spectrum.send(f"已收到文件：{file_name}，请稍候...")

    safe_name = safe_filename(file_name)
    file_path = CACHE_DIR / safe_name

    try:
        success = await download_file(file_url, file_path)
        if not success:
            await spectrum.send("文件下载失败，请稍后重试。")
            return

        if file_name.lower().endswith(".mr"):
            data = convert_mr_to_osr(mr_file(file_path))
        else:
            data = osr_file(file_path)
            data.process()
            
        match data.status:
            case "NotMania":
                await spectrum.send("该回放不是 Mania 模式。")
                return
            case "tooFewKeys":
                await spectrum.send("有效轨道数量过少，无法分析。")
                return
            case "init":
                await spectrum.send("回放尚未process。")
                return
            case _:
                pass
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, plot_spectrum, data, str(CACHE_DIR)
        )
        
        output_path = result
        await spectrum.send(MessageSegment.image(f"file://{output_path}"))
        
    except Exception as e:
        logger.exception("处理回放时出错")
        await spectrum.send(f"处理过程中发生错误：{type(e).__name__}: {e}")

    finally:
        if file_path and file_path.exists():
            asyncio.create_task(cleanup_temp_file(file_path))
        if output_path and Path(output_path).exists():
            asyncio.create_task(cleanup_temp_file(Path(output_path)))
    return