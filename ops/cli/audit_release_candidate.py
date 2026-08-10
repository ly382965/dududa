#!/usr/bin/env python3
"""Build low-sensitivity evidence for one offline Dududa release candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
CLASSIFICATIONS = frozenset({"remove_candidate", "retain_live", "blocked_unknown"})
SAFETY_FIELDS = frozenset(
    {
        "wrong_target",
        "duplicate_delivery",
        "quiet_hour_delivery",
        "revoked_delivery",
        "unauthorized_capability",
        "cross_scope_memory",
        "sensitive_trace",
    }
)
PROFILE_TOKEN_LIMITS = {"short": 128, "medium": 512, "long": 1536}
EXTERNAL_PENDING = (
    "human_chinese_quality",
    "interruption_acceptability",
    "provider_cost",
    "real_qq_latency",
    "real_source_freshness",
)
REQUIRED_GATE_IDS = (
    "python-3.10",
    "python-3.12",
    "worker-3.10",
    "worker-3.12",
    "committed-evals",
    "proactive-30d",
    "fault-sample",
    "web-dependency-audit",
    "web-tests",
    "web-build",
    "web-e2e",
    "astrbot-image-smoke",
    "web-image-smoke",
    "package-static",
    "compose-contract",
    "secret-scan",
    "rollback-package",
    "legacy-consumer-inventory",
)
REQUIRED_SURFACE_IDS = frozenset(
    {
        "root-env-link",
        "root-config-link",
        "root-docker-link",
        "root-plugins-link",
        "root-scripts-link",
        "root-patches-link",
        "root-vendor-link",
        "root-plugin-lock-link",
        "legacy-icourse-service-link",
        "legacy-unified-worker-link",
        "root-manage-wrapper",
        "root-compose-wrapper",
        "legacy-icourse-client",
        "legacy-astrbot-handler",
        "legacy-role-policy",
        "legacy-memory-json",
        "legacy-mcp-protocol-mode",
        "legacy-audit-identities",
    }
)
SURFACE_CATALOG_CONTRACT_DIGEST = (
    "sha256:1705e02a57971e1a6b6df427195f4088f694bc233e7306a34ccaa46ae183889a"
)
REPOSITORY_ARTIFACTS = {
    "root-lock": "uv.lock",
    "worker-lock": "services/mcp/unified-worker/uv.lock",
    "compose": "deploy/compose/compose.yml",
    "plugin-lock": "third_party/plugins.lock.json",
}


class CandidateAuditError(RuntimeError):
    """Stable, content-free audit failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise CandidateAuditError(code)


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
        raise CandidateAuditError("non_canonical_candidate_value") from exc


def _digest(value: object, *, domain: str) -> str:
    material = _canonical_bytes({"domain": domain, "value": value})
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _file_digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        _fail("candidate_evidence_file_missing")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise CandidateAuditError("candidate_evidence_file_unreadable") from exc
    return "sha256:" + digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail("duplicate_candidate_json_key")
            result[key] = value
        return result

    def invalid_constant(value: str) -> object:
        del value
        _fail("non_finite_candidate_json")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
            parse_constant=invalid_constant,
        )
    except CandidateAuditError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateAuditError("invalid_candidate_json") from exc
    return _mapping(value, "document")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(value))
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CandidateAuditError(f"invalid_candidate_mapping:{field}")
    return dict(value)


