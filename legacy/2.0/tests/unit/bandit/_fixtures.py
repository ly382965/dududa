from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.bandit import (
    BanditAction,
    BanditActionProbability,
    BanditContextEvidence,
    BanditDecision,
    BanditDecisionMode,
    BanditExecutionDisposition,
    BanditExecutionReceipt,
    BanditFeedback,
    BanditFeedbackDisposition,
    BanditOpePolicy,
    BanditOpeSample,
    BanditPolicyRef,
    BanditRewardComponent,
    BanditRoundingMode,
    BanditRouterEvidence,
    bandit_decision_digest,
    bandit_execution_receipt_digest,
    build_static_baseline_decision,
)
from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.models.contracts import (
    AdmissionDisposition,
    EndpointAdmissionRequest,
    EndpointAdmissionResult,
    EndpointCapacityLease,
    ModelEndpointRef,
    ModelInvocationEstimate,
    ModelRole,
    ModelTier,
)
from dududa.models.digests import model_invocation_estimate_digest

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def endpoint_ref(
    endpoint_id: str,
    *,
    provider_id: str = "provider-a",
    tier: ModelTier = ModelTier.SONNET,
    priority: int = 10,
) -> ModelEndpointRef:
    return ModelEndpointRef(
        schema_version=1,
        provider_id=provider_id,
        endpoint_id=endpoint_id,
        model_id=f"model-{endpoint_id}",
        endpoint_descriptor_digest=DigestString(f"descriptor:{endpoint_id}"),
        tier=tier,
        priority=priority,
    )


def actions() -> tuple[BanditAction, BanditAction]:
    return (
        BanditAction(1, "action-a", endpoint_ref("endpoint-a"), ModelRole.DIRECT_CHAT),
        BanditAction(1, "action-b", endpoint_ref("endpoint-b"), ModelRole.DIRECT_CHAT),
    )


def context() -> BanditContextEvidence:
    return BanditContextEvidence(
        1,
        "router-context",
        "v1",
        DigestString("feature-schema:digest"),
        DigestString("context-features:digest"),
        DigestString("evaluation-cluster:digest"),
    )


def router_evidence(planned: ModelEndpointRef | None = None) -> BanditRouterEvidence:
    return BanditRouterEvidence(
        1,
        "catalog-v1",
        DigestString("routing-catalog:digest"),
        "direct-chat",
        "route-policy-v1",
        DigestString("route-policy:digest"),
        "operational-v1",
        DigestString("operational:digest"),
        DigestString("model-request:fingerprint"),
        DigestString("route-plan:fingerprint"),
        planned or actions()[1].endpoint,
    )


def policy_ref() -> BanditPolicyRef:
    return BanditPolicyRef(1, "static-router", "v1", DigestString("policy:artifact"))


def reward_policy_ref() -> BanditPolicyRef:
    return BanditPolicyRef(
        1,
        "reward-v1",
        "v1",
        DigestString("reward-policy:digest"),
    )


def static_decision() -> BanditDecision:
    return build_static_baseline_decision(
        decision_id="decision-1",
        context=context(),
        router_evidence=router_evidence(),
        actions=actions(),
        behavior_policy=policy_ref(),
        decided_at=NOW,
    )


def synthetic_decision() -> BanditDecision:
    eligible = actions()
    return BanditDecision(
        schema_version=1,
        decision_id="decision-synthetic",
        mode=BanditDecisionMode.SYNTHETIC_EVALUATION,
        context=context(),
        router_evidence=router_evidence(),
        actions=eligible,
        behavior_policy=BanditPolicyRef(
            1,
            "synthetic-policy",
            "v1",
            DigestString("synthetic-policy:artifact"),
        ),
        distribution=(
            BanditActionProbability(1, "action-a", Decimal("0.6")),
            BanditActionProbability(1, "action-b", Decimal("0.4")),
        ),
        chosen_action_id="action-a",
        chosen_propensity=Decimal("0.6"),
        static_baseline_action_id="action-b",
        decided_at=NOW,
    )


