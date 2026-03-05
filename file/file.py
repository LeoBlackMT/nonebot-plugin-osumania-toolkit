import re
import asyncio
import aiohttp

from nonebot.log import logger
from pathlib import Path
from urllib.parse import unquote

def safe_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', filename)

async def download_file(url: str, save_path: Path) -> bool:
    try:
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