def _exact(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise CandidateAuditError(f"invalid_candidate_fields:{field}")


def _text(value: object, field: str, *, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise CandidateAuditError(f"invalid_candidate_text:{field}")
    return value


def _identifier(value: object, field: str) -> str:
    result = _text(value, field, maximum=128)
    if IDENTIFIER.fullmatch(result) is None:
        raise CandidateAuditError(f"invalid_candidate_identifier:{field}")
    return result


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CandidateAuditError(f"invalid_candidate_integer:{field}")
    return value


def _sequence(value: object, field: str, *, allow_empty: bool = False) -> list[object]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise CandidateAuditError(f"invalid_candidate_sequence:{field}")
    return list(value)


def validate_slo_policy(value: object) -> dict[str, object]:
    policy = _mapping(value, "policy")
    _exact(
        policy,
        {
            "schema_version",
            "policy_id",
            "evidence_class",
            "s23_ready",
            "safety_maximums",
            "response_profiles",
            "recovery",
            "external_pending",
        },
        "policy",
    )
    if policy["schema_version"] != SCHEMA_VERSION:
        _fail("unsupported_slo_policy_version")
    policy_id = _identifier(policy["policy_id"], "policy_id")
    if policy["evidence_class"] != "pilot_default" or policy["s23_ready"] is not False:
        _fail("invalid_slo_evidence_class")

    safety = _mapping(policy["safety_maximums"], "safety_maximums")
    if set(safety) != SAFETY_FIELDS:
        _fail("invalid_slo_safety_fields")
    if any(type(value) is not int or value != 0 for value in safety.values()):
        _fail("nonzero_slo_safety_floor")

    profiles = _mapping(policy["response_profiles"], "response_profiles")
    if set(profiles) != set(PROFILE_TOKEN_LIMITS):
        _fail("invalid_slo_profile_set")
    normalized_profiles: dict[str, object] = {}
    for profile, token_limit in PROFILE_TOKEN_LIMITS.items():
        item = _mapping(profiles[profile], f"response_profiles.{profile}")
        _exact(
            item,
            {"max_visible_tokens", "p95_latency_ms", "measurement"},
            f"response_profiles.{profile}",
        )
        if item["max_visible_tokens"] != token_limit:
            _fail("slo_profile_token_limit_drift")
        latency = _integer(
            item["p95_latency_ms"],
            f"response_profiles.{profile}.p95_latency_ms",
            minimum=1,
        )
        if item["measurement"] != "pilot_default":
            _fail("invalid_slo_profile_measurement")
        normalized_profiles[profile] = {
            "max_visible_tokens": token_limit,
            "p95_latency_ms": latency,
            "measurement": "pilot_default",
        }

    recovery = _mapping(policy["recovery"], "recovery")
    _exact(
        recovery,
        {"rollback_rto_seconds", "data_rpo_seconds", "measurement"},
        "recovery",
    )
    normalized_recovery = {
        "rollback_rto_seconds": _integer(
            recovery["rollback_rto_seconds"], "rollback_rto_seconds", minimum=1
        ),
        "data_rpo_seconds": _integer(recovery["data_rpo_seconds"], "data_rpo_seconds"),
        "measurement": recovery["measurement"],
    }
    if normalized_recovery["measurement"] != "pilot_default":
        _fail("invalid_slo_recovery_measurement")

    pending = tuple(
        _identifier(item, "external_pending")
        for item in _sequence(policy["external_pending"], "external_pending")
    )
    if pending != EXTERNAL_PENDING:
        _fail("invalid_slo_external_gates")
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_id": policy_id,
        "evidence_class": "pilot_default",
        "s23_ready": False,
        "safety_maximums": {key: 0 for key in sorted(SAFETY_FIELDS)},
        "response_profiles": normalized_profiles,
        "recovery": normalized_recovery,
        "external_pending": list(pending),
    }


def load_slo_policy(path: Path) -> tuple[dict[str, object], str]:
    policy = validate_slo_policy(_load_json(path))
    return policy, _digest(policy, domain="dududa:s19-slo-policy:v1")


def _load_surface_definitions(path: Path) -> tuple[str, list[dict[str, object]]]:
    document = _load_json(path)
    _exact(document, {"schema_version", "catalog_id", "surfaces"}, "surfaces")
    if document["schema_version"] != SCHEMA_VERSION:
        _fail("unsupported_surface_catalog_version")
    if _digest(document, domain="dududa:s19-surface-catalog:v1") != (
        SURFACE_CATALOG_CONTRACT_DIGEST
    ):
        _fail("surface_catalog_digest_mismatch")
    catalog_id = _identifier(document["catalog_id"], "catalog_id")
    surfaces: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(_sequence(document["surfaces"], "surfaces")):
        item = _mapping(raw, f"surfaces[{index}]")
        _exact(
            item,
            {"surface_id", "classification", "tracked_paths", "patterns"},
            f"surfaces[{index}]",
        )
        surface_id = _identifier(item["surface_id"], "surface_id")
        if surface_id in seen:
            _fail("duplicate_surface_id")
        seen.add(surface_id)
        classification = _identifier(item["classification"], "classification")
        if classification not in CLASSIFICATIONS:
            _fail("invalid_surface_classification")
        tracked_paths = tuple(
            _relative_path(value, "tracked_path")
            for value in _sequence(
                item["tracked_paths"], "tracked_paths", allow_empty=True
            )
        )
        patterns = tuple(
            _text(value, "pattern") for value in _sequence(item["patterns"], "patterns")
        )
        if len(set(tracked_paths)) != len(tracked_paths) or len(set(patterns)) != len(
            patterns
        ):
            _fail("duplicate_surface_sequence")
        surfaces.append(
            {
                "surface_id": surface_id,
                "classification": classification,
                "tracked_paths": tracked_paths,
                "patterns": patterns,
            }
        )
    if seen != REQUIRED_SURFACE_IDS:
        _fail("surface_catalog_contract_mismatch")
    return catalog_id, surfaces


def _relative_path(value: object, field: str) -> str:
    text = _text(value, field)
    path = Path(text)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise CandidateAuditError(f"unsafe_candidate_path:{field}")
    return path.as_posix()


def _tracked_files(root: Path) -> tuple[str, ...]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CandidateAuditError("tracked_file_inventory_failed") from exc
    try:
        paths = tuple(item.decode("utf-8") for item in output.split(b"\0") if item)
    except UnicodeDecodeError as exc:
        raise CandidateAuditError("tracked_path_not_utf8") from exc
    if not paths or len(set(paths)) != len(paths):
        _fail("invalid_tracked_file_inventory")
    return tuple(sorted(paths))


def build_consumer_inventory(root: Path, definitions_path: Path) -> dict[str, object]:
    root = root.resolve()
    catalog_id, definitions = _load_surface_definitions(definitions_path)
    tracked = _tracked_files(root)
    tracked_set = set(tracked)
    try:
        definitions_relative = definitions_path.resolve().relative_to(root).as_posix()
    except ValueError:
        definitions_relative = ""

    text_files: dict[str, str] = {}
    for relative in tracked:
        if relative == definitions_relative:
            continue
        path = root / relative
        if path.is_symlink() or not path.is_file():
            continue
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise CandidateAuditError("tracked_file_unreadable") from exc
        if b"\0" in payload or len(payload) > 4 * 1024 * 1024:
            continue
        try:
            text_files[relative] = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue

    results: list[dict[str, object]] = []
    for definition in definitions:
        tracked_paths = tuple(definition["tracked_paths"])
        if any(path not in tracked_set for path in tracked_paths):
            _fail("legacy_surface_path_not_tracked")
        patterns = tuple(definition["patterns"])
        consumers = tuple(
            relative
            for relative, text in sorted(text_files.items())
            if any(pattern in text for pattern in patterns)
        )
        consumer_digest = _digest(
            {"surface_id": definition["surface_id"], "consumer_paths": consumers},
            domain="dududa:s19-consumer-list:v1",
        )
        results.append(
            {
                "surface_id": definition["surface_id"],
                "classification": definition["classification"],
                "tracked_paths": list(tracked_paths),
                "consumer_count": len(consumers),
                "consumer_paths": list(consumers),
                "consumer_digest": consumer_digest,
            }
        )
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "inventory_kind": "tracked_legacy_consumers",
        "catalog_id": catalog_id,
        "surface_count": len(results),
        "surfaces": results,
    }
    return {
        **unsigned,
        "inventory_digest": _digest(
            unsigned, domain="dududa:s19-consumer-inventory:v1"
        ),
    }


