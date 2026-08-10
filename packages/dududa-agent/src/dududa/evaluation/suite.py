"""Repository-level adapter for existing offline evaluation evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import TextIO

from dududa.contracts.canonical import canonical_digest, canonical_json_bytes

_SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{7,64}$")
_CATALOG_FIELDS = {
    "schema_version",
    "catalog_id",
    "data_policy",
    "required_dimensions",
    "suites",
    "profiles",
}
_DATA_POLICY = {
    "fixture_kinds": ["public", "synthetic"],
    "network_allowed": False,
    "real_user_data_allowed": False,
}
_CATALOG_CONTRACT_DIGEST = (
    "dududa-c14n-v1:eval:suite-catalog:v1:sha-256:"
    "0a3a5efbfc19c429258448fc9d26d66153a191a57a9f189c687f9a5a4e35677f"
)
_SUITE_FIELDS = {
    "suite_id",
    "runner_id",
    "suite_revision",
    "evidence_kind",
    "dimensions",
    "quality_claim",
    "external_gates",
}


class EvaluationSuiteError(RuntimeError):
    """Stable failure for catalog, execution, or receipt validation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SuiteDefinition:
    suite_id: str
    runner_id: str
    suite_revision: str
    evidence_kind: str
    dimensions: tuple[str, ...]
    quality_claim: str
    external_gates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SuiteCatalog:
    catalog_id: str
    required_dimensions: tuple[str, ...]
    suites: tuple[SuiteDefinition, ...]
    profiles: tuple[tuple[str, tuple[str, ...]], ...]
    document: Mapping[str, object]

    def profile(self, profile_id: str) -> tuple[str, ...]:
        for candidate, suite_ids in self.profiles:
            if candidate == profile_id:
                return suite_ids
        raise EvaluationSuiteError("unknown_evaluation_profile")


@dataclass(frozen=True, slots=True)
class _RunnerDefinition:
    evidence_kind: str
    dimensions: frozenset[str]
    execute: Callable[[Path, TextIO], Mapping[str, object]]


def _bundle_runner(
    relative_path: str,
    checker: Callable[[Path], object],
) -> Callable[[Path, TextIO], Mapping[str, object]]:
    def execute(root: Path, stream: TextIO) -> Mapping[str, object]:
        del stream
        bundle = root / relative_path
        checker(bundle)
        report = _load_json(bundle / "report.json")
        technical_pass = report.get("technical_pass")
        release_ready = report.get("release_ready")
        if technical_pass is not True or type(release_ready) is not bool:
            raise EvaluationSuiteError("invalid_committed_eval_status")
        case_count = report.get("case_count", report.get("sample_count"))
        if type(case_count) is not int or case_count < 1:
            raise EvaluationSuiteError("invalid_committed_eval_case_count")
        input_digest = _first_digest(
            report,
            ("dataset_digest", "cases_digest", "manifest_digest"),
        )
        report_digest = report.get("report_digest")
        if not isinstance(report_digest, str) or not report_digest:
            report_digest = str(
                canonical_digest(report, domain="eval:suite-report-adapter:v1")
            )
        human_review = report.get("human_review_complete", False)
        if type(human_review) is not bool:
            raise EvaluationSuiteError("invalid_committed_eval_review_status")
        user_data_count = report.get("user_data_record_count", 0)
        if type(user_data_count) is not int or user_data_count != 0:
            raise EvaluationSuiteError("real_user_data_in_offline_eval")
        return {
            "technical_pass": True,
            "release_ready": release_ready,
            "human_review_complete": human_review,
            "case_count": case_count,
            "input_digest": input_digest,
            "report_digest": report_digest,
            "user_data_record_count": user_data_count,
        }

    return execute


def _unittest_runner(
    selectors: Sequence[str],
) -> Callable[[Path, TextIO], Mapping[str, object]]:
    frozen_selectors = tuple(selectors)

    def execute(root: Path, stream: TextIO) -> Mapping[str, object]:
        loader = unittest.TestLoader()
        with _repository_context(root):
            suite = loader.loadTestsFromNames(frozen_selectors)
            if loader.errors:
                raise EvaluationSuiteError("evaluation_test_load_failed")
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        summary = {
            "tests_run": result.testsRun,
            "failure_count": len(result.failures),
            "error_count": len(result.errors),
            "skipped_count": len(result.skipped),
            "unexpected_success_count": len(result.unexpectedSuccesses),
        }
        return {
            "technical_pass": result.wasSuccessful(),
            "release_ready": False,
            "human_review_complete": False,
            "case_count": result.testsRun,
            "input_digest": str(
                canonical_digest(
                    {"selectors": frozen_selectors},
                    domain="eval:contract-suite-input:v1",
                )
            ),
            "report_digest": str(
                canonical_digest(summary, domain="eval:contract-suite-report:v1")
            ),
            "user_data_record_count": 0,
        }

    return execute


