from __future__ import annotations

import asyncio
import json
import unittest

from astrbot_plugin_dududa_core.adapters.review import AstrBotReplyReviewer
from astrbot_plugin_reply_review.policy import (
    ConservativeReviewPolicy,
    ReviewPolicyConfig,
)


class FakeProvider:
    def __init__(self, payload: str | None, *, delay: float = 0.0, raise_exc: bool = False):
        self.payload = payload
        self.delay = delay
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_exc:
            raise RuntimeError("provider down")
        return _FakeResponse(self.payload)


class _FakeResponse:
    def __init__(self, completion_text: str | None):
        self.completion_text = completion_text


class ReviewPolicyContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.policy = ConservativeReviewPolicy(
            ReviewPolicyConfig(enabled=True, min_chars=2, max_chars=2_000)
        )

    async def test_keep_decision_preserves_draft(self) -> None:
        provider = FakeProvider(json.dumps({"decision": "keep", "certain": False, "revised_text": None}))
        reviewer = AstrBotReplyReviewer(lambda: provider, self.policy)
        resolution = await reviewer.review("今天天气不错", "你好")
        self.assertFalse(resolution.revised)
        self.assertEqual(resolution.text, "今天天气不错")
        self.assertEqual(resolution.reason, "review_keep")

    async def test_revise_decision_replaces_draft(self) -> None:
        provider = FakeProvider(
            json.dumps(
                {"decision": "revise", "certain": True, "revised_text": "改好的回复"},
                ensure_ascii=False,
            )
        )
        reviewer = AstrBotReplyReviewer(lambda: provider, self.policy)
        resolution = await reviewer.review("乱七八糟的草稿", "上下文")
        self.assertTrue(resolution.revised)
        self.assertEqual(resolution.text, "改好的回复")

    async def test_uncertain_keeps_draft(self) -> None:
        provider = FakeProvider(json.dumps({"decision": "uncertain", "certain": False, "revised_text": None}))
        reviewer = AstrBotReplyReviewer(lambda: provider, self.policy)
        resolution = await reviewer.review("草稿", "上下文")
        self.assertFalse(resolution.revised)
        self.assertEqual(resolution.reason, "review_uncertain")

    async def test_malformed_response_keeps_draft(self) -> None:
        provider = FakeProvider("不是 JSON")
        reviewer = AstrBotReplyReviewer(lambda: provider, self.policy)
        resolution = await reviewer.review("草稿", "上下文")
        self.assertFalse(resolution.revised)
        self.assertEqual(resolution.reason, "review_malformed")

    async def test_provider_exception_keeps_draft(self) -> None:
        provider = FakeProvider(None, raise_exc=True)
        reviewer = AstrBotReplyReviewer(lambda: provider, self.policy)
        resolution = await reviewer.review("草稿", "上下文")
        self.assertFalse(resolution.revised)
        self.assertEqual(resolution.reason, "review_failed")

    async def test_missing_provider_keeps_draft(self) -> None:
        reviewer = AstrBotReplyReviewer(lambda: None, self.policy)
        resolution = await reviewer.review("草稿", "上下文")
        self.assertFalse(resolution.revised)
        self.assertEqual(resolution.reason, "review_provider_unavailable")

    async def test_timeout_keeps_draft(self) -> None:
        provider = FakeProvider(
            json.dumps({"decision": "keep", "certain": False, "revised_text": None}),
            delay=0.5,
        )
        reviewer = AstrBotReplyReviewer(lambda: provider, self.policy, timeout_seconds=0.05)
        resolution = await reviewer.review("草稿", "上下文")
        self.assertFalse(resolution.revised)
        self.assertEqual(resolution.reason, "review_failed")

    async def test_short_draft_skips_provider_call(self) -> None:
        provider = FakeProvider("")
        short_policy = ConservativeReviewPolicy(
            ReviewPolicyConfig(enabled=True, min_chars=6, max_chars=2_000)
        )
        reviewer = AstrBotReplyReviewer(lambda: provider, short_policy)
        resolution = await reviewer.review("短", "上下文")
        self.assertFalse(resolution.revised)
        self.assertEqual(resolution.reason, "below_minimum_length")
        self.assertEqual(len(provider.calls), 0)

    async def test_prompt_includes_context_and_draft(self) -> None:
        provider = FakeProvider(json.dumps({"decision": "keep", "certain": False, "revised_text": None}))
        reviewer = AstrBotReplyReviewer(lambda: provider, self.policy)
        await reviewer.review("草稿回复", "用户说了什么")
        prompt = provider.calls[0]["prompt"]
        self.assertIn("草稿回复", prompt)
        self.assertIn("用户说了什么", prompt)


if __name__ == "__main__":
    unittest.main()
