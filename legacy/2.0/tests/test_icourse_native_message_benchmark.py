from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from ops.cli.run_icourse_native_message_benchmark import (
    DEFAULT_CASES,
    BenchmarkCase,
    NativeShapeEvent,
    extract_answer_profile,
    extract_delivery,
    extract_perception_context,
    finalize_summary,
    parse_case_selection,
    parse_cases,
    render_report,
)


class ICourseNativeMessageBenchmarkTests(unittest.TestCase):
    def test_fixture_has_75_continuous_questions(self) -> None:
        cases = parse_cases(DEFAULT_CASES)

        self.assertEqual([item.case_id for item in cases], list(range(1, 76)))
        self.assertTrue(all(item.question and item.expected for item in cases))

    def test_native_shape_contains_onebot_at_and_text_segments(self) -> None:
        event = NativeShapeEvent(
            BenchmarkCase(1, "title", "查询评课社区吴天", "rubric")
        )

        self.assertEqual(event.get_message_type(), "group")
        self.assertEqual(
            [type(item).__name__ for item in event.get_messages()], ["At", "Plain"]
        )
        self.assertEqual(
            [item["type"] for item in event.message_obj.raw_message["message"]],
            ["at", "text"],
        )
        self.assertEqual(event.message_str, "查询评课社区吴天")
        self.assertIsInstance(event.message_obj.raw_message["self_id"], int)
        self.assertEqual(event.message_obj.raw_message["sub_type"], "normal")
        self.assertEqual(event.message_obj.raw_message["sender"]["role"], "member")

    def test_delivery_extraction_preserves_plain_and_forward_text(self) -> None:
        plain = extract_delivery([[("plain", "短回答")]])
        forward = extract_delivery(
            [
                [
                    (
                        "nodes",
                        [
                            ("node", "第一段", "bot", "bot"),
                            ("node", "第二段", "bot", "bot"),
                        ],
                    )
                ]
            ]
        )

        self.assertEqual(plain, {"shape": "plain", "part_count": 1, "text": "短回答"})
        self.assertEqual(forward["shape"], "forward")
        self.assertEqual(forward["part_count"], 2)
        self.assertEqual(forward["text"], "第一段\n\n第二段")

    def test_case_selection_and_profile_extraction(self) -> None:
        self.assertEqual(
            parse_case_selection("1,4,67-69"), frozenset({1, 4, 67, 68, 69})
        )
        self.assertEqual(extract_answer_profile('{"selected_profile":"long"}'), "long")

    def test_perception_context_extraction(self) -> None:
        prompt = (
            "[DUDUDA_USER_INPUT]\ncontext_json:\n"
            '{"schema_version":1,"messages":[]}\n[/DUDUDA_USER_INPUT]'
        )

        self.assertEqual(
            extract_perception_context(prompt),
            {"schema_version": 1, "messages": []},
        )

    def test_report_describes_connector_shape_and_review_boundary(self) -> None:
        records = [
            {
                "case_id": 1,
                "title": "title",
                "question": "question",
                "runtime_action": "canary_completed",
                "runtime_diagnostics": {"runtime_phase": "completed"},
                "model_calls": [],
                "mcp_calls": [],
                "delivery": {"shape": "plain", "part_count": 1, "text": "runtime"},
                "fake_send_calls": 1,
                "review": {
                    "verdict": "pass",
                    "passed": True,
                    "complete": True,
                    "score": 1,
                    "issues": [],
                    "final_answer": "reviewed",
                },
            },
            {
                "case_id": 2,
                "title": "title",
                "question": "question",
                "runtime_action": "failed",
                "runtime_diagnostics": {"runtime_phase": "failed"},
                "model_calls": [],
                "mcp_calls": [],
                "delivery": {"shape": "none", "part_count": 0, "text": ""},
                "fake_send_calls": 0,
                "review": {
                    "verdict": "blocked",
                    "passed": False,
                    "complete": False,
                    "score": 99,
                    "issues": ["missing evidence"],
                    "final_answer": "clarification",
                },
            },
        ]
        result = finalize_summary({"records": records}, time.perf_counter())

        self.assertEqual(result["summary"]["review_complete"], {"true": 1, "false": 1})
        self.assertEqual(result["summary"]["bridge_completed"], 1)
        self.assertEqual(result["summary"]["runtime_completed"], 1)
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "report.md"
            render_report(result, report_path)
            report = report_path.read_text(encoding="utf-8")

        self.assertIn("AstrBot Connector 接口形状模拟", report)
        self.assertIn("WebSocket 收包、OneBot 帧反序列化和 dispatcher", report)
        self.assertIn("`complete=true` 1；`complete=false` 1", report)
        self.assertIn("`final_answer` 是该轮审校稿", report)
        self.assertIn("修订稿没有重新进入 Runtime", report)
        self.assertNotIn("得分 `", report)

    def test_report_separates_host_ingress_and_targeted_followup(self) -> None:
        result = {
            "summary": {
                "case_count": 1,
                "bridge_completed": 1,
                "runtime_completed": 1,
                "runtime_answered": 1,
                "final_answered": 1,
                "mcp_call_count": 1,
                "fake_send_count": 1,
                "runtime_model_calls": 2,
                "review_calls": 1,
                "health_probe_calls": 3,
                "direct_models": {"gpt-5.6-terra": 1},
                "answer_profiles": {"long": 1},
                "delivery_shapes": {"forward": 1},
                "review_verdicts": {"revised": 1},
                "review_complete": {"true": 1, "false": 0},
                "elapsed_ms": 60_000,
            },
            "targeted_followup": {
                "case_ids": [4],
                "elapsed_ms": 30_000,
                "runtime_model_calls": 2,
                "review_calls": 1,
                "health_probe_calls": 3,
            },
            "host_ingress_contract": {
                "input_count": 75,
                "native_event_count": 75,
                "request_factory_count": 75,
                "outbound_onebot_actions": 0,
                "order_probe": {"input": [1, 2, 3], "observed": [2, 3, 1]},
            },
            "records": [
                {
                    "case_id": 4,
                    "title": "title",
                    "question": "question",
                    "runtime_action": "canary_completed",
                    "model_calls": [
                        {
                            "role": "direct_chat",
                            "requested_model": "gpt-5.6-terra",
                            "reasoning_effort": "low",
                            "answer_profile": "long",
                        }
                    ],
                    "mcp_calls": [
                        {"arguments": {"operation": "review", "query": "吴天"}}
                    ],
                    "delivery": {"shape": "forward", "part_count": 2, "text": "draft"},
                    "editorial_adjustments": ["清理内部术语"],
                    "human_final_audit": {
                        "grounded": True,
                        "complete": False,
                        "reason": "原查询没有拿到完整结果。",
                        "final_answer": "human answer",
                    },
                    "review": {
                        "verdict": "revised",
                        "passed": False,
                        "complete": True,
                        "issues": [],
                        "final_answer": "answer",
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "report.md"
            render_report(result, report_path)
            report = report_path.read_text(encoding="utf-8")

        self.assertIn("AstrBot 宿主入口补充契约", report)
        self.assertIn("`[1, 2, 3]`，实际入队 `[2, 3, 1]`", report)
        self.assertIn("其余 71 题未重复调用模型", report)
        self.assertIn("全过程共发生 6 次业务链调用和 6 次健康探测", report)
        self.assertIn("最终审校答案（人工终审）", report)
        self.assertIn("human answer", report)
        self.assertIn("最终完整 0，未完整 1", report)


if __name__ == "__main__":
    unittest.main()
