from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.exception import FinishedException, RejectedException
from nonebot.params import Arg
from nonebot.typing import T_State

from ..file.cache import CACHE_DIR

from ..algorithm.scoring import (
    cleanup_cvtscore_state,
    first_file_segment,
    get_ruleset_quick_help_text,
    load_chart_from_file_seg,
    load_replay_from_file_seg,
    parse_cvtscore_cmd,
    prepare_cvtscore_state,
    run_cvtscore_conversion,
    update_cvtscore_state_from_text_input
)
from ..render.cvtscore import render_cvtscore_card
from ..algorithm.utils import parse_bid_or_url


CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "render" / "templates"

cvtscore = on_command("cvtscore", aliases={"转换"}, block=True)


async def _finish_with_cvtscore_result(payload: dict | None):
    payload = payload or {}
    text = str(payload.get("text") or "转换完成。")
    card_data = payload.get("card_data")

    if isinstance(card_data, dict):
        try:
            image_bytes = await render_cvtscore_card(card_data, TEMPLATE_DIR)
        except Exception:
            pass
        else:
            await cvtscore.finish(MessageSegment.image(image_bytes))

    await cvtscore.finish(text)


@cvtscore.handle()
async def handle_cvtscore_first(bot: Bot, event: MessageEvent, state: T_State):
    state["status"] = "init"
    state["reject_time"] = 0
    state["bid_loaded"] = False
    state["bid_load_error"] = None
    state["bid"] = None
    state["force_sv2"] = None
    state["target_spec"] = None
    state["replay_kind"] = None
    state["replay_path"] = None
    state["replay_name"] = None
    state["osr_obj"] = None
    state["mr_obj"] = None
    state["chart_path"] = None
    state["chart_name"] = None
    state["osu_obj"] = None
    state["downloaded_chart_path"] = None
    state["converted_chart_path"] = None

    cmd_text = event.get_plaintext().strip()
    bid, force_sv2, ruleset_spec, cmd_errors = parse_cvtscore_cmd(cmd_text)
    if cmd_errors:
        state["status"] = "Fail"
        await cleanup_cvtscore_state(state)
        await cvtscore.finish("错误:\n" + "\n".join(cmd_errors))

    state["bid"] = bid
    state["force_sv2"] = force_sv2
    state["target_spec"] = ruleset_spec

    try:
        if event.reply:
            file_seg = first_file_segment(event.reply.message)
            if file_seg is not None:
                replay_err = await load_replay_from_file_seg(bot, file_seg, state, CACHE_DIR)
                if replay_err is None:
                    await cvtscore.send("已识别回复中的回放文件。")
                else:
                    chart_err = await load_chart_from_file_seg(bot, file_seg, state, CACHE_DIR)
                    if chart_err is None:
                        await cvtscore.send("已识别回复中的谱面文件。")
                    else:
                        state["status"] = "Fail"
                        await cleanup_cvtscore_state(state)
                        await cvtscore.finish(
                            "回复消息中的文件既不是有效回放也不是有效谱面。\n"
                            f"回放错误: {replay_err}\n"
                            f"谱面错误: {chart_err}"
                        )

        ready, prompt = await prepare_cvtscore_state(state, CACHE_DIR)
        if not ready:
            await cvtscore.send(prompt)
            return
        payload, err = await run_cvtscore_conversion(state)
        if err:
            state["status"] = "Fail"
            await cleanup_cvtscore_state(state)
            await cvtscore.finish(f"转换失败: {err}")

        state["status"] = "Finish"
        await cleanup_cvtscore_state(state)
        await _finish_with_cvtscore_result(payload)

    except FinishedException:
        raise
    except Exception as exc:
        state["status"] = "Fail"
        await cleanup_cvtscore_state(state)
        await cvtscore.finish(f"处理失败: {exc}")


