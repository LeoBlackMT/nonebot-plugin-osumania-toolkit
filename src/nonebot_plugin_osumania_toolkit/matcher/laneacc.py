from __future__ import annotations

import os
import re
import asyncio
from pathlib import Path

from nonebot import on_command
from nonebot.params import Arg
from nonebot.typing import T_State
from nonebot.exception import FinishedException
from nonebot.adapters import Bot, Event, Message

from .. import platform
from ..file.cache import CACHE_DIR
from ..file.path import safe_filename
from ..api.download import download_file
from ..file.cleanup import cleanup_paths
from ..api.osu import download_file_by_id
from ..parser.mr_file_parser import mr_file
from ..parser.osr_file_parser import osr_file
from ..parser.osu_file_parser import osu_file
from ..algorithm.conversion import convert_mc_to_osu
from ..algorithm.laneacc.service import analyze_laneacc
from ..algorithm.laneacc.text import format_laneacc_text
from ..algorithm.utils import parse_cmd, parse_bid_or_url
from ..render.laneacc import render_laneacc_card, build_laneacc_template

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "render" / "templates"
_MODE_RE = re.compile(r"(?:^|\s)-mode(?:\s+|=)(\S+)", re.IGNORECASE)

laneacc = on_command("laneacc", aliases={"分轨"}, block=True)


def _strip_mode(cmd_text: str) -> tuple[str | None, str]:
    match = _MODE_RE.search(cmd_text)
    if not match:
        return None, cmd_text
    mode = match.group(1)
    cleaned = (cmd_text[: match.start()] + " " + cmd_text[match.end() :]).strip()
    return mode, cleaned


def _display_name(osu_obj: osu_file, fallback: str) -> str:
    meta = getattr(osu_obj, "meta_data", None)
    if isinstance(meta, dict) and {"Artist", "Title", "Version"}.issubset(meta):
        return f"{meta['Artist']} - {meta['Title']} [{meta['Version']}]"
    return fallback


async def _load_replay(path: Path, file_name: str):
    if file_name.lower().endswith(".mr"):
        mr_obj = await asyncio.to_thread(mr_file, path)
        if mr_obj.status != "OK":
            raise ValueError(
                f"Malody 回放解析失败: {mr_obj.error_message or mr_obj.status}"
            )
        return None, mr_obj
    osr_obj = await asyncio.to_thread(osr_file, path)
    await asyncio.to_thread(osr_obj.process)
    if osr_obj.status not in {"OK", "tooFewKeys"}:
        raise ValueError(f"回放解析失败: {osr_obj.status}")
    return osr_obj, None


async def _load_chart(path: Path, file_name: str) -> osu_file:
    chart_path = path
    if file_name.lower().endswith(".mc"):
        converted = await asyncio.to_thread(convert_mc_to_osu, str(path), str(CACHE_DIR))
        chart_path = Path(converted)
    osu_obj = await asyncio.to_thread(osu_file, chart_path)
    await asyncio.to_thread(osu_obj.process)
    if osu_obj.status == "NotMania":
        raise ValueError("该谱面不是 mania 模式")
    if osu_obj.status != "OK":
        raise ValueError(f"谱面解析失败: {osu_obj.status}")
    return osu_obj


async def _send_result(
    bot: Bot,
    matcher,
    osu_obj: osu_file,
    osr_obj: osr_file | None,
    mr_obj: mr_file | None,
    display_name: str,
    mode_override: str | None,
) -> None:
    result = await asyncio.to_thread(
        analyze_laneacc,
        osu_obj,
        osr_obj=osr_obj,
        mr_obj=mr_obj,
        mode_override=mode_override,
    )
    player = getattr(osr_obj, "player_name", "") if osr_obj is not None else "Malody"
    if int(result.get("keys", 0)) > 10:
        await matcher.send(
            format_laneacc_text(result, display_name=display_name, player=player)
        )
        return
    try:
        data = build_laneacc_template(result, display_name=display_name, player=player)
        image = await render_laneacc_card(TEMPLATE_DIR, data)
        await platform.send_image(bot, matcher, image)
    except FinishedException:
        raise
    except Exception:
        await matcher.finish(
            format_laneacc_text(result, display_name=display_name, player=player)
        )


async def _run_with_chart(
    bot: Bot,
    matcher,
    state: T_State,
    chart_path: Path,
    chart_name: str,
    mode_override: str | None,
) -> None:
    osr_obj = state.get("osr")
    mr_obj = state.get("mr")
    osu_obj = await _load_chart(chart_path, chart_name)
    await matcher.send("正在计算分轨准确度，请稍候...")
    await _send_result(
        bot,
        matcher,
        osu_obj,
        osr_obj,
        mr_obj,
        _display_name(osu_obj, chart_name),
        mode_override,
    )


