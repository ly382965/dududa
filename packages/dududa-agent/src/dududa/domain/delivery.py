from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dududa._compat import StrEnum
from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.errors import validation_error
from dududa.security.models import AuthorizationDecision

from .attachments import AttachmentAccessRequest
from .content import Reaction, ValidatedFinalResponse
from .identity import ConversationScope
from .message import MessageReference
from .primitives import (
    ComponentRevision,
    DigestString,
    Outcome,
    require_aware,
    require_non_empty,
)


class DeliveryStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DeliveryPartStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DeliveryConstraints:
    max_parts: int
    max_part_characters: int
    allow_forward_nodes: bool

    def __post_init__(self) -> None:
        if (
            type(self.max_parts) is not int
            or type(self.max_part_characters) is not int
            or self.max_parts < 1
            or self.max_part_characters < 1
            or type(self.allow_forward_nodes) is not bool
        ):
            raise validation_error("invalid_delivery_constraints")


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    schema_version: int
    delivery_id: str
    run_id: str
    request_digest: DigestString
    payload_digest: DigestString
    idempotency_key: str
    attempt: int
    outcome: Outcome
    response: ValidatedFinalResponse | None
    reaction: Reaction | None
    scope: ConversationScope
    reply_to: MessageReference | None
    constraints: DeliveryConstraints
    authorization: AuthorizationDecision
    attachment_access: tuple[AttachmentAccessRequest, ...]
    adapter_binding: NegotiatedBindingReceipt

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.delivery_id, "delivery_id")
        require_non_empty(self.run_id, "run_id")
        require_non_empty(self.idempotency_key, "idempotency_key")
        require_non_empty(str(self.request_digest), "request_digest")
        require_non_empty(str(self.payload_digest), "payload_digest")
        if type(self.attempt) is not int or self.attempt < 1:
            raise validation_error("invalid_delivery_attempt")
        if (self.response is None) == (self.reaction is None):
            raise validation_error("delivery_requires_one_payload")
        if not isinstance(self.outcome, Outcome) or self.outcome not in {
            Outcome.RESPONSE,
            Outcome.REACTION,
            Outcome.DEFERRED,
            Outcome.FAILED,
        }:
            raise validation_error("invalid_delivery_outcome")
        if self.outcome in {Outcome.RESPONSE, Outcome.DEFERRED, Outcome.FAILED} and (
            self.response is None or self.reaction is not None
        ):
            raise validation_error("delivery_outcome_payload_mismatch")
        if self.outcome is Outcome.REACTION and (
            self.reaction is None or self.response is not None
        ):
            raise validation_error("delivery_outcome_payload_mismatch")
        if self.reply_to is not None and (
            self.reply_to.platform != self.scope.platform
            or self.reply_to.bot_id != self.scope.bot_id
            or self.reply_to.conversation_id != self.scope.conversation_id
        ):
            raise validation_error("delivery_reply_scope_mismatch")
        access = tuple(self.attachment_access)
        if any(item.conversation_scope != self.scope for item in access):
            raise validation_error("delivery_attachment_scope_mismatch")
        object.__setattr__(self, "attachment_access", access)


@dataclass(frozen=True, slots=True)
class DeliveryPartReceipt:
    schema_version: int
    part_id: str
    content_digest: DigestString
    status: DeliveryPartStatus
    platform_message_ref: MessageReference | None
    error_code: str | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.part_id, "part_id")
        require_non_empty(str(self.content_digest), "content_digest")
        if not isinstance(self.status, DeliveryPartStatus):
            raise validation_error("invalid_delivery_part_status")
        if self.status is DeliveryPartStatus.SUCCEEDED and self.error_code is not None:
            raise validation_error("successful_delivery_part_has_error")
        if self.status is DeliveryPartStatus.FAILED and not self.error_code:
            raise validation_error("failed_delivery_part_requires_error")


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    schema_version: int
    delivery_id: str
    run_id: str
    delivery_request_digest: DigestString
    idempotency_key: str
    attempt: int
    adapter_revision: ComponentRevision
    status: DeliveryStatus
    parts: tuple[DeliveryPartReceipt, ...]
    acknowledged_at: datetime
    error_code: str | None = None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.status, DeliveryStatus):
            raise validation_error("invalid_delivery_status")
        if self.status is DeliveryStatus.NOT_REQUIRED:
            raise validation_error("real_delivery_cannot_be_not_required")
        require_non_empty(self.delivery_id, "delivery_id")
        require_non_empty(self.run_id, "run_id")
        require_non_empty(str(self.delivery_request_digest), "delivery_request_digest")
        require_non_empty(self.idempotency_key, "idempotency_key")
        require_aware(self.acknowledged_at, "acknowledged_at")
        if type(self.attempt) is not int or self.attempt < 1:
            raise validation_error("invalid_delivery_attempt")
        parts = tuple(self.parts)
        if not parts:
            raise validation_error("empty_delivery_receipt")
        if len({part.part_id for part in parts}) != len(parts):
            raise validation_error("duplicate_delivery_part")
        part_statuses = {part.status for part in parts}
        valid = (
            (
                self.status is DeliveryStatus.SUCCEEDED
                and part_statuses == {DeliveryPartStatus.SUCCEEDED}
            )
            or (
                self.status is DeliveryStatus.PARTIAL
                and DeliveryPartStatus.SUCCEEDED in part_statuses
                and bool(part_statuses - {DeliveryPartStatus.SUCCEEDED})
            )
            or (
                self.status is DeliveryStatus.FAILED
                and part_statuses == {DeliveryPartStatus.FAILED}
            )
            or (
                self.status is DeliveryStatus.UNKNOWN
                and DeliveryPartStatus.SUCCEEDED not in part_statuses
                and DeliveryPartStatus.UNKNOWN in part_statuses
            )
        )
        if not valid:
            raise validation_error("inconsistent_delivery_status")
        if self.status is DeliveryStatus.SUCCEEDED and self.error_code is not None:
            raise validation_error("successful_delivery_has_error")
        object.__setattr__(self, "parts", parts)


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
