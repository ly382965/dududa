from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import TypeVar

from dududa.domain.identity import ActorRef, ConversationScope
from dududa.domain.primitives import ConversationType, DigestString
from dududa.errors import validation_error
from dududa.responses.contracts import AnswerProfile

from .contracts import (
    LocalTimeWindow,
    ProactiveAuthorizationGrantRef,
    ProactiveSubscription,
    ProactiveTargetPolicyRef,
    ProactiveTrigger,
    ProactiveTriggerKind,
    ScheduleAckDisposition,
    ScheduleClaimReceipt,
    ScheduleLedgerRecord,
    ScheduleMaterializationReceipt,
    ScheduleOccurrence,
    ScheduleOccurrenceOrigin,
    ScheduleOccurrenceState,
    ScheduleSpec,
    ScheduleTriggerClaim,
    SourceCategory,
    SubscriptionMutationDisposition,
    SubscriptionMutationReceipt,
    SubscriptionStatus,
)


def encode_subscription(value: ProactiveSubscription) -> str:
    if not isinstance(value, ProactiveSubscription):
        raise validation_error("invalid_scheduler_subscription")
    return _encode(
        {
            "schema_version": value.schema_version,
            "subscription_id": value.subscription_id,
            "revision": value.revision,
            "status": value.status.value,
            "owner_ref": _actor_ref_payload(value.owner_ref),
            "authorization_grant_ref": _grant_ref_payload(
                value.authorization_grant_ref
            ),
            "target_scope": _scope_payload(value.target_scope),
            "target_policy_ref": _target_ref_payload(value.target_policy_ref),
            "categories": sorted(item.value for item in value.categories),
            "source_policy_id": value.source_policy_id,
            "schedule": _schedule_payload(value.schedule),
            "answer_profile": value.answer_profile.value,
            "maximum_items": value.maximum_items,
            "maximum_age_us": _timedelta_us(value.maximum_age),
            "created_at": _datetime_text(value.created_at),
            "updated_at": _datetime_text(value.updated_at),
            "subscription_digest": str(value.subscription_digest),
        }
    )


def decode_subscription(payload: str) -> ProactiveSubscription:
    value = _decode(payload, "subscription")
    _keys(
        value,
        {
            "schema_version",
            "subscription_id",
            "revision",
            "status",
            "owner_ref",
            "authorization_grant_ref",
            "target_scope",
            "target_policy_ref",
            "categories",
            "source_policy_id",
            "schedule",
            "answer_profile",
            "maximum_items",
            "maximum_age_us",
            "created_at",
            "updated_at",
            "subscription_digest",
        },
        "subscription",
    )
    categories = _list(value["categories"], "subscription_categories")
    return ProactiveSubscription(
        schema_version=_int(value["schema_version"], "schema_version"),
        subscription_id=_str(value["subscription_id"], "subscription_id"),
        revision=_int(value["revision"], "subscription_revision"),
        status=_enum(SubscriptionStatus, value["status"], "subscription_status"),
        owner_ref=_actor_ref(_object(value["owner_ref"], "owner_ref")),
        authorization_grant_ref=_grant_ref(
            _object(value["authorization_grant_ref"], "authorization_grant_ref")
        ),
        target_scope=_scope(_object(value["target_scope"], "target_scope")),
        target_policy_ref=_target_ref(
            _object(value["target_policy_ref"], "target_policy_ref")
        ),
        categories=frozenset(
            _enum(SourceCategory, item, "subscription_category") for item in categories
        ),
        source_policy_id=_str(value["source_policy_id"], "source_policy_id"),
        schedule=_schedule(_object(value["schedule"], "schedule")),
        answer_profile=_enum(AnswerProfile, value["answer_profile"], "answer_profile"),
        maximum_items=_int(value["maximum_items"], "maximum_items"),
        maximum_age=_timedelta(_int(value["maximum_age_us"], "maximum_age_us")),
        created_at=_datetime(value["created_at"], "created_at"),
        updated_at=_datetime(value["updated_at"], "updated_at"),
        subscription_digest=DigestString(
            _str(value["subscription_digest"], "subscription_digest")
        ),
    )


