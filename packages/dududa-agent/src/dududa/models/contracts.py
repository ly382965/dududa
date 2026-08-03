from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from dududa._compat import StrEnum
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    JsonValue,
    PrivacyLevel,
    SchemaRef,
    freeze_json,
    require_aware,
    require_non_empty,
)
from dududa.errors import ErrorCategory, ErrorInfo, validation_error


class ModelRole(StrEnum):
    PERCEPTION = "perception"
    SOCIAL_DECISION = "social_decision"
    TOOL_PLANNING = "tool_planning"
    DIRECT_CHAT = "direct_chat"
    RESPONSE_COMPOSITION = "response_composition"
    PERSONA_RENDERING = "persona_rendering"
    MEMORY_SUMMARY = "memory_summary"
    IMAGE_UNDERSTANDING = "image_understanding"
    IMAGE_GENERATION = "image_generation"


class ModelTier(StrEnum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


class ReasoningDepth(StrEnum):
    OFF = "off"
    LIGHT = "light"
    BALANCED = "balanced"
    DEEP = "deep"
    MAXIMUM = "maximum"


class StructuredOutputSupport(StrEnum):
    NONE = "none"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"


class ModelInputModality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    FILE = "file"


class ModelOutputModality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    EMBEDDING = "embedding"


class ModelProcessingBoundary(StrEnum):
    LOCAL = "local"
    EXTERNAL = "external"


class ModelRetentionMode(StrEnum):
    NO_RETENTION = "no_retention"
    PROVIDER_MANAGED = "provider_managed"


class EndpointHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class StaleSnapshotPolicy(StrEnum):
    EXCLUDE = "exclude"
    ALLOW_DEGRADED = "allow_degraded"


class ModelFailureKind(StrEnum):
    TRANSIENT_NETWORK = "transient_network"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONTEXT_TOO_LONG = "context_too_long"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    CAPABILITY_MISMATCH = "capability_mismatch"
    OUTPUT_INVALID = "output_invalid"
    SAFETY_REJECTED = "safety_rejected"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INTERNAL = "internal"


class RouteAttemptKind(StrEnum):
    PRIMARY = "primary"
    ENDPOINT_RETRY = "endpoint_retry"
    SAME_TIER_FAILOVER = "same_tier_failover"
    CROSS_TIER_FALLBACK = "cross_tier_fallback"
    SCHEMA_REPAIR = "schema_repair"


class AdmissionDisposition(StrEnum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ReasoningProfile:
    schema_version: int
    profile_id: str
    depth: ReasoningDepth
    max_reasoning_tokens: int | None
    required: bool

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.profile_id, "profile_id")
        _require_enum(self.depth, ReasoningDepth, "reasoning_depth")
        _optional_positive_int(self.max_reasoning_tokens, "max_reasoning_tokens")
        if type(self.required) is not bool:
            raise validation_error("invalid_reasoning_required")
        if self.depth is ReasoningDepth.OFF and self.max_reasoning_tokens is not None:
            raise validation_error("reasoning_off_has_token_budget")


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    schema_version: int
    input_modalities: frozenset[ModelInputModality]
    output_modalities: frozenset[ModelOutputModality]
    native_structured_output: StructuredOutputSupport
    max_context_tokens: int
    max_input_tokens: int | None
    max_output_tokens: int
    supports_temperature: bool
    supports_streaming: bool
    supports_seed: bool

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        object.__setattr__(self, "input_modalities", frozenset(self.input_modalities))
        object.__setattr__(self, "output_modalities", frozenset(self.output_modalities))
        if not self.input_modalities or not all(
            isinstance(value, ModelInputModality) for value in self.input_modalities
        ):
            raise validation_error("invalid_input_modalities")
        if not self.output_modalities or not all(
            isinstance(value, ModelOutputModality) for value in self.output_modalities
        ):
            raise validation_error("invalid_output_modalities")
        _require_enum(
            self.native_structured_output,
            StructuredOutputSupport,
            "native_structured_output",
        )
        _positive_int(self.max_context_tokens, "max_context_tokens")
        _optional_positive_int(self.max_input_tokens, "max_input_tokens")
        _positive_int(self.max_output_tokens, "max_output_tokens")
        if (
            self.max_input_tokens is not None
            and self.max_input_tokens > self.max_context_tokens
        ):
            raise validation_error("input_limit_exceeds_context")
        if self.max_output_tokens > self.max_context_tokens:
            raise validation_error("output_limit_exceeds_context")
        for field_name in (
            "supports_temperature",
            "supports_streaming",
            "supports_seed",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise validation_error("invalid_capability_flag", field_name)


@dataclass(frozen=True, slots=True)
class EndpointTrafficPolicy:
    schema_version: int
    policy_id: str
    policy_revision: str
    max_concurrency: int
    rpm_limit: int | None
    tpm_limit: int | None
    max_queue_depth: int
    max_p95_latency_ms: int | None
    max_429_rate: float
    max_error_rate: float
    observation_window_seconds: int
    minimum_samples: int
    cooldown_seconds: int
    max_snapshot_age_seconds: int
    stale_snapshot_policy: StaleSnapshotPolicy

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.policy_id, "traffic_policy_id")
        require_non_empty(self.policy_revision, "traffic_policy_revision")
        _positive_int(self.max_concurrency, "max_concurrency")
        _optional_positive_int(self.rpm_limit, "rpm_limit")
        _optional_positive_int(self.tpm_limit, "tpm_limit")
        _nonnegative_int(self.max_queue_depth, "max_queue_depth")
        _optional_positive_int(self.max_p95_latency_ms, "max_p95_latency_ms")
        _rate(self.max_429_rate, "max_429_rate")
        _rate(self.max_error_rate, "max_error_rate")
        _positive_int(self.observation_window_seconds, "observation_window_seconds")
        _positive_int(self.minimum_samples, "minimum_samples")
        _nonnegative_int(self.cooldown_seconds, "cooldown_seconds")
        _positive_int(self.max_snapshot_age_seconds, "max_snapshot_age_seconds")
        _require_enum(
            self.stale_snapshot_policy,
            StaleSnapshotPolicy,
            "stale_snapshot_policy",
        )


@dataclass(frozen=True, slots=True)
class ModelEndpointDescriptor:
    schema_version: int
    endpoint_id: str
    model_id: str
    descriptor_digest: DigestString
    tier: ModelTier
    capabilities: ModelCapabilities
    reasoning_profiles: tuple[ReasoningProfile, ...]
    default_reasoning_profile_id: str
    allowed_data_classes: frozenset[PrivacyLevel]
    processing_boundary: ModelProcessingBoundary
    available_data_residencies: frozenset[str]
    supported_retention_modes: frozenset[ModelRetentionMode]
    quota_pool_id: str
    traffic_policy: EndpointTrafficPolicy
    enabled: bool

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _require_instance(self.capabilities, ModelCapabilities, "capabilities")
        _require_instance(self.traffic_policy, EndpointTrafficPolicy, "traffic_policy")
        require_non_empty(self.endpoint_id, "endpoint_id")
        require_non_empty(self.model_id, "model_id")
        require_non_empty(str(self.descriptor_digest), "descriptor_digest")
        require_non_empty(
            self.default_reasoning_profile_id, "default_reasoning_profile_id"
        )
        require_non_empty(self.quota_pool_id, "quota_pool_id")
        _require_enum(self.tier, ModelTier, "model_tier")
        _require_enum(
            self.processing_boundary,
            ModelProcessingBoundary,
            "processing_boundary",
        )
        profiles = tuple(self.reasoning_profiles)
        if not profiles or not all(
            isinstance(profile, ReasoningProfile) for profile in profiles
        ):
            raise validation_error("missing_reasoning_profiles")
        _unique_ids(
            (profile.profile_id for profile in profiles),
            "reasoning_profile_id",
        )
        if self.default_reasoning_profile_id not in {
            profile.profile_id for profile in profiles
        }:
            raise validation_error("unknown_default_reasoning_profile")
        object.__setattr__(self, "reasoning_profiles", profiles)
        data_classes = frozenset(self.allowed_data_classes)
        if (
            not data_classes
            or PrivacyLevel.RESTRICTED in data_classes
            or not all(isinstance(value, PrivacyLevel) for value in data_classes)
        ):
            raise validation_error("invalid_endpoint_data_classes")
        object.__setattr__(self, "allowed_data_classes", data_classes)
        residencies = _nonempty_string_set(
            self.available_data_residencies,
            "available_data_residencies",
        )
        object.__setattr__(self, "available_data_residencies", residencies)
        retention_modes = frozenset(self.supported_retention_modes)
        if not retention_modes or not all(
            isinstance(value, ModelRetentionMode) for value in retention_modes
        ):
            raise validation_error("invalid_retention_modes")
        object.__setattr__(self, "supported_retention_modes", retention_modes)
        if type(self.enabled) is not bool:
            raise validation_error("invalid_endpoint_enabled")


@dataclass(frozen=True, slots=True)
class ModelProviderDescriptor:
    schema_version: int
    provider_id: str
    revision: ComponentRevision
    endpoints: tuple[ModelEndpointDescriptor, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.provider_id, "provider_id")
        _require_instance(self.revision, ComponentRevision, "provider_revision")
        endpoints = tuple(self.endpoints)
        if not endpoints or not all(
            isinstance(endpoint, ModelEndpointDescriptor) for endpoint in endpoints
        ):
            raise validation_error("provider_has_no_endpoints")
        _unique_ids((endpoint.endpoint_id for endpoint in endpoints), "endpoint_id")
        object.__setattr__(self, "endpoints", endpoints)


@dataclass(frozen=True, slots=True)
class ModelEndpointRef:
    schema_version: int
    provider_id: str
    endpoint_id: str
    model_id: str
    endpoint_descriptor_digest: DigestString
    tier: ModelTier
    priority: int

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.provider_id, "provider_id")
        require_non_empty(self.endpoint_id, "endpoint_id")
        require_non_empty(self.model_id, "model_id")
        require_non_empty(
            str(self.endpoint_descriptor_digest),
            "endpoint_descriptor_digest",
        )
        _require_enum(self.tier, ModelTier, "model_tier")
        _nonnegative_int(self.priority, "endpoint_priority")


