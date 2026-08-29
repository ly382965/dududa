from astrbot.api import logger
from astrbot.api.star import Context, Star, register


@register(
    "astrbot_plugin_ustc_shuttle",
    "mmdustc",
    "为 Dududa 2.0 提供版本化静态校车查询，不独立处理消息",
    "2.0.0",
)
class UstcShuttlePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        logger.info("USTC Shuttle local capability plugin loaded")
