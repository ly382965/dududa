from __future__ import annotations

from dududa.errors import validation_error

from .contracts import PerceptionContext, PerceptionMessage, ReferenceKind
from .semantic import (
    ReferenceLinkSource,
    SemanticProjectionV2,
    TextSpan,
    VersionedModelPerceptionProjection,
    normalized_text,
    semantic_text_digest,
)
from .validation import validate_model_projection


def validate_versioned_model_projection(
    context: PerceptionContext,
    projection: VersionedModelPerceptionProjection,
) -> VersionedModelPerceptionProjection:
    if not isinstance(context, PerceptionContext):
        raise validation_error("invalid_perception_context")
    if not isinstance(projection, VersionedModelPerceptionProjection):
        raise validation_error("invalid_versioned_model_projection")
    validate_model_projection(context, projection.base_projection)
    if projection.schema_version == 1:
        return projection
    semantic = projection.semantic
    if not isinstance(semantic, SemanticProjectionV2):
        raise validation_error("v2_projection_missing_semantic_extension")

    messages = {item.message_ref: item for item in context.messages}
    identities = {item.identity_ref for item in context.identities}
    topics = {item.topic_id for item in projection.base_projection.topics}
    entity_ids = {item.entity_id for item in semantic.entities}
    if any(
        len(collection) > context.limits.max_candidates_per_kind
        for collection in (
            semantic.entities,
            semantic.references,
            semantic.intents,
        )
    ):
        raise validation_error("semantic_candidate_limit_exceeded")

    for entity in semantic.entities:
        _validate_evidence_limit(entity.evidence_refs, context)
        _validate_span(entity.span, messages)
        _validate_evidence(entity.evidence_refs, messages)
        if entity.span.message_ref not in entity.evidence_refs:
            raise validation_error("entity_span_missing_evidence")

    for reference in semantic.references:
        _validate_evidence_limit(reference.evidence_refs, context)
        _validate_span(reference.mention_span, messages)
        _validate_evidence(reference.evidence_refs, messages)
        if reference.mention_span.message_ref not in reference.evidence_refs:
            raise validation_error("reference_span_missing_evidence")
        source = messages[reference.mention_span.message_ref]
        if reference.link_source is ReferenceLinkSource.STRUCTURAL:
            if reference.kind is ReferenceKind.MESSAGE:
                if source.reply_to_message_ref != reference.target_ref:
                    raise validation_error("unverified_structural_reply_reference")
            elif reference.kind is ReferenceKind.IDENTITY:
                if reference.target_ref not in source.mentioned_identity_refs:
                    raise validation_error("unverified_structural_mention_reference")
            else:
                raise validation_error("unsupported_structural_reference_kind")
        elif reference.kind is ReferenceKind.IDENTITY:
            if reference.target_ref not in identities:
                raise validation_error("unknown_linguistic_identity_reference")
        elif reference.kind is ReferenceKind.MESSAGE:
            if reference.target_ref not in messages:
                raise validation_error("unknown_linguistic_message_reference")
        elif reference.kind is ReferenceKind.TOPIC:
            if reference.target_ref not in topics:
                raise validation_error("unknown_linguistic_topic_reference")

    for intent in semantic.intents:
        _validate_evidence_limit(intent.evidence_refs, context)
        if len(intent.slot_entity_refs) > context.limits.max_candidates_per_kind:
            raise validation_error("semantic_slot_limit_exceeded")
        _validate_evidence(intent.evidence_refs, messages)
        if any(entity_ref not in entity_ids for entity_ref in intent.slot_entity_refs):
            raise validation_error("unknown_intent_slot_entity")
    return projection


def _validate_span(span: TextSpan, messages: dict[str, PerceptionMessage]) -> None:
    message = messages.get(span.message_ref)
    if message is None:
        raise validation_error("unknown_span_message")
    text = normalized_text(message.text)
    if semantic_text_digest(text) != span.text_digest:
        raise validation_error("span_text_digest_mismatch")
    if span.end > len(text):
        raise validation_error("span_out_of_range")
    if text[span.start : span.end] != span.surface:
        raise validation_error("span_surface_mismatch")


def _validate_evidence(
    evidence_refs: tuple[str, ...],
    messages: dict[str, PerceptionMessage],
) -> None:
    if any(reference not in messages for reference in evidence_refs):
        raise validation_error("unknown_semantic_evidence_ref")


def _validate_evidence_limit(
    evidence_refs: tuple[str, ...],
    context: PerceptionContext,
) -> None:
    if len(evidence_refs) > context.limits.max_evidence_refs_per_item:
        raise validation_error("semantic_evidence_limit_exceeded")
