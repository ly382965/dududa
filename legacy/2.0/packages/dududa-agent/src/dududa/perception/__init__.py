"""Validated semantic perception, complexity and social-policy contracts."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .complexity import (
        ComplexityAssessorConfig,
        DeterministicComplexityAssessor,
        default_complexity_assessor_config,
        validate_task_complexity_assessment,
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
        validate_social_decision,
    )
    from .semantic import (
        EntityMention,
        IntentCandidateV2,
        ReferenceLinkSource,
        ReferenceMention,
        SemanticDecision,
        SemanticDecisionAction,
        SemanticProjectionV2,
        TextOffsetUnit,
        TextSpan,
        VersionedModelPerceptionProjection,
        normalized_codepoint_offset,
        normalized_codepoint_span,
        normalized_text,
        semantic_projection_digest,
        semantic_text_digest,
        versioned_model_projection_digest,
    )
    from .semantic_schema import (
        decode_versioned_model_projection,
        encode_versioned_model_projection,
        model_projection_v2_schema,
        model_projection_v2_schema_ref,
    )
    from .semantic_validation import validate_versioned_model_projection

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
    "EntityMention",
    "EvidenceSource",
    "GroupInteractionMode",
    "IntentCandidate",
    "IntentCandidateV2",
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
    "ReferenceLinkSource",
    "ReferenceMention",
    "RulePerceptionResult",
    "RulePerceptionConfig",
    "SocialAction",
    "SocialDecision",
    "SocialDecisionConfig",
    "SpeechAct",
    "SemanticDecision",
    "SemanticDecisionAction",
    "SemanticProjectionV2",
    "TextOffsetUnit",
    "TextSpan",
    "TopicCandidate",
    "VersionedModelPerceptionProjection",
    "decode_versioned_model_projection",
    "encode_versioned_model_projection",
    "model_perception_projection_digest",
    "model_perception_projection_fingerprint",
    "model_projection_schema",
    "model_projection_schema_ref",
    "model_projection_v2_schema",
    "model_projection_v2_schema_ref",
    "normalized_codepoint_offset",
    "normalized_codepoint_span",
    "normalized_text",
    "perception_context_digest",
    "perception_context_fingerprint",
    "perception_result_digest",
    "perception_result_fingerprint",
    "rule_perception_result_digest",
    "rule_perception_result_fingerprint",
    "social_decision_digest",
    "social_decision_fingerprint",
    "semantic_projection_digest",
    "semantic_text_digest",
    "versioned_model_projection_digest",
    "default_rule_perception_config",
    "default_complexity_assessor_config",
    "validate_model_projection",
    "validate_perception_result",
    "validate_rule_result",
    "validate_social_decision",
    "validate_task_complexity_assessment",
    "validate_versioned_model_projection",
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

_SEMANTIC_EXPORTS = {
    "EntityMention",
    "IntentCandidateV2",
    "ReferenceLinkSource",
    "ReferenceMention",
    "SemanticDecision",
    "SemanticDecisionAction",
    "SemanticProjectionV2",
    "TextOffsetUnit",
    "TextSpan",
    "VersionedModelPerceptionProjection",
    "normalized_codepoint_offset",
    "normalized_codepoint_span",
    "normalized_text",
    "semantic_projection_digest",
    "semantic_text_digest",
    "versioned_model_projection_digest",
}

_SEMANTIC_SCHEMA_EXPORTS = {
    "decode_versioned_model_projection",
    "encode_versioned_model_projection",
    "model_projection_v2_schema",
    "model_projection_v2_schema_ref",
}


def __getattr__(name: str) -> object:
    if name in {
        "DeterministicSocialDecisionPolicy",
        "SocialDecisionConfig",
        "validate_social_decision",
    }:
        return getattr(import_module(".social", __name__), name)
    if name in {
        "ComplexityAssessorConfig",
        "DeterministicComplexityAssessor",
        "default_complexity_assessor_config",
        "validate_task_complexity_assessment",
    }:
        return getattr(import_module(".complexity", __name__), name)
    if name in _CONTRACT_EXPORTS:
        return getattr(import_module(".contracts", __name__), name)
    if name in _SEMANTIC_EXPORTS:
        return getattr(import_module(".semantic", __name__), name)
    if name in _SEMANTIC_SCHEMA_EXPORTS:
        return getattr(import_module(".semantic_schema", __name__), name)
    if name == "validate_versioned_model_projection":
        return getattr(import_module(".semantic_validation", __name__), name)
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
    if name in (
        set(__all__)
        - _CONTRACT_EXPORTS
        - _SEMANTIC_EXPORTS
        - _SEMANTIC_SCHEMA_EXPORTS
        - {"validate_versioned_model_projection"}
    ):
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