@dataclass(frozen=True, slots=True)
class RouteHint:
    schema_version: int
    provider_id: str | None
    endpoint_id: str | None
    model_id: str | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        values = (self.provider_id, self.endpoint_id, self.model_id)
        if all(value is None for value in values):
            raise validation_error("empty_route_hint")
        for field_name, value in zip(
            ("provider_id", "endpoint_id", "model_id"),
            values,
        ):
            if value is not None:
                require_non_empty(value, field_name)


@dataclass(frozen=True, slots=True)
class ModelPrivacyPolicy:
    schema_version: int
    data_classification: PrivacyLevel
    allow_external_provider: bool
    allowed_residencies: frozenset[str]
    allow_provider_retention: bool

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.data_classification, PrivacyLevel):
            raise validation_error("invalid_model_data_classification")
        if self.data_classification is PrivacyLevel.RESTRICTED:
            raise validation_error("restricted_model_input_forbidden")
        if type(self.allow_external_provider) is not bool:
            raise validation_error("invalid_external_provider_policy")
        if type(self.allow_provider_retention) is not bool:
            raise validation_error("invalid_retention_policy")
        object.__setattr__(
            self,
            "allowed_residencies",
            _nonempty_string_set(self.allowed_residencies, "allowed_residencies"),
        )