def admission(endpoint: ModelEndpointRef) -> EndpointAdmissionResult:
    estimate = ModelInvocationEstimate(
        schema_version=1,
        model_request_digest=DigestString("model-request:digest"),
        endpoint_descriptor_digest=endpoint.endpoint_descriptor_digest,
        reasoning_profile_id="balanced",
        input_tokens_upper_bound=10,
        generated_tokens_upper_bound=20,
        reasoning_tokens_upper_bound=5,
        total_context_tokens_upper_bound=30,
        cost_units_upper_bound=Decimal("0.01"),
        estimator_revision=ComponentRevision(
            "estimator",
            "1.0.0",
            "v1",
            DigestString("estimator:artifact"),
        ),
    )
    request = EndpointAdmissionRequest(
        schema_version=1,
        reservation_id="reservation-1",
        model_request_id="model-request-1",
        model_request_digest=estimate.model_request_digest,
        provider_id=endpoint.provider_id,
        endpoint_id=endpoint.endpoint_id,
        endpoint_descriptor_digest=endpoint.endpoint_descriptor_digest,
        quota_pool_id="provider-main",
        traffic_policy_id="traffic-default",
        traffic_policy_revision="v1",
        operational_snapshot_id="operational-v1",
        operational_snapshot_digest=DigestString("operational:digest"),
        invocation_estimate_digest=model_invocation_estimate_digest(estimate),
        invocation_estimate=estimate,
        reserved_input_tokens=10,
        reserved_generated_tokens=20,
        reserved_reasoning_tokens=5,
        reserved_cost_units=Decimal("0.01"),
        expires_at=NOW + timedelta(minutes=10),
    )
    lease = EndpointCapacityLease(
        1,
        "lease-1",
        request,
        "admission-v1",
        NOW + timedelta(minutes=1),
    )
    return EndpointAdmissionResult(
        1,
        request,
        AdmissionDisposition.RESERVED,
        lease,
        "admission-v1",
        (),
        NOW + timedelta(minutes=2),
    )


def execution_receipt(
    decision: BanditDecision | None = None,
) -> BanditExecutionReceipt:
    selected_decision = decision or static_decision()
    selected = next(
        item
        for item in selected_decision.actions
        if item.action_id == selected_decision.chosen_action_id
    )
    return BanditExecutionReceipt(
        schema_version=1,
        receipt_id="execution-1",
        decision_id=selected_decision.decision_id,
        decision_digest=bandit_decision_digest(selected_decision),
        action_id=selected.action_id,
        disposition=BanditExecutionDisposition.EXECUTED,
        executed_endpoint=selected.endpoint,
        admission_result=admission(selected.endpoint),
        executed_at=NOW + timedelta(minutes=3),
        reason_codes=(),
        recorded_at=NOW + timedelta(minutes=4),
    )


def feedback(
    decision: BanditDecision | None = None,
    receipt: BanditExecutionReceipt | None = None,
) -> BanditFeedback:
    selected_decision = decision or static_decision()
    selected_receipt = receipt or execution_receipt(selected_decision)
    started = selected_receipt.executed_at
    assert started is not None
    return BanditFeedback(
        schema_version=1,
        feedback_id="feedback-1",
        decision_id=selected_decision.decision_id,
        decision_digest=bandit_decision_digest(selected_decision),
        execution_receipt_id=selected_receipt.receipt_id,
        execution_receipt_digest=bandit_execution_receipt_digest(selected_receipt),
        action_id=selected_receipt.action_id,
        disposition=BanditFeedbackDisposition.OBSERVED,
        reward_policy=reward_policy_ref(),
        observation_started_at=started,
        observation_ends_at=started + timedelta(minutes=10),
        components=(
            BanditRewardComponent(
                1,
                "task-success",
                "v1",
                Decimal(1),
                DigestString("feedback-provenance:digest"),
                started + timedelta(minutes=1),
            ),
        ),
        combined_reward=Decimal(1),
        reason_codes=(),
        recorded_at=started + timedelta(minutes=2),
    )


def ope_policy(
    *,
    floor: str = "0.10",
    maximum_weight: str = "10",
) -> BanditOpePolicy:
    return BanditOpePolicy(
        1,
        "ope-policy",
        "v1",
        Decimal(floor),
        Decimal(maximum_weight),
        12,
        BanditRoundingMode.HALF_EVEN,
    )


def distribution(a: str, b: str) -> tuple[BanditActionProbability, ...]:
    return (
        BanditActionProbability(1, "action-a", Decimal(a)),
        BanditActionProbability(1, "action-b", Decimal(b)),
    )


def ope_sample(
    sample_id: str,
    *,
    decision_id: str | None = None,
    action_id: str = "action-a",
    behavior: tuple[str, str] = ("0.5", "0.5"),
    evaluation: tuple[str, str] = ("0.75", "0.25"),
    reward: Decimal | None = Decimal(1),
    disposition: BanditFeedbackDisposition = BanditFeedbackDisposition.OBSERVED,
    logged_prediction: Decimal | None = Decimal("0.6"),
    evaluation_prediction: Decimal | None = Decimal("0.7"),
) -> BanditOpeSample:
    selected_index = 0 if action_id == "action-a" else 1
    selected_decision_id = decision_id or f"decision-{sample_id}"
    return BanditOpeSample(
        schema_version=1,
        sample_id=sample_id,
        decision_id=selected_decision_id,
        decision_digest=DigestString(f"{selected_decision_id}:digest"),
        action_id=action_id,
        feedback_disposition=disposition,
        behavior_distribution=distribution(*behavior),
        evaluation_distribution=distribution(*evaluation),
        behavior_propensity=Decimal(behavior[selected_index]),
        evaluation_probability=Decimal(evaluation[selected_index]),
        reward=reward,
        logged_action_prediction=logged_prediction,
        evaluation_expected_prediction=evaluation_prediction,
    )
