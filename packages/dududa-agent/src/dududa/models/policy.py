from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TypeAlias

from dududa._compat import StrEnum
from dududa.domain.primitives import (
    DigestString,
    PrivacyLevel,
    RuntimeBudget,
    require_aware,
    require_non_empty,
)
from dududa.domain.task import (
    ContextPressure,
    TaskAmbiguity,
    TaskComplexityAssessment,
    TaskComplexityLevel,
    TaskReasoningDepth,
)
from dududa.errors import validation_error

from .contracts import (
    ModelEndpointDescriptor,
    ModelEndpointRef,
    ModelFailureKind,
    ModelInputModality,
    ModelOutputModality,
    ModelProviderDescriptor,
    ModelRole,
    ModelTier,
    StructuredOutputSupport,
)


class ConfidenceHandling(StrEnum):
    DIRECT = "direct"
    LOW_CONFIDENCE_DEFAULT = "low_confidence_default"
    CONFLICT_DEFAULT = "conflict_default"
    BUDGET_CAPPED = "budget_capped"


@dataclass(frozen=True, slots=True)
class TierSelectionContext:
    schema_version: int
    selection_id: str
    role: ModelRole
    assessment: TaskComplexityAssessment
    content_input_tokens_upper_bound: int
    data_classification: PrivacyLevel
    budget: RuntimeBudget

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.selection_id, "selection_id")
        _require_enum(self.role, ModelRole, "model_role")
        if self.role is ModelRole.PERCEPTION:
            raise validation_error("perception_has_no_assessed_tier_context")
        if not isinstance(self.assessment, TaskComplexityAssessment):
            raise validation_error("invalid_task_complexity_assessment")
        _positive_int(
            self.content_input_tokens_upper_bound,
            "content_input_tokens_upper_bound",
        )
        if not isinstance(self.data_classification, PrivacyLevel):
            raise validation_error("invalid_model_data_classification")
        if self.data_classification is PrivacyLevel.RESTRICTED:
            raise validation_error("restricted_model_input_forbidden")
        if not isinstance(self.budget, RuntimeBudget):
            raise validation_error("invalid_runtime_budget")

    @property
    def complexity_level(self) -> TaskComplexityLevel:
        return self.assessment.level

    @property
    def confidence(self) -> float:
        return self.assessment.confidence

    @property
    def task_kind(self) -> str:
        return self.assessment.task_kind

    @property
    def context_pressure(self) -> ContextPressure:
        return self.assessment.context_pressure

    @property
    def reasoning_depth(self) -> TaskReasoningDepth:
        return self.assessment.reasoning_depth

    @property
    def expected_tool_steps(self) -> int:
        return self.assessment.expected_tool_steps

    @property
    def ambiguity(self) -> TaskAmbiguity:
        return self.assessment.ambiguity

    @property
    def verification_required(self) -> bool:
        return self.assessment.verification_required

    @property
    def conflicting_evidence(self) -> bool:
        return self.assessment.conflicting_evidence


@dataclass(frozen=True, slots=True)
class TierBudgetRequirement:
    schema_version: int
    tier: ModelTier
    minimum_input_tokens_remaining: int
    minimum_generated_tokens_remaining: int
    minimum_cost_units_remaining: Decimal

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _require_enum(self.tier, ModelTier, "model_tier")
        _nonnegative_int(
            self.minimum_input_tokens_remaining,
            "minimum_input_tokens_remaining",
        )
        _nonnegative_int(
            self.minimum_generated_tokens_remaining,
            "minimum_generated_tokens_remaining",
        )
        _nonnegative_decimal(
            self.minimum_cost_units_remaining,
            "minimum_cost_units_remaining",
        )