@dataclass(frozen=True, slots=True)
class ModelInputPart:
    schema_version: int
    part_id: str
    modality: ModelInputModality
    text: str | None
    content_ref: str | None
    content_digest: DigestString | None
    media_type: str | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.part_id, "part_id")
        _require_enum(self.modality, ModelInputModality, "input_modality")
        if self.modality is ModelInputModality.TEXT:
            if self.text is None or not self.text.strip():
                raise validation_error("empty_model_text_part")
            if any(
                value is not None
                for value in (self.content_ref, self.content_digest, self.media_type)
            ):
                raise validation_error("text_part_has_attachment_fields")
            return
        if self.text is not None:
            raise validation_error("attachment_part_has_text")
        if (
            self.content_ref is None
            or self.content_digest is None
            or self.media_type is None
        ):
            raise validation_error("incomplete_model_attachment_part")
        require_non_empty(self.content_ref, "content_ref")
        require_non_empty(str(self.content_digest), "content_digest")
        require_non_empty(self.media_type, "media_type")


@dataclass(frozen=True, slots=True)
class ModelInput:
    schema_version: int
    parts: tuple[ModelInputPart, ...]
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        parts = tuple(self.parts)
        if not parts or not all(isinstance(part, ModelInputPart) for part in parts):
            raise validation_error("empty_model_input")
        _unique_ids((part.part_id for part in parts), "model_input_part_id")
        object.__setattr__(self, "parts", parts)
        object.__setattr__(
            self,
            "source_refs",
            _unique_strings(self.source_refs, "source_refs", required=False),
        )


@dataclass(frozen=True, slots=True)
class ModelRequest:
    schema_version: int
    request_id: str
    role: ModelRole
    input: ModelInput
    output_schema: SchemaRef | None
    max_output_tokens: int
    content_input_tokens_upper_bound: int
    temperature: float | None
    privacy: ModelPrivacyPolicy
    reasoning_profile_id: str
    random_seed: int | None
    idempotency_key: str | None
    route_hint: RouteHint | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.request_id, "request_id")
        require_non_empty(self.reasoning_profile_id, "reasoning_profile_id")
        _require_enum(self.role, ModelRole, "model_role")
        _require_instance(self.input, ModelInput, "model_input")
        _optional_instance(self.output_schema, SchemaRef, "output_schema")
        _require_instance(self.privacy, ModelPrivacyPolicy, "privacy")
        _optional_instance(self.route_hint, RouteHint, "route_hint")
        if self.role is ModelRole.PERCEPTION and self.output_schema is None:
            raise validation_error("perception_schema_required")
        _positive_int(self.max_output_tokens, "max_output_tokens")
        _positive_int(
            self.content_input_tokens_upper_bound,
            "content_input_tokens_upper_bound",
        )
        if self.temperature is not None and (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(self.temperature)
            or self.temperature < 0
        ):
            raise validation_error("invalid_temperature")
        if self.random_seed is not None and type(self.random_seed) is not int:
            raise validation_error("invalid_random_seed")
        if self.idempotency_key is not None:
            require_non_empty(self.idempotency_key, "idempotency_key")


@dataclass(frozen=True, slots=True)
class ModelUsage:
    schema_version: int
    input_tokens: int
    generated_tokens: int
    reasoning_tokens: int | None
    cached_input_tokens: int | None
    cost_units: Decimal | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _nonnegative_int(self.input_tokens, "input_tokens")
        _nonnegative_int(self.generated_tokens, "generated_tokens")
        _optional_nonnegative_int(self.reasoning_tokens, "reasoning_tokens")
        _optional_nonnegative_int(self.cached_input_tokens, "cached_input_tokens")
        _optional_nonnegative_decimal(self.cost_units, "cost_units")
        if (
            self.cached_input_tokens is not None
            and self.cached_input_tokens > self.input_tokens
        ):
            raise validation_error("cached_input_exceeds_input")
        if (
            self.reasoning_tokens is not None
            and self.reasoning_tokens > self.generated_tokens
        ):
            raise validation_error("reasoning_tokens_exceed_generated")

    @property
    def total_generated_tokens(self) -> int:
        return self.generated_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.total_generated_tokens


@dataclass(frozen=True, slots=True)
class ModelInvocationEstimate:
    schema_version: int
    model_request_digest: DigestString
    endpoint_descriptor_digest: DigestString
    reasoning_profile_id: str
    input_tokens_upper_bound: int
    generated_tokens_upper_bound: int
    reasoning_tokens_upper_bound: int
    total_context_tokens_upper_bound: int
    cost_units_upper_bound: Decimal | None
    estimator_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(str(self.model_request_digest), "model_request_digest")
        require_non_empty(
            str(self.endpoint_descriptor_digest),
            "endpoint_descriptor_digest",
        )
        require_non_empty(self.reasoning_profile_id, "reasoning_profile_id")
        _positive_int(self.input_tokens_upper_bound, "input_tokens_upper_bound")
        _positive_int(
            self.generated_tokens_upper_bound,
            "generated_tokens_upper_bound",
        )
        _nonnegative_int(
            self.reasoning_tokens_upper_bound,
            "reasoning_tokens_upper_bound",
        )
        _positive_int(
            self.total_context_tokens_upper_bound,
            "total_context_tokens_upper_bound",
        )
        if self.reasoning_tokens_upper_bound > self.generated_tokens_upper_bound:
            raise validation_error("reasoning_estimate_exceeds_generated")
        expected_total = (
            self.input_tokens_upper_bound + self.generated_tokens_upper_bound
        )
        if self.total_context_tokens_upper_bound != expected_total:
            raise validation_error("invocation_context_estimate_mismatch")
        _optional_nonnegative_decimal(
            self.cost_units_upper_bound,
            "cost_units_upper_bound",
        )
        _require_instance(
            self.estimator_revision,
            ComponentRevision,
            "estimator_revision",
        )


