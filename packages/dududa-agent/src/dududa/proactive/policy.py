from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import Actor
from dududa.domain.primitives import ActionId, Sensitivity
from dududa.errors import DududaError, validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.security.digests import (
    actor_digest,
    audit_event_digest,
    authorization_decision_digest,
    resource_digest,
    scope_digest,
)
from dududa.security.models import AuditEvent, AuthorizationDecision
from dududa.security.ports import (
    AuditSink,
    AuthorizationDecisionVerifier,
    AuthorizationPolicy,
)

from .authorization import (
    PROACTIVE_SEND_ACTION,
    build_proactive_send_authorization_request,
    proactive_authorization_allows,
)
from .config import ProactiveControlConfig
from .contracts import (
    InitiatedRunRequest,
    ProactiveDisposition,
    ProactiveGrantKind,
    ProactivePolicyDecision,
    ProactiveQuotaLease,
    ProactiveRunMode,
    ProactiveSubscription,
    ProactiveTargetPolicyStatus,
    ProactiveTriggerKind,
    SourceCategory,
    SubscriptionStatus,
    validate_grant_ref,
)

if TYPE_CHECKING:
    from dududa.ports.proactive import (
        ProactiveActorResolver,
        ProactiveQuotaLedger,
        ProactiveTargetRegistry,
    )


@dataclass(frozen=True, slots=True)
class ProactivePolicyEvaluation:
    decision: ProactivePolicyDecision
    quota_leases: tuple[ProactiveQuotaLease, ProactiveQuotaLease] | None


