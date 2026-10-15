from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping

from dududa._compat import StrEnum
from dududa.domain.content import ContentSafetyDecision, SafetyStage
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    ComponentRevision,
    DigestString,
    JsonValue,
    ResourceRef,
    ResourceUsage,
    RiskLevel,
    Sensitivity,
    freeze_json,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error


class AuthorizationEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"


class LeaseDisposition(StrEnum):
    COMMITTED = "committed"
    RELEASED = "released"
    ALREADY_COMMITTED = "already_committed"
    ALREADY_RELEASED = "already_released"


class BudgetDisposition(StrEnum):
    SETTLED = "settled"
    RELEASED = "released"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    schema_version: int
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    action: ActionId
    resource: ResourceRef
    capability_id: str | None
    risk_level: RiskLevel
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        _require_digest(self.request_digest, "request_digest")
        require_non_empty(str(self.action), "action")
        if not isinstance(self.risk_level, RiskLevel):
            raise validation_error("invalid_risk_level")
        if self.capability_id is not None:
            require_non_empty(self.capability_id, "capability_id")
        if (
            self.actor.platform != self.conversation_scope.platform
            or self.actor.bot_id != self.conversation_scope.bot_id
        ):
            raise validation_error("authorization_identity_scope_mismatch")
        object.__setattr__(self, "metadata", freeze_json(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    schema_version: int
    decision_id: str
    effect: AuthorizationEffect
    request_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    action: ActionId
    resource_digest: DigestString
    capability_id: str | None
    risk_level: RiskLevel
    metadata_digest: DigestString
    policy_revision: str
    reason_codes: tuple[str, ...]
    decided_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.decision_id, "decision_id")
        if not isinstance(self.effect, AuthorizationEffect):
            raise validation_error("invalid_authorization_effect")
        if not isinstance(self.risk_level, RiskLevel):
            raise validation_error("invalid_risk_level")
        for name in (
            "request_digest",
            "actor_digest",
            "scope_digest",
            "resource_digest",
            "metadata_digest",
        ):
            _require_digest(getattr(self, name), name)
        require_non_empty(str(self.action), "action")
        require_non_empty(self.policy_revision, "policy_revision")
        require_aware(self.decided_at, "decided_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.decided_at:
            raise validation_error("authorization_expiry_not_future")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ConfirmationRequest:
    schema_version: int
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    action: ActionId
    payload_digest: DigestString
    required_permission: str
    ttl: timedelta

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        _require_digest(self.request_digest, "request_digest")
        _require_digest(self.payload_digest, "payload_digest")
        require_non_empty(str(self.action), "action")
        require_non_empty(self.required_permission, "required_permission")
        if self.ttl <= timedelta(0):
            raise validation_error("invalid_confirmation_ttl")


@dataclass(frozen=True, slots=True)
class ConfirmationConsumeRequest:
    schema_version: int
    request_digest: DigestString
    confirmation_id: str
    actor: Actor
    conversation_scope: ConversationScope
    action: ActionId
    payload_digest: DigestString
    required_permission: str
    execution_id: str
    idempotency_key: str
    authorization: AuthorizationDecision

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        _require_digest(self.request_digest, "request_digest")
        _require_digest(self.payload_digest, "payload_digest")
        for name, value in (
            ("confirmation_id", self.confirmation_id),
            ("required_permission", self.required_permission),
            ("execution_id", self.execution_id),
            ("idempotency_key", self.idempotency_key),
        ):
            require_non_empty(value, name)


@dataclass(frozen=True, slots=True)
class ConfirmationRequirement:
    schema_version: int
    confirmation_id: str
    request_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    action: ActionId
    payload_digest: DigestString
    required_permission: str
    public_prompt_key: str
    policy_revision: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name, value in (
            ("confirmation_id", self.confirmation_id),
            ("required_permission", self.required_permission),
            ("public_prompt_key", self.public_prompt_key),
            ("policy_revision", self.policy_revision),
        ):
            require_non_empty(value, name)
        for name in (
            "request_digest",
            "actor_digest",
            "scope_digest",
            "payload_digest",
        ):
            _require_digest(getattr(self, name), name)
        require_aware(self.created_at, "created_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise validation_error("invalid_confirmation_expiry")


@dataclass(frozen=True, slots=True)
class ConfirmationGrant:
    schema_version: int
    confirmation_id: str
    consume_request_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    action: ActionId
    payload_digest: DigestString
    required_permission: str
    execution_id: str
    idempotency_key: str
    authorization_digest: DigestString
    policy_revision: str
    created_at: datetime
    consumed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in (
            "confirmation_id",
            "required_permission",
            "execution_id",
            "idempotency_key",
            "policy_revision",
        ):
            require_non_empty(str(getattr(self, name)), name)
        for name in (
            "consume_request_digest",
            "actor_digest",
            "scope_digest",
            "payload_digest",
            "authorization_digest",
        ):
            _require_digest(getattr(self, name), name)
        for name in ("created_at", "consumed_at", "expires_at"):
            require_aware(getattr(self, name), name)
        if not self.created_at <= self.consumed_at < self.expires_at:
            raise validation_error("invalid_confirmation_grant_time")


@dataclass(frozen=True, slots=True)
class InteractionLimitRequest:
    schema_version: int
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    action: ActionId
    units: int
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        _require_digest(self.request_digest, "request_digest")
        require_non_empty(str(self.action), "action")
        require_non_empty(self.idempotency_key, "idempotency_key")
        if type(self.units) is not int or self.units < 1:
            raise validation_error("invalid_interaction_units")


@dataclass(frozen=True, slots=True)
class InteractionLease:
    schema_version: int
    lease_id: str
    allowed: bool
    request_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    action: ActionId
    units: int
    idempotency_key: str
    policy_revision: str
    reason_codes: tuple[str, ...]
    reserved_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class InteractionLeaseReceipt:
    schema_version: int
    lease_id: str
    idempotency_key: str
    disposition: LeaseDisposition
    limiter_revision: ComponentRevision
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class BudgetReservationRequest:
    schema_version: int
    request_digest: DigestString
    resource: ResourceRef
    maximum: ResourceUsage
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        _require_digest(self.request_digest, "request_digest")
        require_non_empty(self.idempotency_key, "idempotency_key")


@dataclass(frozen=True, slots=True)
class BudgetLease:
    schema_version: int
    lease_id: str
    request_digest: DigestString
    resource_digest: DigestString
    idempotency_key: str
    reserved: ResourceUsage
    policy_revision: str
    reserved_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class BudgetReceipt:
    schema_version: int
    lease_id: str
    request_digest: DigestString
    usage_digest: DigestString
    idempotency_key: str
    disposition: BudgetDisposition
    charged: ResourceUsage
    remaining: ResourceUsage
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class RedactionRequest:
    schema_version: int
    value: JsonValue
    sensitivity: Sensitivity
    purpose: str

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        if not isinstance(self.sensitivity, Sensitivity):
            raise validation_error("invalid_sensitivity")
        require_non_empty(self.purpose, "purpose")
        object.__setattr__(self, "value", freeze_json(self.value))


@dataclass(frozen=True, slots=True)
class RedactionResult:
    schema_version: int
    value: JsonValue
    changed: bool
    reason_codes: tuple[str, ...]
    redactor_revision: str

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.redactor_revision, "redactor_revision")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ContentSafetyRequest:
    schema_version: int
    request_id: str
    request_digest: DigestString
    stage: SafetyStage
    content: JsonValue
    content_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.request_id, "request_id")
        if not isinstance(self.stage, SafetyStage):
            raise validation_error("invalid_safety_stage")
        for name in (
            "request_digest",
            "content_digest",
            "actor_digest",
            "scope_digest",
        ):
            _require_digest(getattr(self, name), name)
        object.__setattr__(self, "content", freeze_json(self.content))


@dataclass(frozen=True, slots=True)
class AuditEvent:
    schema_version: int
    event_id: str
    event_digest: DigestString
    timestamp: datetime
    run_id: str | None
    operation_id: str
    trace_id: str
    span_id: str | None
    actor_digest: DigestString | None
    scope_digest: DigestString | None
    action: ActionId
    decision: str
    authorization_decision_id: str | None
    request_digest: DigestString
    policy_revisions: tuple[str, ...]
    component_revisions: tuple[ComponentRevision, ...]
    reason_codes: tuple[str, ...]
    resource_digest: DigestString
    sanitized_detail: JsonValue
    sensitivity: Sensitivity
    outcome: str

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in ("event_id", "operation_id", "trace_id", "decision", "outcome"):
            require_non_empty(str(getattr(self, name)), name)
        for name in ("event_digest", "request_digest", "resource_digest"):
            _require_digest(getattr(self, name), name)
        require_aware(self.timestamp, "timestamp")
        if not isinstance(self.sensitivity, Sensitivity):
            raise validation_error("invalid_sensitivity")
        object.__setattr__(self, "policy_revisions", tuple(self.policy_revisions))
        object.__setattr__(self, "component_revisions", tuple(self.component_revisions))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "sanitized_detail", freeze_json(self.sanitized_detail))