@dataclass(frozen=True, slots=True)
class SafetyAnnotation:
    schema_version: int
    code: str
    severity: str
    blocked: bool

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.code, "safety_code")
        require_non_empty(self.severity, "safety_severity")
        if type(self.blocked) is not bool:
            raise validation_error("invalid_safety_blocked")


@dataclass(frozen=True, slots=True)
class ModelProcessingReceipt:
    schema_version: int
    provider_id: str
    provider_revision: ComponentRevision
    endpoint_id: str
    endpoint_descriptor_digest: DigestString
    model_id: str
    provider_request_digest: DigestString
    processing_boundary: ModelProcessingBoundary
    data_residency: str
    retention_mode: ModelRetentionMode
    requested_reasoning_profile_id: str
    effective_reasoning_profile_id: str
    requested_seed: int | None
    effective_seed: int | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _require_instance(
            self.provider_revision,
            ComponentRevision,
            "provider_revision",
        )
        for field_name in (
            "provider_id",
            "endpoint_id",
            "model_id",
            "data_residency",
            "requested_reasoning_profile_id",
            "effective_reasoning_profile_id",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_non_empty(
            str(self.endpoint_descriptor_digest),
            "endpoint_descriptor_digest",
        )
        require_non_empty(
            str(self.provider_request_digest),
            "provider_request_digest",
        )
        _require_enum(
            self.processing_boundary,
            ModelProcessingBoundary,
            "processing_boundary",
        )
        _require_enum(self.retention_mode, ModelRetentionMode, "retention_mode")
        for field_name in ("requested_seed", "effective_seed"):
            value = getattr(self, field_name)
            if value is not None and type(value) is not int:
                raise validation_error("invalid_random_seed", field_name)


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    schema_version: int
    request_id: str
    provider_id: str
    provider_revision: ComponentRevision
    endpoint_id: str
    endpoint_descriptor_digest: DigestString
    model_id: str
    selected_tier: ModelTier
    tier_authority_digest: DigestString
    invocation_estimate_digest: DigestString
    route_policy_revision: str
    selected_data_residency: str
    required_retention_mode: ModelRetentionMode
    role: ModelRole
    input: ModelInput
    output_schema: SchemaRef | None
    max_output_tokens: int
    temperature: float | None
    privacy: ModelPrivacyPolicy
    reasoning_profile: ReasoningProfile
    random_seed: int | None
    idempotency_key: str | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _require_instance(
            self.provider_revision,
            ComponentRevision,
            "provider_revision",
        )
        _require_instance(self.input, ModelInput, "model_input")
        _optional_instance(self.output_schema, SchemaRef, "output_schema")
        _require_instance(self.privacy, ModelPrivacyPolicy, "privacy")
        _require_instance(
            self.reasoning_profile,
            ReasoningProfile,
            "reasoning_profile",
        )
        for field_name in (
            "request_id",
            "provider_id",
            "endpoint_id",
            "model_id",
            "route_policy_revision",
            "selected_data_residency",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_non_empty(
            str(self.endpoint_descriptor_digest),
            "endpoint_descriptor_digest",
        )
        require_non_empty(str(self.tier_authority_digest), "tier_authority_digest")
        require_non_empty(
            str(self.invocation_estimate_digest),
            "invocation_estimate_digest",
        )
        _require_enum(self.selected_tier, ModelTier, "selected_tier")
        _require_enum(self.role, ModelRole, "model_role")
        if self.role is ModelRole.PERCEPTION and self.output_schema is None:
            raise validation_error("perception_schema_required")
        _require_enum(
            self.required_retention_mode,
            ModelRetentionMode,
            "required_retention_mode",
        )
        _positive_int(self.max_output_tokens, "max_output_tokens")
        if self.temperature is not None and (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(self.temperature)
            or self.temperature < 0
        ):
            raise validation_error("invalid_temperature")
        if self.random_seed is not None and type(self.random_seed) is not int:
            raise validation_error("invalid_random_seed")
        if self.idempotency_key is not None:
            require_non_empty(self.idempotency_key, "idempotency_key")
        if self.selected_data_residency not in self.privacy.allowed_residencies:
            raise validation_error("provider_residency_not_allowed")
        if (
            not self.privacy.allow_provider_retention
            and self.required_retention_mode is not ModelRetentionMode.NO_RETENTION
        ):
            raise validation_error("provider_retention_not_allowed")


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    schema_version: int
    request_id: str
    provider_id: str
    endpoint_id: str
    model_id: str
    provider_revision: ComponentRevision
    output: JsonValue
    finish_reason: str
    usage: ModelUsage | None
    safety_annotations: tuple[SafetyAnnotation, ...]
    processing: ModelProcessingReceipt

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _require_instance(
            self.provider_revision,
            ComponentRevision,
            "provider_revision",
        )
        _optional_instance(self.usage, ModelUsage, "usage")
        _require_instance(
            self.processing,
            ModelProcessingReceipt,
            "processing",
        )
        for field_name in (
            "request_id",
            "provider_id",
            "endpoint_id",
            "model_id",
            "finish_reason",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        object.__setattr__(self, "output", freeze_json(self.output))
        object.__setattr__(
            self,
            "safety_annotations",
            tuple(self.safety_annotations),
        )
        if not all(
            isinstance(annotation, SafetyAnnotation)
            for annotation in self.safety_annotations
        ):
            raise validation_error("invalid_safety_annotations")
        if (
            self.processing.provider_id != self.provider_id
            or self.processing.endpoint_id != self.endpoint_id
            or self.processing.model_id != self.model_id
            or self.processing.provider_revision != self.provider_revision
        ):
            raise validation_error("provider_processing_receipt_mismatch")


@dataclass(frozen=True, slots=True)
class ModelEndpointHealth:
    schema_version: int
    endpoint_id: str
    endpoint_descriptor_digest: DigestString
    status: EndpointHealthStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.endpoint_id, "endpoint_id")
        require_non_empty(
            str(self.endpoint_descriptor_digest),
            "endpoint_descriptor_digest",
        )
        _require_enum(self.status, EndpointHealthStatus, "endpoint_health_status")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(self.reason_codes, "reason_codes", required=False),
        )


@dataclass(frozen=True, slots=True)
class ModelProviderHealth:
    schema_version: int
    provider_id: str
    status: EndpointHealthStatus
    endpoints: tuple[ModelEndpointHealth, ...]
    snapshot_revision: str
    checked_at: datetime
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.provider_id, "provider_id")
        require_non_empty(self.snapshot_revision, "snapshot_revision")
        require_aware(self.checked_at, "checked_at")
        _require_enum(self.status, EndpointHealthStatus, "provider_health_status")
        endpoints = tuple(self.endpoints)
        if not all(isinstance(endpoint, ModelEndpointHealth) for endpoint in endpoints):
            raise validation_error("invalid_endpoint_health")
        _unique_ids((endpoint.endpoint_id for endpoint in endpoints), "endpoint_id")
        object.__setattr__(self, "endpoints", endpoints)
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(self.reason_codes, "reason_codes", required=False),
        )


