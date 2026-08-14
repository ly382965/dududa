from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    ConversationType,
    DigestString,
    ResourceRef,
    RiskLevel,
)
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.security.digests import authorization_request_digest, scope_digest
from dududa.security.models import (
    AuthorizationDecision,
    AuthorizationEffect,
    AuthorizationRequest,
)
from dududa.security.ports import AuthorizationDecisionVerifier, AuthorizationPolicy

from .contracts import GroupControlScope

CONTROL_PLANE_PERSONA_ID = "control-plane"


class ControlPlaneAuthorizer:
    def __init__(
        self,
        policy: AuthorizationPolicy,
        verifier: AuthorizationDecisionVerifier,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy = policy
        self._verifier = verifier
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def authorize_group(
        self,
        actor: Actor,
        scope: GroupControlScope,
        action: ActionId,
        *,
        risk_level: RiskLevel,
        call: ServiceCallContext,
    ) -> AuthorizationDecision:
        if actor.platform != scope.platform or actor.bot_id != scope.bot_id:
            raise _denied("control_plane_actor_scope_mismatch")
        conversation_scope = group_conversation_scope(scope)
        return await self._authorize(
            actor,
            conversation_scope,
            action,
            ResourceRef(
                "group-service-scope",
                scope.group_id,
                scope_digest(conversation_scope),
            ),
            risk_level=risk_level,
            call=call,
        )

    async def authorize_bot(
        self,
        actor: Actor,
        platform: str,
        bot_id: str,
        action: ActionId,
        *,
        risk_level: RiskLevel,
        call: ServiceCallContext,
    ) -> AuthorizationDecision:
        if actor.platform != platform or actor.bot_id != bot_id:
            raise _denied("control_plane_actor_scope_mismatch")
        conversation_scope = bot_conversation_scope(platform, bot_id)
        return await self._authorize(
            actor,
            conversation_scope,
            action,
            ResourceRef(
                "bot-control-scope",
                bot_id,
                scope_digest(conversation_scope),
            ),
            risk_level=risk_level,
            call=call,
        )

    async def _authorize(
        self,
        actor: Actor,
        conversation_scope: ConversationScope,
        action: ActionId,
        resource: ResourceRef,
        *,
        risk_level: RiskLevel,
        call: ServiceCallContext,
    ) -> AuthorizationDecision:
        candidate = AuthorizationRequest(
            1,
            DigestString("pending"),
            actor,
            conversation_scope,
            action,
            resource,
            None,
            risk_level,
            {},
        )
        request = replace(
            candidate,
            request_digest=authorization_request_digest(candidate),
        )
        decision = await self._policy.decide(request, call=_port_call(call))
        now = self._clock()
        if not self._verifier.verify(decision, at=now):
            raise _denied("control_plane_authorization_unverifiable")
        if decision.effect is not AuthorizationEffect.ALLOW:
            raise _denied(*decision.reason_codes)
        if (
            decision.request_digest != request.request_digest
            or decision.scope_digest != scope_digest(conversation_scope)
            or decision.action != action
        ):
            raise _denied("control_plane_authorization_binding_mismatch")
        return decision


def group_conversation_scope(scope: GroupControlScope) -> ConversationScope:
    return ConversationScope(
        scope.platform,
        scope.bot_id,
        ConversationType.GROUP,
        scope.group_id,
        scope.group_id,
        CONTROL_PLANE_PERSONA_ID,
    )


def bot_conversation_scope(platform: str, bot_id: str) -> ConversationScope:
    return ConversationScope(
        platform,
        bot_id,
        ConversationType.CHANNEL,
        f"control-plane:bot:{bot_id}",
        None,
        CONTROL_PLANE_PERSONA_ID,
    )


def _port_call(call: ServiceCallContext) -> PortCallContext:
    return PortCallContext(
        call.operation_id,
        call.trace,
        call.deadline,
        call.cancellation,
        call.budget,
        call.policy_snapshot_id,
    )


def _denied(*reason_codes: str):
    return error(
        "control_plane_authorization_denied",
        ErrorCategory.AUTHORIZATION,
        "control_plane.denied",
        *reason_codes,
    )


__all__ = [
    "CONTROL_PLANE_PERSONA_ID",
    "ControlPlaneAuthorizer",
    "bot_conversation_scope",
    "group_conversation_scope",
]
