from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeVar

from dududa.domain.primitives import DigestString
from dududa.errors import ErrorCategory, error

from .models import (
    MemoryDeleteReceipt,
    MemoryRecord,
    MemoryRestoreReceipt,
    MemorySubmissionReceipt,
    MemoryTombstone,
)
from .repository import InMemoryMemoryRepository
from .serialization import (
    delete_receipt_from_dict,
    delete_receipt_to_dict,
    record_from_dict,
    record_to_dict,
    restore_receipt_from_dict,
    restore_receipt_to_dict,
    submission_receipt_from_dict,
    submission_receipt_to_dict,
    tombstone_from_dict,
    tombstone_to_dict,
)


class JsonMemoryRepository(InMemoryMemoryRepository):
    """Atomic Memory v2 JSON adapter; legacy JSON is quarantined and never overwritten."""

    def __init__(self, path: Path, selector_verifier: object, **kwargs: object) -> None:
        self.path = path
        self.quarantined_legacy_count = 0
        self._legacy_source = False
        super().__init__(
            selector_verifier, repository_revision="memory-json-v2", **kwargs
        )
        self._load()

    async def _after_write_locked(self) -> None:
        self._persist_current_state()

    async def _after_delete_locked(self) -> None:
        self._persist_current_state()

    async def _after_restore_locked(self) -> None:
        self._persist_current_state()

    def _persist_current_state(self) -> None:
        if self._legacy_source:
            raise error(
                "legacy_memory_json_is_read_only",
                ErrorCategory.CONFLICT,
                "memory.migration_required",
            )
        self._persist()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            raise error(
                "invalid_memory_json",
                ErrorCategory.VALIDATION,
                "memory.unavailable",
            ) from None
        if not isinstance(value, Mapping) or value.get("schema_version") != 1:
            if isinstance(value, Mapping) and value.get("schema_version") == 2:
                self._load_v2(value)
                return
            self._legacy_source = True
            self.quarantined_legacy_count = _legacy_count(value)
            return
        self._load_v1(value)

    def _load_v1(self, value: Mapping[object, object]) -> None:
        if value.get("repository_revision") != "memory-json-v1":
            raise error(
                "invalid_memory_json_revision",
                ErrorCategory.VALIDATION,
                "memory.unavailable",
            )
        records = value.get("records")
        if not isinstance(records, list):
            raise error(
                "invalid_memory_json_records",
                ErrorCategory.VALIDATION,
                "memory.unavailable",
            )
        loaded = tuple(record_from_dict(item) for item in records)
        self._install_loaded_state(
            records=loaded,
            tombstones=(),
            state_revision=1 if loaded else 0,
            write_idempotency={},
            delete_idempotency={},
            restore_idempotency={},
            consumed_write_decisions=set(),
            consumed_delete_confirmations=set(),
        )

    def _load_v2(self, value: Mapping[object, object]) -> None:
        expected_keys = {
            "schema_version",
            "repository_revision",
            "state_revision",
            "records",
            "tombstones",
            "write_idempotency",
            "delete_idempotency",
            "restore_idempotency",
            "consumed_write_decisions",
            "consumed_delete_confirmations",
        }
        if set(value) != expected_keys or value.get("repository_revision") != (
            "memory-json-v2"
        ):
            raise error(
                "invalid_memory_json_v2_envelope",
                ErrorCategory.VALIDATION,
                "memory.unavailable",
            )
        try:
            raw_records = _list(value["records"])
            raw_tombstones = _list(value["tombstones"])
            write_idempotency = _load_idempotency(
                value["write_idempotency"], submission_receipt_from_dict
            )
            delete_idempotency = _load_idempotency(
                value["delete_idempotency"], delete_receipt_from_dict
            )
            restore_idempotency = _load_idempotency(
                value["restore_idempotency"], restore_receipt_from_dict
            )
            self._install_loaded_state(
                records=tuple(record_from_dict(item) for item in raw_records),
                tombstones=tuple(tombstone_from_dict(item) for item in raw_tombstones),
                state_revision=_strict_int(value["state_revision"]),
                write_idempotency=write_idempotency,
                delete_idempotency=delete_idempotency,
                restore_idempotency=restore_idempotency,
                consumed_write_decisions=_string_set(value["consumed_write_decisions"]),
                consumed_delete_confirmations=_string_set(
                    value["consumed_delete_confirmations"]
                ),
            )
        except (KeyError, TypeError, ValueError):
            raise error(
                "invalid_memory_json_v2_state",
                ErrorCategory.VALIDATION,
                "memory.unavailable",
            ) from None

    def _install_loaded_state(
        self,
        *,
        records: tuple[MemoryRecord, ...],
        tombstones: tuple[MemoryTombstone, ...],
        state_revision: int,
        write_idempotency: dict[str, tuple[DigestString, MemorySubmissionReceipt]],
        delete_idempotency: dict[str, tuple[DigestString, MemoryDeleteReceipt]],
        restore_idempotency: dict[str, tuple[DigestString, MemoryRestoreReceipt]],
        consumed_write_decisions: set[str],
        consumed_delete_confirmations: set[str],
    ) -> None:
        record_map = {item.memory_id: item for item in records}
        tombstone_map = {item.memory_id: item for item in tombstones}
        if (
            len(record_map) != len(records)
            or len(tombstone_map) != len(tombstones)
            or set(record_map) & set(tombstone_map)
            or state_revision < 0
            or any(item.state_revision > state_revision for item in tombstones)
        ):
            raise ValueError("invalid loaded memory state")
        self._records = record_map
        self._tombstones = tombstone_map
        self._state_revision = state_revision
        self._idempotency = write_idempotency
        self._delete_idempotency = delete_idempotency
        self._restore_idempotency = restore_idempotency
        self._consumed_decisions = consumed_write_decisions
        self._consumed_delete_confirmations = consumed_delete_confirmations

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2,
            "repository_revision": "memory-json-v2",
            "state_revision": self._state_revision,
            "records": [
                record_to_dict(record)
                for record in sorted(
                    self._records.values(), key=lambda item: item.memory_id
                )
            ],
            "tombstones": [
                tombstone_to_dict(tombstone)
                for tombstone in sorted(
                    self._tombstones.values(), key=lambda item: item.memory_id
                )
            ],
            "write_idempotency": _dump_idempotency(
                self._idempotency, submission_receipt_to_dict
            ),
            "delete_idempotency": _dump_idempotency(
                self._delete_idempotency, delete_receipt_to_dict
            ),
            "restore_idempotency": _dump_idempotency(
                self._restore_idempotency, restore_receipt_to_dict
            ),
            "consumed_write_decisions": sorted(self._consumed_decisions),
            "consumed_delete_confirmations": sorted(
                self._consumed_delete_confirmations
            ),
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError:
            raise error(
                "memory_json_temporary_create_failed",
                ErrorCategory.CONFLICT,
                "memory.unavailable",
            ) from None
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except BaseException as caught:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            if isinstance(caught, Exception):
                raise error(
                    "memory_json_atomic_write_failed",
                    ErrorCategory.EXTERNAL,
                    "memory.unavailable",
                ) from None
            raise


