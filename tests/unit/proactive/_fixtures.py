from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import Actor, ActorRef, ConversationScope
from dududa.domain.primitives import (
    ConversationType,
    RuntimeBudget,
    TraceContext,
)
from dududa.ports.context import (
    NeverCancelled,
    PortCallContext,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.proactive.contracts import (
    InitiatedRunRequest,
    ProactiveAuthorizationGrant,
    ProactiveGrantKind,
    ProactivePreviewRequest,
    ProactiveRunMode,
    ProactiveSubscription,
    ProactiveTargetPolicy,
    ProactiveTargetPolicyStatus,
    ProactiveTrigger,
    ProactiveTriggerKind,
    ScheduleOccurrence,
    ScheduleOccurrenceOrigin,
    ScheduleSpec,
    SourceCategory,
    SubscriptionStatus,
)
from dududa.responses.contracts import AnswerProfile
from dududa.security.digests import actor_digest, scope_digest


def budget() -> RuntimeBudget:
    return RuntimeBudget(0, 0, 0, 0, 0, Decimal(0))


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


class ProactiveFixture:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
        self.clock = MutableClock(self.now)
        self.scope = ConversationScope(
            "qq",
            "bot-1",
            ConversationType.GROUP,
            "group-1",
            "group-1",
            "dududa",
        )
        self.actor = Actor(
            "qq",
            "bot-1",
            "operator-1",
            frozenset({"operator"}),
        )
        self.actor_ref = ActorRef("qq", "bot-1", "operator-ref")
        self.authorization_decision_digest = canonical_digest(
            {"decision": "allow"},
            domain="test:proactive-authorization-decision:v1",
        )
        self.operator_grant = self.grant(
            "grant-operator",
            ProactiveGrantKind.OPERATOR_ENABLE_TARGET,
        )
        self.group_grant = self.grant(
            "grant-group",
            ProactiveGrantKind.GROUP_POLICY_ENABLE,
        )
        self.owner_grant = self.grant(
            "grant-owner",
            ProactiveGrantKind.SUBSCRIPTION_OWNER,
        )
        self.policy = ProactiveTargetPolicy(
            schema_version=1,
            target_policy_id="target-policy-1",
            revision=1,
            status=ProactiveTargetPolicyStatus.ACTIVE,
            target_scope=self.scope,
            operator_authorization_grant_ref=self.operator_grant.as_ref(),
            group_policy_grant_ref=self.group_grant.as_ref(),
            allowed_trigger_kinds=frozenset(ProactiveTriggerKind),
            policy_revision="proactive-policy-v1",
            activated_at=self.now,
            expires_at=self.now + timedelta(days=30),
        )
        self.schedule = ScheduleSpec(
            1,
            "Asia/Shanghai",
            time(8, 0),
            frozenset(range(7)),
            (),
            timedelta(minutes=30),
            "schedule-v1",
        )
        self.subscription = ProactiveSubscription(
            schema_version=1,
            subscription_id="subscription-1",
            revision=1,
            status=SubscriptionStatus.ACTIVE,
            owner_ref=self.actor_ref,
            authorization_grant_ref=self.owner_grant.as_ref(),
            target_scope=self.scope,
            target_policy_ref=self.policy.as_ref(),
            categories=frozenset(SourceCategory),
            source_policy_id="source-policy-v1",
            schedule=self.schedule,
            answer_profile=AnswerProfile.MEDIUM,
            maximum_items=10,
            maximum_age=timedelta(days=1),
            created_at=self.now,
            updated_at=self.now,
        )
        self.occurrence = ScheduleOccurrence(
            1,
            "occurrence-1",
            self.subscription.subscription_id,
            self.subscription.revision,
            ScheduleOccurrenceOrigin.SCHEDULED,
            date(2026, 1, 5),
            self.now + timedelta(hours=1),
            self.now + timedelta(hours=2),
        )
        self.trigger = ProactiveTrigger(
            1,
            "trigger-1",
            ProactiveTriggerKind.SCHEDULED_DIGEST,
            self.scope,
            self.occurrence,
            None,
            self.policy.as_ref(),
            self.now,
            self.now + timedelta(hours=2),
        )
        self.run = InitiatedRunRequest(
            1,
            "run-1",
            self.trigger,
            self.policy.as_ref(),
            ProactiveRunMode.SHADOW,
            "config-v1",
            "source-policy-v1",
            "response-policy-v1",
        )
        self.preview = ProactivePreviewRequest(
            1,
            "preview-1",
            ProactiveRunMode.PREVIEW,
            self.actor,
            "proactive.subscription.preview",
            self.subscription.subscription_id,
            self.subscription.revision,
            self.scope,
            self.policy.as_ref(),
            "config-v1",
            "source-policy-v1",
            "response-policy-v1",
        )

    def grant(
        self,
        grant_id: str,
        kind: ProactiveGrantKind,
    ) -> ProactiveAuthorizationGrant:
        return ProactiveAuthorizationGrant(
            schema_version=1,
            grant_id=grant_id,
            revision=1,
            grant_kind=kind,
            issuer_ref=self.actor_ref,
            issuer_actor_digest=actor_digest(self.actor),
            target_scope_digest=scope_digest(self.scope),
            action="message.send.proactive",
            allowed_trigger_kinds=frozenset(ProactiveTriggerKind),
            allowed_categories=frozenset(SourceCategory),
            authorization_decision_digest=self.authorization_decision_digest,
            policy_revision="proactive-policy-v1",
            issued_at=self.now,
            expires_at=self.now + timedelta(days=30),
            revoked_at=None,
        )

    def service_call(self, operation_id: str = "proactive-test") -> ServiceCallContext:
        return ServiceCallContext(
            operation_id,
            ServicePrincipal("dududa-test", "worker-1", frozenset({"test"})),
            "contract_test",
            TraceContext("trace-proactive"),
            self.clock.value + timedelta(minutes=1),
            NeverCancelled(),
            budget(),
            "policy-snapshot-v1",
        )

    def port_call(self, run_id: str = "proactive-test") -> PortCallContext:
        return PortCallContext(
            run_id,
            TraceContext("trace-proactive"),
            self.clock.value + timedelta(minutes=1),
            NeverCancelled(),
            budget(),
            "policy-snapshot-v1",
        )
