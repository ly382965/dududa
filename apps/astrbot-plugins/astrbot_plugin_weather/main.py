from astrbot.api import logger
from astrbot.api.star import Context, Star, register

PLUGIN_ID = "astrbot_plugin_weather"
PLUGIN_VERSION = "2.0.0"


@register(
    PLUGIN_ID,
    "mmdustc",
    "为 Dududa 2.0 Runtime 提供只读天气数据适配器",
    PLUGIN_VERSION,
)
class WeatherAssetPlugin(Star):
    """Loadable asset only; Dududa 2.0 owns selection, scheduling and output."""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.enabled = bool((config or {}).get("enabled", False))
        logger.info(
            "%s loaded: enabled=%s handlers=0 scheduler=external",
            PLUGIN_ID,
            self.enabled,
        )
