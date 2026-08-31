from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from astrbot_plugin_reply_review import (
    ConservativeReviewPolicy,
    ReviewCandidate,
    ReviewComponentKind,
    ReviewEligibility,
    ReviewPolicyConfig,
    ReviewSourceKind,
)

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "apps" / "astrbot-plugins" / "astrbot_plugin_reply_review"


class ReplyReviewPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ConservativeReviewPolicy(
            ReviewPolicyConfig(enabled=True, min_chars=2, max_chars=80)
        )

    def test_structured_fixed_and_empty_outputs_are_never_reviewed(self) -> None:
        cases = (
            (
                ReviewCandidate("配图", component_kinds=(ReviewComponentKind.IMAGE,)),
                ReviewEligibility.IMAGE_OUTPUT,
            ),
            (
                ReviewCandidate(
                    "合并转发",
                    component_kinds=(ReviewComponentKind.MERGED_FORWARD,),
                ),
                ReviewEligibility.MERGED_FORWARD_OUTPUT,
            ),
            (
                ReviewCandidate("结构化", component_kinds=(ReviewComponentKind.OTHER,)),
                ReviewEligibility.STRUCTURED_OUTPUT,
            ),
            (
                ReviewCandidate(
                    "校车查询固定结果",
                    source_kind=ReviewSourceKind.FIXED_PLUGIN_RESULT,
                ),
                ReviewEligibility.FIXED_PLUGIN_RESULT,
            ),
            (ReviewCandidate("  "), ReviewEligibility.EMPTY_TEXT),
        )

        for candidate, expected in cases:
            with self.subTest(expected=expected.value):
                self.assertEqual(self.policy.classify(candidate), expected)
                self.assertIsNone(self.policy.build_request(candidate))

    def test_request_is_conservative_structured_and_side_effect_free(self) -> None:
        candidate = ReviewCandidate(
            "徐云老师更适合想深入算法的同学。",
            context="用户不在意给分，想学习高难算法知识。",
        )

        request = self.policy.build_request(candidate)

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.temperature, 0.0)
        self.assertEqual(request.max_output_tokens, 600)
        self.assertIn("无法确认时选择 uncertain", request.prompt)
        self.assertIn("不得新增、删除或猜测事实", request.prompt)
        self.assertIn(candidate.text, request.prompt)
        self.assertIn(candidate.context, request.prompt)

    def test_failure_or_uncertainty_strictly_preserves_original(self) -> None:
        candidate = ReviewCandidate("原始回答")
        responses = (
            None,
            "",
            "不是 JSON",
            "[]",
            json.dumps(
                {"decision": "keep", "certain": True, "revised_text": None}
            ),
            json.dumps(
                {"decision": "uncertain", "certain": False, "revised_text": None}
            ),
            json.dumps(
                {"decision": "revise", "certain": False, "revised_text": "改写"}
            ),
            json.dumps(
                {"decision": "revise", "certain": True, "revised_text": ""}
            ),
            json.dumps(
                {"decision": "revise", "certain": True, "revised_text": "改" * 81}
            ),
        )

        for response in responses:
            with self.subTest(response=response):
                resolution = self.policy.resolve(candidate, response)
                self.assertEqual(resolution.text, candidate.text)
                self.assertFalse(resolution.revised)

    def test_certain_valid_revision_can_replace_plain_model_draft(self) -> None:
        candidate = ReviewCandidate("这句明显答非所问")
        response = json.dumps(
            {
                "decision": "revise",
                "certain": True,
                "revised_text": "这是根据上下文修正后的回答。",
            },
            ensure_ascii=False,
        )

        resolution = self.policy.resolve(candidate, response)

        self.assertTrue(resolution.revised)
        self.assertEqual(resolution.text, "这是根据上下文修正后的回答。")
        self.assertEqual(resolution.reason, "review_revised")


class ReplyReviewPackagingTests(unittest.TestCase):
    def test_astrbot_entrypoint_has_no_message_hook_or_provider_call(self) -> None:
        source = (PLUGIN / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        plugin = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ReplyReview"
        )

        self.assertIn("adapter_ready = True", source)
        self.assertIn("production_wired = False", source)
        for forbidden in (
            "on_decorating_result",
            "get_using_provider",
            "text_chat",
            "result.chain",
            "Plain",
        ):
            self.assertNotIn(forbidden, source)
        self.assertFalse(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.decorator_list
                for node in plugin.body
            )
        )

    def test_metadata_and_schema_describe_non_production_wiring(self) -> None:
        metadata = (PLUGIN / "metadata.yaml").read_text(encoding="utf-8")
        schema = json.loads((PLUGIN / "_conf_schema.json").read_text(encoding="utf-8"))

        self.assertIn("Dududa 2.0", metadata)
        self.assertIn("不监听消息", metadata)
        self.assertFalse(schema["enabled"]["default"])
        self.assertIn("不会拦截或改写线上消息", schema["enabled"]["hint"])


if __name__ == "__main__":
    unittest.main()
