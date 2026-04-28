import re

from nonebot import get_plugin_config
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Optional
from .cache import CACHE_DIR
from ..config import Config
config = get_plugin_config(Config)

_WINDOWS_RESERVED = re.compile(
    r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)', re.IGNORECASE
)

def safe_filename(filename: str) -> str:
    name = (filename or "").strip().replace("\x00", "")
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    if name in {"", ".", ".."}:
        name = "uploaded_file"
    if _WINDOWS_RESERVED.match(name):
        name = '_' + name
    return name

def _get_cache_root() -> Optional[Path]:
    try:
        return CACHE_DIR.resolve(strict=False)
    except Exception:
        return None

def _get_local_path_from_str(path_str: str) -> Optional[Path]:
    """
    将字符串解析为本地绝对路径。
    支持：
    - 绝对路径（Windows/Unix/UNC）
    - file:// URI
    若无法解析为本地绝对路径则返回 None。
    """
    if not path_str:
        return None

    try:
        if path_str.startswith("file://"):
            parsed = urlparse(path_str)
            if parsed.scheme != "file":
                return None
            # 对于 file:// URI，从 path 中取实际文件路径并反解码
            file_path = unquote(parsed.path or "")
            if not file_path:
                return None
            p = Path(file_path)
        else:
            p = Path(path_str)

        # 仅接受本地绝对路径，避免误删工作目录等相对路径文件
        if not p.is_absolute():
            return None
    except Exception:
        return None

    return p

def _to_local_path(path_or_uri: str) -> Path:
    """
    将可能为 file:// URI 的字符串转换为本地 Path。
    非 file:// 字符串按原样交给 Path 处理。
    """
    if path_or_uri.startswith("file://"):
        parsed = urlparse(path_or_uri)
        path = unquote(parsed.path)
        # 处理类似 file:///C:/path 这种在 Windows 上会多出一个前导斜杠的情况
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return Path(path)
    return Path(path_or_uri)