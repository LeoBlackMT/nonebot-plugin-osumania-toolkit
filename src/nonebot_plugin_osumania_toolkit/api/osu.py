import re
import asyncio
import aiohttp

from nonebot import get_plugin_config
from pathlib import Path
from urllib.parse import unquote
from ..config import Config
config = get_plugin_config(Config)

MAX_FILE_SIZE = config.max_file_size_mb * 1024 * 1024

async def download_file_by_id(cache_dir: Path, map_id: int) -> tuple[Path, str]:
    url = f"https://osu.ppy.sh/osu/{map_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise Exception(f"下载失败，HTTP {resp.status}")
                
                # 检查文件大小限制
                content_length = resp.headers.get('Content-Length')
                if content_length:
                    try:
                        size = int(content_length)
                        if size > MAX_FILE_SIZE:
                            raise Exception(f"谱面文件过大（{size / 1024 / 1024:.2f}MB），超过 {config.max_file_size_mb}MB 限制")
                    except ValueError:
                        pass
                
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
                # 再检查一次实际大小
                if len(content) > MAX_FILE_SIZE:
                    raise Exception(f"谱面文件过大（{len(content) / 1024 / 1024:.2f}MB），超过 {config.max_file_size_mb}MB 限制")

    except Exception as e:
        raise Exception(f"下载谱面时出错: {e}")

    tmp_file = cache_dir / f"{map_id}.osu"
    await asyncio.to_thread(tmp_file.write_bytes, content)

    return tmp_file, filename