@dataclass(frozen=True, slots=True)
class EndpointLoadSnapshot:
    schema_version: int
    provider_id: str
    endpoint_id: str
    endpoint_descriptor_digest: DigestString
    quota_pool_id: str
    traffic_policy_id: str
    traffic_policy_revision: str
    in_flight: int
    requests_per_minute: int
    tokens_per_minute: int
    queue_depth: int
    p95_latency_ms: int | None
    rate_429: float
    error_rate: float
    sample_count: int
    cooldown_until: datetime | None
    checked_at: datetime
    snapshot_revision: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "provider_id",
            "endpoint_id",
            "quota_pool_id",
            "traffic_policy_id",
            "traffic_policy_revision",
            "snapshot_revision",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_non_empty(
            str(self.endpoint_descriptor_digest),
            "endpoint_descriptor_digest",
        )
        for field_name in (
            "in_flight",
            "requests_per_minute",
            "tokens_per_minute",
            "queue_depth",
            "sample_count",
        ):
            _nonnegative_int(getattr(self, field_name), field_name)
        _optional_nonnegative_int(self.p95_latency_ms, "p95_latency_ms")
        _rate(self.rate_429, "rate_429")
        _rate(self.error_rate, "error_rate")
        require_aware(self.checked_at, "checked_at")
        if self.cooldown_until is not None:
            require_aware(self.cooldown_until, "cooldown_until")


@dataclass(frozen=True, slots=True)
class ModelOperationalSnapshot:
    schema_version: int
    snapshot_id: str
    provider_health: tuple[ModelProviderHealth, ...]
    endpoint_load: tuple[EndpointLoadSnapshot, ...]
    acquired_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.snapshot_id, "operational_snapshot_id")
        require_aware(self.acquired_at, "acquired_at")
        health = tuple(self.provider_health)
        load = tuple(self.endpoint_load)
        if not all(isinstance(item, ModelProviderHealth) for item in health):
            raise validation_error("invalid_provider_health")
        if not all(isinstance(item, EndpointLoadSnapshot) for item in load):
            raise validation_error("invalid_endpoint_load")
        if any(item.checked_at > self.acquired_at for item in health) or any(
            item.checked_at > self.acquired_at for item in load
        ):
            raise validation_error("operational_observation_from_future")
        _unique_ids((item.provider_id for item in health), "provider_health_id")
        _unique_ids(
            (f"{item.provider_id}/{item.endpoint_id}" for item in load),
            "endpoint_load_id",
        )
        object.__setattr__(self, "provider_health", health)
        object.__setattr__(self, "endpoint_load", load)


@dataclass(frozen=True, slots=True)
class EndpointAdmissionRequest:
    schema_version: int
    reservation_id: str
    model_request_id: str
    model_request_digest: DigestString
    provider_id: str
    endpoint_id: str
    endpoint_descriptor_digest: DigestString
    quota_pool_id: str
    traffic_policy_id: str
    traffic_policy_revision: str
    operational_snapshot_id: str
    operational_snapshot_digest: DigestString
    invocation_estimate_digest: DigestString
    reserved_input_tokens: int
    reserved_generated_tokens: int
    reserved_reasoning_tokens: int
    reserved_cost_units: Decimal | None
    expires_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "reservation_id",
            "model_request_id",
            "provider_id",
            "endpoint_id",
            "quota_pool_id",
            "traffic_policy_id",
            "traffic_policy_revision",
            "operational_snapshot_id",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        for field_name in (
            "model_request_digest",
            "endpoint_descriptor_digest",
            "operational_snapshot_digest",
            "invocation_estimate_digest",
        ):
            require_non_empty(str(getattr(self, field_name)), field_name)
        _nonnegative_int(self.reserved_input_tokens, "reserved_input_tokens")
        _nonnegative_int(
            self.reserved_generated_tokens,
            "reserved_generated_tokens",
        )
        _nonnegative_int(
            self.reserved_reasoning_tokens,
            "reserved_reasoning_tokens",
        )
        if self.reserved_reasoning_tokens > self.reserved_generated_tokens:
            raise validation_error("reserved_reasoning_exceeds_generated")
        _optional_nonnegative_decimal(
            self.reserved_cost_units,
            "reserved_cost_units",
        )
        require_aware(self.expires_at, "expires_at")


