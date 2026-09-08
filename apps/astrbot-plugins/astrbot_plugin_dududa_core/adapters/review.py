from __future__ import annotations

import asyncio
from typing import Any, Callable

try:
    from astrbot_plugin_reply_review.policy import (
        ConservativeReviewPolicy,
        ReviewCandidate,
        ReviewResolution,
    )
except ModuleNotFoundError as exc:
    if exc.name != "astrbot_plugin_reply_review":
        raise
    from data.plugins.astrbot_plugin_reply_review.policy import (
        ConservativeReviewPolicy,
        ReviewCandidate,
        ReviewResolution,
    )


class AstrBotReplyReviewer:
    """Execute the conservative reply review against an AstrBot Provider."""

    def __init__(
        self,
        provider_getter: Callable[[], Any],
        policy: ConservativeReviewPolicy,
        *,
        timeout_seconds: float = 15.0,
        context_char_limit: int = 800,
    ) -> None:
        self._provider_getter = provider_getter
        self._policy = policy
        self._timeout_seconds = timeout_seconds
        self._context_char_limit = context_char_limit

    async def review(self, draft_text: str, context: str = "") -> ReviewResolution:
        candidate = ReviewCandidate(
            text=draft_text,
            context=(context or "")[: self._context_char_limit],
        )
        request = self._policy.build_request(candidate)
        if request is None:
            return ReviewResolution(
                draft_text,
                False,
                self._policy.classify(candidate).value,
            )
        provider = self._provider_getter()
        if provider is None:
            return ReviewResolution(draft_text, False, "review_provider_unavailable")
        try:
            response = await asyncio.wait_for(
                provider.text_chat(
                    prompt=request.prompt,
                    system_prompt=request.system_prompt,
                    request_max_retries=1,
                ),
                timeout=self._timeout_seconds,
            )
            review_text = getattr(response, "completion_text", None)
        except Exception:  # noqa: BLE001 - review must never block delivery
            return ReviewResolution(draft_text, False, "review_failed")
        return self._policy.resolve(candidate, review_text)


__all__ = ["AstrBotReplyReviewer"]
