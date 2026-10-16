from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from dududa._compat import StrEnum
from dududa.domain.primitives import DigestString, require_aware, require_non_empty
from dududa.errors import validation_error
from dududa.models.contracts import (
    AdmissionDisposition,
    EndpointAdmissionResult,
    ModelEndpointRef,
    ModelRole,
)


class BanditDecisionMode(StrEnum):
    STATIC_BASELINE = "static_baseline"
    SYNTHETIC_EVALUATION = "synthetic_evaluation"


class BanditExecutionDisposition(StrEnum):
    EXECUTED = "executed"
    NOT_EXECUTED = "not_executed"


class BanditFeedbackDisposition(StrEnum):
    OBSERVED = "observed"
    CENSORED = "censored"
    INVALID = "invalid"


class BanditRoundingMode(StrEnum):
    HALF_EVEN = "half_even"


@dataclass(frozen=True, slots=True)
class BanditAction:
    schema_version: int
    action_id: str
    endpoint: ModelEndpointRef
    role: ModelRole

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.action_id, "bandit_action_id")
        _instance(self.endpoint, ModelEndpointRef, "bandit_action_endpoint")
        _enum(self.role, ModelRole, "bandit_action_role")


@dataclass(frozen=True, slots=True)
class BanditContextEvidence:
    schema_version: int
    feature_schema_id: str
    feature_schema_revision: str
    feature_schema_digest: DigestString
    context_features_digest: DigestString
    evaluation_cluster_digest: DigestString | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.feature_schema_id, "bandit_feature_schema_id")
        require_non_empty(
            self.feature_schema_revision,
            "bandit_feature_schema_revision",
        )
        _digest(self.feature_schema_digest, "bandit_feature_schema_digest")
        _digest(self.context_features_digest, "bandit_context_features_digest")
        if self.evaluation_cluster_digest is not None:
            _digest(
                self.evaluation_cluster_digest,
                "bandit_evaluation_cluster_digest",
            )


@dataclass(frozen=True, slots=True)
class BanditRouterEvidence:
    schema_version: int
    catalog_revision: str
    routing_catalog_digest: DigestString
    route_policy_id: str
    route_policy_revision: str
    route_policy_digest: DigestString
    operational_snapshot_id: str
    operational_snapshot_digest: DigestString
    model_request_fingerprint: DigestString
    route_plan_fingerprint: DigestString
    planned_endpoint: ModelEndpointRef

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "catalog_revision",
            "route_policy_id",
            "route_policy_revision",
            "operational_snapshot_id",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        for field_name in (
            "routing_catalog_digest",
            "route_policy_digest",
            "operational_snapshot_digest",
            "model_request_fingerprint",
            "route_plan_fingerprint",
        ):
            _digest(getattr(self, field_name), field_name)
        _instance(
            self.planned_endpoint,
            ModelEndpointRef,
            "bandit_router_planned_endpoint",
        )


@dataclass(frozen=True, slots=True)
class BanditPolicyRef:
    schema_version: int
    policy_id: str
    policy_revision: str
    artifact_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.policy_id, "bandit_policy_id")
        require_non_empty(self.policy_revision, "bandit_policy_revision")
        _digest(self.artifact_digest, "bandit_policy_artifact_digest")


@dataclass(frozen=True, slots=True)
class BanditActionProbability:
    schema_version: int
    action_id: str
    probability: Decimal

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.action_id, "bandit_probability_action_id")
        _decimal_between_zero_and_one(
            self.probability,
            "bandit_action_probability",
        )


