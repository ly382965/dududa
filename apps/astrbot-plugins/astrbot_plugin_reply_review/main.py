from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.star import Context, Star, register

from .policy import ConservativeReviewPolicy, ReviewPolicyConfig


@register(
    "astrbot_plugin_reply_review",
    "mmdustc",
    "Dududa 2.0 无副作用回复审校策略资产（尚未接入生产 Runtime）",
    "0.2.0",
)
class ReplyReview(Star):
    """Expose the policy asset without intercepting AstrBot message delivery."""

    adapter_ready = True
    production_wired = False

    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        values = config or {}
        self.policy = ConservativeReviewPolicy(
            ReviewPolicyConfig(
                enabled=bool(values.get("enabled", False)),
                min_chars=int(values.get("min_chars", 2)),
                max_chars=int(values.get("max_chars", 2_000)),
                max_output_tokens=int(values.get("max_output_tokens", 600)),
            )
        )
        logger.info(
            "ReplyReview adapter ready: policy_enabled=%s production_wired=false",
            self.policy.config.enabled,
        )
