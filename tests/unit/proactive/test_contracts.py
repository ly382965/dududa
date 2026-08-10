from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import time, timedelta

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import ConversationScope
from dududa.domain.primitives import ConversationType
from dududa.errors import DududaError
from dududa.proactive.authorization import (
    PROACTIVE_PREVIEW_ACTION,
    PROACTIVE_SEND_ACTION,
    build_proactive_preview_authorization_request,
    build_proactive_send_authorization_request,
    proactive_authorization_allows,
)
from dududa.proactive.config import (
    default_proactive_control_config,
    parse_proactive_control_config,
)
from dududa.proactive.contracts import (
    InitiatedRunRequest,
    LocalTimeWindow,
    ProactiveGrantKind,
    ProactiveRunMode,
    ProactiveTargetPolicyRef,
    ProactiveTrigger,
    ProactiveTriggerKind,
    SourceCategory,
)
from dududa.proactive.digests import (
    initiated_run_request_digest,
    proactive_authorization_grant_digest,
    proactive_delivery_idempotency_key,
    proactive_target_policy_digest,
)
from dududa.proactive.registry import InMemoryProactiveTargetRegistry
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)

from ._fixtures import ProactiveFixture


class ProactiveContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProactiveFixture()

    def test_contracts_self_seal_and_named_digests_match(self) -> None:
        fixture = self.fixture
        self.assertEqual(
            fixture.operator_grant.grant_digest,
            proactive_authorization_grant_digest(fixture.operator_grant),
        )
        self.assertEqual(
            fixture.policy.target_policy_digest,
            proactive_target_policy_digest(fixture.policy),
        )
        self.assertEqual(
            fixture.run.start_digest,
            initiated_run_request_digest(fixture.run),
        )
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            replace(fixture.operator_grant, policy_revision="proactive-policy-v2")
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            replace(
                fixture.policy,
                allowed_trigger_kinds=frozenset(
                    {ProactiveTriggerKind.CONVERSATION_PROBE}
                ),
            )

    def test_trigger_one_of_and_run_preview_separation(self) -> None:
        fixture = self.fixture
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            ProactiveTrigger(
                1,
                "trigger-invalid",
                ProactiveTriggerKind.SCHEDULED_DIGEST,
                fixture.scope,
                None,
                None,
                fixture.policy.as_ref(),
                fixture.now,
                fixture.now + timedelta(hours=2),
            )
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            InitiatedRunRequest(
                1,
                "run-preview",
                fixture.trigger,
                fixture.policy.as_ref(),
                ProactiveRunMode.PREVIEW,
                "config-v1",
                "source-policy-v1",
                "response-policy-v1",
            )

    def test_target_scope_and_reference_are_exact(self) -> None:
        fixture = self.fixture
        other_scope = ConversationScope(
            "qq",
            "bot-1",
            ConversationType.GROUP,
            "group-2",
            "group-2",
            "dududa",
        )
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            replace(fixture.trigger, target_scope=other_scope, trigger_digest="")
        forged_ref = replace(
            fixture.policy.as_ref(),
            revision=2,
        )
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            replace(fixture.run, target_policy_ref=forged_ref, start_digest="")

    def test_quiet_window_supports_overnight_without_timezone(self) -> None:
        window = LocalTimeWindow.from_strings("22:00", "06:00")
        self.assertTrue(window.contains(time(23, 0)))
        self.assertTrue(window.contains(time(5, 59)))
        self.assertFalse(window.contains(time(12, 0)))
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            LocalTimeWindow.from_strings("08:00", "08:00")

    def test_business_idempotency_changes_only_with_business_fields(self) -> None:
        fixture = self.fixture
        response_digest = canonical_digest(
            {"response": 1},
            domain="test:validated-response:v1",
        )
        first = proactive_delivery_idempotency_key(
            trigger_kind=fixture.trigger.kind,
            trigger_source_digest=fixture.trigger.source_digest,
            target_scope=fixture.scope,
            item_set_digest=None,
            validated_response_digest=response_digest,
        )
        same = proactive_delivery_idempotency_key(
            trigger_kind=fixture.trigger.kind,
            trigger_source_digest=fixture.trigger.source_digest,
            target_scope=fixture.scope,
            item_set_digest=None,
            validated_response_digest=response_digest,
        )
        changed = proactive_delivery_idempotency_key(
            trigger_kind=fixture.trigger.kind,
            trigger_source_digest=fixture.trigger.source_digest,
            target_scope=fixture.scope,
            item_set_digest=canonical_digest({"item": 1}, domain="test:item-set:v1"),
            validated_response_digest=response_digest,
        )
        self.assertEqual(first, same)
        self.assertNotEqual(first, changed)

    def test_default_control_is_closed_and_parser_is_strict(self) -> None:
        control = default_proactive_control_config()
        for kind in ProactiveTriggerKind:
            behavior = control.for_trigger(kind)
            self.assertIs(behavior.mode, ProactiveRunMode.OFF)
            self.assertFalse(behavior.delivery_enabled)
            self.assertTrue(behavior.kill_switch)
            self.assertEqual(behavior.allowlisted_scope_digests, frozenset())
        document = {
            "schema_version": 1,
            "policy_revision": "policy-v1",
            "digest": self._behavior("digest-v1"),
            "probe": self._behavior("probe-v1"),
        }
        parsed = parse_proactive_control_config(document)
        self.assertEqual(parsed.policy_revision, "policy-v1")
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            parse_proactive_control_config({**document, "unknown": True})
        invalid = dict(document)
        invalid["digest"] = {**document["digest"], "delivery_enabled": True}
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            parse_proactive_control_config(invalid)

    @staticmethod
    def _behavior(revision: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "off",
            "revision": revision,
            "timezone": "Asia/Shanghai",
            "delivery_enabled": False,
            "allowlisted_scope_digests": [],
            "kill_switch": True,
            "maximum_global_messages": 1,
            "maximum_scope_messages": 1,
            "quota_window_seconds": 86400,
            "quiet_hours": [{"start": "22:00", "end": "06:00"}],
        }


class ProactiveRegistryAndAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = ProactiveFixture()
        self.registry = InMemoryProactiveTargetRegistry(
            (
                self.fixture.operator_grant,
                self.fixture.group_grant,
                self.fixture.owner_grant,
            ),
            (self.fixture.policy,),
            clock=self.fixture.clock,
        )

    async def test_registry_resolves_exact_current_target_and_grants(self) -> None:
        fixture = self.fixture
        policy = await self.registry.validate_target(
            fixture.policy.as_ref(),
            trigger_kind=fixture.trigger.kind,
            categories=frozenset(SourceCategory),
            at=fixture.now,
            call=fixture.service_call(),
        )
        self.assertEqual(policy, fixture.policy)
        forged = ProactiveTargetPolicyRef(
            1,
            fixture.policy.target_policy_id,
            2,
            fixture.policy.as_ref().target_scope_digest,
            fixture.policy.target_policy_digest,
        )
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            await self.registry.resolve_target(
                forged,
                at=fixture.now,
                call=fixture.service_call(),
            )

    async def test_registry_rejects_revoked_expired_replaced_and_cross_kind_grants(
        self,
    ) -> None:
        revoked_fixture = ProactiveFixture()
        revoked = replace(
            revoked_fixture.operator_grant,
            revoked_at=revoked_fixture.now + timedelta(seconds=30),
            grant_digest="",
        )
        revoked_registry = self._registry_with_operator(revoked_fixture, revoked)
        revoked_fixture.clock.advance(timedelta(minutes=1))
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            await revoked_registry.resolve_grant(
                revoked.as_ref(),
                at=revoked_fixture.clock.value,
                call=revoked_fixture.service_call(),
            )

        expired_fixture = ProactiveFixture()
        expired = replace(
            expired_fixture.operator_grant,
            expires_at=expired_fixture.now + timedelta(seconds=30),
            grant_digest="",
        )
        expired_registry = self._registry_with_operator(expired_fixture, expired)
        expired_fixture.clock.advance(timedelta(minutes=1))
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            await expired_registry.resolve_grant(
                expired.as_ref(),
                at=expired_fixture.clock.value,
                call=expired_fixture.service_call(),
            )

        replaced_fixture = ProactiveFixture()
        replacement = replace(
            replaced_fixture.operator_grant,
            revision=2,
            grant_digest="",
        )
        replaced_registry = self._registry_with_operator(
            replaced_fixture,
            replacement,
        )
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            await replaced_registry.resolve_grant(
                replaced_fixture.operator_grant.as_ref(),
                at=replaced_fixture.now,
                call=replaced_fixture.service_call(),
            )

        cross_kind_fixture = ProactiveFixture()
        cross_kind = replace(
            cross_kind_fixture.operator_grant,
            grant_kind=ProactiveGrantKind.GROUP_POLICY_ENABLE,
            grant_digest="",
        )
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            self._registry_with_operator(cross_kind_fixture, cross_kind)

    @staticmethod
    def _registry_with_operator(fixture, operator):
        policy = replace(
            fixture.policy,
            operator_authorization_grant_ref=operator.as_ref(),
            target_policy_digest="",
        )
        return InMemoryProactiveTargetRegistry(
            (operator, fixture.group_grant, fixture.owner_grant),
            (policy,),
            clock=fixture.clock,
        )

    async def test_send_and_preview_authorization_are_not_interchangeable(self) -> None:
        fixture = self.fixture
        config = AuthorizationPolicyConfig(
            policy_revision="auth-policy-v1",
            role_permissions={
                "operator": frozenset(
                    {str(PROACTIVE_SEND_ACTION), str(PROACTIVE_PREVIEW_ACTION)}
                )
            },
            role_constraints={
                "operator": {
                    str(PROACTIVE_SEND_ACTION): AuthorizationConstraint(
                        frozenset({"proactive_target"}),
                        frozenset({"*"}),
                    ),
                    str(PROACTIVE_PREVIEW_ACTION): AuthorizationConstraint(
                        frozenset({"proactive_subscription_preview"}),
                        frozenset({"*"}),
                    ),
                }
            },
            confirmation_risks=frozenset(),
        )
        policy = RoleAuthorizationPolicy(
            config,
            clock=fixture.clock,
            id_factory=lambda: "authorization-1",
        )
        send_request = build_proactive_send_authorization_request(
            fixture.actor,
            fixture.scope,
            fixture.trigger,
            target_policy_ref=fixture.policy.as_ref(),
            policy_snapshot_id="policy-snapshot-v1",
        )
        send_decision = await policy.decide(
            send_request,
            call=fixture.port_call(),
        )
        self.assertTrue(
            proactive_authorization_allows(
                send_request,
                send_decision,
                policy,
                at=fixture.now,
                expected_policy_revision="auth-policy-v1",
            )
        )
        preview_request = build_proactive_preview_authorization_request(
            fixture.preview,
            policy_snapshot_id="policy-snapshot-v1",
        )
        preview_decision = await policy.decide(
            preview_request,
            call=fixture.port_call(),
        )
        self.assertTrue(
            proactive_authorization_allows(
                preview_request,
                preview_decision,
                policy,
                at=fixture.now,
                expected_policy_revision="auth-policy-v1",
            )
        )
        self.assertFalse(
            proactive_authorization_allows(
                send_request,
                preview_decision,
                policy,
                at=fixture.now,
                expected_policy_revision="auth-policy-v1",
            )
        )


if __name__ == "__main__":
    unittest.main()
