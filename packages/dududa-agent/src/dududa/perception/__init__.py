"""Validated semantic perception, complexity and social-policy contracts."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .complexity import (
        ComplexityAssessorConfig,
        DeterministicComplexityAssessor,
        default_complexity_assessor_config,
    )
    from .contracts import (
        AmbiguityCandidate,
        AmbiguityKind,
        AuthorizationView,
        ClarificationKey,
        ComplexitySignal,
        ComplexitySignalCode,
        DecisionSignals,
        EntityCandidate,
        EntityKind,
        EvidenceSource,
        GroupInteractionMode,
        IntentCandidate,
        ModelPerceptionProjection,
        PerceptionContext,
        PerceptionIdentity,
        PerceptionLimits,
        PerceptionMessage,
        PerceptionModelStatus,
        PerceptionResult,
        ReferenceCandidate,
        ReferenceKind,
        RulePerceptionResult,
        SocialAction,
        SocialDecision,
        SpeechAct,
        TopicCandidate,
    )
    from .rules import (
        DeterministicRulePerception,
        RulePerceptionConfig,
        default_rule_perception_config,
    )
    from .merge import DeterministicPerceptionMerger, PerceptionMergeConfig
    from .social import (
        DeterministicSocialDecisionPolicy,
        SocialDecisionConfig,
    )

__all__ = [
    "AmbiguityCandidate",
    "AmbiguityKind",
    "AuthorizationView",
    "ClarificationKey",
    "ComplexitySignal",
    "ComplexitySignalCode",
    "ComplexityAssessorConfig",
    "DecisionSignals",
    "DeterministicRulePerception",
    "DeterministicSocialDecisionPolicy",
    "DeterministicPerceptionMerger",
    "DeterministicComplexityAssessor",
    "EntityCandidate",
    "EntityKind",
    "EvidenceSource",
    "GroupInteractionMode",
    "IntentCandidate",
    "ModelPerceptionProjection",
    "PerceptionContext",
    "PerceptionIdentity",
    "PerceptionLimits",
    "PerceptionMergeConfig",
    "PerceptionMessage",
    "PerceptionModelStatus",
    "PerceptionResult",
    "ReferenceCandidate",
    "ReferenceKind",
    "RulePerceptionResult",
    "RulePerceptionConfig",
    "SocialAction",
    "SocialDecision",
    "SocialDecisionConfig",
    "SpeechAct",
    "TopicCandidate",
    "model_perception_projection_digest",
    "model_perception_projection_fingerprint",
    "model_projection_schema",
    "model_projection_schema_ref",
    "perception_context_digest",
    "perception_context_fingerprint",
    "perception_result_digest",
    "perception_result_fingerprint",
    "rule_perception_result_digest",
    "rule_perception_result_fingerprint",
    "social_decision_digest",
    "social_decision_fingerprint",
    "default_rule_perception_config",
    "default_complexity_assessor_config",
    "validate_model_projection",
    "validate_perception_result",
    "validate_rule_result",
]

_CONTRACT_EXPORTS = {
    "AmbiguityCandidate",
    "AmbiguityKind",
    "AuthorizationView",
    "ClarificationKey",
    "ComplexitySignal",
    "ComplexitySignalCode",
    "DecisionSignals",
    "EntityCandidate",
    "EntityKind",
    "EvidenceSource",
    "GroupInteractionMode",
    "IntentCandidate",
    "ModelPerceptionProjection",
    "PerceptionContext",
    "PerceptionIdentity",
    "PerceptionLimits",
    "PerceptionMessage",
    "PerceptionModelStatus",
    "PerceptionResult",
    "ReferenceCandidate",
    "ReferenceKind",
    "RulePerceptionResult",
    "SocialAction",
    "SocialDecision",
    "SpeechAct",
    "TopicCandidate",
}


def __getattr__(name: str) -> object:
    if name in {
        "DeterministicSocialDecisionPolicy",
        "SocialDecisionConfig",
    }:
        return getattr(import_module(".social", __name__), name)
    if name in {
        "ComplexityAssessorConfig",
        "DeterministicComplexityAssessor",
        "default_complexity_assessor_config",
    }:
        return getattr(import_module(".complexity", __name__), name)
    if name in _CONTRACT_EXPORTS:
        return getattr(import_module(".contracts", __name__), name)
    if name in {
        "DeterministicPerceptionMerger",
        "PerceptionMergeConfig",
    }:
        return getattr(import_module(".merge", __name__), name)
    if name in {
        "DeterministicRulePerception",
        "RulePerceptionConfig",
        "default_rule_perception_config",
    }:
        return getattr(import_module(".rules", __name__), name)
    if name in set(__all__) - _CONTRACT_EXPORTS:
        module_name = ".digests"
        if name in {"model_projection_schema", "model_projection_schema_ref"}:
            module_name = ".schema"
        elif name in {
            "validate_model_projection",
            "validate_perception_result",
            "validate_rule_result",
        }:
            module_name = ".validation"
        return getattr(import_module(module_name, __name__), name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