@dataclass(frozen=True, slots=True)
class TierPolicyDefinition:
    schema_version: int
    policy_id: str
    role: ModelRole
    allowed_tiers: frozenset[ModelTier]
    default_tier: ModelTier
    low_complexity_tier: ModelTier
    high_complexity_tier: ModelTier
    low_confidence_threshold: float
    minimum_high_tier_confidence: float
    minimum_high_complexity_signals: int
    high_complexity_reason_codes: frozenset[str]
    tier_budget_requirements: tuple[TierBudgetRequirement, ...]
    policy_revision: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.policy_id, "tier_policy_id")
        require_non_empty(self.policy_revision, "tier_policy_revision")
        _require_enum(self.role, ModelRole, "model_role")
        if self.role is ModelRole.PERCEPTION:
            raise validation_error("perception_uses_bootstrap_tier_policy")
        tiers = frozenset(self.allowed_tiers)
        if not tiers or not all(isinstance(tier, ModelTier) for tier in tiers):
            raise validation_error("invalid_allowed_tiers")
        object.__setattr__(self, "allowed_tiers", tiers)
        for field_name in (
            "default_tier",
            "low_complexity_tier",
            "high_complexity_tier",
        ):
            tier = getattr(self, field_name)
            _require_enum(tier, ModelTier, field_name)
            if tier not in tiers:
                raise validation_error("tier_not_allowed", field_name)
        _rate(self.low_confidence_threshold, "low_confidence_threshold")
        _rate(
            self.minimum_high_tier_confidence,
            "minimum_high_tier_confidence",
        )
        if self.minimum_high_tier_confidence < self.low_confidence_threshold:
            raise validation_error("invalid_tier_confidence_thresholds")
        _positive_int(
            self.minimum_high_complexity_signals,
            "minimum_high_complexity_signals",
        )
        high_complexity_reason_codes = _nonempty_string_set(
            self.high_complexity_reason_codes,
            "high_complexity_reason_codes",
        )
        if self.minimum_high_complexity_signals > len(high_complexity_reason_codes):
            raise validation_error("insufficient_high_complexity_reason_codes")
        object.__setattr__(
            self,
            "high_complexity_reason_codes",
            high_complexity_reason_codes,
        )
        budget_requirements = tuple(self.tier_budget_requirements)
        if not budget_requirements or not all(
            isinstance(requirement, TierBudgetRequirement)
            for requirement in budget_requirements
        ):
            raise validation_error("invalid_tier_budget_requirements")
        requirement_tiers = tuple(
            requirement.tier for requirement in budget_requirements
        )
        if len(requirement_tiers) != len(set(requirement_tiers)):
            raise validation_error("duplicate_tier_budget_requirement")
        if set(requirement_tiers) != set(tiers):
            raise validation_error("missing_tier_budget_requirement")
        object.__setattr__(
            self,
            "tier_budget_requirements",
            budget_requirements,
        )


@dataclass(frozen=True, slots=True)
class TierDecision:
    schema_version: int
    decision_id: str
    role: ModelRole
    selected_tier: ModelTier
    uncapped_tier: ModelTier
    assessment_digest: DigestString
    selection_context_digest: DigestString
    selection_fingerprint: DigestString
    tier_policy_digest: DigestString
    policy_revision: str
    confidence_handling: ConfidenceHandling
    reason_codes: tuple[str, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.decision_id, "tier_decision_id")
        require_non_empty(str(self.assessment_digest), "assessment_digest")
        require_non_empty(
            str(self.selection_context_digest),
            "selection_context_digest",
        )
        require_non_empty(str(self.selection_fingerprint), "selection_fingerprint")
        require_non_empty(str(self.tier_policy_digest), "tier_policy_digest")
        require_non_empty(self.policy_revision, "tier_policy_revision")
        _require_enum(self.role, ModelRole, "model_role")
        _require_enum(self.selected_tier, ModelTier, "selected_tier")
        _require_enum(self.uncapped_tier, ModelTier, "uncapped_tier")
        _require_enum(
            self.confidence_handling,
            ConfidenceHandling,
            "confidence_handling",
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(self.reason_codes, "reason_codes", required=True),
        )
        if self.confidence_handling is ConfidenceHandling.BUDGET_CAPPED:
            if self.uncapped_tier is self.selected_tier:
                raise validation_error("budget_cap_did_not_change_tier")
        elif self.uncapped_tier is not self.selected_tier:
            raise validation_error("uncapped_tier_changed_without_budget_cap")
        require_aware(self.decided_at, "decided_at")


