from __future__ import annotations

import unittest

from dududa.testing.models import ProviderSuccess, RecordingFakeModelProvider

from .model_provider_conformance import (
    ModelProviderConformanceMixin,
    ProviderConformanceFixture,
)
from .model_provider_fixtures import (
    compatible_descriptor,
    compatible_provider_request,
    provider_call,
)
from tests.unit.models.helpers import NOW


class RecordingModelProviderContractTests(
    ModelProviderConformanceMixin,
    unittest.IsolatedAsyncioTestCase,
):
    def make_provider_fixture(self) -> ProviderConformanceFixture:
        descriptor = compatible_descriptor()
        provider = RecordingFakeModelProvider(
            descriptor,
            (ProviderSuccess("ok"),),
            clock=lambda: NOW,
        )
        return ProviderConformanceFixture(
            provider=provider,
            request=compatible_provider_request(descriptor),
            call=provider_call(),
            underlying_call_count=lambda: len(provider.calls),
        )


if __name__ == "__main__":
    unittest.main()
