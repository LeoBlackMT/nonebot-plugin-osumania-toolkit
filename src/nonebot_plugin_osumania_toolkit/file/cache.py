"""Cache directory singleton — avoids circular imports from package __init__.py."""
from nonebot import require

require("nonebot_plugin_localstore")
from nonebot_plugin_localstore import get_plugin_cache_dir

CACHE_DIR = get_plugin_cache_dir()