class DeterministicProactivePolicy:
    """Pre-dispatch revalidation; it never calls sources, models or Output."""

    def __init__(
        self,
        config: ProactiveControlConfig,
        *,
        target_registry: ProactiveTargetRegistry,
        authorization_policy: AuthorizationPolicy,
        authorization_verifier: AuthorizationDecisionVerifier,
        authorization_policy_revision: str,
        quota_ledger: ProactiveQuotaLedger,
        audit_sink: AuditSink,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, ProactiveControlConfig):
            raise validation_error("invalid_proactive_policy_config")
        self._config = config
        self._target_registry = target_registry
        self._authorization_policy = authorization_policy
        self._authorization_verifier = authorization_verifier
        if (
            not isinstance(authorization_policy_revision, str)
            or not authorization_policy_revision.strip()
        ):
            raise validation_error("invalid_proactive_authorization_revision")
        self._authorization_policy_revision = authorization_policy_revision
        self._quota = quota_ledger
        self._audit = audit_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def authorize_delivery(
        self,
        request: InitiatedRunRequest,
        actor: Actor,
        *,
        subscription: ProactiveSubscription | None,
        call: ServiceCallContext,
    ) -> ProactivePolicyEvaluation:
        if not isinstance(request, InitiatedRunRequest) or not isinstance(actor, Actor):
            raise validation_error("invalid_proactive_policy_input")
        now = self._now()
        _validate_call(call, now)
        control = self._config.for_trigger(request.trigger.kind)
        denial = self._static_denial(request, control, now)
        if denial is not None:
            return self._evaluation(request, denial, now, subscription=subscription)
        categories: frozenset[SourceCategory]
        if request.trigger.kind is ProactiveTriggerKind.SCHEDULED_DIGEST:
            if not _subscription_matches(request, subscription):
                return self._evaluation(
                    request,
                    "subscription_binding_invalid",
                    now,
                    subscription=subscription,
                )
            assert subscription is not None
            categories = subscription.categories
            if _inside_quiet_hours(
                now, subscription.schedule.timezone, subscription.schedule.quiet_hours
            ):
                return self._evaluation(
                    request,
                    "subscription_quiet_hours",
                    now,
                    subscription=subscription,
                )
        else:
            if subscription is not None:
                return self._evaluation(
                    request,
                    "probe_forbids_subscription",
                    now,
                    subscription=None,
                )
            categories = frozenset()
        if _inside_quiet_hours(now, control.timezone, control.quiet_hours):
            return self._evaluation(
                request,
                "control_quiet_hours",
                now,
                subscription=subscription,
            )
        try:
            target = await self._target_registry.validate_target(
                request.target_policy_ref,
                trigger_kind=request.trigger.kind,
                categories=categories,
                at=now,
                call=call,
            )
            if target.status is not ProactiveTargetPolicyStatus.ACTIVE:
                raise validation_error("proactive_target_policy_inactive")
            if subscription is not None:
                owner_grant = await self._target_registry.resolve_grant(
                    subscription.authorization_grant_ref,
                    at=now,
                    call=call,
                )
                validate_grant_ref(
                    owner_grant,
                    subscription.authorization_grant_ref,
                    expected_kind=ProactiveGrantKind.SUBSCRIPTION_OWNER,
                )
                if (
                    owner_grant.target_scope_digest
                    != scope_digest(subscription.target_scope)
                    or owner_grant.policy_revision != target.policy_revision
                    or not categories.issubset(owner_grant.allowed_categories)
                    or actor_digest(actor) != owner_grant.issuer_actor_digest
                ):
                    raise validation_error("subscription_owner_grant_binding_mismatch")
            else:
                operator_grant = await self._target_registry.resolve_grant(
                    target.operator_authorization_grant_ref,
                    at=now,
                    call=call,
                )
                if actor_digest(actor) != operator_grant.issuer_actor_digest:
                    raise validation_error("proactive_operator_actor_mismatch")
        except DududaError:
            return self._evaluation(
                request,
                "target_or_grant_invalid",
                now,
                subscription=subscription,
            )
        authorization_request = build_proactive_send_authorization_request(
            actor,
            request.trigger.target_scope,
            request.trigger,
            target_policy_ref=request.target_policy_ref,
            policy_snapshot_id=call.policy_snapshot_id,
        )
        port_call = _port_call(call, request.run_id)
        try:
            authorization = await self._authorization_policy.decide(
                authorization_request,
                call=port_call,
            )
        except Exception:  # noqa: BLE001 - authorization outage denies delivery.
            return self._evaluation(
                request,
                "authorization_unavailable",
                now,
                subscription=subscription,
            )
        if not proactive_authorization_allows(
            authorization_request,
            authorization,
            self._authorization_verifier,
            at=now,
            expected_policy_revision=self._authorization_policy_revision,
        ):
            return self._evaluation(
                request,
                "authorization_denied",
                now,
                subscription=subscription,
                authorization=authorization,
            )
        try:
            leases = await self._quota.reserve(
                request.start_digest,
                request.trigger.target_scope,
                global_limit=control.maximum_global_messages,
                scope_limit=control.maximum_scope_messages,
                window=control.quota_window,
                policy_revision=control.revision,
                call=call,
            )
        except Exception:  # noqa: BLE001 - limiter outage denies delivery.
            return self._evaluation(
                request,
                "quota_unavailable",
                now,
                subscription=subscription,
                authorization=authorization,
            )
        if not all(lease.allowed and lease.expires_at > now for lease in leases):
            return self._evaluation(
                request,
                "quota_exhausted",
                now,
                subscription=subscription,
                authorization=authorization,
            )
        evaluation = self._evaluation(
            request,
            "delivery_authorized",
            now,
            subscription=subscription,
            authorization=authorization,
            leases=leases,
            allowed=True,
        )
        try:
            await self._write_audit(
                request,
                actor,
                authorization,
                evaluation.decision,
                call=call,
            )
        except Exception:  # noqa: BLE001 - audit failure releases and denies.
            await self._quota.release(leases, call=call)
            return self._evaluation(
                request,
                "audit_unavailable",
                now,
                subscription=subscription,
                authorization=authorization,
            )
        return evaluation

    def dependency_denial(
        self,
        request: InitiatedRunRequest,
        reason: str,
        *,
        subscription: ProactiveSubscription | None,
    ) -> ProactivePolicyEvaluation:
        if not isinstance(request, InitiatedRunRequest):
            raise validation_error("invalid_proactive_policy_input")
        if not isinstance(reason, str) or not reason.strip():
            raise validation_error("invalid_proactive_denial_reason")
        return self._evaluation(
            request,
            reason,
            self._now(),
            subscription=subscription,
        )

    def _static_denial(self, request, control, now: datetime) -> str | None:
        if request.trigger.expires_at <= now:
            return "trigger_expired"
        if request.mode is not control.mode:
            return "control_mode_mismatch"
        if request.mode is not ProactiveRunMode.CANARY:
            return "mode_has_no_delivery"
        if not control.delivery_enabled:
            return "delivery_disabled"
        if control.kill_switch:
            return "kill_switch_active"
        if not control.allowlisted_scope_digests:
            return "empty_scope_allowlist"
        if (
            scope_digest(request.trigger.target_scope)
            not in control.allowlisted_scope_digests
        ):
            return "scope_not_allowlisted"
        return None

    def _evaluation(
        self,
        request: InitiatedRunRequest,
        reason: str,
        now: datetime,
        *,
        subscription: ProactiveSubscription | None,
        authorization: AuthorizationDecision | None = None,
        leases: tuple[ProactiveQuotaLease, ProactiveQuotaLease] | None = None,
        allowed: bool = False,
    ) -> ProactivePolicyEvaluation:
        authorization_digest = (
            authorization_decision_digest(authorization)
            if authorization is not None
            else canonical_digest(
                {
                    "start_digest": request.start_digest,
                    "reason": reason,
                },
                domain="proactive:authorization-denial-evidence:v1",
            )
        )
        lease_id = (
            str(
                canonical_digest(
                    tuple(value.lease_digest for value in leases),
                    domain="proactive:quota-lease-pair:v1",
                )
            )
            if leases is not None
            else None
        )
        profile = (
            subscription.answer_profile
            if subscription is not None
            else _probe_profile()
        )
        maximum_items = subscription.maximum_items if subscription is not None else 0
        decision = ProactivePolicyDecision(
            1,
            f"proactive-decision:{self._new_id()}",
            request.trigger.trigger_digest,
            request.target_policy_ref,
            allowed,
            scope_digest(request.trigger.target_scope),
            profile,
            maximum_items if allowed else 0,
            authorization_digest,
            lease_id,
            (reason,),
            self._config.policy_revision,
            now,
            min(request.trigger.expires_at, now + timedelta(minutes=1)),
        )
        return ProactivePolicyEvaluation(decision, leases if allowed else None)

    async def _write_audit(
        self,
        request: InitiatedRunRequest,
        actor: Actor,
        authorization: AuthorizationDecision,
        decision: ProactivePolicyDecision,
        *,
        call: ServiceCallContext,
    ) -> None:
        authorization_request = build_proactive_send_authorization_request(
            actor,
            request.trigger.target_scope,
            request.trigger,
            target_policy_ref=request.target_policy_ref,
            policy_snapshot_id=call.policy_snapshot_id,
        )
        event = AuditEvent(
            1,
            f"proactive-audit:{self._new_id()}",
            canonical_digest({}, domain="pending:v1"),
            decision.decided_at,
            request.run_id,
            call.operation_id,
            call.trace.trace_id,
            call.trace.parent_span_id,
            actor_digest(actor),
            scope_digest(request.trigger.target_scope),
            ActionId(str(PROACTIVE_SEND_ACTION)),
            "allow",
            authorization.decision_id,
            authorization_request.request_digest,
            (self._config.policy_revision, self._authorization_policy_revision),
            (),
            decision.reason_codes,
            resource_digest(authorization_request.resource),
            {
                "trigger_kind": request.trigger.kind.value,
                "mode": request.mode.value,
                "policy_revision": self._config.policy_revision,
            },
            Sensitivity.PUBLIC,
            ProactiveDisposition.PREPARED.value,
        )
        event = replace(event, event_digest=audit_event_digest(event))
        receipt = await self._audit.write(event, call=call)
        if not receipt.persisted or receipt.event_digest != event.event_digest:
            raise validation_error("proactive_audit_receipt_invalid")

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_proactive_policy_clock")
        return value

    def _new_id(self) -> str:
        value = self._id_factory()
        if not isinstance(value, str) or not value.strip():
            raise validation_error("invalid_proactive_policy_id")
        return value


