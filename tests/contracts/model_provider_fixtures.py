from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from dududa.domain.primitives import (
    DigestString,
    PrivacyLevel,
    RuntimeBudget,
    TraceContext,
)
from dududa.models.contracts import (
    EndpointTrafficPolicy,
    ModelCapabilities,
    ModelEndpointDescriptor,
    ModelInput,
    ModelInputModality,
    ModelInputPart,
    ModelOutputModality,
    ModelPrivacyPolicy,
    ModelProcessingBoundary,
    ModelProviderDescriptor,
    ModelRequest,
    ModelRetentionMode,
    ModelRole,
    ModelTier,
    ProviderRequest,
    ReasoningDepth,
    ReasoningProfile,
    RouteAttemptKind,
    StaleSnapshotPolicy,
    StructuredOutputSupport,
)
from dududa.models.digests import model_endpoint_descriptor_digest
from dududa.ports.context import NeverCancelled, PortCallContext

from tests.unit.models.helpers import NOW, revision


def compatible_descriptor() -> ModelProviderDescriptor:
    profile = ReasoningProfile(
        schema_version=1,
        profile_id="provider-default",
        depth=ReasoningDepth.OFF,
        max_reasoning_tokens=None,
        required=False,
    )
    endpoint = ModelEndpointDescriptor(
        schema_version=1,
        endpoint_id="astrbot-sonnet",
        model_id="provider-native-sonnet",
        descriptor_digest=DigestString("pending"),
        tier=ModelTier.SONNET,
        capabilities=ModelCapabilities(
            schema_version=1,
            input_modalities=frozenset({ModelInputModality.TEXT}),
            output_modalities=frozenset({ModelOutputModality.TEXT}),
            native_structured_output=StructuredOutputSupport.NONE,
            max_context_tokens=16_000,
            max_input_tokens=15_000,
            max_output_tokens=1_000,
            supports_temperature=False,
            supports_streaming=False,
            supports_seed=False,
        ),
        reasoning_profiles=(profile,),
        default_reasoning_profile_id=profile.profile_id,
        allowed_data_classes=frozenset(
            {PrivacyLevel.PUBLIC, PrivacyLevel.CONVERSATION}
        ),
        processing_boundary=ModelProcessingBoundary.EXTERNAL,
        available_data_residencies=frozenset({"global"}),
        supported_retention_modes=frozenset({ModelRetentionMode.NO_RETENTION}),
        quota_pool_id="astrbot-provider-1",
        traffic_policy=EndpointTrafficPolicy(
            schema_version=1,
            policy_id="astrbot-conservative",
            policy_revision="traffic-v1",
            max_concurrency=1,
            rpm_limit=10,
            tpm_limit=20_000,
            max_queue_depth=0,
            max_p95_latency_ms=10_000,
            max_429_rate=0.1,
            max_error_rate=0.2,
            observation_window_seconds=60,
            minimum_samples=1,
            cooldown_seconds=30,
            max_snapshot_age_seconds=15,
            stale_snapshot_policy=StaleSnapshotPolicy.EXCLUDE,
        ),
        enabled=True,
    )
    endpoint = replace(
        endpoint,
        descriptor_digest=model_endpoint_descriptor_digest(endpoint),
    )
    return ModelProviderDescriptor(
        schema_version=1,
        provider_id="astrbot-adapter",
        revision=revision("astrbot-adapter"),
        endpoints=(endpoint,),
    )


def compatible_provider_request(
    descriptor: ModelProviderDescriptor,
    *,
    idempotency_key: str | None = "provider-idem-1",
) -> ProviderRequest:
    endpoint = descriptor.endpoints[0]
    model_request = ModelRequest(
        schema_version=1,
        request_id="model-request-1",
        role=ModelRole.DIRECT_CHAT,
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
        output_schema=None,
        max_output_tokens=128,
        content_input_tokens_upper_bound=16,
        temperature=None,
        privacy=ModelPrivacyPolicy(
            schema_version=1,
            data_classification=PrivacyLevel.CONVERSATION,
            allow_external_provider=True,
            allowed_residencies=frozenset({"global"}),
            allow_provider_retention=False,
        ),
        reasoning_profile_id="provider-default",
        random_seed=None,
        idempotency_key=idempotency_key,
        route_hint=None,
    )
    return ProviderRequest(
        schema_version=1,
        request_id="provider-request-1",
        provider_id=descriptor.provider_id,
        provider_revision=descriptor.revision,
        endpoint_id=endpoint.endpoint_id,
        endpoint_descriptor_digest=endpoint.descriptor_digest,
        model_id=endpoint.model_id,
        selected_tier=endpoint.tier,
        tier_authority_digest=DigestString("tier-authority-digest"),
        invocation_estimate_digest=DigestString("estimate-digest"),
        route_policy_revision="route-v1",
        attempt=1,
        attempt_kind=RouteAttemptKind.PRIMARY,
        prompt_template_revision=revision("direct-chat-prompt"),
        selected_data_residency="global",
        required_retention_mode=ModelRetentionMode.NO_RETENTION,
        role=model_request.role,
        input=model_request.input,
        output_schema=None,
        max_output_tokens=model_request.max_output_tokens,
        temperature=None,
        privacy=model_request.privacy,
        reasoning_profile=endpoint.reasoning_profiles[0],
        random_seed=None,
        idempotency_key=idempotency_key,
    )


def provider_call() -> PortCallContext:
    return PortCallContext(
        run_id="run-provider-conformance",
        trace=TraceContext("trace-provider-conformance"),
        deadline=NOW + timedelta(seconds=30),
        cancellation=NeverCancelled(),
        budget=RuntimeBudget(2, 0, 1, 10_000, 10_000, Decimal(10)),
        policy_snapshot_id="policy-v1",
    )
