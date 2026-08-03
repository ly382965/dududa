from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import DigestString, JsonValue, ResourceRef, ResourceUsage
from typing import Mapping

from .models import (
    AuditEvent,
    AuthorizationDecision,
    AuthorizationRequest,
    BudgetReservationRequest,
    ConfirmationConsumeRequest,
    ConfirmationRequest,
    ContentSafetyRequest,
    InteractionLimitRequest,
)


def actor_digest(actor: Actor) -> DigestString:
    return canonical_digest(actor, domain="security:actor:v1")


def scope_digest(scope: ConversationScope) -> DigestString:
    return canonical_digest(scope, domain="security:conversation-scope:v1")


def resource_digest(resource: ResourceRef) -> DigestString:
    return canonical_digest(resource, domain="security:resource:v1")


def authorization_metadata_digest(
    metadata: Mapping[str, JsonValue],
) -> DigestString:
    return canonical_digest(metadata, domain="security:authorization-metadata:v1")


def usage_digest(usage: ResourceUsage) -> DigestString:
    return canonical_digest(usage, domain="security:resource-usage:v1")


def authorization_request_digest(request: AuthorizationRequest) -> DigestString:
    return canonical_digest(
        {
            "schema_version": request.schema_version,
            "actor": request.actor,
            "conversation_scope": request.conversation_scope,
            "action": request.action,
            "resource": request.resource,
            "capability_id": request.capability_id,
            "risk_level": request.risk_level,
            "metadata": request.metadata,
        },
        domain="security:authorization-request:v1",
    )


def authorization_decision_digest(decision: AuthorizationDecision) -> DigestString:
    return canonical_digest(decision, domain="security:authorization-decision:v1")


def confirmation_request_digest(request: ConfirmationRequest) -> DigestString:
    return canonical_digest(
        {
            "schema_version": request.schema_version,
            "actor": request.actor,
            "conversation_scope": request.conversation_scope,
            "action": request.action,
            "payload_digest": request.payload_digest,
            "required_permission": request.required_permission,
            "ttl_seconds": request.ttl.total_seconds(),
        },
        domain="security:confirmation-request:v1",
    )


def confirmation_consume_request_digest(
    request: ConfirmationConsumeRequest,
) -> DigestString:
    return canonical_digest(
        {
            "schema_version": request.schema_version,
            "confirmation_id": request.confirmation_id,
            "actor": request.actor,
            "conversation_scope": request.conversation_scope,
            "action": request.action,
            "payload_digest": request.payload_digest,
            "required_permission": request.required_permission,
            "execution_id": request.execution_id,
            "idempotency_key": request.idempotency_key,
            "authorization": request.authorization,
        },
        domain="security:confirmation-consume-request:v1",
    )


def interaction_limit_request_digest(request: InteractionLimitRequest) -> DigestString:
    return canonical_digest(
        {
            "schema_version": request.schema_version,
            "actor": request.actor,
            "conversation_scope": request.conversation_scope,
            "action": request.action,
            "units": request.units,
            "idempotency_key": request.idempotency_key,
        },
        domain="security:interaction-limit-request:v1",
    )


def budget_reservation_request_digest(
    request: BudgetReservationRequest,
) -> DigestString:
    return canonical_digest(
        {
            "schema_version": request.schema_version,
            "resource": request.resource,
            "maximum": request.maximum,
            "idempotency_key": request.idempotency_key,
        },
        domain="security:budget-reservation-request:v1",
    )


def content_safety_request_digest(request: ContentSafetyRequest) -> DigestString:
    return canonical_digest(
        {
            "schema_version": request.schema_version,
            "request_id": request.request_id,
            "stage": request.stage,
            "content": request.content,
            "content_digest": request.content_digest,
            "actor_digest": request.actor_digest,
            "scope_digest": request.scope_digest,
        },
        domain="security:content-safety-request:v1",
    )


def audit_event_digest(event: AuditEvent) -> DigestString:
    values = {
        name: getattr(event, name)
        for name in event.__dataclass_fields__
        if name != "event_digest"
    }
    return canonical_digest(values, domain="security:audit-event:v1")
