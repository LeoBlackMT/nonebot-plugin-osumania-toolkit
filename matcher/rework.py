import os

import aiohttp
from nonebot import on_command, require
from nonebot.adapters.onebot.v11 import MessageEvent

from ..file.file import download_file_by_id
from ..algorithm.rework import get_result, est_diff, get_rework_sr, parse_cmd, parse_osu_filename

from nonebot_plugin_localstore import get_plugin_cache_dir

CACHE_DIR = get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

rework = on_command("rework", block=True)

@rework.handle()
async def handle_rework(event: MessageEvent):

    cmd_text = event.get_plaintext().strip()
    speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg = parse_cmd(cmd_text)
    
    if err_msg:
        await rework.send("错误:\n" + "\n".join(err_msg) + "\n请检查命令格式并重试。")
        return

    # 如果有提供文件，忽略bid参数，直接处理文件
    if event.reply:
        reply = event.reply

        file_seg = None
        for seg in reply.message:
            if seg.type == "file":
                file_seg = seg
                break
        if not file_seg:
            await rework.finish("回复的消息中没有找到 .osu 文件。")

        # 获取文件信息
        file_ident = file_seg.data.get("file", "")
        file_url = file_seg.data.get("url", "")
        if not file_ident:
            await rework.finish("文件信息不完整。")
        file_name = os.path.basename(file_ident)
        if not file_name.lower().endswith(".osu"):
            await rework.finish("请回复 .osu 格式的谱面文件。")
        if not file_url:
            await rework.finish("无法获取文件下载链接。")

        await rework.send(f"已收到文件：{file_name}，请稍候...")

        tmp_file = CACHE_DIR / file_name

        try:
            # 下载文件
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    if resp.status == 200:
                        with open(tmp_file, 'wb') as f:
                            f.write(await resp.read())
                    else:
                        await rework.finish(f"文件下载失败，状态码：{resp.status}")
        except Exception as e:
            await rework.finish(f"下载异常：{e}")

        try:
            # 计算星数
            sr, LN_ratio = await get_rework_sr(str(tmp_file), speed_rate, od_flag, cvt_flag)

            await rework.send(get_result(parse_osu_filename(file_name), mod_display, sr, speed_rate, od_flag, LN_ratio, est_diff(sr, LN_ratio)), reply_to=True)
            
        except Exception as e:
            if str(e) == "ParseError":
                await rework.send("谱面解析失败，可能是文件损坏或格式不兼容。")
            elif str(e) == "NotMania":
                await rework.send("该谱面不是 mania 模式，无法计算。")
            else:
                await rework.send(f"计算失败：{e}")
        finally:
            if tmp_file and tmp_file.exists():
                tmp_file.unlink()
        return
    
    elif bid is None:
        await rework.finish("请回复包含 .osu 文件的消息，或使用 bid 指定谱面。")
    
    else:
        try:
            tmp_file, file_name = await download_file_by_id(CACHE_DIR,bid)
            sr, LN_ratio = await get_rework_sr(str(tmp_file), speed_rate, od_flag, cvt_flag)

            await rework.send(get_result(parse_osu_filename(file_name), mod_display, sr, speed_rate, od_flag, LN_ratio, est_diff(sr, LN_ratio)), reply_to=True)
        except Exception as e:
            await rework.send(f"{e}")
        finally:
            if tmp_file and tmp_file.exists():
                tmp_file.unlink()
        