from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Mapping
import uuid

from dududa.domain.primitives import ConversationType, Sensitivity
from dududa.errors import ErrorCategory, error

from .digests import memory_content_hash
from .models import (
    EvidenceReference,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    MemoryType,
    Visibility,
)
from .serialization import record_to_dict


@dataclass(frozen=True, slots=True)
class LegacyClassification:
    platform: str
    bot_id: str
    conversation_type: ConversationType
    conversation_id: str
    group_id: str | None
    persona_id: str


@dataclass(frozen=True, slots=True)
class MemoryMigrationReceipt:
    schema_version: int
    migration_id: str
    dry_run: bool
    source_path: str
    destination_path: str
    source_digest: str
    destination_digest: str | None
    migrated_count: int
    quarantined_count: int
    source_backup_path: str | None
    destination_backup_path: str | None
    quarantine_path: str | None
    quarantine_backup_path: str | None
    destination_created: bool
    quarantine_created: bool
    applied_at: str
    tool_revision: str = "memory-migration-v1"
    source_backup_digest: str | None = None
    destination_backup_digest: str | None = None
    quarantine_digest: str | None = None
    quarantine_backup_digest: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryRollbackReceipt:
    schema_version: int
    migration_id: str
    destination_restored: bool
    quarantine_restored: bool
    rolled_back_at: str