def verify_consumer_inventory(value: object) -> dict[str, object]:
    inventory = _mapping(value, "inventory")
    _exact(
        inventory,
        {
            "schema_version",
            "inventory_kind",
            "catalog_id",
            "surface_count",
            "surfaces",
            "inventory_digest",
        },
        "inventory",
    )
    if (
        inventory["schema_version"] != SCHEMA_VERSION
        or inventory["inventory_kind"] != "tracked_legacy_consumers"
    ):
        _fail("invalid_consumer_inventory_header")
    _identifier(inventory["catalog_id"], "catalog_id")
    surfaces = _sequence(inventory["surfaces"], "surfaces")
    if inventory["surface_count"] != len(surfaces):
        _fail("consumer_inventory_count_mismatch")
    seen: set[str] = set()
    for raw in surfaces:
        item = _mapping(raw, "inventory.surface")
        _exact(
            item,
            {
                "surface_id",
                "classification",
                "tracked_paths",
                "consumer_count",
                "consumer_paths",
                "consumer_digest",
            },
            "inventory.surface",
        )
        surface_id = _identifier(item["surface_id"], "surface_id")
        if surface_id in seen:
            _fail("duplicate_inventory_surface")
        seen.add(surface_id)
        if item["classification"] not in CLASSIFICATIONS:
            _fail("invalid_inventory_classification")
        tracked_paths = tuple(
            _relative_path(value, "tracked_path")
            for value in _sequence(
                item["tracked_paths"], "tracked_paths", allow_empty=True
            )
        )
        consumers = tuple(
            _relative_path(value, "consumer_path")
            for value in _sequence(
                item["consumer_paths"], "consumer_paths", allow_empty=True
            )
        )
        if consumers != tuple(sorted(set(consumers))):
            _fail("invalid_inventory_consumer_order")
        if item["consumer_count"] != len(consumers):
            _fail("consumer_count_mismatch")
        expected = _digest(
            {"surface_id": surface_id, "consumer_paths": consumers},
            domain="dududa:s19-consumer-list:v1",
        )
        if item["consumer_digest"] != expected:
            _fail("consumer_digest_mismatch")
        del tracked_paths
    if seen != REQUIRED_SURFACE_IDS:
        _fail("consumer_inventory_surface_mismatch")
    unsigned = {
        key: value for key, value in inventory.items() if key != "inventory_digest"
    }
    if inventory["inventory_digest"] != _digest(
        unsigned, domain="dududa:s19-consumer-inventory:v1"
    ):
        _fail("consumer_inventory_digest_mismatch")
    return inventory


