from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from ops.cli import audit_release_candidate as audit

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "release" / "s19-pilot-slo-v1.json"
SURFACES = ROOT / "configs" / "release" / "legacy-surfaces-v1.json"


def create_s19_inventory_workspace(parent: Path) -> tuple[Path, Path]:
    root = parent / "s19-inventory"
    root.mkdir()
    definitions = root / "legacy-surfaces-v1.json"
    definitions.write_text(SURFACES.read_text(encoding="utf-8"), encoding="utf-8")
    catalog = json.loads(definitions.read_text(encoding="utf-8"))
    patterns: list[str] = []
    for surface in catalog["surfaces"]:
        patterns.extend(surface["patterns"])
        for relative in surface["tracked_paths"]:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"historical {surface['surface_id']}\n", encoding="utf-8")
    (root / "consumer.txt").write_text("\n".join(patterns), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "--all"], cwd=root, check=True)
    return root, definitions


class ReleaseCandidateAuditTests(unittest.TestCase):
    def test_policy_freezes_zero_safety_and_honest_pilot_defaults(self) -> None:
        policy, digest = audit.load_slo_policy(POLICY)

        self.assertEqual(policy["evidence_class"], "pilot_default")
        self.assertFalse(policy["s23_ready"])
        self.assertTrue(all(value == 0 for value in policy["safety_maximums"].values()))
        self.assertEqual(
            {
                profile: value["max_visible_tokens"]
                for profile, value in policy["response_profiles"].items()
            },
            audit.PROFILE_TOKEN_LIMITS,
        )
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")

        document = json.loads(POLICY.read_text(encoding="utf-8"))
        mutations = (
            (
                "safety",
                lambda value: value["safety_maximums"].__setitem__("wrong_target", 1),
            ),
            (
                "tokens",
                lambda value: value["response_profiles"]["short"].__setitem__(
                    "max_visible_tokens", 129
                ),
            ),
            ("claim", lambda value: value.__setitem__("s23_ready", True)),
            (
                "external",
                lambda value: value.__setitem__("external_pending", ["provider_cost"]),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                changed = deepcopy(document)
                mutate(changed)
                with self.assertRaises(audit.CandidateAuditError):
                    audit.validate_slo_policy(changed)

    def test_inventory_is_tracked_digest_bound_and_keeps_legacy_audit_separate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="dududa-s19-inventory-") as temporary:
            root, definitions = create_s19_inventory_workspace(Path(temporary))
            inventory = audit.build_consumer_inventory(root, definitions)
            verified = audit.verify_consumer_inventory(inventory)

        self.assertEqual(verified["surface_count"], 18)
        by_id = {item["surface_id"]: item for item in verified["surfaces"]}
        self.assertEqual(by_id["root-env-link"]["classification"], "remove_candidate")
        self.assertEqual(
            by_id["legacy-mcp-protocol-mode"]["classification"], "retain_live"
        )
        self.assertIn("consumer.txt", by_id["legacy-audit-identities"]["consumer_paths"])
        self.assertGreater(by_id["legacy-icourse-client"]["consumer_count"], 0)

        changed = deepcopy(inventory)
        changed["surfaces"][0]["consumer_count"] += 1
        with self.assertRaisesRegex(
            audit.CandidateAuditError, "consumer_count_mismatch"
        ):
            audit.verify_consumer_inventory(changed)

        definitions = json.loads(SURFACES.read_text(encoding="utf-8"))
        definitions["surfaces"][0]["classification"] = "retain_live"
        with tempfile.TemporaryDirectory(prefix="dududa-s19-surfaces-") as temporary:
            changed_path = Path(temporary) / "surfaces.json"
            changed_path.write_text(json.dumps(definitions), encoding="utf-8")
            with self.assertRaisesRegex(
                audit.CandidateAuditError, "surface_catalog_digest_mismatch"
            ):
                audit.build_consumer_inventory(root, changed_path)

    def test_gate_receipt_hashes_sensitive_evidence_and_is_atomic_0600(self) -> None:
        sentinel = "sk-s19-secret /home/private group_id=123456789"
        with tempfile.TemporaryDirectory(prefix="dududa-s19-gate-") as temporary:
            root = Path(temporary)
            evidence = root / "evidence.log"
            evidence.write_text(sentinel, encoding="utf-8")
            output = root / "gate.json"

            exit_code = audit.main(
                [
                    "gate",
                    "--gate-id",
                    "python-3.12",
                    "--status",
                    "passed",
                    "--case-count",
                    "7",
                    "--evidence",
                    str(evidence),
                    "--reason-code",
                    "repository_tests_passed",
                    "--output",
                    str(output),
                ]
            )
            receipt = audit.verify_gate_receipt(json.loads(output.read_text()))

            self.assertEqual(exit_code, 0)
            self.assertEqual(receipt["case_count"], 7)
            self.assertNotIn(sentinel, output.read_text(encoding="utf-8"))
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)

            receipt["case_count"] = 8
            with self.assertRaisesRegex(
                audit.CandidateAuditError, "candidate_gate_digest_mismatch"
            ):
                audit.verify_gate_receipt(receipt)

    def test_candidate_requires_every_passing_gate_and_stays_low_sensitivity(
        self,
    ) -> None:
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        previous = subprocess.run(
            ["git", "rev-parse", "HEAD^"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="dududa-s19-candidate-") as temporary:
            workspace = Path(temporary)
            sentinel = "private-output /home/user 987654321"
            evidence = workspace / "evidence.log"
            evidence.write_text(sentinel, encoding="utf-8")
            previous_source = workspace / "previous.tar"
            previous_source.write_bytes(b"synthetic previous source")
            inventory_path = workspace / "inventory.json"
            inventory_root, definitions = create_s19_inventory_workspace(workspace)
            audit._atomic_json(
                inventory_path,
                audit.build_consumer_inventory(inventory_root, definitions),
            )
            gate_paths: list[Path] = []
            for gate_id in audit.REQUIRED_GATE_IDS:
                gate = audit.create_gate_receipt(
                    gate_id=gate_id,
                    status_value="passed",
                    case_count=1,
                    evidence_path=evidence,
                    reason_code="offline_gate_passed",
                )
                gate_path = workspace / f"{gate_id}.json"
                audit._atomic_json(gate_path, gate)
                gate_paths.append(gate_path)

            with patch.object(audit, "_git_evidence", return_value=(current, False)):
                receipt = audit.create_candidate_receipt(
                    root=ROOT,
                    previous_revision=previous,
                    previous_source=previous_source,
                    policy_path=POLICY,
                    inventory_path=inventory_path,
                    gate_paths=gate_paths,
                )

                self.assertEqual(receipt["status"], "passed_offline")
                self.assertFalse(receipt["s23_ready"])
                self.assertEqual(receipt["gate_count"], len(audit.REQUIRED_GATE_IDS))
                serialized = json.dumps(receipt, sort_keys=True)
                self.assertNotIn(sentinel, serialized)
                self.assertNotIn(str(ROOT), serialized)

                with self.assertRaisesRegex(
                    audit.CandidateAuditError, "candidate_gate_set_mismatch"
                ):
                    audit.create_candidate_receipt(
                        root=ROOT,
                        previous_revision=previous,
                        previous_source=previous_source,
                        policy_path=POLICY,
                        inventory_path=inventory_path,
                        gate_paths=gate_paths[:-1],
                    )

            failed = audit.create_gate_receipt(
                gate_id=audit.REQUIRED_GATE_IDS[0],
                status_value="failed",
                case_count=1,
                evidence_path=evidence,
                reason_code="offline_gate_failed",
            )
            audit._atomic_json(gate_paths[0], failed)
            with (
                patch.object(audit, "_git_evidence", return_value=(current, False)),
                self.assertRaisesRegex(
                    audit.CandidateAuditError, "candidate_gate_failed"
                ),
            ):
                audit.create_candidate_receipt(
                    root=ROOT,
                    previous_revision=previous,
                    previous_source=previous_source,
                    policy_path=POLICY,
                    inventory_path=inventory_path,
                    gate_paths=gate_paths,
                )

            with (
                patch.object(audit, "_git_evidence", return_value=(current, True)),
                self.assertRaisesRegex(
                    audit.CandidateAuditError, "dirty_candidate_source"
                ),
            ):
                audit.create_candidate_receipt(
                    root=ROOT,
                    previous_revision=previous,
                    previous_source=previous_source,
                    policy_path=POLICY,
                    inventory_path=inventory_path,
                    gate_paths=gate_paths,
                )

    def test_previous_source_archive_is_digest_bound_and_private(self) -> None:
        previous = subprocess.run(
            ["git", "rev-parse", "HEAD^"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="dududa-s19-archive-") as temporary:
            archive = Path(temporary) / "previous.tar"
            digest = audit.create_previous_source_archive(ROOT, previous, archive)

            self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(os.stat(archive).st_mode & 0o777, 0o600)
            with tarfile.open(archive) as bundle:
                self.assertIn("README.md", bundle.getnames())

        with self.assertRaisesRegex(
            audit.CandidateAuditError, "invalid_previous_revision"
        ):
            audit.create_previous_source_archive(ROOT, "HEAD", Path("unused.tar"))


if __name__ == "__main__":
    unittest.main()
