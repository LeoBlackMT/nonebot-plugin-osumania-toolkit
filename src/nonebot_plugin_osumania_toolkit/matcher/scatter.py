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

from ..render.scatter import plot_scatter
from ..file.path import safe_filename
from ..api.download import download_file, get_file_url
from ..api.osu import download_file_by_id
from ..file.cleanup import cleanup_temp_file
from ..algorithm.utils import parse_cmd, is_mc_file
from ..algorithm.conversion import convert_mr_to_osr, convert_mc_to_osu

CACHE_DIR.mkdir(parents=True, exist_ok=True)

scatter = on_command("scatter", aliases={"散点"})

@scatter.handle()
async def handle_first(bot: Bot, event: MessageEvent, state: T_State):
    
    state["status"] = "init"
    
    cmd_text = event.get_plaintext().strip()
    _speed_rate, _od_flag, _cvt_flag, bid, _mod_display, cmd_err_msg = parse_cmd(cmd_text)
    if cmd_err_msg:
        state["status"] = "Fail"
        await scatter.finish("错误:\n" + "\n".join(cmd_err_msg) + "\n请检查命令格式并重试。")
    
    if not bid:
        await scatter.finish("请回复一条包含回放文件的消息，同时使用 b<谱面ID> 指定谱面。")

    if not event.reply:
        if bid is None:
            state["status"] = "Fail"
            await scatter.finish("请回复一条包含回放文件的消息，同时使用 b<谱面ID> 指定谱面。")
        else:
            state["status"] = "Fail"
            await scatter.finish("请回复一条包含回放文件的消息。")
    reply = event.reply
    file_seg = None
    for seg in reply.message:
        if seg.type == "file":
            file_seg = seg
            break

    if not file_seg:
        state["status"] = "Fail"
        await scatter.finish("回复的消息中没有找到文件。")

    # 获取文件信息
    file_info = await get_file_url(bot, file_seg)
    if not file_info:
        state["status"] = "Fail"
        await scatter.finish("无法获取文件信息。请确保机器人有权限访问该文件，或者文件链接有效。")

    file_name, file_url = file_info
    file_name = os.path.basename(file_name)
    if not (file_name.lower().endswith(".osr") or file_name.lower().endswith(".mr")):
        state["status"] = "Fail"
        await scatter.finish("请回复 .osr 或 .mr 格式的回放文件。")

    osr_path = CACHE_DIR / safe_filename(file_name)
    state["osr_path"] = osr_path
    file_err_msg = []
    
    try:
        success = await download_file(file_url, osr_path)
        if not success:
            state["status"] = "Fail"
            await scatter.finish("文件下载失败，请稍后重试。")
        
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
        pass
    except Exception as e:
        state["status"] = "Fail"
        await scatter.send(f"处理过程中发生错误：{type(e).__name__}: {e}")
    finally:
        if osr_path and osr_path.exists():
            asyncio.create_task(cleanup_temp_file(osr_path))
    
    state["osr"] = osr
    
    # 按是否提供谱面 ID 分支处理
    if bid is not None:
        # 已提供谱面 ID
        try:
            osu_path, _osu_name = await download_file_by_id(CACHE_DIR, bid)
            
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
                await scatter.finish("错误:\n" + "\n".join(file_err_msg))
            
            await scatter.send("已收到文件，请稍候...")
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, plot_scatter, osr, osu, str(CACHE_DIR)
            )
            output_path = result
            state["status"] = "Finish"
            await scatter.finish(MessageSegment.image(f"file://{output_path}"))
        except FinishedException:
            pass    
        except Exception as e:
            state["status"] = "Fail"
            await scatter.send(str(e))
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
            await scatter.finish("错误:\n" + "\n".join(file_err_msg))
        # 直接返回，进入下一个 got 阶段（交互模式），由 @scatter.got 处理
        await scatter.send("未提供谱面 ID, 请发送对应的谱面文件。")
        return

@scatter.got("user_file")
async def handle_file(bot: Bot, state: T_State, user_file: Message = Arg("user_file")):
    
    osr_path = state["osr_path"]
    osu_path = None
    output_path = None
       
    match state["status"]:
        case "Fail" | "Finish":
            if osr_path and osr_path.exists():
                asyncio.create_task(cleanup_temp_file(osr_path))
            if osu_path and osu_path.exists():
                asyncio.create_task(cleanup_temp_file(osu_path))
            if output_path and Path(output_path).exists():
                asyncio.create_task(cleanup_temp_file(Path(output_path))) 
            await scatter.finish()
        case _:
            pass
    
    # 检查用户是否发送了文件
    file_seg = None
    for seg in user_file:
        if seg.type == "file":
            file_seg = seg
            break
        
    if not file_seg:
        await scatter.finish("未找到谱面文件，操作已取消。")

    # 使用辅助函数获取文件信息
    file_info = await get_file_url(bot, file_seg)
    if not file_info:
        await scatter.finish("无法获取文件信息。请确保机器人有权限访问该文件，或者文件链接有效。")

    file_name, file_url = file_info
    file_name = os.path.basename(file_name)
    if not (file_name.lower().endswith(".osu") or file_name.lower().endswith(".mc")):
        await scatter.finish("请回复 .osu 或 .mc 格式的谱面文件。")
    if not file_url:
        await scatter.finish("无法获取文件下载链接。")

    osu_path = CACHE_DIR / safe_filename(file_name)
    osr = state["osr"]
    osr_path = state["osr_path"]
    file_err_msg = []
    
    try:
        success = await download_file(file_url, osu_path)
        if not success:
            await scatter.finish("文件下载失败，请稍后重试。")

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
                await scatter.finish(f".mc 文件转换失败: {e}")
            
        osu = await asyncio.to_thread(osu_file, chart_file)
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
                await scatter.finish("错误:\n" + "\n".join(file_err_msg))
                
        await scatter.send("已收到文件，请稍候...")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, plot_scatter, osr, osu, str(CACHE_DIR)
        )
        output_path = result
        await scatter.finish(MessageSegment.image(f"file://{output_path}"))
    except FinishedException:
        pass    
    except Exception as e:
        await scatter.send(str(e))
    finally:
        if osr_path and osr_path.exists():
            asyncio.create_task(cleanup_temp_file(osr_path))
        if osu_path and osu_path.exists():
            asyncio.create_task(cleanup_temp_file(osu_path))
        if output_path and Path(output_path).exists():
            asyncio.create_task(cleanup_temp_file(Path(output_path)))
        if chart_file and Path(chart_file).exists():
            asyncio.create_task(cleanup_temp_file(Path(chart_file))) 