def encode_trigger(value: ProactiveTrigger) -> str:
    if (
        not isinstance(value, ProactiveTrigger)
        or value.kind is not ProactiveTriggerKind.SCHEDULED_DIGEST
        or value.occurrence is None
    ):
        raise validation_error("invalid_scheduler_trigger")
    occurrence = value.occurrence
    return _encode(
        {
            "schema_version": value.schema_version,
            "trigger_id": value.trigger_id,
            "kind": value.kind.value,
            "target_scope": _scope_payload(value.target_scope),
            "occurrence": {
                "schema_version": occurrence.schema_version,
                "occurrence_id": occurrence.occurrence_id,
                "subscription_id": occurrence.subscription_id,
                "subscription_revision": occurrence.subscription_revision,
                "origin": occurrence.origin.value,
                "local_date": occurrence.local_date.isoformat(),
                "scheduled_for": _datetime_text(occurrence.scheduled_for),
                "eligible_until": _datetime_text(occurrence.eligible_until),
                "occurrence_digest": str(occurrence.occurrence_digest),
            },
            "target_policy_ref": _target_ref_payload(value.target_policy_ref),
            "created_at": _datetime_text(value.created_at),
            "expires_at": _datetime_text(value.expires_at),
            "trigger_digest": str(value.trigger_digest),
        }
    )


def decode_trigger(payload: str) -> ProactiveTrigger:
    value = _decode(payload, "trigger")
    _keys(
        value,
        {
            "schema_version",
            "trigger_id",
            "kind",
            "target_scope",
            "occurrence",
            "target_policy_ref",
            "created_at",
            "expires_at",
            "trigger_digest",
        },
        "trigger",
    )
    occurrence_value = _object(value["occurrence"], "occurrence")
    _keys(
        occurrence_value,
        {
            "schema_version",
            "occurrence_id",
            "subscription_id",
            "subscription_revision",
            "origin",
            "local_date",
            "scheduled_for",
            "eligible_until",
            "occurrence_digest",
        },
        "occurrence",
    )
    occurrence = ScheduleOccurrence(
        schema_version=_int(occurrence_value["schema_version"], "schema_version"),
        occurrence_id=_str(occurrence_value["occurrence_id"], "occurrence_id"),
        subscription_id=_str(occurrence_value["subscription_id"], "subscription_id"),
        subscription_revision=_int(
            occurrence_value["subscription_revision"], "subscription_revision"
        ),
        origin=_enum(
            ScheduleOccurrenceOrigin,
            occurrence_value["origin"],
            "occurrence_origin",
        ),
        local_date=_date(occurrence_value["local_date"], "local_date"),
        scheduled_for=_datetime(occurrence_value["scheduled_for"], "scheduled_for"),
        eligible_until=_datetime(occurrence_value["eligible_until"], "eligible_until"),
        occurrence_digest=DigestString(
            _str(occurrence_value["occurrence_digest"], "occurrence_digest")
        ),
    )
    return ProactiveTrigger(
        schema_version=_int(value["schema_version"], "schema_version"),
        trigger_id=_str(value["trigger_id"], "trigger_id"),
        kind=_enum(ProactiveTriggerKind, value["kind"], "trigger_kind"),
        target_scope=_scope(_object(value["target_scope"], "target_scope")),
        occurrence=occurrence,
        opportunity=None,
        target_policy_ref=_target_ref(
            _object(value["target_policy_ref"], "target_policy_ref")
        ),
        created_at=_datetime(value["created_at"], "created_at"),
        expires_at=_datetime(value["expires_at"], "expires_at"),
        trigger_digest=DigestString(_str(value["trigger_digest"], "trigger_digest")),
    )


def encode_claim(value: ScheduleTriggerClaim) -> str:
    if not isinstance(value, ScheduleTriggerClaim):
        raise validation_error("invalid_scheduler_claim")
    return _encode(
        {
            "schema_version": value.schema_version,
            "claim_id": value.claim_id,
            "trigger": json.loads(encode_trigger(value.trigger)),
            "worker_id": value.worker_id,
            "lease_revision": value.lease_revision,
            "claimed_at": _datetime_text(value.claimed_at),
            "expires_at": _datetime_text(value.expires_at),
            "claim_digest": str(value.claim_digest),
        }
    )