def _repository_test_runner(root: Path, stream: TextIO) -> Mapping[str, object]:
    loader = unittest.TestLoader()
    with _repository_context(root):
        suite = loader.discover(
            start_dir=str(root / "tests"),
        )
        if loader.errors:
            raise EvaluationSuiteError("repository_test_load_failed")
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    summary = {
        "tests_run": result.testsRun,
        "failure_count": len(result.failures),
        "error_count": len(result.errors),
        "skipped_count": len(result.skipped),
        "unexpected_success_count": len(result.unexpectedSuccesses),
    }
    return {
        "technical_pass": result.wasSuccessful(),
        "release_ready": False,
        "human_review_complete": False,
        "case_count": result.testsRun,
        "input_digest": str(
            canonical_digest(
                {"discovery_root": "tests"},
                domain="eval:repository-test-input:v1",
            )
        ),
        "report_digest": str(
            canonical_digest(summary, domain="eval:repository-test-report:v1")
        ),
        "user_data_record_count": 0,
    }


def _check_s09(path: Path) -> None:
    from .s09 import check_s09_bundle

    check_s09_bundle(path)


def _check_semantic(path: Path) -> None:
    from .semantic_v2 import check_semantic_schema_pilot

    draft_validator = import_module("jsonschema").Draft202012Validator

    def validate(schema: object, instance: object) -> None:
        draft_validator.check_schema(schema)
        draft_validator(schema).validate(instance)

    check_semantic_schema_pilot(path, validate_schema=validate)


def _check_memory(path: Path) -> None:
    from .memory import check_memory_retrieval_bundle

    check_memory_retrieval_bundle(path)


def _check_response_profile(path: Path) -> None:
    from .response_profile import check_response_profile_bundle

    check_response_profile_bundle(path)


_ROUTING_DIMENSIONS = frozenset(
    {
        "reply_target_semantics",
        "static_model_routing",
    }
)
_CAPABILITY_DIMENSIONS = frozenset(
    {
        "mcp_capability_execution",
        "tool_selection_arguments_validation",
    }
)
_RESPONSE_DIMENSIONS = frozenset(
    {
        "answer_profile",
        "persona_mechanics",
    }
)
_PROACTIVE_DIMENSIONS = frozenset(
    {
        "scheduler_subscription",
        "source_freshness_provenance_dedup",
        "digest_shadow",
        "probe_shadow",
    }
)
_TRACE_DIMENSIONS = frozenset({"runtime_trace_privacy", "import_boundaries"})
_ALL_DIMENSIONS = frozenset(
    {
        *_ROUTING_DIMENSIONS,
        "semantic_intent_entity_reference",
        *_CAPABILITY_DIMENSIONS,
        "memory_scope_retrieval",
        *_RESPONSE_DIMENSIONS,
        *_PROACTIVE_DIMENSIONS,
        *_TRACE_DIMENSIONS,
    }
)