@dataclass(frozen=True, slots=True)
class BanditDecision:
    schema_version: int
    decision_id: str
    mode: BanditDecisionMode
    context: BanditContextEvidence
    router_evidence: BanditRouterEvidence
    actions: tuple[BanditAction, ...]
    behavior_policy: BanditPolicyRef
    distribution: tuple[BanditActionProbability, ...]
    chosen_action_id: str
    chosen_propensity: Decimal
    static_baseline_action_id: str
    decided_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.decision_id, "bandit_decision_id")
        _enum(self.mode, BanditDecisionMode, "bandit_decision_mode")
        _instance(self.context, BanditContextEvidence, "bandit_context")
        _instance(self.router_evidence, BanditRouterEvidence, "bandit_router_evidence")
        _instance(self.behavior_policy, BanditPolicyRef, "bandit_behavior_policy")
        require_non_empty(self.chosen_action_id, "bandit_chosen_action_id")
        require_non_empty(
            self.static_baseline_action_id,
            "bandit_static_baseline_action_id",
        )
        _positive_probability(self.chosen_propensity, "bandit_chosen_propensity")
        require_aware(self.decided_at, "bandit_decided_at")

        actions = tuple(self.actions)
        distribution = tuple(self.distribution)
        if len(actions) < 2 or any(
            not isinstance(item, BanditAction) for item in actions
        ):
            raise validation_error("bandit_requires_multiple_actions")
        if any(not isinstance(item, BanditActionProbability) for item in distribution):
            raise validation_error("invalid_bandit_distribution")
        actions = tuple(sorted(actions, key=lambda item: item.action_id))
        distribution = tuple(sorted(distribution, key=lambda item: item.action_id))
        action_ids = tuple(item.action_id for item in actions)
        endpoint_ids = tuple(
            (item.endpoint.provider_id, item.endpoint.endpoint_id) for item in actions
        )
        _unique(action_ids, "bandit_action_id")
        _unique(endpoint_ids, "bandit_action_endpoint")
        roles = {item.role for item in actions}
        tiers = {item.endpoint.tier for item in actions}
        if len(roles) != 1:
            raise validation_error("bandit_cross_role_actions")
        if len(tiers) != 1:
            raise validation_error("bandit_cross_tier_actions")

        probability_ids = tuple(item.action_id for item in distribution)
        _unique(probability_ids, "bandit_distribution_action_id")
        if set(probability_ids) != set(action_ids):
            raise validation_error("bandit_distribution_action_set_mismatch")
        probabilities = {item.action_id: item.probability for item in distribution}
        if sum(probabilities.values(), Decimal(0)) != Decimal(1):
            raise validation_error("bandit_distribution_sum_mismatch")
        if self.chosen_action_id not in probabilities:
            raise validation_error("bandit_chosen_action_not_eligible")
        if probabilities[self.chosen_action_id] != self.chosen_propensity:
            raise validation_error("bandit_chosen_propensity_mismatch")

        baseline_matches = tuple(
            item.action_id
            for item in actions
            if item.endpoint == self.router_evidence.planned_endpoint
        )
        if len(baseline_matches) != 1:
            raise validation_error("bandit_router_baseline_not_eligible")
        baseline = baseline_matches[0]
        if self.static_baseline_action_id != baseline:
            raise validation_error("bandit_static_baseline_mismatch")
        if self.mode is BanditDecisionMode.STATIC_BASELINE:
            if self.chosen_action_id != baseline or any(
                probability != (Decimal(1) if action_id == baseline else Decimal(0))
                for action_id, probability in probabilities.items()
            ):
                raise validation_error("invalid_bandit_static_distribution")
        elif any(probability <= 0 for probability in probabilities.values()):
            raise validation_error("bandit_synthetic_support_missing")

        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "distribution", distribution)


@dataclass(frozen=True, slots=True)
class BanditExecutionReceipt:
    schema_version: int
    receipt_id: str
    decision_id: str
    decision_digest: DigestString
    action_id: str
    disposition: BanditExecutionDisposition
    executed_endpoint: ModelEndpointRef | None
    admission_result: EndpointAdmissionResult | None
    executed_at: datetime | None
    reason_codes: tuple[str, ...]
    recorded_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.receipt_id, "bandit_execution_receipt_id")
        require_non_empty(self.decision_id, "bandit_execution_decision_id")
        _digest(self.decision_digest, "bandit_execution_decision_digest")
        require_non_empty(self.action_id, "bandit_execution_action_id")
        _enum(
            self.disposition,
            BanditExecutionDisposition,
            "bandit_execution_disposition",
        )
        require_aware(self.recorded_at, "bandit_execution_recorded_at")
        reason_codes = _reason_codes(self.reason_codes, required=False)
        if self.disposition is BanditExecutionDisposition.EXECUTED:
            _instance(
                self.executed_endpoint,
                ModelEndpointRef,
                "bandit_executed_endpoint",
            )
            if self.admission_result is None or self.executed_at is None:
                raise validation_error("bandit_executed_evidence_missing")
            _instance(
                self.admission_result,
                EndpointAdmissionResult,
                "bandit_admission_result",
            )
            if self.admission_result.disposition is not AdmissionDisposition.RESERVED:
                raise validation_error("bandit_execution_admission_not_reserved")
            require_aware(self.executed_at, "bandit_executed_at")
            if self.executed_at > self.recorded_at:
                raise validation_error("bandit_execution_time_order_invalid")
            if reason_codes:
                raise validation_error("bandit_executed_has_reason_codes")
        else:
            if self.executed_endpoint is not None or self.executed_at is not None:
                raise validation_error("bandit_unexecuted_has_execution")
            if self.admission_result is not None:
                _instance(
                    self.admission_result,
                    EndpointAdmissionResult,
                    "bandit_admission_result",
                )
            if not reason_codes:
                raise validation_error("bandit_unexecuted_reason_missing")
        object.__setattr__(self, "reason_codes", reason_codes)


