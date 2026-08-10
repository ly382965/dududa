from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from ops.cli import validate_s23_readiness as readiness

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "release" / "s23-readiness.template.json"
NOW = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)


def digest(character: str) -> str:
    return "sha256:" + character * 64


def authorized_shadow() -> dict[str, object]:
    value = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    value.update(
        {
            "manifest_id": "s23-pilot-a",
            "manifest_revision": "pilot-a-v1",
            "status": "authorized",
            "candidate_release_digest": digest("a"),
            "rollback_release_digest": digest("b"),
            "rollback_archive_digest": digest("c"),
        }
    )
    value["slo"].update(
        {
            "policy_id": "s23-pilot-slo-v1",
            "policy_digest": digest("d"),
            "s23_ready": True,
        }
    )
    value["target"].update(
        {
            "bot_account_ref": "bot:pilot-a",
            "target_group_ref": "group:pilot-a",
        }
    )
    value["authorization_window"].update(
        {
            "valid_from": "2026-08-11T10:00:00+08:00",
            "valid_until": "2026-08-11T14:00:00+08:00",
        }
    )
    value["data_policy"].update(
        {
            "purpose_revision": "pilot-purpose-v1",
            "retention_until": "2026-08-18T14:00:00+08:00",
            "deletion_owner_ref": "operator:data-owner",
            "audit_sink_ref": "audit:s23-private",
        }
    )
    value["data_policy"]["read_window"].update(
        {
            "valid_from": "2026-08-10T10:00:00+08:00",
            "valid_until": "2026-08-11T10:00:00+08:00",
        }
    )
    value["secret_refs"] = [
        {
            "purpose": "onebot_access",
            "namespace": "s23",
            "secret_id": "onebot-pilot",
            "version_hint": "v1",
        },
        {
            "purpose": "provider_api",
            "namespace": "s23",
            "secret_id": "provider-pilot",
            "version_hint": "v1",
        },
    ]
    value["endpoint_evidence"].update(
        {
            "conformance_digest": digest("e"),
            "routing_catalog_digest": digest("f"),
            "health_evidence_digest": digest("1"),
            "enabled_bindings": [
                {
                    "role": "direct_chat",
                    "tier": "sonnet",
                    "endpoint_ref_digest": digest("2"),
                }
            ],
        }
    )
    value["grant"].update(
        {
            "authorization_id": "authorization:shadow-a",
            "authorization_revision": "shadow-a-v1",
            "valid_from": "2026-08-11T10:00:00+08:00",
            "valid_until": "2026-08-11T14:00:00+08:00",
            "max_runs": 3,
            "kill_switch_owner_ref": "operator:kill-switch",
            "stop_policy_digest": digest("3"),
        }
    )
    return value


