from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from dududa.domain.primitives import ComponentRevision, DigestString, PrivacyLevel
from dududa.models.contracts import (
    EndpointTrafficPolicy,
    ModelCapabilities,
    ModelEndpointDescriptor,
    ModelInputModality,
    ModelOutputModality,
    ModelProcessingBoundary,
    ModelRetentionMode,
    ModelTier,
    ReasoningDepth,
    ReasoningProfile,
    StaleSnapshotPolicy,
    StructuredOutputSupport,
)
from dududa.models.digests import model_endpoint_descriptor_digest

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def revision(component_id: str = "provider") -> ComponentRevision:
    return ComponentRevision(
        component_id=component_id,
        implementation_version="1.0.0",
        config_revision="config-v1",
        artifact_digest=DigestString(f"artifact-{component_id}"),
    )


def traffic_policy() -> EndpointTrafficPolicy:
    return EndpointTrafficPolicy(
        schema_version=1,
        policy_id="saas-default",
        policy_revision="traffic-v1",
        max_concurrency=4,
        rpm_limit=60,
        tpm_limit=100_000,
        max_queue_depth=8,
        max_p95_latency_ms=15_000,
        max_429_rate=0.1,
        max_error_rate=0.2,
        observation_window_seconds=60,
        minimum_samples=20,
        cooldown_seconds=30,
        max_snapshot_age_seconds=15,
        stale_snapshot_policy=StaleSnapshotPolicy.EXCLUDE,
    )


def reasoning_profiles() -> tuple[ReasoningProfile, ...]:
    return (
        ReasoningProfile(
            schema_version=1,
            profile_id="quick",
            depth=ReasoningDepth.LIGHT,
            max_reasoning_tokens=1_024,
            required=True,
        ),
        ReasoningProfile(
            schema_version=1,
            profile_id="balanced",
            depth=ReasoningDepth.BALANCED,
            max_reasoning_tokens=4_096,
            required=True,
        ),
        ReasoningProfile(
            schema_version=1,
            profile_id="deep",
            depth=ReasoningDepth.DEEP,
            max_reasoning_tokens=16_384,
            required=True,
        ),
    )


def endpoint(
    endpoint_id: str,
    tier: ModelTier,
    *,
    model_id: str = "provider-native-model",
    profiles: tuple[ReasoningProfile, ...] | None = None,
    default_profile_id: str = "balanced",
    enabled: bool = True,
) -> ModelEndpointDescriptor:
    descriptor = ModelEndpointDescriptor(
        schema_version=1,
        endpoint_id=endpoint_id,
        model_id=model_id,
        descriptor_digest=DigestString("pending-descriptor-digest"),
        tier=tier,
        capabilities=ModelCapabilities(
            schema_version=1,
            input_modalities=frozenset({ModelInputModality.TEXT}),
            output_modalities=frozenset({ModelOutputModality.TEXT}),
            native_structured_output=StructuredOutputSupport.JSON_SCHEMA,
            max_context_tokens=128_000,
            max_input_tokens=120_000,
            max_output_tokens=8_000,
            supports_temperature=True,
            supports_streaming=True,
            supports_seed=False,
        ),
        reasoning_profiles=profiles or reasoning_profiles(),
        default_reasoning_profile_id=default_profile_id,
        allowed_data_classes=frozenset(
            {
                PrivacyLevel.PUBLIC,
                PrivacyLevel.CONVERSATION,
                PrivacyLevel.PERSONAL,
            }
        ),
        processing_boundary=ModelProcessingBoundary.EXTERNAL,
        available_data_residencies=frozenset({"global"}),
        supported_retention_modes=frozenset({ModelRetentionMode.NO_RETENTION}),
        quota_pool_id="provider-main",
        traffic_policy=traffic_policy(),
        enabled=enabled,
    )
    return replace(
        descriptor,
        descriptor_digest=model_endpoint_descriptor_digest(descriptor),
    )
