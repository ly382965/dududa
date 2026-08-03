from __future__ import annotations

import unittest
from inspect import Parameter, signature

from dududa.models.contracts import RouteHint
from dududa.ports.models import (
    BootstrapModelTierPolicy,
    ModelAdmissionController,
    ModelCatalogPublisher,
    ModelInvocationEstimator,
    ModelOperationalStateRegistry,
    ModelOutputCodec,
    ModelProvider,
    ModelRouter,
    ModelRoutingRegistry,
    ModelTierPolicy,
)
from dududa.runtime import state as runtime_state
from dududa.runtime.state import RuntimeInvocationOptions


class _Router:
    async def invoke(self, request, tier_authority, *, call):
        raise NotImplementedError


class _Provider:
    @property
    def descriptor(self):
        return object()

    async def generate(self, request, *, call):
        raise NotImplementedError

    async def health(self, *, call):
        raise NotImplementedError

    async def close(self):
        return None


class _Registry:
    def acquire_snapshot(self):
        raise NotImplementedError

    def resolve_provider(self, snapshot, provider_id, expected_revision):
        raise NotImplementedError

    def list_enabled(self, snapshot):
        return ()

    def policy_for(self, snapshot, role):
        raise NotImplementedError


class _Publisher:
    async def publish(self, update, *, call):
        raise NotImplementedError


class _OperationalState:
    def acquire_snapshot(self):
        raise NotImplementedError


class _Admission:
    async def reserve(self, request, *, call):
        raise NotImplementedError

    async def settle(self, lease, usage, *, call):
        raise NotImplementedError

    async def release(self, lease, *, call):
        raise NotImplementedError


class _Codec:
    @property
    def revision(self):
        return object()

    def validate(self, output, schema):
        return output


class _Estimator:
    def estimate(self, request, endpoint, reasoning_profile):
        raise NotImplementedError


class _TierPolicy:
    def decide(self, context, definition, *, now):
        raise NotImplementedError


class _BootstrapTierPolicy:
    def decide(self, definition, *, now=None):
        raise NotImplementedError


class ModelPortContractTests(unittest.TestCase):
    def test_minimal_implementations_structurally_conform(self) -> None:
        implementations = (
            (_Router(), ModelRouter),
            (_Provider(), ModelProvider),
            (_Registry(), ModelRoutingRegistry),
            (_Publisher(), ModelCatalogPublisher),
            (_OperationalState(), ModelOperationalStateRegistry),
            (_Admission(), ModelAdmissionController),
            (_Codec(), ModelOutputCodec),
            (_Estimator(), ModelInvocationEstimator),
            (_TierPolicy(), ModelTierPolicy),
            (_BootstrapTierPolicy(), BootstrapModelTierPolicy),
        )
        for implementation, protocol in implementations:
            with self.subTest(protocol=protocol.__name__):
                self.assertIsInstance(implementation, protocol)

    def test_execution_port_fixtures_match_required_call_shapes(self) -> None:
        expected = (
            (_Router.invoke, ("self", "request", "tier_authority", "call")),
            (
                _Registry.resolve_provider,
                ("self", "snapshot", "provider_id", "expected_revision"),
            ),
            (_Admission.settle, ("self", "lease", "usage", "call")),
        )
        for method, names in expected:
            with self.subTest(method=method.__qualname__):
                parameters = signature(method).parameters
                self.assertEqual(tuple(parameters), names)
                if "call" in parameters:
                    self.assertIs(parameters["call"].kind, Parameter.KEYWORD_ONLY)

    def test_runtime_uses_the_shared_route_hint_contract(self) -> None:
        hint = RouteHint(
            schema_version=1,
            provider_id="provider-a",
            endpoint_id="endpoint-a",
            model_id=None,
        )
        options = RuntimeInvocationOptions(
            schema_version=1,
            route_hint=hint,
            entrypoint_id="offline-test",
            feature_flags={},
            feature_flag_revision="flags-v1",
        )

        self.assertIs(runtime_state.RouteHint, RouteHint)
        self.assertIs(options.route_hint, hint)


if __name__ == "__main__":
    unittest.main()
