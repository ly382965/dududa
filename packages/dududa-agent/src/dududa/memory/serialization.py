from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    Sensitivity,
)
from dududa.errors import validation_error

from .models import (
    EvidenceReference,
    MemoryDeleteReceipt,
    MemoryRecord,
    MemoryRepositoryArchive,
    MemoryRestoreReceipt,
    MemoryScope,
    MemorySource,
    MemorySubmissionReceipt,
    MemorySubmissionStatus,
    MemoryTombstone,
    MemoryTombstoneCheckpoint,
    MemoryType,
    Visibility,
)


def record_to_dict(record: MemoryRecord) -> dict[str, object]:
    scope = record.scope
    return {
        "schema_version": 1,
        "memory_id": record.memory_id,
        "scope": {
            "schema_version": 1,
            "platform": scope.platform,
            "bot_id": scope.bot_id,
            "conversation_type": scope.conversation_type.value,
            "conversation_id": scope.conversation_id,
            "group_id": scope.group_id,
            "user_id": scope.user_id,
            "persona_id": scope.persona_id,
            "memory_type": scope.memory_type.value,
        },
        "content": record.content,
        "source": record.source.value,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "confidence": record.confidence,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "sensitivity": record.sensitivity.value,
        "visibility": record.visibility.value,
        "evidence": [
            {
                "reference_id": item.reference_id,
                "source_type": item.source_type,
                "source_id": item.source_id,
                "source_user_id": item.source_user_id,
            }
            for item in record.evidence
        ],
        "content_hash": str(record.content_hash),
        "version": record.version,
    }


def record_from_dict(value: object) -> MemoryRecord:
    if not isinstance(value, Mapping):
        raise validation_error("memory_record_not_mapping")
    scope_value = value.get("scope")
    if not isinstance(scope_value, Mapping):
        raise validation_error("memory_scope_not_mapping")
    try:
        scope = MemoryScope(
            int(scope_value["schema_version"]),
            str(scope_value["platform"]),
            str(scope_value["bot_id"]),
            ConversationType(str(scope_value["conversation_type"])),
            str(scope_value["conversation_id"]),
            _optional_string(scope_value.get("group_id")),
            _optional_string(scope_value.get("user_id")),
            str(scope_value["persona_id"]),
            MemoryType(str(scope_value["memory_type"])),
        )
        raw_evidence = value.get("evidence", [])
        if not isinstance(raw_evidence, list):
            raise TypeError
        evidence = tuple(
            EvidenceReference(
                str(item["reference_id"]),
                str(item["source_type"]),
                str(item["source_id"]),
                _optional_string(item.get("source_user_id")),
            )
            for item in raw_evidence
            if isinstance(item, Mapping)
        )
        if len(evidence) != len(raw_evidence):
            raise ValueError
        return MemoryRecord(
            int(value["schema_version"]),
            str(value["memory_id"]),
            scope,
            str(value["content"]),
            MemorySource(str(value["source"])),
            _datetime(value["created_at"]),
            _datetime(value["updated_at"]),
            float(value["confidence"]),
            _datetime(value["expires_at"])
            if value.get("expires_at") is not None
            else None,
            Sensitivity(str(value["sensitivity"])),
            Visibility(str(value["visibility"])),
            evidence,
            DigestString(str(value["content_hash"])),
            int(value["version"]),
        )
    except (KeyError, TypeError, ValueError):
        raise validation_error("invalid_serialized_memory_record") from None


def tombstone_to_dict(tombstone: MemoryTombstone) -> dict[str, object]:
    return {
        "schema_version": tombstone.schema_version,
        "tombstone_id": tombstone.tombstone_id,
        "memory_id": tombstone.memory_id,
        "scope": _scope_to_dict(tombstone.scope),
        "deleted_record_digest": str(tombstone.deleted_record_digest),
        "content_hash": str(tombstone.content_hash),
        "deleted_version": tombstone.deleted_version,
        "delete_command_digest": str(tombstone.delete_command_digest),
        "authorization_digest": str(tombstone.authorization_digest),
        "confirmation_digest": str(tombstone.confirmation_digest),
        "policy_revision": tombstone.policy_revision,
        "writer_revision": _component_to_dict(tombstone.writer_revision),
        "deleted_at": tombstone.deleted_at.isoformat(),
        "state_revision": tombstone.state_revision,
        "integrity_digest": str(tombstone.integrity_digest),
    }


def tombstone_from_dict(value: object) -> MemoryTombstone:
    from .digests import memory_tombstone_digest

    item = _mapping(value, "memory_tombstone")
    try:
        result = MemoryTombstone(
            int(item["schema_version"]),
            str(item["tombstone_id"]),
            str(item["memory_id"]),
            _scope_from_dict(item["scope"]),
            DigestString(str(item["deleted_record_digest"])),
            DigestString(str(item["content_hash"])),
            int(item["deleted_version"]),
            DigestString(str(item["delete_command_digest"])),
            DigestString(str(item["authorization_digest"])),
            DigestString(str(item["confirmation_digest"])),
            str(item["policy_revision"]),
            _component_from_dict(item["writer_revision"]),
            _datetime(item["deleted_at"]),
            int(item["state_revision"]),
            DigestString(str(item["integrity_digest"])),
        )
    except (KeyError, TypeError, ValueError):
        raise validation_error("invalid_serialized_memory_tombstone") from None
    if memory_tombstone_digest(result) != result.integrity_digest:
        raise validation_error("memory_tombstone_digest_mismatch")
    return result