class S23ReadinessTests(unittest.TestCase):
    def test_template_is_valid_but_fail_closed_and_low_sensitivity(self) -> None:
        document = readiness.load_manifest(TEMPLATE)
        report = readiness.evaluate_readiness(document, checked_at=NOW)
        self.assertFalse(report["manifest_ready"])
        self.assertFalse(report["live_execution_authorized"])
        self.assertEqual(report["validation_scope"], "manifest_only")
        self.assertIn("slo_not_s23_ready", report["blockers"])
        self.assertIn("missing_target_group_ref", report["blockers"])
        self.assertIn("missing_slo_policy_id", report["blockers"])
        self.assertIn("missing_data_read_window", report["blockers"])

        authorized = authorized_shadow()
        authorized["manifest_id"] = "sk-proj-secretvalue"
        serialized = json.dumps(
            readiness.evaluate_readiness(authorized, checked_at=NOW), sort_keys=True
        )
        for private_ref in (
            authorized["manifest_id"],
            authorized["target"]["bot_account_ref"],
            authorized["target"]["target_group_ref"],
            authorized["secret_refs"][0]["secret_id"],
            authorized["secret_refs"][1]["secret_id"],
        ):
            self.assertNotIn(private_ref, serialized)

    def test_complete_shadow_manifest_is_ready(self) -> None:
        report = readiness.evaluate_readiness(authorized_shadow(), checked_at=NOW)
        self.assertTrue(report["manifest_ready"])
        self.assertFalse(report["live_execution_authorized"])
        self.assertEqual(report["blockers"], [])
        self.assertRegex(report["manifest_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_inbound_requires_predecessor_test_user_and_bounded_output(self) -> None:
        value = authorized_shadow()
        value["requested_stage"] = "inbound_canary"
        value["grant"].update(
            {
                "behavior": "inbound_canary",
                "output_enabled": True,
                "max_messages": 2,
            }
        )
        blocked = readiness.evaluate_readiness(value, checked_at=NOW)
        self.assertEqual(
            set(blocked["blockers"]),
            {"missing_previous_stage_receipt", "missing_test_user_ref"},
        )
        value["target"]["test_user_refs"] = ["user:tester-a"]
        value["grant"]["previous_stage_receipt_digest"] = digest("4")
        self.assertTrue(
            readiness.evaluate_readiness(value, checked_at=NOW)["manifest_ready"]
        )

    def test_digest_and_probe_require_real_stage_evidence(self) -> None:
        digest_value = authorized_shadow()
        digest_value["requested_stage"] = "scheduled_digest"
        digest_value["grant"].update(
            {
                "behavior": "scheduled_digest",
                "output_enabled": True,
                "max_messages": 1,
                "previous_stage_receipt_digest": digest("4"),
            }
        )
        blocked = readiness.evaluate_readiness(digest_value, checked_at=NOW)
        self.assertEqual(
            set(blocked["blockers"]),
            {"missing_live_source_adapter", "missing_schedule_policy_digest"},
        )
        digest_value["source_evidence"] = [
            {
                "source_id": "arxiv-feed",
                "adapter_digest": digest("5"),
                "policy_digest": digest("6"),
                "license_evidence_digest": digest("7"),
                "live": True,
            }
        ]
        digest_value["schedule_policy_digest"] = digest("8")
        self.assertTrue(
            readiness.evaluate_readiness(digest_value, checked_at=NOW)["manifest_ready"]
        )

        probe = authorized_shadow()
        probe["requested_stage"] = "probe_canary"
        probe["grant"].update(
            {
                "behavior": "probe_canary",
                "output_enabled": True,
                "max_messages": 1,
                "previous_stage_receipt_digest": digest("4"),
                "cooldown_seconds": 86400,
            }
        )
        self.assertIn(
            "missing_projection_evidence",
            readiness.evaluate_readiness(probe, checked_at=NOW)["blockers"],
        )
        probe["projection_evidence"] = {
            "adapter_digest": digest("5"),
            "schema_digest": digest("6"),
            "privacy_policy_digest": digest("7"),
        }
        self.assertTrue(
            readiness.evaluate_readiness(probe, checked_at=NOW)["manifest_ready"]
        )

    def test_secret_values_nonzero_safety_and_unknown_fields_are_rejected(self) -> None:
        mutations = (
            lambda value: value["secret_refs"][0].__setitem__("value", "forbidden"),
            lambda value: value["slo"]["safety_maximums"].__setitem__(
                "wrong_target", 1
            ),
            lambda value: value.__setitem__("group_id", "forbidden"),
        )
        for mutate in mutations:
            value = authorized_shadow()
            mutate(value)
            with self.assertRaises(readiness.S23ReadinessError):
                readiness.evaluate_readiness(value, checked_at=NOW)

    def test_invalid_windows_timezone_and_template_identity_fail_closed(self) -> None:
        mutations = (
            (
                "invalid_authorization_window",
                lambda value: value["authorization_window"].update(
                    {
                        "valid_from": "2026-08-11T14:00:00+08:00",
                        "valid_until": "2026-08-11T10:00:00+08:00",
                    }
                ),
            ),
            (
                "invalid_data_read_window",
                lambda value: value["data_policy"]["read_window"].update(
                    {
                        "valid_from": "2026-08-11T10:00:00+08:00",
                        "valid_until": "2026-08-10T10:00:00+08:00",
                    }
                ),
            ),
            (
                "placeholder_manifest_identity",
                lambda value: value.__setitem__(
                    "manifest_id", "s23-readiness-template"
                ),
            ),
        )
        for expected, mutate in mutations:
            value = authorized_shadow()
            mutate(value)
            self.assertIn(
                expected,
                readiness.evaluate_readiness(value, checked_at=NOW)["blockers"],
            )

        value = authorized_shadow()
        value["grant"]["timezone"] = "Mars/Olympus"
        with self.assertRaisesRegex(
            readiness.S23ReadinessError, "invalid_s23_timezone:grant.timezone"
        ):
            readiness.evaluate_readiness(value, checked_at=NOW)

    def test_stage_exclusivity_and_read_window_are_bounded(self) -> None:
        value = authorized_shadow()
        value["data_policy"]["read_window"]["valid_from"] = "2026-07-01T10:00:00+08:00"
        self.assertIn(
            "data_read_window_unbounded",
            readiness.evaluate_readiness(value, checked_at=NOW)["blockers"],
        )

        value = authorized_shadow()
        value["requested_stage"] = "manual_digest"
        value["grant"].update(
            {
                "behavior": "manual_digest",
                "output_enabled": True,
                "max_messages": 1,
                "previous_stage_receipt_digest": digest("4"),
            }
        )
        value["source_evidence"] = [
            {
                "source_id": "arxiv-feed",
                "adapter_digest": digest("5"),
                "policy_digest": digest("6"),
                "license_evidence_digest": digest("7"),
                "live": True,
            }
        ]
        value["schedule_policy_digest"] = digest("8")
        self.assertIn(
            "manual_digest_has_schedule",
            readiness.evaluate_readiness(value, checked_at=NOW)["blockers"],
        )

        value = authorized_shadow()
        value["requested_stage"] = "closeout"
        value["grant"].update(
            {
                "behavior": "closeout",
                "max_messages": 1,
                "memory_allowed": True,
                "allowed_capabilities": ["icourse.stats.read.v1"],
                "previous_stage_receipt_digest": digest("4"),
            }
        )
        self.assertEqual(
            set(readiness.evaluate_readiness(value, checked_at=NOW)["blockers"]),
            {
                "closeout_output_not_disabled",
                "closeout_side_effect_capability_present",
            },
        )

    def test_cli_uses_distinct_exit_codes_for_blocked_and_invalid(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = readiness.main(
                ["--manifest", str(TEMPLATE), "--at", NOW.isoformat()]
            )
        self.assertEqual(code, 2)
        report = json.loads(output.getvalue())
        self.assertFalse(report["manifest_ready"])
        self.assertFalse(report["live_execution_authorized"])

        output = StringIO()
        with redirect_stdout(output):
            code = readiness.main(
                ["--manifest", str(ROOT / "missing.json"), "--at", NOW.isoformat()]
            )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["error"], "invalid_s23_json")


if __name__ == "__main__":
    unittest.main()
