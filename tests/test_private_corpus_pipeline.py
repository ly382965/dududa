from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str, filename: str):  # type: ignore[no-untyped-def]
    script = ROOT / "ops" / "cli" / filename
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_script("private_corpus_pipeline", "private_corpus_pipeline.py")
TEACHER = _load_script("private_corpus_teacher", "private_corpus_teacher.py")
STUDENT = _load_script("private_corpus_student", "private_corpus_student.py")
DEMO = _load_script("private_corpus_demo", "private_corpus_demo.py")


class PrivateCorpusPipelineTests(unittest.TestCase):
    def test_html_parser_keeps_messages_after_void_tags(self) -> None:
        parser = MODULE.HtmlMessageParser()
        parser.feed(
            """
            <div class="message other" data-sender-uid="u1" id="msg-m1">
              <span class="sender">A</span><span class="time">2026/08/15 12:00:00</span>
              <span class="text-content">first<img src="private" /></span>
            </div>
            <div class="message other" data-sender-uid="u2" id="msg-m2">
              <span class="sender">B</span><span class="time">2026/08/15 12:01:00</span>
              <span class="text-content">second<br>line</span>
            </div>
            """
        )
        parser.close()

        self.assertEqual([item["id"] for item in parser.messages], ["m1", "m2"])
        self.assertIn("first", parser.messages[0]["text"])
        self.assertIn("second", parser.messages[1]["text"])

    def test_extract_prefers_jsonl_supplements_and_excludes_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            group = input_root / "group_Test_123456_20260815_120000_chunked_jsonl"
            (group / "chunks").mkdir(parents=True)
            self._write_manifest(group / "manifest.json", "group")
            records = [
                self._record("m1", 1_000, "u1", "authoritative"),
                self._record("m2", 2_000, "u2", "second"),
                self._record("m3", 3_000, "u3", "third"),
            ]
            self._write_jsonl(group / "chunks/chunk_0001.jsonl", records)

            zip_path = input_root / "group_Test_123456_20260815_120100_streaming.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                payload = "\n".join(
                    json.dumps(item, ensure_ascii=False)
                    for item in (
                        self._record("m1", 1_000, "u1", "conflicting copy"),
                        self._record("m4", 4_000, "u4", "zip supplement"),
                    )
                )
                archive.writestr("message_batches/batch_000001.jsonl", payload)

            html_path = input_root / "group_Test_123456_20260815_120200.html"
            html_path.write_text(
                """
                <div class="message other" data-sender-uid="u5" id="msg-m5">
                  <span class="sender">Example</span>
                  <span class="time">2026/08/15 12:02:00</span>
                  <span class="text-content">html supplement</span>
                </div>
                """,
                encoding="utf-8",
            )

            friend = input_root / "friend_private_20260815_120000_chunked_jsonl"
            (friend / "chunks").mkdir(parents=True)
            self._write_manifest(friend / "manifest.json", "friend")
            self._write_jsonl(
                friend / "chunks/chunk_0001.jsonl",
                [self._record("private", 1_000, "u9", "must not load")],
            )

            MODULE.inventory(input_root, output_root)
            report = MODULE.extract(input_root, output_root)
            messages = list(MODULE.read_jsonl(output_root / "normalized/messages.jsonl"))

            self.assertEqual(report["unique_messages"], 5)
            self.assertEqual(report["counts"]["duplicate_records"], 1)
            self.assertEqual(report["counts"]["conflict_records"], 1)
            self.assertEqual(report["counts"]["supplement_records"], 2)
            self.assertEqual(report["counts"]["excluded_private_sources"], 1)
            first = next(item for item in messages if item["text"] == "authoritative")
            self.assertEqual(first["source_format"], "directory_jsonl")
            self.assertNotIn("normalized_message_id", first)
            serialized = json.dumps(messages, ensure_ascii=False)
            self.assertNotIn("must not load", serialized)
            self.assertNotIn("123456", serialized)

    def test_windows_are_past_only_and_validate_existing_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            rows = []
            for index in range(1, 7):
                rows.append(
                    {
                        "schema_version": 1,
                        "source_ref": "source-0001",
                        "conversation_ref": "conversation-0001",
                        "message_ref": f"message-{index:08d}",
                        "sender_ref": f"identity-{(index % 3) + 1:06d}",
                        "timestamp_ms": index * 60_000,
                        "seq": str(index),
                        "self_authored": index == 4,
                        "text": f"message {index}",
                        "reply_to_ref": "message-00000001" if index == 6 else None,
                        "reply_unresolved": False,
                        "mention_refs": [],
                        "mention_all": False,
                        "attachment_kinds": [],
                        "source_format": "directory_jsonl",
                        "source_ordinal": index,
                        "recalled": False,
                        "system": False,
                        "conflict_flags": [],
                    }
                )
            MODULE.write_jsonl(output_root / "normalized/messages.jsonl", rows)
            report = MODULE.window(output_root)
            windows = list(MODULE.read_jsonl(output_root / "windows/all.jsonl"))

            self.assertEqual(report["window_count"], 3)
            self.assertNotIn("message-00000004", {row["current_message_ref"] for row in windows})
            final = windows[-1]
            refs = [item["message_ref"] for item in final["messages"]]
            self.assertEqual(refs[-1], final["current_message_ref"])
            self.assertIn("message-00000001", refs)
            timestamps = [item["timestamp_ms"] for item in final["messages"]]
            self.assertEqual(timestamps, sorted(timestamps))
            self.assertTrue(final["perception_context_digest"])
            self.assertEqual(
                final["perception_context"]["messages"][-1]["message_ref"],
                final["current_message_ref"],
            )

    def test_teacher_targets_are_total_unique_windows(self) -> None:
        async def fake_stage(rows, **_kwargs):  # type: ignore[no-untyped-def]
            calls.append(len(rows))
            completed = [
                {
                    "window_id": str(row["window_id"]),
                    "draft": {
                        "decision": {"action": "accept"},
                        "confidence": 0.9,
                        "ambiguities": [],
                    },
                }
                for row in rows
            ]
            return completed, [], {
                "requested": len(rows),
                "completed": len(rows),
                "network_quality_eligible": len(rows),
                "elapsed_seconds": 1.0,
            }

        cases = ((5, [5]), (50, [5, 50]), (240, [5, 50, 240]))
        for target, expected_calls in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                smoke = [
                    {"window_id": f"window-{index:03d}"} for index in range(50)
                ]
                candidate = [
                    {"window_id": f"window-{index:03d}"} for index in range(240)
                ]
                MODULE.write_jsonl(root / "windows/smoke-50.jsonl", smoke)
                MODULE.write_jsonl(root / "windows/candidate-240.jsonl", candidate)
                calls: list[int] = []
                config = TEACHER.TeacherConfig("https://invalid", "terra", "unused")
                with mock.patch.object(TEACHER, "_label_stage", new=fake_stage):
                    report = asyncio.run(
                        TEACHER.label_teacher_batch(
                            root,
                            target=target,
                            config=config,
                        )
                    )
                self.assertEqual(calls, expected_calls)
                self.assertEqual(report["selected_target"], target)
                self.assertEqual(report["unique_completed"], target)
                self.assertEqual(report["target_shortfall"], 0)
                self.assertEqual(report["label_status"], "model_prelabel")

    def test_teacher_smoke_failure_stops_at_five(self) -> None:
        async def failing_stage(rows, **_kwargs):  # type: ignore[no-untyped-def]
            error = TEACHER.TeacherCallError("invalid_teacher_draft")
            return [], [
                TEACHER._review_row(
                    str(rows[0]["window_id"]),
                    stage="compile",
                    error=error,
                )
            ], {
                "requested": len(rows),
                "completed": 0,
                "network_quality_eligible": 0,
                "elapsed_seconds": 1.0,
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            smoke = [{"window_id": f"window-{index:03d}"} for index in range(50)]
            MODULE.write_jsonl(root / "windows/smoke-50.jsonl", smoke)
            config = TEACHER.TeacherConfig("https://invalid", "terra", "unused")
            with mock.patch.object(TEACHER, "_label_stage", new=failing_stage):
                report = asyncio.run(
                    TEACHER.label_teacher_batch(root, target=240, config=config)
                )
            self.assertEqual(report["selected_target"], 5)
            self.assertEqual(report["selection_reason"], "smoke_5_review")
            self.assertEqual(report["halt_reason"], "smoke-5-review")
            self.assertEqual(report["stopped_after_stage"], "smoke-5")

    def test_teacher_capacity_does_not_force_minimum_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "windows").mkdir()
            (root / "windows/candidate-240.jsonl").touch()
            selected, capacity, reason = TEACHER._choose_target(
                root,
                pilot_window_count=50,
                fresh_quality_prelabels=1,
                pilot_elapsed_seconds=500.0,
                total_budget_seconds=900.0,
                reserve_seconds=300.0,
            )
            self.assertEqual(selected, 50)
            self.assertLess(capacity, 240)
            self.assertEqual(reason, "endpoint_capacity_below_240")

            selected, capacity, reason = TEACHER._choose_target(
                root,
                pilot_window_count=50,
                fresh_quality_prelabels=0,
                pilot_elapsed_seconds=0.01,
                total_budget_seconds=900.0,
                reserve_seconds=300.0,
            )
            self.assertEqual((selected, capacity), (50, 50))
            self.assertEqual(reason, "no_fresh_quality_throughput")

    def test_teacher_uses_provider_compatible_schema_without_weakening_local(self) -> None:
        config = TEACHER.TeacherConfig("https://invalid", "terra", "unused")
        body = TEACHER._responses_body({"window_id": "window-1"}, config)
        provider_schema = body["text"]["format"]["schema"]
        provider_json = json.dumps(provider_schema, sort_keys=True)

        self.assertNotIn('"const"', provider_json)
        self.assertNotIn('"uniqueItems"', provider_json)
        self.assertIn('"enum": [1]', provider_json)
        local_properties = TEACHER.TEACHER_DRAFT_SCHEMA["properties"]
        self.assertEqual(local_properties["schema_version"]["const"], 1)
        self.assertTrue(local_properties["speech_acts"]["uniqueItems"])

    def test_single_class_students_train_evaluate_and_predict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            windows = []
            for index in range(6):
                window = self._student_window(index)
                windows.append(window)
                rows.append(
                    {
                        "window": window,
                        "sidecar": {
                            "need_tools": False,
                            "semantic_complexity": "low",
                            "answer_profile": "short",
                        },
                    }
                )
            MODULE.write_jsonl(root / "semantic-v2/silver.jsonl", rows)
            MODULE.write_jsonl(root / "windows/all.jsonl", windows)

            training = STUDENT.train_students(root, seed=23)
            metrics = STUDENT.evaluate_students(root)
            predictions = STUDENT.predict_all(root)

            self.assertEqual(
                set(training["model_kinds"].values()),
                {"constant_dummy_single_training_class"},
            )
            self.assertEqual(metrics["metric_scope"], "held_out_silver_agreement")
            self.assertEqual(predictions["prediction_count"], len(windows))
            self.assertTrue((root / "students/training.json").is_file())
            self.assertTrue((root / "students/prediction-summary.json").is_file())

    def test_demo_recursively_redacts_structured_semantic_text(self) -> None:
        phone = "13800138000"
        email = "demo.private@example.com"
        account = "123456789"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            window = self._student_window(0)
            messages = window["messages"]
            assert isinstance(messages, list)
            messages[0]["text"] = f"联系 {phone} 或 {email}"
            row = {
                "window": window,
                "sidecar": {
                    "need_tools": False,
                    "semantic_complexity": "low",
                    "answer_profile": "short",
                },
                "model_projection_v2": {
                    "topics": [{"label": f"账号 {account}"}],
                    "semantic": {
                        "decision": {"action": "accept", "reason_codes": []},
                        "intents": [],
                        "entities": [
                            {
                                "entity_id": "entity-1",
                                "span": {"surface": phone},
                                "normalized_value": email,
                                "value": account,
                                "evidence_refs": ["message-000"],
                            }
                        ],
                        "references": [],
                    },
                },
                "validation": {"canonical_round_trip": True},
            }
            MODULE.write_jsonl(root / "semantic-v2/silver.jsonl", [row])
            report = DEMO.generate_demo(root, sample_limit=1)
            html = Path(report["demo_path"]).read_text(encoding="utf-8")
            self.assertNotIn(phone, html)
            self.assertNotIn(email, html)
            self.assertNotIn(account, html)
            self.assertIn("[PHONE]", html)
            self.assertIn("[EMAIL]", html)
            self.assertIn("PRIVATE DEVELOPMENT DATA", html)

    def test_demo_previews_existing_static_tier_policy_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            levels = ("low", "medium", "high")
            silver = []
            predictions = []
            for index, level in enumerate(levels):
                window = self._student_window(index)
                silver.append(
                    {
                        "window": window,
                        "sidecar": {
                            "need_tools": False,
                            "semantic_complexity": level,
                            "answer_profile": "short",
                        },
                    }
                )
                predictions.append(
                    {
                        "window_id": window["window_id"],
                        "conversation_ref": window["conversation_ref"],
                        "predictions": {
                            "need_tools": {"label": False, "confidence": 0.99},
                            "semantic_complexity": {
                                "label": level,
                                "confidence": 0.99,
                            },
                            "answer_profile": {
                                "label": "short",
                                "confidence": 0.99,
                            },
                        },
                    }
                )

            MODULE.write_jsonl(root / "semantic-v2/silver.jsonl", silver)
            MODULE.write_jsonl(root / "students/predictions.jsonl", predictions)

            report = DEMO.generate_demo(root, sample_limit=3)
            html = Path(report["demo_path"]).read_text(encoding="utf-8")

            self.assertIn('"selected_tier":"haiku"', html)
            self.assertIn('"selected_tier":"sonnet"', html)
            self.assertIn('"selected_tier":"opus"', html)
            self.assertIn("STATIC TIER OFFLINE PREVIEW", html)
            self.assertIn("离线预览", html)
            self.assertIn("非生产路由", html)

    @staticmethod
    def _record(
        message_id: str, timestamp: int, sender: str, text: str
    ) -> dict[str, object]:
        return {
            "id": message_id,
            "seq": message_id,
            "timestamp": timestamp,
            "sender": {"uid": sender, "uin": "0", "name": "Example"},
            "type": "text",
            "content": {
                "text": text,
                "elements": [{"type": "text", "data": {"text": text}}],
                "mentions": [],
            },
            "recalled": False,
            "system": False,
        }

    @staticmethod
    def _write_manifest(path: Path, chat_type: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "chatInfo": {
                        "type": chat_type,
                        "selfUid": "self-user",
                        "selfUin": "999999",
                    }
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _student_window(index: int) -> dict[str, object]:
        return {
            "window_id": f"window-{index:03d}",
            "conversation_ref": f"conversation-{index:03d}",
            "current_message_ref": f"message-{index:03d}",
            "speaker_count": 1,
            "messages": [
                {
                    "message_ref": f"message-{index:03d}",
                    "sender_ref": f"identity-{index:03d}",
                    "text": f"日常消息 {index}",
                    "reply_to_ref": None,
                    "mention_refs": [],
                    "attachment_kinds": [],
                    "self_authored": False,
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