_RUNNERS: Mapping[str, _RunnerDefinition] = {
    "perception-tiering-bundle-v1": _RunnerDefinition(
        "committed_bundle",
        frozenset({"reply_target_semantics", "static_model_routing"}),
        _bundle_runner("evals/perception-tiering/v1", _check_s09),
    ),
    "semantic-schema-bundle-v2": _RunnerDefinition(
        "committed_bundle",
        frozenset({"semantic_intent_entity_reference"}),
        _bundle_runner("evals/perception-semantic/v2", _check_semantic),
    ),
    "memory-retrieval-bundle-v1": _RunnerDefinition(
        "committed_bundle",
        frozenset({"memory_scope_retrieval"}),
        _bundle_runner("evals/memory-retrieval/v1", _check_memory),
    ),
    "response-profile-bundle-v1": _RunnerDefinition(
        "committed_bundle",
        frozenset({"answer_profile"}),
        _bundle_runner("evals/response-profile/v1", _check_response_profile),
    ),
    "routing-contracts-v1": _RunnerDefinition(
        "contract_suite",
        _ROUTING_DIMENSIONS,
        _unittest_runner(
            (
                "tests.unit.models.test_tiering",
                "tests.unit.models.test_router",
                "tests.unit.perception.test_social",
            )
        ),
    ),
    "capability-mcp-contracts-v1": _RunnerDefinition(
        "contract_suite",
        _CAPABILITY_DIMENSIONS,
        _unittest_runner(
            (
                "tests.unit.evaluation.test_capabilities",
                "tests.unit.mcp.test_client",
                "tests.contracts.test_mcp_capability_extension",
                "tests.contracts.test_mcp_capability_provider",
            )
        ),
    ),
    "response-persona-contracts-v1": _RunnerDefinition(
        "contract_suite",
        _RESPONSE_DIMENSIONS,
        _unittest_runner(
            (
                "tests.unit.persona.test_contracts",
                "tests.unit.persona.test_registry",
                "tests.unit.responses.test_policy",
            )
        ),
    ),
    "proactive-contracts-v1": _RunnerDefinition(
        "contract_suite",
        _PROACTIVE_DIMENSIONS,
        _unittest_runner(
            (
                "tests.unit.proactive.test_scheduler",
                "tests.unit.proactive.test_sources",
                "tests.unit.proactive.test_digest_shadow",
                "tests.unit.proactive.test_probe_shadow",
            )
        ),
    ),
    "trace-boundary-contracts-v1": _RunnerDefinition(
        "contract_suite",
        _TRACE_DIMENSIONS,
        _unittest_runner(
            (
                "tests.unit.runtime.test_shadow",
                "tests.unit.runtime.test_trace",
                "tests.contracts.test_import_boundaries",
            )
        ),
    ),
    "repository-tests-v1": _RunnerDefinition(
        "repository_suite",
        _ALL_DIMENSIONS,
        _repository_test_runner,
    ),
}


def load_suite_catalog(path: Path | str) -> SuiteCatalog:
    catalog_path = Path(path)
    document = _load_json(catalog_path)
    _exact_fields(document, _CATALOG_FIELDS, "catalog")
    if document.get("schema_version") != _SCHEMA_VERSION:
        raise EvaluationSuiteError("unsupported_evaluation_catalog_version")
    catalog_id = _identifier(document.get("catalog_id"), "catalog_id")
    if document.get("data_policy") != _DATA_POLICY:
        raise EvaluationSuiteError("unsafe_evaluation_data_policy")
    required_dimensions = _identifier_tuple(
        document.get("required_dimensions"),
        "required_dimensions",
    )
    if frozenset(required_dimensions) != _ALL_DIMENSIONS:
        raise EvaluationSuiteError("evaluation_dimension_contract_mismatch")

    raw_suites = document.get("suites")
    if not isinstance(raw_suites, list) or not raw_suites:
        raise EvaluationSuiteError("invalid_evaluation_suites")
    suites: list[SuiteDefinition] = []
    for index, raw_suite in enumerate(raw_suites):
        suite = _mapping(raw_suite, f"suites[{index}]")
        _exact_fields(suite, _SUITE_FIELDS, f"suites[{index}]")
        definition = SuiteDefinition(
            suite_id=_identifier(suite.get("suite_id"), "suite_id"),
            runner_id=_identifier(suite.get("runner_id"), "runner_id"),
            suite_revision=_identifier(suite.get("suite_revision"), "suite_revision"),
            evidence_kind=_identifier(suite.get("evidence_kind"), "evidence_kind"),
            dimensions=_identifier_tuple(suite.get("dimensions"), "dimensions"),
            quality_claim=_identifier(suite.get("quality_claim"), "quality_claim"),
            external_gates=_identifier_tuple(
                suite.get("external_gates"),
                "external_gates",
                allow_empty=True,
            ),
        )
        registered = _RUNNERS.get(definition.runner_id)
        if registered is None:
            raise EvaluationSuiteError("unknown_evaluation_runner")
        if (
            definition.evidence_kind != registered.evidence_kind
            or frozenset(definition.dimensions) != registered.dimensions
        ):
            raise EvaluationSuiteError("evaluation_runner_contract_mismatch")
        suites.append(definition)
    suite_ids = tuple(item.suite_id for item in suites)
    if len(set(suite_ids)) != len(suite_ids):
        raise EvaluationSuiteError("duplicate_evaluation_suite")
    covered = frozenset(dimension for item in suites for dimension in item.dimensions)
    if covered != _ALL_DIMENSIONS:
        raise EvaluationSuiteError("incomplete_evaluation_dimension_coverage")

    raw_profiles = _mapping(document.get("profiles"), "profiles")
    profiles: list[tuple[str, tuple[str, ...]]] = []
    for raw_profile_id, raw_suite_ids in sorted(raw_profiles.items()):
        profile_id = _identifier(raw_profile_id, "profile_id")
        selected = _identifier_tuple(raw_suite_ids, f"profiles.{profile_id}")
        if any(item not in suite_ids for item in selected):
            raise EvaluationSuiteError("unknown_profile_suite")
        profiles.append((profile_id, selected))
    if {item[0] for item in profiles} != {
        "committed-bundles",
        "s18-focused",
        "ci-python",
    }:
        raise EvaluationSuiteError("evaluation_profile_contract_mismatch")
    for coverage_profile in ("s18-focused", "ci-python"):
        selected = next(items for name, items in profiles if name == coverage_profile)
        selected_dimensions = frozenset(
            dimension
            for suite in suites
            if suite.suite_id in selected
            for dimension in suite.dimensions
        )
        if selected_dimensions != _ALL_DIMENSIONS:
            raise EvaluationSuiteError("incomplete_profile_dimension_coverage")
    catalog_digest = str(canonical_digest(document, domain="eval:suite-catalog:v1"))
    if catalog_digest != _CATALOG_CONTRACT_DIGEST:
        raise EvaluationSuiteError("evaluation_catalog_contract_mismatch")

    return SuiteCatalog(
        catalog_id=catalog_id,
        required_dimensions=required_dimensions,
        suites=tuple(suites),
        profiles=tuple(profiles),
        document=document,
    )


