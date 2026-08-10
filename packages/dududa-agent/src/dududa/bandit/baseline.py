from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from dududa.domain.primitives import require_aware, require_non_empty
from dududa.errors import validation_error

from .contracts import (
    BanditAction,
    BanditActionProbability,
    BanditContextEvidence,
    BanditDecision,
    BanditDecisionMode,
    BanditPolicyRef,
    BanditRouterEvidence,
)


def build_static_baseline_decision(
    *,
    decision_id: str,
    context: BanditContextEvidence,
    router_evidence: BanditRouterEvidence,
    actions: tuple[BanditAction, ...],
    behavior_policy: BanditPolicyRef,
    decided_at: datetime,
) -> BanditDecision:
    require_non_empty(decision_id, "bandit_decision_id")
    require_aware(decided_at, "bandit_decided_at")
    ordered = tuple(sorted(actions, key=lambda action: action.action_id))
    if len(ordered) < 2:
        raise validation_error("bandit_requires_multiple_actions")
    matches = tuple(
        action
        for action in ordered
        if action.endpoint == router_evidence.planned_endpoint
    )
    if len(matches) != 1:
        raise validation_error("bandit_router_baseline_not_eligible")
    chosen = matches[0]
    return BanditDecision(
        schema_version=1,
        decision_id=decision_id,
        mode=BanditDecisionMode.STATIC_BASELINE,
        context=context,
        router_evidence=router_evidence,
        actions=ordered,
        behavior_policy=behavior_policy,
        distribution=tuple(
            BanditActionProbability(
                schema_version=1,
                action_id=action.action_id,
                probability=(
                    Decimal(1) if action.action_id == chosen.action_id else Decimal(0)
                ),
            )
            for action in ordered
        ),
        chosen_action_id=chosen.action_id,
        chosen_propensity=Decimal(1),
        static_baseline_action_id=chosen.action_id,
        decided_at=decided_at,
    )


__all__ = ["build_static_baseline_decision"]
