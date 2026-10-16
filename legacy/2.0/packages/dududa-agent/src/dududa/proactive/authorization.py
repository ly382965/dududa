from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    JsonValue,
    ResourceRef,
    RiskLevel,
)
from dududa.errors import validation_error
from dududa.security.digests import (
    actor_digest,
    authorization_metadata_digest,
    authorization_request_digest,
    resource_digest,
    scope_digest,
)
from dududa.security.models import (
    AuthorizationDecision,
    AuthorizationEffect,
    AuthorizationRequest,
)
from dududa.security.ports import AuthorizationDecisionVerifier

from .contracts import (
    ProactivePreviewRequest,
    ProactiveTargetPolicyRef,
    ProactiveTrigger,
)

PROACTIVE_SEND_ACTION = ActionId("message.send.proactive")
PROACTIVE_PREVIEW_ACTION = ActionId("proactive.subscription.preview")


def build_proactive_send_authorization_request(
    actor: Actor,
    scope: ConversationScope,
    trigger: ProactiveTrigger,
    *,
    target_policy_ref: ProactiveTargetPolicyRef,
    policy_snapshot_id: str,
    content_digest: str | None = None,
    item_set_digest: str | None = None,
) -> AuthorizationRequest:
    if (
        not isinstance(actor, Actor)
        or not isinstance(scope, ConversationScope)
        or not isinstance(trigger, ProactiveTrigger)
        or not isinstance(target_policy_ref, ProactiveTargetPolicyRef)
        or scope != trigger.target_scope
        or trigger.target_policy_ref != target_policy_ref
    ):
        raise validation_error("invalid_proactive_send_authorization_input")
    metadata: dict[str, JsonValue] = {
        "policy_snapshot_id": _string(
            policy_snapshot_id,
            "policy_snapshot_id",
        ),
        "purpose": "proactive_delivery",
        "trigger_kind": trigger.kind.value,
        "trigger_digest": str(trigger.trigger_digest),
        "target_policy_id": target_policy_ref.target_policy_id,
        "target_policy_revision": target_policy_ref.revision,
        "target_policy_digest": str(target_policy_ref.target_policy_digest),
        "content_digest": _optional_string(content_digest, "content_digest"),
        "item_set_digest": _optional_string(item_set_digest, "item_set_digest"),
    }
    return _build_request(
        actor,
        scope,
        action=PROACTIVE_SEND_ACTION,
        resource=ResourceRef(
            resource_type="proactive_target",
            resource_id=target_policy_ref.target_policy_id,
            scope_digest=scope_digest(scope),
        ),
        metadata=metadata,
    )


def build_proactive_preview_authorization_request(
    request: ProactivePreviewRequest,
    *,
    policy_snapshot_id: str,
) -> AuthorizationRequest:
    if not isinstance(request, ProactivePreviewRequest):
        raise validation_error("invalid_proactive_preview_authorization_input")
    if request.action != str(PROACTIVE_PREVIEW_ACTION):
        raise validation_error("invalid_proactive_preview_action")
    metadata: dict[str, JsonValue] = {
        "policy_snapshot_id": _string(
            policy_snapshot_id,
            "policy_snapshot_id",
        ),
        "purpose": "proactive_subscription_preview",
        "preview_request_digest": str(request.request_digest),
        "subscription_id": request.subscription_id,
        "subscription_revision": request.subscription_revision,
        "target_policy_id": request.target_policy_ref.target_policy_id,
        "target_policy_revision": request.target_policy_ref.revision,
        "target_policy_digest": str(request.target_policy_ref.target_policy_digest),
    }
    return _build_request(
        request.requested_by,
        request.target_scope,
        action=PROACTIVE_PREVIEW_ACTION,
        resource=ResourceRef(
            resource_type="proactive_subscription_preview",
            resource_id=request.subscription_id,
            scope_digest=scope_digest(request.target_scope),
        ),
        metadata=metadata,
    )


def proactive_authorization_allows(
    request: AuthorizationRequest,
    decision: AuthorizationDecision,
    verifier: AuthorizationDecisionVerifier,
    *,
    at: datetime,
    expected_policy_revision: str,
) -> bool:
    if (
        not isinstance(request, AuthorizationRequest)
        or not isinstance(decision, AuthorizationDecision)
        or not isinstance(at, datetime)
        or at.tzinfo is None
        or at.utcoffset() is None
        or not isinstance(expected_policy_revision, str)
        or not expected_policy_revision.strip()
        or request.action not in {PROACTIVE_SEND_ACTION, PROACTIVE_PREVIEW_ACTION}
        or decision.effect is not AuthorizationEffect.ALLOW
    ):
        return False
    try:
        verified = verifier.verify(decision, at=at)
    except Exception:  # noqa: BLE001 - verifier failure is a deterministic deny.
        return False
    return bool(verified) and (
        decision.request_digest == request.request_digest
        and decision.actor_digest == actor_digest(request.actor)
        and decision.scope_digest == scope_digest(request.conversation_scope)
        and decision.action == request.action
        and decision.resource_digest == resource_digest(request.resource)
        and decision.capability_id is None
        and decision.risk_level is request.risk_level
        and decision.metadata_digest == authorization_metadata_digest(request.metadata)
        and decision.policy_revision == expected_policy_revision
        and decision.decided_at <= at < decision.expires_at
    )


def _build_request(
    actor: Actor,
    scope: ConversationScope,
    *,
    action: ActionId,
    resource: ResourceRef,
    metadata: Mapping[str, JsonValue],
) -> AuthorizationRequest:
    request = AuthorizationRequest(
        schema_version=1,
        request_digest=canonical_digest({}, domain="pending:v1"),
        actor=actor,
        conversation_scope=scope,
        action=action,
        resource=resource,
        capability_id=None,
        risk_level=RiskLevel.LOW,
        metadata=MappingProxyType(dict(metadata)),
    )
    return replace(request, request_digest=authorization_request_digest(request))


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise validation_error("invalid_proactive_authorization_string", field_name)
    return value


def _optional_string(value: object, field_name: str) -> JsonValue:
    if value is None:
        return None
    return _string(value, field_name)


__all__ = [
    "PROACTIVE_PREVIEW_ACTION",
    "PROACTIVE_SEND_ACTION",
    "build_proactive_preview_authorization_request",
    "build_proactive_send_authorization_request",
    "proactive_authorization_allows",
]
