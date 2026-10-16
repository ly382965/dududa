from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Callable

from dududa.models.contracts import ProviderRequest
from dududa.models.errors import ModelProviderError
from dududa.ports.context import ManualCancellationToken, PortCallContext

from tests.unit.models.helpers import NOW


@dataclass(slots=True)
class ProviderConformanceFixture:
    provider: object
    request: ProviderRequest
    call: PortCallContext
    underlying_call_count: Callable[[], int]


class ModelProviderConformanceMixin:
    def make_provider_fixture(self) -> ProviderConformanceFixture:
        raise NotImplementedError

    async def test_conformance_success_binds_request_and_processing(self) -> None:
        fixture = self.make_provider_fixture()
        response = await fixture.provider.generate(fixture.request, call=fixture.call)
        self.assertEqual(response.request_id, fixture.request.request_id)
        self.assertEqual(response.provider_id, fixture.request.provider_id)
        self.assertEqual(response.endpoint_id, fixture.request.endpoint_id)
        self.assertEqual(response.model_id, fixture.request.model_id)
        self.assertEqual(
            response.processing.endpoint_descriptor_digest,
            fixture.request.endpoint_descriptor_digest,
        )
        self.assertEqual(fixture.underlying_call_count(), 1)

    async def test_conformance_health_binds_descriptor_and_close_is_idempotent(
        self,
    ) -> None:
        fixture = self.make_provider_fixture()
        health = await fixture.provider.health(call=fixture.call)
        descriptor = fixture.provider.descriptor
        self.assertEqual(health.provider_id, descriptor.provider_id)
        self.assertEqual(
            tuple(item.endpoint_id for item in health.endpoints),
            tuple(item.endpoint_id for item in descriptor.endpoints),
        )
        await fixture.provider.close()
        await fixture.provider.close()

    async def test_conformance_pre_cancel_and_deadline_make_no_underlying_call(
        self,
    ) -> None:
        cancelled = self.make_provider_fixture()
        token = ManualCancellationToken()
        token.cancel()
        with self.assertRaises(ModelProviderError):
            await cancelled.provider.generate(
                cancelled.request,
                call=replace(cancelled.call, cancellation=token),
            )
        self.assertEqual(cancelled.underlying_call_count(), 0)

        expired = self.make_provider_fixture()
        with self.assertRaises(ModelProviderError):
            await expired.provider.generate(
                expired.request,
                call=replace(expired.call, deadline=NOW - timedelta(seconds=1)),
            )
        self.assertEqual(expired.underlying_call_count(), 0)

    async def test_conformance_identity_drift_fails_before_underlying_call(
        self,
    ) -> None:
        fixture = self.make_provider_fixture()
        with self.assertRaises(ModelProviderError):
            await fixture.provider.generate(
                replace(fixture.request, model_id="wrong-model"),
                call=fixture.call,
            )
        self.assertEqual(fixture.underlying_call_count(), 0)

    async def test_conformance_idempotency_replays_and_conflicts_are_local(
        self,
    ) -> None:
        fixture = self.make_provider_fixture()
        first = await fixture.provider.generate(fixture.request, call=fixture.call)
        duplicate = await fixture.provider.generate(fixture.request, call=fixture.call)
        self.assertEqual(first, duplicate)
        self.assertEqual(fixture.underlying_call_count(), 1)

        with self.assertRaises(ModelProviderError):
            await fixture.provider.generate(
                replace(fixture.request, request_id="idempotency-conflict"),
                call=fixture.call,
            )
        self.assertEqual(fixture.underlying_call_count(), 1)