@dataclass(frozen=True, slots=True)
class BanditRewardComponent:
    schema_version: int
    component_id: str
    component_revision: str
    value: Decimal
    provenance_digest: DigestString
    observed_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.component_id, "bandit_reward_component_id")
        require_non_empty(
            self.component_revision,
            "bandit_reward_component_revision",
        )
        _finite_decimal(self.value, "bandit_reward_component_value")
        _digest(self.provenance_digest, "bandit_reward_provenance_digest")
        require_aware(self.observed_at, "bandit_reward_observed_at")


@dataclass(frozen=True, slots=True)
class BanditFeedback:
    schema_version: int
    feedback_id: str
    decision_id: str
    decision_digest: DigestString
    execution_receipt_id: str
    execution_receipt_digest: DigestString
    action_id: str
    disposition: BanditFeedbackDisposition
    reward_policy: BanditPolicyRef
    observation_started_at: datetime
    observation_ends_at: datetime
    components: tuple[BanditRewardComponent, ...]
    combined_reward: Decimal | None
    reason_codes: tuple[str, ...]
    recorded_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "feedback_id",
            "decision_id",
            "execution_receipt_id",
            "action_id",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        for field_name in (
            "decision_digest",
            "execution_receipt_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        _instance(self.reward_policy, BanditPolicyRef, "bandit_reward_policy")
        _enum(
            self.disposition, BanditFeedbackDisposition, "bandit_feedback_disposition"
        )
        require_aware(self.observation_started_at, "bandit_observation_started_at")
        require_aware(self.observation_ends_at, "bandit_observation_ends_at")
        require_aware(self.recorded_at, "bandit_feedback_recorded_at")
        if self.observation_ends_at <= self.observation_started_at:
            raise validation_error("invalid_bandit_observation_window")
        if self.recorded_at < self.observation_started_at:
            raise validation_error("bandit_feedback_precedes_observation_window")
        components = tuple(self.components)
        if any(not isinstance(item, BanditRewardComponent) for item in components):
            raise validation_error("invalid_bandit_reward_component")
        _unique(
            tuple(item.component_id for item in components),
            "bandit_reward_component_id",
        )
        if self.combined_reward is not None:
            _finite_decimal(self.combined_reward, "bandit_combined_reward")
        reason_codes = _reason_codes(self.reason_codes, required=False)

        if self.disposition is BanditFeedbackDisposition.OBSERVED:
            if not components:
                raise validation_error("bandit_observed_feedback_empty")
            if reason_codes:
                raise validation_error("bandit_observed_feedback_has_reason_codes")
            if self.recorded_at > self.observation_ends_at:
                raise validation_error("bandit_feedback_after_window")
            for component in components:
                if not (
                    self.observation_started_at
                    <= component.observed_at
                    <= self.recorded_at
                ):
                    raise validation_error("bandit_reward_outside_window")
        else:
            if components or self.combined_reward is not None:
                raise validation_error("bandit_nonobserved_feedback_has_reward")
            if not reason_codes:
                raise validation_error("bandit_feedback_reason_missing")
            if (
                self.disposition is BanditFeedbackDisposition.CENSORED
                and self.recorded_at < self.observation_ends_at
            ):
                raise validation_error("bandit_censoring_before_window_end")
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "reason_codes", reason_codes)


