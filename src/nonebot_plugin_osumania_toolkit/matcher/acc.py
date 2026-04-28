import os
import asyncio
import re
from pathlib import Path

from nonebot import on_command
from nonebot.params import Arg, CommandArg
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.typing import T_State
from nonebot.exception import FinishedException, RejectedException

from ..file.cache import CACHE_DIR
from ..file.path import safe_filename
from ..api.download import download_file, get_file_url
from ..api.osu import download_file_by_id
from ..file.cleanup import cleanup_paths
from ..algorithm.acc import (
    calculate_acc_from_dan, 
    calculate_acc,
    calculate_acc_change_from_dan,
    calculate_acc_change,
    validate_dan_name, 
    parse_acc_cmd, 
    calculate_map_notes,
    get_acc_result_text,
)
from ..algorithm.utils import parse_osu_filename
from ..algorithm.utils import is_mc_file
from ..algorithm.conversion import convert_mc_to_osu

CACHE_DIR.mkdir(parents=True, exist_ok=True)

acc = on_command("acc", aliases={"单曲"}, block=True)

@acc.handle()
async def acc_handle_first(matcher: Matcher, event: MessageEvent, state: T_State, cmd: Message = CommandArg()):
    cmd_text = event.get_plaintext().strip()
    dan_name, acc_str, bid, num_songs, sv2_flag, reverse_flag, error_msg = parse_acc_cmd(cmd_text)
    
    state["status"] = "init"
    
    if error_msg:
        state["status"] = "Fail"
        error_text = '\n'.join(error_msg)
        await acc.finish(f"错误: {error_text}")
        
    # 初始化所有state
    state["acc_str"] = acc_str
    state["display_name"] = None
    state["dan_name"] = dan_name
    state["bid"] = bid
    state["num_songs"] = num_songs
    state["note_counts"] = None
    state["osu_path"] = ""
    state["osu_name"] = None
    state["reject_time"] = 0
    state["sv2_flag"] = sv2_flag
    state["reverse_flag"] = reverse_flag
    state["downloaded_path"] = None
    state["converted_path"] = None
    
    # bid模式
    if bid:
        state["mode"] = "bid"
        try:
            osu_path, osu_name = await download_file_by_id(CACHE_DIR, bid)
            state["osu_path"] = osu_path
            state["osu_name"] = osu_name
            
            # 段位名称即谱面元信息
            meta_data = parse_osu_filename(osu_name)
            if meta_data:
                display_name = f"{meta_data['Artist']} - {meta_data['Title']} [{meta_data['Version']}]"
                state["display_name"] = display_name
            else:
                state["display_name"] = osu_name
            
            # 计算各单曲物量
            note_counts = await calculate_map_notes(osu_path, num_songs, sv2_flag)
            state["note_counts"] = note_counts
            
            if acc_str:
                # 有ACC字符串，数据已满足计算条件，到第二个got统一计算
                state["status"] = "Ready"
                matcher.set_arg("handle_second", cmd) # 跳转到第一个got
                return
            else:
                # 没有ACC字符串，进入第一个got获取
                acc_format = "-".join([f"acc{i+1}" for i in range(len(note_counts))])
                prompt_text = "单曲ACC" if state.get("reverse_flag", False) else "ACC变化"
                await acc.send(f"谱面物量分布: {'-'.join(str(n) for n in note_counts)}\n请输入{prompt_text} (格式: {acc_format}):")
                return
        
        except FinishedException:
            raise
        except Exception as e:
            state["status"] = "Fail"
            await acc.send(f"处理谱面时出错: {str(e)}")
            return
        finally:
            asyncio.create_task(
                cleanup_paths(
                    state.get("osu_path"),
                    state.get("downloaded_path"),
                    state.get("converted_path")
                )
            )
    
    # 给定段位名模式
    elif dan_name and acc_str:
        if not validate_dan_name(dan_name, sv2_flag): # 二次验证，确保段位名和 sv2 标志匹配，否则后续计算会出问题
            await acc.reject(f"当前段位{dan_name}暂不支持ScoreV2, 或段位名有误。请确认段位名或移除 -sv2 参数，或重新输入段位名:")
        state["mode"] = "predefined"
        if acc_str:
            state["status"] = "Ready"
            # 有ACC字符串，数据已满足计算条件，到第二个got统一计算
            matcher.set_arg("handle_second", cmd) # 跳转到第一个got
            return
        else:
            # 只有段位名，需要ACC字符串
            sv2_msg = " (+ScoreV2)" if state.get("sv2_flag", False) else ""
            prompt_text = "单曲ACC" if state.get("reverse_flag", False) else "ACC变化"
            await acc.send(f"已选择段位: {dan_name}{sv2_msg}\n请输入{prompt_text} (格式: acc1-acc2-acc3-acc4...):")
    
    # 用户未提供任何信息，进入交互模式，需要先询问段位名或谱面
    else:
        state["mode"] = "interactive"
        await acc.send("请输入要计算的段位名，或发送谱面文件，或输入自定义物量。输入0取消。")
        return

