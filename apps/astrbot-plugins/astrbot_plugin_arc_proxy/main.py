from astrbot.api import logger
from astrbot.api.star import Context, Star, register

PLUGIN_ID = "astrbot_plugin_arc_proxy"
PLUGIN_VERSION = "2.0.0"


@register(
    PLUGIN_ID,
    "mmdustc",
    "为 Dududa 2.0 Runtime 提供本地 Arcaea B50 渲染资产",
    PLUGIN_VERSION,
)
class ArcB50AssetPlugin(Star):
    """Loadable asset only; Core owns policy, invocation and delivery."""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.enabled = bool((config or {}).get("enabled", False))
        logger.info(
            "%s loaded: enabled=%s handlers=0 external_transport=none",
            PLUGIN_ID,
            self.enabled,
        )
