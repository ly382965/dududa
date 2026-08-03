from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    ConversationType,
    DenyFlag,
    DigestString,
    ResourceRef,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.confirmation import InMemoryConfirmationService
from dududa.security.digests import (
    authorization_request_digest,
    confirmation_consume_request_digest,
    confirmation_request_digest,
    scope_digest,
)
from dududa.security.models import (
    AuthorizationDecision,
    AuthorizationEffect,
    AuthorizationRequest,
    ConfirmationConsumeRequest,
    ConfirmationRequest,
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class SecurityFixture(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.clock = MutableClock(self.now)
        self.scope = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "g-1", "g-1", "dududa"
        )
        self.actor = Actor(
            "qq", "bot-1", "u-1", frozenset({RoleId("admin")}), frozenset()
        )
        self.call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            self.now + timedelta(hours=1),
            NeverCancelled(),
            RuntimeBudget(1, 1, 1, 100, 100, Decimal("1")),
            "policy-1",
        )

    def authorization_request(
        self,
        *,
        actor: Actor | None = None,
        action: str = "config.read",
        risk: RiskLevel = RiskLevel.LOW,
        metadata: dict[str, object] | None = None,
    ) -> AuthorizationRequest:
        from dududa.security.digests import scope_digest as digest_scope

        request = AuthorizationRequest(
            1,
            DigestString("pending"),
            actor or self.actor,
            self.scope,
            ActionId(action),
            ResourceRef("config", "core", digest_scope(self.scope)),
            None,
            risk,
            metadata or {},
        )
        return replace(request, request_digest=authorization_request_digest(request))

    @staticmethod
    def config_constraint() -> AuthorizationConstraint:
        return AuthorizationConstraint(
            frozenset({"config"}),
            frozenset({"core"}),
            maximum_risk=RiskLevel.CRITICAL,
        )


class AuthorizationTests(SecurityFixture):
    async def test_default_deny_role_matrix_and_confirmation(self) -> None:
        policy = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                "policy-v1",
                {"admin": frozenset({"config.read", "config.write"})},
                {
                    "admin": {
                        "config.read": self.config_constraint(),
                        "config.write": self.config_constraint(),
                    }
                },
            ),
            clock=self.clock,
            id_factory=lambda: "decision-1",
        )
        allowed = await policy.decide(self.authorization_request(), call=self.call)
        self.assertEqual(allowed.effect, AuthorizationEffect.ALLOW)

        unknown = await policy.decide(
            self.authorization_request(action="unknown.action"), call=self.call
        )
        self.assertEqual(unknown.effect, AuthorizationEffect.DENY)

        high_risk = await policy.decide(
            self.authorization_request(action="config.write", risk=RiskLevel.HIGH),
            call=self.call,
        )
        self.assertEqual(high_risk.effect, AuthorizationEffect.REQUIRE_CONFIRMATION)

        muted = replace(self.actor, deny_flags=frozenset({DenyFlag("muted")}))
        denied = await policy.decide(
            self.authorization_request(actor=muted), call=self.call
        )
        self.assertEqual(denied.effect, AuthorizationEffect.DENY)

    async def test_tampered_request_digest_is_rejected(self) -> None:
        policy = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                "policy-v1",
                {"admin": frozenset({"config.read"})},
                {"admin": {"config.read": self.config_constraint()}},
            ),
            clock=self.clock,
        )
        request = self.authorization_request(metadata={"purpose": "read"})
        tampered = replace(request, metadata={"purpose": "write"})
        with self.assertRaises(DududaError):
            await policy.decide(tampered, call=self.call)

    async def test_resource_and_capability_constraints_fail_closed(self) -> None:
        policy = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                "policy-v1",
                {"admin": frozenset({"config.read"})},
                {"admin": {"config.read": self.config_constraint()}},
            ),
            clock=self.clock,
        )
        original = self.authorization_request()
        requests = (
            replace(
                original,
                resource=ResourceRef("config", "other", scope_digest(self.scope)),
            ),
            replace(original, capability_id="unlisted-capability"),
        )
        for request in requests:
            request = replace(
                request,
                request_digest=authorization_request_digest(request),
            )
            decision = await policy.decide(request, call=self.call)
            self.assertEqual(decision.effect, AuthorizationEffect.DENY)

    async def test_permission_cannot_borrow_constraint_from_another_role(self) -> None:
        other_constraint = AuthorizationConstraint(
            frozenset({"config"}),
            frozenset({"other"}),
        )
        policy = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                "policy-v1",
                {
                    "reader": frozenset({"config.read"}),
                    "unrelated": frozenset({"other.action"}),
                },
                {
                    "reader": {"config.read": other_constraint},
                    "unrelated": {"config.read": self.config_constraint()},
                },
            ),
            clock=self.clock,
        )
        actor = replace(
            self.actor,
            roles=frozenset({RoleId("reader"), RoleId("unrelated")}),
        )
        decision = await policy.decide(
            self.authorization_request(actor=actor),
            call=self.call,
        )
        self.assertEqual(decision.effect, AuthorizationEffect.DENY)


