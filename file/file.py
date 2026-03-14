import re
import asyncio
import aiohttp
import shutil
import time

from nonebot.log import logger
from nonebot.adapters.onebot.v11 import Bot, MessageSegment
from pathlib import Path
from urllib.parse import unquote
from typing import Optional, Tuple

def safe_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', filename)


async def get_file_url(bot: Bot, file_seg: MessageSegment) -> Optional[Tuple[str, str]]:
    """
    从文件消息段中提取文件名和 URL，支持多种 OneBot 实现

    Args:
        bot: NoneBot Bot 实例
        file_seg: 文件消息段

    Returns:
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
                    file_url = file_info.get("url", "") or file_info.get("file", "")
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

    Args:
        url: HTTP URL 或本地文件路径
        save_path: 保存路径

    Returns:
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
            # 移除 file:// 前缀并转换为路径
            path_str = url[7:]  # 移除 'file://'
            local_file_path = Path(path_str)

        if is_local_path and local_file_path:
            # 本地文件复制
            if not local_file_path.exists():
                logger.error(f"本地文件不存在：{local_file_path}")
                return False

            logger.info(f"从本地路径移动文件：{local_file_path} -> {save_path}")
            shutil.move(local_file_path, save_path)  # 移动文件，自动清理源文件
            return True
        else:
            # HTTP/HTTPS 下载
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        with open(save_path, 'wb') as f:
                            f.write(await resp.read())
                        return True
                    else:
                        logger.error(f"下载失败，状态码：{resp.status}")
                        return False
    except Exception as e:
        logger.error(f"下载异常：{e}")
        return False


async def download_file_by_id(cache_dir: Path, map_id: int) -> tuple[Path, str]:
    url = f"https://osu.ppy.sh/osu/{map_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise Exception(f"下载失败，HTTP {resp.status}")
                
                content_disp = resp.headers.get('Content-Disposition', '')
                filename = None
                if content_disp:
                    match = re.search(r"filename\*?=UTF-8''(.+)", content_disp) or \
                            re.search(r'filename="(.+)"', content_disp)
                    if match:
                        filename = unquote(match.group(1))
                if not filename:
                    # 如果获取失败，使用默认的 map_id 作为文件名
                    filename = f"b{map_id}"
                
                content = await resp.read()
                
    except Exception as e:
        raise Exception(f"下载谱面时出错: {e}")

    tmp_file = cache_dir / f"{map_id}.osu"
    with open(tmp_file, 'wb') as f:
        f.write(content)

    return tmp_file, filename


async def cleanup_temp_file(file_path: Path, delay: float = 10.0):
    await asyncio.sleep(delay)
    try:
        if file_path.exists():
            file_path.unlink()
            logger.debug(f"已清理临时文件：{file_path}")
    except Exception as e:
        logger.warning(f"清理文件失败：{e}")


def cleanup_old_cache(cache_dir: Path, max_age_hours: int = 24):
    """
    清理超过指定时间的旧缓存文件

    Args:
        cache_dir: 缓存目录
        max_age_hours: 最大保留时间（小时），默认 24 小时
    """
    try:
        if not cache_dir.exists():
            logger.info(f"缓存目录不存在，跳过清理: {cache_dir}")
            return

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        cleaned_count = 0
        kept_count = 0
        total_size = 0

        logger.info(f"开始清理缓存，最大保留时间: {max_age_hours} 小时")

        # 遍历缓存目录中的所有文件
        for file_path in cache_dir.iterdir():
            if not file_path.is_file():
                continue

            try:
                # 获取文件修改时间
                file_age = current_time - file_path.stat().st_mtime
                file_age_hours = file_age / 3600

                # 如果文件超过最大保留时间，删除它
                if file_age > max_age_seconds:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    cleaned_count += 1
                    total_size += file_size
                    logger.info(f"清理过期缓存文件: {file_path.name} (已存在 {file_age_hours:.1f} 小时，超过 {max_age_hours} 小时)")
                else:
                    kept_count += 1
                    logger.debug(f"保留缓存文件: {file_path.name} (已存在 {file_age_hours:.1f} 小时，未超过 {max_age_hours} 小时)")
            except Exception as e:
                logger.warning(f"清理文件 {file_path.name} 时出错: {e}")

        if cleaned_count > 0:
            logger.info(f"缓存清理完成: 删除 {cleaned_count} 个文件，保留 {kept_count} 个文件，释放 {total_size/1024/1024:.2f} MB 空间")
        else:
            logger.info(f"缓存清理完成: 没有发现过期文件，保留 {kept_count} 个文件")

    except Exception as e:
        logger.error(f"清理缓存目录时发生错误: {e}")