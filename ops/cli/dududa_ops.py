#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from uuid import uuid4

SCHEMA_VERSION = 1
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
RESERVED_BACKUP_ROOTS = frozenset({".dududa", "backups"})


class OperationsError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}: {detail}")


class OperationFailed(OperationsError):
    def __init__(self, code: str, summary: OperationSummary) -> None:
        self.summary = summary
        super().__init__(code, summary.operation_id)


def _fail(code: str, detail: object | None = None) -> None:
    raise OperationsError(code, None if detail is None else str(detail))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        _fail("naive_operations_timestamp")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, field: str) -> str:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("invalid_operations_timestamp", field)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("naive_operations_timestamp", field)
    return _timestamp(parsed)


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise OperationsError("non_canonical_operations_value") from exc
    return encoded.encode("utf-8")


def _digest(value: object, *, domain: str) -> str:
    payload = {"domain": domain, "value": value}
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail("invalid_operations_mapping", field)
    return dict(value)


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        _fail(
            "invalid_operations_fields",
            f"{field}: missing={sorted(expected - actual)!r} unknown={sorted(actual - expected)!r}",
        )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail("invalid_operations_text", field)
    return value


def _optional_identifier(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field)


def _identifier(value: object, field: str) -> str:
    text = _text(value, field)
    if not IDENTIFIER.fullmatch(text):
        _fail("invalid_operations_identifier", field)
    return text


def _sha256(value: object, field: str) -> str:
    text = _text(value, field)
    if not DIGEST.fullmatch(text):
        _fail("invalid_operations_digest", field)
    return text


def _string_map(value: object, field: str) -> dict[str, str]:
    item = _mapping(value, field)
    result: dict[str, str] = {}
    for key, raw in sorted(item.items()):
        normalized = _identifier(key, f"{field}.key")
        result[normalized] = _text(raw, f"{field}.{key}")
    return result


def _load_json(path: Path, code: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperationsError(code, str(path)) from exc
    return _mapping(value, str(path))


def _atomic_json(path: Path, value: object, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical_bytes(value))
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_data_root(path: Path) -> Path:
    root = path.expanduser().resolve()
    if root == Path(root.anchor) or not root.name:
        _fail("unsafe_operations_data_root", root)
    return root


def _relative_path(value: object, field: str) -> Path:
    text = _text(value, field)
    path = Path(text)
    if path.is_absolute() or text in {".", ".."} or ".." in path.parts:
        _fail("unsafe_operations_relative_path", field)
    normalized = Path(*path.parts)
    if not normalized.parts:
        _fail("unsafe_operations_relative_path", field)
    return normalized


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


@dataclass(frozen=True)
class ReleaseManifest:
    release_id: str
    source_revision: str
    source_dirty: bool
    created_at: str
    previous_release_id: str | None
    data_schema_version: str
    image_references: tuple[tuple[str, str], ...]
    component_digests: tuple[tuple[str, str], ...]
    deployment_contract_digest: str
    manifest_digest: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        release_id: str,
        source_revision: str,
        source_dirty: bool,
        created_at: datetime,
        previous_release_id: str | None,
        data_schema_version: str,
        image_references: Mapping[str, str],
        component_digests: Mapping[str, str],
        deployment_contract_digest: str,
    ) -> ReleaseManifest:
        if not isinstance(source_dirty, bool):
            _fail("invalid_release_dirty_flag")
        images = _validated_images(image_references)
        components = _validated_digests(component_digests, "component_digests")
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "release_id": _identifier(release_id, "release_id"),
            "source_revision": _identifier(source_revision, "source_revision"),
            "source_dirty": source_dirty,
            "created_at": _timestamp(created_at),
            "previous_release_id": _optional_identifier(
                previous_release_id, "previous_release_id"
            ),
            "data_schema_version": _identifier(
                data_schema_version, "data_schema_version"
            ),
            "image_references": dict(images),
            "component_digests": dict(components),
            "deployment_contract_digest": _sha256(
                deployment_contract_digest, "deployment_contract_digest"
            ),
        }
        return cls._from_unsigned(unsigned)

    @classmethod
    def _from_unsigned(cls, value: Mapping[str, object]) -> ReleaseManifest:
        digest = _digest(value, domain="dududa:release-manifest:v1")
        return cls(
            release_id=str(value["release_id"]),
            source_revision=str(value["source_revision"]),
            source_dirty=bool(value["source_dirty"]),
            created_at=str(value["created_at"]),
            previous_release_id=(
                None
                if value["previous_release_id"] is None
                else str(value["previous_release_id"])
            ),
            data_schema_version=str(value["data_schema_version"]),
            image_references=tuple(
                sorted(
                    _string_map(value["image_references"], "image_references").items()
                )
            ),
            component_digests=tuple(
                sorted(
                    _string_map(value["component_digests"], "component_digests").items()
                )
            ),
            deployment_contract_digest=str(value["deployment_contract_digest"]),
            manifest_digest=digest,
        )

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "source_revision": self.source_revision,
            "source_dirty": self.source_dirty,
            "created_at": self.created_at,
            "previous_release_id": self.previous_release_id,
            "data_schema_version": self.data_schema_version,
            "image_references": dict(self.image_references),
            "component_digests": dict(self.component_digests),
            "deployment_contract_digest": self.deployment_contract_digest,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "manifest_digest": self.manifest_digest}

    @classmethod
    def from_dict(cls, value: object) -> ReleaseManifest:
        item = _mapping(value, "release_manifest")
        expected = {
            "schema_version",
            "release_id",
            "source_revision",
            "source_dirty",
            "created_at",
            "previous_release_id",
            "data_schema_version",
            "image_references",
            "component_digests",
            "deployment_contract_digest",
            "manifest_digest",
        }
        _exact_keys(item, expected, "release_manifest")
        if item["schema_version"] != SCHEMA_VERSION:
            _fail("unsupported_release_manifest_version")
        if not isinstance(item["source_dirty"], bool):
            _fail("invalid_release_dirty_flag")
        images = _validated_images(
            _string_map(item["image_references"], "image_references")
        )
        components = _validated_digests(
            _string_map(item["component_digests"], "component_digests"),
            "component_digests",
        )
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "release_id": _identifier(item["release_id"], "release_id"),
            "source_revision": _identifier(item["source_revision"], "source_revision"),
            "source_dirty": item["source_dirty"],
            "created_at": _parse_timestamp(item["created_at"], "created_at"),
            "previous_release_id": _optional_identifier(
                item["previous_release_id"], "previous_release_id"
            ),
            "data_schema_version": _identifier(
                item["data_schema_version"], "data_schema_version"
            ),
            "image_references": dict(images),
            "component_digests": dict(components),
            "deployment_contract_digest": _sha256(
                item["deployment_contract_digest"], "deployment_contract_digest"
            ),
        }
        expected_digest = _digest(unsigned, domain="dududa:release-manifest:v1")
        if _sha256(item["manifest_digest"], "manifest_digest") != expected_digest:
            _fail("release_manifest_digest_mismatch")
        return cls._from_unsigned(unsigned)