class ConfirmationTests(SecurityFixture):
    def authorization_policy(self) -> RoleAuthorizationPolicy:
        return RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                "policy-v1",
                {"admin": frozenset({"config.write"})},
                {"admin": {"config.write": self.config_constraint()}},
                confirmation_risks=frozenset(),
            ),
            clock=self.clock,
            id_factory=lambda: "decision-1",
        )

    async def allow_decision(
        self,
        policy: RoleAuthorizationPolicy,
        action: str,
    ) -> AuthorizationDecision:
        return await policy.decide(
            self.authorization_request(action=action),
            call=self.call,
        )

    def issue_request(self, payload: str = "payload-a") -> ConfirmationRequest:
        request = ConfirmationRequest(
            1,
            DigestString("pending"),
            self.actor,
            self.scope,
            ActionId("config.write"),
            DigestString(payload),
            "config.write",
            timedelta(minutes=5),
        )
        return replace(request, request_digest=confirmation_request_digest(request))

    async def test_confirmation_binds_every_field_and_is_single_use(self) -> None:
        policy = self.authorization_policy()
        service = InMemoryConfirmationService(
            policy_revision="policy-v1",
            authorization_verifier=policy,
            clock=self.clock,
            id_factory=lambda: "confirm-1",
        )
        requirement = await service.issue(self.issue_request(), call=self.call)
        consume = ConfirmationConsumeRequest(
            1,
            DigestString("pending"),
            requirement.confirmation_id,
            self.actor,
            self.scope,
            requirement.action,
            requirement.payload_digest,
            requirement.required_permission,
            "execution-1",
            "idempotency-1",
            await self.allow_decision(policy, "config.write"),
        )
        consume = replace(
            consume,
            request_digest=confirmation_consume_request_digest(consume),
        )
        grant = await service.consume(consume, call=self.call)
        self.assertEqual(grant.execution_id, "execution-1")
        with self.assertRaises(DududaError):
            await service.consume(consume, call=self.call)

    async def test_mismatched_payload_and_expiry_fail_closed(self) -> None:
        policy = self.authorization_policy()
        service = InMemoryConfirmationService(
            policy_revision="policy-v1",
            authorization_verifier=policy,
            clock=self.clock,
            id_factory=lambda: "confirm-2",
        )
        requirement = await service.issue(self.issue_request(), call=self.call)
        self.clock.value += timedelta(minutes=6)
        consume = ConfirmationConsumeRequest(
            1,
            DigestString("pending"),
            requirement.confirmation_id,
            self.actor,
            self.scope,
            requirement.action,
            DigestString("payload-b"),
            requirement.required_permission,
            "execution-2",
            "idempotency-2",
            await self.allow_decision(policy, "config.write"),
        )
        consume = replace(
            consume, request_digest=confirmation_consume_request_digest(consume)
        )
        with self.assertRaises(DududaError):
            await service.consume(consume, call=self.call)

    async def test_unissued_or_old_policy_authorization_is_rejected(self) -> None:
        policy = self.authorization_policy()
        service = InMemoryConfirmationService(
            policy_revision="policy-v1",
            authorization_verifier=policy,
            clock=self.clock,
            id_factory=lambda: "confirm-3",
        )
        requirement = await service.issue(self.issue_request(), call=self.call)
        legitimate = await self.allow_decision(policy, "config.write")
        forged = replace(legitimate, policy_revision="revoked-old-policy")
        consume = ConfirmationConsumeRequest(
            1,
            DigestString("pending"),
            requirement.confirmation_id,
            self.actor,
            self.scope,
            requirement.action,
            requirement.payload_digest,
            requirement.required_permission,
            "execution-3",
            "idempotency-3",
            forged,
        )
        consume = replace(
            consume,
            request_digest=confirmation_consume_request_digest(consume),
        )
        with self.assertRaises(DududaError):
            await service.consume(consume, call=self.call)


if __name__ == "__main__":
    unittest.main()
