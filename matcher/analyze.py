import os
import asyncio
from pathlib import Path

from nonebot import on_command, require
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.log import logger

from ..file.osr_file_parser import osr_file
from ..file.osu_file_parser import osu_file
from ..file.draw import plot_pressingtime, plot_delta, plot_spectrum
from ..file.file import safe_filename, download_file, cleanup_temp_file
from ..algorithm import cheat_analyze


require("nonebot_plugin_localstore")
from nonebot_plugin_localstore import get_plugin_cache_dir

CACHE_DIR = get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

analyze = on_command("analyze", aliases={"分析"}, block=True)

@analyze.handle()
# todo 复制的pressingtime 还没改
async def handle_analyze(event: MessageEvent):
    if not event.reply:
        await analyze.finish("请回复一条包含 .osr 文件的消息。")

    reply = event.reply
    file_seg = None
    for seg in reply.message:
        if seg.type == "file":
            file_seg = seg
            break

    if not file_seg:
        await analyze.finish("回复的消息中没有找到文件。")

    file_name = file_seg.data.get("file", "")
    file_url = file_seg.data.get("url", "")
    
    if not file_name:
        await analyze.finish("无法获取文件名。")
    if not file_url:
        await analyze.finish("无法获取文件下载链接。")
    file_name = os.path.basename(file_name)
    if not file_name.lower().endswith(".osr"):
        await analyze.finish("请回复 .osr 格式的回放文件。")
    if not file_url:
        await analyze.finish("无法获取文件下载链接。")
    
    await analyze.send(f"已收到文件：{file_name}，请稍候...")

    safe_name = safe_filename(file_name)
    file_path = CACHE_DIR / safe_name

    try:
        success = await download_file(file_url, file_path)
        if not success:
            await analyze.send("文件下载失败，请稍后重试。")
            return

        data = osr_file(file_path)
        data.process()
        match data.status:
            case "NotMania":
                await analyze.send("该回放不是 Mania 模式。")
                return
            case "tooFewKeys":
                await analyze.send("有效轨道数量过少，无法分析。")
                return
            case "init":
                await analyze.send("回放尚未process。")
                return
            case _:
                pass
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, plot_pressingtime, data, str(CACHE_DIR)
        )
        
        output_path = result
        await analyze.send(MessageSegment.image(f"file://{output_path}"))

        # cheat_analysis = result["cheat_analysis"]
        # sim_precent = cheat_analysis["percent"]
        # if cheat_analysis["cheat"] or cheat_analysis["sus"]:
        #     reason = cheat_analysis["reason"]
        #     if cheat_analysis["cheat"]:
        #         await pressingtime.send(MessageSegment.image(f"file://{output_path}"))
        #         await pressingtime.send(f"<!>此成绩检测到作弊：{reason}\n仅供参考，请结合其他信息进行判断。")
        #     else:
        #         await pressingtime.send(MessageSegment.image(f"file://{output_path}"))
        #         await pressingtime.send(f"此成绩检测到可疑：{reason}\n这可能是因为玩家设备问题，或者帧数/采样率过低。请结合其他信息进行判断。")
        # else:
        #     await pressingtime.send(MessageSegment.image(f"file://{output_path}"))
        #     await pressingtime.send(f"轨道相似度：{sim_precent:.1f}%")
        
    except Exception as e:
        logger.exception("处理回放时出错")
        await analyze.send(f"处理过程中发生错误：{type(e).__name__}: {e}")

    finally:
        if file_path and file_path.exists():
            asyncio.create_task(cleanup_temp_file(file_path))
        if output_path and Path(output_path).exists():
            asyncio.create_task(cleanup_temp_file(Path(output_path)))
    return