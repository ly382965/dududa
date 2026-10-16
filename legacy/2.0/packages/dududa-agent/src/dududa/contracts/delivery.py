from __future__ import annotations

from dataclasses import dataclass

from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.contracts.canonical import canonical_digest
from dududa.domain.attachments import AttachmentAccessRequest
from dududa.domain.content import Reaction, ValidatedFinalResponse
from dududa.domain.delivery import (
    DeliveryConstraints,
    DeliveryPartIntent,
    DeliveryRequest,
)
from dududa.domain.identity import ConversationScope
from dududa.domain.message import MessageReference
from dududa.domain.primitives import (
    DigestString,
    JsonValue,
    Outcome,
    ResourceRef,
    require_non_empty,
)
from dududa.errors import validation_error
from dududa.security.digests import scope_digest


@dataclass(frozen=True, slots=True)
class DeliveryAuthorizationIntent:
    schema_version: int
    delivery_id: str
    run_id: str
    payload_digest: DigestString
    idempotency_key: str
    attempt: int
    outcome: Outcome
    scope: ConversationScope
    reply_to: MessageReference | None
    constraints: DeliveryConstraints
    part_intents: tuple[DeliveryPartIntent, ...]
    attachment_access: tuple[AttachmentAccessRequest, ...]
    adapter_binding: NegotiatedBindingReceipt

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.outcome, Outcome):
            raise validation_error("invalid_delivery_outcome")
        require_non_empty(self.delivery_id, "delivery_id")
        require_non_empty(self.run_id, "run_id")
        require_non_empty(str(self.payload_digest), "payload_digest")
        require_non_empty(self.idempotency_key, "idempotency_key")
        if type(self.attempt) is not int or self.attempt < 1:
            raise validation_error("invalid_delivery_attempt")
        if not isinstance(self.scope, ConversationScope):
            raise validation_error("invalid_delivery_scope")
        if not isinstance(self.constraints, DeliveryConstraints):
            raise validation_error("invalid_delivery_constraints")
        if not isinstance(self.adapter_binding, NegotiatedBindingReceipt):
            raise validation_error("invalid_delivery_adapter_binding")
        part_intents = tuple(self.part_intents)
        attachments = tuple(self.attachment_access)
        if not part_intents or not all(
            isinstance(part, DeliveryPartIntent) for part in part_intents
        ):
            raise validation_error("missing_delivery_part_intents")
        if not all(isinstance(item, AttachmentAccessRequest) for item in attachments):
            raise validation_error("invalid_delivery_attachment_access")
        object.__setattr__(self, "part_intents", part_intents)
        object.__setattr__(self, "attachment_access", attachments)


def delivery_payload_digest(
    payload: ValidatedFinalResponse | Reaction,
) -> DigestString:
    return canonical_digest(payload, domain="delivery:payload:v1")


def delivery_request_digest(request: DeliveryRequest) -> DigestString:
    values = {
        name: getattr(request, name)
        for name in request.__dataclass_fields__
        if name != "request_digest"
    }
    return canonical_digest(values, domain="delivery:request:v1")


def delivery_authorization_intent(
    request: DeliveryRequest,
) -> DeliveryAuthorizationIntent:
    return DeliveryAuthorizationIntent(
        schema_version=request.schema_version,
        delivery_id=request.delivery_id,
        run_id=request.run_id,
        payload_digest=request.payload_digest,
        idempotency_key=request.idempotency_key,
        attempt=request.attempt,
        outcome=request.outcome,
        scope=request.scope,
        reply_to=request.reply_to,
        constraints=request.constraints,
        part_intents=request.part_intents,
        attachment_access=request.attachment_access,
        adapter_binding=request.adapter_binding,
    )


def delivery_authorization_resource(
    request: DeliveryRequest | DeliveryAuthorizationIntent,
) -> ResourceRef:
    intent = (
        delivery_authorization_intent(request)
        if isinstance(request, DeliveryRequest)
        else request
    )
    return ResourceRef(
        "delivery",
        intent.delivery_id,
        scope_digest(intent.scope),
    )


def delivery_authorization_metadata(
    request: DeliveryRequest | DeliveryAuthorizationIntent,
    *,
    policy_snapshot_id: str,
) -> dict[str, JsonValue]:
    value = (
        delivery_authorization_intent(request)
        if isinstance(request, DeliveryRequest)
        else request
    )
    return {
        "delivery_intent_digest": canonical_digest(
            value,
            domain="delivery:authorization-intent:v1",
        ),
        "policy_snapshot_id": policy_snapshot_id,
    }
