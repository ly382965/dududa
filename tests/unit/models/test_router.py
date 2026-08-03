from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import itertools
import time
import unittest

from dududa.contracts.canonical import canonical_json_bytes, canonical_schema_digest
from dududa.domain.primitives import (
    DigestString,
    PrivacyLevel,
    RuntimeBudget,
    SchemaRef,
    TraceContext,
)
from dududa.models.admission import InMemoryModelAdmissionController
from dududa.models.contracts import (
    AdmissionDisposition,
    EndpointHealthStatus,
    EndpointLoadSnapshot,
    LoadCounterScope,
    ModelEndpointHealth,
    ModelEndpointRef,
    ModelFailureKind,
    ModelInput,
    ModelInputModality,
    ModelInputPart,
    ModelOperationalSnapshot,
    ModelOutputModality,
    ModelPrivacyPolicy,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRequest,
    ModelRole,
    ModelTier,
    RouteAttemptKind,
    RouteHint,
    SafetyAnnotation,
    StructuredOutputSupport,
)
from dududa.models.digests import (
    bootstrap_tier_selection_fingerprint,
    model_endpoint_descriptor_digest,
    route_decision_digest,
)
from dududa.errors import ErrorCategory, ErrorInfo
from dududa.models.errors import ModelInvocationError
from dududa.models.estimation import (
    ConservativeModelInvocationEstimator,
    ModelTokenPricing,
)
from dududa.models.policy import (
    BootstrapTierDecision,
    ConfidenceHandling,
    ModelCapabilitiesRequirement,
    ModelFallbackPolicy,
    ModelRoutePolicy,
    TierDecision,
    TierFallbackEdge,
)
from dududa.models.registry import (
    InMemoryModelOperationalStateRegistry,
    InMemoryModelRoutingRegistry,
)
from dududa.models.router import StaticModelRouter, _cancel_provider_task
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
)
from dududa.testing.models import (
    ProviderSuccess,
    RecordingFakeModelProvider,
    provider_failure,
)
from plugins.astrbot_plugin_dududa_core.adapters.model_codec import (
    JsonSchemaDocumentRegistry,
    JsonSchemaOutputCodec,
)

from .helpers import NOW, endpoint, revision


PERCEPTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "intent"],
    "properties": {
        "schema_version": {"const": 1},
        "intent": {"type": "string", "minLength": 1},
    },
}
PERCEPTION_SCHEMA_REF = SchemaRef(
    schema_id="perception-result",
    schema_version=1,
    digest=canonical_schema_digest(
        PERCEPTION_SCHEMA,
        schema_id="perception-result",
        schema_version=1,
    ),
)


def _ref(descriptor, priority: int) -> ModelEndpointRef:
    return ModelEndpointRef(
        schema_version=1,
        provider_id="provider-a",
        endpoint_id=descriptor.endpoint_id,
        model_id=descriptor.model_id,
        endpoint_descriptor_digest=descriptor.descriptor_digest,
        tier=descriptor.tier,
        priority=priority,
    )


def _policy(
    role: ModelRole,
    descriptors,
    *,
    schema: bool,
    profile: str,
    fallback_edges=(),
) -> ModelRoutePolicy:
    tiers = frozenset(item.tier for item in descriptors)
    default_tier = ModelTier.HAIKU if role is ModelRole.PERCEPTION else ModelTier.SONNET
    return ModelRoutePolicy(
        schema_version=1,
        policy_id=f"route-{role.value}",
        role=role,
        default_tier=default_tier,
        allowed_tiers=tiers,
        candidate_endpoints=tuple(
            _ref(item, index * 10) for index, item in enumerate(descriptors, 1)
        ),
        requirements=ModelCapabilitiesRequirement(
            schema_version=1,
            input_modalities=frozenset({ModelInputModality.TEXT}),
            output_modalities=frozenset({ModelOutputModality.TEXT}),
            minimum_native_structured_output=StructuredOutputSupport.NONE,
            requires_schema_validation=schema,
            minimum_context_tokens=1_024,
            minimum_output_tokens=64,
            reasoning_profile_id=profile,
        ),
        allowed_data_classes=frozenset(
            {PrivacyLevel.PUBLIC, PrivacyLevel.CONVERSATION}
        ),
        fallback=ModelFallbackPolicy(
            schema_version=1,
            max_retries_per_endpoint=1,
            max_same_tier_failovers=2,
            max_tier_hops=1,
            max_total_attempts=6,
            max_schema_repairs=1,
            retryable_failure_kinds=frozenset(
                {
                    ModelFailureKind.TRANSIENT_NETWORK,
                    ModelFailureKind.TIMEOUT,
                    ModelFailureKind.RATE_LIMITED,
                    ModelFailureKind.PROVIDER_UNAVAILABLE,
                }
            ),
            deterministic_fallback_id=f"{role.value}-unavailable",
        ),
        tier_fallback_edges=tuple(fallback_edges),
        policy_revision=f"route-{role.value}-v1",
    )


def _operational(descriptors) -> ModelOperationalSnapshot:
    health = ModelProviderHealth(
        schema_version=1,
        provider_id="provider-a",
        status=EndpointHealthStatus.HEALTHY,
        endpoints=tuple(
            ModelEndpointHealth(
                schema_version=1,
                endpoint_id=item.endpoint_id,
                endpoint_descriptor_digest=item.descriptor_digest,
                status=EndpointHealthStatus.HEALTHY,
                reason_codes=(),
            )
            for item in descriptors
        ),
        snapshot_revision="health-v1",
        checked_at=NOW,
        reason_codes=(),
    )
    loads = tuple(
        EndpointLoadSnapshot(
            schema_version=1,
            provider_id="provider-a",
            endpoint_id=item.endpoint_id,
            endpoint_descriptor_digest=item.descriptor_digest,
            quota_pool_id=item.quota_pool_id,
            traffic_policy_id=item.traffic_policy.policy_id,
            traffic_policy_revision=item.traffic_policy.policy_revision,
            counter_scope=LoadCounterScope.EXTERNAL_TO_ADMISSION_CONTROLLER,
            in_flight=0,
            requests_per_minute=0,
            tokens_per_minute=0,
            queue_depth=0,
            p95_latency_ms=10,
            rate_429=0,
            error_rate=0,
            sample_count=item.traffic_policy.minimum_samples,
            cooldown_until=None,
            checked_at=NOW,
            snapshot_revision=f"load:{item.endpoint_id}",
        )
        for item in descriptors
    )
    return ModelOperationalSnapshot(
        schema_version=1,
        snapshot_id="operational-v1",
        provider_health=(health,),
        endpoint_load=loads,
        acquired_at=NOW,
    )


