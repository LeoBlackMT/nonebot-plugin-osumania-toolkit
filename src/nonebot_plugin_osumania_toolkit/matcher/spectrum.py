import os
import asyncio
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.log import logger

from ..parser.osr_file_parser import osr_file
from ..parser.mr_file_parser import mr_file

from ..render.spectrum import plot_spectrum
from ..file.path import safe_filename
from ..api.download import download_file
from ..file.cleanup import cleanup_temp_file
from ..algorithm.conversion import convert_mr_to_osr
from .. import platform

from ..file.cache import CACHE_DIR

CACHE_DIR.mkdir(parents=True, exist_ok=True)

spectrum = on_command("spectrum", aliases={"频谱"})

@spectrum.handle()
async def handle_spectrum(bot: Bot, event: MessageEvent):
    if not event.reply:
        await spectrum.finish("请回复一条包含回放文件的消息。")

    file_info = await platform.extract_replied_file(bot, event)
    if not file_info:
        await spectrum.finish("回复的消息中没有找到文件。")
    file_name, file_url = file_info
    file_name = os.path.basename(file_name)
    if not (file_name.lower().endswith(".osr") or file_name.lower().endswith(".mr")) :
        await spectrum.finish("请回复 .osr 或 .mr 格式的回放文件。")

    await spectrum.send(f"已收到文件：{file_name}，请稍候...")

    safe_name = safe_filename(file_name)
    file_path = CACHE_DIR / safe_name

    try:
        await download_file(file_url, file_path)

        if file_name.lower().endswith(".mr"):
            mr_obj = await asyncio.to_thread(mr_file, file_path)
            data = await asyncio.to_thread(convert_mr_to_osr, mr_obj)
        else:
            data = await asyncio.to_thread(osr_file, file_path)
            await asyncio.to_thread(data.process)
            
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
        await platform.send_image(bot, spectrum, Path(output_path).read_bytes())
        
    except Exception as e:
        logger.exception("处理回放时出错")
        await spectrum.send(f"处理过程中发生错误：{type(e).__name__}: {e}")

    finally:
        if file_path and file_path.exists():
            asyncio.create_task(cleanup_temp_file(file_path))
        if output_path and Path(output_path).exists():
            asyncio.create_task(cleanup_temp_file(Path(output_path)))
    return