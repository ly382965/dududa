#!/usr/bin/env python3
"""Validate a low-sensitivity S23 authorization/readiness manifest offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"^[a-z][a-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
TIME_OF_DAY = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
STAGES = (
    "shadow",
    "inbound_canary",
    "manual_digest",
    "scheduled_digest",
    "probe_canary",
    "closeout",
)
STAGE_INDEX = {stage: index for index, stage in enumerate(STAGES)}
TIERS = frozenset({"haiku", "sonnet", "opus"})
SAFETY_FIELDS = frozenset(
    {
        "cross_scope_memory",
        "duplicate_delivery",
        "personal_probe_target",
        "quiet_hour_delivery",
        "revoked_delivery",
        "sensitive_trace",
        "stale_or_uncited_digest",
        "unauthorized_capability",
        "unknown_delivery_outcome",
        "wrong_target",
    }
)
REQUIRED_SECRET_PURPOSES = frozenset({"onebot_access", "provider_api"})
MAX_READ_WINDOW = timedelta(days=7)


class S23ReadinessError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def load_manifest(path: Path | str) -> dict[str, object]:
    source = Path(path)

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise S23ReadinessError("duplicate_s23_json_key")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        del value
        raise S23ReadinessError("non_finite_s23_json")

    try:
        value = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except S23ReadinessError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise S23ReadinessError("invalid_s23_json") from exc
    return validate_manifest(value)


def validate_manifest(value: object) -> dict[str, object]:
    document = _mapping(value, "manifest")
    _exact(
        document,
        {
            "schema_version",
            "manifest_id",
            "manifest_revision",
            "status",
            "requested_stage",
            "candidate_release_digest",
            "rollback_release_digest",
            "rollback_archive_digest",
            "slo",
            "target",
            "authorization_window",
            "data_policy",
            "secret_refs",
            "endpoint_evidence",
            "source_evidence",
            "projection_evidence",
            "schedule_policy_digest",
            "grant",
        },
        "manifest",
    )
    if document["schema_version"] != SCHEMA_VERSION:
        _fail("unsupported_s23_schema_version")
    _identifier(document["manifest_id"], "manifest_id")
    _identifier(document["manifest_revision"], "manifest_revision")
    if document["status"] not in {"draft", "authorized"}:
        _fail("invalid_s23_status")
    if document["requested_stage"] not in STAGES:
        _fail("invalid_s23_stage")
    for field in (
        "candidate_release_digest",
        "rollback_release_digest",
        "rollback_archive_digest",
        "schedule_policy_digest",
    ):
        _optional_digest(document[field], field)
    _validate_slo(document["slo"])
    _validate_target(document["target"])
    _validate_window(document["authorization_window"], "authorization_window")
    _validate_data_policy(document["data_policy"])
    _validate_secret_refs(document["secret_refs"])
    _validate_endpoint_evidence(document["endpoint_evidence"])
    _validate_source_evidence(document["source_evidence"])
    _validate_projection(document["projection_evidence"])
    _validate_grant(document["grant"])
    return document


def evaluate_readiness(
    value: object,
    *,
    checked_at: datetime,
) -> dict[str, object]:
    document = validate_manifest(value)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        _fail("naive_s23_check_time")
    blockers: set[str] = set()

    if document["status"] != "authorized":
        blockers.add("manifest_not_authorized")
    if "template" in str(document["manifest_id"]) or str(
        document["manifest_revision"]
    ).startswith("draft"):
        blockers.add("placeholder_manifest_identity")
    for field in (
        "candidate_release_digest",
        "rollback_release_digest",
        "rollback_archive_digest",
    ):
        if document[field] is None:
            blockers.add(f"missing_{field}")
    if (
        document["candidate_release_digest"] is not None
        and document["candidate_release_digest"] == document["rollback_release_digest"]
    ):
        blockers.add("candidate_equals_rollback")

    slo = _mapping(document["slo"], "slo")
    if slo["policy_id"] is None:
        blockers.add("missing_slo_policy_id")
    if slo["policy_digest"] is None:
        blockers.add("missing_slo_policy_digest")
    if slo["s23_ready"] is not True:
        blockers.add("slo_not_s23_ready")

    target = _mapping(document["target"], "target")
    for field in ("bot_account_ref", "target_group_ref"):
        if target[field] is None:
            blockers.add(f"missing_{field}")

    window = _mapping(document["authorization_window"], "authorization_window")
    valid_from, valid_until = _window_bounds(window)
    if valid_from is None or valid_until is None:
        blockers.add("missing_authorization_window")
    elif valid_from >= valid_until:
        blockers.add("invalid_authorization_window")
    else:
        if not valid_from <= checked_at <= valid_until:
            blockers.add("authorization_window_inactive")
        if valid_until - valid_from > timedelta(days=7):
            blockers.add("authorization_window_unbounded")

    data_policy = _mapping(document["data_policy"], "data_policy")
    for field in (
        "purpose_revision",
        "retention_until",
        "deletion_owner_ref",
        "audit_sink_ref",
    ):
        if data_policy[field] is None:
            blockers.add(f"missing_data_{field}")
    read_window = _mapping(data_policy["read_window"], "data_policy.read_window")
    read_from, read_until = _window_bounds(read_window)
    if read_from is None or read_until is None:
        blockers.add("missing_data_read_window")
    elif read_from >= read_until:
        blockers.add("invalid_data_read_window")
    elif read_until - read_from > MAX_READ_WINDOW:
        blockers.add("data_read_window_unbounded")
    retention = _optional_datetime(data_policy["retention_until"], "retention_until")
    if retention is not None and valid_until is not None and retention < valid_until:
        blockers.add("retention_precedes_authorization_end")

    secrets = _sequence(document["secret_refs"], "secret_refs", allow_empty=True)
    purposes = {_mapping(item, "secret_ref")["purpose"] for item in secrets}
    for purpose in REQUIRED_SECRET_PURPOSES - purposes:
        blockers.add(f"missing_secret_ref:{purpose}")

    endpoint = _mapping(document["endpoint_evidence"], "endpoint_evidence")
    for field in (
        "conformance_digest",
        "routing_catalog_digest",
        "health_evidence_digest",
    ):
        if endpoint[field] is None:
            blockers.add(f"missing_endpoint_{field}")
    if not endpoint["enabled_bindings"]:
        blockers.add("missing_endpoint_binding")

    grant = _mapping(document["grant"], "grant")
    stage = str(document["requested_stage"])
    for field in (
        "authorization_id",
        "authorization_revision",
        "kill_switch_owner_ref",
        "stop_policy_digest",
    ):
        if grant[field] is None:
            blockers.add(f"missing_grant_{field}")
    if grant["behavior"] != stage:
        blockers.add("grant_behavior_mismatch")
    if grant["max_runs"] < 1:
        blockers.add("grant_has_no_runs")
    grant_from, grant_until = _window_bounds(grant)
    if grant_from is None or grant_until is None:
        blockers.add("missing_grant_window")
    elif grant_from >= grant_until:
        blockers.add("invalid_grant_window")
    elif (
        valid_from is not None
        and valid_until is not None
        and not (valid_from <= grant_from < grant_until <= valid_until)
    ):
        blockers.add("grant_outside_authorization_window")
    if STAGE_INDEX[stage] > 0 and grant["previous_stage_receipt_digest"] is None:
        blockers.add("missing_previous_stage_receipt")

    _stage_blockers(document, blockers)
    report: dict[str, object] = {
        "schema_version": 1,
        "validation_scope": "manifest_only",
        "manifest_identity_digest": _digest(
            {
                "manifest_id": document["manifest_id"],
                "manifest_revision": document["manifest_revision"],
            },
            domain="s23-readiness-manifest-identity-v1",
        ),
        "requested_stage": stage,
        "checked_at": checked_at.astimezone(timezone.utc).isoformat(),
        "manifest_digest": _digest(document, domain="s23-readiness-manifest-v1"),
        "manifest_ready": not blockers,
        "live_execution_authorized": False,
        "blockers": sorted(blockers),
    }
    report["report_digest"] = _digest(report, domain="s23-readiness-report-v1")
    return report


def _stage_blockers(document: Mapping[str, object], blockers: set[str]) -> None:
    stage = str(document["requested_stage"])
    target = _mapping(document["target"], "target")
    grant = _mapping(document["grant"], "grant")
    sources = _sequence(
        document["source_evidence"], "source_evidence", allow_empty=True
    )
    if stage == "shadow":
        if grant["output_enabled"] is not False or grant["max_messages"] != 0:
            blockers.add("shadow_output_not_disabled")
        if grant["memory_allowed"] is not False or grant["allowed_capabilities"]:
            blockers.add("shadow_side_effect_capability_present")
    elif stage == "inbound_canary":
        if not target["test_user_refs"]:
            blockers.add("missing_test_user_ref")
        if grant["output_enabled"] is not True or grant["max_messages"] < 1:
            blockers.add("inbound_output_not_bounded")
        if grant["memory_allowed"] is not False:
            blockers.add("inbound_memory_not_disabled")
    elif stage in {"manual_digest", "scheduled_digest"}:
        live_sources = [
            item
            for item in sources
            if _mapping(item, "source_evidence_item")["live"] is True
        ]
        if not live_sources:
            blockers.add("missing_live_source_adapter")
        if grant["output_enabled"] is not True or grant["max_messages"] < 1:
            blockers.add("digest_output_not_bounded")
        if grant["memory_allowed"] is not False:
            blockers.add("digest_memory_not_disabled")
        if stage == "manual_digest" and document["schedule_policy_digest"] is not None:
            blockers.add("manual_digest_has_schedule")
        if stage == "scheduled_digest" and document["schedule_policy_digest"] is None:
            blockers.add("missing_schedule_policy_digest")
    elif stage == "probe_canary":
        if document["projection_evidence"] is None:
            blockers.add("missing_projection_evidence")
        if grant["output_enabled"] is not True or grant["max_messages"] < 1:
            blockers.add("probe_output_not_bounded")
        if grant["memory_allowed"] is not False:
            blockers.add("probe_memory_not_disabled")
        if grant["no_personal_target"] is not True:
            blockers.add("probe_personal_target_not_forbidden")
        if grant["no_response_followup"] is not False:
            blockers.add("probe_followup_not_disabled")
        if grant["cooldown_seconds"] < 86400:
            blockers.add("probe_cooldown_too_short")
    elif stage == "closeout":
        if grant["output_enabled"] is not False or grant["max_messages"] != 0:
            blockers.add("closeout_output_not_disabled")
        if grant["memory_allowed"] is not False or grant["allowed_capabilities"]:
            blockers.add("closeout_side_effect_capability_present")


def _validate_slo(value: object) -> None:
    item = _mapping(value, "slo")
    _exact(item, {"policy_id", "policy_digest", "s23_ready", "safety_maximums"}, "slo")
    _optional_identifier(item["policy_id"], "slo.policy_id")
    _optional_digest(item["policy_digest"], "slo.policy_digest")
    if type(item["s23_ready"]) is not bool:
        _fail("invalid_s23_ready_flag")
    safety = _mapping(item["safety_maximums"], "safety_maximums")
    if set(safety) != SAFETY_FIELDS:
        _fail("invalid_s23_safety_fields")
    if any(type(limit) is not int or limit != 0 for limit in safety.values()):
        _fail("nonzero_s23_safety_maximum")


def _validate_target(value: object) -> None:
    item = _mapping(value, "target")
    _exact(item, {"bot_account_ref", "target_group_ref", "test_user_refs"}, "target")
    _optional_identifier(item["bot_account_ref"], "bot_account_ref")
    _optional_identifier(item["target_group_ref"], "target_group_ref")
    refs = _sequence(item["test_user_refs"], "test_user_refs", allow_empty=True)
    normalized = [_identifier(ref, "test_user_ref") for ref in refs]
    if len(normalized) != len(set(normalized)):
        _fail("duplicate_test_user_ref")


def _validate_window(value: object, field: str) -> None:
    item = _mapping(value, field)
    _exact(item, {"valid_from", "valid_until", "timezone"}, field)
    _optional_datetime(item["valid_from"], f"{field}.valid_from")
    _optional_datetime(item["valid_until"], f"{field}.valid_until")
    _timezone_name(item["timezone"], f"{field}.timezone")


def _validate_data_policy(value: object) -> None:
    item = _mapping(value, "data_policy")
    _exact(
        item,
        {
            "purpose_revision",
            "read_window",
            "retention_until",
            "deletion_owner_ref",
            "audit_sink_ref",
        },
        "data_policy",
    )
    for field in ("purpose_revision", "deletion_owner_ref", "audit_sink_ref"):
        _optional_identifier(item[field], f"data_policy.{field}")
    _validate_window(item["read_window"], "data_policy.read_window")
    _optional_datetime(item["retention_until"], "data_policy.retention_until")


def _validate_secret_refs(value: object) -> None:
    refs = _sequence(value, "secret_refs", allow_empty=True)
    purposes: list[str] = []
    for raw in refs:
        item = _mapping(raw, "secret_ref")
        _exact(
            item, {"purpose", "namespace", "secret_id", "version_hint"}, "secret_ref"
        )
        purposes.append(_identifier(item["purpose"], "secret_ref.purpose"))
        _identifier(item["namespace"], "secret_ref.namespace")
        _identifier(item["secret_id"], "secret_ref.secret_id")
        _optional_identifier(item["version_hint"], "secret_ref.version_hint")
    if len(purposes) != len(set(purposes)):
        _fail("duplicate_secret_purpose")


def _validate_endpoint_evidence(value: object) -> None:
    item = _mapping(value, "endpoint_evidence")
    _exact(
        item,
        {
            "conformance_digest",
            "routing_catalog_digest",
            "health_evidence_digest",
            "enabled_bindings",
        },
        "endpoint_evidence",
    )
    for field in (
        "conformance_digest",
        "routing_catalog_digest",
        "health_evidence_digest",
    ):
        _optional_digest(item[field], f"endpoint_evidence.{field}")
    bindings = _sequence(item["enabled_bindings"], "enabled_bindings", allow_empty=True)
    seen: set[tuple[str, str]] = set()
    for raw in bindings:
        binding = _mapping(raw, "endpoint_binding")
        _exact(binding, {"role", "tier", "endpoint_ref_digest"}, "endpoint_binding")
        role = _identifier(binding["role"], "endpoint_binding.role")
        tier = _text(binding["tier"], "endpoint_binding.tier")
        if tier not in TIERS:
            _fail("invalid_endpoint_binding_tier")
        _digest_value(binding["endpoint_ref_digest"], "endpoint_ref_digest")
        if (role, tier) in seen:
            _fail("duplicate_endpoint_binding")
        seen.add((role, tier))


def _validate_source_evidence(value: object) -> None:
    sources = _sequence(value, "source_evidence", allow_empty=True)
    seen: set[str] = set()
    for raw in sources:
        item = _mapping(raw, "source_evidence_item")
        _exact(
            item,
            {
                "source_id",
                "adapter_digest",
                "policy_digest",
                "license_evidence_digest",
                "live",
            },
            "source_evidence_item",
        )
        source_id = _identifier(item["source_id"], "source_id")
        if source_id in seen:
            _fail("duplicate_source_evidence")
        seen.add(source_id)
        for field in ("adapter_digest", "policy_digest", "license_evidence_digest"):
            _digest_value(item[field], f"source.{field}")
        if type(item["live"]) is not bool:
            _fail("invalid_source_live_flag")


def _validate_projection(value: object) -> None:
    if value is None:
        return
    item = _mapping(value, "projection_evidence")
    _exact(
        item,
        {"adapter_digest", "schema_digest", "privacy_policy_digest"},
        "projection_evidence",
    )
    for field in item:
        _digest_value(item[field], f"projection.{field}")


def _validate_grant(value: object) -> None:
    item = _mapping(value, "grant")
    _exact(
        item,
        {
            "authorization_id",
            "authorization_revision",
            "behavior",
            "valid_from",
            "valid_until",
            "timezone",
            "max_runs",
            "max_messages",
            "allowed_capabilities",
            "memory_allowed",
            "output_enabled",
            "quiet_hours",
            "kill_switch_owner_ref",
            "stop_policy_digest",
            "previous_stage_receipt_digest",
            "cooldown_seconds",
            "no_response_followup",
            "no_personal_target",
        },
        "grant",
    )
    for field in (
        "authorization_id",
        "authorization_revision",
        "kill_switch_owner_ref",
    ):
        _optional_identifier(item[field], f"grant.{field}")
    if item["behavior"] not in STAGES:
        _fail("invalid_grant_behavior")
    _optional_datetime(item["valid_from"], "grant.valid_from")
    _optional_datetime(item["valid_until"], "grant.valid_until")
    _timezone_name(item["timezone"], "grant.timezone")
    _nonnegative_integer(item["max_runs"], "grant.max_runs")
    _nonnegative_integer(item["max_messages"], "grant.max_messages")
    _nonnegative_integer(item["cooldown_seconds"], "grant.cooldown_seconds")
    capabilities = _sequence(
        item["allowed_capabilities"], "allowed_capabilities", allow_empty=True
    )
    normalized = [_identifier(value, "allowed_capability") for value in capabilities]
    if len(normalized) != len(set(normalized)):
        _fail("duplicate_allowed_capability")
    for field in (
        "memory_allowed",
        "output_enabled",
        "no_response_followup",
        "no_personal_target",
    ):
        if type(item[field]) is not bool:
            _fail(f"invalid_grant_boolean:{field}")
    quiet = _mapping(item["quiet_hours"], "quiet_hours")
    _exact(quiet, {"start", "end"}, "quiet_hours")
    for field in ("start", "end"):
        if (
            not isinstance(quiet[field], str)
            or TIME_OF_DAY.fullmatch(quiet[field]) is None
        ):
            _fail("invalid_quiet_hours")
    _optional_digest(item["stop_policy_digest"], "grant.stop_policy_digest")
    _optional_digest(
        item["previous_stage_receipt_digest"], "grant.previous_stage_receipt_digest"
    )


def _window_bounds(
    value: Mapping[str, object],
) -> tuple[datetime | None, datetime | None]:
    return (
        _optional_datetime(value["valid_from"], "valid_from"),
        _optional_datetime(value["valid_until"], "valid_until"),
    )


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise S23ReadinessError(f"invalid_s23_mapping:{field}")
    return dict(value)


def _sequence(value: object, field: str, *, allow_empty: bool) -> list[object]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise S23ReadinessError(f"invalid_s23_sequence:{field}")
    return list(value)


def _exact(value: Mapping[str, object], fields: set[str], name: str) -> None:
    if set(value) != fields:
        raise S23ReadinessError(f"invalid_s23_fields:{name}")


def _text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
    ):
        raise S23ReadinessError(f"invalid_s23_text:{field}")
    return value


def _identifier(value: object, field: str) -> str:
    result = _text(value, field)
    if IDENTIFIER.fullmatch(result) is None:
        raise S23ReadinessError(f"invalid_s23_identifier:{field}")
    return result


def _optional_identifier(value: object, field: str) -> str | None:
    return None if value is None else _identifier(value, field)


def _timezone_name(value: object, field: str) -> str:
    result = _text(value, field)
    try:
        ZoneInfo(result)
    except (ZoneInfoNotFoundError, ValueError):
        raise S23ReadinessError(f"invalid_s23_timezone:{field}") from None
    return result


def _digest_value(value: object, field: str) -> str:
    result = _text(value, field)
    if SHA256.fullmatch(result) is None:
        raise S23ReadinessError(f"invalid_s23_digest:{field}")
    return result


def _optional_digest(value: object, field: str) -> str | None:
    return None if value is None else _digest_value(value, field)


def _optional_datetime(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise S23ReadinessError(f"invalid_s23_datetime:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"naive_s23_datetime:{field}")
    return parsed


def _nonnegative_integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise S23ReadinessError(f"invalid_s23_integer:{field}")
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise S23ReadinessError("non_canonical_s23_value") from exc


def _digest(value: object, *, domain: str) -> str:
    material = _canonical_bytes({"domain": domain, "value": value})
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _fail(code: str) -> None:
    raise S23ReadinessError(code)


def _parse_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = _optional_datetime(value, "checked_at")
    assert parsed is not None
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--at")
    args = parser.parse_args(argv)
    try:
        report = evaluate_readiness(
            load_manifest(args.manifest), checked_at=_parse_at(args.at)
        )
    except S23ReadinessError as exc:
        print(
            json.dumps(
                {
                    "manifest_ready": False,
                    "live_execution_authorized": False,
                    "error": exc.code,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["manifest_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
