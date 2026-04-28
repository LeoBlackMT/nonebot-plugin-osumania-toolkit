import os
import shutil
import time
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.exception import FinishedException

from ..algorithm.conversion import convert_mc_to_osu
from ..algorithm.utils import extract_zip_file
from ..algorithm.pattern import (
    PatternNotManiaError,
    PatternParseError,
    analyze_pattern_file,
    format_pattern_result_text,
)
from ..algorithm.pattern.card import build_pattern_card_data
from ..render.pattern import render_pattern_card
from ..algorithm.utils import parse_cmd, is_mc_file, resolve_meta_data, send_forward_text_messages
from ..api.download import download_file, get_file_url
from ..api.osu import download_file_by_id
from ..file.path import safe_filename

from ..file.cache import CACHE_DIR
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "render" / "templates"


pattern = on_command("pattern", aliases={"键型"}, block=True)


@dataclass
class PatternOutputRow:
    file_name: str
    text: str
    card_data: dict[str, Any] | None


def _is_detail_mode(cmd_text: str) -> bool:
    tokens = {part.strip().lower() for part in cmd_text.split()}
    return "-d" in tokens or "-detail" in tokens or "--detail" in tokens


def _fallback_text_rows(rows: list[PatternOutputRow]) -> list[str]:
    if rows:
        return [row.text for row in rows]
    return ["图包中没有可分析的谱面文件。"]


async def _send_pattern_rows(
    bot: Bot,
    event: MessageEvent,
    rows: list[PatternOutputRow],
    detail_mode: bool,
) -> None:
    fallback_rows = _fallback_text_rows(rows)

    if detail_mode or not rows:
        await send_forward_text_messages(bot, event, fallback_rows)
        return

    try:
        if any(row.card_data is None for row in rows):
            raise RuntimeError("fallback to forwarded text")

        if len(rows) == 1:
            image_bytes = await render_pattern_card(rows[0].card_data or {}, TEMPLATE_DIR)
            await pattern.send(MessageSegment.image(image_bytes))
            return

        image_nodes: list[Message] = []
        for row in rows:
            image_bytes = await render_pattern_card(row.card_data or {}, TEMPLATE_DIR)
            image_nodes.append(Message(f"{row.file_name}\n") + MessageSegment.image(image_bytes))

        await send_forward_text_messages(bot, event, image_nodes)
    except Exception:
        await send_forward_text_messages(bot, event, fallback_rows)


async def _analyze_single_chart(chart_file: Path, file_name: str, rate: float) -> PatternOutputRow:
    target_file = chart_file
    target_name = file_name
    if is_mc_file(str(target_file)):
        osu_file_path = await asyncio.to_thread(
            convert_mc_to_osu,
            str(target_file),
            str(CACHE_DIR),
        )
        target_file = Path(osu_file_path)
        target_name = os.path.basename(osu_file_path)

    report = await analyze_pattern_file(str(target_file), rate=rate)
    meta_data = resolve_meta_data(target_file, target_name)
    return PatternOutputRow(
        file_name=target_name,
        text=format_pattern_result_text(meta_data, report, rate=rate),
        card_data=build_pattern_card_data(meta_data, report, rate=rate),
    )


async def _analyze_zip_file(zip_file: Path, rate: float) -> list[PatternOutputRow]:
    temp_dir = CACHE_DIR / f"pattern_batch_{int(time.time())}_{os.getpid()}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        try:
            chart_files = await asyncio.to_thread(extract_zip_file, zip_file, temp_dir)
        except Exception as e:
            return [
                PatternOutputRow(
                    file_name=zip_file.name,
                    text=f"图包分析失败 - {e}",
                    card_data=None,
                )
            ]

        results: list[PatternOutputRow] = []

        if not chart_files:
            return [
                PatternOutputRow(
                    file_name=zip_file.name,
                    text="图包中没有可分析的谱面文件。",
                    card_data=None,
                )
            ]

        for chart_file in chart_files:
            try:
                result = await _analyze_single_chart(chart_file, chart_file.name, rate)
                results.append(result)
            except PatternNotManiaError:
                results.append(
                    PatternOutputRow(
                        file_name=chart_file.name,
                        text=f"{chart_file.name}: 不是 mania 模式，无法分析。",
                        card_data=None,
                    )
                )
            except PatternParseError as e:
                results.append(
                    PatternOutputRow(
                        file_name=chart_file.name,
                        text=f"{chart_file.name}: 谱面解析失败 - {e}",
                        card_data=None,
                    )
                )
            except Exception as e:
                results.append(
                    PatternOutputRow(
                        file_name=chart_file.name,
                        text=f"{chart_file.name}: 分析失败 - {e}",
                        card_data=None,
                    )
                )
        return results
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