def _validated_images(value: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    if not value:
        _fail("release_images_empty")
    result: list[tuple[str, str]] = []
    for key, raw in sorted(value.items()):
        name = _identifier(key, "image_reference.key")
        reference = _text(raw, f"image_reference.{key}")
        if not IMAGE_DIGEST.fullmatch(reference):
            _fail("release_image_not_digest_pinned", key)
        result.append((name, reference))
    return tuple(result)


def _validated_digests(
    value: Mapping[str, str], field: str
) -> tuple[tuple[str, str], ...]:
    if not value:
        _fail("release_component_digests_empty")
    return tuple(
        (
            _identifier(key, f"{field}.key"),
            _sha256(raw, f"{field}.{key}"),
        )
        for key, raw in sorted(value.items())
    )


@dataclass(frozen=True)
class ReleaseState:
    revision: int
    current_release_id: str | None
    previous_release_id: str | None
    updated_at: str
    state_digest: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        revision: int,
        current_release_id: str | None,
        previous_release_id: str | None,
        updated_at: datetime,
    ) -> ReleaseState:
        if isinstance(revision, bool) or revision < 0:
            _fail("invalid_release_state_revision")
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "revision": revision,
            "current_release_id": _optional_identifier(
                current_release_id, "current_release_id"
            ),
            "previous_release_id": _optional_identifier(
                previous_release_id, "previous_release_id"
            ),
            "updated_at": _timestamp(updated_at),
        }
        return cls(
            revision=revision,
            current_release_id=unsigned["current_release_id"],
            previous_release_id=unsigned["previous_release_id"],
            updated_at=str(unsigned["updated_at"]),
            state_digest=_digest(unsigned, domain="dududa:release-state:v1"),
        )

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "current_release_id": self.current_release_id,
            "previous_release_id": self.previous_release_id,
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "state_digest": self.state_digest}

    @classmethod
    def from_dict(cls, value: object) -> ReleaseState:
        item = _mapping(value, "release_state")
        _exact_keys(
            item,
            {
                "schema_version",
                "revision",
                "current_release_id",
                "previous_release_id",
                "updated_at",
                "state_digest",
            },
            "release_state",
        )
        if item["schema_version"] != SCHEMA_VERSION:
            _fail("unsupported_release_state_version")
        revision = item["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            _fail("invalid_release_state_revision")
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "revision": revision,
            "current_release_id": _optional_identifier(
                item["current_release_id"], "current_release_id"
            ),
            "previous_release_id": _optional_identifier(
                item["previous_release_id"], "previous_release_id"
            ),
            "updated_at": _parse_timestamp(item["updated_at"], "updated_at"),
        }
        expected = _digest(unsigned, domain="dududa:release-state:v1")
        if _sha256(item["state_digest"], "state_digest") != expected:
            _fail("release_state_digest_mismatch")
        return cls(
            revision=revision,
            current_release_id=unsigned["current_release_id"],
            previous_release_id=unsigned["previous_release_id"],
            updated_at=str(unsigned["updated_at"]),
            state_digest=expected,
        )