def _request(
    role: ModelRole,
    *,
    request_id: str,
    schema: SchemaRef | None = None,
    profile: str = "balanced",
    hint: RouteHint | None = None,
    idempotency_key: str | None = "idem-1",
) -> ModelRequest:
    return ModelRequest(
        schema_version=1,
        request_id=request_id,
        role=role,
        input=ModelInput(
            schema_version=1,
            parts=(
                ModelInputPart(
                    schema_version=1,
                    part_id="part-1",
                    modality=ModelInputModality.TEXT,
                    text="hello",
                    content_ref=None,
                    content_digest=None,
                    media_type=None,
                ),
            ),
            source_refs=("message:m1",),
        ),
        output_schema=schema,
        max_output_tokens=128,
        content_input_tokens_upper_bound=32,
        temperature=0,
        privacy=ModelPrivacyPolicy(
            schema_version=1,
            data_classification=PrivacyLevel.CONVERSATION,
            allow_external_provider=True,
            allowed_residencies=frozenset({"global"}),
            allow_provider_retention=False,
        ),
        reasoning_profile_id=profile,
        random_seed=None,
        idempotency_key=idempotency_key,
        route_hint=hint,
    )


def _tier_decision(tier: ModelTier, *, decision_id: str = "tier-1") -> TierDecision:
    return TierDecision(
        schema_version=1,
        decision_id=decision_id,
        role=ModelRole.DIRECT_CHAT,
        selected_tier=tier,
        uncapped_tier=tier,
        assessment_digest=DigestString("assessment-digest"),
        selection_context_digest=DigestString("selection-context-digest"),
        selection_fingerprint=DigestString("tier-selection-plan"),
        tier_policy_digest=DigestString("tier-policy-digest"),
        policy_revision="tier-policy-v1",
        confidence_handling=ConfidenceHandling.DIRECT,
        reason_codes=("deterministic_test_tier",),
        decided_at=NOW,
    )


def _bootstrap() -> BootstrapTierDecision:
    policy_digest = DigestString("bootstrap-policy-digest")
    reasons = ("fixed_perception_bootstrap",)
    fingerprint = bootstrap_tier_selection_fingerprint(
        role=ModelRole.PERCEPTION,
        selected_tier=ModelTier.HAIKU,
        tier_policy_digest=policy_digest,
        policy_revision="bootstrap-v1",
        reason_codes=reasons,
    )
    return BootstrapTierDecision(
        schema_version=1,
        decision_id="bootstrap-1",
        role=ModelRole.PERCEPTION,
        selected_tier=ModelTier.HAIKU,
        selection_fingerprint=fingerprint,
        tier_policy_digest=policy_digest,
        policy_revision="bootstrap-v1",
        reason_codes=reasons,
        decided_at=NOW,
    )


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


class _InvalidResponseProvider:
    def __init__(self, descriptor) -> None:
        self._descriptor = descriptor
        self.calls = []

    @property
    def descriptor(self):
        return self._descriptor

    async def generate(self, request, *, call):
        self.calls.append((request, call))
        return object()

    async def health(self, *, call):  # pragma: no cover
        raise AssertionError("not invoked")

    async def close(self) -> None:
        return None


class _SynchronousFailureProvider(_InvalidResponseProvider):
    def generate(self, request, *, call):
        self.calls.append((request, call))
        raise RuntimeError("synchronous provider secret")


class _AsyncFailureProvider(_InvalidResponseProvider):
    async def generate(self, request, *, call):
        self.calls.append((request, call))
        raise RuntimeError("asynchronous provider secret")


class _StubbornProvider(_InvalidResponseProvider):
    def __init__(self, descriptor) -> None:
        super().__init__(descriptor)
        self.started = asyncio.Event()
        self.cancelled_once = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()

    async def generate(self, request, *, call):
        self.calls.append((request, call))
        self.started.set()
        try:
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancelled_once.set()
            return object()
        finally:
            self.finished.set()


class _ForgedResponseProvider(RecordingFakeModelProvider):
    def __init__(self, descriptor, field: str, *, clock) -> None:
        super().__init__(descriptor, (ProviderSuccess("forged"),), clock=clock)
        self._field = field

    async def generate(self, request, *, call):
        response = await super().generate(request, call=call)
        object.__setattr__(response, self._field, object())
        return response


class RouterFixture:
    def __init__(
        self,
        descriptors,
        policies,
        outcomes,
        *,
        provider_factory=None,
        clock=None,
        operational_factory=None,
        prompt_revisions=None,
        repair_revisions=None,
        id_prefix="id",
        provider_wrapping_tokens=4,
    ) -> None:
        self.clock = clock or (lambda: NOW)
        provider_descriptor = ModelProviderDescriptor(
            schema_version=1,
            provider_id="provider-a",
            revision=revision("provider-a"),
            endpoints=tuple(descriptors),
        )
        self.provider = (
            provider_factory(provider_descriptor)
            if provider_factory is not None
            else RecordingFakeModelProvider(
                provider_descriptor,
                outcomes,
                clock=self.clock,
            )
        )
        ids = (f"{id_prefix}-{index}" for index in itertools.count(1))
        self.routing = InMemoryModelRoutingRegistry(
            (self.provider,),
            tuple(policies),
            clock=self.clock,
            id_factory=lambda: next(ids),
        )
        self.operational_snapshot = (
            operational_factory(descriptors)
            if operational_factory is not None
            else _operational(descriptors)
        )
        self.operational = InMemoryModelOperationalStateRegistry(
            self.routing,
            self.operational_snapshot,
            clock=self.clock,
        )
        self.admission = InMemoryModelAdmissionController(
            self.routing,
            self.operational,
            admission_revision="admission-v1",
            clock=self.clock,
            id_factory=lambda: next(ids),
        )
        schema_registry = JsonSchemaDocumentRegistry(
            {PERCEPTION_SCHEMA_REF: PERCEPTION_SCHEMA}
        )
        codec = JsonSchemaOutputCodec(
            schema_registry,
            revision=revision("json-schema-codec"),
        )
        estimator = ConservativeModelInvocationEstimator(
            revision=revision("model-estimator"),
            role_prompt_tokens={
                ModelRole.DIRECT_CHAT: 8,
                ModelRole.PERCEPTION: 12,
            },
            provider_wrapping_tokens={
                item.descriptor_digest: provider_wrapping_tokens for item in descriptors
            },
            schema_tokens={
                PERCEPTION_SCHEMA_REF.digest: schema_registry.token_upper_bound(
                    PERCEPTION_SCHEMA_REF
                )
            },
            pricing={
                item.descriptor_digest: ModelTokenPricing(
                    schema_version=1,
                    input_cost_per_million=Decimal(1),
                    generated_cost_per_million=Decimal(2),
                )
                for item in descriptors
            },
        )
        if prompt_revisions is None:
            prompt_revisions = {
                ModelRole.DIRECT_CHAT: revision("direct-chat-prompt"),
                ModelRole.PERCEPTION: revision("perception-prompt"),
            }
        self.router = StaticModelRouter(
            self.routing,
            self.operational,
            self.admission,
            estimator,
            output_codec=codec,
            prompt_template_revisions=prompt_revisions,
            schema_repair_prompt_revisions=(
                repair_revisions
                if repair_revisions is not None
                else {ModelRole.PERCEPTION: revision("perception-repair-prompt")}
            ),
            clock=self.clock,
            id_factory=lambda: next(ids),
        )
        self.call = PortCallContext(
            run_id="run-1",
            trace=TraceContext("trace-router"),
            deadline=NOW + timedelta(seconds=30),
            cancellation=NeverCancelled(),
            budget=RuntimeBudget(
                model_calls_remaining=10,
                tool_steps_remaining=0,
                retries_remaining=9,
                input_tokens_remaining=100_000,
                output_tokens_remaining=100_000,
                cost_units_remaining=Decimal(100),
            ),
            policy_snapshot_id="policy-v1",
        )


class StaticRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_primary_success_and_plan_fingerprint_ignore_correlation_ids(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT, (sonnet,), schema=False, profile="balanced"
                ),
            ),
            (ProviderSuccess("first"), ProviderSuccess("second")),
        )
        first = await fixture.router.invoke(
            _request(
                ModelRole.DIRECT_CHAT,
                request_id="request-1",
                idempotency_key="idem-request-1",
            ),
            _tier_decision(ModelTier.SONNET, decision_id="tier-1"),
            call=fixture.call,
        )
        second = await fixture.router.invoke(
            _request(
                ModelRole.DIRECT_CHAT,
                request_id="request-2",
                idempotency_key="idem-request-2",
            ),
            _tier_decision(ModelTier.SONNET, decision_id="tier-2"),
            call=fixture.call,
        )

        self.assertEqual(first.output, "first")
        self.assertEqual(len(first.route_decision.attempts), 1)
        self.assertEqual(
            first.route_decision.route_plan_fingerprint,
            second.route_decision.route_plan_fingerprint,
        )
        self.assertNotEqual(
            route_decision_digest(first.route_decision),
            route_decision_digest(second.route_decision),
        )

    async def test_hint_only_reorders_eligible_endpoint_in_selected_tier(self) -> None:
        first = endpoint("sonnet-a", ModelTier.SONNET)
        second = endpoint("sonnet-b", ModelTier.SONNET)
        fixture = RouterFixture(
            (first, second),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (first, second),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (ProviderSuccess("hinted"),),
        )
        request = _request(
            ModelRole.DIRECT_CHAT,
            request_id="request-hint",
            hint=RouteHint(
                schema_version=1,
                provider_id="provider-a",
                endpoint_id="sonnet-b",
                model_id=None,
            ),
        )
        response = await fixture.router.invoke(
            request,
            _tier_decision(ModelTier.SONNET),
            call=fixture.call,
        )
        self.assertEqual(
            response.route_decision.planned_endpoint.endpoint_id,  # type: ignore[union-attr]
            "sonnet-b",
        )

    async def test_retry_failover_and_explicit_cross_tier_fallback(self) -> None:
        sonnet_a = endpoint("sonnet-a", ModelTier.SONNET)
        sonnet_b = endpoint("sonnet-b", ModelTier.SONNET)
        haiku = endpoint("haiku-a", ModelTier.HAIKU)
        edge = TierFallbackEdge(
            schema_version=1,
            from_tier=ModelTier.SONNET,
            to_tier=ModelTier.HAIKU,
            failure_kinds=frozenset({ModelFailureKind.RATE_LIMITED}),
        )
        fixture = RouterFixture(
            (sonnet_a, sonnet_b, haiku),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet_a, sonnet_b, haiku),
                    schema=False,
                    profile="balanced",
                    fallback_edges=(edge,),
                ),
            ),
            (
                provider_failure(ModelFailureKind.TIMEOUT, "timeout-1"),
                provider_failure(ModelFailureKind.TIMEOUT, "timeout-2"),
                provider_failure(ModelFailureKind.RATE_LIMITED, "rate-limited"),
                provider_failure(
                    ModelFailureKind.RATE_LIMITED,
                    "rate-limited-retry",
                ),
                ProviderSuccess("fallback-success"),
            ),
        )
        response = await fixture.router.invoke(
            _request(ModelRole.DIRECT_CHAT, request_id="request-reliability"),
            _tier_decision(ModelTier.SONNET),
            call=fixture.call,
        )
        self.assertEqual(response.output, "fallback-success")
        self.assertEqual(
            tuple(item.kind for item in response.route_decision.attempts),
            (
                RouteAttemptKind.PRIMARY,
                RouteAttemptKind.ENDPOINT_RETRY,
                RouteAttemptKind.SAME_TIER_FAILOVER,
                RouteAttemptKind.ENDPOINT_RETRY,
                RouteAttemptKind.CROSS_TIER_FALLBACK,
            ),
        )
        self.assertEqual(response.route_decision.selected_tier, ModelTier.HAIKU)

    async def test_authentication_failure_stops_without_retry(self) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT, (sonnet,), schema=False, profile="balanced"
                ),
            ),
            (
                provider_failure(
                    ModelFailureKind.AUTHENTICATION,
                    "credential_rejected",
                ),
            ),
        )
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-auth"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        self.assertEqual(
            captured.exception.failure_kind, ModelFailureKind.AUTHENTICATION
        )
        self.assertEqual(len(fixture.provider.calls), 1)
        self.assertEqual(len(captured.exception.route_decision.attempts), 1)

    async def test_provider_invalid_request_stops_without_retry_or_failover(
        self,
    ) -> None:
        first = endpoint("sonnet-a", ModelTier.SONNET)
        second = endpoint("sonnet-b", ModelTier.SONNET)
        fixture = RouterFixture(
            (first, second),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (first, second),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (
                provider_failure(
                    ModelFailureKind.INVALID_REQUEST,
                    "provider_rejected_request",
                ),
                ProviderSuccess("must-not-run"),
            ),
        )

        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-invalid-provider"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )

        self.assertEqual(
            captured.exception.failure_kind,
            ModelFailureKind.INVALID_REQUEST,
        )
        self.assertEqual(len(fixture.provider.calls), 1)
        self.assertEqual(len(captured.exception.route_decision.attempts), 1)
        self.assertEqual(
            captured.exception.route_decision.attempts[0].failure_kind,
            ModelFailureKind.INVALID_REQUEST,
        )
        state = fixture.admission._states[first.quota_pool_id]
        self.assertEqual(state.active, {})

    async def test_provider_errors_are_normalized_and_unknown_exits_settle(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet,),
            schema=False,
            profile="balanced",
        )
        for provider_factory in (
            _SynchronousFailureProvider,
            _AsyncFailureProvider,
        ):
            with self.subTest(provider=provider_factory.__name__):
                fixture = RouterFixture(
                    (sonnet,),
                    (policy,),
                    (),
                    provider_factory=provider_factory,
                )
                with self.assertRaises(ModelInvocationError) as captured:
                    await fixture.router.invoke(
                        _request(
                            ModelRole.DIRECT_CHAT,
                            request_id=f"request-{provider_factory.__name__}",
                        ),
                        _tier_decision(ModelTier.SONNET),
                        call=fixture.call,
                    )

                self.assertEqual(
                    captured.exception.failure_kind,
                    ModelFailureKind.INTERNAL,
                )
                self.assertTrue(captured.exception.info.outcome_unknown)
                self.assertEqual(len(fixture.provider.calls), 1)
                state = fixture.admission._states[sonnet.quota_pool_id]
                self.assertEqual(state.active, {})
                receipt = next(iter(fixture.admission._receipts.values()))
                self.assertEqual(receipt.disposition, AdmissionDisposition.SETTLED)
                self.assertEqual(
                    receipt.reason_codes,
                    ("reservation_ceiling_charged",),
                )

    async def test_untrusted_provider_error_fields_never_enter_route_receipts(
        self,
    ) -> None:
        secrets = (
            "https://provider.invalid/v1?api_key=query-secret",
            "Authorization: Bearer header-secret",
            "/private/provider/path-secret.json",
            "prompt-secret-user-content",
            '{"error":"provider-body-secret"}',
        )
        unsafe = provider_failure(
            ModelFailureKind.TIMEOUT,
            "safe_placeholder",
            outcome_unknown=True,
        )
        unsafe.info = ErrorInfo(
            schema_version=1,
            code=secrets[0],
            category=ErrorCategory.TIMEOUT,
            retryable=True,
            outcome_unknown=True,
            public_message_key=secrets[1],
            reason_codes=secrets[2:],
        )
        unsafe.detail = secrets[-1]
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (unsafe,),
        )

        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-unsafe-error"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )

        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.INTERNAL)
        self.assertTrue(captured.exception.info.outcome_unknown)
        decision = captured.exception.route_decision
        public_surfaces = (
            str(captured.exception),
            repr(captured.exception),
            repr(captured.exception.info),
            repr(decision),
            canonical_json_bytes(decision).decode("utf-8"),
        )
        for secret in secrets:
            for surface in public_surfaces:
                self.assertNotIn(secret, surface)
        self.assertEqual(
            decision.attempts[0].error,
            decision.terminal_error,
        )

    async def test_perception_bootstrap_repairs_schema_once(self) -> None:
        haiku = endpoint("haiku-a", ModelTier.HAIKU)
        fixture = RouterFixture(
            (haiku,),
            (_policy(ModelRole.PERCEPTION, (haiku,), schema=True, profile="quick"),),
            (
                ProviderSuccess('{"schema_version":1}'),
                ProviderSuccess('{"schema_version":1,"intent":"chat"}'),
            ),
        )
        response = await fixture.router.invoke(
            _request(
                ModelRole.PERCEPTION,
                request_id="request-perception",
                schema=PERCEPTION_SCHEMA_REF,
                profile="quick",
            ),
            _bootstrap(),
            call=fixture.call,
        )
        self.assertEqual(response.output["intent"], "chat")
        self.assertEqual(
            tuple(item.kind for item in response.route_decision.attempts),
            (RouteAttemptKind.PRIMARY, RouteAttemptKind.SCHEMA_REPAIR),
        )
        self.assertTrue(
            fixture.provider.calls[1][0].prompt_template_revision.component_id.endswith(
                "repair-prompt"
            )
        )

    async def test_second_invalid_schema_is_terminal(self) -> None:
        haiku = endpoint("haiku-a", ModelTier.HAIKU)
        fixture = RouterFixture(
            (haiku,),
            (_policy(ModelRole.PERCEPTION, (haiku,), schema=True, profile="quick"),),
            (
                ProviderSuccess("not-json"),
                ProviderSuccess('{"schema_version":1}'),
            ),
        )
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(
                    ModelRole.PERCEPTION,
                    request_id="request-invalid",
                    schema=PERCEPTION_SCHEMA_REF,
                    profile="quick",
                ),
                _bootstrap(),
                call=fixture.call,
            )
        self.assertEqual(
            captured.exception.failure_kind, ModelFailureKind.OUTPUT_INVALID
        )
        self.assertEqual(len(fixture.provider.calls), 2)

    async def test_privacy_and_context_filters_produce_attempt_free_no_route(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet,),
            schema=False,
            profile="balanced",
        )
        fixture = RouterFixture((sonnet,), (policy,), ())
        request = _request(ModelRole.DIRECT_CHAT, request_id="request-private")
        request = replace(
            request,
            privacy=replace(request.privacy, allow_external_provider=False),
        )
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                request,
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        self.assertEqual(
            captured.exception.failure_kind, ModelFailureKind.ROUTE_NOT_FOUND
        )
        self.assertEqual(captured.exception.route_decision.attempts, ())
        self.assertEqual(
            captured.exception.route_decision.rejected_endpoints[0].reason_codes,
            ("external_processing_forbidden",),
        )

        context_fixture = RouterFixture((sonnet,), (policy,), ())
        too_long = replace(
            _request(ModelRole.DIRECT_CHAT, request_id="request-too-long"),
            content_input_tokens_upper_bound=sonnet.capabilities.max_context_tokens,
        )
        with self.assertRaises(ModelInvocationError) as context_error:
            await context_fixture.router.invoke(
                too_long,
                _tier_decision(ModelTier.SONNET),
                call=replace(
                    context_fixture.call,
                    budget=replace(
                        context_fixture.call.budget,
                        input_tokens_remaining=200_000,
                    ),
                ),
            )
        self.assertEqual(
            context_error.exception.route_decision.rejected_endpoints[0].reason_codes,
            ("input_context_limit_exceeded",),
        )

    async def test_no_idempotency_disables_provider_retry(self) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (provider_failure(ModelFailureKind.TIMEOUT, "timeout"),),
        )
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(
                    ModelRole.DIRECT_CHAT,
                    request_id="request-no-idempotency",
                    idempotency_key=None,
                ),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.TIMEOUT)
        self.assertEqual(len(fixture.provider.calls), 1)

    async def test_retry_is_stopped_by_shared_model_call_budget(self) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (provider_failure(ModelFailureKind.TIMEOUT, "timeout"),),
        )
        limited_call = replace(
            fixture.call,
            budget=replace(
                fixture.call.budget,
                model_calls_remaining=1,
                retries_remaining=1,
            ),
        )
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-budget"),
                _tier_decision(ModelTier.SONNET),
                call=limited_call,
            )
        self.assertEqual(
            captured.exception.failure_kind,
            ModelFailureKind.BUDGET_EXHAUSTED,
        )
        self.assertEqual(
            captured.exception.route_decision.attempts[-1].failure_kind,
            ModelFailureKind.TIMEOUT,
        )
        self.assertEqual(len(fixture.provider.calls), 1)

    async def test_pre_cancel_and_provider_receipt_drift_stop_safely(self) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        cancelled_fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
        )
        token = ManualCancellationToken()
        token.cancel()
        with self.assertRaises(ModelInvocationError) as cancelled:
            await cancelled_fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-cancelled"),
                _tier_decision(ModelTier.SONNET),
                call=replace(cancelled_fixture.call, cancellation=token),
            )
        self.assertEqual(cancelled.exception.failure_kind, ModelFailureKind.CANCELLED)
        self.assertEqual(cancelled_fixture.provider.calls, [])

        drift_fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (
                ProviderSuccess(
                    "invalid-receipt",
                    effective_reasoning_profile_id="quick",
                ),
            ),
        )
        with self.assertRaises(ModelInvocationError) as drift:
            await drift_fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-drift"),
                _tier_decision(ModelTier.SONNET),
                call=drift_fixture.call,
            )
        self.assertEqual(drift.exception.failure_kind, ModelFailureKind.INTERNAL)
        self.assertEqual(len(drift_fixture.provider.calls), 1)

    async def test_opus_hint_cannot_upgrade_a_sonnet_tier_decision(self) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        opus = endpoint("opus-a", ModelTier.OPUS)
        edge = TierFallbackEdge(
            schema_version=1,
            from_tier=ModelTier.SONNET,
            to_tier=ModelTier.OPUS,
            failure_kinds=frozenset({ModelFailureKind.PROVIDER_UNAVAILABLE}),
        )
        fixture = RouterFixture(
            (opus, sonnet),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (opus, sonnet),
                    schema=False,
                    profile="balanced",
                    fallback_edges=(edge,),
                ),
            ),
            (ProviderSuccess("sonnet"),),
        )
        response = await fixture.router.invoke(
            _request(
                ModelRole.DIRECT_CHAT,
                request_id="request-opus-hint",
                hint=RouteHint(
                    schema_version=1,
                    provider_id="provider-a",
                    endpoint_id="opus-a",
                    model_id=None,
                ),
            ),
            _tier_decision(ModelTier.SONNET),
            call=fixture.call,
        )
        self.assertEqual(response.route_decision.selected_tier, ModelTier.SONNET)
        self.assertEqual(fixture.provider.calls[0][0].endpoint_id, "sonnet-a")

    async def test_safety_and_unknown_outcome_never_retry(self) -> None:
        sonnet_a = endpoint("sonnet-a", ModelTier.SONNET)
        sonnet_b = endpoint("sonnet-b", ModelTier.SONNET)
        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet_a, sonnet_b),
            schema=False,
            profile="balanced",
        )
        safety_fixture = RouterFixture(
            (sonnet_a, sonnet_b),
            (policy,),
            (
                ProviderSuccess(
                    "blocked",
                    safety_annotations=(
                        SafetyAnnotation(
                            schema_version=1,
                            code="provider-policy",
                            severity="high",
                            blocked=True,
                        ),
                    ),
                ),
            ),
        )
        with self.assertRaises(ModelInvocationError) as safety:
            await safety_fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-safety"),
                _tier_decision(ModelTier.SONNET),
                call=safety_fixture.call,
            )
        self.assertEqual(
            safety.exception.failure_kind, ModelFailureKind.SAFETY_REJECTED
        )
        self.assertEqual(len(safety_fixture.provider.calls), 1)

        unknown_fixture = RouterFixture(
            (sonnet_a, sonnet_b),
            (policy,),
            (
                provider_failure(
                    ModelFailureKind.TIMEOUT,
                    "unknown-timeout",
                    outcome_unknown=True,
                ),
            ),
        )
        with self.assertRaises(ModelInvocationError) as unknown:
            await unknown_fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-unknown"),
                _tier_decision(ModelTier.SONNET),
                call=unknown_fixture.call,
            )
        self.assertTrue(unknown.exception.info.outcome_unknown)
        self.assertEqual(len(unknown_fixture.provider.calls), 1)

    async def test_policy_retry_and_failover_ceilings_are_hard(self) -> None:
        sonnet_a = endpoint("sonnet-a", ModelTier.SONNET)
        sonnet_b = endpoint("sonnet-b", ModelTier.SONNET)
        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet_a, sonnet_b),
            schema=False,
            profile="balanced",
        )
        policy = replace(
            policy,
            fallback=replace(
                policy.fallback,
                max_retries_per_endpoint=0,
                max_same_tier_failovers=0,
                max_tier_hops=0,
                max_total_attempts=1,
            ),
        )
        fixture = RouterFixture(
            (sonnet_a, sonnet_b),
            (policy,),
            (provider_failure(ModelFailureKind.TIMEOUT, "timeout"),),
        )
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-ceilings"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.TIMEOUT)
        self.assertEqual(len(fixture.provider.calls), 1)

    async def test_missing_initial_tier_never_uses_attempt_free_fallback(self) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        sonnet = replace(
            sonnet,
            allowed_data_classes=frozenset({PrivacyLevel.PUBLIC}),
        )
        sonnet = replace(
            sonnet,
            descriptor_digest=model_endpoint_descriptor_digest(sonnet),
        )
        haiku = endpoint("haiku-a", ModelTier.HAIKU)
        edge = TierFallbackEdge(
            schema_version=1,
            from_tier=ModelTier.SONNET,
            to_tier=ModelTier.HAIKU,
            failure_kinds=frozenset({ModelFailureKind.PROVIDER_UNAVAILABLE}),
        )
        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet, haiku),
            schema=False,
            profile="balanced",
            fallback_edges=(edge,),
        )
        fixture = RouterFixture(
            (sonnet, haiku),
            (policy,),
            (),
        )
        request = _request(ModelRole.DIRECT_CHAT, request_id="request-no-primary")
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                request,
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        self.assertEqual(
            captured.exception.failure_kind,
            ModelFailureKind.ROUTE_NOT_FOUND,
        )
        self.assertEqual(fixture.provider.calls, [])

    async def test_native_task_cancellation_settles_lease_and_cancels_provider(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        holder = {}

        def provider_factory(descriptor):
            provider = _BlockingProvider(descriptor)
            holder["provider"] = provider
            return provider

        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
            provider_factory=provider_factory,
        )
        invocation = asyncio.create_task(
            fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-native-cancel"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        )
        provider = holder["provider"]
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        invocation.cancel()
        with self.assertRaises(ModelInvocationError) as captured:
            await invocation

        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.CANCELLED)
        self.assertTrue(captured.exception.info.outcome_unknown)
        self.assertTrue(provider.cancelled.is_set())
        pool = fixture.admission._states[sonnet.quota_pool_id]
        self.assertEqual(pool.active, {})
        self.assertEqual(len(fixture.admission._receipts), 1)
        receipt = next(iter(fixture.admission._receipts.values()))
        self.assertEqual(receipt.disposition.value, "settled")

    async def test_repeated_native_cancellation_cannot_leak_lease_or_provider(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
            provider_factory=_StubbornProvider,
        )
        invocation = asyncio.create_task(
            fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-double-cancel"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        )
        provider = fixture.provider
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        invocation.cancel()
        await asyncio.wait_for(provider.cancelled_once.wait(), timeout=1)
        invocation.cancel()

        with self.assertRaises(ModelInvocationError) as captured:
            await asyncio.wait_for(invocation, timeout=1)
        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.CANCELLED)
        state = fixture.admission._states[sonnet.quota_pool_id]
        self.assertEqual(state.active, {})
        self.assertEqual(len(fixture.admission._receipts), 1)
        receipt = next(iter(fixture.admission._receipts.values()))
        self.assertEqual(receipt.disposition, AdmissionDisposition.SETTLED)

        provider.release.set()
        await asyncio.wait_for(provider.finished.wait(), timeout=1)

    async def test_deadline_after_reserve_returns_typed_timeout_with_receipt(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        now = [NOW]
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
            clock=lambda: now[0],
        )
        original_reserve = fixture.admission.reserve

        async def reserve_then_expire(request, *, call):
            result = await original_reserve(request, call=call)
            now[0] = call.deadline
            return result

        fixture.admission.reserve = reserve_then_expire
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-expired-reserve"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )

        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.TIMEOUT)
        self.assertEqual(fixture.provider.calls, [])
        decision = captured.exception.route_decision
        self.assertEqual(len(decision.admission_results), 1)
        self.assertEqual(len(decision.capacity_receipts), 1)
        receipt = decision.capacity_receipts[0]
        self.assertEqual(receipt.disposition, AdmissionDisposition.SETTLED)
        self.assertEqual(
            receipt.reason_codes,
            ("expired_lease_ceiling_charged",),
        )
        state = fixture.admission._states[sonnet.quota_pool_id]
        self.assertEqual(state.active, {})

    async def test_router_clock_failure_after_reserve_releases_capacity(self) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
        )
        original_reserve = fixture.admission.reserve

        async def reserve_then_break_router_clock(request, *, call):
            result = await original_reserve(request, call=call)
            failed = False

            def fail_once():
                nonlocal failed
                if not failed:
                    failed = True
                    raise ValueError("clock implementation secret")
                return NOW

            fixture.router._clock = fail_once
            return result

        fixture.admission.reserve = reserve_then_break_router_clock
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-clock-failure"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )

        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.INTERNAL)
        self.assertNotIn("clock implementation secret", repr(captured.exception))
        self.assertIsNone(captured.exception.__context__)
        receipt = captured.exception.route_decision.capacity_receipts[0]
        self.assertEqual(receipt.disposition, AdmissionDisposition.RELEASED)
        state = fixture.admission._states[sonnet.quota_pool_id]
        self.assertEqual(state.active, {})

    async def test_deadline_is_rechecked_immediately_before_provider_dispatch(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
        )
        original_reserve = fixture.admission.reserve
        short_call = replace(
            fixture.call,
            deadline=NOW + timedelta(seconds=5),
        )

        async def reserve_then_approach_deadline(request, *, call):
            result = await original_reserve(request, call=call)
            reads = 0

            def deadline_clock():
                nonlocal reads
                reads += 1
                if reads == 1:
                    return call.deadline - timedelta(milliseconds=20)
                return call.deadline

            fixture.router._clock = deadline_clock
            return result

        fixture.admission.reserve = reserve_then_approach_deadline
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-dispatch-deadline"),
                _tier_decision(ModelTier.SONNET),
                call=short_call,
            )

        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.TIMEOUT)
        self.assertEqual(fixture.provider.calls, [])
        decision = captured.exception.route_decision
        self.assertEqual(decision.attempts, ())
        self.assertEqual(
            decision.capacity_receipts[0].disposition,
            AdmissionDisposition.RELEASED,
        )
        state = fixture.admission._states[sonnet.quota_pool_id]
        self.assertEqual(state.active, {})

    async def test_pre_reserve_configuration_failures_never_create_lease(self) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet,),
            schema=False,
            profile="balanced",
        )
        missing_prompt = RouterFixture(
            (sonnet,),
            (policy,),
            (),
            prompt_revisions={ModelRole.PERCEPTION: revision("perception-prompt")},
        )
        with self.assertRaises(ModelInvocationError) as prompt_error:
            await missing_prompt.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-no-prompt"),
                _tier_decision(ModelTier.SONNET),
                call=missing_prompt.call,
            )
        self.assertEqual(
            prompt_error.exception.failure_kind,
            ModelFailureKind.INVALID_REQUEST,
        )
        self.assertEqual(missing_prompt.admission._states, {})

        missing_provider = RouterFixture((sonnet,), (policy,), ())
        missing_provider.routing._providers.clear()
        with self.assertRaises(ModelInvocationError) as provider_error:
            await missing_provider.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-no-provider"),
                _tier_decision(ModelTier.SONNET),
                call=missing_provider.call,
            )
        self.assertEqual(
            provider_error.exception.failure_kind,
            ModelFailureKind.INTERNAL,
        )
        self.assertEqual(missing_provider.admission._states, {})

    async def test_invalid_provider_result_is_terminal_and_settles_unknown(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
            provider_factory=_InvalidResponseProvider,
        )
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-invalid-result"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.INTERNAL)
        self.assertTrue(captured.exception.info.outcome_unknown)
        self.assertEqual(len(captured.exception.route_decision.attempts), 1)
        pool = fixture.admission._states[sonnet.quota_pool_id]
        self.assertEqual(pool.active, {})

    async def test_forged_provider_response_fields_cannot_escape_lease_guard(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet,),
            schema=False,
            profile="balanced",
        )
        for field in ("processing", "usage"):
            with self.subTest(field=field):
                fixture = RouterFixture(
                    (sonnet,),
                    (policy,),
                    (),
                    provider_factory=lambda descriptor, field=field: (
                        _ForgedResponseProvider(
                            descriptor,
                            field,
                            clock=lambda: NOW,
                        )
                    ),
                )
                with self.assertRaises(ModelInvocationError) as captured:
                    await fixture.router.invoke(
                        _request(
                            ModelRole.DIRECT_CHAT,
                            request_id=f"request-forged-{field}",
                        ),
                        _tier_decision(ModelTier.SONNET),
                        call=fixture.call,
                    )

                self.assertEqual(
                    captured.exception.failure_kind,
                    ModelFailureKind.INTERNAL,
                )
                self.assertIsNone(captured.exception.__context__)
                state = fixture.admission._states[sonnet.quota_pool_id]
                self.assertEqual(state.active, {})
                self.assertEqual(len(fixture.admission._receipts), 1)
                receipt = next(iter(fixture.admission._receipts.values()))
                self.assertEqual(receipt.disposition, AdmissionDisposition.SETTLED)

    async def test_provider_completion_after_deadline_cannot_return_success(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        now = [NOW]

        class AdvancingProvider(RecordingFakeModelProvider):
            async def generate(self, request, *, call):
                response = await super().generate(request, call=call)
                now[0] = call.deadline + timedelta(seconds=1)
                return response

        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
            clock=lambda: now[0],
            provider_factory=lambda descriptor: AdvancingProvider(
                descriptor,
                (ProviderSuccess("late"),),
                clock=lambda: now[0],
            ),
        )
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-late"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.TIMEOUT)
        self.assertEqual(len(captured.exception.route_decision.attempts), 1)
        self.assertEqual(
            captured.exception.route_decision.attempts[0].failure_kind,
            ModelFailureKind.TIMEOUT,
        )

    async def test_dynamic_gate_skips_failed_candidate_and_uses_next_endpoint(
        self,
    ) -> None:
        sonnet_a = endpoint("sonnet-a", ModelTier.SONNET)
        sonnet_b = endpoint("sonnet-b", ModelTier.SONNET)
        sonnet_c = endpoint("sonnet-c", ModelTier.SONNET)
        relaxed = []
        for descriptor in (sonnet_a, sonnet_b, sonnet_c):
            changed = replace(
                descriptor,
                traffic_policy=replace(
                    descriptor.traffic_policy,
                    max_snapshot_age_seconds=60,
                ),
            )
            relaxed.append(
                replace(
                    changed,
                    descriptor_digest=model_endpoint_descriptor_digest(changed),
                )
            )
        sonnet_a, sonnet_b, sonnet_c = relaxed
        now = [NOW]

        class AdvancingFailureProvider(RecordingFakeModelProvider):
            async def generate(self, request, *, call):
                try:
                    return await super().generate(request, call=call)
                finally:
                    if len(self.calls) == 1:
                        now[0] = call.deadline - timedelta(milliseconds=500)

        def operational_factory(descriptors):
            snapshot = _operational(descriptors)
            return replace(
                snapshot,
                endpoint_load=tuple(
                    replace(
                        load,
                        p95_latency_ms=(
                            1_000 if load.endpoint_id == "sonnet-b" else 10
                        ),
                    )
                    for load in snapshot.endpoint_load
                ),
            )

        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet_a, sonnet_b, sonnet_c),
            schema=False,
            profile="balanced",
        )
        policy = replace(
            policy,
            fallback=replace(policy.fallback, max_retries_per_endpoint=0),
        )
        fixture = RouterFixture(
            (sonnet_a, sonnet_b, sonnet_c),
            (policy,),
            (),
            clock=lambda: now[0],
            operational_factory=operational_factory,
            provider_factory=lambda descriptor: AdvancingFailureProvider(
                descriptor,
                (
                    provider_failure(
                        ModelFailureKind.PROVIDER_UNAVAILABLE,
                        "first-unavailable",
                    ),
                    ProviderSuccess("third-success"),
                ),
                clock=lambda: now[0],
            ),
        )
        response = await fixture.router.invoke(
            _request(ModelRole.DIRECT_CHAT, request_id="request-dynamic-gate"),
            _tier_decision(ModelTier.SONNET),
            call=fixture.call,
        )
        self.assertEqual(response.output, "third-success")
        self.assertEqual(
            tuple(request.endpoint_id for request, _ in fixture.provider.calls),
            ("sonnet-a", "sonnet-c"),
        )

    async def test_admission_cancellation_is_not_misclassified_as_rate_limit(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)

        def congested(descriptors):
            snapshot = _operational(descriptors)
            return replace(
                snapshot,
                endpoint_load=tuple(
                    replace(
                        load,
                        in_flight=sonnet.traffic_policy.max_concurrency,
                    )
                    for load in snapshot.endpoint_load
                ),
            )

        fixture = RouterFixture(
            (sonnet,),
            (
                _policy(
                    ModelRole.DIRECT_CHAT,
                    (sonnet,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
            operational_factory=congested,
        )
        cancellation = ManualCancellationToken()
        call = replace(fixture.call, cancellation=cancellation)
        invocation = asyncio.create_task(
            fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="request-queue-cancel"),
                _tier_decision(ModelTier.SONNET),
                call=call,
            )
        )
        for _ in range(20):
            state = fixture.admission._states.get(sonnet.quota_pool_id)
            if state is not None and state.waiters == 1:
                break
            await asyncio.sleep(0)
        cancellation.cancel()
        with self.assertRaises(ModelInvocationError) as captured:
            await invocation
        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.CANCELLED)
        self.assertEqual(
            captured.exception.route_decision.admission_results[0].reason_codes,
            ("admission_cancelled",),
        )
        self.assertEqual(fixture.provider.calls, [])

    async def test_initial_deadline_and_token_cost_budgets_are_typed(self) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet,),
            schema=False,
            profile="balanced",
        )
        cases = (
            (
                "deadline",
                lambda call: replace(call, deadline=NOW),
                ModelFailureKind.TIMEOUT,
            ),
            (
                "input",
                lambda call: replace(
                    call,
                    budget=replace(call.budget, input_tokens_remaining=1),
                ),
                ModelFailureKind.BUDGET_EXHAUSTED,
            ),
            (
                "output",
                lambda call: replace(
                    call,
                    budget=replace(call.budget, output_tokens_remaining=1),
                ),
                ModelFailureKind.BUDGET_EXHAUSTED,
            ),
            (
                "cost",
                lambda call: replace(
                    call,
                    budget=replace(call.budget, cost_units_remaining=Decimal(0)),
                ),
                ModelFailureKind.BUDGET_EXHAUSTED,
            ),
        )
        for name, mutate, expected in cases:
            with self.subTest(case=name):
                fixture = RouterFixture((sonnet,), (policy,), ())
                with self.assertRaises(ModelInvocationError) as captured:
                    await fixture.router.invoke(
                        _request(
                            ModelRole.DIRECT_CHAT,
                            request_id=f"request-{name}-budget",
                        ),
                        _tier_decision(ModelTier.SONNET),
                        call=mutate(fixture.call),
                    )
                self.assertEqual(captured.exception.failure_kind, expected)
                self.assertEqual(fixture.provider.calls, [])

    async def test_provider_cancellation_wait_is_strictly_bounded(self) -> None:
        release = asyncio.Event()
        provider_started = asyncio.Event()

        async def ignore_cancellation():
            provider_started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue

        provider_task = asyncio.create_task(ignore_cancellation())
        await provider_started.wait()
        started = time.monotonic()
        await asyncio.wait_for(_cancel_provider_task(provider_task), timeout=0.5)
        self.assertLess(time.monotonic() - started, 0.4)
        self.assertFalse(provider_task.done())
        release.set()
        await asyncio.wait_for(provider_task, timeout=1)

    async def test_route_plan_fingerprint_invariance_and_sensitivity_matrix(
        self,
    ) -> None:
        sonnet = endpoint("sonnet-a", ModelTier.SONNET)
        policy = _policy(
            ModelRole.DIRECT_CHAT,
            (sonnet,),
            schema=False,
            profile="balanced",
        )
        request = _request(ModelRole.DIRECT_CHAT, request_id="fingerprint-request")
        authority = _tier_decision(ModelTier.SONNET, decision_id="fingerprint-tier")

        baseline = RouterFixture(
            (sonnet,),
            (policy,),
            (ProviderSuccess("same-output"),),
        )
        baseline_response = await baseline.router.invoke(
            request,
            authority,
            call=baseline.call,
        )
        baseline_plan = baseline_response.route_decision.route_plan_fingerprint

        def shifted_operational(descriptors):
            snapshot = _operational(descriptors)
            shifted = NOW + timedelta(seconds=1)
            return replace(
                snapshot,
                snapshot_id="operational-shifted",
                provider_health=tuple(
                    replace(item, checked_at=shifted)
                    for item in snapshot.provider_health
                ),
                endpoint_load=tuple(
                    replace(item, checked_at=shifted) for item in snapshot.endpoint_load
                ),
                acquired_at=shifted,
            )

        shifted = RouterFixture(
            (sonnet,),
            (policy,),
            (ProviderSuccess("same-output"),),
            clock=lambda: NOW + timedelta(seconds=1),
            operational_factory=shifted_operational,
            id_prefix="shifted-id",
        )
        shifted_response = await shifted.router.invoke(
            request,
            authority,
            call=shifted.call,
        )
        self.assertEqual(
            baseline_plan,
            shifted_response.route_decision.route_plan_fingerprint,
        )
        self.assertNotEqual(
            route_decision_digest(baseline_response.route_decision),
            route_decision_digest(shifted_response.route_decision),
        )

        class DelayedProvider(RecordingFakeModelProvider):
            async def generate(self, request, *, call):
                await asyncio.sleep(0.02)
                return await super().generate(request, call=call)

        delayed = RouterFixture(
            (sonnet,),
            (policy,),
            (),
            provider_factory=lambda descriptor: DelayedProvider(
                descriptor,
                (ProviderSuccess("same-output"),),
                clock=lambda: NOW,
            ),
        )
        delayed_response = await delayed.router.invoke(
            request,
            authority,
            call=delayed.call,
        )
        self.assertEqual(
            baseline_plan,
            delayed_response.route_decision.route_plan_fingerprint,
        )
        self.assertGreater(delayed_response.route_decision.attempts[0].latency_ms, 0)
        self.assertNotEqual(
            route_decision_digest(baseline_response.route_decision),
            route_decision_digest(delayed_response.route_decision),
        )

        changed_input = replace(
            request,
            input=replace(
                request.input,
                parts=(replace(request.input.parts[0], text="different message"),),
            ),
        )
        semantic = RouterFixture(
            (sonnet,),
            (policy,),
            (ProviderSuccess("same-output"),),
        )
        semantic_response = await semantic.router.invoke(
            changed_input,
            authority,
            call=semantic.call,
        )

        changed_policy = replace(policy, policy_revision="route-direct-chat-v2")
        policy_fixture = RouterFixture(
            (sonnet,),
            (changed_policy,),
            (ProviderSuccess("same-output"),),
        )
        policy_response = await policy_fixture.router.invoke(
            request,
            authority,
            call=policy_fixture.call,
        )

        estimate_fixture = RouterFixture(
            (sonnet,),
            (policy,),
            (ProviderSuccess("same-output"),),
            provider_wrapping_tokens=5,
        )
        estimate_response = await estimate_fixture.router.invoke(
            request,
            authority,
            call=estimate_fixture.call,
        )

        def ineligible_operational(descriptors):
            snapshot = _operational(descriptors)
            return replace(
                snapshot,
                endpoint_load=tuple(
                    replace(item, rate_429=0.2) for item in snapshot.endpoint_load
                ),
            )

        eligibility_fixture = RouterFixture(
            (sonnet,),
            (policy,),
            (),
            operational_factory=ineligible_operational,
        )
        with self.assertRaises(ModelInvocationError) as eligibility_error:
            await eligibility_fixture.router.invoke(
                request,
                authority,
                call=eligibility_fixture.call,
            )

        changed_plans = (
            semantic_response.route_decision.route_plan_fingerprint,
            policy_response.route_decision.route_plan_fingerprint,
            estimate_response.route_decision.route_plan_fingerprint,
            eligibility_error.exception.route_decision.route_plan_fingerprint,
        )
        for changed_plan in changed_plans:
            self.assertNotEqual(baseline_plan, changed_plan)


if __name__ == "__main__":
    unittest.main()
