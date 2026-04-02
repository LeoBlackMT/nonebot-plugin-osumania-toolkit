import os
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.exception import FinishedException
from nonebot_plugin_localstore import get_plugin_cache_dir

from ..algorithm.mapview import analyze_mapview_chart, analyze_mapview_zip, render_analysis_card
from ..algorithm.patterns import PatternNotManiaError, PatternParseError
from ..algorithm.rework import ParseError, NotManiaError
from ..algorithm.utils import parse_cmd, send_forward_text_messages
from ..file.file import download_file, download_file_by_id, get_file_url, safe_filename


CACHE_DIR = get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


mapview = on_command("mapview", aliases={"rework"}, block=True)


@mapview.handle()
async def handle_mapview(bot: Bot, event: MessageEvent):
    cmd_text = event.get_plaintext().strip()
    speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg = parse_cmd(cmd_text)

    if err_msg:
        await mapview.finish("错误:\n" + "\n".join(err_msg) + "\n请检查命令格式并重试。")

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
                await mapview.finish("回复的消息中没有找到文件。")

            file_info = await get_file_url(bot, file_seg)
            if not file_info:
                await mapview.finish("无法获取文件信息。请确保机器人有权限访问该文件，或者文件链接有效。")

            file_name, file_url = file_info
            file_name = safe_filename(os.path.basename(file_name))
            if not file_name.lower().endswith((".osu", ".mc", ".osz", ".mcz")):
                await mapview.finish("请回复 .osu/.mc/.osz/.mcz 格式的谱面文件。")

            tmp_file = CACHE_DIR / file_name
            if not await download_file(file_url, tmp_file):
                await mapview.finish(
                    "下载失败：文件可能过大或链接无效，请检查并重试。\n"
                    "建议：可以删除图包内的媒体文件（音频/背景视频/图片）后再重新打包上传。"
                )

            if file_name.lower().endswith((".osz", ".mcz")):
                await mapview.send(f"已收到图包：{file_name}，正在生成图片，请稍候...")
                rows, errors = await analyze_mapview_zip(
                    tmp_file, speed_rate, od_flag, cvt_flag, mod_display, CACHE_DIR
                )

                nodes: list[Message | str] = []
                for row in rows:
                    try:
                        image_bytes = await render_analysis_card(TEMPLATE_DIR, row["template"])
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
                await mapview.finish()

            else:
                chart_file = tmp_file
                await mapview.send(f"已收到文件：{file_name}，正在生成图片...")
                row = await analyze_mapview_chart(
                    chart_file,
                    file_name,
                    speed_rate,
                    od_flag,
                    cvt_flag,
                    mod_display,
                    CACHE_DIR,
                )
                image_bytes = await render_analysis_card(TEMPLATE_DIR, row["template"])
                await mapview.finish(MessageSegment.image(image_bytes))

        elif bid is not None:
            tmp_file, file_name = await download_file_by_id(CACHE_DIR, bid)
            chart_file = tmp_file

            row = await analyze_mapview_chart(
                chart_file,
                file_name,
                speed_rate,
                od_flag,
                cvt_flag,
                mod_display,
                CACHE_DIR,
            )
            image_bytes = await render_analysis_card(TEMPLATE_DIR, row["template"])
            await mapview.finish(MessageSegment.image(image_bytes))
        else:
            await mapview.finish("请回复包含 .osu/.mc/.osz/.mcz 文件的消息，或使用 bid/mania 谱面网址指定谱面。")

    except FinishedException:
        raise
    except (ParseError, PatternParseError):
        await mapview.finish("谱面解析失败，可能是文件损坏或格式不兼容。")
    except (NotManiaError, PatternNotManiaError):
        await mapview.finish("该谱面不是 mania 模式，无法分析。")
    except Exception as e:
        error_text = str(e)
        if "超过" in error_text or "过大" in error_text:
            await mapview.finish(
                "分析失败：文件过大。\n"
                "建议：可以删除图包内的媒体文件（音频/背景视频/图片）后再重新打包上传。"
            )
        elif "max() iterable argument is empty" in error_text:
            await mapview.finish(f"错误: 未找到谱面 b{bid}，请检查bid是否正确")
        else:
            await mapview.finish(f"分析失败：{e}")
    finally:
        if tmp_file and tmp_file.exists():
            tmp_file.unlink()
        if chart_file and chart_file != tmp_file and chart_file.exists():
            chart_file.unlink()