class ReleaseStore:
    def __init__(self, data_root: Path, *, clock: Callable[[], datetime] = _utc_now):
        self.data_root = _safe_data_root(data_root)
        self.metadata_root = self.data_root / ".dududa"
        self.releases_root = self.metadata_root / "releases"
        self.receipts_root = self.metadata_root / "receipts"
        self.staging_root = self.metadata_root / "staging"
        self.backups_root = self.data_root / "backups"
        self.state_path = self.metadata_root / "state.json"
        self._clock = clock

    def bootstrap(self) -> ReleaseState:
        for path in (
            self.data_root,
            self.data_root / "astrbot",
            self.data_root / "astrbot" / "plugins",
            self.data_root / "napcat",
            self.data_root / "napcat" / "config",
            self.data_root / "napcat" / "ntqq",
            self.metadata_root,
            self.releases_root,
            self.receipts_root,
            self.staging_root,
            self.backups_root,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path, 0o700)
        if not self.state_path.exists():
            initial = ReleaseState.create(
                revision=0,
                current_release_id=None,
                previous_release_id=None,
                updated_at=self._clock(),
            )
            _atomic_json(self.state_path, initial.to_dict())
        return self.state()

    def state(self) -> ReleaseState:
        if not self.state_path.is_file() or self.state_path.is_symlink():
            _fail("release_state_missing")
        return ReleaseState.from_dict(
            _load_json(self.state_path, "release_state_unreadable")
        )

    def manifest_path(self, release_id: str) -> Path:
        return (
            self.releases_root / _identifier(release_id, "release_id") / "manifest.json"
        )

    def publish_manifest(self, manifest: ReleaseManifest) -> Path:
        self.bootstrap()
        path = self.manifest_path(manifest.release_id)
        if path.exists():
            current = ReleaseManifest.from_dict(
                _load_json(path, "release_manifest_unreadable")
            )
            if current.manifest_digest != manifest.manifest_digest:
                _fail("release_manifest_id_collision", manifest.release_id)
            return path
        path.parent.mkdir(parents=True, mode=0o700)
        _atomic_json(path, manifest.to_dict())
        return path

    def load_manifest(self, release_id: str) -> ReleaseManifest:
        path = self.manifest_path(release_id)
        if not path.is_file() or path.is_symlink():
            _fail("release_manifest_missing", release_id)
        return ReleaseManifest.from_dict(
            _load_json(path, "release_manifest_unreadable")
        )

    def promote(
        self,
        release_id: str,
        *,
        expected_current: str | None,
        previous_release_id: str | None = None,
    ) -> ReleaseState:
        self.load_manifest(release_id)
        current = self.state()
        if current.current_release_id != expected_current:
            _fail("release_state_conflict")
        previous = (
            expected_current if previous_release_id is None else previous_release_id
        )
        next_state = ReleaseState.create(
            revision=current.revision + 1,
            current_release_id=release_id,
            previous_release_id=previous,
            updated_at=self._clock(),
        )
        observed = self.state()
        if observed.state_digest != current.state_digest:
            _fail("release_state_conflict")
        _atomic_json(self.state_path, next_state.to_dict())
        return next_state

    def receipt_directory(self, operation_id: str) -> Path:
        return self.receipts_root / _identifier(operation_id, "operation_id")

    def write_stage_receipt(self, receipt: StageReceipt) -> Path:
        directory = self.receipt_directory(receipt.operation_id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = (
            directory / f"{receipt.sequence:04d}-{receipt.stage}-{receipt.status}.json"
        )
        if path.exists():
            existing = _load_json(path, "stage_receipt_unreadable")
            if existing != receipt.to_dict():
                _fail("stage_receipt_collision", path)
            return path
        _atomic_json(path, receipt.to_dict())
        return path

    def write_summary(self, summary: OperationSummary) -> Path:
        directory = self.receipt_directory(summary.operation_id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / "summary.json"
        if path.exists():
            existing = _load_json(path, "operation_summary_unreadable")
            if existing != summary.to_dict():
                _fail("operation_summary_collision", path)
            return path
        _atomic_json(path, summary.to_dict())
        return path


@dataclass(frozen=True)
class HealthCheck:
    check_id: str
    status: str
    reason_code: str
    evidence_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "evidence_digest": self.evidence_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> HealthCheck:
        item = _mapping(value, "health_check")
        _exact_keys(
            item,
            {"check_id", "status", "reason_code", "evidence_digest"},
            "health_check",
        )
        status_value = _text(item["status"], "health_check.status")
        if status_value not in {"healthy", "degraded", "unhealthy"}:
            _fail("invalid_health_status")
        return cls(
            check_id=_identifier(item["check_id"], "health_check.check_id"),
            status=status_value,
            reason_code=_identifier(item["reason_code"], "health_check.reason_code"),
            evidence_digest=_sha256(
                item["evidence_digest"], "health_check.evidence_digest"
            ),
        )


@dataclass(frozen=True)
class HealthReport:
    release_id: str
    status: str
    observed_at: str
    checks: tuple[HealthCheck, ...]
    report_digest: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        release_id: str,
        observed_at: datetime,
        checks: Sequence[HealthCheck],
    ) -> HealthReport:
        normalized = tuple(sorted(checks, key=lambda item: item.check_id))
        if not normalized or len({item.check_id for item in normalized}) != len(
            normalized
        ):
            _fail("invalid_health_checks")
        status_value = "healthy"
        if any(item.status == "unhealthy" for item in normalized):
            status_value = "unhealthy"
        elif any(item.status == "degraded" for item in normalized):
            status_value = "degraded"
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "release_id": _identifier(release_id, "health.release_id"),
            "status": status_value,
            "observed_at": _timestamp(observed_at),
            "checks": [item.to_dict() for item in normalized],
        }
        return cls(
            release_id=str(unsigned["release_id"]),
            status=status_value,
            observed_at=str(unsigned["observed_at"]),
            checks=normalized,
            report_digest=_digest(unsigned, domain="dududa:health-report:v1"),
        )

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "status": self.status,
            "observed_at": self.observed_at,
            "checks": [item.to_dict() for item in self.checks],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "report_digest": self.report_digest}

    @classmethod
    def from_dict(cls, value: object) -> HealthReport:
        item = _mapping(value, "health_report")
        _exact_keys(
            item,
            {
                "schema_version",
                "release_id",
                "status",
                "observed_at",
                "checks",
                "report_digest",
            },
            "health_report",
        )
        if item["schema_version"] != SCHEMA_VERSION:
            _fail("unsupported_health_report_version")
        raw_checks = item["checks"]
        if not isinstance(raw_checks, list):
            _fail("invalid_health_checks")
        checks = tuple(HealthCheck.from_dict(raw) for raw in raw_checks)
        observed = datetime.fromisoformat(
            _parse_timestamp(item["observed_at"], "health.observed_at").replace(
                "Z", "+00:00"
            )
        )
        result = cls.create(
            release_id=_identifier(item["release_id"], "health.release_id"),
            observed_at=observed,
            checks=checks,
        )
        if item["status"] != result.status:
            _fail("health_status_mismatch")
        if (
            _sha256(item["report_digest"], "health.report_digest")
            != result.report_digest
        ):
            _fail("health_report_digest_mismatch")
        return result


@dataclass(frozen=True)
class BackupEntry:
    relative_path: str
    kind: str
    size: int
    mode: int
    content_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "kind": self.kind,
            "size": self.size,
            "mode": self.mode,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> BackupEntry:
        item = _mapping(value, "backup_entry")
        _exact_keys(
            item,
            {"relative_path", "kind", "size", "mode", "content_digest"},
            "backup_entry",
        )
        relative = _relative_path(item["relative_path"], "backup_entry.relative_path")
        kind = _text(item["kind"], "backup_entry.kind")
        if kind not in {"file", "sqlite"}:
            _fail("invalid_backup_entry_kind")
        size = item["size"]
        mode = item["mode"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            _fail("invalid_backup_entry_size")
        if (
            isinstance(mode, bool)
            or not isinstance(mode, int)
            or not 0 <= mode <= 0o777
        ):
            _fail("invalid_backup_entry_mode")
        return cls(
            relative_path=relative.as_posix(),
            kind=kind,
            size=size,
            mode=mode,
            content_digest=_sha256(
                item["content_digest"], "backup_entry.content_digest"
            ),
        )


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    release_id: str
    created_at: str
    entries: tuple[BackupEntry, ...]
    manifest_digest: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        backup_id: str,
        release_id: str,
        created_at: datetime,
        entries: Sequence[BackupEntry],
    ) -> BackupManifest:
        normalized = tuple(sorted(entries, key=lambda item: item.relative_path))
        if not normalized or len({item.relative_path for item in normalized}) != len(
            normalized
        ):
            _fail("invalid_backup_entries")
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "backup_id": _identifier(backup_id, "backup_id"),
            "release_id": _identifier(release_id, "backup.release_id"),
            "created_at": _timestamp(created_at),
            "entries": [item.to_dict() for item in normalized],
        }
        return cls(
            backup_id=str(unsigned["backup_id"]),
            release_id=str(unsigned["release_id"]),
            created_at=str(unsigned["created_at"]),
            entries=normalized,
            manifest_digest=_digest(unsigned, domain="dududa:backup-manifest:v1"),
        )

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "backup_id": self.backup_id,
            "release_id": self.release_id,
            "created_at": self.created_at,
            "entries": [item.to_dict() for item in self.entries],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "manifest_digest": self.manifest_digest}

    @classmethod
    def from_dict(cls, value: object) -> BackupManifest:
        item = _mapping(value, "backup_manifest")
        _exact_keys(
            item,
            {
                "schema_version",
                "backup_id",
                "release_id",
                "created_at",
                "entries",
                "manifest_digest",
            },
            "backup_manifest",
        )
        if item["schema_version"] != SCHEMA_VERSION:
            _fail("unsupported_backup_manifest_version")
        raw_entries = item["entries"]
        if not isinstance(raw_entries, list):
            _fail("invalid_backup_entries")
        created_at = datetime.fromisoformat(
            _parse_timestamp(item["created_at"], "backup.created_at").replace(
                "Z", "+00:00"
            )
        )
        result = cls.create(
            backup_id=_identifier(item["backup_id"], "backup_id"),
            release_id=_identifier(item["release_id"], "backup.release_id"),
            created_at=created_at,
            entries=tuple(BackupEntry.from_dict(raw) for raw in raw_entries),
        )
        if (
            _sha256(item["manifest_digest"], "backup.manifest_digest")
            != result.manifest_digest
        ):
            _fail("backup_manifest_digest_mismatch")
        return result


