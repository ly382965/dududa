from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.domain.capability import CapabilityDefinition
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import ActionId, ResourceRef
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

from .contracts import CapabilityCatalogSnapshot


class CapabilityAuthorizationPurpose(StrEnum):
    RETRIEVAL = "retrieval"
    EXECUTION = "execution"


def capability_authorization_resource(
    definition: CapabilityDefinition,
    scope: ConversationScope,
) -> ResourceRef:
    if not isinstance(definition, CapabilityDefinition) or not isinstance(
        scope, ConversationScope
    ):
        raise validation_error("invalid_capability_authorization_resource")
    return ResourceRef(
        resource_type="capability",
        resource_id=definition.capability_id,
        scope_digest=scope_digest(scope),
    )


def build_capability_authorization_request(
    definition: CapabilityDefinition,
    actor: Actor,
    scope: ConversationScope,
    catalog: CapabilityCatalogSnapshot,
    *,
    permission: str,
    purpose: CapabilityAuthorizationPurpose,
    policy_snapshot_id: str,
) -> AuthorizationRequest:
    if (
        not isinstance(definition, CapabilityDefinition)
        or not isinstance(actor, Actor)
        or not isinstance(scope, ConversationScope)
        or not isinstance(catalog, CapabilityCatalogSnapshot)
        or not isinstance(purpose, CapabilityAuthorizationPurpose)
        or permission not in definition.required_permissions
        or not isinstance(policy_snapshot_id, str)
        or not policy_snapshot_id.strip()
    ):
        raise validation_error("invalid_capability_authorization_input")
    metadata = {
        "purpose": purpose.value,
        "policy_snapshot_id": policy_snapshot_id,
        "catalog_snapshot_id": catalog.snapshot_id,
        "catalog_digest": str(catalog.catalog_digest),
        "definition_digest": str(definition.definition_digest),
    }
    request = AuthorizationRequest(
        schema_version=1,
        request_digest=canonical_digest({}, domain="pending:v1"),
        actor=actor,
        conversation_scope=scope,
        action=ActionId(permission),
        resource=capability_authorization_resource(definition, scope),
        capability_id=definition.capability_id,
        risk_level=definition.risk_level,
        metadata=metadata,
    )
    return replace(request, request_digest=authorization_request_digest(request))


def capability_authorization_allows(
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
    ):
        return False
    if decision.effect is not AuthorizationEffect.ALLOW:
        return False
    try:
        verified = verifier.verify(decision, at=at)
    except Exception:  # noqa: BLE001 - verifier failures deny without disclosure.
        return False
    return bool(verified) and (
        decision.request_digest == request.request_digest
        and decision.actor_digest == actor_digest(request.actor)
        and decision.scope_digest == scope_digest(request.conversation_scope)
        and decision.action == request.action
        and decision.resource_digest == resource_digest(request.resource)
        and decision.capability_id == request.capability_id
        and decision.risk_level is request.risk_level
        and decision.metadata_digest == authorization_metadata_digest(request.metadata)
        and decision.policy_revision == expected_policy_revision
        and decision.decided_at <= at < decision.expires_at
    )


__all__ = [
    "CapabilityAuthorizationPurpose",
    "build_capability_authorization_request",
    "capability_authorization_allows",
    "capability_authorization_resource",
]
