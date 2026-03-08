import os
import asyncio
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment, Message
from nonebot.typing import T_State
from nonebot.params import Arg
from nonebot.exception import FinishedException

from ..file.osu_file_parser import osu_file
from ..file.osr_file_parser import osr_file

from ..file.draw import run_plot_comprehensive
from ..file.file import safe_filename, download_file, download_file_by_id, cleanup_temp_file
from ..algorithm.utils import parse_cmd
from ..algorithm.cheat_analyze import run_analyze_cheating


from nonebot_plugin_localstore import get_plugin_cache_dir

CACHE_DIR = get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

analyze = on_command("analyze", aliases={"分析"}, block= True)

@analyze.handle()
async def handle_first(event: MessageEvent, state: T_State):
    
    state["status"] = "init"
    
    cmd_text = event.get_plaintext().strip()
    speed_rate, od_flag, cvt_flag, bid, mod_display, cmd_err_msg = parse_cmd(cmd_text)
    if cmd_err_msg:
        state["status"] = "Fail"
        await analyze.finish("错误:\n" + "\n".join(cmd_err_msg) + "\n请检查命令格式并重试。")

    if not event.reply:
        if bid is None:
            state["status"] = "Fail"
            await analyze.finish("请回复一条包含 .osr 文件的消息，或使用 b<谱面ID> 指定谱面。")
        else:
            state["status"] = "Fail"
            await analyze.finish("请回复一条包含 .osr 文件的消息。")
        # return

    reply = event.reply
    file_seg = None
    for seg in reply.message:
        if seg.type == "file":
            file_seg = seg
            break

    if not file_seg:
        state["status"] = "Fail"
        await analyze.finish("回复的消息中没有找到文件。")

    file_name = file_seg.data.get("file", "")
    file_url = file_seg.data.get("url", "")
    
    if not file_name:
        state["status"] = "Fail"
        await analyze.finish("无法获取文件名。")
    if not file_url:
        state["status"] = "Fail"
        await analyze.finish("无法获取文件下载链接。")
    file_name = os.path.basename(file_name)
    if not file_name.lower().endswith(".osr"):
        state["status"] = "Fail"
        await analyze.finish("请回复 .osr 格式的回放文件。")
    if not file_url:
        state["status"] = "Fail"
        await analyze.finish("无法获取文件下载链接。")

    osr_path = CACHE_DIR / safe_filename(file_name)
    state["osr_path"] = osr_path
    file_err_msg = []
    
    try:
        success = await download_file(file_url, osr_path)
        if not success:
            state["status"] = "Fail"
            await analyze.finish("文件下载失败，请稍后重试。")
            
        osr = osr_file(osr_path)
        osr.process()
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
        if osr_path and osr_path.exists():
            asyncio.create_task(cleanup_temp_file(osr_path))
        if output_path and Path(output_path).exists():
            asyncio.create_task(cleanup_temp_file(Path(output_path)))
    except Exception as e:
        state["status"] = "Fail"
        await analyze.send(f"处理过程中发生错误：{type(e).__name__}: {e}")
    
    state["osr"] = osr
    
    # 分支判断
    if bid is not None:
        # 有谱面 ID
        try:
            osu_path, osu_name = await download_file_by_id(CACHE_DIR,bid)
            
            osu = osu_file(osu_path)
            osu.process()
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
            
            await analyze.send(f"已收到文件，请稍候...")     
             
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
            if osr_path and osr_path.exists():
                asyncio.create_task(cleanup_temp_file(osr_path))
            if osu_path and osu_path.exists():
                asyncio.create_task(cleanup_temp_file(osu_path))
            if output_path and Path(output_path).exists():
                asyncio.create_task(cleanup_temp_file(Path(output_path)))    
        except Exception as e:
            state["status"] = "Fail"
            await analyze.send(f"{e}")
        
    else:
        # 无 bid
        if file_err_msg:
            state["status"] = "Fail"
            await analyze.finish("错误:\n" + "\n".join(file_err_msg))
        # 直接返回，进入下一个 got 阶段(交互模式),由 @delta.got 处理
        await analyze.send("未提供谱面 ID, 请发送对应的.osu文件。输入 1 跳过（将执行无谱面分析），输入 0 取消。")
        return

@analyze.got("user_file")
async def handle_file(state: T_State, user_msg: Message = Arg()):
    
    match state["status"]:
        case "Fail" | "Finish":
            if osr_path and osr_path.exists():
                asyncio.create_task(cleanup_temp_file(osr_path))
            if osu_path and osu_path.exists():
                asyncio.create_task(cleanup_temp_file(osu_path))
            if output_path and Path(output_path).exists():
                asyncio.create_task(cleanup_temp_file(Path(output_path))) 
            await analyze.finish()
        case _:
            pass    
    
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
            # 无osu文件分析
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
            except Exception as e:
                await analyze.send
        else:
            await analyze.reject("输入无效，请发送 .osu 文件，或输入 1 跳过，输入 0 取消。")

    
    file_name = file_seg.data.get("file", "")
    file_url = file_seg.data.get("url", "")
    
    if not file_name:
        await analyze.finish("无法获取文件名。")
    if not file_url:
        await analyze.finish("无法获取文件下载链接。")
    file_name = os.path.basename(file_name)
    if not file_name.lower().endswith(".osr"):
        await analyze.finish("请回复 .osr 格式的回放文件。")
    if not file_url:
        await analyze.finish("无法获取文件下载链接。")

    osu_path = CACHE_DIR / safe_filename(file_name)
    osr = state["osr"]
    osr_path = state["osr_path"]
    file_err_msg = []
    
    try:
        success = await download_file(file_url, osu_path)
        if not success:
            await analyze.finish("文件下载失败，请稍后重试。")
            
        osu = osu_file(osu_path)
        osu.process()
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
        if osr_path and osr_path.exists():
            asyncio.create_task(cleanup_temp_file(osr_path))
        if osu_path and osu_path.exists():
            asyncio.create_task(cleanup_temp_file(osu_path))
        if output_path and Path(output_path).exists():
            asyncio.create_task(cleanup_temp_file(Path(output_path)))    
    except Exception as e:
        await analyze.send(f"{e}")