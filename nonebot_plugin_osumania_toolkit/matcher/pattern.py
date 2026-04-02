import os
import shutil
import time
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.exception import FinishedException
from nonebot_plugin_localstore import get_plugin_cache_dir

from ..algorithm.convert import convert_mc_to_osu
from ..algorithm.utils import extract_zip_file
from ..algorithm.patterns import (
    PatternNotManiaError,
    PatternParseError,
    analyze_pattern_file,
    format_pattern_result_text,
)
from ..algorithm.utils import parse_cmd, is_mc_file, resolve_meta_data, send_forward_text_messages
from ..file.file import download_file, download_file_by_id, get_file_url, safe_filename


CACHE_DIR = get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)


pattern = on_command("pattern", aliases={"键型"}, block=True)


async def _analyze_single_chart(chart_file: Path, file_name: str, rate: float) -> str:
    target_file = chart_file
    target_name = file_name
    if is_mc_file(str(target_file)):
        osu_file_path = convert_mc_to_osu(str(target_file), str(CACHE_DIR))
        target_file = Path(osu_file_path)
        target_name = os.path.basename(osu_file_path)

    report = await analyze_pattern_file(str(target_file), rate=rate)
    meta_data = resolve_meta_data(target_file, target_name)
    return format_pattern_result_text(meta_data, report, rate=rate)


async def _analyze_zip_file(zip_file: Path, rate: float) -> list[str]:
    temp_dir = CACHE_DIR / f"pattern_batch_{int(time.time())}_{os.getpid()}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        try:
            chart_files = extract_zip_file(zip_file, temp_dir)
        except Exception as e:
            return [f"图包分析失败 - {e}"]

        results: list[str] = []

        if not chart_files:
            return ["图包中没有可分析的谱面文件。"]

        for chart_file in chart_files:
            try:
                result = await _analyze_single_chart(chart_file, chart_file.name, rate)
                results.append(result)
            except PatternNotManiaError:
                results.append(f"{chart_file.name}: 不是 mania 模式，无法分析。")
            except PatternParseError as e:
                results.append(f"{chart_file.name}: 谱面解析失败 - {e}")
            except Exception as e:
                results.append(f"{chart_file.name}: 分析失败 - {e}")
        return results
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


@pattern.handle()
async def handle_pattern(bot: Bot, event: MessageEvent):
    cmd_text = event.get_plaintext().strip()
    _, _, _, bid, _, _ = parse_cmd(cmd_text)

    tmp_file: Path | None = None
    chart_file: Path | None = None
    result_texts: list[str] = []

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
                result_texts = await _analyze_zip_file(tmp_file, rate=1.0)
            else:
                chart_file = tmp_file
                await pattern.send(f"已收到文件：{file_name}，请稍候...")
                result_texts = [await _analyze_single_chart(chart_file, file_name, rate=1.0)]

            await send_forward_text_messages(bot, event, result_texts)
            await pattern.finish()

        elif bid is not None:
            tmp_file, file_name = await download_file_by_id(CACHE_DIR, bid)
            chart_file = tmp_file

            result_texts = [await _analyze_single_chart(chart_file, file_name, rate=1.0)]
            await send_forward_text_messages(bot, event, result_texts)
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
