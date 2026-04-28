import asyncio
import aiohttp
import shutil

from nonebot.log import logger
from nonebot import get_plugin_config
from nonebot.adapters.onebot.v11 import Bot, MessageSegment
from pathlib import Path
from urllib.parse import unquote
from typing import Optional, Tuple

from ..config import Config
from ..file.path import _get_local_path_from_str
from ..file.cleanup import cleanup_temp_file, _is_safe_cleanup_target
config = get_plugin_config(Config)

# 文件大小限制
MAX_FILE_SIZE = config.max_file_size_mb * 1024 * 1024  # 根据配置设置

async def get_file_url(bot: Bot, file_seg: MessageSegment) -> Optional[Tuple[str, str]]:
    """
    从文件消息段中提取文件名和 URL，支持多种 OneBot 实现

    参数:
        bot: NoneBot Bot 实例
        file_seg: 文件消息段

    返回:
        (file_name, file_url) 元组，如果获取失败返回 None
    """
    try:
        file_data = file_seg.data
        logger.debug(f"文件消息段数据: {file_data}")

        # 获取文件名
        file_name = file_data.get("file", "") or file_data.get("name", "")
        if not file_name:
            logger.error("无法从文件消息段获取文件名")
            return None

        # 获取文件 URL
        file_url = file_data.get("url", "")

        # 如果 url 字段是 HTTP URL，检查 file 字段是否同时存有本地路径，有则调度清理
        if file_url and file_url.startswith("http"):
            file_field_raw = file_data.get("file", "")
            if file_field_raw and not file_field_raw.startswith("http"):
                local_path = _get_local_path_from_str(file_field_raw)
                if local_path is not None and _is_safe_cleanup_target(local_path):
                    asyncio.create_task(cleanup_temp_file(local_path))

        # 如果没有直接的 URL，尝试其他方法
        if not file_url:
            # 方法1: 检查 file 字段是否已经是 URL
            file_field = file_data.get("file", "")
            if file_field and (file_field.startswith("http://") or file_field.startswith("https://")):
                file_url = file_field
                logger.info(f"从 file 字段获取到 URL: {file_url}")

            # 方法2: 尝试使用 file_id 通过 Bot API 获取文件信息
            elif file_field:
                try:
                    # 尝试调用 get_file API（仅部分实现支持）
                    file_info = await bot.call_api("get_file", file_id=file_field)
                    http_url = file_info.get("url", "")
                    local_file_str = file_info.get("file", "")
                    if http_url:
                        file_url = http_url
                        local_path = _get_local_path_from_str(local_file_str)
                        if local_path is not None and _is_safe_cleanup_target(local_path):
                            asyncio.create_task(cleanup_temp_file(local_path))
                    elif local_file_str:
                        file_url = local_file_str
                    if file_url:
                        logger.info(f"通过 get_file API 获取到 URL: {file_url}")
                except Exception as e:
                    logger.warning(f"调用 get_file API 失败: {e}")
                    # 继续尝试其他方法

        if not file_url:
            logger.error(f"无法获取文件下载链接。文件数据: {file_data}")
            return None

        return (file_name, file_url)

    except Exception as e:
        logger.error(f"获取文件信息时发生异常: {e}")
        return None


async def download_file(url: str, save_path: Path) -> bool:
    """
    下载文件或复制本地文件到指定路径

    参数:
        url: HTTP URL 或本地文件路径
        save_path: 保存路径

    返回:
        成功返回 True，失败返回 False
    """
    try:
        # 检测是否是本地文件路径
        # Windows 路径: C:\..., D:\..., \\server\...
        # Unix 路径: /..., ~/...
        is_local_path = False
        local_file_path = None

        # 检查是否是 Windows 绝对路径 (C:\, D:\, etc.)
        if len(url) > 2 and url[1] == ':' and url[2] in ('\\', '/'):
            is_local_path = True
            local_file_path = Path(url)
        # 检查是否是 UNC 路径 (\\server\share)
        elif url.startswith('\\\\'):
            is_local_path = True
            local_file_path = Path(url)
        # 检查是否是 Unix 绝对路径
        elif url.startswith('/') or url.startswith('~/'):
            is_local_path = True
            local_file_path = Path(url).expanduser()
        # 检查是否是 file:// URI
        elif url.startswith('file://'):
            is_local_path = True
            # 移除 file:// 前缀，解码 URL 编码，并转换为路径
            path_str = unquote(url[7:])  # 移除 'file://' 并解码 %xx
            # Windows: file:///C:/... -> /C:/... -> C:/...
            if len(path_str) > 2 and path_str[0] == '/' and path_str[2] == ':':
                path_str = path_str[1:]
            local_file_path = Path(path_str)

        if is_local_path and local_file_path:
            # 本地文件复制
            if not local_file_path.exists():
                logger.error(f"本地文件不存在：{local_file_path}")
                return False
            
            # 检查文件大小
            file_size = local_file_path.stat().st_size
            if file_size > MAX_FILE_SIZE:
                logger.warning(f"文件过大（{file_size / 1024 / 1024:.2f}MB）超过限制（{config.max_file_size_mb}MB）：{local_file_path}")
                return False

            logger.info(f"从本地路径复制文件：{local_file_path} -> {save_path}")
            await asyncio.to_thread(shutil.copy2, local_file_path, save_path)
            if _is_safe_cleanup_target(local_file_path):
                asyncio.create_task(cleanup_temp_file(local_file_path, delay=30.0))
            return True
        else:
            # HTTP/HTTPS 下载
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        # 检查 Content-Length 头，提前拦截超大文件
                        content_length = resp.headers.get('Content-Length')
                        if content_length:
                            try:
                                size = int(content_length)
                                if size > MAX_FILE_SIZE:
                                    logger.warning(f"文件过大（{size / 1024 / 1024:.2f}MB）超过限制（{config.max_file_size_mb}MB）：{url}")
                                    return False
                            except ValueError:
                                pass
                        content = await resp.read()
                        if len(content) > MAX_FILE_SIZE:
                            logger.warning(f"下载中发现文件超过限制（{config.max_file_size_mb}MB），中止下载：{url}")
                            save_path.unlink(missing_ok=True)
                            return False

                        await asyncio.to_thread(save_path.write_bytes, content)
                        return True
                    else:
                        logger.error(f"下载失败，状态码：{resp.status}")
                        return False
    except Exception as e:
        logger.error(f"下载异常：{e}")
        return False