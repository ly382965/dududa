from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from dududa.contracts.canonical import (
    canonical_digest,
    canonical_json_bytes,
    verify_canonical_digest,
)
from dududa.evaluation import suite as suite_module
from dududa.evaluation.suite import (
    EvaluationSuiteError,
    load_suite_catalog,
    run_suite_profile,
)

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "evals" / "suite-v1.json"


def _fake_evidence(root: Path, stream) -> dict[str, object]:
    del root, stream
    return {
        "technical_pass": True,
        "release_ready": False,
        "human_review_complete": False,
        "case_count": 3,
        "input_digest": str(
            canonical_digest({"fixture": True}, domain="eval:test-input:v1")
        ),
        "report_digest": str(
            canonical_digest({"passed": True}, domain="eval:test-report:v1")
        ),
        "user_data_record_count": 0,
    }


class EvaluationSuiteTests(unittest.TestCase):
    def test_catalog_is_strict_registered_and_dimension_complete(self) -> None:
        catalog = load_suite_catalog(CATALOG)

        self.assertEqual(catalog.catalog_id, "dududa-offline-suite-v1")
        self.assertEqual(len(catalog.required_dimensions), 14)
        self.assertEqual(len(catalog.suites), 10)
        self.assertEqual(
            {name for name, _ in catalog.profiles},
            {"committed-bundles", "s18-focused", "ci-python"},
        )

        document = json.loads(CATALOG.read_text(encoding="utf-8"))
        document["suites"][0]["runner_id"] = "arbitrary-callable"
        with tempfile.TemporaryDirectory(prefix="dududa-suite-catalog-") as temporary:
            changed = Path(temporary) / "suite.json"
            changed.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                EvaluationSuiteError,
                "unknown_evaluation_runner",
            ):
                load_suite_catalog(changed)

    def test_catalog_binds_evidence_metadata_and_profile_membership(self) -> None:
        mutations = (
            (
                "revision",
                lambda value: value["suites"][0].__setitem__(
                    "suite_revision", "forged-revision"
                ),
            ),
            (
                "claim",
                lambda value: value["suites"][0].__setitem__(
                    "quality_claim", "production_ready"
                ),
            ),
            (
                "gates",
                lambda value: value["suites"][0].__setitem__("external_gates", []),
            ),
            (
                "profile",
                lambda value: value["profiles"].__setitem__(
                    "committed-bundles", ["perception-tiering-v1"]
                ),
            ),
        )
        with tempfile.TemporaryDirectory(prefix="dududa-suite-binding-") as temporary:
            for label, mutate in mutations:
                with self.subTest(label=label):
                    document = json.loads(CATALOG.read_text(encoding="utf-8"))
                    mutate(document)
                    changed = Path(temporary) / f"{label}.json"
                    changed.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        EvaluationSuiteError,
                        "evaluation_catalog_contract_mismatch",
                    ):
                        load_suite_catalog(changed)

    def test_success_receipt_is_atomic_digest_bound_and_low_sensitivity(self) -> None:
        replacements = {
            runner_id: replace(definition, execute=_fake_evidence)
            for runner_id, definition in suite_module._RUNNERS.items()
        }
        with (
            tempfile.TemporaryDirectory(prefix="dududa-suite-receipt-") as temporary,
            patch.dict(suite_module._RUNNERS, replacements, clear=True),
        ):
            receipt_path = Path(temporary) / "receipt.json"
            receipt = run_suite_profile(
                CATALOG,
                profile_id="committed-bundles",
                receipt_path=receipt_path,
            )
            committed = json.loads(receipt_path.read_text(encoding="utf-8"))

            self.assertEqual(receipt["status"], "passed")
            self.assertRegex(receipt["run_id"], r"^eval-[0-9a-f]{32}$")
            self.assertEqual(
                canonical_json_bytes(committed),
                canonical_json_bytes(receipt),
            )
            self.assertEqual(os.stat(receipt_path).st_mode & 0o777, 0o600)
            unsigned = {
                key: value
                for key, value in committed.items()
                if key != "receipt_digest"
            }
            self.assertTrue(
                verify_canonical_digest(
                    unsigned,
                    committed["receipt_digest"],
                    domain="eval:suite-receipt:v1",
                )
            )
            serialized = receipt_path.read_text(encoding="utf-8")
            for forbidden in (
                "/home/",
                "command",
                "environment",
                "hostname",
                "stdout",
                "stderr",
                "prompt",
                "message_text",
                "group_id",
                "user_id",
            ):
                self.assertNotIn(forbidden, serialized)

    def test_failure_receipt_omits_exception_text_and_stops_the_profile(self) -> None:
        secret = "sk-s18-secret /home/private 123456789"

        def fail(root: Path, stream):
            del root, stream
            raise RuntimeError(secret)

        first_id = "perception-tiering-bundle-v1"
        replacement = replace(suite_module._RUNNERS[first_id], execute=fail)
        with (
            tempfile.TemporaryDirectory(prefix="dududa-suite-failure-") as temporary,
            patch.dict(suite_module._RUNNERS, {first_id: replacement}),
        ):
            receipt_path = Path(temporary) / "receipt.json"
            receipt = run_suite_profile(
                CATALOG,
                profile_id="committed-bundles",
                receipt_path=receipt_path,
            )

            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(len(receipt["results"]), 1)
            self.assertEqual(
                receipt["results"][0]["reason_code"],
                "evaluation_suite_execution_failed",
            )
            self.assertNotIn(secret, receipt_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
