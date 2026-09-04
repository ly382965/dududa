from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dududa.domain.primitives import ResponseConstraints
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import PortCallContext

from .contracts import (
    ClarificationKey,
    DecisionSignals,
    GroupInteractionMode,
    PerceptionResult,
    SocialAction,
    SocialDecision,
)
from .digests import perception_result_digest


@dataclass(frozen=True, slots=True)
class SocialDecisionConfig:
    policy_revision: str
    clarification_confidence_threshold: float
    response_constraints: ResponseConstraints = field(
        default_factory=ResponseConstraints
    )

    def __post_init__(self) -> None:
        if not self.policy_revision.strip():
            raise ValueError("invalid Social Decision policy revision")
        value = self.clarification_confidence_threshold
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 1
        ):
            raise ValueError("invalid clarification confidence threshold")
        if not isinstance(self.response_constraints, ResponseConstraints):
            raise TypeError("invalid Social Decision response constraints")


class DeterministicSocialDecisionPolicy:
    def __init__(
        self,
        config: SocialDecisionConfig,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, SocialDecisionConfig):
            raise TypeError("invalid Social Decision config")
        self._config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def decide(
        self,
        perception: PerceptionResult,
        signals: DecisionSignals,
        *,
        call: PortCallContext,
    ) -> SocialDecision:
        if not isinstance(perception, PerceptionResult):
            raise validation_error("invalid_perception_result")
        if not isinstance(signals, DecisionSignals):
            raise validation_error("invalid_decision_signals")
        now = self._clock()
        if call.cancellation.is_cancelled:
            raise error(
                "social_decision_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if call.deadline <= now:
            raise error(
                "social_decision_deadline_exceeded",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )

        action, reasons, targets, clarification_key, confidence = (
            _social_decision_values(perception, signals, self._config)
        )
        return SocialDecision(
            schema_version=1,
            decision_id=self._id_factory(),
            perception_result_digest=perception_result_digest(perception),
            action=action,
            confidence=confidence,
            reason_codes=reasons,
            target_identity_refs=targets,
            clarification_key=clarification_key,
            response_constraints=self._config.response_constraints,
            policy_revision=self._config.policy_revision,
            decided_at=now,
        )


def validate_social_decision(
    decision: SocialDecision,
    perception: PerceptionResult,
    signals: DecisionSignals,
    config: SocialDecisionConfig,
) -> SocialDecision:
    """Validate the stable policy result without replaying clock or cancellation."""

    if not isinstance(decision, SocialDecision):
        raise validation_error("invalid_social_decision")
    if not isinstance(perception, PerceptionResult):
        raise validation_error("invalid_perception_result")
    if not isinstance(signals, DecisionSignals):
        raise validation_error("invalid_decision_signals")
    if not isinstance(config, SocialDecisionConfig):
        raise validation_error("invalid_social_decision_config")
    action, reasons, targets, clarification_key, confidence = _social_decision_values(
        perception,
        signals,
        config,
    )
    expected = SocialDecision(
        schema_version=1,
        decision_id=decision.decision_id,
        perception_result_digest=perception_result_digest(perception),
        action=action,
        confidence=confidence,
        reason_codes=reasons,
        target_identity_refs=targets,
        clarification_key=clarification_key,
        response_constraints=config.response_constraints,
        policy_revision=config.policy_revision,
        decided_at=decision.decided_at,
    )
    if decision != expected:
        raise validation_error("social_decision_binding_mismatch")
    return decision


def _social_decision_values(
    perception: PerceptionResult,
    signals: DecisionSignals,
    config: SocialDecisionConfig,
) -> tuple[
    SocialAction,
    tuple[str, ...],
    tuple[str, ...],
    ClarificationKey | None,
    float,
]:
    action: SocialAction
    reasons: tuple[str, ...]
    proactive_group = (
        not signals.explicit_interaction
        and not signals.private_conversation
        and signals.group_mode is GroupInteractionMode.ACTIVE
    )
    if signals.duplicate_or_self_message:
        action = SocialAction.IGNORE
        reasons = ("duplicate_or_self_message",)
    elif not proactive_group and (
        not signals.known_target or not perception.target_identity_refs
    ):
        action = SocialAction.IGNORE
        reasons = ("unknown_response_target",)
    elif not signals.authorization.can_respond:
        action = SocialAction.IGNORE
        reasons = ("response_not_authorized",)
    elif signals.rate_limited:
        action = SocialAction.IGNORE
        reasons = ("interaction_rate_limited",)
    elif proactive_group and signals.private_data_boundary:
        action = SocialAction.IGNORE
        reasons = ("proactive_group_private_data_skipped",)
    elif proactive_group and perception.need_tools:
        action = SocialAction.IGNORE
        reasons = ("proactive_group_tool_use_skipped",)
    elif proactive_group and perception.ambiguities:
        action = SocialAction.IGNORE
        reasons = ("proactive_group_clarification_skipped",)
    elif proactive_group and perception.conflicting_evidence:
        action = SocialAction.IGNORE
        reasons = ("proactive_group_conflict_skipped",)
    elif signals.private_data_boundary:
        action = SocialAction.DEFER
        reasons = ("private_data_boundary",)
    elif (
        not signals.explicit_interaction
        and not signals.private_conversation
        and not proactive_group
    ):
        action = SocialAction.IGNORE
        reasons = ("no_explicit_interaction",)
    elif perception.need_tools:
        if not signals.authorization.can_use_tools:
            action = SocialAction.DEFER
            reasons = ("tool_use_not_authorized",)
        elif not signals.tools_enabled:
            action = SocialAction.DEFER
            reasons = ("tools_disabled",)
        else:
            action = SocialAction.USE_TOOLS
            reasons = ("bounded_tool_execution",)
    else:
        clarification = next(
            (
                ambiguity.clarification_key
                for ambiguity in perception.ambiguities
                if ambiguity.clarification_key is not None
            ),
            None,
        )
        if clarification is not None and (
            perception.conflicting_evidence
            or perception.confidence < config.clarification_confidence_threshold
            or perception.ambiguities
        ):
            action = SocialAction.ASK_CLARIFICATION
            reasons = ("bounded_clarification_required",)
        elif perception.conflicting_evidence:
            action = SocialAction.DEFER
            # Carry only fixed diagnostic codes into the terminal HTTP result.
            reasons = (
                "conflicting_evidence_without_clarification",
                *(code for code in (
                    "rule_model_conflict_task_kind",
                    "rule_model_conflict_targets",
                    "rule_model_conflict_tools",
                    "rule_model_conflict_depth",
                ) if code in perception.reason_codes),
            )
        else:
            action = SocialAction.DIRECT_REPLY
            reasons = (
                ("proactive_group_direct_reply",)
                if proactive_group
                else ("explicit_direct_reply",)
            )

    targets = (
        ()
        if proactive_group
        else perception.target_identity_refs
        if action is not SocialAction.IGNORE
        else ()
    )
    clarification_key = None
    if action is SocialAction.ASK_CLARIFICATION:
        clarification_key = next(
            ambiguity.clarification_key
            for ambiguity in perception.ambiguities
            if ambiguity.clarification_key is not None
        )
    confidence = (
        1.0
        if action in {SocialAction.IGNORE, SocialAction.DEFER}
        else perception.confidence
    )
    return action, reasons, targets, clarification_key, confidence
