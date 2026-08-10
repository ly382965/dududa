from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from dududa.contracts.canonical import canonical_digest
from dududa.contracts.delivery import (
    DeliveryAuthorizationIntent,
    delivery_authorization_metadata,
    delivery_authorization_resource,
)
from dududa.domain.delivery import DeliveryRequest
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    JsonValue,
    ResourceRef,
    RiskLevel,
    require_non_empty,
)
from dududa.errors import validation_error
from dududa.security.digests import authorization_request_digest, scope_digest
from dududa.security.models import AuthorizationRequest


def response_authorization_resource(scope: ConversationScope) -> ResourceRef:
    if not isinstance(scope, ConversationScope):
        raise validation_error("invalid_response_authorization_scope")
    return ResourceRef(
        resource_type="conversation",
        resource_id=scope.conversation_id,
        scope_digest=scope_digest(scope),
    )


def response_authorization_metadata(
    *,
    policy_snapshot_id: str,
) -> Mapping[str, JsonValue]:
    require_non_empty(policy_snapshot_id, "policy_snapshot_id")
    return MappingProxyType(
        {
            "policy_snapshot_id": policy_snapshot_id,
            "purpose": "direct_chat_response",
        }
    )


def capability_plan_authorization_resource(
    scope: ConversationScope,
    *,
    run_id: str,
) -> ResourceRef:
    if not isinstance(scope, ConversationScope):
        raise validation_error("invalid_capability_plan_authorization_scope")
    require_non_empty(run_id, "capability_plan_run_id")
    return ResourceRef(
        resource_type="capability-plan",
        resource_id=run_id,
        scope_digest=scope_digest(scope),
    )


def capability_plan_authorization_metadata(
    *,
    policy_snapshot_id: str,
    query_digest: str,
) -> Mapping[str, JsonValue]:
    require_non_empty(policy_snapshot_id, "policy_snapshot_id")
    require_non_empty(query_digest, "capability_plan_query_digest")
    return MappingProxyType(
        {
            "policy_snapshot_id": policy_snapshot_id,
            "purpose": "bounded_capability_plan",
            "query_digest": query_digest,
        }
    )


def build_capability_plan_authorization_request(
    actor: Actor,
    scope: ConversationScope,
    *,
    run_id: str,
    policy_snapshot_id: str,
    query_digest: str,
) -> AuthorizationRequest:
    if not isinstance(actor, Actor) or not isinstance(scope, ConversationScope):
        raise validation_error("invalid_capability_plan_authorization_identity")
    request = AuthorizationRequest(
        schema_version=1,
        request_digest=canonical_digest({}, domain="pending:v1"),
        actor=actor,
        conversation_scope=scope,
        action=ActionId("capability.plan"),
        resource=capability_plan_authorization_resource(scope, run_id=run_id),
        capability_id=None,
        risk_level=RiskLevel.LOW,
        metadata=capability_plan_authorization_metadata(
            policy_snapshot_id=policy_snapshot_id,
            query_digest=query_digest,
        ),
    )
    return replace(request, request_digest=authorization_request_digest(request))


def build_response_authorization_request(
    actor: Actor,
    scope: ConversationScope,
    *,
    policy_snapshot_id: str,
) -> AuthorizationRequest:
    if not isinstance(actor, Actor) or not isinstance(scope, ConversationScope):
        raise validation_error("invalid_response_authorization_identity")
    request = AuthorizationRequest(
        schema_version=1,
        request_digest=canonical_digest({}, domain="pending:v1"),
        actor=actor,
        conversation_scope=scope,
        action=ActionId("message.respond"),
        resource=response_authorization_resource(scope),
        capability_id=None,
        risk_level=RiskLevel.LOW,
        metadata=response_authorization_metadata(
            policy_snapshot_id=policy_snapshot_id,
        ),
    )
    return replace(request, request_digest=authorization_request_digest(request))


def build_delivery_authorization_request(
    actor: Actor,
    delivery: DeliveryRequest | DeliveryAuthorizationIntent,
    *,
    policy_snapshot_id: str,
) -> AuthorizationRequest:
    if not isinstance(actor, Actor) or not isinstance(
        delivery,
        (DeliveryRequest, DeliveryAuthorizationIntent),
    ):
        raise validation_error("invalid_delivery_authorization_input")
    request = AuthorizationRequest(
        schema_version=1,
        request_digest=canonical_digest({}, domain="pending:v1"),
        actor=actor,
        conversation_scope=delivery.scope,
        action=ActionId("message.send"),
        resource=delivery_authorization_resource(delivery),
        capability_id=None,
        risk_level=RiskLevel.LOW,
        metadata=delivery_authorization_metadata(
            delivery,
            policy_snapshot_id=policy_snapshot_id,
        ),
    )
    return replace(request, request_digest=authorization_request_digest(request))