def run_suite_profile(
    catalog_path: Path | str,
    *,
    profile_id: str,
    receipt_path: Path | str,
    stream: TextIO | None = None,
) -> Mapping[str, object]:
    catalog_file = Path(catalog_path).resolve()
    root = catalog_file.parent.parent
    if not (root / "pyproject.toml").is_file():
        raise EvaluationSuiteError("evaluation_repository_root_missing")
    catalog = load_suite_catalog(catalog_file)
    selected_ids = catalog.profile(profile_id)
    selected = {item.suite_id: item for item in catalog.suites}
    bounded_run_id = f"eval-{uuid.uuid4().hex}"
    output = stream or sys.stderr
    started_at = _utc_now()
    source_revision, source_dirty = _git_evidence(root)
    results: list[Mapping[str, object]] = []
    overall_status = "passed"

    for suite_id in selected_ids:
        suite = selected[suite_id]
        runner = _RUNNERS[suite.runner_id]
        suite_started = time.monotonic_ns()
        reason_code = "evaluation_suite_passed"
        try:
            evidence = dict(runner.execute(root, output))
            _validate_runner_evidence(evidence)
            if evidence["technical_pass"] is not True:
                overall_status = "failed"
                reason_code = "evaluation_gate_failed"
        except Exception as exc:  # noqa: BLE001 - exception content is never persisted.
            overall_status = "failed"
            reason_code = "evaluation_suite_execution_failed"
            evidence = _failed_evidence(suite)
            print(
                f"{suite.suite_id}: {reason_code} ({type(exc).__name__})",
                file=output,
            )
        duration_ms = max(0, (time.monotonic_ns() - suite_started) // 1_000_000)
        results.append(
            {
                "schema_version": _SCHEMA_VERSION,
                "suite_id": suite.suite_id,
                "suite_revision": suite.suite_revision,
                "evidence_kind": suite.evidence_kind,
                "status": "passed"
                if reason_code == "evaluation_suite_passed"
                else "failed",
                "technical_pass": evidence["technical_pass"],
                "release_ready": evidence["release_ready"],
                "human_review_complete": evidence["human_review_complete"],
                "case_count": evidence["case_count"],
                "user_data_record_count": evidence["user_data_record_count"],
                "input_digest": evidence["input_digest"],
                "report_digest": evidence["report_digest"],
                "quality_claim": suite.quality_claim,
                "external_gates": suite.external_gates,
                "reason_code": reason_code,
                "duration_ms": duration_ms,
            }
        )
        if overall_status == "failed":
            break

    completed_at = _utc_now()
    unsigned: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "receipt_kind": "offline_evaluation",
        "run_id": bounded_run_id,
        "catalog_id": catalog.catalog_id,
        "catalog_digest": str(
            canonical_digest(catalog.document, domain="eval:suite-catalog:v1")
        ),
        "profile_id": profile_id,
        "profile_digest": str(
            canonical_digest(
                {"profile_id": profile_id, "suite_ids": selected_ids},
                domain="eval:suite-profile:v1",
            )
        ),
        "source_revision": source_revision,
        "source_dirty": source_dirty,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "started_at": started_at,
        "completed_at": completed_at,
        "status": overall_status,
        "results": tuple(results),
    }
    receipt = {
        **unsigned,
        "receipt_digest": str(
            canonical_digest(unsigned, domain="eval:suite-receipt:v1")
        ),
    }
    _atomic_json(Path(receipt_path), receipt)
    return receipt