@dataclass(frozen=True, slots=True)
class AuditReceipt:
    schema_version: int
    event_id: str
    event_digest: DigestString
    persisted: bool
    sink_revision: str


@dataclass(frozen=True, slots=True)
class TraceReceipt:
    schema_version: int
    event_id: str
    accepted: bool
    sink_revision: str


@dataclass(frozen=True, slots=True)
class SecretRef:
    schema_version: int
    namespace: str
    secret_id: str
    version_hint: str | None = None

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.namespace, "namespace")
        require_non_empty(self.secret_id, "secret_id")


def _require_v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _require_digest(value: DigestString, name: str) -> None:
    require_non_empty(str(value), name)


__all__ = [
    "AuditEvent",
    "AuditReceipt",
    "AuthorizationDecision",
    "AuthorizationEffect",
    "AuthorizationRequest",
    "BudgetDisposition",
    "BudgetLease",
    "BudgetReceipt",
    "BudgetReservationRequest",
    "ConfirmationConsumeRequest",
    "ConfirmationGrant",
    "ConfirmationRequest",
    "ConfirmationRequirement",
    "ContentSafetyDecision",
    "ContentSafetyRequest",
    "InteractionLease",
    "InteractionLeaseReceipt",
    "InteractionLimitRequest",
    "LeaseDisposition",
    "RedactionRequest",
    "RedactionResult",
    "SecretRef",
    "TraceReceipt",
]