def _legacy_count(value: object) -> int:
    if not isinstance(value, Mapping):
        return 1
    count = 0
    for item in value.values():
        if isinstance(item, Mapping) and isinstance(item.get("memories"), list):
            count += len(item["memories"])
    return count or len(value)


_ReceiptT = TypeVar("_ReceiptT")


def _dump_idempotency(
    values: Mapping[str, tuple[DigestString, _ReceiptT]],
    receipt_encoder: Callable[[_ReceiptT], dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "idempotency_key": key,
            "command_digest": str(command_digest),
            "receipt": receipt_encoder(receipt),
        }
        for key, (command_digest, receipt) in sorted(values.items())
    ]


def _load_idempotency(
    value: object,
    receipt_decoder: Callable[[object], _ReceiptT],
) -> dict[str, tuple[DigestString, _ReceiptT]]:
    result: dict[str, tuple[DigestString, _ReceiptT]] = {}
    for raw in _list(value):
        item = _mapping(raw)
        if set(item) != {"idempotency_key", "command_digest", "receipt"}:
            raise ValueError("invalid idempotency entry")
        key = str(item["idempotency_key"])
        if not key.strip() or key in result:
            raise ValueError("invalid idempotency key")
        receipt = receipt_decoder(item["receipt"])
        if getattr(receipt, "idempotency_key", None) != key:
            raise ValueError("idempotency receipt mismatch")
        result[key] = (DigestString(str(item["command_digest"])), receipt)
    return result


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("memory state value must be a list")
    return value


def _mapping(value: object) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise TypeError("memory state value must be a mapping")
    return value


def _string_set(value: object) -> set[str]:
    items = _list(value)
    result = {str(item) for item in items}
    if len(result) != len(items) or any(not item.strip() for item in result):
        raise ValueError("invalid memory state string set")
    return result


def _strict_int(value: object) -> int:
    if type(value) is not int:
        raise TypeError("memory state revision must be an integer")
    return value
