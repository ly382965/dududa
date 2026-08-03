from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.domain.task import TaskComplexityAssessment

from .contracts import (
    EndpointAdmissionRequest,
    EndpointAdmissionResult,
    EndpointCapacityReceipt,
    EndpointRejection,
    EndpointRouteCandidatePlan,
    ModelEndpointDescriptor,
    ModelEndpointRef,
    ModelInvocationEstimate,
    ModelOperationalSnapshot,
    ModelProviderDescriptor,
    ModelRequest,
    ModelRole,
    ModelTier,
    ProviderRequest,
    RouteDecision,
)
from .policy import (
    BootstrapTierDecision,
    ModelRoutePolicy,
    TierAuthority,
    TierDecision,
    TierPolicyDefinition,
    TierSelectionContext,
)


def task_complexity_assessment_digest(
    assessment: TaskComplexityAssessment,
) -> DigestString:
    return canonical_digest(assessment, domain="task:complexity-assessment:v1")


def task_complexity_assessment_fingerprint(
    assessment: TaskComplexityAssessment,
) -> DigestString:
    values = {
        name: getattr(assessment, name)
        for name in assessment.__dataclass_fields__
        if name != "assessment_id"
    }
    return canonical_digest(values, domain="task:complexity-assessment-plan:v1")


def tier_selection_context_digest(context: TierSelectionContext) -> DigestString:
    return canonical_digest(context, domain="model:tier-selection-context:v1")


def tier_policy_definition_digest(
    definition: TierPolicyDefinition,
) -> DigestString:
    return canonical_digest(definition, domain="model:tier-policy-definition:v1")


def tier_selection_fingerprint(
    context: TierSelectionContext,
    definition: TierPolicyDefinition,
) -> DigestString:
    return canonical_digest(
        {
            "role": context.role,
            "assessment_fingerprint": task_complexity_assessment_fingerprint(
                context.assessment
            ),
            "content_input_tokens_upper_bound": context.content_input_tokens_upper_bound,
            "data_classification": context.data_classification,
            "budget": context.budget,
            "tier_policy_digest": tier_policy_definition_digest(definition),
        },
        domain="model:tier-selection-plan:v1",
    )


def bootstrap_tier_selection_fingerprint(
    *,
    role: ModelRole,
    selected_tier: ModelTier,
    tier_policy_digest: DigestString,
    policy_revision: str,
    reason_codes: tuple[str, ...],
) -> DigestString:
    return canonical_digest(
        {
            "role": role,
            "selected_tier": selected_tier,
            "tier_policy_digest": tier_policy_digest,
            "policy_revision": policy_revision,
            "reason_codes": reason_codes,
        },
        domain="model:bootstrap-tier-selection-plan:v1",
    )


def tier_decision_digest(decision: TierDecision) -> DigestString:
    return canonical_digest(decision, domain="model:tier-decision:v1")


def bootstrap_tier_decision_digest(
    decision: BootstrapTierDecision,
) -> DigestString:
    return canonical_digest(decision, domain="model:bootstrap-tier-decision:v1")


def tier_authority_digest(authority: TierAuthority) -> DigestString:
    if isinstance(authority, BootstrapTierDecision):
        return bootstrap_tier_decision_digest(authority)
    return tier_decision_digest(authority)


def model_endpoint_descriptor_digest(
    descriptor: ModelEndpointDescriptor,
) -> DigestString:
    values = {
        name: getattr(descriptor, name)
        for name in descriptor.__dataclass_fields__
        if name != "descriptor_digest"
    }
    return canonical_digest(values, domain="model:endpoint-descriptor:v1")


def routing_catalog_digest(
    providers: tuple[ModelProviderDescriptor, ...],
    policies: tuple[ModelRoutePolicy, ...],
) -> DigestString:
    return canonical_digest(
        {
            "provider_descriptors": tuple(providers),
            "route_policies": tuple(policies),
        },
        domain="model:routing-catalog:v1",
    )


def model_request_digest(request: ModelRequest) -> DigestString:
    return canonical_digest(request, domain="model:request:v1")


def model_request_fingerprint(request: ModelRequest) -> DigestString:
    values = {
        name: getattr(request, name)
        for name in request.__dataclass_fields__
        if name not in {"request_id", "idempotency_key"}
    }
    return canonical_digest(values, domain="model:request-plan:v1")


def model_invocation_estimate_digest(
    estimate: ModelInvocationEstimate,
) -> DigestString:
    return canonical_digest(estimate, domain="model:invocation-estimate:v1")


def model_invocation_estimate_fingerprint(
    estimate: ModelInvocationEstimate,
) -> DigestString:
    values = {
        name: getattr(estimate, name)
        for name in estimate.__dataclass_fields__
        if name != "model_request_digest"
    }
    return canonical_digest(values, domain="model:invocation-estimate-plan:v1")


def model_operational_snapshot_digest(
    snapshot: ModelOperationalSnapshot,
) -> DigestString:
    return canonical_digest(snapshot, domain="model:operational-snapshot:v1")


def provider_request_digest(request: ProviderRequest) -> DigestString:
    return canonical_digest(request, domain="model:provider-request:v1")


def endpoint_admission_request_digest(
    request: EndpointAdmissionRequest,
) -> DigestString:
    return canonical_digest(request, domain="model:endpoint-admission-request:v1")


def endpoint_admission_result_digest(result: EndpointAdmissionResult) -> DigestString:
    return canonical_digest(result, domain="model:endpoint-admission-result:v1")


def endpoint_capacity_receipt_digest(
    receipt: EndpointCapacityReceipt,
) -> DigestString:
    return canonical_digest(receipt, domain="model:endpoint-capacity-receipt:v1")


def model_route_policy_digest(policy: ModelRoutePolicy) -> DigestString:
    return canonical_digest(policy, domain="model:route-policy:v1")


def route_decision_digest(decision: RouteDecision) -> DigestString:
    return canonical_digest(decision, domain="model:route-decision:v1")


def route_plan_fingerprint(
    *,
    model_request_fingerprint: DigestString,
    tier_selection_fingerprint: DigestString,
    requested_tier: ModelTier,
    catalog_revision: str,
    route_policy_digest: DigestString,
    output_schema_digest: DigestString | None,
    output_codec_revision: ComponentRevision | None,
    candidate_plans: tuple[EndpointRouteCandidatePlan, ...],
    rejected_endpoints: tuple[EndpointRejection, ...],
    planned_endpoint: ModelEndpointRef | None,
) -> DigestString:
    candidate_fingerprints = tuple(
        {
            "endpoint": candidate.endpoint,
            "estimate_fingerprint": model_invocation_estimate_fingerprint(
                candidate.estimate
            ),
            "reasoning_profile": candidate.reasoning_profile,
            "selected_data_residency": candidate.selected_data_residency,
            "required_retention_mode": candidate.required_retention_mode,
        }
        for candidate in candidate_plans
    )
    return canonical_digest(
        {
            "model_request_fingerprint": model_request_fingerprint,
            "tier_selection_fingerprint": tier_selection_fingerprint,
            "requested_tier": requested_tier,
            "catalog_revision": catalog_revision,
            "route_policy_digest": route_policy_digest,
            "output_schema_digest": output_schema_digest,
            "output_codec_revision": output_codec_revision,
            "candidate_plans": candidate_fingerprints,
            "rejected_endpoints": rejected_endpoints,
            "planned_endpoint": planned_endpoint,
        },
        domain="model:route-plan:v1",
    )