@dataclass(frozen=True)
class RestorePlan:
    backup_id: str
    backup_manifest_digest: str
    destination: str
    entries: tuple[BackupEntry, ...]
    plan_digest: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(cls, manifest: BackupManifest, destination: Path) -> RestorePlan:
        resolved = destination.expanduser().resolve()
        if resolved == Path(resolved.anchor):
            _fail("unsafe_restore_destination")
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "backup_id": manifest.backup_id,
            "backup_manifest_digest": manifest.manifest_digest,
            "destination": str(resolved),
            "entries": [item.to_dict() for item in manifest.entries],
        }
        return cls(
            backup_id=manifest.backup_id,
            backup_manifest_digest=manifest.manifest_digest,
            destination=str(resolved),
            entries=manifest.entries,
            plan_digest=_digest(unsigned, domain="dududa:restore-plan:v1"),
        )

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "backup_id": self.backup_id,
            "backup_manifest_digest": self.backup_manifest_digest,
            "destination": self.destination,
            "entries": [item.to_dict() for item in self.entries],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "plan_digest": self.plan_digest}


class BackupManager:
    def __init__(
        self, store: ReleaseStore, *, clock: Callable[[], datetime] = _utc_now
    ):
        self.store = store
        self._clock = clock

    def create(
        self,
        *,
        backup_id: str,
        release_id: str,
        includes: Sequence[str | Path],
    ) -> BackupManifest:
        self.store.bootstrap()
        self.store.load_manifest(release_id)
        backup_name = _identifier(backup_id, "backup_id")
        final = self.store.backups_root / backup_name
        if final.exists():
            _fail("backup_id_collision", backup_name)
        selected = self._inventory(includes)
        staging = self.store.backups_root / f".{backup_name}.staging-{uuid4().hex}"
        staging.mkdir(mode=0o700)
        try:
            entries: list[BackupEntry] = []
            for relative, source in selected:
                destination = staging / "payload" / relative
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                kind = "sqlite" if _is_sqlite(source) else "file"
                if kind == "sqlite":
                    _backup_sqlite(source, destination)
                else:
                    shutil.copy2(source, destination, follow_symlinks=False)
                mode = stat.S_IMODE(source.stat(follow_symlinks=False).st_mode)
                os.chmod(destination, mode)
                entries.append(
                    BackupEntry(
                        relative.as_posix(),
                        kind,
                        destination.stat().st_size,
                        mode,
                        _file_digest(destination),
                    )
                )
            manifest = BackupManifest.create(
                backup_id=backup_name,
                release_id=release_id,
                created_at=self._clock(),
                entries=entries,
            )
            _atomic_json(staging / "manifest.json", manifest.to_dict())
            self._verify_at(staging, manifest)
            os.replace(staging, final)
            _fsync_directory(final.parent)
            return manifest
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def verify(self, backup_id: str) -> BackupManifest:
        root = self.store.backups_root / _identifier(backup_id, "backup_id")
        if not root.is_dir() or root.is_symlink():
            _fail("backup_missing", backup_id)
        manifest = BackupManifest.from_dict(
            _load_json(root / "manifest.json", "backup_manifest_unreadable")
        )
        if manifest.backup_id != backup_id:
            _fail("backup_id_mismatch")
        self._verify_at(root, manifest)
        return manifest

    def plan_restore(self, *, backup_id: str, destination: Path) -> RestorePlan:
        manifest = self.verify(backup_id)
        resolved = destination.expanduser().resolve()
        if _paths_overlap(resolved, self.store.backups_root.resolve()):
            _fail("restore_destination_overlaps_backups")
        return RestorePlan.create(manifest, resolved)

    def restore(self, plan: RestorePlan) -> Path:
        manifest = self.verify(plan.backup_id)
        expected_plan = RestorePlan.create(manifest, Path(plan.destination))
        if expected_plan.plan_digest != plan.plan_digest:
            _fail("restore_plan_digest_mismatch")
        destination = Path(plan.destination)
        if destination.exists():
            if not destination.is_dir() or destination.is_symlink():
                _fail("restore_destination_not_empty")
            try:
                next(destination.iterdir())
            except StopIteration:
                pass
            else:
                _fail("restore_destination_not_empty")
        staging = destination.parent / f".{destination.name}.restore-{uuid4().hex}"
        if staging.exists():
            _fail("restore_staging_collision")
        staging.mkdir(parents=True, mode=0o700)
        backup_root = self.store.backups_root / manifest.backup_id / "payload"
        try:
            for entry in manifest.entries:
                relative = _relative_path(entry.relative_path, "restore.relative_path")
                source = backup_root / relative
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(source, target, follow_symlinks=False)
                os.chmod(target, entry.mode)
                if _file_digest(target) != entry.content_digest:
                    _fail("restored_file_digest_mismatch", relative)
                if entry.kind == "sqlite":
                    _check_sqlite(target)
            if destination.exists():
                destination.rmdir()
            os.replace(staging, destination)
            _fsync_directory(destination.parent)
            return destination
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _inventory(
        self, includes: Sequence[str | Path]
    ) -> tuple[tuple[Path, Path], ...]:
        if not includes:
            _fail("backup_includes_empty")
        result: dict[str, tuple[Path, Path]] = {}
        root = self.store.data_root
        for raw in includes:
            relative = _relative_path(str(raw), "backup.include")
            if relative.parts[0] in RESERVED_BACKUP_ROOTS:
                _fail("backup_include_reserved", relative)
            source = root / relative
            if source.is_symlink():
                _fail("backup_symlink_rejected", relative)
            if source.is_file():
                result[relative.as_posix()] = (relative, source)
                continue
            if not source.is_dir():
                _fail("backup_source_missing", relative)
            for item in sorted(source.rglob("*"), key=lambda path: path.as_posix()):
                nested = item.relative_to(root)
                if item.is_symlink():
                    _fail("backup_symlink_rejected", nested)
                if item.is_file():
                    result[nested.as_posix()] = (nested, item)
        if not result:
            _fail("backup_inventory_empty")
        return tuple(result[key] for key in sorted(result))

    def _verify_at(self, root: Path, manifest: BackupManifest) -> None:
        expected: set[str] = set()
        payload = root / "payload"
        for entry in manifest.entries:
            relative = _relative_path(entry.relative_path, "backup.relative_path")
            expected.add(relative.as_posix())
            path = payload / relative
            if not path.is_file() or path.is_symlink():
                _fail("backup_file_missing", relative)
            if (
                path.stat().st_size != entry.size
                or _file_digest(path) != entry.content_digest
            ):
                _fail("backup_digest_mismatch", relative)
            if entry.kind == "sqlite":
                _check_sqlite(path)
        actual = {
            path.relative_to(payload).as_posix()
            for path in payload.rglob("*")
            if path.is_file()
        }
        if actual != expected:
            _fail("backup_payload_inventory_mismatch")


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(16) == b"SQLite format 3\x00"
    except OSError as exc:
        raise OperationsError("backup_source_unreadable", str(path)) from exc