def submission_receipt_to_dict(
    receipt: MemorySubmissionReceipt,
) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "command_id": receipt.command_id,
        "decision_id": receipt.decision_id,
        "candidate_id": receipt.candidate_id,
        "idempotency_key": receipt.idempotency_key,
        "status": receipt.status.value,
        "memory_id": receipt.memory_id,
        "outbox_event_id": receipt.outbox_event_id,
        "policy_revision": receipt.policy_revision,
        "producer": _component_to_dict(receipt.producer),
        "writer_revision": (
            _component_to_dict(receipt.writer_revision)
            if receipt.writer_revision is not None
            else None
        ),
        "reason_codes": list(receipt.reason_codes),
        "recorded_at": receipt.recorded_at.isoformat(),
    }


def submission_receipt_from_dict(value: object) -> MemorySubmissionReceipt:
    item = _mapping(value, "memory_submission_receipt")
    try:
        writer = item.get("writer_revision")
        reasons = item.get("reason_codes")
        if not isinstance(reasons, list):
            raise TypeError
        return MemorySubmissionReceipt(
            int(item["schema_version"]),
            str(item["command_id"]),
            str(item["decision_id"]),
            str(item["candidate_id"]),
            str(item["idempotency_key"]),
            MemorySubmissionStatus(str(item["status"])),
            _optional_string(item.get("memory_id")),
            _optional_string(item.get("outbox_event_id")),
            str(item["policy_revision"]),
            _component_from_dict(item["producer"]),
            _component_from_dict(writer) if writer is not None else None,
            tuple(str(reason) for reason in reasons),
            _datetime(item["recorded_at"]),
        )
    except (KeyError, TypeError, ValueError):
        raise validation_error("invalid_serialized_memory_submission") from None


def delete_receipt_to_dict(receipt: MemoryDeleteReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "command_id": receipt.command_id,
        "request_digest": str(receipt.request_digest),
        "idempotency_key": receipt.idempotency_key,
        "memory_id": receipt.memory_id,
        "deleted_version": receipt.deleted_version,
        "tombstone_digest": str(receipt.tombstone_digest),
        "state_revision": receipt.state_revision,
        "policy_revision": receipt.policy_revision,
        "writer_revision": _component_to_dict(receipt.writer_revision),
        "completed_at": receipt.completed_at.isoformat(),
        "receipt_digest": str(receipt.receipt_digest),
    }


def delete_receipt_from_dict(value: object) -> MemoryDeleteReceipt:
    from .digests import memory_delete_receipt_digest

    item = _mapping(value, "memory_delete_receipt")
    try:
        result = MemoryDeleteReceipt(
            int(item["schema_version"]),
            str(item["command_id"]),
            DigestString(str(item["request_digest"])),
            str(item["idempotency_key"]),
            str(item["memory_id"]),
            int(item["deleted_version"]),
            DigestString(str(item["tombstone_digest"])),
            int(item["state_revision"]),
            str(item["policy_revision"]),
            _component_from_dict(item["writer_revision"]),
            _datetime(item["completed_at"]),
            DigestString(str(item["receipt_digest"])),
        )
    except (KeyError, TypeError, ValueError):
        raise validation_error("invalid_serialized_memory_delete_receipt") from None
    if memory_delete_receipt_digest(result) != result.receipt_digest:
        raise validation_error("memory_delete_receipt_digest_mismatch")
    return result


def checkpoint_to_dict(
    checkpoint: MemoryTombstoneCheckpoint,
) -> dict[str, object]:
    return {
        "schema_version": checkpoint.schema_version,
        "checkpoint_id": checkpoint.checkpoint_id,
        "repository_revision": checkpoint.repository_revision,
        "state_revision": checkpoint.state_revision,
        "tombstones": [tombstone_to_dict(item) for item in checkpoint.tombstones],
        "created_at": checkpoint.created_at.isoformat(),
        "checkpoint_digest": str(checkpoint.checkpoint_digest),
    }


def checkpoint_from_dict(value: object) -> MemoryTombstoneCheckpoint:
    from .digests import memory_tombstone_checkpoint_digest

    item = _mapping(value, "memory_tombstone_checkpoint")
    try:
        raw_tombstones = item["tombstones"]
        if not isinstance(raw_tombstones, list):
            raise TypeError
        result = MemoryTombstoneCheckpoint(
            int(item["schema_version"]),
            str(item["checkpoint_id"]),
            str(item["repository_revision"]),
            int(item["state_revision"]),
            tuple(tombstone_from_dict(entry) for entry in raw_tombstones),
            _datetime(item["created_at"]),
            DigestString(str(item["checkpoint_digest"])),
        )
    except (KeyError, TypeError, ValueError):
        raise validation_error("invalid_serialized_memory_checkpoint") from None
    if memory_tombstone_checkpoint_digest(result) != result.checkpoint_digest:
        raise validation_error("memory_checkpoint_digest_mismatch")
    return result


