from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from dududa._compat import StrEnum
from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.contracts.canonical import canonical_digest
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
    schema_version: int
    max_parts: int
    max_bytes_per_part: int
    allow_forward_bundle: bool
    allowed_attachment_schemes: frozenset[str]
    reconciliation_window: timedelta

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if (
            type(self.max_parts) is not int
            or type(self.max_bytes_per_part) is not int
            or self.max_parts < 1
            or self.max_bytes_per_part < 1
            or type(self.allow_forward_bundle) is not bool
        ):
            raise validation_error("invalid_delivery_constraints")
        schemes = frozenset(self.allowed_attachment_schemes)
        if any(
            not isinstance(scheme, str)
            or re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme) is None
            for scheme in schemes
        ):
            raise validation_error("invalid_delivery_attachment_scheme")
        if not isinstance(
            self.reconciliation_window, timedelta
        ) or self.reconciliation_window <= timedelta(0):
            raise validation_error("invalid_delivery_reconciliation_window")
        object.__setattr__(self, "allowed_attachment_schemes", schemes)


@dataclass(frozen=True, slots=True)
class DeliveryPartIntent:
    schema_version: int
    part_id: str
    text: str | None
    content_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.part_id, "delivery_part_intent_id")
        require_non_empty(str(self.content_digest), "delivery_part_intent_digest")
        if self.text is not None and not self.text:
            raise validation_error("empty_delivery_part_intent_text")


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
    part_intents: tuple[DeliveryPartIntent, ...]
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
        if not isinstance(self.constraints, DeliveryConstraints):
            raise validation_error("invalid_delivery_constraints")
        if not isinstance(self.authorization, AuthorizationDecision):
            raise validation_error("invalid_delivery_authorization")
        if not isinstance(self.adapter_binding, NegotiatedBindingReceipt):
            raise validation_error("invalid_delivery_adapter_binding")
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
        part_intents = tuple(self.part_intents)
        if not part_intents or not all(
            isinstance(part, DeliveryPartIntent) for part in part_intents
        ):
            raise validation_error("missing_delivery_part_intents")
        if len(part_intents) > self.constraints.max_parts:
            raise validation_error("delivery_part_limit_exceeded")
        if len({part.part_id for part in part_intents}) != len(part_intents):
            raise validation_error("duplicate_delivery_part_intent")
        if any(
            part.text is not None
            and len(part.text.encode("utf-8")) > self.constraints.max_bytes_per_part
            for part in part_intents
        ):
            raise validation_error("delivery_part_limit_exceeded")
        expected_parts = plan_delivery_parts(
            self.delivery_id,
            self.response,
            self.reaction,
            reply_to=self.reply_to,
            constraints=self.constraints,
            payload_digest=self.payload_digest,
        )
        if part_intents != expected_parts:
            raise validation_error("delivery_part_intent_mismatch")
        object.__setattr__(self, "part_intents", part_intents)
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
        generated = (
            self.response.response.attachments if self.response is not None else ()
        )
        if generated:
            allowed = self.constraints.allowed_attachment_schemes
            if not allowed:
                raise validation_error("delivery_attachments_not_allowed")
            for attachment in generated:
                scheme, separator, _ = attachment.content_ref.partition(":")
                if not separator or scheme not in allowed:
                    raise validation_error("delivery_attachment_scheme_not_allowed")


def plan_delivery_parts(
    delivery_id: str,
    response: ValidatedFinalResponse | None,
    reaction: Reaction | None,
    *,
    reply_to: MessageReference | None,
    constraints: DeliveryConstraints,
    payload_digest: DigestString,
) -> tuple[DeliveryPartIntent, ...]:
    require_non_empty(delivery_id, "delivery_id")
    if not isinstance(constraints, DeliveryConstraints):
        raise validation_error("invalid_delivery_constraints")
    require_non_empty(str(payload_digest), "payload_digest")
    if (response is None) == (reaction is None):
        raise validation_error("delivery_requires_one_payload")
    if reaction is not None:
        part_id = f"{delivery_id}:0001"
        return (DeliveryPartIntent(1, part_id, None, payload_digest),)
    if response is None:
        raise validation_error("delivery_response_missing")
    texts: list[str] = []
    for block in response.response.blocks:
        if block.content.text is None:
            raise validation_error("generated_asset_delivery_not_enabled")
        texts.append(block.content.text)
    split = _split_utf8_parts(
        tuple(texts),
        maximum_bytes=constraints.max_bytes_per_part,
        maximum_parts=constraints.max_parts,
    )
    targets = tuple(
        target.actor_ref.opaque_actor_id for target in response.response.target_users
    )
    intents: list[DeliveryPartIntent] = []
    for index, text in enumerate(split, start=1):
        part_id = f"{delivery_id}:{index:04d}"
        digest = canonical_digest(
            {
                "part_id": part_id,
                "reply_to": reply_to if index == 1 else None,
                "target_user_ids": targets if index == 1 else (),
                "text": text,
            },
            domain="delivery:part:v1",
        )
        intents.append(DeliveryPartIntent(1, part_id, text, digest))
    return tuple(intents)