@laneacc.handle()
async def handle_laneacc(bot: Bot, event: Event, state: T_State):
    state["mode_override"] = None
    state["osr"] = None
    state["mr"] = None
    state["replay_path"] = None

    cmd_text = event.get_plaintext().strip()
    mode_override, cmd_text = _strip_mode(cmd_text)
    try:
        mode_override = mode_override.strip().lower() if mode_override else None
    except AttributeError:
        mode_override = None
    state["mode_override"] = mode_override

    speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg, _range_text = parse_cmd(
        cmd_text
    )
    if err_msg:
        await laneacc.finish("错误:\n" + "\n".join(err_msg) + "\n请检查命令格式并重试。")

    file_info = await platform.extract_replied_file(bot, event)
    if not file_info:
        await laneacc.finish("请回复一条包含 .osr/.mr 回放文件的消息。")
    file_name, file_url = file_info
    file_name = safe_filename(os.path.basename(file_name))
    if not file_name.lower().endswith((".osr", ".mr")):
        await laneacc.finish("请回复 .osr 或 .mr 格式的回放文件。")

    replay_path = CACHE_DIR / file_name
    state["replay_path"] = replay_path
    try:
        await download_file(file_url, replay_path)
        osr_obj, mr_obj = await _load_replay(replay_path, file_name)
    except FinishedException:
        raise
    except Exception as e:
        await laneacc.finish(f"回放处理失败：{e}")

    state["osr"] = osr_obj
    state["mr"] = mr_obj

    try:
        if bid is not None:
            chart_path, chart_name = await download_file_by_id(CACHE_DIR, bid)
            try:
                await _run_with_chart(
                    bot, laneacc, state, chart_path, chart_name, mode_override
                )
            finally:
                asyncio.create_task(cleanup_paths(replay_path, chart_path))
            await laneacc.finish()
        else:
            await laneacc.send(
                "已收到回放，请发送对应的 .osu/.mc 谱面，或输入 b<bid>；输入 0 取消。"
            )
            return
    except FinishedException:
        raise
    except Exception as e:
        asyncio.create_task(cleanup_paths(replay_path))
        await laneacc.finish(f"分轨分析失败：{e}")


@laneacc.got("map_input")
async def handle_map_input(
    bot: Bot,
    event: Event,
    state: T_State,
    message: Message = Arg("map_input"),
):
    replay_path = state.get("replay_path")
    if state.get("osr") is None and state.get("mr") is None:
        await laneacc.finish("状态异常，请重新开始。")
    if replay_path is None:
        await laneacc.finish("状态异常，请重新开始。")

    file_info = await platform.extract_file_from_message(bot, event)
    chart_path: Path | None = None
    temp_path: Path | None = None
    try:
        if file_info is not None:
            chart_name, chart_url = file_info
            chart_name = safe_filename(os.path.basename(chart_name))
            if not chart_name.lower().endswith((".osu", ".mc")):
                await laneacc.reject("请发送 .osu 或 .mc 格式的谱面文件，或输入 b<bid>。")
            temp_path = CACHE_DIR / chart_name
            await download_file(chart_url, temp_path)
            chart_path = temp_path
        else:
            text = message.extract_plain_text().strip()
            if text == "0":
                await laneacc.finish("操作已取消。")
            parsed_bid, bid_err = parse_bid_or_url(text)
            if bid_err is not None:
                await laneacc.reject(
                    f"{bid_err}\n请发送谱面文件，或输入 b<bid>，输入 0 取消。"
                )
            if parsed_bid is None:
                await laneacc.reject(
                    "输入无效，请发送谱面文件，或输入 b<bid>，输入 0 取消。"
                )
            downloaded, downloaded_name = await download_file_by_id(
                CACHE_DIR, int(parsed_bid)
            )
            chart_path = downloaded
            temp_path = downloaded
            chart_name = downloaded_name

        await _run_with_chart(
            bot,
            laneacc,
            state,
            chart_path,
            chart_name,
            state.get("mode_override"),
        )
        await laneacc.finish()
    except FinishedException:
        raise
    except Exception as e:
        await laneacc.finish(f"分轨分析失败：{e}")
    finally:
        asyncio.create_task(cleanup_paths(replay_path, temp_path))