@dataclass(frozen=True, slots=True)
class BootstrapTierDecision:
    schema_version: int
    decision_id: str
    role: ModelRole
    selected_tier: ModelTier
    selection_fingerprint: DigestString
    tier_policy_digest: DigestString
    policy_revision: str
    reason_codes: tuple[str, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.decision_id, "bootstrap_tier_decision_id")
        require_non_empty(str(self.selection_fingerprint), "selection_fingerprint")
        require_non_empty(str(self.tier_policy_digest), "tier_policy_digest")
        require_non_empty(self.policy_revision, "tier_policy_revision")
        _require_enum(self.role, ModelRole, "model_role")
        _require_enum(self.selected_tier, ModelTier, "selected_tier")
        if self.role is not ModelRole.PERCEPTION:
            raise validation_error("bootstrap_role_forbidden")
        if self.selected_tier is not ModelTier.HAIKU:
            raise validation_error("bootstrap_tier_forbidden")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(self.reason_codes, "reason_codes", required=True),
        )
        require_aware(self.decided_at, "decided_at")


TierAuthority: TypeAlias = BootstrapTierDecision | TierDecision


def validate_tier_authority(
    role: ModelRole,
    authority: TierAuthority,
) -> None:
    _require_enum(role, ModelRole, "model_role")
    if not isinstance(authority, (BootstrapTierDecision, TierDecision)):
        raise validation_error("invalid_tier_authority")
    if authority.role is not role:
        raise validation_error("tier_authority_role_mismatch")
    if role is ModelRole.PERCEPTION:
        if not isinstance(authority, BootstrapTierDecision):
            raise validation_error("perception_requires_bootstrap_tier_authority")
    elif isinstance(authority, BootstrapTierDecision):
        raise validation_error("bootstrap_tier_authority_role_forbidden")


@dataclass(frozen=True, slots=True)
class ModelCapabilitiesRequirement:
    schema_version: int
    input_modalities: frozenset[ModelInputModality]
    output_modalities: frozenset[ModelOutputModality]
    minimum_native_structured_output: StructuredOutputSupport
    requires_schema_validation: bool
    minimum_context_tokens: int
    minimum_output_tokens: int
    reasoning_profile_id: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        inputs = frozenset(self.input_modalities)
        outputs = frozenset(self.output_modalities)
        if not inputs or not all(
            isinstance(value, ModelInputModality) for value in inputs
        ):
            raise validation_error("invalid_input_modalities")
        if not outputs or not all(
            isinstance(value, ModelOutputModality) for value in outputs
        ):
            raise validation_error("invalid_output_modalities")
        object.__setattr__(self, "input_modalities", inputs)
        object.__setattr__(self, "output_modalities", outputs)
        _require_enum(
            self.minimum_native_structured_output,
            StructuredOutputSupport,
            "minimum_native_structured_output",
        )
        if type(self.requires_schema_validation) is not bool:
            raise validation_error("invalid_schema_validation_requirement")
        _positive_int(self.minimum_context_tokens, "minimum_context_tokens")
        _positive_int(self.minimum_output_tokens, "minimum_output_tokens")
        if self.minimum_output_tokens > self.minimum_context_tokens:
            raise validation_error("output_requirement_exceeds_context")
        require_non_empty(self.reasoning_profile_id, "reasoning_profile_id")


@dataclass(frozen=True, slots=True)
class TierFallbackEdge:
    schema_version: int
    from_tier: ModelTier
    to_tier: ModelTier
    failure_kinds: frozenset[ModelFailureKind]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _require_enum(self.from_tier, ModelTier, "fallback_from_tier")
        _require_enum(self.to_tier, ModelTier, "fallback_to_tier")
        if self.from_tier is self.to_tier:
            raise validation_error("self_tier_fallback")
        failures = frozenset(self.failure_kinds)
        if not failures or not all(
            isinstance(value, ModelFailureKind) for value in failures
        ):
            raise validation_error("invalid_fallback_failure_kinds")
        forbidden = {
            ModelFailureKind.AUTHENTICATION,
            ModelFailureKind.INVALID_REQUEST,
            ModelFailureKind.OUTPUT_INVALID,
            ModelFailureKind.SAFETY_REJECTED,
            ModelFailureKind.CANCELLED,
        }
        if failures & forbidden:
            raise validation_error("unsafe_cross_tier_fallback")
        object.__setattr__(self, "failure_kinds", failures)