def migrate_legacy_json(
    source: Path,
    destination: Path,
    *,
    classifications: Mapping[str, LegacyClassification],
    backup_directory: Path,
    receipt_path: Path,
    dry_run: bool,
    now: datetime | None = None,
) -> MemoryMigrationReceipt:
    current = now or datetime.now(timezone.utc)
    source = source.resolve()
    destination = destination.resolve()
    backup_directory = backup_directory.resolve()
    receipt_path = receipt_path.resolve()
    quarantine_path = destination.with_suffix(destination.suffix + ".quarantine.json")
    _validate_migration_paths(
        source,
        destination,
        backup_directory,
        receipt_path,
        quarantine_path,
        dry_run=dry_run,
    )
    if not source.is_file():
        raise _migration_error("memory_migration_source_missing")
    source_bytes = source.read_bytes()
    try:
        legacy = json.loads(source_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _migration_error("invalid_legacy_memory_json") from None
    records, quarantined = _classify_legacy(legacy, classifications, current)
    migration_id = uuid.uuid4().hex
    destination_existed = destination.exists()
    quarantine_existed = quarantine_path.exists()
    receipt = MemoryMigrationReceipt(
        1,
        migration_id,
        dry_run,
        str(source),
        str(destination),
        _file_digest_bytes(source_bytes),
        None,
        len(records),
        len(quarantined),
        None,
        None,
        None,
        None,
        not destination_existed,
        not quarantine_existed,
        current.isoformat(),
    )
    if dry_run:
        return receipt

    backup_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_backup = backup_directory / f"{migration_id}.source.json"
    destination_backup = (
        backup_directory / f"{migration_id}.destination.json"
        if destination_existed
        else None
    )
    quarantine_backup = (
        backup_directory / f"{migration_id}.quarantine.json"
        if quarantine_existed
        else None
    )
    _require_distinct_paths(
        source,
        destination,
        receipt_path,
        quarantine_path,
        source_backup,
        destination_backup,
        quarantine_backup,
    )
    shutil.copy2(source, source_backup)
    os.chmod(source_backup, 0o600)
    if destination_backup is not None:
        shutil.copy2(destination, destination_backup)
        os.chmod(destination_backup, 0o600)
    if quarantine_backup is not None:
        shutil.copy2(quarantine_path, quarantine_backup)
        os.chmod(quarantine_backup, 0o600)
    source_backup_digest = _file_digest(source_backup)
    destination_backup_digest = (
        _file_digest(destination_backup) if destination_backup else None
    )
    quarantine_backup_digest = (
        _file_digest(quarantine_backup) if quarantine_backup else None
    )

    destination_payload = {
        "schema_version": 1,
        "repository_revision": "memory-json-v1",
        "records": [record_to_dict(record) for record in records],
    }
    quarantine_payload = {
        "schema_version": 1,
        "migration_id": migration_id,
        "records": quarantined,
    }
    destination_written = False
    quarantine_written = False
    try:
        _atomic_json(destination, destination_payload)
        destination_written = True
        _atomic_json(quarantine_path, quarantine_payload)
        quarantine_written = True
        destination_digest = _file_digest(destination)
        quarantine_digest = _file_digest(quarantine_path)
        receipt = MemoryMigrationReceipt(
            1,
            migration_id,
            False,
            str(source),
            str(destination),
            _file_digest_bytes(source_bytes),
            destination_digest,
            len(records),
            len(quarantined),
            str(source_backup),
            str(destination_backup) if destination_backup else None,
            str(quarantine_path),
            str(quarantine_backup) if quarantine_backup else None,
            not destination_existed,
            not quarantine_existed,
            current.isoformat(),
            source_backup_digest=source_backup_digest,
            destination_backup_digest=destination_backup_digest,
            quarantine_digest=quarantine_digest,
            quarantine_backup_digest=quarantine_backup_digest,
        )
        _atomic_json(receipt_path, asdict(receipt))
    except BaseException:
        try:
            if destination_written:
                _restore_apply_target(
                    destination,
                    destination_backup,
                    destination_backup_digest,
                )
            if quarantine_written:
                _restore_apply_target(
                    quarantine_path,
                    quarantine_backup,
                    quarantine_backup_digest,
                )
            if receipt_path.exists():
                receipt_path.unlink()
        except OSError:
            raise _migration_error("memory_migration_apply_rollback_failed") from None
        raise _migration_error("memory_migration_apply_failed") from None
    return receipt


def rollback_memory_migration(
    receipt_path: Path,
    *,
    now: datetime | None = None,
) -> MemoryRollbackReceipt:
    current = now or datetime.now(timezone.utc)
    if receipt_path.is_symlink():
        raise _migration_error("invalid_memory_migration_receipt")
    receipt_path = receipt_path.resolve()
    try:
        raw = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt = MemoryMigrationReceipt(**raw)
    except (OSError, json.JSONDecodeError, TypeError):
        raise _migration_error("invalid_memory_migration_receipt") from None
    if receipt.dry_run or receipt.destination_digest is None:
        raise _migration_error("dry_run_migration_cannot_rollback")
    source = Path(receipt.source_path)
    if _file_digest(source) != receipt.source_digest:
        raise _migration_error("memory_migration_source_changed")
    if (
        not receipt.source_backup_path
        or not receipt.source_backup_digest
        or _file_digest(Path(receipt.source_backup_path))
        != receipt.source_backup_digest
    ):
        raise _migration_error("memory_migration_source_backup_changed")
    destination = Path(receipt.destination_path)
    if (
        not destination.exists()
        or _file_digest(destination) != receipt.destination_digest
    ):
        raise _migration_error("memory_migration_destination_changed")
    quarantine = Path(receipt.quarantine_path) if receipt.quarantine_path else None
    if (
        quarantine is not None
        and receipt.quarantine_digest is not None
        and _file_digest(quarantine) != receipt.quarantine_digest
    ):
        raise _migration_error("memory_migration_quarantine_changed")

    if receipt.destination_backup_path:
        _validate_backup(
            Path(receipt.destination_backup_path),
            receipt.destination_backup_digest,
        )
    if receipt.quarantine_backup_path:
        _validate_backup(
            Path(receipt.quarantine_backup_path),
            receipt.quarantine_backup_digest,
        )

    if receipt.destination_backup_path:
        _restore_backup(
            Path(receipt.destination_backup_path),
            destination,
            receipt.destination_backup_digest,
        )
    elif receipt.destination_created:
        destination.unlink()
    else:
        raise _migration_error("memory_destination_rollback_state_invalid")

    quarantine_restored = False
    if quarantine is not None:
        if receipt.quarantine_backup_path:
            _restore_backup(
                Path(receipt.quarantine_backup_path),
                quarantine,
                receipt.quarantine_backup_digest,
            )
            quarantine_restored = True
        elif receipt.quarantine_created and quarantine.exists():
            quarantine.unlink()
            quarantine_restored = True
    return MemoryRollbackReceipt(
        1,
        receipt.migration_id,
        True,
        quarantine_restored,
        current.isoformat(),
    )


def load_classifications(path: Path) -> dict[str, LegacyClassification]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise _migration_error("invalid_memory_classification_file") from None
    if not isinstance(raw, Mapping):
        raise _migration_error("invalid_memory_classification_file")
    result: dict[str, LegacyClassification] = {}
    try:
        for user_id, value in raw.items():
            if not isinstance(value, Mapping):
                raise ValueError
            result[str(user_id)] = LegacyClassification(
                str(value["platform"]),
                str(value["bot_id"]),
                ConversationType(str(value["conversation_type"])),
                str(value["conversation_id"]),
                None if value.get("group_id") is None else str(value["group_id"]),
                str(value["persona_id"]),
            )
    except (KeyError, TypeError, ValueError):
        raise _migration_error("invalid_memory_classification_file") from None
    return result


def _classify_legacy(
    value: object,
    classifications: Mapping[str, LegacyClassification],
    now: datetime,
) -> tuple[list[MemoryRecord], list[dict[str, object]]]:
    if not isinstance(value, Mapping):
        raise _migration_error("legacy_memory_root_not_mapping")
    records: list[MemoryRecord] = []
    quarantined: list[dict[str, object]] = []
    for raw_user_id, state in value.items():
        user_id = str(raw_user_id)
        memories = state.get("memories") if isinstance(state, Mapping) else None
        if not isinstance(memories, list):
            continue
        classification = classifications.get(user_id)
        for index, item in enumerate(memories):
            if not isinstance(item, Mapping) or not isinstance(item.get("text"), str):
                quarantined.append(
                    _quarantine_entry(user_id, index, item, "invalid_legacy_record")
                )
                continue
            if classification is None:
                quarantined.append(
                    _quarantine_entry(
                        user_id, index, item, "missing_scope_classification"
                    )
                )
                continue
            created_at = _legacy_time(item.get("time"), now)
            content = str(item["text"]).strip()
            if not content:
                quarantined.append(
                    _quarantine_entry(user_id, index, item, "empty_legacy_content")
                )
                continue
            record_key = f"{user_id}:{index}:{content}"
            record_id = (
                "legacy-" + hashlib.sha256(record_key.encode("utf-8")).hexdigest()[:24]
            )
            scope = MemoryScope(
                1,
                classification.platform,
                classification.bot_id,
                classification.conversation_type,
                classification.conversation_id,
                classification.group_id,
                user_id,
                classification.persona_id,
                MemoryType.EXPLICIT_USER_MEMORY,
            )
            records.append(
                MemoryRecord(
                    1,
                    record_id,
                    scope,
                    content,
                    MemorySource.LEGACY_IMPORT,
                    created_at,
                    created_at,
                    1.0,
                    None,
                    Sensitivity.PERSONAL,
                    Visibility.CURRENT_CONVERSATION,
                    (
                        EvidenceReference(
                            f"legacy:{user_id}:{index}",
                            "legacy_json",
                            str(index),
                            user_id,
                        ),
                    ),
                    memory_content_hash(content),
                    1,
                )
            )
    return records, quarantined


def _quarantine_entry(
    user_id: str,
    index: int,
    item: object,
    reason: str,
) -> dict[str, object]:
    return {
        "legacy_user_id": user_id,
        "legacy_index": index,
        "reason_code": reason,
        "raw": item,
    }


def _legacy_time(value: object, fallback: datetime) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
    return fallback


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(
        temporary,
        os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _restore_backup(
    backup: Path,
    destination: Path,
    expected_digest: str | None,
) -> None:
    _validate_backup(backup, expected_digest)
    temporary = destination.with_suffix(destination.suffix + ".rollback.tmp")
    shutil.copy2(backup, temporary)
    temporary.replace(destination)
    os.chmod(destination, 0o600)


def _validate_backup(backup: Path, expected_digest: str | None) -> None:
    if not backup.is_file():
        raise _migration_error("memory_migration_backup_missing")
    if expected_digest is None or _file_digest(backup) != expected_digest:
        raise _migration_error("memory_migration_backup_changed")


def _restore_apply_target(
    path: Path,
    backup: Path | None,
    backup_digest: str | None,
) -> None:
    if backup is None:
        path.unlink(missing_ok=True)
        return
    _restore_backup(backup, path, backup_digest)


def _validate_migration_paths(
    source: Path,
    destination: Path,
    backup_directory: Path,
    receipt_path: Path,
    quarantine_path: Path,
    *,
    dry_run: bool,
) -> None:
    _require_distinct_paths(
        source,
        destination,
        backup_directory,
        receipt_path,
        quarantine_path,
    )
    if any(path.is_dir() for path in (destination, receipt_path, quarantine_path)):
        raise _migration_error("memory_migration_path_is_directory")
    if not dry_run and receipt_path.exists():
        raise _migration_error("memory_migration_receipt_exists")


def _require_distinct_paths(*paths: Path | None) -> None:
    concrete = tuple(path for path in paths if path is not None)
    if len(set(concrete)) != len(concrete):
        raise _migration_error("memory_migration_path_collision")


def _file_digest(path: Path) -> str:
    try:
        return _file_digest_bytes(path.read_bytes())
    except OSError:
        raise _migration_error("memory_migration_file_missing") from None


def _file_digest_bytes(value: bytes) -> str:
    return "sha-256:" + hashlib.sha256(value).hexdigest()


def _migration_error(code: str):
    return error(code, ErrorCategory.CONFLICT, "memory.migration_failed")
