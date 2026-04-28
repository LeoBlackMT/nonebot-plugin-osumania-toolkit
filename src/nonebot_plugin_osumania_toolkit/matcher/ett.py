import os
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.exception import FinishedException

from ..file.cache import CACHE_DIR
from ..algorithm.ett import (
    ETTNotManiaError,
    ETTParseError,
    ETTUnsupportedKeyError,
    OfficialRunnerError,
    analyze_ett_chart,
    analyze_ett_zip,
)
from ..render.ett import render_ett_card
from ..algorithm.utils import parse_cmd, send_forward_text_messages
from ..api.download import download_file, get_file_url
from ..api.osu import download_file_by_id
from ..file.path import safe_filename
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "render" / "templates"


ett = on_command("ett", aliases={"msd"}, block=True)


@ett.handle()
async def handle_ett(bot: Bot, event: MessageEvent):
    cmd_text = event.get_plaintext().strip()
    speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg = parse_cmd(cmd_text)

    if mod_display != "NM" or cvt_flag or od_flag is not None:
        err_msg.append("/ett 不支持 mods、OD 覆写和 IN/HO，仅支持 rate（如 x1.4）")

    if err_msg:
        await ett.finish("错误:\n" + "\n".join(err_msg) + "\n请检查命令格式并重试。")

    tmp_file: Path | None = None
    chart_file: Path | None = None

    try:
        if event.reply:
            file_seg = None
            for seg in event.reply.message:
                if seg.type == "file":
                    file_seg = seg
                    break

            if not file_seg:
                await ett.finish("回复的消息中没有找到文件。")

            file_info = await get_file_url(bot, file_seg)
            if not file_info:
                await ett.finish("无法获取文件信息。请确保机器人有权限访问该文件，或者文件链接有效。")

            file_name, file_url = file_info
            file_name = safe_filename(os.path.basename(file_name))
            if not file_name.lower().endswith((".osu", ".mc", ".osz", ".mcz")):
                await ett.finish("请回复 .osu/.mc/.osz/.mcz 格式的谱面文件。")

            tmp_file = CACHE_DIR / file_name
            if not await download_file(file_url, tmp_file):
                await ett.finish(
                    "下载失败：文件可能过大或链接无效，请检查并重试。\n"
                    "建议：可以删除图包内的媒体文件（音频/背景视频/图片）后再重新打包上传。"
                )

            if file_name.lower().endswith((".osz", ".mcz")):
                await ett.send(f"已收到图包：{file_name}，正在生成图片，请稍候...")
                rows, errors = await analyze_ett_zip(
                    tmp_file, speed_rate, cvt_flag, mod_display, CACHE_DIR
                )

                nodes: list[Message | str] = []
                for row in rows:
                    try:
                        image_bytes = await render_ett_card(TEMPLATE_DIR, row["template"])
                        nodes.append(
                            Message(f"{row['file_name']}\n") + MessageSegment.image(image_bytes)
                        )
                    except Exception as e:
                        errors.append(f"{row['file_name']}: 图片渲染失败 - {e}")

                if errors:
                    for err in errors:
                        nodes.append(err)

                if not nodes:
                    nodes = ["图包中没有可分析的谱面文件。"]

                await send_forward_text_messages(bot, event, nodes)
                await ett.finish()

            else:
                chart_file = tmp_file
                await ett.send(f"已收到文件：{file_name}，正在生成分析图片...")
                row = await analyze_ett_chart(
                    chart_file,
                    file_name,
                    speed_rate,
                    cvt_flag,
                    mod_display,
                    CACHE_DIR,
                )
                image_bytes = await render_ett_card(TEMPLATE_DIR, row["template"])
                await ett.finish(MessageSegment.image(image_bytes))

        elif bid is not None:
            tmp_file, file_name = await download_file_by_id(CACHE_DIR, bid)
            chart_file = tmp_file

            row = await analyze_ett_chart(
                chart_file,
                file_name,
                speed_rate,
                cvt_flag,
                mod_display,
                CACHE_DIR,
            )
            image_bytes = await render_ett_card(TEMPLATE_DIR, row["template"])
            await ett.finish(MessageSegment.image(image_bytes))
        else:
            await ett.finish("请回复包含 .osu/.mc/.osz/.mcz 文件的消息，或使用 bid/mania 谱面网址指定谱面。")

    except FinishedException:
        raise
    except ETTParseError:
        await ett.finish("谱面解析失败，可能是文件损坏或格式不兼容。")
    except ETTNotManiaError:
        await ett.finish("该谱面不是 mania 模式，无法分析。")
    except ETTUnsupportedKeyError as e:
        await ett.finish(f"分析失败：{e}")
    except OfficialRunnerError as e:
        await ett.finish(f"计算失败：{e}")
    except Exception as e:
        error_text = str(e)
        if "超过" in error_text or "过大" in error_text:
            await ett.finish(
                "分析失败：文件过大。\n"
                "建议：可以删除图包内的媒体文件（音频/背景视频/图片）后再重新打包上传。"
            )
        else:
            await ett.finish(f"分析失败：{e}")
    finally:
        if tmp_file and tmp_file.exists():
            tmp_file.unlink()
        if chart_file and chart_file != tmp_file and chart_file.exists():
            chart_file.unlink()