def archive_to_dict(archive: MemoryRepositoryArchive) -> dict[str, object]:
    return {
        "schema_version": archive.schema_version,
        "archive_id": archive.archive_id,
        "repository_revision": archive.repository_revision,
        "state_revision": archive.state_revision,
        "records": [record_to_dict(item) for item in archive.records],
        "tombstone_checkpoint": checkpoint_to_dict(archive.tombstone_checkpoint),
        "exported_at": archive.exported_at.isoformat(),
        "archive_digest": str(archive.archive_digest),
    }


def archive_from_dict(value: object) -> MemoryRepositoryArchive:
    from .digests import memory_repository_archive_digest

    item = _mapping(value, "memory_repository_archive")
    try:
        raw_records = item["records"]
        if not isinstance(raw_records, list):
            raise TypeError
        result = MemoryRepositoryArchive(
            int(item["schema_version"]),
            str(item["archive_id"]),
            str(item["repository_revision"]),
            int(item["state_revision"]),
            tuple(record_from_dict(entry) for entry in raw_records),
            checkpoint_from_dict(item["tombstone_checkpoint"]),
            _datetime(item["exported_at"]),
            DigestString(str(item["archive_digest"])),
        )
    except (KeyError, TypeError, ValueError):
        raise validation_error("invalid_serialized_memory_archive") from None
    if memory_repository_archive_digest(result) != result.archive_digest:
        raise validation_error("memory_archive_digest_mismatch")
    return result


def restore_receipt_to_dict(receipt: MemoryRestoreReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "command_id": receipt.command_id,
        "request_digest": str(receipt.request_digest),
        "idempotency_key": receipt.idempotency_key,
        "archive_digest": str(receipt.archive_digest),
        "checkpoint_digest": str(receipt.checkpoint_digest),
        "restored_records": receipt.restored_records,
        "suppressed_records": receipt.suppressed_records,
        "state_revision_before": receipt.state_revision_before,
        "state_revision_after": receipt.state_revision_after,
        "writer_revision": _component_to_dict(receipt.writer_revision),
        "completed_at": receipt.completed_at.isoformat(),
        "receipt_digest": str(receipt.receipt_digest),
    }


def restore_receipt_from_dict(value: object) -> MemoryRestoreReceipt:
    from .digests import memory_restore_receipt_digest

    item = _mapping(value, "memory_restore_receipt")
    try:
        result = MemoryRestoreReceipt(
            int(item["schema_version"]),
            str(item["command_id"]),
            DigestString(str(item["request_digest"])),
            str(item["idempotency_key"]),
            DigestString(str(item["archive_digest"])),
            DigestString(str(item["checkpoint_digest"])),
            int(item["restored_records"]),
            int(item["suppressed_records"]),
            int(item["state_revision_before"]),
            int(item["state_revision_after"]),
            _component_from_dict(item["writer_revision"]),
            _datetime(item["completed_at"]),
            DigestString(str(item["receipt_digest"])),
        )
    except (KeyError, TypeError, ValueError):
        raise validation_error("invalid_serialized_memory_restore_receipt") from None
    if memory_restore_receipt_digest(result) != result.receipt_digest:
        raise validation_error("memory_restore_receipt_digest_mismatch")
    return result


def _scope_to_dict(scope: MemoryScope) -> dict[str, object]:
    return {
        "schema_version": scope.schema_version,
        "platform": scope.platform,
        "bot_id": scope.bot_id,
        "conversation_type": scope.conversation_type.value,
        "conversation_id": scope.conversation_id,
        "group_id": scope.group_id,
        "user_id": scope.user_id,
        "persona_id": scope.persona_id,
        "memory_type": scope.memory_type.value,
    }


def _scope_from_dict(value: object) -> MemoryScope:
    item = _mapping(value, "memory_scope")
    return MemoryScope(
        int(item["schema_version"]),
        str(item["platform"]),
        str(item["bot_id"]),
        ConversationType(str(item["conversation_type"])),
        str(item["conversation_id"]),
        _optional_string(item.get("group_id")),
        _optional_string(item.get("user_id")),
        str(item["persona_id"]),
        MemoryType(str(item["memory_type"])),
    )


def _component_to_dict(value: ComponentRevision) -> dict[str, object]:
    return {
        "component_id": value.component_id,
        "implementation_version": value.implementation_version,
        "config_revision": value.config_revision,
        "artifact_digest": str(value.artifact_digest),
    }


def _component_from_dict(value: object) -> ComponentRevision:
    item = _mapping(value, "component_revision")
    return ComponentRevision(
        str(item["component_id"]),
        str(item["implementation_version"]),
        str(item["config_revision"]),
        DigestString(str(item["artifact_digest"])),
    )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise validation_error("invalid_serialized_memory_mapping", field_name)
    return value


def _datetime(value: object) -> datetime:
    result = datetime.fromisoformat(str(value))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError
    return result


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)
