from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
import itertools
import unittest

from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.errors import DududaError, ErrorCategory
from dududa.models.admission import InMemoryModelAdmissionController
from dududa.models.contracts import (
    ModelProviderDescriptor,
    ModelRole,
    ModelTier,
)
from dududa.models.estimation import (
    ConservativeModelInvocationEstimator,
    ModelTokenPricing,
)
from dududa.models.digests import model_request_fingerprint
from dududa.models.policy import BootstrapTierPolicyDefinition
from dududa.models.registry import (
    InMemoryModelOperationalStateRegistry,
    InMemoryModelRoutingRegistry,
)
from dududa.models.router import StaticModelRouter
from dududa.models.tiering import FixedPerceptionBootstrapTierPolicy
from dududa.perception.contracts import PerceptionModelStatus
from dududa.perception.merge import (
    DeterministicPerceptionMerger,
    PerceptionMergeConfig,
)
from dududa.perception.rules import (
    DeterministicRulePerception,
    default_rule_perception_config,
)
from dududa.perception.schema import (
    model_projection_schema,
    model_projection_schema_ref,
)
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
)
from dududa.runtime.perception import (
    HybridPerceptionEngine,
    RouterBackedModelPerception,
    RouterBackedModelPerceptionConfig,
    serialize_perception_context,
)
from dududa.testing.models import ProviderSuccess, RecordingFakeModelProvider
from plugins.astrbot_plugin_dududa_core.adapters.model_codec import (
    JsonSchemaDocumentRegistry,
    JsonSchemaOutputCodec,
)

from tests.unit.models.helpers import NOW as ROUTER_NOW, endpoint
from tests.unit.models.test_router import _operational, _policy
from tests.unit.perception.helpers import context, limits, model_payload, revision


class _RecordingRouter:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls = []

    async def invoke(self, request, tier_authority, *, call):
        self.calls.append((request, tier_authority, call))
        return await self.inner.invoke(request, tier_authority, call=call)


class _BlockingProvider:
    def __init__(self, descriptor) -> None:
        self._descriptor = descriptor
        self.calls = []
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    @property
    def descriptor(self):
        return self._descriptor

    async def generate(self, request, *, call):
        self.calls.append((request, call))
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def health(self, *, call):  # pragma: no cover
        raise AssertionError("not invoked")

    async def close(self) -> None:
        return None