@pattern.handle()
async def handle_pattern(bot: Bot, event: MessageEvent):
    cmd_text = event.get_plaintext().strip()
    detail_mode = _is_detail_mode(cmd_text)
    _, _, _, bid, _, _ = parse_cmd(cmd_text)

    tmp_file: Path | None = None
    chart_file: Path | None = None
    result_rows: list[PatternOutputRow] = []

    try:
        if event.reply:
            reply = event.reply
            file_seg = None
            for seg in reply.message:
                if seg.type == "file":
                    file_seg = seg
                    break

            if not file_seg:
                await pattern.finish("回复的消息中没有找到文件。")

            file_info = await get_file_url(bot, file_seg)
            if not file_info:
                await pattern.finish("无法获取文件信息。请确保机器人有权限访问该文件，或者文件链接有效。")

            file_name, file_url = file_info
            file_name = safe_filename(os.path.basename(file_name))
            if not file_name.lower().endswith((".osu", ".mc", ".osz", ".mcz")):
                await pattern.finish("请回复 .osu/.mc/.osz/.mcz 格式的谱面文件。")

            tmp_file = CACHE_DIR / file_name
            if not await download_file(file_url, tmp_file):
                await pattern.finish(
                    "下载失败：文件可能过大或链接无效，请检查并重试。\n"
                    "建议：可以删除图包内的媒体文件（音频/背景视频/图片）后再重新打包上传。"
                )

            if file_name.lower().endswith((".osz", ".mcz")):
                await pattern.send(f"已收到图包：{file_name}，正在分析，请稍候...")
                result_rows = await _analyze_zip_file(tmp_file, rate=1.0)
            else:
                chart_file = tmp_file
                await pattern.send(f"已收到文件：{file_name}，请稍候...")
                result_rows = [await _analyze_single_chart(chart_file, file_name, rate=1.0)]

            await _send_pattern_rows(bot, event, result_rows, detail_mode)
            await pattern.finish()

        elif bid is not None:
            tmp_file, file_name = await download_file_by_id(CACHE_DIR, bid)
            chart_file = tmp_file

            result_rows = [await _analyze_single_chart(chart_file, file_name, rate=1.0)]
            await _send_pattern_rows(bot, event, result_rows, detail_mode)
            await pattern.finish()
        else:
            await pattern.finish("请回复包含 .osu/.mc/.osz/.mcz 文件的消息，或使用 bid/mania 谱面网址指定谱面。")

    except FinishedException:
        raise
    except PatternNotManiaError:
        await pattern.finish("该谱面不是 mania 模式，无法分析键型。")
    except PatternParseError as e:
        await pattern.finish(f"谱面解析失败：{e}")
    except Exception as e:
        error_text = str(e)
        if "超过" in error_text or "过大" in error_text:
            await pattern.finish(
                "键型分析失败：文件过大。\n"
                "建议：可以删除图包内的媒体文件（音频/背景视频/图片）后再重新打包上传。"
            )
        else:
            await pattern.finish(f"键型分析失败：{e}")
    finally:
        if tmp_file and tmp_file.exists():
            tmp_file.unlink()
        if chart_file and chart_file != tmp_file and chart_file.exists():
            chart_file.unlink()
