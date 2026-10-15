from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from jsonschema import Draft202012Validator

from dududa.errors import DududaError
from dududa.evaluation.semantic_v2 import (
    check_semantic_schema_pilot,
    run_semantic_schema_pilot,
)


ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "evals" / "perception-semantic" / "v2"


def validate_draft_2020_12(schema: object, instance: object) -> None:
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)


class SemanticV2SchemaPilotTests(unittest.TestCase):
    def test_committed_schema_only_bundle_is_reproducible_and_honest(self) -> None:
        report = check_semantic_schema_pilot(
            BUNDLE,
            validate_schema=validate_draft_2020_12,
        )

        self.assertTrue(report["technical_pass"])
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["quality_claim"], "schema_only")
        self.assertFalse(report["real_chinese_quality_claimed"])
        self.assertFalse(report["human_review_complete"])
        self.assertEqual(report["real_model_call_count"], 0)
        self.assertEqual(report["user_data_record_count"], 0)
        self.assertGreaterEqual(report["normalized_input_case_count"], 1)
        self.assertEqual(set(report["turn_counts"]), {"3", "6", "12"})
        self.assertTrue(all(report["coverage"].values()))

    def test_tampered_span_digest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dududa-semantic-pilot-") as temp:
            copied = Path(temp) / "v2"
            shutil.copytree(BUNDLE, copied)
            cases_path = copied / "cases.json"
            document = json.loads(cases_path.read_text(encoding="utf-8"))
            document["cases"][0]["projection"]["semantic"]["references"][0][
                "mention_span"
            ]["text_digest"] = "tampered"
            cases_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(DududaError):
                run_semantic_schema_pilot(
                    copied,
                    validate_schema=validate_draft_2020_12,
                )


if __name__ == "__main__":
    unittest.main()
