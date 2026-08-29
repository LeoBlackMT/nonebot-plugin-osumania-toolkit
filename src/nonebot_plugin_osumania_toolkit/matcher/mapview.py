import asyncio
import os
from pathlib import Path

from nonebot import get_plugin_config, on_command
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import Message as OBMessage, MessageSegment
from nonebot.exception import FinishedException

from ..algorithm.mapview import (
    analyze_mapview_chart,
    analyze_mapview_zip,
    format_mapview_result_text,
    format_parse_error_for_user,
)
from ..algorithm.pattern import PatternNotManiaError, PatternParseError
from ..algorithm.estimator.exceptions import ParseError, NotManiaError
from ..algorithm.utils import parse_cmd, send_forward_text_messages
from ..render.mapview import render_analysis_card
from ..api.download import download_file
from ..api.osu import download_file_by_id
from ..file.path import safe_filename
from .. import platform
from ..config import Config
from ..file.cache import CACHE_DIR
from ..render.batch import merge_images_to_grid

config = get_plugin_config(Config)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "render" / "templates"


mapview = on_command("mapview", aliases={"rework"}, block=True)


@mapview.handle()
async def handle_mapview(bot: Bot, event: Event):
    cmd_text = event.get_plaintext().strip()
    speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg = parse_cmd(cmd_text)

    if err_msg:
        await mapview.finish("错误:\n" + "\n".join(err_msg) + "\n请检查命令格式并重试。")

    tmp_file: Path | None = None
    chart_file: Path | None = None

    try:
        file_info = await platform.extract_replied_file(bot, event)
        if file_info:
            file_name, file_url = file_info
            file_name = safe_filename(os.path.basename(file_name))
            if not file_name.lower().endswith((".osu", ".mc", ".osz", ".mcz")):
                await mapview.finish("请回复 .osu/.mc/.osz/.mcz 格式的谱面文件。")

            tmp_file = CACHE_DIR / file_name
            await download_file(file_url, tmp_file)

            if file_name.lower().endswith((".osz", ".mcz")):
                if platform.is_qq(bot):
                    await mapview.send(
                        f"已收到图包：{file_name}，正在分析，请稍候..."
                    )
                    rows, errors, total = await analyze_mapview_zip(
                        tmp_file,
                        speed_rate,
                        od_flag,
                        cvt_flag,
                        mod_display,
                        CACHE_DIR,
                        max_charts=config.qq_max_zip_charts,
                    )
                    if not rows and not errors:
                        await mapview.finish("图包中没有可分析的谱面文件。")
                    if not rows:
                        await mapview.finish("错误:\n" + "\n".join(errors))
                    images: list[bytes] = []
                    for row in rows:
                        try:
                            image_bytes = await render_analysis_card(
                                TEMPLATE_DIR, row["template"]
                            )
                        except Exception:
                            image_bytes = None
                        if image_bytes is not None:
                            images.append(image_bytes)
                        else:
                            errors.append(
                                f"{row['file_name']} 渲染失败，已跳过"
                            )
                    if images:
                        merged = merge_images_to_grid(images)
                        await platform.send_image(bot, mapview, merged)
                    if errors:
                        await mapview.send(
                            "部分谱面分析失败:\n" + "\n".join(errors)
                        )
                    await mapview.finish()
                else:
                    await mapview.send(
                        f"已收到图包：{file_name}，正在分析，请稍候..."
                    )
                    rows, errors, total = await analyze_mapview_zip(
                        tmp_file,
                        speed_rate,
                        od_flag,
                        cvt_flag,
                        mod_display,
                        CACHE_DIR,
                    )
                    if not rows and not errors:
                        await mapview.finish("图包中没有可分析的谱面文件。")
                    if not rows:
                        await mapview.finish("错误:\n" + "\n".join(errors))

                    avalible = len(rows)
                    if total >= 3:
                        await mapview.send(
                            f"分析完成，有效 {avalible} / {total}，正在生成图片..."
                        )

                    nodes: list[OBMessage | str] = []
                    batch_size = 5
                    for idx, row in enumerate(rows):
                        try:
                            image_bytes = await render_analysis_card(
                                TEMPLATE_DIR, row["template"]
                            )
                            nodes.append(
                                OBMessage(f"{row['file_name']}\n")
                                + MessageSegment.image(image_bytes)
                            )
                        except Exception:
                            nodes.append(
                                f"{row['file_name']}:\n"
                                f"{format_mapview_result_text(row)}"
                            )

                        if (
                            len(nodes) >= batch_size
                            or idx == avalible - 1
                        ):
                            await send_forward_text_messages(
                                bot, event, nodes
                            )
                            nodes = []

                        await asyncio.sleep(0.5)  # 避免发送过快

                    if errors:
                        await send_forward_text_messages(
                            bot,
                            event,
                            ["部分谱面分析失败:\n" + "\n".join(errors)],
                        )

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
                try:
                    image_bytes = await render_analysis_card(
                        TEMPLATE_DIR, row["template"]
                    )
                    await platform.send_image(bot, mapview, image_bytes)
                    await mapview.finish()
                except FinishedException:
                    raise
                except Exception:
                    await mapview.finish(format_mapview_result_text(row))

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
            try:
                image_bytes = await render_analysis_card(
                    TEMPLATE_DIR, row["template"]
                )
                await platform.send_image(bot, mapview, image_bytes)
                await mapview.finish()
            except FinishedException:
                raise
            except Exception:
                await mapview.finish(format_mapview_result_text(row))
        else:
            await mapview.finish("请回复包含 .osu/.mc/.osz/.mcz 文件的消息，或使用 bid/mania 谱面网址指定谱面。")

    except FinishedException:
        raise
    except (ParseError, PatternParseError) as e:
        await mapview.finish(format_parse_error_for_user(e))
    except (NotManiaError, PatternNotManiaError):
        await mapview.finish("该谱面不是 mania 模式，无法分析。")
    except Exception as e:
        error_text = str(e)
        if "超过" in error_text or "过大" in error_text:
            await mapview.finish(
                f"分析失败：{e}\n"
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