@dataclass(frozen=True, slots=True)
class BanditOpeSample:
    schema_version: int
    sample_id: str
    decision_id: str
    decision_digest: DigestString
    action_id: str
    feedback_disposition: BanditFeedbackDisposition
    behavior_distribution: tuple[BanditActionProbability, ...]
    evaluation_distribution: tuple[BanditActionProbability, ...]
    behavior_propensity: Decimal
    evaluation_probability: Decimal
    reward: Decimal | None
    logged_action_prediction: Decimal | None
    evaluation_expected_prediction: Decimal | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in ("sample_id", "decision_id", "action_id"):
            require_non_empty(getattr(self, field_name), field_name)
        _digest(self.decision_digest, "bandit_ope_decision_digest")
        _enum(
            self.feedback_disposition,
            BanditFeedbackDisposition,
            "bandit_ope_feedback_disposition",
        )
        _decimal_between_zero_and_one(
            self.behavior_propensity,
            "bandit_behavior_propensity",
        )
        _decimal_between_zero_and_one(
            self.evaluation_probability,
            "bandit_evaluation_probability",
        )
        behavior = tuple(self.behavior_distribution)
        evaluation = tuple(self.evaluation_distribution)
        for field_name, distribution in (
            ("behavior_distribution", behavior),
            ("evaluation_distribution", evaluation),
        ):
            if len(distribution) < 2 or any(
                not isinstance(item, BanditActionProbability) for item in distribution
            ):
                raise validation_error("invalid_bandit_ope_distribution", field_name)
            action_ids = tuple(item.action_id for item in distribution)
            _unique(action_ids, f"bandit_ope_{field_name}_action_id")
            if sum((item.probability for item in distribution), Decimal(0)) != Decimal(
                1
            ):
                raise validation_error(
                    "bandit_ope_distribution_sum_mismatch", field_name
                )
        if {item.action_id for item in behavior} != {
            item.action_id for item in evaluation
        }:
            raise validation_error("bandit_ope_action_set_mismatch")
        behavior_by_id = {item.action_id: item.probability for item in behavior}
        evaluation_by_id = {item.action_id: item.probability for item in evaluation}
        if self.action_id not in behavior_by_id:
            raise validation_error("bandit_ope_logged_action_not_found")
        if behavior_by_id[self.action_id] != self.behavior_propensity:
            raise validation_error("bandit_ope_behavior_propensity_mismatch")
        if evaluation_by_id[self.action_id] != self.evaluation_probability:
            raise validation_error("bandit_ope_evaluation_probability_mismatch")
        for field_name in (
            "reward",
            "logged_action_prediction",
            "evaluation_expected_prediction",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _finite_decimal(value, f"bandit_ope_{field_name}")
        object.__setattr__(
            self,
            "behavior_distribution",
            tuple(sorted(behavior, key=lambda item: item.action_id)),
        )
        object.__setattr__(
            self,
            "evaluation_distribution",
            tuple(sorted(evaluation, key=lambda item: item.action_id)),
        )


@dataclass(frozen=True, slots=True)
class BanditOpePolicy:
    schema_version: int
    policy_id: str
    policy_revision: str
    minimum_behavior_propensity: Decimal
    maximum_importance_weight: Decimal
    decimal_places: int
    rounding_mode: BanditRoundingMode

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.policy_id, "bandit_ope_policy_id")
        require_non_empty(self.policy_revision, "bandit_ope_policy_revision")
        _positive_probability(
            self.minimum_behavior_propensity,
            "bandit_minimum_behavior_propensity",
        )
        _finite_decimal(
            self.maximum_importance_weight,
            "bandit_maximum_importance_weight",
        )
        if self.maximum_importance_weight <= 0:
            raise validation_error("invalid_bandit_maximum_importance_weight")
        if type(self.decimal_places) is not int or not 0 <= self.decimal_places <= 18:
            raise validation_error("invalid_bandit_decimal_places")
        _enum(self.rounding_mode, BanditRoundingMode, "bandit_rounding_mode")


@dataclass(frozen=True, slots=True)
class BanditOpeValidationIssue:
    schema_version: int
    sample_id: str
    reason_code: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.sample_id, "bandit_ope_issue_sample_id")
        require_non_empty(self.reason_code, "bandit_ope_issue_reason_code")


