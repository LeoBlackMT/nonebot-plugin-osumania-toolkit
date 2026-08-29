"""jinja2 Environment 缓存：避免每次渲染重复解析/编译模板。

Environment 复用后，jinja2 的模板 LRU 缓存生效（模板内容不变时命中缓存，
不再重复 parse/compile）。auto_reload 保持 jinja2 默认（True）：模板文件被
替换时按 mtime 失效并重新编译，因此 nb 运行时替换模板文件仍可生效。
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_ENVS: dict[str, Environment] = {}


def get_template_env(template_dir: Path) -> Environment:
    """返回按目录缓存的 jinja2 Environment（模板编译缓存随实例生效）。"""
    key = str(template_dir)
    env = _TEMPLATE_ENVS.get(key)
    if env is None:
        env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            enable_async=True,
        )
        _TEMPLATE_ENVS[key] = env
    return env