@dataclass(frozen=True, slots=True)
class ModelFallbackPolicy:
    schema_version: int
    max_retries_per_endpoint: int
    max_same_tier_failovers: int
    max_tier_hops: int
    max_total_attempts: int
    max_schema_repairs: int
    retryable_failure_kinds: frozenset[ModelFailureKind]
    deterministic_fallback_id: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "max_retries_per_endpoint",
            "max_same_tier_failovers",
            "max_tier_hops",
            "max_schema_repairs",
        ):
            _nonnegative_int(getattr(self, field_name), field_name)
        if self.max_schema_repairs > 1:
            raise validation_error("too_many_schema_repairs")
        _positive_int(self.max_total_attempts, "max_total_attempts")
        retryable = frozenset(self.retryable_failure_kinds)
        allowed = {
            ModelFailureKind.TRANSIENT_NETWORK,
            ModelFailureKind.TIMEOUT,
            ModelFailureKind.RATE_LIMITED,
            ModelFailureKind.PROVIDER_UNAVAILABLE,
        }
        if not retryable <= allowed:
            raise validation_error("unsafe_retry_failure_kind")
        object.__setattr__(self, "retryable_failure_kinds", retryable)
        require_non_empty(self.deterministic_fallback_id, "deterministic_fallback_id")


@dataclass(frozen=True, slots=True)
class ModelRoutePolicy:
    schema_version: int
    policy_id: str
    role: ModelRole
    default_tier: ModelTier
    allowed_tiers: frozenset[ModelTier]
    candidate_endpoints: tuple[ModelEndpointRef, ...]
    requirements: ModelCapabilitiesRequirement
    allowed_data_classes: frozenset[PrivacyLevel]
    fallback: ModelFallbackPolicy
    tier_fallback_edges: tuple[TierFallbackEdge, ...]
    policy_revision: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.policy_id, "route_policy_id")
        require_non_empty(self.policy_revision, "route_policy_revision")
        _require_enum(self.role, ModelRole, "model_role")
        _require_enum(self.default_tier, ModelTier, "default_tier")
        if not isinstance(self.requirements, ModelCapabilitiesRequirement):
            raise validation_error("invalid_capabilities_requirement")
        if not isinstance(self.fallback, ModelFallbackPolicy):
            raise validation_error("invalid_fallback_policy")
        tiers = frozenset(self.allowed_tiers)
        if not tiers or not all(isinstance(tier, ModelTier) for tier in tiers):
            raise validation_error("invalid_allowed_tiers")
        if self.default_tier not in tiers:
            raise validation_error("default_tier_not_allowed")
        object.__setattr__(self, "allowed_tiers", tiers)
        candidates = tuple(self.candidate_endpoints)
        if not candidates or not all(
            isinstance(candidate, ModelEndpointRef) for candidate in candidates
        ):
            raise validation_error("route_policy_has_no_candidates")
        _unique_strings(
            tuple(f"{item.provider_id}/{item.endpoint_id}" for item in candidates),
            "candidate_endpoint",
            required=True,
        )
        candidate_tiers = {candidate.tier for candidate in candidates}
        if not candidate_tiers <= tiers or self.default_tier not in candidate_tiers:
            raise validation_error("candidate_tier_not_allowed")
        if candidate_tiers != tiers:
            raise validation_error("allowed_tier_has_no_candidate")
        object.__setattr__(self, "candidate_endpoints", candidates)
        data_classes = frozenset(self.allowed_data_classes)
        if (
            not data_classes
            or PrivacyLevel.RESTRICTED in data_classes
            or not all(isinstance(value, PrivacyLevel) for value in data_classes)
        ):
            raise validation_error("invalid_route_data_classes")
        object.__setattr__(self, "allowed_data_classes", data_classes)
        edges = tuple(self.tier_fallback_edges)
        if not all(isinstance(edge, TierFallbackEdge) for edge in edges):
            raise validation_error("invalid_tier_fallback_edge")
        edge_ids = tuple(
            f"{edge.from_tier.value}/{edge.to_tier.value}" for edge in edges
        )
        _unique_strings(edge_ids, "tier_fallback_edge", required=False)
        if any(
            edge.from_tier not in tiers or edge.to_tier not in tiers for edge in edges
        ):
            raise validation_error("fallback_tier_not_allowed")
        object.__setattr__(self, "tier_fallback_edges", edges)
        _reject_fallback_cycles(tiers, edges)
        if self.role is ModelRole.PERCEPTION and (
            self.default_tier is not ModelTier.HAIKU
            or tiers != frozenset({ModelTier.HAIKU})
            or not self.requirements.requires_schema_validation
            or edges
        ):
            raise validation_error("invalid_perception_route_policy")