@dataclass(frozen=True, slots=True)
class BanditOpeValidationReport:
    schema_version: int
    sample_count: int
    support_coverage: Decimal
    reward_coverage: Decimal
    issues: tuple[BanditOpeValidationIssue, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if type(self.sample_count) is not int or self.sample_count < 0:
            raise validation_error("invalid_bandit_ope_sample_count")
        _decimal_between_zero_and_one(self.support_coverage, "support_coverage")
        _decimal_between_zero_and_one(self.reward_coverage, "reward_coverage")
        issues = tuple(self.issues)
        if any(not isinstance(item, BanditOpeValidationIssue) for item in issues):
            raise validation_error("invalid_bandit_ope_issue")
        object.__setattr__(self, "issues", issues)

    @property
    def valid(self) -> bool:
        return not self.issues and self.sample_count > 0

    @property
    def offending_sample_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.sample_id for item in self.issues}))


@dataclass(frozen=True, slots=True)
class BanditOpeReport:
    schema_version: int
    policy_id: str
    policy_revision: str
    policy_digest: DigestString
    sample_set_digest: DigestString
    sample_count: int
    support_coverage: Decimal
    reward_coverage: Decimal
    minimum_behavior_propensity: Decimal
    maximum_importance_weight: Decimal
    ips: Decimal
    snips: Decimal
    doubly_robust: Decimal
    effective_sample_size: Decimal

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.policy_id, "bandit_ope_report_policy_id")
        require_non_empty(self.policy_revision, "bandit_ope_report_policy_revision")
        _digest(self.policy_digest, "bandit_ope_report_policy_digest")
        _digest(self.sample_set_digest, "bandit_ope_report_sample_set_digest")
        if type(self.sample_count) is not int or self.sample_count < 1:
            raise validation_error("invalid_bandit_ope_report_sample_count")
        for field_name in (
            "support_coverage",
            "reward_coverage",
        ):
            _decimal_between_zero_and_one(getattr(self, field_name), field_name)
        _positive_probability(
            self.minimum_behavior_propensity,
            "minimum_behavior_propensity",
        )
        _finite_decimal(self.maximum_importance_weight, "maximum_importance_weight")
        if self.maximum_importance_weight <= 0:
            raise validation_error("invalid_bandit_report_importance_weight")
        for field_name in ("ips", "snips", "doubly_robust"):
            _finite_decimal(getattr(self, field_name), field_name)
        _finite_decimal(self.effective_sample_size, "effective_sample_size")
        if not Decimal(0) < self.effective_sample_size <= Decimal(self.sample_count):
            raise validation_error("invalid_bandit_effective_sample_size")


def _v1(value: object) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _instance(value: object, expected: type[object], field: str) -> None:
    if not isinstance(value, expected):
        raise validation_error("invalid_nested_contract", field)


def _enum(value: object, expected: type[StrEnum], field: str) -> None:
    if not isinstance(value, expected):
        raise validation_error("invalid_enum", field)


def _digest(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise validation_error("invalid_digest", field)
    require_non_empty(value, field)


def _finite_decimal(value: object, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise validation_error("invalid_finite_decimal", field)


def _decimal_between_zero_and_one(value: object, field: str) -> None:
    _finite_decimal(value, field)
    if not Decimal(0) <= value <= Decimal(1):
        raise validation_error("decimal_out_of_range", field)


def _positive_probability(value: object, field: str) -> None:
    _decimal_between_zero_and_one(value, field)
    if value <= 0:
        raise validation_error("nonpositive_probability", field)


def _unique(values: tuple[object, ...], field: str) -> None:
    if len(values) != len(set(values)):
        raise validation_error("duplicate_identifier", field)


def _reason_codes(values: object, *, required: bool) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_string_collection", "reason_codes")
    materialized = tuple(values)  # type: ignore[arg-type]
    if required and not materialized:
        raise validation_error("empty_collection", "reason_codes")
    if any(not isinstance(value, str) or not value.strip() for value in materialized):
        raise validation_error("invalid_reason_codes")
    _unique(materialized, "reason_codes")
    return materialized


__all__ = [
    "BanditAction",
    "BanditActionProbability",
    "BanditContextEvidence",
    "BanditDecision",
    "BanditDecisionMode",
    "BanditExecutionDisposition",
    "BanditExecutionReceipt",
    "BanditFeedback",
    "BanditFeedbackDisposition",
    "BanditOpePolicy",
    "BanditOpeReport",
    "BanditOpeSample",
    "BanditOpeValidationIssue",
    "BanditOpeValidationReport",
    "BanditPolicyRef",
    "BanditRewardComponent",
    "BanditRoundingMode",
    "BanditRouterEvidence",
]