@acc.got("handle_second")
async def acc_handle_second(matcher: Matcher, bot: Bot, state: T_State, message: Message = Arg("handle_second")):
    """
    第二个handler:
    获取段位名、自定义物量、谱面文件或ACC输入
    """
    
    match state["status"]:
        case "Finish" | "Fail":
            asyncio.create_task(
                cleanup_paths(
                    state.get("osu_path"),
                    state.get("downloaded_path"),
                    state.get("converted_path")
                )
            )
            await acc.finish()
        case "Ready":
            # 数据已满足计算条件，到第二个got统一计算
            matcher.set_arg("handle_third", message) # 跳转到第二个got
            return
        case _:
            pass
        
    if state["reject_time"] > 5:
        state["status"] = "Fail"
        await acc.finish("重试次数过多，已取消操作。")
    
    # 检查用户是否发送了文件
    file_seg = None
    for seg in message:
        if seg.type == "file":
            file_seg = seg
            break
    
    if file_seg:
        # 用户发送了文件
        file_info = await get_file_url(bot, file_seg)
        if not file_info:
            state["status"] = "Fail"
            await acc.finish("无法获取文件信息。")
        
        file_name, file_url = file_info
        file_name = os.path.basename(file_name)
        
        if not file_name.lower().endswith(('.osu', '.mc')):
            state["status"] = "Fail"
            await acc.finish("请发送.osu 或 .mc 格式的谱面文件。")
        
        # 下载文件
        downloaded_path = CACHE_DIR / safe_filename(file_name)
        success = await download_file(file_url, downloaded_path)
        if not success:
            state["status"] = "Fail"
            await acc.finish("文件下载失败，请稍后再试。")

        osu_path = downloaded_path
        converted_path = None
        state["downloaded_path"] = downloaded_path

        if file_name.lower().endswith('.mc'):
            try:
                if not is_mc_file(str(downloaded_path)):
                    state["status"] = "Fail"
                    await acc.finish("无效的 .mc 文件，或不是支持的 key 模式谱面。")
                converted_path = Path(
                    await asyncio.to_thread(
                        convert_mc_to_osu,
                        str(downloaded_path),
                        str(CACHE_DIR),
                    )
                )
                osu_path = converted_path
                file_name = converted_path.name
            except FinishedException:
                raise
            except Exception as e:
                state["status"] = "Fail"
                await acc.finish(f".mc 文件转换失败: {e}")

        state["converted_path"] = converted_path
        
        # 保存到state 进入文件模式
        state["mode"] = "file"
        state["osu_path"] = osu_path
        state["osu_name"] = file_name
        
        # 解析谱面文件名
        meta_data = parse_osu_filename(file_name)
        if meta_data:
            display_name = f"{meta_data['Artist']} - {meta_data['Title']} [{meta_data['Version']}]"
            state["display_name"] = display_name
        else:
            state["display_name"] = file_name
        
        # 已保存文件并进入文件模式，使用reject重启本handler以获取信息
        await acc.reject(f"已收到文件: {state['display_name']}\n请对文件回复并发送单曲个数和sv2标识（均可选），用空格分开；或不回复直接发送acc变化。发送0以取消。")
        return
    
    # 不是文件，检查文本输入
    text_input = message.extract_plain_text().strip()
    
    # 输入0，取消操作
    if text_input == '0':
        state["status"] = "Finish"
        await acc.finish("操作已取消。")
        
    # -r 仅允许在首轮命令中使用
    if any(p.lower() == "-r" for p in re.split(r"\s+", text_input) if p):
        state["reject_time"] += 1
        await acc.reject("参数 -r 仅支持在首次命令中输入。请重新输入:")
    
    # 检查是否为acc变化
    # 从上个reject的文件模式下 获取 acc变化 处理发送的文件并跳转到第三部分
    if (state["mode"] == "file") and re.match(r'^(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))+$', text_input):
        state["num_songs"] = 4 # 默认4首歌
        state["sv2_flag"] = False # 默认不启用 sv2
        # 处理文件并计算物量，将获取的acc变化字符串注入到第三个got进行计算
        try:
            note_counts = await calculate_map_notes(state["osu_path"], state["num_songs"], state.get("sv2_flag", False))
            state["note_counts"] = note_counts
        except Exception as e:
            state["status"] = "Fail"
            asyncio.create_task(
                cleanup_paths(
                    state.get("osu_path"),
                    state.get("downloaded_path"),
                    state.get("converted_path")
                )
            )
            await acc.finish(f"处理谱面失败: {e}")
        matcher.set_arg("handle_third", message) # 跳转到第二个got
        return
    
    # 从上个reject已获取文件，进入文件模式
    if state["mode"] == "file":
        # 用户在文件模式下输入了文本，视为分段数和sv2标识
        parts = [p for p in re.split(r"\s+", text_input) if p]
        if len(parts) > 2:
            state["reject_time"] += 1
            await acc.reject("输入格式错误。请对文件回复并发送单曲个数和sv2标识（均可选），用空格分开；或直接发送acc变化。发送0以取消。请重新输入:")
        
        num_songs = None
        sv2_flag = False
        
        for part in parts:
            if part.isdigit():
                num = int(part)
                if num <= 0 or num >= 10:
                    state["reject_time"] += 1
                    await acc.reject("单曲个数必须属于区间(0,10)。发送0以取消。请重新输入:")
                num_songs = num
            elif part.lower() in {"-sv2", "sv2"}:
                sv2_flag = True
            else:
                state["reject_time"] += 1
                await acc.reject("无效的输入。请对文件回复并发送单曲个数和sv2标识（均可选），用空格分开；或直接发送acc变化。发送0以取消。请重新输入:")
        
        state["num_songs"] = num_songs if num_songs else 4 # 默认4首歌
        state["sv2_flag"] = sv2_flag
        
        # 根据新的分段数重新计算物量并提示用户输入acc变化
        try:
            note_counts = await calculate_map_notes(state["osu_path"], state["num_songs"], state.get("sv2_flag", False))
            state["note_counts"] = note_counts
            sv2_msg = " (+ScoreV2)" if state.get("sv2_flag", False) else ""
            acc_format = "-".join([f"acc{i+1}" for i in range(len(note_counts))])
            prompt_text = "单曲ACC" if state.get("reverse_flag", False) else "ACC变化"
            await acc.send(f"已设置分段数: {state['num_songs']}{sv2_msg}\n谱面物量分布: {'-'.join(str(n) for n in note_counts)}\n请输入{prompt_text} (格式: {acc_format}):")
            # 跳转到handle_third获取acc变化
            return
        except Exception as e:
            state["status"] = "Fail"
            asyncio.create_task(
                cleanup_paths(
                    state.get("osu_path"),
                    state.get("downloaded_path"),
                    state.get("converted_path")
                )
            )
            await acc.finish(f"处理谱面失败: {e}")
    
    # 检查是否是自定义物量格式 (int,int,int...)
    if re.match(r'^\d+(?:,\d+)+$', text_input):
        # 自定义物量
        note_counts = [int(n) for n in text_input.split(',')]
        
        # 检查物量值是否有效
        if len(note_counts) < 1:
            state["reject_time"] += 1
            await acc.reject("至少需要一首歌的物量值。请重新输入:")
        
        if any(n <= 0 for n in note_counts):
            state["reject_time"] += 1
            await acc.reject("物量必须为正整数。请重新输入:")
            
        try:    
            # 进入自定义物量模式
            state["mode"] = "custom"
            state["note_counts"] = note_counts
            state["display_name"] = "自定义物量"
            state["sv2_flag"] = False # 自定义物量sv2无意义
            
            # 根据物量个数生成ACC格式提示
            acc_format = "-".join([f"acc{i+1}" for i in range(len(note_counts))])
            prompt_text = "单曲ACC" if state.get("reverse_flag", False) else "ACC变化"
            await acc.send(f"已设置自定义物量: {text_input}\n请输入{prompt_text} (格式: {acc_format}):")
            return
            # 转第二个got，获取acc变化。
        
        except RejectedException:
            pass
        except ValueError:
            state["status"] = "Fail"
            await acc.send("物量格式错误。请使用格式: 物量1,物量2,物量3...")
            return
        except Exception as e:
            state["status"] = "Fail"
            await acc.send(f"处理过程发生错误: {e}")
            return
    
    # 检查混合输入，包含段位名和sv2标识。例如 "regular1 -sv2" 或 "-sv2 regular1"
    parts = [p for p in re.split(r"\s+", text_input) if p]
    has_sv2 = any(p.lower() in {"-sv2", "sv2"} for p in parts)
    # 去掉 sv2 标记后的文本
    core_parts = [p for p in parts if p.lower() not in {"-sv2", "sv2"}]
    core_text = " ".join(core_parts).strip()
    
    # 如果 core_text 存在且为段位名，允许同时包含 sv2 标志
    if core_text and validate_dan_name(core_text, True if has_sv2 else None):
        # 若用户在输入中包含 sv2，则将其写入 state
        if has_sv2:
            state["sv2_flag"] = True
        state["mode"] = "predefined"
        state["dan_name"] = core_text
        sv2_msg = " (+ScoreV2)" if state.get("sv2_flag", False) else ""
        prompt_text = "单曲ACC" if state.get("reverse_flag", False) else "ACC变化"
        await acc.send(f"已选择段位: {core_text}{sv2_msg}\n请输入{prompt_text} (格式: acc1-acc2-acc3-acc4...):")
        return

    # 原有段位匹配降级：如果没有核心文本或不匹配，则继续下一步的 acc 变化匹配或报错
    
    # 检查是否为acc变化
    # 在预定义段位和bid模式下 获取 acc变化 并跳转到第三部分
    if (state["mode"] == "predefined" or state["mode"] == "bid") and re.match(r'^(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))+$', text_input):
        matcher.set_arg("handle_third", message) # 跳转到第二个got
        return
    
    # 无效输入
    state["reject_time"] += 1
    await acc.reject("输入无效。请根据上一个消息的提示发送正确的内容，或输入0取消操作。\n请重新输入:")

