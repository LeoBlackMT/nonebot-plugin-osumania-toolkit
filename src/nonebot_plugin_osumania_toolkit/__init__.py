import asyncio

from nonebot import get_plugin_config, get_driver, require
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_plugin_cache_dir
CACHE_DIR = get_plugin_cache_dir()
from .matcher import *
from .config import Config
from .file.file import cleanup_old_cache

__plugin_meta__ = PluginMetadata(
    name="osu!mania 工具箱",
    description="提供多种osu!mania高级分析功能和实用工具",
    usage="发送 /omtk 获取帮助信息",
    homepage = "https://github.com/LeoBlackMT/nonebot-plugin-osumania-toolkit",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"}
)

config = get_plugin_config(Config)

# 获取驱动器
driver = get_driver()

# 在 Bot 启动时清理旧缓存
@driver.on_startup
async def startup_cleanup():
    """Bot 启动时清理超过指定时间的旧缓存文件"""
    max_age = config.omtk_cache_max_age
    await asyncio.to_thread(cleanup_old_cache, CACHE_DIR, max_age_hours=max_age)