@dataclass(frozen=True, slots=True)
class EndpointCapacityLease:
    schema_version: int
    lease_id: str
    request: EndpointAdmissionRequest
    admission_revision: str
    issued_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.lease_id, "lease_id")
        require_non_empty(self.admission_revision, "admission_revision")
        _require_instance(self.request, EndpointAdmissionRequest, "admission_request")
        require_aware(self.issued_at, "issued_at")
        if self.request.expires_at <= self.issued_at:
            raise validation_error("expired_capacity_lease")


@dataclass(frozen=True, slots=True)
class EndpointCapacityReceipt:
    schema_version: int
    lease_id: str
    disposition: AdmissionDisposition
    usage: ModelUsage | None
    reason_codes: tuple[str, ...]
    recorded_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.lease_id, "lease_id")
        _require_enum(self.disposition, AdmissionDisposition, "admission_disposition")
        _optional_instance(self.usage, ModelUsage, "usage")
        require_aware(self.recorded_at, "recorded_at")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(self.reason_codes, "reason_codes", required=False),
        )
        if self.disposition is AdmissionDisposition.SETTLED and self.usage is None:
            raise validation_error("settled_capacity_requires_usage")
        if (
            self.disposition is not AdmissionDisposition.SETTLED
            and self.usage is not None
        ):
            raise validation_error("nonsettled_capacity_has_usage")


@dataclass(frozen=True, slots=True)
class RouteAttempt:
    schema_version: int
    attempt: int
    kind: RouteAttemptKind
    provider_id: str
    endpoint_id: str
    model_id: str
    tier: ModelTier
    provider_request_digest: DigestString
    prompt_template_revision: ComponentRevision
    started_at: datetime
    latency_ms: int
    failure_kind: ModelFailureKind | None
    error: ErrorInfo | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _positive_int(self.attempt, "attempt")
        _require_enum(self.kind, RouteAttemptKind, "route_attempt_kind")
        _require_enum(self.tier, ModelTier, "model_tier")
        for field_name in ("provider_id", "endpoint_id", "model_id"):
            require_non_empty(getattr(self, field_name), field_name)
        require_non_empty(
            str(self.provider_request_digest),
            "provider_request_digest",
        )
        _require_instance(
            self.prompt_template_revision,
            ComponentRevision,
            "prompt_template_revision",
        )
        require_aware(self.started_at, "started_at")
        _nonnegative_int(self.latency_ms, "latency_ms")
        _optional_instance(self.error, ErrorInfo, "route_error")
        if (self.failure_kind is None) != (self.error is None):
            raise validation_error("route_attempt_error_mismatch")
        if self.failure_kind is not None:
            _require_enum(self.failure_kind, ModelFailureKind, "model_failure_kind")
            validate_model_failure_info(self.failure_kind, self.error)


@dataclass(frozen=True, slots=True)
class EndpointRejection:
    schema_version: int
    provider_id: str
    endpoint_id: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.provider_id, "provider_id")
        require_non_empty(self.endpoint_id, "endpoint_id")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(self.reason_codes, "reason_codes", required=True),
        )


