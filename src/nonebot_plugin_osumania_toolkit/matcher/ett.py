import asyncio
import os
from pathlib import Path

from nonebot import get_plugin_config, on_command
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import Message as OBMessage, MessageSegment
from nonebot.exception import FinishedException

from ..file.cache import CACHE_DIR
from ..algorithm.ett import (
    ETTNotManiaError,
    ETTParseError,
    ETTUnsupportedKeyError,
    OfficialRunnerError,
    analyze_ett_chart,
    analyze_ett_zip,
    format_ett_result_text,
)
from ..render.ett import render_ett_card
from ..algorithm.utils import parse_cmd, send_forward_text_messages
from ..api.download import download_file
from ..api.osu import download_file_by_id
from ..file.path import safe_filename
from .. import platform
from ..config import Config
from ..render.batch import merge_images_to_grid

config = get_plugin_config(Config)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "render" / "templates"


ett = on_command("ett", aliases={"msd"}, block=True)


@ett.handle()
async def handle_ett(bot: Bot, event: Event):
    cmd_text = event.get_plaintext().strip()
    speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg = parse_cmd(cmd_text)

    if mod_display != "NM" or cvt_flag or od_flag is not None:
        err_msg.append("/ett 不支持 mods、OD 覆写和 IN/HO，仅支持 rate（如 x1.4）")

    if err_msg:
        await ett.finish("错误:\n" + "\n".join(err_msg) + "\n请检查命令格式并重试。")

    tmp_file: Path | None = None
    chart_file: Path | None = None

    try:
        file_info = await platform.extract_replied_file(bot, event)
        if not file_info:
            await ett.finish("请回复一条包含文件的消息。")

        if file_info:
            file_name, file_url = file_info
            file_name = safe_filename(os.path.basename(file_name))
            if not file_name.lower().endswith((".osu", ".mc", ".osz", ".mcz")):
                await ett.finish("请回复 .osu/.mc/.osz/.mcz 格式的谱面文件。")

            tmp_file = CACHE_DIR / file_name
            await download_file(file_url, tmp_file)

            if file_name.lower().endswith((".osz", ".mcz")):
                if platform.is_qq(bot):
                    await ett.send(
                        f"已收到图包：{file_name}，正在分析，请稍候..."
                    )
                    rows, errors, total = await analyze_ett_zip(
                        tmp_file,
                        speed_rate,
                        cvt_flag,
                        mod_display,
                        CACHE_DIR,
                        max_charts=config.qq_max_zip_charts,
                    )
                    if not rows and not errors:
                        await ett.finish("图包中没有可分析的谱面文件。")
                    if not rows:
                        await ett.finish("错误:\n" + "\n".join(errors))
                    images: list[bytes] = []
                    for row in rows:
                        try:
                            image_bytes = await render_ett_card(
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
                        await platform.send_image(bot, ett, merged)
                    if errors:
                        await ett.send(
                            "部分谱面分析失败:\n" + "\n".join(errors)
                        )
                    await ett.finish()
                else:
                    await ett.send(
                        f"已收到图包：{file_name}，正在分析，请稍候..."
                    )
                    rows, errors, total = await analyze_ett_zip(
                        tmp_file,
                        speed_rate,
                        cvt_flag,
                        mod_display,
                        CACHE_DIR,
                    )
                    if not rows and not errors:
                        await ett.finish("图包中没有可分析的谱面文件。")
                    if not rows:
                        await ett.finish("错误:\n" + "\n".join(errors))

                    if total >= 3:
                        await ett.send(
                            f"分析完成，有效 {len(rows)} / {total}，正在生成图片..."
                        )

                    nodes: list[OBMessage | str] = []
                    batch_size = 5
                    for idx, row in enumerate(rows):
                        try:
                            image_bytes = await render_ett_card(
                                TEMPLATE_DIR, row["template"]
                            )
                            nodes.append(
                                OBMessage(f"{row['file_name']}\n")
                                + MessageSegment.image(image_bytes)
                            )
                        except Exception:
                            nodes.append(
                                f"{row['file_name']}:\n"
                                f"{format_ett_result_text(row)}"
                            )

                        if (
                            len(nodes) >= batch_size
                            or idx == len(rows) - 1
                        ):
                            await send_forward_text_messages(
                                bot, event, nodes
                            )
                            nodes = []
                            await asyncio.sleep(0.5)

                    if errors:
                        await send_forward_text_messages(
                            bot,
                            event,
                            ["部分谱面分析失败:\n" + "\n".join(errors)],
                        )

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
                try:
                    image_bytes = await render_ett_card(
                        TEMPLATE_DIR, row["template"]
                    )
                except Exception:
                    await ett.finish(format_ett_result_text(row))
                await platform.send_image(bot, ett, image_bytes)
                await ett.finish()

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
            try:
                image_bytes = await render_ett_card(
                    TEMPLATE_DIR, row["template"]
                )
                await platform.send_image(bot, ett, image_bytes)
                await ett.finish()
            except FinishedException:
                raise
            except Exception:
                await ett.finish(format_ett_result_text(row))
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
                f"分析失败：{e}\n"
                "建议：可以删除图包内的媒体文件（音频/背景视频/图片）后再重新打包上传。"
            )
        else:
            await ett.finish(f"分析失败：{e}")
    finally:
        if tmp_file and tmp_file.exists():
            tmp_file.unlink()
        if chart_file and chart_file != tmp_file and chart_file.exists():
            chart_file.unlink()
