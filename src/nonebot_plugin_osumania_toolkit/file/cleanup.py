import asyncio
import shutil
import time

from nonebot.log import logger
from nonebot import get_plugin_config

from pathlib import Path
from ..config import Config
from .path import _get_cache_root
config = get_plugin_config(Config)

def _is_safe_cleanup_target(path: Path) -> bool:
    cache_root = _get_cache_root()
    if cache_root is None:
        return False

    try:
        target = path.resolve(strict=False)
    except Exception:
        return False

    # 不允许通过 cleanup_paths 删除缓存根目录本身。
    if target == cache_root:
        return False

    try:
        target.relative_to(cache_root)
        return True
    except Exception:
        return False
    
async def cleanup_temp_file(file_path: Path, delay: float = 10.0):
    # 兼容旧接口
    await cleanup_paths(file_path, delay=delay)

async def cleanup_paths(*paths, delay: float = 10.0):
    """
    批量清理临时文件路径。

    参数:
        *paths: 任意数量的路径参数，支持 Path/str/None。
        delay: 延迟清理时间（秒）。防止用户连续发送命令时过快清理文件导致错误。
    """
    await asyncio.sleep(delay)

    seen = set()
    for path in paths:
        if path is None:
            continue

        try:
            file_path = Path(path)
        except Exception:
            continue

        key = str(file_path)
        if key in seen:
            continue
        seen.add(key)

        if not file_path.exists():
            continue

        if not _is_safe_cleanup_target(file_path):
            logger.warning(f"拒绝清理非缓存路径：{file_path}")
            continue

        try:
            if file_path.is_dir():
                shutil.rmtree(file_path)
                logger.debug(f"已清理临时目录：{file_path}")
            else:
                file_path.unlink()
                logger.debug(f"已清理临时文件：{file_path}")
        except Exception as e:
            logger.warning(f"清理路径失败：{e}")


def cleanup_old_cache(cache_dir: Path, max_age_hours: int = 24):
    """
    清理超过指定时间的旧缓存文件

    Args:
        cache_dir: 缓存目录
        max_age_hours: 最大保留时间（小时），默认 24 小时
    """
    try:
        cache_root = _get_cache_root()
        try:
            resolved_cache_dir = cache_dir.resolve(strict=False)
        except Exception:
            logger.warning(f"缓存目录路径无效，跳过清理: {cache_dir}")
            return

        if resolved_cache_dir.parent == resolved_cache_dir:
            logger.warning(f"拒绝清理根目录样式路径: {resolved_cache_dir}")
            return

        if cache_root is not None and resolved_cache_dir != cache_root:
            logger.warning(
                f"缓存目录与插件缓存根不一致，跳过清理: {resolved_cache_dir} (expected: {cache_root})"
            )
            return

        if not cache_dir.exists():
            logger.info(f"缓存目录不存在，跳过清理: {cache_dir}")
            return

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        cleaned_file_count = 0
        cleaned_dir_count = 0
        kept_count = 0
        total_size = 0

        logger.info(f"开始清理缓存，最大保留时间: {max_age_hours} 小时")

        # 遍历缓存目录中的一级子项（文件与目录）
        for target_path in cache_dir.iterdir():
            try:
                if not _is_safe_cleanup_target(target_path):
                    logger.warning(f"跳过非安全缓存路径: {target_path}")
                    continue

                if target_path.is_symlink():
                    logger.warning(f"跳过符号链接路径: {target_path}")
                    continue

                if target_path.is_file():
                    file_age = current_time - target_path.stat().st_mtime
                    file_age_hours = file_age / 3600
                    if file_age > max_age_seconds:
                        file_size = target_path.stat().st_size
                        target_path.unlink()
                        cleaned_file_count += 1
                        total_size += file_size
                        logger.info(
                            f"清理过期缓存文件: {target_path.name} "
                            f"(已存在 {file_age_hours:.1f} 小时，超过 {max_age_hours} 小时)"
                        )
                    else:
                        kept_count += 1
                        logger.debug(
                            f"保留缓存文件: {target_path.name} "
                            f"(已存在 {file_age_hours:.1f} 小时，未超过 {max_age_hours} 小时)"
                        )
                    continue

                if target_path.is_dir():
                    # 目录使用“目录树内最新修改时间”判断是否过期，避免误删仍在更新中的子内容。
                    latest_mtime = target_path.stat().st_mtime
                    dir_size = 0
                    for sub in target_path.rglob('*'):
                        try:
                            if sub.is_symlink():
                                continue
                            sub_stat = sub.stat()
                            latest_mtime = max(latest_mtime, sub_stat.st_mtime)
                            if sub.is_file():
                                dir_size += sub_stat.st_size
                        except Exception:
                            continue

                    dir_age = current_time - latest_mtime
                    dir_age_hours = dir_age / 3600
                    if dir_age > max_age_seconds:
                        shutil.rmtree(target_path)
                        cleaned_dir_count += 1
                        total_size += dir_size
                        logger.info(
                            f"清理过期缓存目录: {target_path.name} "
                            f"(最新修改距今 {dir_age_hours:.1f} 小时，超过 {max_age_hours} 小时)"
                        )
                    else:
                        kept_count += 1
                        logger.debug(
                            f"保留缓存目录: {target_path.name} "
                            f"(最新修改距今 {dir_age_hours:.1f} 小时，未超过 {max_age_hours} 小时)"
                        )
                    continue

                logger.debug(f"跳过未知路径类型: {target_path}")

            except Exception as e:
                logger.warning(f"清理路径 {target_path.name} 时出错: {e}")

        total_cleaned = cleaned_file_count + cleaned_dir_count
        if total_cleaned > 0:
            logger.info(
                f"缓存清理完成: 删除 {cleaned_file_count} 个文件、{cleaned_dir_count} 个目录，"
                f"保留 {kept_count} 个路径，释放 {total_size/1024/1024:.2f} MB 空间"
            )
        else:
            logger.info(f"缓存清理完成: 没有发现过期路径，保留 {kept_count} 个路径")

    except Exception as e:
        logger.error(f"清理缓存目录时发生错误: {e}")