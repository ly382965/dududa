from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.content import Reaction, ValidatedFinalResponse
from dududa.domain.delivery import DeliveryRequest
from dududa.domain.primitives import DigestString, JsonValue, ResourceRef
from dududa.security.digests import scope_digest


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


def delivery_authorization_resource(request: DeliveryRequest) -> ResourceRef:
    return ResourceRef(
        "delivery",
        request.delivery_id,
        scope_digest(request.scope),
    )


def delivery_authorization_metadata(
    request: DeliveryRequest,
    *,
    policy_snapshot_id: str,
) -> dict[str, JsonValue]:
    intent = {
        "schema_version": request.schema_version,
        "delivery_id": request.delivery_id,
        "run_id": request.run_id,
        "payload_digest": request.payload_digest,
        "idempotency_key": request.idempotency_key,
        "attempt": request.attempt,
        "outcome": request.outcome,
        "scope": request.scope,
        "reply_to": request.reply_to,
        "constraints": request.constraints,
        "attachment_access": request.attachment_access,
        "adapter_binding": request.adapter_binding,
    }
    return {
        "delivery_intent_digest": canonical_digest(
            intent,
            domain="delivery:authorization-intent:v1",
        ),
        "policy_snapshot_id": policy_snapshot_id,
    }