def decode_claim(payload: str) -> ScheduleTriggerClaim:
    value = _decode(payload, "claim")
    _keys(
        value,
        {
            "schema_version",
            "claim_id",
            "trigger",
            "worker_id",
            "lease_revision",
            "claimed_at",
            "expires_at",
            "claim_digest",
        },
        "claim",
    )
    return ScheduleTriggerClaim(
        schema_version=_int(value["schema_version"], "schema_version"),
        claim_id=_str(value["claim_id"], "claim_id"),
        trigger=decode_trigger(_encode(_object(value["trigger"], "trigger"))),
        worker_id=_str(value["worker_id"], "worker_id"),
        lease_revision=_int(value["lease_revision"], "lease_revision"),
        claimed_at=_datetime(value["claimed_at"], "claimed_at"),
        expires_at=_datetime(value["expires_at"], "expires_at"),
        claim_digest=DigestString(_str(value["claim_digest"], "claim_digest")),
    )


def encode_mutation_receipt(value: SubscriptionMutationReceipt) -> str:
    if not isinstance(value, SubscriptionMutationReceipt):
        raise validation_error("invalid_subscription_mutation_receipt")
    return _encode(
        {
            "schema_version": value.schema_version,
            "mutation_id": value.mutation_id,
            "subscription_id": value.subscription_id,
            "previous_revision": value.previous_revision,
            "applied_revision": value.applied_revision,
            "subscription_digest": str(value.subscription_digest),
            "status": value.status.value,
            "disposition": value.disposition.value,
            "recorded_at": _datetime_text(value.recorded_at),
            "receipt_digest": str(value.receipt_digest),
        }
    )


def decode_mutation_receipt(payload: str) -> SubscriptionMutationReceipt:
    value = _decode(payload, "mutation_receipt")
    _keys(
        value,
        {
            "schema_version",
            "mutation_id",
            "subscription_id",
            "previous_revision",
            "applied_revision",
            "subscription_digest",
            "status",
            "disposition",
            "recorded_at",
            "receipt_digest",
        },
        "mutation_receipt",
    )
    previous = value["previous_revision"]
    return SubscriptionMutationReceipt(
        schema_version=_int(value["schema_version"], "schema_version"),
        mutation_id=_str(value["mutation_id"], "mutation_id"),
        subscription_id=_str(value["subscription_id"], "subscription_id"),
        previous_revision=(
            _int(previous, "previous_revision") if previous is not None else None
        ),
        applied_revision=_int(value["applied_revision"], "applied_revision"),
        subscription_digest=DigestString(
            _str(value["subscription_digest"], "subscription_digest")
        ),
        status=_enum(SubscriptionStatus, value["status"], "subscription_status"),
        disposition=_enum(
            SubscriptionMutationDisposition,
            value["disposition"],
            "mutation_disposition",
        ),
        recorded_at=_datetime(value["recorded_at"], "recorded_at"),
        receipt_digest=DigestString(_str(value["receipt_digest"], "receipt_digest")),
    )


def encode_claim_receipt(value: ScheduleClaimReceipt) -> str:
    if not isinstance(value, ScheduleClaimReceipt):
        raise validation_error("invalid_schedule_claim_receipt")
    return _encode(
        {
            "schema_version": value.schema_version,
            "claim_digest": str(value.claim_digest),
            "occurrence_digest": str(value.occurrence_digest),
            "disposition": value.disposition.value,
            "state": value.state.value,
            "record_revision": value.record_revision,
            "completed_at": _datetime_text(value.completed_at),
            "receipt_digest": str(value.receipt_digest),
        }
    )


def decode_claim_receipt(payload: str) -> ScheduleClaimReceipt:
    value = _decode(payload, "claim_receipt")
    _keys(
        value,
        {
            "schema_version",
            "claim_digest",
            "occurrence_digest",
            "disposition",
            "state",
            "record_revision",
            "completed_at",
            "receipt_digest",
        },
        "claim_receipt",
    )
    return ScheduleClaimReceipt(
        schema_version=_int(value["schema_version"], "schema_version"),
        claim_digest=DigestString(_str(value["claim_digest"], "claim_digest")),
        occurrence_digest=DigestString(
            _str(value["occurrence_digest"], "occurrence_digest")
        ),
        disposition=_enum(
            ScheduleAckDisposition,
            value["disposition"],
            "ack_disposition",
        ),
        state=_enum(
            ScheduleOccurrenceState,
            value["state"],
            "occurrence_state",
        ),
        record_revision=_int(value["record_revision"], "record_revision"),
        completed_at=_datetime(value["completed_at"], "completed_at"),
        receipt_digest=DigestString(_str(value["receipt_digest"], "receipt_digest")),
    )