def _split_utf8_parts(
    texts: tuple[str, ...],
    *,
    maximum_bytes: int,
    maximum_parts: int,
) -> tuple[str, ...]:
    result: list[str] = []
    for text in texts:
        remaining = text
        while remaining:
            end = _utf8_prefix_end(remaining, maximum_bytes)
            if end == 0:
                raise validation_error("delivery_part_limit_exceeded")
            if end < len(remaining):
                end = _preferred_text_boundary(remaining, end)
            result.append(remaining[:end])
            remaining = remaining[end:]
    if not result or len(result) > maximum_parts:
        raise validation_error("delivery_part_limit_exceeded")
    return tuple(result)


def _utf8_prefix_end(text: str, maximum_bytes: int) -> int:
    used = 0
    for index, character in enumerate(text):
        size = len(character.encode("utf-8"))
        if used + size > maximum_bytes:
            return index
        used += size
    return len(text)


def _preferred_text_boundary(text: str, hard_end: int) -> int:
    minimum = max(1, hard_end // 2)
    for index in range(hard_end - 1, minimum - 1, -1):
        if text[index] in "\n。！？；;!?，,、 \t":
            return index + 1
    return hard_end


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


def validate_delivery_receipt_against_request(
    request: DeliveryRequest,
    receipt: DeliveryReceipt,
) -> DeliveryReceipt:
    if not isinstance(request, DeliveryRequest) or not isinstance(
        receipt, DeliveryReceipt
    ):
        raise validation_error("invalid_delivery_receipt_binding_input")
    if (
        receipt.delivery_id != request.delivery_id
        or receipt.run_id != request.run_id
        or receipt.delivery_request_digest != request.request_digest
        or receipt.idempotency_key != request.idempotency_key
        or receipt.attempt != request.attempt
        or receipt.adapter_revision != request.adapter_binding.component_revision
    ):
        raise validation_error("delivery_receipt_request_mismatch")
    intent_by_id = {part.part_id: part for part in request.part_intents}
    for part in receipt.parts:
        intent = intent_by_id.get(part.part_id)
        if intent is None or intent.content_digest != part.content_digest:
            raise validation_error("delivery_receipt_part_mismatch")
        reference = part.platform_message_ref
        if reference is not None and (
            reference.platform != request.scope.platform
            or reference.bot_id != request.scope.bot_id
            or reference.conversation_id != request.scope.conversation_id
        ):
            raise validation_error("delivery_part_scope_mismatch")
    if receipt.status is DeliveryStatus.SUCCEEDED and {
        part.part_id for part in receipt.parts
    } != set(intent_by_id):
        raise validation_error("successful_delivery_missing_part")
    return receipt


def canonicalize_delivery_receipt(
    request: DeliveryRequest,
    receipt: DeliveryReceipt,
) -> DeliveryReceipt:
    """Bind, complete and order Adapter evidence before it enters Runtime state."""

    validate_delivery_receipt_against_request(request, receipt)
    observed = {part.part_id: part for part in receipt.parts}
    parts = tuple(
        observed.get(intent.part_id)
        or DeliveryPartReceipt(
            schema_version=1,
            part_id=intent.part_id,
            content_digest=intent.content_digest,
            status=DeliveryPartStatus.UNKNOWN,
            platform_message_ref=None,
            error_code="delivery_part_not_acknowledged",
        )
        for intent in request.part_intents
    )
    statuses = {part.status for part in parts}
    if statuses == {DeliveryPartStatus.SUCCEEDED}:
        status = DeliveryStatus.SUCCEEDED
        error_code = None
    elif DeliveryPartStatus.SUCCEEDED in statuses:
        status = DeliveryStatus.PARTIAL
        error_code = receipt.error_code or "delivery_partial"
    elif DeliveryPartStatus.UNKNOWN in statuses:
        status = DeliveryStatus.UNKNOWN
        error_code = receipt.error_code or "delivery_unknown"
    else:
        status = DeliveryStatus.FAILED
        error_code = receipt.error_code or "delivery_failed"
    return replace(
        receipt,
        status=status,
        parts=parts,
        error_code=error_code,
    )


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
