import re
from nonebot.log import logger

_PYPI_URL = "https://pypi.org/pypi/nonebot-plugin-osumania-toolkit/json"
_GITHUB_API_URL = "https://api.github.com/repos/LeoBlackMT/nonebot-plugin-osumania-toolkit/releases/latest"

def _parse_version(version_str: str) -> tuple[int, ...] | None:
    """解析版本号字符串为可比较的元组。兼容 '1.0.4' 与 'v1.0.4' 格式。"""
    cleaned = version_str.strip().lstrip("vV")
    parts = re.split(r"[.\-]", cleaned)
    try:
        return tuple(int(p) for p in parts[:3])
    except ValueError:
        return None

def _compare_versions(local: str, remote: str) -> int:
    """比较两个版本号。返回 >0 表示 remote 更新，0 相同，<0 表示 local 更新。"""
    local_tuple = _parse_version(local)
    remote_tuple = _parse_version(remote)
    if local_tuple is None or remote_tuple is None:
        return 0
    # Pad to equal length
    max_len = max(len(local_tuple), len(remote_tuple))
    lt = local_tuple + (0,) * (max_len - len(local_tuple))
    rt = remote_tuple + (0,) * (max_len - len(remote_tuple))
    for l, r in zip(lt, rt):
        if r > l:
            return 1
        if r < l:
            return -1
    return 0

async def _check_pypi_version() -> str | None:
    """从 PyPI 获取最新版本号。失败返回 None。"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(_PYPI_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return str(data.get("info", {}).get("version", "")).strip() or None
    except Exception:
        pass
    return None

async def _check_github_latest_tag() -> str | None:
    """从 GitHub Releases 获取最新 tag。失败返回 None。"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(_GITHUB_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tag = str(data.get("tag_name", "")).strip()
                    return tag if tag.startswith("v") or tag.startswith("V") else None
    except Exception:
        pass
    return None

async def check_update(version: str) -> None:
    """检查更新并通过 logger.info 输出中文结果。"""
    remote_version: str | None = None
    source_name: str = ""

    # 优先 PyPI
    remote_version = await _check_pypi_version()
    if remote_version:
        source_name = "PyPI"

    # 回退 GitHub
    if not remote_version:
        remote_version = await _check_github_latest_tag()
        if remote_version:
            source_name = "GitHub Releases"

    if not remote_version:
        logger.warning("osumania_toolkit 更新检查失败：无法连接到 PyPI 或 GitHub，请检查网络。")
        return

    cmp = _compare_versions(version, remote_version)

    if cmp > 0:
        logger.warning(
            f"osumania_toolkit 发现新版本！"
            f"当前版本：v{version}，最新版本：{remote_version}（{source_name}）。"
        )
    elif cmp < 0:
        logger.info(
            f"osumania_toolkit 当前版本 v{version} 比 {source_name} 最新版本 {remote_version} 更高，"
            f"可能正在使用开发版。"
        )
    else:
        logger.info(f"osumania_toolkit 已是最新版本 v{version}。")

