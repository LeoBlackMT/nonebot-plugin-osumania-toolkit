import asyncio

from nonebot import get_plugin_config, get_driver
from nonebot.plugin import PluginMetadata

from .api.check_update import check_update
from .config import Config
from .file.cleanup import cleanup_old_cache
from .file.cache import CACHE_DIR

from .matcher import *

__plugin_meta__ = PluginMetadata(
    name="osu!mania 工具箱",
    description="提供多种osu!mania高级分析功能和实用工具",
    usage="发送 /omtk 获取帮助信息",
    homepage = "https://github.com/LeoBlackMT/nonebot-plugin-osumania-toolkit",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"}
)

_VERSION = "1.1.0"

config = get_plugin_config(Config)
driver = get_driver()

# 在 Bot 启动时清理旧缓存
@driver.on_startup
async def startup_cleanup():
    """Bot 启动时清理超过指定时间的旧缓存文件"""
    max_age = config.omtk_cache_max_age
    await asyncio.to_thread(cleanup_old_cache, CACHE_DIR, max_age_hours=max_age)

# 在 Bot 启动时异步检查更新
@driver.on_startup
async def startup_update_check():
    """Bot 启动时异步检查更新"""
    asyncio.create_task(check_update(_VERSION))