@cvtscore.got("user_input")
async def handle_cvtscore_interactive(bot: Bot, state: T_State, user_input: Message = Arg("user_input")):
    if state.get("status") in {"Fail", "Finish"}:
        await cleanup_cvtscore_state(state)
        await cvtscore.finish()

    reject_time = int(state.get("reject_time", 0) or 0)
    if reject_time > 5:
        state["status"] = "Fail"
        await cleanup_cvtscore_state(state)
        await cvtscore.finish("重试次数过多，操作已取消。")

    text = user_input.extract_plain_text().strip()
    if text == "0":
        state["status"] = "Finish"
        await cleanup_cvtscore_state(state)
        await cvtscore.finish("已取消操作。")

    stage = str(state.get("stage") or "need_replay")
    file_seg = first_file_segment(user_input)

    try:
        if stage == "need_replay":
            if file_seg is not None:
                err = await load_replay_from_file_seg(bot, file_seg, state, CACHE_DIR)
                if err:
                    state["reject_time"] = reject_time + 1
                    await cvtscore.reject(f"回放文件处理失败: {err}\n请重新发送 .osr/.mr 文件，或输入 0 取消。")
            elif text:
                errors = update_cvtscore_state_from_text_input(text, state)
                if errors:
                    state["reject_time"] = reject_time + 1
                    await cvtscore.reject("参数错误:\n" + "\n".join(errors) + "\n请继续发送回放文件。")
            else:
                state["reject_time"] = reject_time + 1
                await cvtscore.reject("请发送回放文件（.osr/.mr）。输入 0 取消。")

        elif stage == "need_chart":
            if file_seg is not None:
                err = await load_chart_from_file_seg(bot, file_seg, state, CACHE_DIR)
                if err:
                    state["reject_time"] = reject_time + 1
                    await cvtscore.reject(f"谱面文件处理失败: {err}\n请重新发送 .osu/.mc，或输入 b<bid>，输入 0 取消。")
            elif text:
                parsed_bid, bid_err = parse_bid_or_url(text)
                if bid_err is not None:
                    state["reject_time"] = reject_time + 1
                    await cvtscore.reject(f"{bid_err}\n请重新输入 b<bid>（或 mania 链接），或发送谱面文件，输入 0 取消。")
                if parsed_bid is None:
                    errors = update_cvtscore_state_from_text_input(text, state)
                    if errors:
                        state["reject_time"] = reject_time + 1
                        await cvtscore.reject("参数错误:\n" + "\n".join(errors) + "\n请继续提供谱面。")
                    if state.get("bid") is None and state.get("osu_obj") is None:
                        state["reject_time"] = reject_time + 1
                        await cvtscore.reject("请发送 .osu/.mc 谱面文件，或输入 b<bid>。")
                else:
                    state["bid"] = parsed_bid
                    state["bid_loaded"] = False
                    state["bid_load_error"] = None
            else:
                state["reject_time"] = reject_time + 1
                await cvtscore.reject("请发送 .osu/.mc 谱面文件，或输入 b<bid>。输入 0 取消。")

        elif stage == "need_ruleset":
            if file_seg is not None:
                state["reject_time"] = reject_time + 1
                await cvtscore.reject("当前步骤需要输入目标 ruleset 文本，不需要发送文件。输入 0 取消。")
            if not text:
                state["reject_time"] = reject_time + 1
                await cvtscore.reject("请输入目标 ruleset。\n" + get_ruleset_quick_help_text())

            errors = update_cvtscore_state_from_text_input(text, state)
            if errors:
                state["reject_time"] = reject_time + 1
                await cvtscore.reject("参数错误:\n" + "\n".join(errors) + "\n" + get_ruleset_quick_help_text())

            if not state.get("target_spec"):
                state["reject_time"] = reject_time + 1
                await cvtscore.reject("未解析到目标 ruleset。\n" + get_ruleset_quick_help_text())

        ready, prompt = await prepare_cvtscore_state(state, CACHE_DIR)
        if not ready:
            await cvtscore.reject(prompt)

        await cvtscore.send("信息已齐全，正在转换成绩，请稍候...")
        payload, err = await run_cvtscore_conversion(state)
        if err:
            state["status"] = "Fail"
            await cleanup_cvtscore_state(state)
            await cvtscore.finish(f"转换失败: {err}")

        state["status"] = "Finish"
        await cleanup_cvtscore_state(state)
        await _finish_with_cvtscore_result(payload)

    except FinishedException:
        raise
    except RejectedException:
        raise
    except Exception as exc:
        state["status"] = "Fail"
        await cleanup_cvtscore_state(state)
        await cvtscore.finish(f"处理失败: {exc}")
