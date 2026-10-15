from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from dududa.evaluation.response_profile import (
    check_response_profile_bundle,
    run_response_profile_eval,
)

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "evals" / "response-profile" / "v1"


class ResponseProfileEvalTests(unittest.TestCase):
    def test_committed_bundle_is_reproducible_and_honest(self) -> None:
        report = check_response_profile_bundle(BUNDLE)

        self.assertTrue(report["technical_pass"])
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["dataset_kind"], "synthetic")
        self.assertEqual(report["quality_claim"], "mechanical_contract_only")
        self.assertEqual(report["matrix_cell_count"], 9)
        self.assertEqual(report["cross_two_profile_error_count"], 0)
        self.assertEqual(report["hard_limit_mismatch_count"], 0)
        self.assertTrue(report["order_reproducible"])
        self.assertFalse(report["human_review_complete"])
        self.assertFalse(report["real_chinese_quality_claimed"])
        self.assertFalse(report["persona_style_quality_claimed"])
        self.assertFalse(report["provider_tokenizer_equivalence_claimed"])
        self.assertFalse(report["pilot_budgets_calibrated"])
        self.assertFalse(report["network_allowed"])
        self.assertEqual(report["real_model_call_count"], 0)
        self.assertEqual(report["user_data_record_count"], 0)

    def test_tampered_case_and_report_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dududa-profile-case-") as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(BUNDLE, copied)
            path = copied / "cases.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["cases"][0]["text"] = "tampered"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                run_response_profile_eval(copied)

        with tempfile.TemporaryDirectory(prefix="dududa-profile-report-") as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(BUNDLE, copied)
            path = copied / "report.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["technical_pass"] = False
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                check_response_profile_bundle(copied)

    def test_duplicate_key_and_non_finite_json_fail_closed(self) -> None:
        for replacement in (
            '"schema_version": 1, "schema_version": 1,',
            '"schema_version": NaN,',
        ):
            with (
                self.subTest(replacement=replacement),
                tempfile.TemporaryDirectory(prefix="dududa-profile-json-") as temp,
            ):
                copied = Path(temp) / "bundle"
                shutil.copytree(BUNDLE, copied)
                path = copied / "manifest.json"
                text = path.read_text(encoding="utf-8")
                path.write_text(
                    text.replace('"schema_version": 1,', replacement, 1),
                    encoding="utf-8",
                )
                with self.assertRaises(RuntimeError):
                    run_response_profile_eval(copied)


if __name__ == "__main__":
    unittest.main()