@dataclass(frozen=True, slots=True)
class RouteDecision:
    schema_version: int
    decision_id: str
    request_id: str
    model_request_digest: DigestString
    model_request_fingerprint: DigestString
    role: ModelRole
    requested_tier: ModelTier
    selected_tier: ModelTier | None
    tier_authority_digest: DigestString
    tier_selection_fingerprint: DigestString
    routing_snapshot_id: str
    catalog_revision: str
    route_policy_revision: str
    operational_snapshot_id: str
    operational_snapshot_digest: DigestString
    output_schema_digest: DigestString | None
    output_codec_revision: ComponentRevision | None
    route_plan_fingerprint: DigestString
    eligible_endpoints: tuple[ModelEndpointRef, ...]
    rejected_endpoints: tuple[EndpointRejection, ...]
    selected_endpoint: ModelEndpointRef | None
    reasoning_profile: ReasoningProfile
    attempts: tuple[RouteAttempt, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "decision_id",
            "request_id",
            "routing_snapshot_id",
            "catalog_revision",
            "route_policy_revision",
            "operational_snapshot_id",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_non_empty(str(self.tier_authority_digest), "tier_authority_digest")
        for field_name in (
            "model_request_digest",
            "model_request_fingerprint",
            "tier_selection_fingerprint",
            "operational_snapshot_digest",
            "route_plan_fingerprint",
        ):
            require_non_empty(str(getattr(self, field_name)), field_name)
        _require_enum(self.role, ModelRole, "model_role")
        _require_enum(self.requested_tier, ModelTier, "requested_tier")
        if self.selected_tier is not None:
            _require_enum(self.selected_tier, ModelTier, "selected_tier")
        eligible = tuple(self.eligible_endpoints)
        rejected = tuple(self.rejected_endpoints)
        attempts = tuple(self.attempts)
        if not all(isinstance(item, ModelEndpointRef) for item in eligible):
            raise validation_error("invalid_eligible_endpoint")
        if not all(isinstance(item, EndpointRejection) for item in rejected):
            raise validation_error("invalid_rejected_endpoint")
        if not all(isinstance(item, RouteAttempt) for item in attempts):
            raise validation_error("invalid_route_attempt")
        _optional_instance(
            self.selected_endpoint,
            ModelEndpointRef,
            "selected_endpoint",
        )
        _require_instance(
            self.reasoning_profile,
            ReasoningProfile,
            "reasoning_profile",
        )
        _optional_instance(
            self.output_codec_revision,
            ComponentRevision,
            "output_codec_revision",
        )
        if (self.output_schema_digest is None) != (self.output_codec_revision is None):
            raise validation_error("output_codec_schema_receipt_mismatch")
        if self.output_schema_digest is not None:
            require_non_empty(str(self.output_schema_digest), "output_schema_digest")
        if self.role is ModelRole.PERCEPTION and self.output_schema_digest is None:
            raise validation_error("perception_schema_receipt_required")
        _unique_ids(
            (f"{item.provider_id}/{item.endpoint_id}" for item in eligible),
            "eligible_endpoint",
        )
        _unique_ids(
            (f"{item.provider_id}/{item.endpoint_id}" for item in rejected),
            "rejected_endpoint",
        )
        eligible_by_key = {
            (item.provider_id, item.endpoint_id): item for item in eligible
        }
        if set(eligible_by_key) & {
            (item.provider_id, item.endpoint_id) for item in rejected
        }:
            raise validation_error("endpoint_both_eligible_and_rejected")
        if tuple(item.attempt for item in attempts) != tuple(
            range(1, len(attempts) + 1)
        ):
            raise validation_error("route_attempt_sequence_invalid")
        _validate_attempt_transitions(attempts)
        for attempt in attempts:
            attempted_endpoint = eligible_by_key.get(
                (attempt.provider_id, attempt.endpoint_id)
            )
            if attempted_endpoint is None:
                raise validation_error("attempted_endpoint_not_eligible")
            if (
                attempt.model_id != attempted_endpoint.model_id
                or attempt.tier is not attempted_endpoint.tier
            ):
                raise validation_error("route_attempt_endpoint_mismatch")
        if self.selected_endpoint is None:
            if self.selected_tier is not None or attempts:
                raise validation_error("empty_route_has_selection")
        else:
            if self.selected_tier is None:
                raise validation_error("selected_route_has_no_tier")
            if self.selected_endpoint not in eligible:
                raise validation_error("selected_endpoint_not_eligible")
            if self.selected_endpoint.tier is not self.selected_tier:
                raise validation_error("selected_endpoint_tier_mismatch")
            if attempts:
                terminal = attempts[-1]
                if (
                    terminal.provider_id != self.selected_endpoint.provider_id
                    or terminal.endpoint_id != self.selected_endpoint.endpoint_id
                    or terminal.model_id != self.selected_endpoint.model_id
                    or terminal.tier is not self.selected_tier
                ):
                    raise validation_error("terminal_attempt_selection_mismatch")
        require_aware(self.decided_at, "decided_at")
        object.__setattr__(self, "eligible_endpoints", eligible)
        object.__setattr__(self, "rejected_endpoints", rejected)
        object.__setattr__(self, "attempts", attempts)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    schema_version: int
    request_id: str
    role: ModelRole
    output_schema_digest: DigestString | None
    output: JsonValue
    finish_reason: str
    usage: ModelUsage | None
    latency_ms: int
    route_decision: RouteDecision
    safety_annotations: tuple[SafetyAnnotation, ...]
    processing: ModelProcessingReceipt

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.request_id, "request_id")
        require_non_empty(self.finish_reason, "finish_reason")
        _require_enum(self.role, ModelRole, "model_role")
        _optional_instance(self.usage, ModelUsage, "usage")
        _require_instance(self.route_decision, RouteDecision, "route_decision")
        _require_instance(
            self.processing,
            ModelProcessingReceipt,
            "processing",
        )
        _nonnegative_int(self.latency_ms, "latency_ms")
        if self.request_id != self.route_decision.request_id:
            raise validation_error("route_decision_request_mismatch")
        if self.role is not self.route_decision.role:
            raise validation_error("route_decision_role_mismatch")
        if self.route_decision.selected_endpoint is None:
            raise validation_error("response_has_no_selected_endpoint")
        if not self.route_decision.attempts:
            raise validation_error("response_has_no_route_attempt")
        if self.route_decision.attempts[-1].failure_kind is not None:
            raise validation_error("response_last_attempt_failed")
        selected = self.route_decision.selected_endpoint
        if (
            selected.provider_id != self.processing.provider_id
            or selected.endpoint_id != self.processing.endpoint_id
            or selected.model_id != self.processing.model_id
            or selected.endpoint_descriptor_digest
            != self.processing.endpoint_descriptor_digest
        ):
            raise validation_error("response_processing_route_mismatch")
        if (
            self.route_decision.attempts[-1].provider_request_digest
            != self.processing.provider_request_digest
        ):
            raise validation_error("response_provider_request_mismatch")
        if (
            self.processing.requested_reasoning_profile_id
            != self.route_decision.reasoning_profile.profile_id
        ):
            raise validation_error("response_reasoning_profile_mismatch")
        if (
            self.route_decision.reasoning_profile.required
            and self.processing.effective_reasoning_profile_id
            != self.processing.requested_reasoning_profile_id
        ):
            raise validation_error("required_reasoning_profile_not_effective")
        if self.output_schema_digest is not None:
            require_non_empty(str(self.output_schema_digest), "output_schema_digest")
        elif self.role is ModelRole.PERCEPTION:
            raise validation_error("perception_schema_receipt_required")
        if self.output_schema_digest != self.route_decision.output_schema_digest:
            raise validation_error("response_schema_route_mismatch")
        object.__setattr__(self, "output", freeze_json(self.output))
        object.__setattr__(
            self,
            "safety_annotations",
            tuple(self.safety_annotations),
        )
        if not all(
            isinstance(annotation, SafetyAnnotation)
            for annotation in self.safety_annotations
        ):
            raise validation_error("invalid_safety_annotations")


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def validate_model_failure_info(
    failure_kind: ModelFailureKind,
    info: ErrorInfo,
) -> None:
    categories = {
        ModelFailureKind.TRANSIENT_NETWORK: {ErrorCategory.EXTERNAL},
        ModelFailureKind.TIMEOUT: {ErrorCategory.TIMEOUT},
        ModelFailureKind.RATE_LIMITED: {ErrorCategory.EXTERNAL},
        ModelFailureKind.PROVIDER_UNAVAILABLE: {ErrorCategory.EXTERNAL},
        ModelFailureKind.CONTEXT_TOO_LONG: {
            ErrorCategory.EXTERNAL,
            ErrorCategory.VALIDATION,
        },
        ModelFailureKind.AUTHENTICATION: {ErrorCategory.EXTERNAL},
        ModelFailureKind.INVALID_REQUEST: {ErrorCategory.VALIDATION},
        ModelFailureKind.CAPABILITY_MISMATCH: {ErrorCategory.VALIDATION},
        ModelFailureKind.OUTPUT_INVALID: {ErrorCategory.VALIDATION},
        ModelFailureKind.SAFETY_REJECTED: {
            ErrorCategory.AUTHORIZATION,
            ErrorCategory.EXTERNAL,
        },
        ModelFailureKind.CANCELLED: {ErrorCategory.CANCELLED},
        ModelFailureKind.BUDGET_EXHAUSTED: {ErrorCategory.BUDGET},
        ModelFailureKind.INTERNAL: {ErrorCategory.INTERNAL},
    }
    if info.category not in categories[failure_kind]:
        raise validation_error("model_failure_category_mismatch")
    retryable = {
        ModelFailureKind.TRANSIENT_NETWORK,
        ModelFailureKind.TIMEOUT,
        ModelFailureKind.RATE_LIMITED,
        ModelFailureKind.PROVIDER_UNAVAILABLE,
    }
    if info.retryable != (failure_kind in retryable):
        raise validation_error("model_failure_retryability_mismatch")


