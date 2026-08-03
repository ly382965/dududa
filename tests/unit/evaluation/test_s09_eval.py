from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from dududa.contracts.canonical import canonical_digest
from dududa.evaluation.s09 import check_s09_bundle, run_s09_eval


ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "evals" / "perception-tiering" / "v1"


class S09SyntheticEvalTests(unittest.TestCase):
    def test_committed_bundle_is_complete_cluster_safe_and_honest(self) -> None:
        manifest = json.loads(
            (BUNDLE / "dataset-manifest.json").read_text(encoding="utf-8")
        )
        split = json.loads((BUNDLE / "split-manifest.json").read_text(encoding="utf-8"))
        plan = json.loads((BUNDLE / "eval-plan.json").read_text(encoding="utf-8"))
        report = run_s09_eval(BUNDLE)

        self.assertEqual(manifest["case_count"], 320)
        self.assertEqual(manifest["template_count"], 32)
        self.assertEqual(manifest["label_basis"], "policy_gold")
        self.assertFalse(manifest["human_review_complete"])
        self.assertEqual(
            len(split["case_ids"]["development"]),
            80,
        )
        self.assertEqual(len(split["case_ids"]["test"]), 240)
        self.assertTrue(report["technical_pass"])
        self.assertFalse(report["release_ready"])
        self.assertFalse(report["empirical_minimum_tier_claimed"])
        self.assertTrue(report["order_reproducible"])
        self.assertEqual(
            report["hard_policy_violations"]["violation_event_count"],
            0,
        )
        self.assertEqual(report["policy_under_selection"]["count"], 0)
        self.assertEqual(report["policy_unexpected_opus"]["count"], 0)
        self.assertEqual(report["independent_cluster_count"], 32)
        self.assertEqual(report["unique_text_count"], 300)
        self.assertEqual(report["material_case_profile_count"], 320)
        self.assertEqual(report["dataset_digest"], manifest["dataset_digest"])
        self.assertEqual(report["split_digest"], split["split_digest"])
        self.assertEqual(report["plan_digest"], plan["plan_digest"])

    def test_committed_bundle_matches_deterministic_generator(self) -> None:
        check_s09_bundle(BUNDLE)

    def test_variants_are_material_but_clustered_for_statistics(self) -> None:
        cases = [
            json.loads(line)
            for line in (BUNDLE / "cases.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        by_template: dict[str, set[str]] = {}
        for case in cases:
            template = case["cluster_ids"]["template_family"]
            by_template.setdefault(template, set()).add(
                case["provenance"]["variant_text_digest"]
            )

        self.assertEqual(len(by_template), 32)
        self.assertTrue(all(len(values) == 10 for values in by_template.values()))
        report = run_s09_eval(BUNDLE)
        cross_scope = report["hard_policy_gates"]["no_cross_scope_reference"]
        self.assertEqual(cross_scope["applicable_case_count"], 10)
        self.assertEqual(cross_scope["applicable_independent_cluster_count"], 1)
        self.assertAlmostEqual(
            float(cross_scope["one_sided_95_percent_upper_if_zero"]),
            0.95,
        )

    def test_runner_rejects_extra_fields_and_unbound_split(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dududa-s09-tamper-") as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE, copied)
            case_path = copied / "cases.jsonl"
            records = [
                json.loads(line)
                for line in case_path.read_text(encoding="utf-8").splitlines()
            ]
            records[0]["raw_qq_id"] = "synthetic-forbidden-field"
            payload = {
                key: value for key, value in records[0].items() if key != "case_digest"
            }
            records[0]["case_digest"] = str(
                canonical_digest(payload, domain="eval:perception-tiering-case:v1")
            )
            case_path.write_text(
                "".join(
                    json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
                    for item in records
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                run_s09_eval(copied)

        with tempfile.TemporaryDirectory(prefix="dududa-s09-split-") as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(BUNDLE, copied)
            split_path = copied / "split-manifest.json"
            split = json.loads(split_path.read_text(encoding="utf-8"))
            moved = split["case_ids"]["test"].pop()
            split["case_ids"]["development"].append(moved)
            payload = {
                key: value for key, value in split.items() if key != "split_digest"
            }
            split["split_digest"] = str(
                canonical_digest(payload, domain="eval:perception-tiering-split:v1")
            )
            split_path.write_text(
                json.dumps(split, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                run_s09_eval(copied)


if __name__ == "__main__":
    unittest.main()
