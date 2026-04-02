'''
/rework 命令已重定向至 /mapview，本文件暂时保留以供参考，未来可能会删除。
'''
import os
import logging

from nonebot import on_command, get_plugin_config
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.exception import FinishedException
from pathlib import Path

from ..file.file import download_file, download_file_by_id, get_file_url, safe_filename
from ..algorithm.utils import send_forward_text_messages
from ..algorithm.rework import get_rework_result_text, get_rework_result, process_zip_file, ParseError, NotManiaError
from ..algorithm.utils import parse_cmd, is_mc_file, resolve_meta_data
from ..algorithm.convert import convert_mc_to_osu

from ..config import Config
config = get_plugin_config(Config)

from nonebot_plugin_localstore import get_plugin_cache_dir

CACHE_DIR = get_plugin_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

rework = on_command("rework", block=True)

@rework.handle()
async def handle_rework(bot: Bot, event: MessageEvent):

    cmd_text = event.get_plaintext().strip()
    speed_rate, od_flag, cvt_flag, bid, mod_display, err_msg = parse_cmd(cmd_text)
    
    if err_msg:
        await rework.send("错误:\n" + "\n".join(err_msg) + "\n请检查命令格式并重试。")
        return

    # 如果有提供文件，忽略bid参数，直接处理文件
    if event.reply:
        reply = event.reply

        file_seg = None
        for seg in reply.message:
            if seg.type == "file":
                file_seg = seg
                break
        if not file_seg:
            await rework.finish("回复的消息中没有找到文件。")

        # 使用辅助函数获取文件信息
        file_info = await get_file_url(bot, file_seg)
        if not file_info:
            await rework.finish("无法获取文件信息。请确保机器人有权限访问该文件，或者文件链接有效。")

        file_name, file_url = file_info
        file_name = safe_filename(os.path.basename(file_name))
        if not (file_name.lower().endswith(".osu") or file_name.lower().endswith(".mc") or
                file_name.lower().endswith(".osz") or file_name.lower().endswith(".mcz")):
            await rework.finish("请回复 .osu/.mc 格式的谱面文件。")

        tmp_file = CACHE_DIR / file_name

        if not await download_file(file_url, tmp_file):
            logging.warning("Failed to download file '%s' from URL '%s'", file_name, file_url)
            # 检查是否因为文件过大而下载失败
            if tmp_file.exists():
                tmp_file.unlink()  # 清理已下载的部分文件
            await rework.finish(
                f"下载失败：文件可能过大（限制{config.max_file_size_mb}MB）或链接无效，请检查并重试。\n"
                "建议：可以删除图包内的媒体文件（音频/背景视频/图片）后再重新打包上传。"
            )

        # 检查文件类型并处理
        try:
            if file_name.lower().endswith(('.osz', '.mcz')):
                # 处理压缩包文件
                await rework.send(f"已收到图包：{file_name}，请耐心等待，请勿重复发送命令。")
                results = await process_zip_file(CACHE_DIR, tmp_file, speed_rate, od_flag, cvt_flag, mod_display)
                
                # 发送结果（分批发送，避免消息过长）
                batch_size = 5  # 每批发送5个结果
                total_batches = (len(results) + batch_size - 1) // batch_size  # 计算总批次数
                batch_messages: list[str] = []
                for i in range(0, len(results), batch_size):
                    batch = results[i:i + batch_size]
                    batch_text = "\n\n".join(batch)
                    batch_messages.append(f"结果（{i//batch_size + 1}/{total_batches}）:\n{batch_text}")

                if len(results) <= 3:
                    for message in batch_messages:
                        await rework.send(message)
                else:
                    await send_forward_text_messages(bot, event, batch_messages)
                    
            else:
                # 处理单个谱面文件
                await rework.send(f"已收到文件：{file_name}，请稍候...")
                
                chart_file = tmp_file
                
                # 检查是否为 .mc 文件，如果是则转换为 .osu
                if is_mc_file(str(chart_file)):
                    try:
                        osu_file_path = convert_mc_to_osu(str(tmp_file), str(CACHE_DIR))
                        chart_file = Path(osu_file_path)
                        file_name = os.path.basename(osu_file_path)
                    except Exception as e:
                        await rework.finish(f".mc 文件转换失败: {e}")

                # 计算星数
                sr, LN_ratio, column_count = await get_rework_result(str(chart_file), speed_rate, od_flag, cvt_flag)
                await rework.send(get_rework_result_text(resolve_meta_data(chart_file, file_name), mod_display, sr, speed_rate, od_flag, LN_ratio, column_count), at_sender=True)
                
        except ParseError:
            await rework.send("谱面解析失败，可能是文件损坏或格式不兼容。")
        except NotManiaError:
            await rework.send("该谱面不是 mania 模式，无法计算。")
        except Exception as e:
            await rework.send(f"计算失败：{e}")
        finally:
            # 清理临时文件
            if tmp_file and tmp_file.exists():
                tmp_file.unlink()
        return
    
    elif bid is None:
        await rework.finish("请回复包含 .osu 或 .mc 文件的消息，或使用 bid/mania 谱面网址指定谱面。")
    
    else:
        try:
            tmp_file, file_name = await download_file_by_id(CACHE_DIR,bid)
            if not tmp_file:
                await rework.finish(f"未找到谱面: b{bid}")
                
            sr, LN_ratio, column_count = await get_rework_result(str(tmp_file), speed_rate, od_flag, cvt_flag)
            await rework.send(get_rework_result_text(resolve_meta_data(tmp_file, file_name), mod_display, sr, speed_rate, od_flag, LN_ratio, column_count), at_sender=True)
        except FinishedException:
            pass
        except ParseError:
            await rework.send("错误: 谱面解析失败，可能是文件损坏或格式不兼容")
        except NotManiaError:
            await rework.send("错误: 该谱面不是 mania 模式，无法计算")
        except Exception as e:
            error_msg = str(e)
            if "超过 {config.max_file_size_mb}MB 限制" in error_msg or "过大" in error_msg:
                await rework.send(
                    f"错误: 谱面文件过大（限制{config.max_file_size_mb}MB），无法处理\n"
                    "建议：可以删除图包内的媒体文件（音频/背景视频/图片）后再重新打包上传。"
                )
            elif "max() iterable argument is empty" in error_msg:
                await rework.send(f"错误: 未找到谱面 b{bid}，请检查bid是否正确")
            else:
                await rework.send(f"错误: {e}")
        finally:
            if tmp_file and tmp_file.exists():
                tmp_file.unlink()