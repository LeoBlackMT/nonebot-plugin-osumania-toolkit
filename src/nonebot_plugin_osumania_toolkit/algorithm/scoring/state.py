"""Cvtscore state management: file loading, preparation, and orchestration."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from ..conversion import convert_mc_to_osu, convert_mr_to_osr
from ..utils import is_mc_file
from ...api.download import download_file, get_file_url
from ...api.osu import download_file_by_id
from ...file.cleanup import cleanup_paths
from ...file.path import safe_filename
from ...parser.mr_file_parser import mr_file
from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import osu_file

from .ruleset import get_ruleset_quick_help_text, parse_cvtscore_cmd, resolve_target_ruleset, detect_source_ruleset
from .convert import compute_cvtscore, format_cvtscore_message
from .card import build_cvtscore_card_data, validate_replay_status, validate_chart_status


def first_file_segment(message: Any):
    for seg in message:
        if getattr(seg, "type", None) == "file":
            return seg
    return None


def all_cleanup_targets(state: dict[str, Any]) -> tuple[Path | str | None, ...]:
    return (
        state.get("replay_path"),
        state.get("downloaded_chart_path"),
        state.get("converted_chart_path"),
    )


async def cleanup_cvtscore_state(state: dict[str, Any]) -> None:
    asyncio.create_task(cleanup_paths(*all_cleanup_targets(state)))


async def load_replay_from_file_seg(bot: Any, file_seg: Any, state: dict[str, Any], cache_dir: Path) -> str | None:
    file_info = await get_file_url(bot, file_seg)
    if not file_info:
        return "无法获取文件信息。请确保机器人有权限访问该文件。"

    file_name, file_url = file_info
    file_name = os.path.basename(file_name)
    lower_name = file_name.lower()

    if not (lower_name.endswith(".osr") or lower_name.endswith(".mr")):
        return "请发送 .osr 或 .mr 回放文件。"

    replay_path = cache_dir / safe_filename(file_name)
    success = await download_file(file_url, replay_path)
    if not success:
        return "回放文件下载失败，请稍后重试。"

    # 即使后续解析失败，也保留路径用于统一清理。
    state["replay_path"] = replay_path

    if lower_name.endswith(".osr"):
        replay_obj = await asyncio.to_thread(osr_file, replay_path)
        await asyncio.to_thread(replay_obj.process)
        err = validate_replay_status("osr", osr_obj=replay_obj)
        if err:
            return err

        state["replay_kind"] = "osr"
        state["mr_obj"] = None
        state["osr_obj"] = replay_obj
        state["replay_path"] = replay_path
        state["replay_name"] = file_name
        return None

    mr_obj = await asyncio.to_thread(mr_file, replay_path)
    err = validate_replay_status("mr", mr_obj=mr_obj)
    if err:
        return err

    replay_obj = convert_mr_to_osr(mr_obj)
    if replay_obj.status in {"NotMania", "tooFewKeys"}:
        return "该 mr 回放有效轨道数量不足或并非 Mania 数据，无法计算。"

    state["replay_kind"] = "mr"
    state["mr_obj"] = mr_obj
    state["osr_obj"] = replay_obj
    state["replay_path"] = replay_path
    state["replay_name"] = file_name
    return None


async def load_chart_from_file_seg(bot: Any, file_seg: Any, state: dict[str, Any], cache_dir: Path) -> str | None:
    file_info = await get_file_url(bot, file_seg)
    if not file_info:
        return "无法获取文件信息。请确保机器人有权限访问该文件。"

    file_name, file_url = file_info
    file_name = os.path.basename(file_name)
    lower_name = file_name.lower()

    if not (lower_name.endswith(".osu") or lower_name.endswith(".mc")):
        return "请发送 .osu 或 .mc 谱面文件。"

    downloaded_path = cache_dir / safe_filename(file_name)
    success = await download_file(file_url, downloaded_path)
    if not success:
        return "谱面文件下载失败，请稍后重试。"

    # 即使后续解析失败，也保留路径用于统一清理。
    state["downloaded_chart_path"] = downloaded_path

    chart_path = downloaded_path
    converted_path: Path | None = None

    if lower_name.endswith(".mc"):

        if not is_mc_file(str(downloaded_path)):
            return "无效的 .mc 文件，或不是支持的 key 模式谱面。"
        try:
            converted_path = Path(
                await asyncio.to_thread(convert_mc_to_osu, str(downloaded_path), str(cache_dir))
            )
        except Exception as exc:
            return f".mc 转换失败: {exc}"
        chart_path = converted_path
        file_name = converted_path.name

    osu_obj = osu_file(str(chart_path))
    await asyncio.to_thread(osu_obj.process)
    err = validate_chart_status(osu_obj)
    if err:
        return err

    state["downloaded_chart_path"] = downloaded_path
    state["converted_chart_path"] = converted_path
    state["chart_path"] = chart_path
    state["chart_name"] = file_name
    state["osu_obj"] = osu_obj
    return None


async def load_chart_from_bid(state: dict[str, Any], cache_dir: Path) -> str | None:
    bid = state.get("bid")
    if bid is None:
        return "未提供 bid。"

    try:
        osu_path, osu_name = await download_file_by_id(cache_dir, int(bid))
    except Exception as exc:
        return f"通过 bid 下载谱面失败: {exc}"

    osu_obj = osu_file(str(osu_path))
    await asyncio.to_thread(osu_obj.process)
    err = validate_chart_status(osu_obj)
    if err:
        return err

    state["downloaded_chart_path"] = osu_path
    state["converted_chart_path"] = None
    state["chart_path"] = osu_path
    state["chart_name"] = osu_name
    state["osu_obj"] = osu_obj
    return None


async def prepare_cvtscore_state(state: dict[str, Any], cache_dir: Path) -> tuple[bool, str]:
    if state.get("osr_obj") is None:
        state["stage"] = "need_replay"
        return False, "请发送回放文件（.osr 或 .mr）。可以同时补充 bid/ruleset 参数，输入 0 取消。"

    if state.get("osu_obj") is None:
        if state.get("bid") is not None and not state.get("bid_loaded"):
            state["bid_loaded"] = True
            bid_err = await load_chart_from_bid(state, cache_dir)
            if bid_err:
                state["bid_load_error"] = bid_err
                state["osu_obj"] = None

        if state.get("osu_obj") is None:
            state["stage"] = "need_chart"
            bid_err = state.get("bid_load_error")
            if bid_err:
                return (
                    False,
                    f"{bid_err}\n请重新输入 b<bid>（或 mania 链接），或发送 .osu/.mc 谱面文件。谱面不可跳过。输入 0 取消。",
                )
            return False, "请发送谱面文件（.osu/.mc），或输入 b<bid>（或 mania 链接）。谱面不可跳过，输入 0 取消。"

    if not state.get("target_spec"):
        state["stage"] = "need_ruleset"
        return False, "请输入目标 ruleset。\n" + get_ruleset_quick_help_text() + "\n你也可以附带 -sv2 / -nosv2。"

    state["stage"] = "ready"
    return True, ""


async def run_cvtscore_conversion(state: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    target_spec = str(state.get("target_spec") or "").strip()
    target_rs, target_info, target_err = resolve_target_ruleset(target_spec)
    if target_err:
        return None, target_err

    replay_kind = str(state.get("replay_kind") or "").lower()
    osr_obj = state.get("osr_obj")
    mr_obj = state.get("mr_obj")
    osu_obj = state.get("osu_obj")
    force_sv2 = state.get("force_sv2")

    source_rs, source_info, source_err = detect_source_ruleset(
        replay_kind=replay_kind,
        osu_obj=osu_obj,
        osr_obj=osr_obj,
        mr_obj=mr_obj,
        force_sv2=force_sv2,
    )
    if source_err:
        return None, source_err

    result, cvt_err = compute_cvtscore(
        osu_obj=osu_obj,
        osr_obj=osr_obj,
        source_ruleset=source_rs,
        target_ruleset=target_rs,
    )
    if cvt_err:
        return None, cvt_err

    message = format_cvtscore_message(
        source_info=source_info,
        target_info=target_info,
        source_ruleset=source_rs,
        target_ruleset=target_rs,
        source_score=result["source_score"],
        target_score=result["target_score"],
    )

    card_data: dict[str, Any] | None = None
    try:
        card_data = build_cvtscore_card_data(
            source_info=source_info,
            target_info=target_info,
            source_ruleset=source_rs,
            target_ruleset=target_rs,
            source_score=result["source_score"],
            target_score=result["target_score"],
        )
    except Exception:
        # Keep text output available even when card data building fails.
        card_data = None

    return {
        "text": message,
        "card_data": card_data,
    }, None


def update_cvtscore_state_from_text_input(text: str, state: dict[str, Any]) -> list[str]:
    bid, force_sv2, spec, errors = parse_cvtscore_cmd(text)
    if force_sv2 is not None:
        state["force_sv2"] = force_sv2
    if bid is not None:
        state["bid"] = bid
        state["bid_loaded"] = False
        state["bid_load_error"] = None
    if spec:
        state["target_spec"] = spec
    return errors

