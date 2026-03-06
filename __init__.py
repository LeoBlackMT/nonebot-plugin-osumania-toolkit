from nonebot import get_plugin_config, require
from nonebot.plugin import PluginMetadata
require("nonebot_plugin_localstore")

from .matcher import *
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="nonebot_plugin_osumania_toolkit",
    description="a nonebot plugin with some useful osu!mania utilities",
    usage="send /omtk for help",
    homepage = "https://github.com/LeoBlackMT/nonebot_plugin_osumania_toolkit",
    config=Config,
)

config = get_plugin_config(Config)