@acc.got("handle_third")
async def acc_handle_third(state: T_State, message: Message = Arg("handle_third")):
    """
    第三个handle
    获取ACC输入并输出计算结果
    """
    match state["status"]:
        case "Finish" | "Fail":
            asyncio.create_task(
                cleanup_paths(
                    state.get("osu_path"),
                    state.get("downloaded_path"),
                    state.get("converted_path")
                )
            )
            await acc.finish()
        case _:
            pass
    
    if state["reject_time"] > 5:
        state["status"] = "Fail"
        await acc.finish("重试次数过多，已取消操作。")
    
    # 当数据不满足计算条件时，用户输入ACC
    if state["status"] != "Ready":
        msg_text = message.extract_plain_text().strip()
        if msg_text == '0':
            state["status"] = "Finish"
            asyncio.create_task(
                cleanup_paths(
                    state.get("osu_path"),
                    state.get("downloaded_path"),
                    state.get("converted_path")
                )
            )
            await acc.finish("已取消操作")
        if re.match(r'^(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))+$', msg_text):
            state["acc_str"] = msg_text
        else:
            state["reject_time"] += 1
            await acc.reject("ACC格式错误。请重新输入，或输入0取消:")
    
    # 开始计算（正向：由ACC变化算单曲ACC；反向：由单曲ACC推算ACC变化）
    single_accs = None
    
    # 检查mode是否已定义
    mode = state.get("mode")
    if not mode:
        state["status"] = "Fail"
        await acc.finish("错误: 未获取到计算模式")
    
    if mode == "predefined":
        # 预定义段位模式
        try:
            dan_name = state["dan_name"]
            if not dan_name:
                state["status"] = "Fail"
                await acc.finish("错误: 未获取到段位名")

            if state.get("reverse_flag", False):
                single_accs, calc_error = calculate_acc_change_from_dan(
                    dan_name,
                    state["acc_str"],
                    state.get("sv2_flag", False)
                )
            else:
                single_accs, calc_error = calculate_acc_from_dan(
                    dan_name,
                    state["acc_str"],
                    state.get("sv2_flag", False)
                )
            if calc_error:
                state["status"] = "Fail"
                await acc.finish(f"计算错误: {calc_error}")

            result_msg = get_acc_result_text(
                "predefined",
                dan_name,
                None,
                state["acc_str"],
                single_accs,
                state.get("sv2_flag", False),
                state.get("reverse_flag", False)
            )
            
        except FinishedException:
            raise
        except Exception as e:
            state["status"] = "Fail"
            await acc.send(f"发生错误：{e}")
            return
        finally:
            asyncio.create_task(
                cleanup_paths(
                    state.get("osu_path"),
                    state.get("downloaded_path"),
                    state.get("converted_path")
                )
            )
    
    elif mode in ["bid", "file", "custom"]:
        # 谱面或自定义物量模式
        try:
            note_counts = state["note_counts"]
            display_name = state.get("display_name", "未知")
            
            if not note_counts:
                state["status"] = "Fail"
                await acc.finish("错误: 未获取到物量数据")
            
            if state.get("reverse_flag", False):
                single_accs, calc_error = calculate_acc_change(note_counts, state["acc_str"])
            else:
                single_accs, calc_error = calculate_acc(note_counts, state["acc_str"], state.get("sv2_flag", False))
            if calc_error:
                state["status"] = "Fail"
                await acc.finish(f"计算错误: {calc_error}")
            
            # 构建结果消息
            result_msg = get_acc_result_text(
                mode,
                display_name,
                note_counts,
                state["acc_str"],
                single_accs,
                state.get("sv2_flag", False),
                state.get("reverse_flag", False)
            )
            
        except FinishedException:
            raise
        except Exception as e:
            state["status"] = "Fail"
            await acc.send(f"发生错误：{e}")
            return
        finally:
            asyncio.create_task(
                cleanup_paths(
                    state.get("osu_path"),
                    state.get("downloaded_path"),
                    state.get("converted_path")
                )
            )
    else:
        state["status"] = "Fail"
        await acc.finish("错误: 未知模式")
    
    # 发送结果
    state["status"] = "Finish"
    await acc.finish(result_msg, at_sender=True)
    return
    
