from __future__ import annotations

from datetime import datetime
from typing import Mapping

from dududa.domain.primitives import ConversationType, DigestString, Sensitivity
from dududa.errors import validation_error

from .models import (
    EvidenceReference,
    MemoryRecord,
    MemoryScope,
    MemorySource,
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
            raise ValueError
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


def _datetime(value: object) -> datetime:
    result = datetime.fromisoformat(str(value))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError
    return result


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)