def create_gate_receipt(
    *,
    gate_id: str,
    status_value: str,
    case_count: int,
    evidence_path: Path,
    reason_code: str,
) -> dict[str, object]:
    gate_id = _identifier(gate_id, "gate_id")
    if gate_id not in REQUIRED_GATE_IDS:
        _fail("unknown_candidate_gate")
    if status_value not in {"passed", "failed"}:
        _fail("invalid_candidate_gate_status")
    case_count = _integer(case_count, "case_count")
    reason_code = _identifier(reason_code, "reason_code")
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "receipt_kind": "candidate_gate",
        "gate_id": gate_id,
        "status": status_value,
        "case_count": case_count,
        "evidence_digest": _file_digest(evidence_path),
        "reason_code": reason_code,
    }
    return {
        **unsigned,
        "gate_digest": _digest(unsigned, domain="dududa:s19-gate-receipt:v1"),
    }


def verify_gate_receipt(value: object) -> dict[str, object]:
    gate = _mapping(value, "gate")
    _exact(
        gate,
        {
            "schema_version",
            "receipt_kind",
            "gate_id",
            "status",
            "case_count",
            "evidence_digest",
            "reason_code",
            "gate_digest",
        },
        "gate",
    )
    if (
        gate["schema_version"] != SCHEMA_VERSION
        or gate["receipt_kind"] != "candidate_gate"
    ):
        _fail("invalid_gate_receipt_header")
    gate_id = _identifier(gate["gate_id"], "gate_id")
    if gate_id not in REQUIRED_GATE_IDS:
        _fail("unknown_candidate_gate")
    if gate["status"] not in {"passed", "failed"}:
        _fail("invalid_candidate_gate_status")
    _integer(gate["case_count"], "case_count")
    if (
        not isinstance(gate["evidence_digest"], str)
        or SHA256.fullmatch(gate["evidence_digest"]) is None
    ):
        _fail("invalid_gate_evidence_digest")
    _identifier(gate["reason_code"], "reason_code")
    unsigned = {key: value for key, value in gate.items() if key != "gate_digest"}
    if gate["gate_digest"] != _digest(unsigned, domain="dududa:s19-gate-receipt:v1"):
        _fail("candidate_gate_digest_mismatch")
    return gate


def _git_evidence(root: Path) -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CandidateAuditError("candidate_git_evidence_failed") from exc
    if REVISION.fullmatch(revision) is None:
        _fail("invalid_candidate_revision")
    return revision, dirty


