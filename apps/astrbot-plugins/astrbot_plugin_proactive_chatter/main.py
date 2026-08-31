from __future__ import annotations

from astrbot.api import logger
from astrbot.api.star import Context, Star, register

from .policy import proactive_context_skip_reason


@register(
    "astrbot_plugin_proactive_chatter",
    "mmdustc",
    "嘟嘟哒 2.0 主动搭话上下文策略扩展",
    "0.2.0",
)
class ProactiveChatterPolicyExtension(Star):
    """Expose a side-effect-free policy extension to Dududa 2.0."""

    policy_name = "social.proactive_talk.context_filter"
    evaluate = staticmethod(proactive_context_skip_reason)

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        logger.info("Dududa 2.0 proactive context policy extension loaded")