def _backup_sqlite(source: Path, destination: Path) -> None:
    uri = "file:" + quote(str(source.resolve()), safe="/") + "?mode=ro"
    try:
        with (
            sqlite3.connect(uri, uri=True) as source_db,
            sqlite3.connect(destination) as destination_db,
        ):
            source_db.backup(destination_db)
        with sqlite3.connect(destination) as destination_db:
            destination_db.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error as exc:
        raise OperationsError("sqlite_backup_failed", str(source)) from exc
    _check_sqlite(destination)


def _check_sqlite(path: Path) -> None:
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro&immutable=1"
    try:
        with sqlite3.connect(uri, uri=True) as database:
            row = database.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        raise OperationsError("sqlite_backup_invalid", str(path)) from exc
    if row != ("ok",):
        _fail("sqlite_backup_invalid", path)


@dataclass(frozen=True)
class StageReceipt:
    operation_id: str
    sequence: int
    operation: str
    release_id: str
    previous_release_id: str | None
    stage: str
    status: str
    observed_at: str
    evidence_digest: str | None
    reason_code: str | None
    receipt_digest: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        sequence: int,
        operation: str,
        release_id: str,
        previous_release_id: str | None,
        stage: str,
        status: str,
        observed_at: datetime,
        evidence_digest: str | None = None,
        reason_code: str | None = None,
    ) -> StageReceipt:
        if isinstance(sequence, bool) or sequence < 1:
            _fail("invalid_stage_receipt_sequence")
        if status not in {"started", "succeeded", "failed"}:
            _fail("invalid_stage_receipt_status")
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": _identifier(operation_id, "operation_id"),
            "sequence": sequence,
            "operation": _identifier(operation, "operation"),
            "release_id": _identifier(release_id, "receipt.release_id"),
            "previous_release_id": _optional_identifier(
                previous_release_id, "receipt.previous_release_id"
            ),
            "stage": _identifier(stage, "stage"),
            "status": status,
            "observed_at": _timestamp(observed_at),
            "evidence_digest": (
                None
                if evidence_digest is None
                else _sha256(evidence_digest, "evidence_digest")
            ),
            "reason_code": (
                None if reason_code is None else _identifier(reason_code, "reason_code")
            ),
        }
        return cls(
            operation_id=str(unsigned["operation_id"]),
            sequence=sequence,
            operation=str(unsigned["operation"]),
            release_id=str(unsigned["release_id"]),
            previous_release_id=unsigned["previous_release_id"],
            stage=str(unsigned["stage"]),
            status=status,
            observed_at=str(unsigned["observed_at"]),
            evidence_digest=unsigned["evidence_digest"],
            reason_code=unsigned["reason_code"],
            receipt_digest=_digest(unsigned, domain="dududa:stage-receipt:v1"),
        )

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "sequence": self.sequence,
            "operation": self.operation,
            "release_id": self.release_id,
            "previous_release_id": self.previous_release_id,
            "stage": self.stage,
            "status": self.status,
            "observed_at": self.observed_at,
            "evidence_digest": self.evidence_digest,
            "reason_code": self.reason_code,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "receipt_digest": self.receipt_digest}


@dataclass(frozen=True)
class OperationSummary:
    operation_id: str
    operation: str
    release_id: str
    previous_release_id: str | None
    status: str
    backup_id: str | None
    stage_receipt_digests: tuple[str, ...]
    completed_at: str
    summary_digest: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        operation: str,
        release_id: str,
        previous_release_id: str | None,
        status: str,
        backup_id: str | None,
        receipts: Sequence[StageReceipt],
        completed_at: datetime,
    ) -> OperationSummary:
        if status not in {"succeeded", "failed", "rolled_back", "recovery_failed"}:
            _fail("invalid_operation_summary_status")
        receipt_digests = tuple(receipt.receipt_digest for receipt in receipts)
        if not receipt_digests:
            _fail("operation_summary_receipts_empty")
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": _identifier(operation_id, "operation_id"),
            "operation": _identifier(operation, "operation"),
            "release_id": _identifier(release_id, "summary.release_id"),
            "previous_release_id": _optional_identifier(
                previous_release_id, "summary.previous_release_id"
            ),
            "status": status,
            "backup_id": (
                None if backup_id is None else _identifier(backup_id, "backup_id")
            ),
            "stage_receipt_digests": [
                _sha256(value, "stage_receipt_digest") for value in receipt_digests
            ],
            "completed_at": _timestamp(completed_at),
        }
        return cls(
            operation_id=str(unsigned["operation_id"]),
            operation=str(unsigned["operation"]),
            release_id=str(unsigned["release_id"]),
            previous_release_id=unsigned["previous_release_id"],
            status=status,
            backup_id=unsigned["backup_id"],
            stage_receipt_digests=receipt_digests,
            completed_at=str(unsigned["completed_at"]),
            summary_digest=_digest(unsigned, domain="dududa:operation-summary:v1"),
        )

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "operation": self.operation,
            "release_id": self.release_id,
            "previous_release_id": self.previous_release_id,
            "status": self.status,
            "backup_id": self.backup_id,
            "stage_receipt_digests": list(self.stage_receipt_digests),
            "completed_at": self.completed_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "summary_digest": self.summary_digest}


class OperationsDriver(Protocol):
    def prepare(self, manifest: ReleaseManifest) -> object: ...

    def start(self, manifest: ReleaseManifest) -> object: ...

    def health(self, manifest: ReleaseManifest) -> HealthReport: ...

    def rollback(self, manifest: ReleaseManifest) -> object: ...


