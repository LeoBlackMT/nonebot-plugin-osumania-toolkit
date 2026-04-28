import os
import asyncio
from pathlib import Path

from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment, Message
from nonebot.typing import T_State
from nonebot.exception import FinishedException
from nonebot import on_command
from nonebot.params import Arg

from ..file.cache import CACHE_DIR
from ..parser.osu_file_parser import osu_file
from ..parser.osr_file_parser import osr_file
from ..parser.mr_file_parser import mr_file

from ..render.comprehensive import run_plot_comprehensive
from ..file.path import safe_filename
from ..api.download import download_file, get_file_url
from ..api.osu import download_file_by_id
from ..file.cleanup import cleanup_temp_file
from ..algorithm.utils import parse_bid_or_url, parse_cmd, is_mc_file
from ..algorithm.detector import run_analyze_cheating
from ..algorithm.conversion import convert_mr_to_osr, convert_mc_to_osu

CACHE_DIR.mkdir(parents=True, exist_ok=True)

analyze = on_command("analyze", aliases={"分析"}, block=True)

@analyze.handle()
async def handle_first(bot: Bot, event: MessageEvent, state: T_State):
    
    state["status"] = "init"
    
    cmd_text = event.get_plaintext().strip()
    _speed_rate, _od_flag, _cvt_flag, bid, _mod_display, cmd_err_msg = parse_cmd(cmd_text)
    if cmd_err_msg:
        state["status"] = "Fail"
        await analyze.finish("错误:\n" + "\n".join(cmd_err_msg) + "\n请检查命令格式并重试。")

    if not event.reply:
        if bid is None:
            state["status"] = "Fail"
            await analyze.finish("请回复一条包含回放文件的消息，或使用 b<谱面ID> 指定谱面。")
        else:
            state["status"] = "Fail"
            await analyze.finish("请回复一条包含回放文件的消息。")
    reply = event.reply
    file_seg = None
    for seg in reply.message:
        if seg.type == "file":
            file_seg = seg
            break

    if not file_seg:
        state["status"] = "Fail"
        await analyze.finish("回复的消息中没有找到文件。")

    # 获取文件信息
    file_info = await get_file_url(bot, file_seg)
    if not file_info:
        state["status"] = "Fail"
        await analyze.finish("无法获取文件信息。请确保机器人有权限访问该文件，或者文件链接有效。")

    file_name, file_url = file_info
    file_name = os.path.basename(file_name)
    if not (file_name.lower().endswith(".osr") or file_name.lower().endswith(".mr")):
        state["status"] = "Fail"
        await analyze.finish("请回复 .osr 或 .mr 格式的回放文件。")

    osr_path = CACHE_DIR / safe_filename(file_name)
    state["osr_path"] = osr_path
    file_err_msg = []
    osr = None

    try:
        success = await download_file(file_url, osr_path)
        if not success:
            state["status"] = "Fail"
            await analyze.finish("文件下载失败，请稍后重试。")

        if file_name.lower().endswith(".mr"):
            state["status"] = "Malody"
            mr_obj = await asyncio.to_thread(mr_file, osr_path)
            osr = await asyncio.to_thread(convert_mr_to_osr, mr_obj)
        else:
            osr = await asyncio.to_thread(osr_file, osr_path)
            await asyncio.to_thread(osr.process)

        match osr.status:
            case "NotMania":
                file_err_msg.append("该回放不是 Mania 模式。")
            case "tooFewKeys":
                file_err_msg.append("有效轨道数量过少，无法分析。")
            case "init":
                file_err_msg.append("回放尚未process。")
            case _:
                pass

    except FinishedException:
        raise
    except Exception as e:
        state["status"] = "Fail"
        await analyze.send(f"处理过程中发生错误：{type(e).__name__}: {e}")
        return
    finally:
        if osr_path and osr_path.exists():
            asyncio.create_task(cleanup_temp_file(osr_path))

    state["osr"] = osr
    
    # 按是否提供谱面 ID 分支处理
    if bid is not None:
        # 已提供谱面 ID
        try:
            osu_path, osu_name = await download_file_by_id(CACHE_DIR,bid)
            
            osu = await asyncio.to_thread(osu_file, osu_path)
            await asyncio.to_thread(osu.process)
            match osu.status:
                case "NotMania":
                    file_err_msg.append("该谱面不是 Mania 模式。")
                case "init":
                    file_err_msg.append("谱面尚未process。")
                case "OK":
                    pass
                case _:
                    pass
            
            if file_err_msg:
                state["status"] = "Fail"
                await analyze.finish("错误:\n" + "\n".join(file_err_msg))
            
            await analyze.send("已收到文件，请稍候...")
             
            output_path = await run_plot_comprehensive(str(CACHE_DIR), osr, osu)
            result = await run_analyze_cheating(osr, osu)
            reason_str = "\n".join(result["reasons"]) if result["reasons"] else "无分析结果。"
            if result["cheat"] or result["sus"]:
                if result["cheat"]:
                    state["status"] = "Finish"
                    await analyze.send(MessageSegment.image(f"file://{output_path}"))
                    await analyze.finish(f"<!>此成绩检测到作弊：\n{reason_str}\n仅供参考，请结合其他信息进行判断。")
                else:
                    state["status"] = "Finish"
                    await analyze.send(MessageSegment.image(f"file://{output_path}"))
                    await analyze.finish(f"<*>此成绩检测到可疑：\n{reason_str}\n仅供参考，请结合其他信息进行判断。")
            else:
                state["status"] = "Finish"
                await analyze.send(MessageSegment.image(f"file://{output_path}"))
                await analyze.finish(f"分析完成: \n{reason_str}\n仅供参考，请结合其他信息进行判断。")
        except FinishedException:
            pass    
        except Exception as e:
            state["status"] = "Fail"
            await analyze.send(str(e))
        finally:
            if osr_path and osr_path.exists():
                asyncio.create_task(cleanup_temp_file(osr_path))
            if osu_path and osu_path.exists():
                asyncio.create_task(cleanup_temp_file(osu_path))
            if output_path and Path(output_path).exists():
                asyncio.create_task(cleanup_temp_file(Path(output_path)))
        
    else:
        # 未提供谱面 ID
        if file_err_msg:
            state["status"] = "Fail"
            await analyze.finish("错误:\n" + "\n".join(file_err_msg))
        # 直接返回，进入下一个 got 阶段(交互模式),由 @analyze.got 处理
        await analyze.send("未提供谱面 ID, 请发送对应的谱面文件。输入 1 跳过（将执行无谱面分析），输入 0 取消。")
        return

