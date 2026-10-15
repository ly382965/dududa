from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from dududa.contracts.canonical import canonical_digest
from dududa.errors import DududaError
from dududa.proactive.authorization import (
    PROACTIVE_PREVIEW_ACTION,
    PROACTIVE_SEND_ACTION,
)
from dududa.proactive.config import (
    ProactiveBehaviorControl,
    ProactiveControlConfig,
    default_proactive_control_config,
)
from dududa.proactive.contracts import (
    DispatchState,
    LocalTimeWindow,
    ProactiveRunMode,
)
from dududa.proactive.policy import (
    DeterministicProactivePolicy,
    ProactiveInitiationGuard,
)
from dududa.proactive.preview import IsolatedProactivePreviewService
from dududa.proactive.quota import InMemoryProactiveQuotaLedger
from dududa.proactive.registry import InMemoryProactiveTargetRegistry
from dududa.proactive.store import InMemoryProactiveDispatchStore
from dududa.security.audit import InMemoryAuditSink
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.digests import scope_digest
from dududa.testing.proactive import (
    MappingProactiveActorResolver,
    RecordingFakeProactiveOutput,
    RecordingProactivePreviewMetadataStore,
    StaticProactivePreviewProducer,
)

from ._fixtures import ProactiveFixture
from .test_digests import _binding, _prepared_dispatch, _response


class FailingAuditSink:
    async def write(self, event, *, call):
        raise RuntimeError("synthetic audit outage")


class DispatchAndQuotaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = ProactiveFixture()
        self.ids = iter(f"id-{index}" for index in range(100))

    async def test_prepare_reuses_original_across_adapter_revision(self) -> None:
        fixture = self.fixture
        store = InMemoryProactiveDispatchStore(
            clock=fixture.clock,
            id_factory=lambda: next(self.ids),
        )
        original = _prepared_dispatch(fixture, adapter_revision="adapter-v1")
        await store.prepare(original, call=fixture.service_call())
        upgraded_candidate = replace(
            original,
            dispatch_id="dispatch-after-restart",
            adapter_binding=_binding("adapter-v2"),
            prepared_at=original.prepared_at + timedelta(seconds=10),
            expires_at=original.expires_at + timedelta(seconds=10),
            prepared_dispatch_digest="",
        )
        recovered = await store.prepare(
            upgraded_candidate,
            call=fixture.service_call(),
        )
        self.assertIs(recovered, original)
        self.assertEqual(recovered.idempotency_key, original.idempotency_key)
        self.assertEqual(recovered.adapter_binding, original.adapter_binding)

    async def test_changed_business_content_conflicts_for_same_trigger(self) -> None:
        fixture = self.fixture
        store = InMemoryProactiveDispatchStore(clock=fixture.clock)
        original = _prepared_dispatch(fixture, adapter_revision="adapter-v1")
        await store.prepare(original, call=fixture.service_call())
        changed_response = canonical_digest(
            {"different": True},
            domain="test:proactive-validated-response:v1",
        )
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            replace(
                original,
                validated_response_digest=changed_response,
                prepared_dispatch_digest="",
            )
        changed_policy = replace(
            original,
            policy_decision_digest=canonical_digest(
                {"policy": 2},
                domain="test:proactive-policy-decision:v1",
            ),
            prepared_dispatch_digest="",
        )
        with self.assertRaisesRegex(DududaError, "request.conflict"):
            await store.prepare(changed_policy, call=fixture.service_call())

    async def test_attempt_crash_recovers_unknown_without_new_payload(self) -> None:
        fixture = self.fixture
        store = InMemoryProactiveDispatchStore(
            clock=fixture.clock,
            id_factory=lambda: next(self.ids),
        )
        prepared = _prepared_dispatch(fixture, adapter_revision="adapter-v1")
        await store.prepare(prepared, call=fixture.service_call())
        attempted = await store.record_attempt(
            prepared.trigger_digest,
            expected_revision=1,
            delivery_request_digest=canonical_digest(
                {"delivery": 1},
                domain="test:proactive-delivery-request:v1",
            ),
            call=fixture.service_call(),
        )
        recovered = await store.recover(
            prepared.trigger_digest,
            call=fixture.service_call(),
        )
        assert recovered is not None
        self.assertIs(recovered.state, DispatchState.UNKNOWN)
        self.assertEqual(recovered.prepared, prepared)
        self.assertEqual(recovered.attempt, attempted.attempt)
        self.assertEqual(recovered.prepared.idempotency_key, prepared.idempotency_key)

    async def test_claim_has_single_live_owner(self) -> None:
        fixture = self.fixture
        store = InMemoryProactiveDispatchStore(
            clock=fixture.clock,
            id_factory=lambda: next(self.ids),
        )
        prepared = _prepared_dispatch(fixture, adapter_revision="adapter-v1")
        await store.prepare(prepared, call=fixture.service_call())
        first = await store.claim(
            prepared.trigger_digest,
            worker_id="worker-1",
            ttl=timedelta(seconds=30),
            call=fixture.service_call(),
        )
        duplicate = await store.claim(
            prepared.trigger_digest,
            worker_id="worker-1",
            ttl=timedelta(seconds=30),
            call=fixture.service_call(),
        )
        self.assertEqual(first, duplicate)
        with self.assertRaisesRegex(DududaError, "request.conflict"):
            await store.claim(
                prepared.trigger_digest,
                worker_id="worker-2",
                ttl=timedelta(seconds=30),
                call=fixture.service_call(),
            )

    async def test_quota_pair_is_atomic_idempotent_and_releasable(self) -> None:
        fixture = self.fixture
        quota = InMemoryProactiveQuotaLedger(
            clock=fixture.clock,
            id_factory=lambda: next(self.ids),
        )
        first_digest = canonical_digest({"run": 1}, domain="test:quota-run:v1")
        first = await quota.reserve(
            first_digest,
            fixture.scope,
            global_limit=1,
            scope_limit=1,
            window=timedelta(days=1),
            policy_revision="quota-v1",
            call=fixture.service_call(),
        )
        self.assertTrue(all(value.allowed for value in first))
        self.assertEqual(
            first,
            await quota.reserve(
                first_digest,
                fixture.scope,
                global_limit=1,
                scope_limit=1,
                window=timedelta(days=1),
                policy_revision="quota-v1",
                call=fixture.service_call(),
            ),
        )
        denied = await quota.reserve(
            canonical_digest({"run": 2}, domain="test:quota-run:v1"),
            fixture.scope,
            global_limit=1,
            scope_limit=1,
            window=timedelta(days=1),
            policy_revision="quota-v1",
            call=fixture.service_call(),
        )
        self.assertFalse(any(value.allowed for value in denied))
        await quota.release(first, call=fixture.service_call())
        third = await quota.reserve(
            canonical_digest({"run": 3}, domain="test:quota-run:v1"),
            fixture.scope,
            global_limit=1,
            scope_limit=1,
            window=timedelta(days=1),
            policy_revision="quota-v1",
            call=fixture.service_call(),
        )
        self.assertTrue(all(value.allowed for value in third))


class PolicyAndPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = ProactiveFixture()
        self.ids = iter(f"policy-id-{index}" for index in range(100))
        self.registry = InMemoryProactiveTargetRegistry(
            (
                self.fixture.operator_grant,
                self.fixture.group_grant,
                self.fixture.owner_grant,
            ),
            (self.fixture.policy,),
            clock=self.fixture.clock,
        )
        self.authorization = self._authorization_policy()

    def _authorization_policy(self) -> RoleAuthorizationPolicy:
        permissions = {
            str(PROACTIVE_SEND_ACTION): AuthorizationConstraint(
                frozenset({"proactive_target"}),
                frozenset({"*"}),
            ),
            str(PROACTIVE_PREVIEW_ACTION): AuthorizationConstraint(
                frozenset({"proactive_subscription_preview"}),
                frozenset({"*"}),
            ),
        }
        return RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                policy_revision="auth-policy-v1",
                role_permissions={"operator": frozenset(permissions)},
                role_constraints={"operator": permissions},
                confirmation_risks=frozenset(),
            ),
            clock=self.fixture.clock,
            id_factory=lambda: next(self.ids),
        )

    def _canary_control(
        self,
        *,
        kill_switch: bool = False,
        quiet: bool = False,
        maximum_messages: int = 10,
    ) -> ProactiveControlConfig:
        common = {
            "schema_version": 1,
            "mode": ProactiveRunMode.CANARY,
            "timezone": "Asia/Shanghai",
            "delivery_enabled": True,
            "allowlisted_scope_digests": frozenset({scope_digest(self.fixture.scope)}),
            "kill_switch": kill_switch,
            "maximum_global_messages": maximum_messages,
            "maximum_scope_messages": maximum_messages,
            "quota_window": timedelta(days=1),
            "quiet_hours": (
                (LocalTimeWindow.from_strings("07:00", "09:00"),) if quiet else ()
            ),
        }
        return ProactiveControlConfig(
            1,
            "proactive-policy-v1",
            ProactiveBehaviorControl(revision="digest-canary-v1", **common),
            ProactiveBehaviorControl(revision="probe-canary-v1", **common),
        )

    def _policy(
        self,
        control: ProactiveControlConfig,
        audit=None,
        quota=None,
        *,
        authorization_policy_revision: str = "auth-policy-v1",
    ):
        return DeterministicProactivePolicy(
            control,
            target_registry=self.registry,
            authorization_policy=self.authorization,
            authorization_verifier=self.authorization,
            authorization_policy_revision=authorization_policy_revision,
            quota_ledger=quota
            or InMemoryProactiveQuotaLedger(
                clock=self.fixture.clock, id_factory=lambda: next(self.ids)
            ),
            audit_sink=audit or InMemoryAuditSink(clock=self.fixture.clock),
            clock=self.fixture.clock,
            id_factory=lambda: next(self.ids),
        )

    async def test_default_off_short_circuits_before_side_effects(self) -> None:
        output = RecordingFakeProactiveOutput()
        evaluation = await self._policy(
            default_proactive_control_config()
        ).authorize_delivery(
            self.fixture.run,
            self.fixture.actor,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )
        self.assertFalse(evaluation.decision.allowed)
        self.assertEqual(evaluation.decision.reason_codes, ("control_mode_mismatch",))
        self.assertEqual(output.calls, [])

    async def test_non_delivery_modes_and_empty_allowlist_never_authorize(self) -> None:
        base = self._canary_control()
        for mode in (
            ProactiveRunMode.OFF,
            ProactiveRunMode.COLLECT,
            ProactiveRunMode.SHADOW,
        ):
            with self.subTest(mode=mode):
                digest = replace(
                    base.digest,
                    mode=mode,
                    delivery_enabled=False,
                )
                probe = replace(
                    base.probe,
                    mode=mode,
                    delivery_enabled=False,
                )
                control = replace(base, digest=digest, probe=probe)
                request = replace(self.fixture.run, mode=mode, start_digest="")
                evaluation = await self._policy(control).authorize_delivery(
                    request,
                    self.fixture.actor,
                    subscription=self.fixture.subscription,
                    call=self.fixture.service_call(),
                )
                self.assertFalse(evaluation.decision.allowed)
                self.assertEqual(
                    evaluation.decision.reason_codes,
                    ("mode_has_no_delivery",),
                )

        empty_digest = replace(
            base.digest,
            allowlisted_scope_digests=frozenset(),
        )
        empty_probe = replace(
            base.probe,
            allowlisted_scope_digests=frozenset(),
        )
        empty_control = replace(base, digest=empty_digest, probe=empty_probe)
        canary = replace(
            self.fixture.run,
            mode=ProactiveRunMode.CANARY,
            start_digest="",
        )
        denied = await self._policy(empty_control).authorize_delivery(
            canary,
            self.fixture.actor,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )
        self.assertEqual(denied.decision.reason_codes, ("empty_scope_allowlist",))

    async def test_canary_revalidates_authorization_quota_and_audit(self) -> None:
        audit = InMemoryAuditSink(clock=self.fixture.clock)
        request = replace(
            self.fixture.run,
            mode=ProactiveRunMode.CANARY,
            start_digest="",
        )
        evaluation = await self._policy(
            self._canary_control(), audit=audit
        ).authorize_delivery(
            request,
            self.fixture.actor,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )
        self.assertTrue(evaluation.decision.allowed)
        self.assertIsNotNone(evaluation.quota_leases)
        self.assertEqual(evaluation.decision.reason_codes, ("delivery_authorized",))
        self.assertEqual(len(audit.events), 1)

    async def test_initiation_guard_resolves_subscription_owner(self) -> None:
        request = replace(
            self.fixture.run,
            mode=ProactiveRunMode.CANARY,
            start_digest="",
        )
        resolver = MappingProactiveActorResolver(
            {self.fixture.subscription.owner_ref: self.fixture.actor}
        )
        guard = ProactiveInitiationGuard(
            self._policy(self._canary_control()),
            target_registry=self.registry,
            actor_resolver=resolver,
            clock=self.fixture.clock,
        )

        evaluation = await guard.authorize_delivery(
            request,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )

        self.assertTrue(evaluation.decision.allowed)
        self.assertEqual(
            resolver.requests,
            [(self.fixture.subscription.owner_ref, self.fixture.scope)],
        )

    async def test_initiation_guard_denies_missing_current_actor(self) -> None:
        request = replace(
            self.fixture.run,
            mode=ProactiveRunMode.CANARY,
            start_digest="",
        )
        resolver = MappingProactiveActorResolver({})
        guard = ProactiveInitiationGuard(
            self._policy(self._canary_control()),
            target_registry=self.registry,
            actor_resolver=resolver,
            clock=self.fixture.clock,
        )

        evaluation = await guard.authorize_delivery(
            request,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )

        self.assertFalse(evaluation.decision.allowed)
        self.assertEqual(
            evaluation.decision.reason_codes,
            ("actor_resolution_unavailable",),
        )

    async def test_authorization_policy_revision_must_match(self) -> None:
        request = replace(
            self.fixture.run,
            mode=ProactiveRunMode.CANARY,
            start_digest="",
        )

        evaluation = await self._policy(
            self._canary_control(),
            authorization_policy_revision="unexpected-policy-v2",
        ).authorize_delivery(
            request,
            self.fixture.actor,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )

        self.assertFalse(evaluation.decision.allowed)
        self.assertEqual(evaluation.decision.reason_codes, ("authorization_denied",))

    async def test_audit_failure_releases_reserved_quota(self) -> None:
        quota = InMemoryProactiveQuotaLedger(
            clock=self.fixture.clock,
            id_factory=lambda: next(self.ids),
        )
        control = self._canary_control(maximum_messages=1)
        first = replace(
            self.fixture.run,
            run_id="run-audit-failure",
            mode=ProactiveRunMode.CANARY,
            start_digest="",
        )
        failed = await self._policy(
            control,
            audit=FailingAuditSink(),
            quota=quota,
        ).authorize_delivery(
            first,
            self.fixture.actor,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )
        second = replace(
            first,
            run_id="run-after-audit-failure",
            start_digest="",
        )
        recovered = await self._policy(control, quota=quota).authorize_delivery(
            second,
            self.fixture.actor,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )

        self.assertEqual(failed.decision.reason_codes, ("audit_unavailable",))
        self.assertTrue(recovered.decision.allowed)

    async def test_kill_switch_and_quiet_hours_deny_before_output(self) -> None:
        request = replace(
            self.fixture.run,
            mode=ProactiveRunMode.CANARY,
            start_digest="",
        )
        killed = await self._policy(
            self._canary_control(kill_switch=True)
        ).authorize_delivery(
            request,
            self.fixture.actor,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )
        self.assertEqual(killed.decision.reason_codes, ("kill_switch_active",))
        quiet = await self._policy(self._canary_control(quiet=True)).authorize_delivery(
            request,
            self.fixture.actor,
            subscription=self.fixture.subscription,
            call=self.fixture.service_call(),
        )
        self.assertEqual(quiet.decision.reason_codes, ("control_quiet_hours",))

    async def test_preview_authorized_result_has_no_output_or_dispatch(self) -> None:
        output = RecordingFakeProactiveOutput()
        producer = StaticProactivePreviewProducer(
            _response(self.fixture),
            source_batch_digest=canonical_digest(
                {"batch": 1},
                domain="test:preview-source-batch:v1",
            ),
        )
        metadata_store = RecordingProactivePreviewMetadataStore()
        preview = IsolatedProactivePreviewService(
            target_registry=self.registry,
            authorization_policy=self.authorization,
            authorization_verifier=self.authorization,
            authorization_policy_revision="auth-policy-v1",
            producer=producer,
            metadata_store=metadata_store,
            clock=self.fixture.clock,
        )
        result = await preview.preview(
            self.fixture.preview,
            call=self.fixture.service_call(),
        )
        self.assertEqual(result.mode, ProactiveRunMode.PREVIEW)
        self.assertIsNotNone(result.final_response)
        self.assertEqual(len(producer.requests), 1)
        self.assertEqual(len(metadata_store.records), 1)
        self.assertFalse(hasattr(metadata_store.records[0], "final_response"))
        self.assertEqual(output.calls, [])


if __name__ == "__main__":
    unittest.main()