@dataclass(frozen=True, slots=True)
class ModelRoutingSnapshot:
    schema_version: int
    snapshot_id: str
    catalog_revision: str
    provider_descriptors: tuple[ModelProviderDescriptor, ...]
    route_policies: tuple[ModelRoutePolicy, ...]
    acquired_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.snapshot_id, "routing_snapshot_id")
        require_non_empty(self.catalog_revision, "catalog_revision")
        require_aware(self.acquired_at, "acquired_at")
        providers = tuple(self.provider_descriptors)
        policies = tuple(self.route_policies)
        if (
            not providers
            or not policies
            or not all(
                isinstance(provider, ModelProviderDescriptor) for provider in providers
            )
            or not all(isinstance(policy, ModelRoutePolicy) for policy in policies)
        ):
            raise validation_error("empty_routing_snapshot")
        _unique_strings(
            tuple(provider.provider_id for provider in providers),
            "provider_id",
            required=True,
        )
        _unique_strings(
            tuple(policy.role.value for policy in policies),
            "route_policy_role",
            required=True,
        )
        object.__setattr__(self, "provider_descriptors", providers)
        object.__setattr__(self, "route_policies", policies)


@dataclass(frozen=True, slots=True)
class ModelCatalogUpdate:
    schema_version: int
    expected_revision: str
    provider_descriptors: tuple[ModelProviderDescriptor, ...]
    route_policies: tuple[ModelRoutePolicy, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.expected_revision, "expected_catalog_revision")
        providers = tuple(self.provider_descriptors)
        policies = tuple(self.route_policies)
        if (
            not providers
            or not policies
            or not all(
                isinstance(provider, ModelProviderDescriptor) for provider in providers
            )
            or not all(isinstance(policy, ModelRoutePolicy) for policy in policies)
        ):
            raise validation_error("empty_catalog_update")
        _unique_strings(
            tuple(provider.provider_id for provider in providers),
            "provider_id",
            required=True,
        )
        _unique_strings(
            tuple(policy.role.value for policy in policies),
            "route_policy_role",
            required=True,
        )
        object.__setattr__(self, "provider_descriptors", providers)
        object.__setattr__(self, "route_policies", policies)


@dataclass(frozen=True, slots=True)
class ModelCatalogPublishReceipt:
    schema_version: int
    previous_revision: str
    catalog_revision: str
    snapshot_id: str
    published_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.previous_revision, "previous_catalog_revision")
        require_non_empty(self.catalog_revision, "catalog_revision")
        require_non_empty(self.snapshot_id, "routing_snapshot_id")
        require_aware(self.published_at, "published_at")


def validate_routing_snapshot(snapshot: ModelRoutingSnapshot) -> None:
    from .digests import model_endpoint_descriptor_digest, routing_catalog_digest

    endpoint_by_key = {}
    traffic_policy_by_pool = {}
    for provider in snapshot.provider_descriptors:
        for endpoint in provider.endpoints:
            key = (provider.provider_id, endpoint.endpoint_id)
            if key in endpoint_by_key:
                raise validation_error("duplicate_catalog_endpoint", *key)
            if endpoint.descriptor_digest != model_endpoint_descriptor_digest(endpoint):
                raise validation_error("endpoint_descriptor_digest_mismatch", *key)
            pool_policy = traffic_policy_by_pool.get(endpoint.quota_pool_id)
            if pool_policy is not None and pool_policy != endpoint.traffic_policy:
                raise validation_error(
                    "quota_pool_traffic_policy_mismatch",
                    endpoint.quota_pool_id,
                )
            traffic_policy_by_pool[endpoint.quota_pool_id] = endpoint.traffic_policy
            endpoint_by_key[key] = endpoint

    for policy in snapshot.route_policies:
        for candidate in policy.candidate_endpoints:
            key = (candidate.provider_id, candidate.endpoint_id)
            endpoint = endpoint_by_key.get(key)
            if endpoint is None:
                raise validation_error("unknown_route_endpoint", *key)
            if not endpoint.enabled:
                raise validation_error("disabled_route_endpoint", *key)
            if (
                candidate.model_id != endpoint.model_id
                or candidate.endpoint_descriptor_digest != endpoint.descriptor_digest
                or candidate.tier is not endpoint.tier
            ):
                raise validation_error("route_endpoint_descriptor_mismatch", *key)
            _validate_candidate_capability(policy, endpoint)

    expected = str(
        routing_catalog_digest(
            snapshot.provider_descriptors,
            snapshot.route_policies,
        )
    )
    if snapshot.catalog_revision != expected:
        raise validation_error("routing_catalog_revision_mismatch")