@analyze.got("user_file")
async def handle_file(bot: Bot, state: T_State, user_msg: Message = Arg("user_file")):
    # 从 state 中取回之前保存的对象
    osr = state["osr"]
    osr_path = state["osr_path"]
    if osr is None or osr_path is None:
        await analyze.finish("状态异常，请重新开始。")
    osu_path = None
    output_path = None

    if state["status"] == "Finish" or state["status"] == "Fail":
        if osr_path and osr_path.exists():
            asyncio.create_task(cleanup_temp_file(osr_path))
        if osu_path and osu_path.exists():
            asyncio.create_task(cleanup_temp_file(osu_path))
        if output_path and Path(output_path).exists():
            asyncio.create_task(cleanup_temp_file(Path(output_path)))
        await analyze.finish()

    # 检查用户是否发送了文件
    file_seg = None
    for seg in user_msg:
        if seg.type == "file":
            file_seg = seg
            break

    if not file_seg:
        text = user_msg.extract_plain_text().strip()
        if text == "0":
            await analyze.finish("操作已取消。")
        elif text == "1":
            # 不带谱面的分析
            await analyze.send("处理中，请稍后...")
            try:
                output_path = await run_plot_comprehensive(str(CACHE_DIR), osr)
                result = await run_analyze_cheating(osr)
                reason_str = "\n".join(result["reasons"]) if result["reasons"] else "无分析结果。"
                if result["cheat"] or result["sus"]:
                    if result["cheat"]:
                        await analyze.send(MessageSegment.image(f"file://{output_path}"))
                        await analyze.finish(f"<!>此成绩检测到作弊：\n{reason_str}\n仅供参考，请结合其他信息进行判断。")
                    else:
                        await analyze.send(MessageSegment.image(f"file://{output_path}"))
                        await analyze.finish(f"<*>此成绩检测到可疑：\n{reason_str}\n仅供参考，请结合其他信息进行判断。")
                else:
                    await analyze.send(MessageSegment.image(f"file://{output_path}"))
                    await analyze.finish(f"分析完成: \n{reason_str}\n仅供参考，请结合其他信息进行判断。")
            except FinishedException:
                pass
            except Exception as e:
                await analyze.send(f"错误：{e}")
            finally:
                if osr_path and osr_path.exists():
                    asyncio.create_task(cleanup_temp_file(osr_path))
                if osu_path and osu_path.exists():
                    asyncio.create_task(cleanup_temp_file(osu_path))
                if output_path and Path(output_path).exists():
                    asyncio.create_task(cleanup_temp_file(Path(output_path)))
        elif text:
            parsed_bid, bid_err = parse_bid_or_url(text)
            if bid_err is not None:
                await analyze.reject(f"{bid_err}\n请发送谱面文件，或输入 b<bid>/mania 链接，输入 1 跳过，输入 0 取消。")
            if parsed_bid is None:
                await analyze.reject("输入无效，请发送谱面文件，或输入 b<bid>/mania 链接，输入 1 跳过，输入 0 取消。")

            try:
                osu_path, _osu_name = await download_file_by_id(CACHE_DIR, int(parsed_bid))
                osu = await asyncio.to_thread(osu_file, osu_path)
                await asyncio.to_thread(osu.process)

                file_err_msg = []
                match osu.status:
                    case "NotMania":
                        file_err_msg.append("该谱面不是 Mania 模式。")
                    case "init":
                        file_err_msg.append("谱面尚未process。")
                    case _:
                        pass
                if file_err_msg:
                    await analyze.finish("错误:\n" + "\n".join(file_err_msg))

                await analyze.send("已收到谱面链接，处理中，请稍候...")
                output_path = await run_plot_comprehensive(str(CACHE_DIR), osr, osu)
                result = await run_analyze_cheating(osr, osu)
                reason_str = "\n".join(result["reasons"]) if result["reasons"] else "无分析结果。"
                if result["cheat"] or result["sus"]:
                    if result["cheat"]:
                        await analyze.send(MessageSegment.image(f"file://{output_path}"))
                        await analyze.finish(f"<!>此成绩检测到作弊：\n{reason_str}\n仅供参考，请结合其他信息进行判断。")
                    else:
                        await analyze.send(MessageSegment.image(f"file://{output_path}"))
                        await analyze.finish(f"<*>此成绩检测到可疑：\n{reason_str}\n仅供参考，请结合其他信息进行判断。")
                else:
                    await analyze.send(MessageSegment.image(f"file://{output_path}"))
                    await analyze.finish(f"分析完成: \n{reason_str}\n仅供参考，请结合其他信息进行判断。")
            except FinishedException:
                pass
            except Exception as e:
                await analyze.send(f"错误：{e}")
            finally:
                if osr_path and osr_path.exists():
                    asyncio.create_task(cleanup_temp_file(osr_path))
                if osu_path and osu_path.exists():
                    asyncio.create_task(cleanup_temp_file(osu_path))
                if output_path and Path(output_path).exists():
                    asyncio.create_task(cleanup_temp_file(Path(output_path)))
        else:
            await analyze.reject("输入无效，请发送谱面文件，或输入 1 跳过，输入 0 取消。")
    else:
        # 处理用户发送的 .osu 文件
        file_info = await get_file_url(bot, file_seg)
        if not file_info:
            await analyze.finish("无法获取文件信息。请确保机器人有权限访问该文件，或者文件链接有效。")

        file_name, file_url = file_info
        file_name = os.path.basename(file_name)
        if not (file_name.lower().endswith(".osu") or file_name.lower().endswith(".mc")):
            await analyze.finish("请发送 .osu 或 .mc 格式的谱面文件。")

        osu_path = CACHE_DIR / safe_filename(file_name)
        try:
            success = await download_file(file_url, osu_path)
            if not success:
                await analyze.finish("文件下载失败，请稍后重试。")
                
            chart_file = osu_path
            mc_file = is_mc_file(chart_file)
            if mc_file:
                try:
                    # 转换为 .osu 文件
                    osu_file_path = await asyncio.to_thread(
                        convert_mc_to_osu,
                        str(osu_path),
                        str(CACHE_DIR),
                    )
                    chart_file = Path(osu_file_path)
                    file_name = os.path.basename(osu_file_path)
                except Exception as e:
                    await analyze.finish(f".mc 文件转换失败: {e}")
                
            osu = await asyncio.to_thread(osu_file, chart_file)
            await asyncio.to_thread(osu.process)
            file_err_msg = []
            match osu.status:
                case "NotMania":
                    file_err_msg.append("该谱面不是 Mania 模式。")
                case "init":
                    file_err_msg.append("谱面尚未process。")
                case _:
                    pass
            if file_err_msg:
                await analyze.finish("错误:\n" + "\n".join(file_err_msg))

            await analyze.send(f"已收到文件，请稍候...")
            output_path = await run_plot_comprehensive(str(CACHE_DIR), osr, osu)
            result = await run_analyze_cheating(osr, osu)
            reason_str = "\n".join(result["reasons"]) if result["reasons"] else "无分析结果。"
            if result["cheat"] or result["sus"]:
                if result["cheat"]:
                    await analyze.send(MessageSegment.image(f"file://{output_path}"))
                    await analyze.finish(f"<!>此成绩检测到作弊：\n{reason_str}\n仅供参考，请结合其他信息进行判断。")
                else:
                    await analyze.send(MessageSegment.image(f"file://{output_path}"))
                    await analyze.finish(f"<*>此成绩检测到可疑：\n{reason_str}\n仅供参考，请结合其他信息进行判断。")
            else:
                await analyze.send(MessageSegment.image(f"file://{output_path}"))
                await analyze.finish(f"分析完成: \n{reason_str}\n仅供参考，请结合其他信息进行判断。")
        except FinishedException:
            pass
        except Exception as e:
            await analyze.send(f"错误：{e}")
        finally:
            if osr_path and osr_path.exists():
                asyncio.create_task(cleanup_temp_file(osr_path))
            if osu_path and osu_path.exists():
                asyncio.create_task(cleanup_temp_file(osu_path))
            if output_path and Path(output_path).exists():
                asyncio.create_task(cleanup_temp_file(Path(output_path)))