"""
流程说明：
    - handler_first:
        - 用户未提供参数: 进入交互模式 -> handler_second (获取段位名或谱面文件或自定义物量)
        - 用户只提供段位名: 进入预定义段位模式 -> handler_second (获取acc字符串)
        - 用户只提供bid: 进入谱面模式 -> handler_second (获取acc字符串)
        - 用户同时提供bid和acc字符串: 进入谱面模式 (标记Ready) -> handler_second
        - 用户同时提供段位名和acc字符串: 进入预定义段位模式 (标记Ready) -> handler_second
        - 用户输入错误: 提示错误并重试，超过次数则标记Fail -> handler_second
        - 程序发生异常: 标记Fail -> handler_second
        
    - handler_second:
        - Finish或Fail状态: 清理临时文件并结束
        - Ready状态: -> handler_third (计算并发送结果)
        - 用户输入0: 取消操作，标记Finish并结束
        - 用户输入 -r: 拒绝 -> handler_second
        - 用户发送了文件: 进入文件模式 (记录必要信息) -> (reject) handler_second (获取其他信息，如分段数)
        - 当前为文件模式且用户输入了非acc字符串: 视为分段数和sv2标识 -> handler_third (获取acc字符串)
        - 当前为文件模式且用户输入了acc字符串: 在文件模式下记录信息 -> 将acc字符串传入并跳转 handler_third (计算并发送结果)
        - 用户输入了自定义物量: 进入自定义物量模式 -> handler_third (计算并发送结果)
        - 用户输入了段位名: 进入预定义段位模式 -> handler_third (计算并发送结果)
        - 用户输入了acc字符串: 如果之前已获取段位名或谱面，进入相应模式 -> 将acc字符串传入并跳转 handler_third (计算并发送结果)
        - 用户输入错误: 提示错误并重试，超过次数则标记Fail -> handler_third
        - 程序发生异常: 标记Fail -> handler_third

    - handler_third:
        - Finish或Fail状态: 清理临时文件并结束
        - 用户输入0: 取消操作，标记Finish并结束
        - Ready状态: 根据mode与是否反推进行计算，生成结果消息并发送，标记Finish
        - 否则获取用户输入的ACC字符串，进行计算，生成结果消息并发送，标记Finish
        - 用户输入错误: 提示错误并重试，超过次数则标记Fail
        - 程序发生异常: 标记Fail
"""