def _validate_attempt_transitions(attempts: tuple[RouteAttempt, ...]) -> None:
    if not attempts:
        return
    if attempts[0].kind is not RouteAttemptKind.PRIMARY:
        raise validation_error("route_first_attempt_not_primary")
    for previous, current in pairwise(attempts):
        if previous.failure_kind is None:
            raise validation_error("route_attempt_after_success")
        same_endpoint = (
            previous.provider_id == current.provider_id
            and previous.endpoint_id == current.endpoint_id
        )
        if current.kind is RouteAttemptKind.PRIMARY:
            raise validation_error("duplicate_primary_route_attempt")
        if current.kind is RouteAttemptKind.ENDPOINT_RETRY and not same_endpoint:
            raise validation_error("endpoint_retry_changed_endpoint")
        if current.kind is RouteAttemptKind.SAME_TIER_FAILOVER and (
            same_endpoint or current.tier is not previous.tier
        ):
            raise validation_error("same_tier_failover_mismatch")
        if current.kind is RouteAttemptKind.CROSS_TIER_FALLBACK and (
            same_endpoint or current.tier is previous.tier
        ):
            raise validation_error("cross_tier_fallback_mismatch")
        if current.kind is RouteAttemptKind.SCHEMA_REPAIR and (
            not same_endpoint
            or current.tier is not previous.tier
            or previous.failure_kind is not ModelFailureKind.OUTPUT_INVALID
        ):
            raise validation_error("schema_repair_transition_mismatch")


def _require_enum(value: object, expected: type[StrEnum], field: str) -> None:
    if not isinstance(value, expected):
        raise validation_error("invalid_enum", field)


def _require_instance(value: object, expected: type[object], field: str) -> None:
    if not isinstance(value, expected):
        raise validation_error("invalid_nested_contract", field)


def _optional_instance(
    value: object | None,
    expected: type[object],
    field: str,
) -> None:
    if value is not None:
        _require_instance(value, expected, field)


def _positive_int(value: object, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise validation_error("invalid_positive_integer", field)


def _optional_positive_int(value: object, field: str) -> None:
    if value is not None:
        _positive_int(value, field)


def _nonnegative_int(value: object, field: str) -> None:
    if type(value) is not int or value < 0:
        raise validation_error("invalid_nonnegative_integer", field)


def _optional_nonnegative_int(value: object, field: str) -> None:
    if value is not None:
        _nonnegative_int(value, field)


def _optional_nonnegative_decimal(value: Decimal | None, field: str) -> None:
    if value is not None and (
        not isinstance(value, Decimal) or not value.is_finite() or value < 0
    ):
        raise validation_error("invalid_nonnegative_decimal", field)


def _rate(value: object, field: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise validation_error("invalid_rate", field)


def _unique_ids(values: object, field: str) -> None:
    materialized = tuple(values)  # type: ignore[arg-type]
    if len(materialized) != len(set(materialized)):
        raise validation_error("duplicate_identifier", field)


def _unique_strings(
    values: tuple[str, ...],
    field: str,
    *,
    required: bool,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_string_collection", field)
    materialized = tuple(values)
    if required and not materialized:
        raise validation_error("empty_collection", field)
    if any(not isinstance(value, str) or not value.strip() for value in materialized):
        raise validation_error("empty_collection_item", field)
    _unique_ids(materialized, field)
    return materialized


def _nonempty_string_set(values: object, field: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_string_set", field)
    materialized = frozenset(values)  # type: ignore[arg-type]
    if not materialized or any(
        not isinstance(value, str) or not value.strip() for value in materialized
    ):
        raise validation_error("invalid_string_set", field)
    return materialized