def encode_schedule_record(value: ScheduleLedgerRecord) -> str:
    if not isinstance(value, ScheduleLedgerRecord):
        raise validation_error("invalid_schedule_ledger_record")
    return _encode(
        {
            "schema_version": value.schema_version,
            "subscription_id": value.subscription_id,
            "subscription_revision": value.subscription_revision,
            "local_date": value.local_date.isoformat(),
            "state": value.state.value,
            "revision": value.revision,
            "trigger": (
                json.loads(encode_trigger(value.trigger))
                if value.trigger is not None
                else None
            ),
            "claim": (
                json.loads(encode_claim(value.claim))
                if value.claim is not None
                else None
            ),
            "updated_at": _datetime_text(value.updated_at),
            "record_digest": str(value.record_digest),
        }
    )


def decode_schedule_record(payload: str) -> ScheduleLedgerRecord:
    value = _decode(payload, "schedule_record")
    _keys(
        value,
        {
            "schema_version",
            "subscription_id",
            "subscription_revision",
            "local_date",
            "state",
            "revision",
            "trigger",
            "claim",
            "updated_at",
            "record_digest",
        },
        "schedule_record",
    )
    trigger_value = value["trigger"]
    claim_value = value["claim"]
    return ScheduleLedgerRecord(
        schema_version=_int(value["schema_version"], "schema_version"),
        subscription_id=_str(value["subscription_id"], "subscription_id"),
        subscription_revision=_int(
            value["subscription_revision"], "subscription_revision"
        ),
        local_date=_date(value["local_date"], "local_date"),
        state=_enum(ScheduleOccurrenceState, value["state"], "schedule_state"),
        revision=_int(value["revision"], "record_revision"),
        trigger=(
            decode_trigger(_encode(_object(trigger_value, "trigger")))
            if trigger_value is not None
            else None
        ),
        claim=(
            decode_claim(_encode(_object(claim_value, "claim")))
            if claim_value is not None
            else None
        ),
        updated_at=_datetime(value["updated_at"], "updated_at"),
        record_digest=DigestString(_str(value["record_digest"], "record_digest")),
    )


def encode_materialization_receipt(value: ScheduleMaterializationReceipt) -> str:
    if not isinstance(value, ScheduleMaterializationReceipt):
        raise validation_error("invalid_schedule_materialization_receipt")
    return _encode(
        {
            "schema_version": value.schema_version,
            "subscription_id": value.subscription_id,
            "subscription_revision": value.subscription_revision,
            "local_date": value.local_date.isoformat(),
            "state": value.state.value,
            "occurrence_digest": (
                str(value.occurrence_digest)
                if value.occurrence_digest is not None
                else None
            ),
            "trigger_digest": (
                str(value.trigger_digest) if value.trigger_digest is not None else None
            ),
            "created": value.created,
            "record_revision": value.record_revision,
            "recorded_at": _datetime_text(value.recorded_at),
            "receipt_digest": str(value.receipt_digest),
        }
    )


def decode_materialization_receipt(payload: str) -> ScheduleMaterializationReceipt:
    value = _decode(payload, "materialization_receipt")
    _keys(
        value,
        {
            "schema_version",
            "subscription_id",
            "subscription_revision",
            "local_date",
            "state",
            "occurrence_digest",
            "trigger_digest",
            "created",
            "record_revision",
            "recorded_at",
            "receipt_digest",
        },
        "materialization_receipt",
    )
    occurrence_digest = value["occurrence_digest"]
    trigger_digest = value["trigger_digest"]
    return ScheduleMaterializationReceipt(
        schema_version=_int(value["schema_version"], "schema_version"),
        subscription_id=_str(value["subscription_id"], "subscription_id"),
        subscription_revision=_int(
            value["subscription_revision"], "subscription_revision"
        ),
        local_date=_date(value["local_date"], "local_date"),
        state=_enum(ScheduleOccurrenceState, value["state"], "schedule_state"),
        occurrence_digest=(
            DigestString(_str(occurrence_digest, "occurrence_digest"))
            if occurrence_digest is not None
            else None
        ),
        trigger_digest=(
            DigestString(_str(trigger_digest, "trigger_digest"))
            if trigger_digest is not None
            else None
        ),
        created=_bool(value["created"], "created"),
        record_revision=_int(value["record_revision"], "record_revision"),
        recorded_at=_datetime(value["recorded_at"], "recorded_at"),
        receipt_digest=DigestString(_str(value["receipt_digest"], "receipt_digest")),
    )


