from __future__ import annotations

from collections.abc import Iterable

from dududa.errors import validation_error

from .contracts import (
    AmbiguityCandidate,
    ComplexitySignal,
    EntityCandidate,
    IntentCandidate,
    ModelPerceptionProjection,
    PerceptionContext,
    PerceptionResult,
    ReferenceCandidate,
    ReferenceKind,
    TopicCandidate,
    RulePerceptionResult,
)
from .digests import perception_context_digest


def validate_rule_result(
    context: PerceptionContext,
    result: RulePerceptionResult,
) -> RulePerceptionResult:
    if not isinstance(context, PerceptionContext):
        raise validation_error("invalid_perception_context")
    if not isinstance(result, RulePerceptionResult):
        raise validation_error("invalid_rule_perception_result")
    if result.context_digest != perception_context_digest(context):
        raise validation_error("rule_result_context_mismatch")
    known_targets = {
        identity.identity_ref for identity in context.identities if not identity.is_bot
    }
    if not set(result.target_identity_refs) <= known_targets:
        raise validation_error("rule_result_unknown_target")
    if not set(result.capability_categories) <= set(
        context.available_capability_categories
    ):
        raise validation_error("rule_result_unknown_capability_category")
    message_refs = {message.message_ref for message in context.messages}
    for signal in result.complexity_signals:
        if len(signal.evidence_refs) > context.limits.max_evidence_refs_per_item:
            raise validation_error("rule_result_evidence_limit_exceeded")
        if not set(signal.evidence_refs) <= message_refs:
            raise validation_error("rule_result_unknown_evidence")
    return result


def validate_model_projection(
    context: PerceptionContext,
    projection: ModelPerceptionProjection,
) -> ModelPerceptionProjection:
    if not isinstance(context, PerceptionContext):
        raise validation_error("invalid_perception_context")
    if not isinstance(projection, ModelPerceptionProjection):
        raise validation_error("invalid_model_perception_projection")
    if projection.context_digest != perception_context_digest(context):
        raise validation_error("model_projection_context_mismatch")

    message_refs = {message.message_ref for message in context.messages}
    identity_refs = {identity.identity_ref for identity in context.identities}
    non_bot_identity_refs = {
        identity.identity_ref for identity in context.identities if not identity.is_bot
    }
    capability_categories = set(context.available_capability_categories)
    if not set(projection.target_identity_refs) <= non_bot_identity_refs:
        raise validation_error("model_projection_unknown_target")
    if not set(projection.capability_categories) <= capability_categories:
        raise validation_error("model_projection_unknown_capability_category")
    if projection.need_tools:
        if projection.expected_tool_steps < 1:
            raise validation_error("tool_need_has_zero_expected_steps")
    elif projection.capability_categories or projection.expected_tool_steps:
        raise validation_error("tool_free_projection_has_tool_details")

    collections: tuple[tuple[object, ...], ...] = (
        projection.topics,
        projection.intents,
        projection.entities,
        projection.references,
        projection.ambiguities,
    )
    if any(
        len(collection) > context.limits.max_candidates_per_kind
        for collection in collections
    ):
        raise validation_error("model_projection_candidate_limit_exceeded")

    evidence_holders: Iterable[
        TopicCandidate
        | IntentCandidate
        | EntityCandidate
        | ReferenceCandidate
        | AmbiguityCandidate
        | ComplexitySignal
    ] = (
        *projection.topics,
        *projection.intents,
        *projection.entities,
        *projection.references,
        *projection.ambiguities,
        *projection.complexity_signals,
    )
    for holder in evidence_holders:
        if len(holder.evidence_refs) > context.limits.max_evidence_refs_per_item:
            raise validation_error("model_projection_evidence_limit_exceeded")
        if not set(holder.evidence_refs) <= message_refs:
            raise validation_error("model_projection_unknown_evidence")

    topic_ids = {topic.topic_id for topic in projection.topics}
    for reference in projection.references:
        if reference.kind is ReferenceKind.MESSAGE:
            allowed = message_refs
        elif reference.kind is ReferenceKind.IDENTITY:
            allowed = identity_refs
        elif reference.kind is ReferenceKind.TOPIC:
            allowed = topic_ids
        else:
            allowed = set()
        if reference.target_ref is not None and reference.target_ref not in allowed:
            raise validation_error("model_projection_unknown_reference_target")
    return projection


def validate_perception_result(
    context: PerceptionContext,
    result: PerceptionResult,
) -> PerceptionResult:
    if not isinstance(context, PerceptionContext):
        raise validation_error("invalid_perception_context")
    if not isinstance(result, PerceptionResult):
        raise validation_error("invalid_perception_result")
    if result.context_digest != perception_context_digest(context):
        raise validation_error("perception_result_context_mismatch")
    known_targets = {
        identity.identity_ref for identity in context.identities if not identity.is_bot
    }
    if not set(result.target_identity_refs) <= known_targets:
        raise validation_error("perception_result_unknown_target")
    if not set(result.capability_categories) <= set(
        context.available_capability_categories
    ):
        raise validation_error("perception_result_unknown_capability_category")
    if result.need_tools:
        if result.expected_tool_steps < 1:
            raise validation_error("perception_tool_need_has_zero_steps")
    elif result.capability_categories or result.expected_tool_steps:
        raise validation_error("perception_tool_free_has_tool_details")
    if any(
        len(collection) > context.limits.max_candidates_per_kind
        for collection in (
            result.topics,
            result.intents,
            result.entities,
            result.references,
            result.ambiguities,
        )
    ):
        raise validation_error("perception_result_candidate_limit_exceeded")
    message_refs = {message.message_ref for message in context.messages}
    evidence_holders: Iterable[
        TopicCandidate
        | IntentCandidate
        | EntityCandidate
        | ReferenceCandidate
        | AmbiguityCandidate
        | ComplexitySignal
    ] = (
        *result.topics,
        *result.intents,
        *result.entities,
        *result.references,
        *result.ambiguities,
        *result.complexity_signals,
    )
    for holder in evidence_holders:
        if len(holder.evidence_refs) > context.limits.max_evidence_refs_per_item:
            raise validation_error("perception_result_evidence_limit_exceeded")
        if not set(holder.evidence_refs) <= message_refs:
            raise validation_error("perception_result_unknown_evidence")
    topic_ids = {topic.topic_id for topic in result.topics}
    identity_refs = {identity.identity_ref for identity in context.identities}
    for reference in result.references:
        if reference.kind is ReferenceKind.MESSAGE:
            allowed = message_refs
        elif reference.kind is ReferenceKind.IDENTITY:
            allowed = identity_refs
        elif reference.kind is ReferenceKind.TOPIC:
            allowed = topic_ids
        else:
            allowed = set()
        if reference.target_ref is not None and reference.target_ref not in allowed:
            raise validation_error("perception_result_unknown_reference_target")
    return result