class _Journal:
    def __init__(
        self,
        store: ReleaseStore,
        *,
        operation_id: str,
        operation: str,
        release_id: str,
        previous_release_id: str | None,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.operation_id = _identifier(operation_id, "operation_id")
        self.operation = _identifier(operation, "operation")
        self.release_id = _identifier(release_id, "release_id")
        self.previous_release_id = _optional_identifier(
            previous_release_id, "previous_release_id"
        )
        self.clock = clock
        self.receipts: list[StageReceipt] = []

    def record(
        self,
        stage: str,
        status: str,
        *,
        evidence: object | None = None,
        reason_code: str | None = None,
    ) -> StageReceipt:
        evidence_digest = (
            None
            if evidence is None
            else _digest(evidence, domain=f"dududa:operation-evidence:{stage}:v1")
        )
        receipt = StageReceipt.create(
            operation_id=self.operation_id,
            sequence=len(self.receipts) + 1,
            operation=self.operation,
            release_id=self.release_id,
            previous_release_id=self.previous_release_id,
            stage=stage,
            status=status,
            observed_at=self.clock(),
            evidence_digest=evidence_digest,
            reason_code=reason_code,
        )
        self.store.write_stage_receipt(receipt)
        self.receipts.append(receipt)
        return receipt

    def finish(self, status: str, *, backup_id: str | None) -> OperationSummary:
        summary = OperationSummary.create(
            operation_id=self.operation_id,
            operation=self.operation,
            release_id=self.release_id,
            previous_release_id=self.previous_release_id,
            status=status,
            backup_id=backup_id,
            receipts=self.receipts,
            completed_at=self.clock(),
        )
        self.store.write_summary(summary)
        return summary


class OperationsCoordinator:
    def __init__(
        self,
        store: ReleaseStore,
        backup: BackupManager,
        driver: OperationsDriver,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.store = store
        self.backup = backup
        self.driver = driver
        self._clock = clock

    def health(self, release_id: str | None = None) -> HealthReport:
        state = self.store.state()
        selected = release_id or state.current_release_id
        if selected is None:
            _fail("current_release_missing")
        manifest = self.store.load_manifest(selected)
        return self.driver.health(manifest)

    def start_release(
        self, manifest: ReleaseManifest, *, operation_id: str
    ) -> OperationSummary:
        self.store.publish_manifest(manifest)
        state = self.store.state()
        if state.current_release_id is not None:
            _fail("start_requires_empty_release_state")
        if manifest.source_dirty:
            _fail("dirty_release_rejected")
        if manifest.previous_release_id != state.current_release_id:
            _fail("release_previous_mismatch")
        journal = _Journal(
            self.store,
            operation_id=operation_id,
            operation="start",
            release_id=manifest.release_id,
            previous_release_id=state.current_release_id,
            clock=self._clock,
        )
        stage = "start"
        try:
            journal.record(stage, "started")
            evidence = self.driver.start(manifest)
            journal.record(stage, "succeeded", evidence=evidence)
            stage = "health"
            journal.record(stage, "started")
            report = self.driver.health(manifest)
            if report.status != "healthy":
                _fail("release_health_not_healthy", report.status)
            journal.record(stage, "succeeded", evidence=report.to_dict())
            self.store.promote(
                manifest.release_id,
                expected_current=state.current_release_id,
            )
            journal.record("promote", "succeeded", evidence=manifest.manifest_digest)
            return journal.finish("succeeded", backup_id=None)
        except BaseException as exc:
            journal.record(stage, "failed", reason_code=_reason_code(exc))
            summary = journal.finish("failed", backup_id=None)
            raise OperationFailed("start_release_failed", summary) from exc

    def upgrade(
        self,
        manifest: ReleaseManifest,
        *,
        operation_id: str,
        backup_id: str,
        includes: Sequence[str | Path],
    ) -> OperationSummary:
        self.store.publish_manifest(manifest)
        state = self.store.state()
        if manifest.source_dirty:
            _fail("dirty_release_rejected")
        previous_id = state.current_release_id
        if previous_id is None:
            _fail("upgrade_requires_current_release")
        if manifest.previous_release_id != previous_id:
            _fail("release_previous_mismatch")
        previous = self.store.load_manifest(previous_id)
        journal = _Journal(
            self.store,
            operation_id=operation_id,
            operation="upgrade",
            release_id=manifest.release_id,
            previous_release_id=previous_id,
            clock=self._clock,
        )
        stage = "backup"
        started_target = False
        backup_name: str | None = None
        try:
            journal.record(stage, "started")
            backup_manifest = self.backup.create(
                backup_id=backup_id,
                release_id=previous_id,
                includes=includes,
            )
            backup_name = backup_manifest.backup_id
            journal.record(
                stage,
                "succeeded",
                evidence=backup_manifest.manifest_digest,
            )
            stage = "prepare"
            journal.record(stage, "started")
            evidence = self.driver.prepare(manifest)
            journal.record(stage, "succeeded", evidence=evidence)
            stage = "start"
            journal.record(stage, "started")
            evidence = self.driver.start(manifest)
            started_target = True
            journal.record(stage, "succeeded", evidence=evidence)
            stage = "health"
            journal.record(stage, "started")
            report = self.driver.health(manifest)
            if report.status != "healthy":
                _fail("release_health_not_healthy", report.status)
            journal.record(stage, "succeeded", evidence=report.to_dict())
            self.store.promote(manifest.release_id, expected_current=previous_id)
            journal.record("promote", "succeeded", evidence=manifest.manifest_digest)
            return journal.finish("succeeded", backup_id=backup_name)
        except BaseException as exc:
            journal.record(stage, "failed", reason_code=_reason_code(exc))
            if not started_target:
                summary = journal.finish("failed", backup_id=backup_name)
                raise OperationFailed("upgrade_failed", summary) from exc
            try:
                recovery_stage = "rollback"
                journal.record(recovery_stage, "started")
                evidence = self.driver.rollback(previous)
                journal.record(recovery_stage, "succeeded", evidence=evidence)
                recovery_stage = "rollback-health"
                journal.record(recovery_stage, "started")
                report = self.driver.health(previous)
                if report.status != "healthy":
                    _fail("rollback_health_not_healthy", report.status)
                journal.record(recovery_stage, "succeeded", evidence=report.to_dict())
                summary = journal.finish("rolled_back", backup_id=backup_name)
                raise OperationFailed("upgrade_rolled_back", summary) from exc
            except OperationFailed:
                raise
            except BaseException as rollback_exc:
                journal.record(
                    recovery_stage,
                    "failed",
                    reason_code=_reason_code(rollback_exc),
                )
                summary = journal.finish("recovery_failed", backup_id=backup_name)
                raise OperationFailed(
                    "upgrade_recovery_failed", summary
                ) from rollback_exc

    def rollback(self, *, operation_id: str) -> OperationSummary:
        state = self.store.state()
        current_id = state.current_release_id
        previous_id = state.previous_release_id
        if current_id is None or previous_id is None:
            _fail("rollback_release_missing")
        previous = self.store.load_manifest(previous_id)
        journal = _Journal(
            self.store,
            operation_id=operation_id,
            operation="rollback",
            release_id=current_id,
            previous_release_id=previous_id,
            clock=self._clock,
        )
        stage = "rollback"
        try:
            journal.record(stage, "started")
            evidence = self.driver.rollback(previous)
            journal.record(stage, "succeeded", evidence=evidence)
            stage = "health"
            journal.record(stage, "started")
            report = self.driver.health(previous)
            if report.status != "healthy":
                _fail("rollback_health_not_healthy", report.status)
            journal.record(stage, "succeeded", evidence=report.to_dict())
            self.store.promote(
                previous_id,
                expected_current=current_id,
                previous_release_id=current_id,
            )
            journal.record("promote", "succeeded", evidence=previous.manifest_digest)
            return journal.finish("succeeded", backup_id=None)
        except BaseException as exc:
            journal.record(stage, "failed", reason_code=_reason_code(exc))
            summary = journal.finish("failed", backup_id=None)
            raise OperationFailed("rollback_failed", summary) from exc


def _reason_code(exc: BaseException) -> str:
    if isinstance(exc, OperationsError):
        return exc.code
    return "operations_driver_failed"


class LocalHealthDriver:
    def __init__(
        self,
        store: ReleaseStore,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.store = store
        self._clock = clock

    def prepare(self, manifest: ReleaseManifest) -> object:
        _fail("deployment_driver_not_configured")

    def start(self, manifest: ReleaseManifest) -> object:
        _fail("deployment_driver_not_configured")

    def health(self, manifest: ReleaseManifest) -> HealthReport:
        checks = (
            HealthCheck(
                "release-store",
                "healthy",
                "release-manifest-verified",
                manifest.manifest_digest,
            ),
            HealthCheck(
                "deployment",
                "degraded",
                "deployment-probe-not-configured",
                _digest({}, domain="dududa:deployment-probe:missing:v1"),
            ),
        )
        return HealthReport.create(
            release_id=manifest.release_id,
            observed_at=self._clock(),
            checks=checks,
        )

    def rollback(self, manifest: ReleaseManifest) -> object:
        _fail("deployment_driver_not_configured")


class CommandOperationsDriver:
    def __init__(
        self,
        commands: Mapping[str, Sequence[str]],
        *,
        cwd: Path,
        store: ReleaseStore,
    ) -> None:
        self.commands = {key: tuple(value) for key, value in commands.items()}
        self.cwd = cwd.resolve()
        self.store = store

    def prepare(self, manifest: ReleaseManifest) -> object:
        return self._run("prepare", manifest)

    def start(self, manifest: ReleaseManifest) -> object:
        return self._run("start", manifest)

    def health(self, manifest: ReleaseManifest) -> HealthReport:
        result = self._run_process("health", manifest)
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise OperationsError("driver_health_output_invalid") from exc
        report = HealthReport.from_dict(value)
        if report.release_id != manifest.release_id:
            _fail("driver_health_release_mismatch")
        return report

    def rollback(self, manifest: ReleaseManifest) -> object:
        return self._run("rollback", manifest)

    def _run(self, stage: str, manifest: ReleaseManifest) -> object:
        result = self._run_process(stage, manifest)
        return {
            "stage": stage,
            "stdout_digest": "sha256:"
            + hashlib.sha256(result.stdout.encode()).hexdigest(),
            "stderr_digest": "sha256:"
            + hashlib.sha256(result.stderr.encode()).hexdigest(),
        }

    def _run_process(
        self, stage: str, manifest: ReleaseManifest
    ) -> subprocess.CompletedProcess[str]:
        raw = self.commands.get(stage)
        if not raw:
            _fail("driver_stage_command_missing", stage)
        substitutions = {
            "{release_id}": manifest.release_id,
            "{previous_release_id}": manifest.previous_release_id or "",
            "{manifest_path}": str(self.store.manifest_path(manifest.release_id)),
            "{data_root}": str(self.store.data_root),
        }
        command: list[str] = []
        for argument in raw:
            value = argument
            for marker, replacement in substitutions.items():
                value = value.replace(marker, replacement)
            command.append(value)
        try:
            return subprocess.run(
                command,
                cwd=self.cwd,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise OperationsError("driver_stage_command_failed", stage) from exc


def load_driver_plan(path: Path) -> dict[str, tuple[str, ...]]:
    value = _load_json(path, "driver_plan_unreadable")
    allowed = {"prepare", "start", "health", "rollback"}
    if not set(value).issubset(allowed):
        _fail("driver_plan_unknown_stage")
    result: dict[str, tuple[str, ...]] = {}
    for stage, raw in value.items():
        if (
            not isinstance(raw, list)
            or not raw
            or not all(isinstance(argument, str) and argument for argument in raw)
        ):
            _fail("driver_plan_invalid_command", stage)
        result[stage] = tuple(raw)
    return result


def validate_compose_contract(value: object) -> dict[str, object]:
    root = _mapping(value, "compose")
    services = _mapping(root.get("services"), "compose.services")
    protocol_services = {"napcat", "llbot"}.intersection(services)
    required_services = {"web", "astrbot"} | protocol_services
    if not protocol_services or not required_services.issubset(services):
        _fail("compose_required_service_missing")
    for name in sorted(required_services):
        service = _mapping(services[name], f"compose.services.{name}")
        networks = service.get("networks")
        if isinstance(networks, list):
            network_names = set(networks)
        else:
            network_names = set(_mapping(networks, f"compose.{name}.networks"))
        if not {"bot_net", "edge"}.issubset(network_names):
            _fail("compose_network_boundary_missing", name)
        for port in service.get("ports", []):
            if not isinstance(port, dict):
                _fail("compose_port_shape_invalid", name)
            host_ip = port.get("host_ip") or port.get("host_ip_address")
            if host_ip not in {"127.0.0.1", "::1"}:
                _fail("compose_port_not_loopback", name)
    astrbot = _mapping(services["astrbot"], "compose.astrbot")
    astrbot_mounts = _mount_map(astrbot.get("volumes", []), "astrbot")
    for target in (
        "/opt/dududa/config",
        "/opt/dududa/scripts",
        "/AstrBot/data/icourse-mcp",
    ):
        if astrbot_mounts.get(target) is not True:
            _fail("compose_source_mount_not_read_only", target)
    if astrbot_mounts.get("/AstrBot/data") is not False:
        _fail("compose_runtime_mount_not_writable", "astrbot")
    for name in protocol_services:
        service = _mapping(services[name], f"compose.{name}")
        mounts = _mount_map(service.get("volumes", []), name)
        targets = ("/app/llbot/data",) if name == "llbot" else ("/AstrBot/data", "/app/napcat/config", "/app/.config/QQ")
        for target in targets:
            if mounts.get(target) is not False:
                _fail("compose_runtime_mount_not_writable", target)
        if name == "llbot" and mounts.get("/AstrBot/data") is not True:
            _fail("compose_source_mount_not_read_only", "/AstrBot/data")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "services": sorted(required_services),
        "loopback_ports": True,
        "source_mounts_read_only": True,
        "runtime_mounts_writable": True,
        "networks": ["bot_net", "edge"],
    }
    return {
        **summary,
        "contract_digest": _digest(summary, domain="dududa:compose-contract:v1"),
    }


def _mount_map(value: object, service: str) -> dict[str, bool]:
    if not isinstance(value, list):
        _fail("compose_volumes_invalid", service)
    result: dict[str, bool] = {}
    for mount in value:
        if not isinstance(mount, dict):
            _fail("compose_volume_shape_invalid", service)
        target = mount.get("target")
        if not isinstance(target, str):
            _fail("compose_volume_target_invalid", service)
        read_only = mount.get("read_only", False)
        if not isinstance(read_only, bool):
            _fail("compose_volume_read_only_invalid", target)
        result[target] = read_only
    return result


def _pairs(values: Sequence[str], *, digest_values: bool) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            _fail("invalid_key_value_argument", raw)
        key, value = raw.split("=", 1)
        normalized = _identifier(key, "key_value.key")
        if normalized in result:
            _fail("duplicate_key_value_argument", normalized)
        result[normalized] = (
            _sha256(value, f"key_value.{key}") if digest_values else _text(value, key)
        )
    return result


def _driver(args: argparse.Namespace, store: ReleaseStore) -> OperationsDriver:
    plan = getattr(args, "driver_plan", None)
    if plan is None:
        return LocalHealthDriver(store)
    return CommandOperationsDriver(
        load_driver_plan(plan),
        cwd=getattr(args, "driver_cwd", Path.cwd()),
        store=store,
    )


def _manifest_from_args(args: argparse.Namespace) -> ReleaseManifest:
    return ReleaseManifest.create(
        release_id=args.release_id,
        source_revision=args.source_revision,
        source_dirty=args.source_dirty,
        created_at=_utc_now(),
        previous_release_id=args.previous_release_id,
        data_schema_version=args.data_schema_version,
        image_references=_pairs(args.image, digest_values=False),
        component_digests=_pairs(args.component, digest_values=True),
        deployment_contract_digest=args.deployment_contract_digest,
    )


def _add_data_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-root", required=True, type=Path)


def _add_driver(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--driver-plan", type=Path)
    parser.add_argument("--driver-cwd", type=Path, default=Path.cwd())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dududa versioned release, backup and rollback operations."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser("bootstrap")
    _add_data_root(bootstrap)

    state = commands.add_parser("state")
    _add_data_root(state)

    manifest = commands.add_parser("manifest")
    _add_data_root(manifest)
    manifest.add_argument("--release-id", required=True)
    manifest.add_argument("--source-revision", required=True)
    manifest.add_argument("--source-dirty", action="store_true")
    manifest.add_argument("--previous-release-id")
    manifest.add_argument("--data-schema-version", required=True)
    manifest.add_argument("--image", action="append", default=[], required=True)
    manifest.add_argument("--component", action="append", default=[], required=True)
    manifest.add_argument("--deployment-contract-digest", required=True)

    health = commands.add_parser("health")
    _add_data_root(health)
    _add_driver(health)
    health.add_argument("--release-id")

    backup = commands.add_parser("backup")
    _add_data_root(backup)
    backup.add_argument("--backup-id", required=True)
    backup.add_argument("--release-id", required=True)
    backup.add_argument("--include", action="append", default=[], required=True)

    restore = commands.add_parser("restore")
    _add_data_root(restore)
    restore.add_argument("--backup-id", required=True)
    restore.add_argument("--destination", required=True, type=Path)
    restore.add_argument("--apply", action="store_true")

    start = commands.add_parser("start")
    _add_data_root(start)
    _add_driver(start)
    start.add_argument("--manifest", required=True, type=Path)
    start.add_argument("--operation-id", required=True)

    upgrade = commands.add_parser("upgrade")
    _add_data_root(upgrade)
    _add_driver(upgrade)
    upgrade.add_argument("--manifest", required=True, type=Path)
    upgrade.add_argument("--operation-id", required=True)
    upgrade.add_argument("--backup-id", required=True)
    upgrade.add_argument("--include", action="append", default=[], required=True)

    rollback = commands.add_parser("rollback")
    _add_data_root(rollback)
    _add_driver(rollback)
    rollback.add_argument("--operation-id", required=True)

    compose = commands.add_parser("compose-contract")
    compose.add_argument("--input", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compose-contract":
            output = validate_compose_contract(
                _load_json(args.input, "compose_config_unreadable")
            )
        else:
            store = ReleaseStore(args.data_root)
            backup = BackupManager(store)
            if args.command == "bootstrap":
                output = store.bootstrap().to_dict()
            elif args.command == "state":
                output = store.state().to_dict()
            elif args.command == "manifest":
                manifest = _manifest_from_args(args)
                store.publish_manifest(manifest)
                output = manifest.to_dict()
            elif args.command == "health":
                coordinator = OperationsCoordinator(store, backup, _driver(args, store))
                output = coordinator.health(args.release_id).to_dict()
            elif args.command == "backup":
                output = backup.create(
                    backup_id=args.backup_id,
                    release_id=args.release_id,
                    includes=args.include,
                ).to_dict()
            elif args.command == "restore":
                plan = backup.plan_restore(
                    backup_id=args.backup_id,
                    destination=args.destination,
                )
                output = plan.to_dict()
                if args.apply:
                    restored = backup.restore(plan)
                    output = {**output, "applied": True, "restored_to": str(restored)}
                else:
                    output = {**output, "applied": False}
            elif args.command in {"start", "upgrade"}:
                manifest = ReleaseManifest.from_dict(
                    _load_json(args.manifest, "release_manifest_unreadable")
                )
                coordinator = OperationsCoordinator(store, backup, _driver(args, store))
                if args.command == "start":
                    summary = coordinator.start_release(
                        manifest, operation_id=args.operation_id
                    )
                else:
                    summary = coordinator.upgrade(
                        manifest,
                        operation_id=args.operation_id,
                        backup_id=args.backup_id,
                        includes=args.include,
                    )
                output = summary.to_dict()
            elif args.command == "rollback":
                coordinator = OperationsCoordinator(store, backup, _driver(args, store))
                output = coordinator.rollback(operation_id=args.operation_id).to_dict()
            else:  # pragma: no cover
                _fail("unknown_operations_command")
        json.dump(output, sys.stdout, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except OperationFailed as exc:
        json.dump(
            {
                "status": "error",
                "code": exc.code,
                "operation": exc.summary.to_dict(),
            },
            sys.stderr,
            ensure_ascii=False,
            sort_keys=True,
        )
        sys.stderr.write("\n")
        return 1
    except OperationsError as exc:
        json.dump(
            {"status": "error", "code": exc.code},
            sys.stderr,
            ensure_ascii=False,
            sort_keys=True,
        )
        sys.stderr.write("\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