def _actor_ref_payload(value: ActorRef) -> dict[str, object]:
    return {
        "platform": value.platform,
        "bot_id": value.bot_id,
        "opaque_actor_id": value.opaque_actor_id,
    }


def _actor_ref(value: Mapping[str, object]) -> ActorRef:
    _keys(value, {"platform", "bot_id", "opaque_actor_id"}, "actor_ref")
    return ActorRef(
        _str(value["platform"], "platform"),
        _str(value["bot_id"], "bot_id"),
        _str(value["opaque_actor_id"], "opaque_actor_id"),
    )


def _scope_payload(value: ConversationScope) -> dict[str, object]:
    return {
        "platform": value.platform,
        "bot_id": value.bot_id,
        "conversation_type": value.conversation_type.value,
        "conversation_id": value.conversation_id,
        "group_id": value.group_id,
        "persona_id": value.persona_id,
    }


def _scope(value: Mapping[str, object]) -> ConversationScope:
    _keys(
        value,
        {
            "platform",
            "bot_id",
            "conversation_type",
            "conversation_id",
            "group_id",
            "persona_id",
        },
        "scope",
    )
    group_id = value["group_id"]
    return ConversationScope(
        _str(value["platform"], "platform"),
        _str(value["bot_id"], "bot_id"),
        _enum(ConversationType, value["conversation_type"], "conversation_type"),
        _str(value["conversation_id"], "conversation_id"),
        _str(group_id, "group_id") if group_id is not None else None,
        _str(value["persona_id"], "persona_id"),
    )


def _grant_ref_payload(value: ProactiveAuthorizationGrantRef) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "grant_id": value.grant_id,
        "revision": value.revision,
        "authorization_decision_digest": str(value.authorization_decision_digest),
        "policy_revision": value.policy_revision,
        "grant_digest": str(value.grant_digest),
    }


def _grant_ref(value: Mapping[str, object]) -> ProactiveAuthorizationGrantRef:
    _keys(
        value,
        {
            "schema_version",
            "grant_id",
            "revision",
            "authorization_decision_digest",
            "policy_revision",
            "grant_digest",
        },
        "grant_ref",
    )
    return ProactiveAuthorizationGrantRef(
        _int(value["schema_version"], "schema_version"),
        _str(value["grant_id"], "grant_id"),
        _int(value["revision"], "grant_revision"),
        DigestString(
            _str(
                value["authorization_decision_digest"],
                "authorization_decision_digest",
            )
        ),
        _str(value["policy_revision"], "policy_revision"),
        DigestString(_str(value["grant_digest"], "grant_digest")),
    )


def _target_ref_payload(value: ProactiveTargetPolicyRef) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "target_policy_id": value.target_policy_id,
        "revision": value.revision,
        "target_scope_digest": str(value.target_scope_digest),
        "target_policy_digest": str(value.target_policy_digest),
    }


def _target_ref(value: Mapping[str, object]) -> ProactiveTargetPolicyRef:
    _keys(
        value,
        {
            "schema_version",
            "target_policy_id",
            "revision",
            "target_scope_digest",
            "target_policy_digest",
        },
        "target_ref",
    )
    return ProactiveTargetPolicyRef(
        _int(value["schema_version"], "schema_version"),
        _str(value["target_policy_id"], "target_policy_id"),
        _int(value["revision"], "target_policy_revision"),
        DigestString(_str(value["target_scope_digest"], "target_scope_digest")),
        DigestString(_str(value["target_policy_digest"], "target_policy_digest")),
    )


