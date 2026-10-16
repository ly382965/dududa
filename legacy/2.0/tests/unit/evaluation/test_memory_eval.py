from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from dududa.evaluation.memory import (
    check_memory_retrieval_bundle,
    run_memory_retrieval_eval,
)

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "evals" / "memory-retrieval" / "v1"


class MemoryRetrievalEvalTests(unittest.TestCase):
    def test_committed_bundle_is_reproducible_safe_and_honest(self) -> None:
        report = check_memory_retrieval_bundle(BUNDLE)

        self.assertTrue(report["technical_pass"])
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["dataset_kind"], "synthetic")
        self.assertFalse(report["human_review_complete"])
        self.assertFalse(report["real_chinese_quality_claimed"])
        self.assertEqual(report["network_call_count"], 0)
        self.assertEqual(report["real_model_call_count"], 0)
        self.assertEqual(report["user_data_record_count"], 0)
        self.assertTrue(report["m0_zero_calls"])
        self.assertTrue(report["same_fixture_generation"])
        self.assertTrue(report["order_reproducible"])
        self.assertTrue(report["lexical_subset_comparison"]["m2_strictly_better"])
        self.assertEqual(
            report["degraded_case_ids"]["cjk_bm25"],
            ["single-han"],
        )
        self.assertEqual(
            report["metrics"]["no_memory"]["recall_at_k"]["value"],
            "0.000000000000",
        )
        self.assertEqual(
            report["metrics"]["cjk_bm25"]["recall_at_k"]["value"],
            "1.000000000000",
        )
        for strategy in report["safety"].values():
            for category in strategy.values():
                self.assertGreater(category["opportunity_count"], 0)
                self.assertGreater(category["applicable_case_count"], 0)
                self.assertEqual(category["exposure_event_count"], 0)
                self.assertIsNotNone(
                    category["nominal_one_sided_95_percent_upper_if_zero"]
                )

    def test_tampered_input_and_report_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dududa-memory-eval-tamper-") as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(BUNDLE, copied)
            records_path = copied / "records.json"
            records = json.loads(records_path.read_text(encoding="utf-8"))
            records["records"][0]["content"] = "tampered"
            records_path.write_text(
                json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                run_memory_retrieval_eval(copied)

        with tempfile.TemporaryDirectory(prefix="dududa-memory-report-tamper-") as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(BUNDLE, copied)
            report_path = copied / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["technical_pass"] = False
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                check_memory_retrieval_bundle(copied)

    def test_duplicate_json_key_and_non_finite_number_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dududa-memory-eval-json-") as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(BUNDLE, copied)
            manifest_path = copied / "manifest.json"
            text = manifest_path.read_text(encoding="utf-8")
            manifest_path.write_text(
                text.replace(
                    '  "schema_version": 1,',
                    '  "schema_version": 1,\n  "schema_version": 1,',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                run_memory_retrieval_eval(copied)

        with tempfile.TemporaryDirectory(prefix="dududa-memory-eval-nan-") as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(BUNDLE, copied)
            manifest_path = copied / "manifest.json"
            text = manifest_path.read_text(encoding="utf-8")
            manifest_path.write_text(
                text.replace('"k": 2', '"k": NaN', 1),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                run_memory_retrieval_eval(copied)


if __name__ == "__main__":
    unittest.main()