class _RuntimePerceptionFixture:
    def __init__(self, outcomes, *, provider_factory=None) -> None:
        self.limits = limits()
        self.schema = model_projection_schema(self.limits)
        self.schema_ref = model_projection_schema_ref(self.limits)
        descriptor = endpoint(
            "perception-haiku",
            ModelTier.HAIKU,
            default_profile_id="quick",
        )
        provider_descriptor = ModelProviderDescriptor(
            schema_version=1,
            provider_id="provider-a",
            revision=revision("provider-a"),
            endpoints=(descriptor,),
        )
        self.provider = (
            provider_factory(provider_descriptor)
            if provider_factory is not None
            else RecordingFakeModelProvider(
                provider_descriptor,
                outcomes,
                clock=lambda: ROUTER_NOW,
            )
        )
        ids = (f"router-{index}" for index in itertools.count(1))
        routing = InMemoryModelRoutingRegistry(
            (self.provider,),
            (
                _policy(
                    ModelRole.PERCEPTION,
                    (descriptor,),
                    schema=True,
                    profile="quick",
                ),
            ),
            clock=lambda: ROUTER_NOW,
            id_factory=lambda: next(ids),
        )
        operational = InMemoryModelOperationalStateRegistry(
            routing,
            _operational((descriptor,)),
            clock=lambda: ROUTER_NOW,
        )
        admission = InMemoryModelAdmissionController(
            routing,
            operational,
            admission_revision="admission-v1",
            clock=lambda: ROUTER_NOW,
            id_factory=lambda: next(ids),
        )
        schema_registry = JsonSchemaDocumentRegistry({self.schema_ref: self.schema})
        codec = JsonSchemaOutputCodec(
            schema_registry,
            revision=revision("json-schema-codec"),
        )
        estimator = ConservativeModelInvocationEstimator(
            revision=revision("model-estimator"),
            role_prompt_tokens={ModelRole.PERCEPTION: 16},
            provider_wrapping_tokens={descriptor.descriptor_digest: 8},
            schema_tokens={
                self.schema_ref.digest: schema_registry.token_upper_bound(
                    self.schema_ref
                )
            },
            pricing={
                descriptor.descriptor_digest: ModelTokenPricing(
                    1,
                    Decimal("1"),
                    Decimal("2"),
                )
            },
        )
        static_router = StaticModelRouter(
            routing,
            operational,
            admission,
            estimator,
            output_codec=codec,
            prompt_template_revisions={
                ModelRole.PERCEPTION: revision("perception-prompt")
            },
            schema_repair_prompt_revisions={
                ModelRole.PERCEPTION: revision("perception-repair-prompt")
            },
            clock=lambda: ROUTER_NOW,
            id_factory=lambda: next(ids),
        )
        self.router = _RecordingRouter(static_router)
        bootstrap_definition = BootstrapTierPolicyDefinition(
            1,
            "perception-bootstrap",
            ModelRole.PERCEPTION,
            ModelTier.HAIKU,
            "perception-bootstrap-v1",
            ("fixed_perception_haiku",),
        )
        perception_ids = (f"perception-{index}" for index in itertools.count(1))
        model = RouterBackedModelPerception(
            self.router,
            FixedPerceptionBootstrapTierPolicy(id_factory=lambda: next(perception_ids)),
            RouterBackedModelPerceptionConfig(
                component_revision=revision("model-perception"),
                limits=self.limits,
                bootstrap_policy=bootstrap_definition,
                reasoning_profile_id="quick",
                max_output_tokens=1_024,
                prompt_tokens_upper_bound=256,
                allow_external_provider=True,
                allowed_residencies=frozenset({"global"}),
                allow_provider_retention=False,
            ),
            clock=lambda: ROUTER_NOW,
            id_factory=lambda: next(perception_ids),
        )
        rules = DeterministicRulePerception(
            default_rule_perception_config(revision("rule-perception")),
            id_factory=lambda: "rule-result",
        )
        merger = DeterministicPerceptionMerger(
            PerceptionMergeConfig(
                revision("perception-pipeline"),
                revision("perception-merger"),
                revision("perception-validator"),
                0.59,
                0.59,
            ),
            id_factory=lambda: "perception-result",
        )
        self.rules = rules
        self.merger = merger
        self.model = model
        self.engine = HybridPerceptionEngine(
            rules,
            model,
            merger,
            clock=lambda: ROUTER_NOW,
        )
        self.call = PortCallContext(
            run_id="run-1",
            trace=TraceContext("trace-1"),
            deadline=ROUTER_NOW + timedelta(seconds=30),
            cancellation=NeverCancelled(),
            budget=RuntimeBudget(4, 0, 3, 100_000, 100_000, Decimal("100")),
            policy_snapshot_id="policy-v1",
        )


class RouterBackedModelPerceptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_static_router_is_fixed_haiku_and_has_no_route_hint(
        self,
    ) -> None:
        fixture = _RuntimePerceptionFixture((ProviderSuccess(model_payload()),))

        result = await fixture.engine.perceive(context(), call=fixture.call)

        self.assertIs(result.model_status, PerceptionModelStatus.VALID)
        self.assertEqual(len(fixture.router.calls), 1)
        request, authority, _ = fixture.router.calls[0]
        self.assertIs(request.role, ModelRole.PERCEPTION)
        self.assertIsNone(request.route_hint)
        self.assertEqual(request.reasoning_profile_id, "quick")
        self.assertEqual(request.output_schema, fixture.schema_ref)
        self.assertEqual(request.idempotency_key, model_request_fingerprint(request))
        self.assertIs(authority.selected_tier, ModelTier.HAIKU)
        self.assertEqual(len(fixture.provider.calls), 1)
        self.assertIs(
            fixture.provider.calls[0][0].selected_tier,
            ModelTier.HAIKU,
        )

    async def test_context_serializer_is_an_explicit_safe_projection(self) -> None:
        serialized = serialize_perception_context(context()).decode("utf-8")

        self.assertIn("message:current", serialized)
        self.assertIn("identity:user", serialized)
        for forbidden in (
            "context-1",
            "scope-digest",
            "data_classification",
            "authorization",
            "provider_id",
            "roles",
        ):
            self.assertNotIn(forbidden, serialized)

    async def test_semantically_unknown_reference_discards_whole_model_result(
        self,
    ) -> None:
        payload = model_payload(target_identity_refs=["identity:outside"])
        fixture = _RuntimePerceptionFixture((ProviderSuccess(payload),))

        result = await fixture.engine.perceive(context(), call=fixture.call)

        self.assertIs(result.model_status, PerceptionModelStatus.INVALID)
        self.assertIsNone(result.model_projection_digest)
        self.assertEqual(result.confidence, 0.59)
        self.assertEqual(len(fixture.provider.calls), 1)

    async def test_schema_invalid_output_repairs_once_then_falls_back(self) -> None:
        invalid = model_payload(tier="opus")
        fixture = _RuntimePerceptionFixture(
            (ProviderSuccess(invalid), ProviderSuccess(invalid))
        )

        result = await fixture.engine.perceive(context(), call=fixture.call)

        self.assertIs(result.model_status, PerceptionModelStatus.INVALID)
        self.assertEqual(result.confidence, 0.59)
        self.assertEqual(len(fixture.provider.calls), 2)

    async def test_pre_cancelled_call_does_not_become_rule_fallback(self) -> None:
        fixture = _RuntimePerceptionFixture((ProviderSuccess(model_payload()),))
        token = ManualCancellationToken()
        token.cancel()
        call = PortCallContext(
            run_id=fixture.call.run_id,
            trace=fixture.call.trace,
            deadline=fixture.call.deadline,
            cancellation=token,
            budget=fixture.call.budget,
            policy_snapshot_id=fixture.call.policy_snapshot_id,
        )

        with self.assertRaises(DududaError) as captured:
            await fixture.engine.perceive(context(), call=call)

        self.assertIs(captured.exception.info.category, ErrorCategory.CANCELLED)
        self.assertEqual(fixture.provider.calls, [])

    async def test_router_cancellation_is_propagated_not_rule_fallback(self) -> None:
        fixture = _RuntimePerceptionFixture(
            (),
            provider_factory=_BlockingProvider,
        )
        token = ManualCancellationToken()
        call = PortCallContext(
            run_id=fixture.call.run_id,
            trace=fixture.call.trace,
            deadline=fixture.call.deadline,
            cancellation=token,
            budget=fixture.call.budget,
            policy_snapshot_id=fixture.call.policy_snapshot_id,
        )
        task = asyncio.create_task(fixture.engine.perceive(context(), call=call))
        await fixture.provider.started.wait()
        token.cancel()

        with self.assertRaises(DududaError) as captured:
            await task

        self.assertIs(captured.exception.info.category, ErrorCategory.CANCELLED)
        self.assertTrue(fixture.provider.cancelled.is_set())

    async def test_deadline_crossed_after_model_return_is_propagated(self) -> None:
        fixture = _RuntimePerceptionFixture((ProviderSuccess(model_payload()),))
        value = context()
        projection = await fixture.model.perceive(value, call=fixture.call)
        clock = [ROUTER_NOW]

        class DeadlineCrossingModel:
            async def perceive(self, context, *, call):
                clock[0] = call.deadline
                return projection

        engine = HybridPerceptionEngine(
            fixture.rules,
            DeadlineCrossingModel(),
            fixture.merger,
            clock=lambda: clock[0],
        )

        with self.assertRaises(DududaError) as captured:
            await engine.perceive(value, call=fixture.call)

        self.assertIs(captured.exception.info.category, ErrorCategory.TIMEOUT)


if __name__ == "__main__":
    unittest.main()