def _validate_runner_evidence(value: Mapping[str, object]) -> None:
    expected = {
        "technical_pass",
        "release_ready",
        "human_review_complete",
        "case_count",
        "input_digest",
        "report_digest",
        "user_data_record_count",
    }
    _exact_fields(value, expected, "runner_evidence")
    for field_name in (
        "technical_pass",
        "release_ready",
        "human_review_complete",
    ):
        if type(value[field_name]) is not bool:
            raise EvaluationSuiteError("invalid_evaluation_boolean_evidence")
    if type(value["case_count"]) is not int or value["case_count"] < 1:
        raise EvaluationSuiteError("invalid_evaluation_case_count")
    if (
        type(value["user_data_record_count"]) is not int
        or value["user_data_record_count"] != 0
    ):
        raise EvaluationSuiteError("real_user_data_in_offline_eval")
    for field_name in ("input_digest", "report_digest"):
        raw = value[field_name]
        if not isinstance(raw, str) or not raw.startswith("dududa-c14n-v1:"):
            raise EvaluationSuiteError("invalid_evaluation_evidence_digest")


def _failed_evidence(suite: SuiteDefinition) -> Mapping[str, object]:
    failure = {
        "suite_id": suite.suite_id,
        "suite_revision": suite.suite_revision,
        "status": "failed",
    }
    digest = str(canonical_digest(failure, domain="eval:suite-failure:v1"))
    return {
        "technical_pass": False,
        "release_ready": False,
        "human_review_complete": False,
        "case_count": 1,
        "input_digest": digest,
        "report_digest": digest,
        "user_data_record_count": 0,
    }


def _first_digest(value: Mapping[str, object], fields: Sequence[str]) -> str:
    for field_name in fields:
        candidate = value.get(field_name)
        if isinstance(candidate, str) and candidate.startswith("dududa-c14n-v1:"):
            return candidate
    raise EvaluationSuiteError("committed_eval_input_digest_missing")


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
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    if _SOURCE_REVISION.fullmatch(revision) is None:
        return "unknown", True
    return revision, dirty


@contextmanager
def _repository_context(root: Path):
    previous_cwd = Path.cwd()
    root_text = str(root)
    inserted = not sys.path or sys.path[0] != root_text
    if inserted:
        sys.path.insert(0, root_text)
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(previous_cwd)
        if inserted and sys.path and sys.path[0] == root_text:
            sys.path.pop(0)


def _load_json(path: Path) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise EvaluationSuiteError("duplicate_evaluation_json_key")
            result[key] = value
        return result

    def invalid_constant(value: str) -> object:
        del value
        raise EvaluationSuiteError("non_finite_evaluation_json")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
            parse_constant=invalid_constant,
        )
    except EvaluationSuiteError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationSuiteError("invalid_evaluation_json") from exc
    return _mapping(value, "document")


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise EvaluationSuiteError(f"invalid_evaluation_mapping:{field_name}")
    return dict(value)


def _exact_fields(
    value: Mapping[str, object], expected: set[str], field_name: str
) -> None:
    if set(value) != expected:
        raise EvaluationSuiteError(f"invalid_evaluation_fields:{field_name}")


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise EvaluationSuiteError(f"invalid_evaluation_identifier:{field_name}")
    return value


def _identifier_tuple(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise EvaluationSuiteError(f"invalid_evaluation_sequence:{field_name}")
    normalized = tuple(_identifier(item, field_name) for item in value)
    if len(set(normalized)) != len(normalized):
        raise EvaluationSuiteError(f"duplicate_evaluation_sequence:{field_name}")
    return normalized


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="run one registered suite profile")
    check.add_argument("catalog", type=Path)
    check.add_argument("--profile", default="s18-focused")
    check.add_argument("--receipt", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = run_suite_profile(
            args.catalog,
            profile_id=args.profile,
            receipt_path=args.receipt,
        )
    except EvaluationSuiteError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "run_id": receipt["run_id"],
                "profile_id": receipt["profile_id"],
                "status": receipt["status"],
                "receipt_digest": receipt["receipt_digest"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