def create_previous_source_archive(root: Path, revision: str, output: Path) -> str:
    revision = _text(revision, "previous_revision", maximum=40)
    if REVISION.fullmatch(revision) is None:
        _fail("invalid_previous_revision")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        subprocess.run(
            ["git", "archive", "--format=tar", f"--output={temporary}", revision],
            cwd=root,
            check=True,
            capture_output=True,
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CandidateAuditError("previous_source_archive_failed") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return _file_digest(output)


def _repository_artifact_digests(root: Path) -> dict[str, str]:
    return {
        artifact_id: _file_digest(root / relative)
        for artifact_id, relative in sorted(REPOSITORY_ARTIFACTS.items())
    }


def create_candidate_receipt(
    *,
    root: Path,
    previous_revision: str,
    previous_source: Path,
    policy_path: Path,
    inventory_path: Path,
    gate_paths: Sequence[Path],
) -> dict[str, object]:
    root = root.resolve()
    revision, dirty = _git_evidence(root)
    if dirty:
        _fail("dirty_candidate_source")
    if REVISION.fullmatch(previous_revision) is None or previous_revision == revision:
        _fail("invalid_previous_revision")
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{previous_revision}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CandidateAuditError("previous_revision_unavailable") from exc

    policy, policy_digest = load_slo_policy(policy_path)
    inventory = verify_consumer_inventory(_load_json(inventory_path))
    gates = [verify_gate_receipt(_load_json(path)) for path in gate_paths]
    gate_ids = tuple(str(gate["gate_id"]) for gate in gates)
    if len(set(gate_ids)) != len(gate_ids):
        _fail("duplicate_candidate_gate")
    if frozenset(gate_ids) != frozenset(REQUIRED_GATE_IDS):
        _fail("candidate_gate_set_mismatch")
    if any(gate["status"] != "passed" for gate in gates):
        _fail("candidate_gate_failed")
    ordered_gates = sorted(gates, key=lambda item: str(item["gate_id"]))
    projected_gates = [
        {
            "gate_id": gate["gate_id"],
            "case_count": gate["case_count"],
            "evidence_digest": gate["evidence_digest"],
            "gate_digest": gate["gate_digest"],
        }
        for gate in ordered_gates
    ]
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "receipt_kind": "offline_release_candidate",
        "status": "passed_offline",
        "candidate_revision": revision,
        "source_dirty": False,
        "previous_revision": previous_revision,
        "previous_source_digest": _file_digest(previous_source),
        "policy_id": policy["policy_id"],
        "policy_digest": policy_digest,
        "inventory_digest": inventory["inventory_digest"],
        "repository_artifacts": _repository_artifact_digests(root),
        "gate_count": len(projected_gates),
        "gates": projected_gates,
        "external_pending": list(EXTERNAL_PENDING),
        "s23_ready": False,
        "created_at": datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    return {
        **unsigned,
        "receipt_digest": _digest(unsigned, domain="dududa:s19-candidate-receipt:v1"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    policy = commands.add_parser("policy-check")
    policy.add_argument("--input", type=Path, required=True)

    inventory = commands.add_parser("inventory")
    inventory.add_argument("--root", type=Path, default=Path.cwd())
    inventory.add_argument("--definitions", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)

    gate = commands.add_parser("gate")
    gate.add_argument("--gate-id", required=True)
    gate.add_argument("--status", choices=("passed", "failed"), required=True)
    gate.add_argument("--case-count", type=int, required=True)
    gate.add_argument("--evidence", type=Path, required=True)
    gate.add_argument("--reason-code", required=True)
    gate.add_argument("--output", type=Path, required=True)

    archive = commands.add_parser("archive")
    archive.add_argument("--root", type=Path, default=Path.cwd())
    archive.add_argument("--revision", required=True)
    archive.add_argument("--output", type=Path, required=True)

    candidate = commands.add_parser("candidate")
    candidate.add_argument("--root", type=Path, default=Path.cwd())
    candidate.add_argument("--previous-revision", required=True)
    candidate.add_argument("--previous-source", type=Path, required=True)
    candidate.add_argument("--policy", type=Path, required=True)
    candidate.add_argument("--inventory", type=Path, required=True)
    candidate.add_argument("--gate", type=Path, action="append", default=[])
    candidate.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "policy-check":
            _, digest = load_slo_policy(args.input)
            print(json.dumps({"policy_digest": digest}, sort_keys=True))
            return 0
        if args.command == "inventory":
            result = build_consumer_inventory(args.root, args.definitions)
            _atomic_json(args.output, result)
            print(
                json.dumps(
                    {
                        "surface_count": result["surface_count"],
                        "inventory_digest": result["inventory_digest"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "gate":
            result = create_gate_receipt(
                gate_id=args.gate_id,
                status_value=args.status,
                case_count=args.case_count,
                evidence_path=args.evidence,
                reason_code=args.reason_code,
            )
            _atomic_json(args.output, result)
            print(json.dumps({"gate_digest": result["gate_digest"]}, sort_keys=True))
            return 0
        if args.command == "archive":
            digest = create_previous_source_archive(
                args.root, args.revision, args.output
            )
            print(json.dumps({"source_digest": digest}, sort_keys=True))
            return 0
        if args.command == "candidate":
            result = create_candidate_receipt(
                root=args.root,
                previous_revision=args.previous_revision,
                previous_source=args.previous_source,
                policy_path=args.policy,
                inventory_path=args.inventory,
                gate_paths=args.gate,
            )
            _atomic_json(args.output, result)
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "candidate_revision": result["candidate_revision"],
                        "receipt_digest": result["receipt_digest"],
                        "s23_ready": result["s23_ready"],
                    },
                    sort_keys=True,
                )
            )
            return 0
    except CandidateAuditError as exc:
        print(exc.code, file=os.sys.stderr)
        return 2
    _fail("unknown_candidate_command")


if __name__ == "__main__":
    raise SystemExit(main())