class ProactiveInitiationGuard:
    """Resolves the current authorized Actor before deterministic policy checks."""

    def __init__(
        self,
        policy: DeterministicProactivePolicy,
        *,
        target_registry: ProactiveTargetRegistry,
        actor_resolver: ProactiveActorResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(policy, DeterministicProactivePolicy):
            raise validation_error("invalid_proactive_policy")
        self._policy = policy
        self._target_registry = target_registry
        self._actor_resolver = actor_resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def authorize_delivery(
        self,
        request: InitiatedRunRequest,
        *,
        subscription: ProactiveSubscription | None,
        call: ServiceCallContext,
    ) -> ProactivePolicyEvaluation:
        if not isinstance(request, InitiatedRunRequest):
            raise validation_error("invalid_proactive_policy_input")
        now = self._now()
        _validate_call(call, now)
        if request.trigger.kind is ProactiveTriggerKind.SCHEDULED_DIGEST:
            if not isinstance(subscription, ProactiveSubscription):
                raise validation_error("scheduled_run_requires_subscription")
            actor_ref = subscription.owner_ref
        else:
            try:
                target = await self._target_registry.resolve_target(
                    request.target_policy_ref,
                    at=now,
                    call=call,
                )
                operator = await self._target_registry.resolve_grant(
                    target.operator_authorization_grant_ref,
                    at=now,
                    call=call,
                )
                actor_ref = operator.issuer_ref
            except Exception:  # noqa: BLE001 - dependency failure denies initiation.
                return self._policy.dependency_denial(
                    request,
                    "target_or_grant_invalid",
                    subscription=subscription,
                )
        try:
            actor = await self._actor_resolver.resolve(
                actor_ref,
                request.trigger.target_scope,
                call=call,
            )
            if not isinstance(actor, Actor):
                raise validation_error("invalid_proactive_actor_resolution")
        except Exception:  # noqa: BLE001 - resolver failure denies initiation.
            return self._policy.dependency_denial(
                request,
                "actor_resolution_unavailable",
                subscription=subscription,
            )
        return await self._policy.authorize_delivery(
            request,
            actor,
            subscription=subscription,
            call=call,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_proactive_initiation_clock")
        return value


def _subscription_matches(
    request: InitiatedRunRequest,
    subscription: ProactiveSubscription | None,
) -> bool:
    occurrence = request.trigger.occurrence
    return bool(
        occurrence is not None
        and isinstance(subscription, ProactiveSubscription)
        and subscription.status is SubscriptionStatus.ACTIVE
        and subscription.subscription_id == occurrence.subscription_id
        and subscription.revision == occurrence.subscription_revision
        and subscription.target_scope == request.trigger.target_scope
        and subscription.target_policy_ref == request.target_policy_ref
    )


def _inside_quiet_hours(now, timezone_name: str, windows) -> bool:
    local = now.astimezone(ZoneInfo(timezone_name)).timetz().replace(tzinfo=None)
    return any(window.contains(local) for window in windows)


def _port_call(call: ServiceCallContext, run_id: str) -> PortCallContext:
    return PortCallContext(
        run_id,
        call.trace,
        call.deadline,
        call.cancellation,
        call.budget,
        call.policy_snapshot_id,
    )


def _validate_call(call: ServiceCallContext, now: datetime) -> None:
    if not isinstance(call, ServiceCallContext):
        raise validation_error("invalid_proactive_service_call")
    if call.cancellation.is_cancelled or call.deadline <= now:
        raise validation_error("proactive_call_cancelled_or_expired")


def _probe_profile():
    from dududa.responses.contracts import AnswerProfile

    return AnswerProfile.SHORT


__all__ = [
    "DeterministicProactivePolicy",
    "ProactiveInitiationGuard",
    "ProactivePolicyEvaluation",
]
