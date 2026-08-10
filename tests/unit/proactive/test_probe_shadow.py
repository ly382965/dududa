from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import timedelta

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import ConversationScope
from dududa.domain.primitives import ConversationType, Sensitivity
from dududa.errors import DududaError
from dududa.ports.proactive import (
    ProbeComposer,
    ProbeOpportunityDetector,
    ProbeShadowMetadataSink,
    ProbeShadowRunner,
    ProbeStateStore,
)
from dududa.proactive.contracts import (
    LocalTimeWindow,
    ProactiveDisposition,
    ProactiveRunMode,
)
from dududa.proactive.probe_contracts import (
    ProbeDetectionStatus,
    ProbeHardBlocker,
    ProbeOutcomeKind,
    ProbeOutcomeObservation,
    ProbeShadowMetadata,
)
from dududa.security.digests import scope_digest
from dududa.testing.proactive import RecordingFakeProactiveOutput

from ._probe_fixtures import ProbeShadowFixture


class ProbeShadowTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_group_pause_builds_bound_short_opportunity(self) -> None:
        fixture = ProbeShadowFixture()
        window = fixture.window()

        detection = fixture.detector.detect(window, fixture.policy, at=fixture.now)
        repeated = fixture.detector.detect(window, fixture.policy, at=fixture.now)

        self.assertIs(detection.status, ProbeDetectionStatus.ELIGIBLE)
        self.assertEqual(
            detection.opportunity.snapshot_digest,
            repeated.opportunity.snapshot_digest,
        )
        opportunity = detection.opportunity
        self.assertEqual(opportunity.scope, fixture.proactive.scope)
        self.assertEqual(
            opportunity.target_policy_ref,
            fixture.proactive.policy.as_ref(),
        )
        self.assertLessEqual(
            opportunity.expires_at,
            fixture.now + fixture.policy.opportunity_ttl,
        )
        candidate = await fixture.builder.build(
            opportunity,
            fixture.bound_run(opportunity),
            fixture.proactive.actor,
            call=fixture.call(),
        )
        self.assertEqual(candidate.response_plan.selected_profile.value, "short")
        self.assertEqual(len(candidate.validated_response.response.blocks), 1)
        self.assertEqual(candidate.validated_response.response.target_users, ())
        self.assertNotIn(
            "@",
            candidate.validated_response.response.blocks[0].content.text,
        )

        runtime = fixture.runtime()
        metadata = await runtime.run(fixture.request(window), call=fixture.call())
        self.assertEqual(metadata.disposition, ProactiveDisposition.SHADOWED)
        self.assertTrue(metadata.candidate_built)
        self.assertIsInstance(fixture.detector, ProbeOpportunityDetector)
        self.assertIsInstance(fixture.composer, ProbeComposer)
        self.assertIsInstance(fixture.state_store, ProbeStateStore)
        self.assertIsInstance(fixture.metadata_sink, ProbeShadowMetadataSink)
        self.assertIsInstance(runtime, ProbeShadowRunner)

    async def test_group_and_public_boundaries_fail_closed(self) -> None:
        fixture = ProbeShadowFixture()
        window = fixture.window()
        private_scope = ConversationScope(
            window.scope.platform,
            window.scope.bot_id,
            ConversationType.PRIVATE,
            "private-1",
            None,
            window.scope.persona_id,
        )
        with self.assertRaises(DududaError):
            fixture.replace_window(window, scope=private_scope)
        forged_ref = replace(
            window.target_policy_ref,
            target_scope_digest=canonical_digest(
                {"scope": "other"},
                domain="test:other-probe-scope:v1",
            ),
        )
        with self.assertRaises(DududaError):
            fixture.replace_window(window, target_policy_ref=forged_ref)

        cases = (
            fixture.window("personal", sensitivity=Sensitivity.PERSONAL),
            fixture.window("mention", summary="@alice should answer this"),
            fixture.window(
                "target",
                blockers=frozenset({ProbeHardBlocker.PERSONAL_TARGET}),
            ),
            fixture.window(
                "memory",
                blockers=frozenset({ProbeHardBlocker.PERSONAL_MEMORY_REQUIRED}),
            ),
        )
        for value in cases:
            with self.subTest(window=value.window_id):
                result = fixture.detector.detect(value, fixture.policy, at=fixture.now)
                self.assertIs(result.status, ProbeDetectionStatus.INELIGIBLE)
                self.assertIsNone(result.opportunity)

    async def test_interruption_and_control_gates_stop_before_candidate(self) -> None:
        blockers = (
            ProbeHardBlocker.ACTIVE_HUMAN_DIALOGUE,
            ProbeHardBlocker.DIRECTED_QUESTION,
            ProbeHardBlocker.CONFLICT_ESCALATION,
            ProbeHardBlocker.SAFETY_EVENT,
            ProbeHardBlocker.PENDING_DELIVERY,
            ProbeHardBlocker.UNRESOLVED_PROBE,
        )
        for blocker in blockers:
            with self.subTest(blocker=blocker):
                fixture = ProbeShadowFixture()
                metadata = await fixture.runtime().run(
                    fixture.request(
                        fixture.window(
                            blocker.value,
                            blockers=frozenset({blocker}),
                        )
                    ),
                    call=fixture.call(),
                )
                self.assertEqual(metadata.disposition, ProactiveDisposition.DENIED)
                self.assertFalse(metadata.candidate_built)

        recent = ProbeShadowFixture()
        recent_result = recent.detector.detect(
            recent.window("recent", last_bot_delta=timedelta(minutes=1)),
            recent.policy,
            at=recent.now,
        )
        self.assertIn("probe_bot_activity_too_recent", recent_result.reason_codes)

        controls = (
            (ProactiveRunMode.SHADOW, True, (), ProactiveDisposition.DENIED),
            (
                ProactiveRunMode.SHADOW,
                False,
                (LocalTimeWindow.from_strings("07:00", "09:00"),),
                ProactiveDisposition.DENIED,
            ),
            (ProactiveRunMode.COLLECT, False, (), ProactiveDisposition.COLLECTED),
        )
        for mode, kill_switch, quiet_hours, expected in controls:
            with self.subTest(mode=mode, kill_switch=kill_switch):
                fixture = ProbeShadowFixture()
                metadata = await fixture.runtime(
                    mode,
                    kill_switch=kill_switch,
                    quiet_hours=quiet_hours,
                ).run(
                    fixture.request(mode=mode),
                    call=fixture.call(),
                )
                self.assertEqual(metadata.disposition, expected)
                if expected is not ProactiveDisposition.SHADOWED:
                    self.assertFalse(metadata.candidate_built)

    async def test_topic_ttl_boundaries_never_revive(self) -> None:
        fixture = ProbeShadowFixture()
        before = fixture.window(
            "before",
            last_human_delta=fixture.policy.maximum_topic_age
            - timedelta(microseconds=1),
            last_bot_delta=None,
        )
        exact = fixture.window(
            "exact",
            last_human_delta=fixture.policy.maximum_topic_age,
            last_bot_delta=None,
        )
        self.assertIs(
            fixture.detector.detect(before, fixture.policy, at=fixture.now).status,
            ProbeDetectionStatus.ELIGIBLE,
        )
        self.assertIs(
            fixture.detector.detect(exact, fixture.policy, at=fixture.now).status,
            ProbeDetectionStatus.INELIGIBLE,
        )
        self.assertIs(
            fixture.detector.detect(
                exact,
                fixture.policy,
                at=fixture.now + timedelta(days=1),
            ).status,
            ProbeDetectionStatus.INELIGIBLE,
        )

        expiring = ProbeShadowFixture()

        class ExpiringActorResolver:
            async def resolve(self, reference, scope, *, call):
                expiring.clock.advance(timedelta(minutes=11))
                return expiring.proactive.actor

        expiring.actor_resolver = ExpiringActorResolver()
        metadata = await expiring.runtime().run(
            expiring.request(),
            call=expiring.call(),
        )
        self.assertEqual(metadata.disposition, ProactiveDisposition.DENIED)
        self.assertEqual(
            metadata.reason_codes,
            ("probe_opportunity_expired_before_composition",),
        )
        self.assertFalse(metadata.candidate_built)

    async def test_scope_cooldown_and_no_response_boundaries(self) -> None:
        fixture = ProbeShadowFixture()
        first = fixture.detector.detect(
            fixture.window("first"),
            fixture.policy,
            at=fixture.clock.value,
        ).opportunity
        claims = await asyncio.gather(
            *(
                fixture.state_store.claim(
                    first,
                    namespace="shadow:probe-policy-v1",
                    cooldown=fixture.policy.shadow_cooldown,
                    at=fixture.clock.value,
                    call=fixture.port_call(),
                )
                for _ in range(2)
            )
        )
        first_claim = next(value for value in claims if value.acquired)
        self.assertTrue(first_claim.acquired)
        self.assertEqual(
            sorted(value.disposition.value for value in claims),
            ["acquired", "duplicate"],
        )

        fixture.clock.advance(timedelta(minutes=11))
        second = fixture.detector.detect(
            fixture.window("second"),
            fixture.policy,
            at=fixture.clock.value,
        ).opportunity
        cooling = await fixture.state_store.claim(
            second,
            namespace="shadow:probe-policy-v1",
            cooldown=fixture.policy.shadow_cooldown,
            at=fixture.clock.value,
            call=fixture.port_call(),
        )
        self.assertEqual(cooling.disposition.value, "cooldown")

        fixture.clock.value = fixture.now + fixture.policy.shadow_cooldown
        boundary = fixture.detector.detect(
            fixture.window("boundary"),
            fixture.policy,
            at=fixture.clock.value,
        ).opportunity
        acquired = await fixture.state_store.claim(
            boundary,
            namespace="shadow:probe-policy-v1",
            cooldown=fixture.policy.shadow_cooldown,
            at=fixture.clock.value,
            call=fixture.port_call(),
        )
        self.assertTrue(acquired.acquired)
        early = ProbeOutcomeObservation(
            1,
            "probe-outcome-early",
            "shadow:probe-policy-v1",
            scope_digest(fixture.proactive.scope),
            boundary.snapshot_digest,
            canonical_digest(
                {"delivery": "synthetic-boundary"},
                domain="test:probe-attribution:v1",
            ),
            acquired.current_revision,
            ProbeOutcomeKind.NO_OBSERVED_RESPONSE,
            fixture.clock.value,
        )
        with self.assertRaises(DududaError):
            await fixture.state_store.record_outcome(
                early,
                attribution_window=fixture.policy.response_attribution_window,
                ordinary_cooldown=fixture.policy.shadow_cooldown,
                no_response_cooldown=fixture.policy.no_response_cooldown,
                call=fixture.port_call(),
            )
        fixture.clock.advance(fixture.policy.response_attribution_window)
        observation = replace(
            early,
            observation_id="probe-outcome-1",
            observed_at=fixture.clock.value,
            observation_digest="",
        )
        state = await fixture.state_store.record_outcome(
            observation,
            attribution_window=fixture.policy.response_attribution_window,
            ordinary_cooldown=fixture.policy.shadow_cooldown,
            no_response_cooldown=fixture.policy.no_response_cooldown,
            call=fixture.port_call(),
        )
        self.assertIs(state.last_outcome, ProbeOutcomeKind.NO_OBSERVED_RESPONSE)
        fixture.clock.advance(
            fixture.policy.no_response_cooldown - timedelta(seconds=1)
        )
        within = fixture.detector.detect(
            fixture.window("within"),
            fixture.policy,
            at=fixture.clock.value,
        ).opportunity
        denied = await fixture.state_store.claim(
            within,
            namespace="shadow:probe-policy-v1",
            cooldown=fixture.policy.shadow_cooldown,
            at=fixture.clock.value,
            call=fixture.port_call(),
        )
        self.assertEqual(denied.disposition.value, "cooldown")
        fixture.clock.advance(timedelta(seconds=1))
        after = fixture.detector.detect(
            fixture.window("after"),
            fixture.policy,
            at=fixture.clock.value,
        ).opportunity
        self.assertTrue(
            (
                await fixture.state_store.claim(
                    after,
                    namespace="shadow:probe-policy-v1",
                    cooldown=fixture.policy.shadow_cooldown,
                    at=fixture.clock.value,
                    call=fixture.port_call(),
                )
            ).acquired
        )

    async def test_shadow_metadata_only_no_send_and_day_sampling(self) -> None:
        fixture = ProbeShadowFixture()
        runtime = fixture.runtime()
        output = RecordingFakeProactiveOutput()
        request = fixture.request()

        first = await runtime.run(request, call=fixture.call())
        duplicate = await runtime.run(request, call=fixture.call())
        state = await fixture.state_store.load(
            "shadow:probe-policy-v1",
            scope_digest(fixture.proactive.scope),
            call=fixture.port_call(),
        )
        fixture.clock.advance(fixture.policy.response_attribution_window)
        await fixture.state_store.record_outcome(
            ProbeOutcomeObservation(
                1,
                "probe-outcome-shadow-1",
                state.namespace,
                state.scope_digest,
                state.last_opportunity_digest,
                canonical_digest(
                    {"delivery": "synthetic-shadow"},
                    domain="test:probe-attribution:v1",
                ),
                state.revision,
                ProbeOutcomeKind.NO_OBSERVED_RESPONSE,
                fixture.clock.value,
            ),
            attribution_window=fixture.policy.response_attribution_window,
            ordinary_cooldown=fixture.policy.shadow_cooldown,
            no_response_cooldown=fixture.policy.no_response_cooldown,
            call=fixture.port_call(),
        )
        fixture.clock.advance(timedelta(days=1))
        day_2 = await runtime.run(
            fixture.request(fixture.window("day-2"), suffix="day-2"),
            call=fixture.call(),
        )
        fixture.clock.advance(timedelta(days=28))
        day_30 = await runtime.run(
            fixture.request(fixture.window("day-30"), suffix="day-30"),
            call=fixture.call(),
        )

        self.assertEqual(first.disposition, ProactiveDisposition.SHADOWED)
        self.assertEqual(duplicate.reason_codes, ("probe_state_duplicate",))
        self.assertEqual(day_2.reason_codes, ("probe_state_cooldown",))
        self.assertEqual(day_30.reason_codes, ("probe_state_cooldown",))
        self.assertEqual(
            sum(value.candidate_built for value in fixture.metadata_sink.records),
            1,
        )
        self.assertEqual(output.calls, [])
        self.assertNotIn("topic_summary", ProbeShadowMetadata.__dataclass_fields__)
        self.assertNotIn("response", ProbeShadowMetadata.__dataclass_fields__)
        self.assertFalse(
            set(vars(runtime))
            & {
                "_output",
                "_dispatch_store",
                "_scheduler",
                "_memory",
                "_capability",
                "_tool",
                "_model",
                "_follow_up",
            }
        )
        self.assertEqual(len(fixture.metadata_sink.records), 4)


if __name__ == "__main__":
    unittest.main()
