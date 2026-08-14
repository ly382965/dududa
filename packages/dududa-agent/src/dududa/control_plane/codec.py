from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from dududa.contracts.canonical import canonical_json_bytes
from dududa.domain.identity import ActorRef
from dududa.domain.primitives import ActionId, DigestString
from dududa.errors import validation_error

from .contracts import (
    AssignmentStatus,
    CommandOutcome,
    CommandReceipt,
    ControlPlaneAuditRecord,
    GroupControlScope,
    GroupServiceAssignment,
    GroupServicePreview,
    ProfileRef,
    ServiceResolution,
    StoredAssignmentCommand,
    StoredPreviewCommand,
)


def encode_control_plane_value(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def decode_preview(payload: str) -> GroupServicePreview:
    value = _object(payload)
    return GroupServicePreview(
        _int(value, "schema_version"),
        _str(value, "preview_id"),
        _scope(value["scope"]),
        _profile_ref(value["profile_ref"]),
        DigestString(_str(value, "profile_digest")),
        _int(value, "onboarding_revision"),
        _str(value, "catalog_revision"),
        _strings(value, "desired_service_ids"),
        _strings(value, "effective_service_ids"),
        tuple(_resolution(item) for item in _list(value, "resolutions")),
        _datetime(value, "created_at"),
        _datetime(value, "expires_at"),
        _optional_int(value, "assignment_revision"),
    )


def decode_assignment(payload: str) -> GroupServiceAssignment:
    value = _object(payload)
    return GroupServiceAssignment(
        _int(value, "schema_version"),
        _scope(value["scope"]),
        _int(value, "assignment_revision"),
        AssignmentStatus(_str(value, "status")),
        _profile_ref(value["profile_ref"]),
        DigestString(_str(value, "profile_digest")),
        _strings(value, "desired_service_ids"),
        _strings(value, "effective_service_ids"),
        _actor_ref(value["selected_by"]),
        _str(value, "authorization_decision_id"),
        _str(value, "policy_revision"),
        _optional_int(value, "previous_revision"),
        _int(value, "last_known_good_revision"),
        _datetime(value, "activated_at"),
    )


def decode_stored_preview(payload: str) -> StoredPreviewCommand:
    value = _object(payload)
    return StoredPreviewCommand(
        _int(value, "schema_version"),
        DigestString(_str(value, "request_digest")),
        decode_preview(_nested(value, "preview")),
        _receipt(value["receipt"]),
        _audit(value["audit_record"]),
    )


def decode_stored_assignment(payload: str) -> StoredAssignmentCommand:
    value = _object(payload)
    return StoredAssignmentCommand(
        _int(value, "schema_version"),
        DigestString(_str(value, "request_digest")),
        decode_assignment(_nested(value, "assignment")),
        _receipt(value["receipt"]),
        _audit(value["audit_record"]),
    )


def _scope(value: object) -> GroupControlScope:
    item = _mapping(value)
    return GroupControlScope(
        _int(item, "schema_version"),
        _str(item, "platform"),
        _str(item, "bot_id"),
        _str(item, "group_id"),
    )


def _profile_ref(value: object) -> ProfileRef:
    item = _mapping(value)
    return ProfileRef(_str(item, "profile_id"), _int(item, "revision"))


def _actor_ref(value: object) -> ActorRef:
    item = _mapping(value)
    return ActorRef(
        _str(item, "platform"),
        _str(item, "bot_id"),
        _str(item, "opaque_actor_id"),
    )


def _resolution(value: object) -> ServiceResolution:
    item = _mapping(value)
    return ServiceResolution(
        _int(item, "schema_version"),
        _str(item, "service_id"),
        _bool(item, "eligible"),
        _strings(item, "reason_codes"),
    )


def _receipt(value: object) -> CommandReceipt:
    item = _mapping(value)
    result_digest = item.get("result_digest")
    return CommandReceipt(
        _int(item, "schema_version"),
        _str(item, "receipt_id"),
        _str(item, "command_id"),
        _str(item, "idempotency_key"),
        ActionId(_str(item, "action")),
        CommandOutcome(_str(item, "outcome")),
        DigestString(_str(item, "request_digest")),
        DigestString(_str(item, "scope_digest")),
        _str(item, "authorization_decision_id"),
        DigestString(result_digest) if isinstance(result_digest, str) else None,
        _strings(item, "reason_codes"),
        _datetime(item, "committed_at"),
    )


def _audit(value: object) -> ControlPlaneAuditRecord:
    item = _mapping(value)
    return ControlPlaneAuditRecord(
        _int(item, "schema_version"),
        _str(item, "audit_record_id"),
        _str(item, "command_id"),
        ActionId(_str(item, "action")),
        DigestString(_str(item, "actor_digest")),
        DigestString(_str(item, "scope_digest")),
        DigestString(_str(item, "request_digest")),
        _str(item, "receipt_id"),
        CommandOutcome(_str(item, "outcome")),
        _strings(item, "reason_codes"),
        _datetime(item, "recorded_at"),
    )


def _object(payload: str) -> dict[str, Any]:
    try:
        return _mapping(json.loads(payload))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise validation_error(
            "invalid_control_plane_storage_payload",
            type(exc).__name__,
        ) from None


def _nested(value: dict[str, Any], key: str) -> str:
    return json.dumps(
        _mapping(value.get(key)), ensure_ascii=False, separators=(",", ":")
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise validation_error("invalid_control_plane_storage_object")
    return cast(dict[str, Any], value)


def _list(value: dict[str, Any], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list):
        raise validation_error("invalid_control_plane_storage_sequence", key)
    return cast(list[object], item)


def _str(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise validation_error("invalid_control_plane_storage_string", key)
    return item


def _int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if type(item) is not int:
        raise validation_error("invalid_control_plane_storage_integer", key)
    return item


def _optional_int(value: dict[str, Any], key: str) -> int | None:
    item = value.get(key)
    if item is None:
        return None
    if type(item) is not int:
        raise validation_error("invalid_control_plane_storage_integer", key)
    return item


def _bool(value: dict[str, Any], key: str) -> bool:
    item = value.get(key)
    if type(item) is not bool:
        raise validation_error("invalid_control_plane_storage_boolean", key)
    return item


def _strings(value: dict[str, Any], key: str) -> tuple[str, ...]:
    items = _list(value, key)
    if any(not isinstance(item, str) for item in items):
        raise validation_error("invalid_control_plane_storage_sequence", key)
    return tuple(cast(list[str], items))


def _datetime(value: dict[str, Any], key: str) -> datetime:
    raw = _str(value, key)
    try:
        return datetime.fromisoformat(raw.removesuffix("Z") + "+00:00")
    except ValueError:
        raise validation_error("invalid_control_plane_storage_datetime", key) from None


__all__ = [
    "decode_assignment",
    "decode_preview",
    "decode_stored_assignment",
    "decode_stored_preview",
    "encode_control_plane_value",
]
