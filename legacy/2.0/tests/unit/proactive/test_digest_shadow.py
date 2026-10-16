from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from dududa.contracts.canonical import canonical_digest
from dududa.errors import DududaError, ErrorCategory, error
from dududa.ports.proactive import (
    DigestComposer,
    DigestShadowMetadataSink,
    DigestShadowRunner,
    ProactivePreviewProducer,
)
from dududa.proactive.contracts import ProactiveDisposition, ProactiveRunMode
from dududa.proactive.digest_contracts import DigestShadowMetadata
from dududa.proactive.source_contracts import SourceFetchOriginKind, SourceFetchStatus

from ._digest_fixtures import DigestShadowFixture
from ._source_fixtures import GovernedSourceFixture, source_definitions


class DigestShadowTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_chain_caps_long_and_preserves_source_evidence(
        self,
    ) -> None:
        fixture = DigestShadowFixture()

        outcome = await fixture.builder.build(
            fixture.subscription,
            fixture.proactive.actor,
            origin_kind=SourceFetchOriginKind.SCHEDULED_TRIGGER,
            origin_digest=fixture.trigger.trigger_digest,
            state_namespace=fixture.subscription.subscription_id,
            call=fixture.call(),
        )

        self.assertTrue(outcome.candidate_built)
        self.assertIsInstance(fixture.composer, DigestComposer)
        self.assertEqual(outcome.response_plan.uncapped_profile.value, "long")
        self.assertEqual(outcome.response_plan.selected_profile.value, "medium")
        response = outcome.validated_response
        self.assertIsNotNone(response)
        self.assertEqual(len(response.response.fact_anchors), 3)
        self.assertEqual(len(response.response.citations), 3)
        self.assertTrue(response.profile_validation.valid)
        self.assertEqual(response.response.render_metadata.persona_id, "dududa")
        source_urls = {citation.source_ref for citation in response.response.citations}
        self.assertEqual(
            source_urls,
            {item.canonical_url for item in outcome.fetch_receipt.batch.items},
        )

        with self.assertRaises(DududaError):
            replace(
                fixture.policy,
                policy_digest=canonical_digest(
                    {"tampered": True},
                    domain="test:digest-policy-tamper:v1",
                ),
            )

    async def test_admission_modes_stop_before_source(self) -> None:
        cases = (
            (
                ProactiveRunMode.COLLECT,
                ProactiveRunMode.COLLECT,
                False,
                ProactiveDisposition.COLLECTED,
            ),
            (
                ProactiveRunMode.OFF,
                ProactiveRunMode.SHADOW,
                False,
                ProactiveDisposition.DENIED,
            ),
            (
                ProactiveRunMode.CANARY,
                ProactiveRunMode.SHADOW,
                False,
                ProactiveDisposition.DENIED,
            ),
            (
                ProactiveRunMode.SHADOW,
                ProactiveRunMode.SHADOW,
                True,
                ProactiveDisposition.DENIED,
            ),
        )
        for request_mode, control_mode, kill_switch, expected in cases:
            with self.subTest(mode=request_mode, kill_switch=kill_switch):
                fixture = DigestShadowFixture()
                runtime = fixture.runtime(control_mode, kill_switch=kill_switch)
                receipt = await runtime.run(
                    fixture.run_request(request_mode),
                    call=fixture.call(),
                )
                self.assertEqual(receipt.disposition, expected)
                self.assertEqual(fixture.source.reader.calls, [])

        fixture = DigestShadowFixture()

        class ExpiringActorResolver:
            async def resolve(self, reference, scope, *, call):
                fixture.proactive.clock.advance(timedelta(hours=2))
                return fixture.proactive.actor

        fixture.actor_resolver = ExpiringActorResolver()
        expired = await fixture.runtime().run(
            fixture.run_request(),
            call=fixture.call(),
        )
        self.assertEqual(expired.disposition, ProactiveDisposition.DENIED)
        self.assertEqual(expired.reason_codes, ("digest_trigger_expired",))
        self.assertEqual(fixture.source.reader.calls, [])

    async def test_shadow_records_digest_only_metadata_and_duplicate_noop(self) -> None:
        fixture = DigestShadowFixture()
        runtime = fixture.runtime()
        request = fixture.run_request()

        first = await runtime.run(request, call=fixture.call())
        second = await runtime.run(request, call=fixture.call())

        self.assertEqual(first.disposition, ProactiveDisposition.SHADOWED)
        self.assertIsInstance(runtime, DigestShadowRunner)
        self.assertIsInstance(
            fixture.metadata_sink,
            DigestShadowMetadataSink,
        )
        self.assertEqual(second.disposition, ProactiveDisposition.SHADOWED)
        self.assertTrue(fixture.metadata_sink.records[0].candidate_built)
        self.assertFalse(fixture.metadata_sink.records[1].candidate_built)
        self.assertEqual(
            fixture.metadata_sink.records[1].source_fetch_status,
            SourceFetchStatus.NO_NEW_ITEMS,
        )
        self.assertNotIn("response", DigestShadowMetadata.__dataclass_fields__)
        self.assertFalse(
            set(vars(runtime))
            & {
                "_output",
                "_dispatch_store",
                "_scheduler",
                "_memory",
                "_model",
            }
        )

    async def test_partial_failure_and_cancellation_have_bounded_results(self) -> None:
        timeout = error(
            "source_timeout",
            ErrorCategory.TIMEOUT,
            "request.timeout",
            retryable=True,
        )
        partial_source = GovernedSourceFixture(failures={"arxiv-fixture": timeout})
        partial = DigestShadowFixture(source=partial_source)
        partial_outcome = await partial.builder.build(
            partial.subscription,
            partial.proactive.actor,
            origin_kind=SourceFetchOriginKind.SCHEDULED_TRIGGER,
            origin_digest=partial.trigger.trigger_digest,
            state_namespace=partial.subscription.subscription_id,
            call=partial.call(),
        )
        self.assertEqual(
            partial_outcome.fetch_receipt.status,
            SourceFetchStatus.PARTIAL,
        )
        self.assertTrue(partial_outcome.candidate_built)
        self.assertEqual(len(partial_outcome.validated_response.response.warnings), 1)

        failures = {
            definition.source_id: timeout for definition in source_definitions()
        }
        failed = DigestShadowFixture(source=GovernedSourceFixture(failures=failures))
        failed_receipt = await failed.runtime().run(
            failed.run_request(),
            call=failed.call(),
        )
        self.assertEqual(failed_receipt.disposition, ProactiveDisposition.FAILED)
        self.assertFalse(failed.metadata_sink.records[0].candidate_built)

        cancelled_error = error(
            "source_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
        cancelled = DigestShadowFixture(
            source=GovernedSourceFixture(failures={"campus-fixture": cancelled_error})
        )
        cancelled_receipt = await cancelled.runtime().run(
            cancelled.run_request(),
            call=cancelled.call(),
        )
        self.assertEqual(
            cancelled_receipt.disposition,
            ProactiveDisposition.FAILED,
        )
        self.assertEqual(
            cancelled.metadata_sink.records[0].source_fetch_status,
            SourceFetchStatus.CANCELLED,
        )

    async def test_preview_uses_state_isolated_from_scheduled_shadow(self) -> None:
        fixture = DigestShadowFixture()
        runtime = fixture.runtime()
        await runtime.run(fixture.run_request(), call=fixture.call())
        producer = fixture.preview_producer()

        response, batch_digest = await producer.build(
            fixture.preview_request(),
            call=fixture.call(),
        )

        self.assertIsInstance(producer, ProactivePreviewProducer)
        self.assertIsNotNone(response)
        self.assertIsNotNone(batch_digest)
        second_shadow = await runtime.run(fixture.run_request(), call=fixture.call())
        self.assertEqual(second_shadow.disposition, ProactiveDisposition.SHADOWED)
        self.assertFalse(fixture.metadata_sink.records[-1].candidate_built)
        with self.assertRaises(DududaError):
            await producer.build(fixture.preview_request(), call=fixture.call())
        self.assertFalse(
            set(vars(producer))
            & {"_scheduler", "_dispatch_store", "_output", "_delivery"}
        )

    async def test_day_1_2_30_sampling_never_builds_a_duplicate_candidate(self) -> None:
        fixture = DigestShadowFixture()
        runtime = fixture.runtime()

        await runtime.run(
            fixture.run_request_at(fixture.now, "day-1"),
            call=fixture.call(),
        )
        fixture.proactive.clock.advance(timedelta(days=1))
        fixture.source.clock.advance(timedelta(days=1))
        await runtime.run(
            fixture.run_request_at(fixture.proactive.clock.value, "day-2"),
            call=fixture.call(),
        )
        fixture.proactive.clock.advance(timedelta(days=28))
        fixture.source.clock.advance(timedelta(days=28))
        await runtime.run(
            fixture.run_request_at(fixture.proactive.clock.value, "day-30"),
            call=fixture.call(),
        )

        self.assertEqual(
            sum(item.candidate_built for item in fixture.metadata_sink.records),
            1,
        )
        self.assertEqual(
            fixture.metadata_sink.records[1].source_fetch_status,
            SourceFetchStatus.NO_NEW_ITEMS,
        )
        self.assertEqual(
            fixture.metadata_sink.records[2].source_fetch_status,
            SourceFetchStatus.FAILED,
        )


if __name__ == "__main__":
    unittest.main()