def _schedule_payload(value: ScheduleSpec) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "timezone": value.timezone,
        "local_time": value.local_time.isoformat(timespec="microseconds"),
        "weekdays": sorted(value.weekdays),
        "quiet_hours": [
            {
                "start": window.start.isoformat(timespec="microseconds"),
                "end": window.end.isoformat(timespec="microseconds"),
            }
            for window in value.quiet_hours
        ],
        "misfire_grace_us": _timedelta_us(value.misfire_grace),
        "schedule_revision": value.schedule_revision,
    }


def _schedule(value: Mapping[str, object]) -> ScheduleSpec:
    _keys(
        value,
        {
            "schema_version",
            "timezone",
            "local_time",
            "weekdays",
            "quiet_hours",
            "misfire_grace_us",
            "schedule_revision",
        },
        "schedule",
    )
    weekdays = _list(value["weekdays"], "weekdays")
    windows = _list(value["quiet_hours"], "quiet_hours")
    return ScheduleSpec(
        _int(value["schema_version"], "schema_version"),
        _str(value["timezone"], "timezone"),
        _time(value["local_time"], "local_time"),
        frozenset(_int(item, "weekday") for item in weekdays),
        tuple(
            LocalTimeWindow(
                _time(_object(item, "quiet_window")["start"], "quiet_start"),
                _time(_object(item, "quiet_window")["end"], "quiet_end"),
            )
            for item in windows
        ),
        _timedelta(_int(value["misfire_grace_us"], "misfire_grace_us")),
        _str(value["schedule_revision"], "schedule_revision"),
    )


def _encode(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(payload: object, field_name: str) -> dict[str, object]:
    if not isinstance(payload, str) or not payload:
        raise validation_error("invalid_scheduler_json", field_name)
    try:
        value = json.loads(payload)
    except (TypeError, ValueError):
        raise validation_error("invalid_scheduler_json", field_name) from None
    return _object(value, field_name)


def _keys(value: Mapping[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise validation_error("invalid_scheduler_json_fields", field_name)


def _object(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise validation_error("invalid_scheduler_json_object", field_name)
    return value


def _list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise validation_error("invalid_scheduler_json_list", field_name)
    return value


def _str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise validation_error("invalid_scheduler_json_string", field_name)
    return value


def _int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise validation_error("invalid_scheduler_json_integer", field_name)
    return value


_EnumT = TypeVar("_EnumT", bound=Enum)


def _enum(enum_type: type[_EnumT], value: object, field_name: str) -> _EnumT:
    raw = _str(value, field_name)
    try:
        return enum_type(raw)
    except ValueError:
        raise validation_error("invalid_scheduler_json_enum", field_name) from None


def _bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise validation_error("invalid_scheduler_json_boolean", field_name)
    return value


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise validation_error("invalid_scheduler_datetime")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _datetime(value: object, field_name: str) -> datetime:
    raw = _str(value, field_name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise validation_error("invalid_scheduler_datetime", field_name) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise validation_error("invalid_scheduler_datetime", field_name)
    return parsed.astimezone(timezone.utc)


def _date(value: object, field_name: str) -> date:
    try:
        return date.fromisoformat(_str(value, field_name))
    except ValueError:
        raise validation_error("invalid_scheduler_date", field_name) from None


def _time(value: object, field_name: str) -> time:
    try:
        parsed = time.fromisoformat(_str(value, field_name))
    except ValueError:
        raise validation_error("invalid_scheduler_time", field_name) from None
    if parsed.tzinfo is not None:
        raise validation_error("invalid_scheduler_time", field_name)
    return parsed


def _timedelta_us(value: timedelta) -> int:
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds


def _timedelta(value: int) -> timedelta:
    return timedelta(microseconds=value)


__all__ = [
    "decode_claim",
    "decode_claim_receipt",
    "decode_materialization_receipt",
    "decode_mutation_receipt",
    "decode_schedule_record",
    "decode_subscription",
    "decode_trigger",
    "encode_claim",
    "encode_claim_receipt",
    "encode_materialization_receipt",
    "encode_mutation_receipt",
    "encode_schedule_record",
    "encode_subscription",
    "encode_trigger",
]
