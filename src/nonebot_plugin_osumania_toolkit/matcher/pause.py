from __future__ import annotations

import os
import asyncio

from nonebot import on_command
from nonebot.adapters import Bot, Event
from nonebot.exception import FinishedException

from .. import platform
from ..file.cache import CACHE_DIR
from ..file.path import safe_filename
from ..api.download import download_file
from ..file.cleanup import cleanup_temp_file
from ..parser.osr_file_parser import osr_file
from ..algorithm.pause import format_pause_line

pause = on_command("pause", aliases={"pc", "暂停"}, block=True)


@pause.handle()
async def handle_pause(bot: Bot, event: Event):
    file_info = await platform.extract_replied_file(bot, event)
    if not file_info:
        await pause.finish("请回复一条包含 .osr 回放文件的消息。")
    file_name, file_url = file_info
    file_name = safe_filename(os.path.basename(file_name))
    if not file_name.lower().endswith((".osr", ".mr")):
        await pause.finish("请回复 .osr 或 .mr 格式的回放文件。")
    if file_name.lower().endswith(".mr"):
        await pause.finish("Malody .mr 回放不包含暂停数据。")

    path = CACHE_DIR / file_name
    try:
        await download_file(file_url, path)
        osr_obj = await asyncio.to_thread(osr_file, path)
        if osr_obj.status == "NotMania":
            await pause.finish("该回放不是 Mania 模式。")
        line = format_pause_line(osr_obj)
        if line is None:
            await pause.finish(
                "该回放不含暂停数据（osu!stable 不记录；Lazer 版本过旧时也只有次数）。"
            )
        await pause.finish(line)
    except FinishedException:
        raise
    except Exception as e:
        await pause.finish(f"暂停读取失败：{e}")
    finally:
        if path.exists():
            asyncio.create_task(cleanup_temp_file(path))