def _validate_candidate_capability(
    policy: ModelRoutePolicy,
    endpoint: ModelEndpointDescriptor,
) -> None:
    capabilities = endpoint.capabilities
    if not policy.requirements.input_modalities <= capabilities.input_modalities:
        raise validation_error("route_input_capability_mismatch")
    if not policy.requirements.output_modalities <= capabilities.output_modalities:
        raise validation_error("route_output_capability_mismatch")
    if not _structured_supports(
        capabilities.native_structured_output,
        policy.requirements.minimum_native_structured_output,
    ):
        raise validation_error("route_structured_output_mismatch")
    if capabilities.max_context_tokens < policy.requirements.minimum_context_tokens:
        raise validation_error("route_context_capability_mismatch")
    if capabilities.max_output_tokens < policy.requirements.minimum_output_tokens:
        raise validation_error("route_output_limit_mismatch")
    if policy.requirements.reasoning_profile_id not in {
        item.profile_id for item in endpoint.reasoning_profiles
    }:
        raise validation_error("route_reasoning_profile_mismatch")
    if not policy.allowed_data_classes & endpoint.allowed_data_classes:
        raise validation_error("route_privacy_capability_mismatch")


def _structured_supports(
    actual: StructuredOutputSupport,
    required: StructuredOutputSupport,
) -> bool:
    allowed = {
        StructuredOutputSupport.NONE: {
            StructuredOutputSupport.NONE,
            StructuredOutputSupport.JSON_OBJECT,
            StructuredOutputSupport.JSON_SCHEMA,
        },
        StructuredOutputSupport.JSON_OBJECT: {
            StructuredOutputSupport.JSON_OBJECT,
            StructuredOutputSupport.JSON_SCHEMA,
        },
        StructuredOutputSupport.JSON_SCHEMA: {StructuredOutputSupport.JSON_SCHEMA},
    }
    return actual in allowed[required]


def _reject_fallback_cycles(
    tiers: frozenset[ModelTier],
    edges: tuple[TierFallbackEdge, ...],
) -> None:
    graph = {tier: set() for tier in tiers}
    for edge in edges:
        graph[edge.from_tier].add(edge.to_tier)
    visiting: set[ModelTier] = set()
    visited: set[ModelTier] = set()

    def visit(tier: ModelTier) -> None:
        if tier in visiting:
            raise validation_error("tier_fallback_cycle")
        if tier in visited:
            return
        visiting.add(tier)
        for target in graph[tier]:
            visit(target)
        visiting.remove(tier)
        visited.add(tier)

    for tier in tiers:
        visit(tier)


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _require_enum(value: object, expected: type[StrEnum], field: str) -> None:
    if not isinstance(value, expected):
        raise validation_error("invalid_enum", field)


def _positive_int(value: object, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise validation_error("invalid_positive_integer", field)


def _nonnegative_int(value: object, field: str) -> None:
    if type(value) is not int or value < 0:
        raise validation_error("invalid_nonnegative_integer", field)


def _nonnegative_decimal(value: object, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise validation_error("invalid_nonnegative_decimal", field)


def _rate(value: object, field: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise validation_error("invalid_rate", field)


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
    if len(materialized) != len(set(materialized)):
        raise validation_error("duplicate_identifier", field)
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
