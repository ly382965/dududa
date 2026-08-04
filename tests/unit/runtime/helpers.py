from __future__ import annotations

from decimal import Decimal

from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.models.contracts import ModelRole, ModelTier
from dududa.models.policy import (
    TierBudgetRequirement,
    TierPolicyDefinition,
)
from dududa.perception.complexity import default_complexity_assessor_config
from dududa.perception.contracts import GroupInteractionMode
from dududa.perception.social import SocialDecisionConfig
from dududa.runtime.contracts import OfflineRuntimePolicySnapshot


def revision(name: str, config: str = "cfg-v1") -> ComponentRevision:
    return ComponentRevision(
        name,
        "1.0.0",
        config,
        DigestString(f"artifact:{name}:{config}"),
    )


def runtime_policy(snapshot_id: str = "policy-v1") -> OfflineRuntimePolicySnapshot:
    assessor = default_complexity_assessor_config(revision("complexity-assessor"))
    return OfflineRuntimePolicySnapshot(
        schema_version=1,
        snapshot_id=snapshot_id,
        authorization_policy_revision="authorization-v1",
        group_mode=GroupInteractionMode.NORMAL,
        complexity_assessor=assessor,
        social_decision=SocialDecisionConfig("social-v1", 0.6),
        direct_chat_tier=TierPolicyDefinition(
            schema_version=1,
            policy_id="direct-chat-tier-policy",
            role=ModelRole.DIRECT_CHAT,
            allowed_tiers=frozenset(
                {ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS}
            ),
            default_tier=ModelTier.SONNET,
            low_complexity_tier=ModelTier.HAIKU,
            high_complexity_tier=ModelTier.OPUS,
            low_confidence_threshold=0.6,
            minimum_high_tier_confidence=0.85,
            minimum_high_complexity_signals=2,
            high_complexity_reason_codes=frozenset(
                {
                    "deep_reasoning",
                    "independent_verification",
                    "multi_constraint_synthesis",
                }
            ),
            tier_budget_requirements=(
                TierBudgetRequirement(
                    1,
                    ModelTier.HAIKU,
                    1,
                    1,
                    Decimal("0.1"),
                ),
                TierBudgetRequirement(
                    1,
                    ModelTier.SONNET,
                    1,
                    1,
                    Decimal("0.2"),
                ),
                TierBudgetRequirement(
                    1,
                    ModelTier.OPUS,
                    1,
                    1,
                    Decimal("0.3"),
                ),
            ),
            policy_revision="direct-chat-tier-v1",
        ),
    )
