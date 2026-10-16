from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import cast

from dududa.contracts.canonical import canonical_schema_digest
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    JsonValue,
    SchemaRef,
    freeze_json,
)
from dududa.errors import validation_error

from .contracts import (
    AmbiguityCandidate,
    ComplexitySignal,
    EntityCandidate,
    EntityKind,
    IntentCandidate,
    ModelPerceptionProjection,
    PerceptionLimits,
    ReferenceCandidate,
    ReferenceKind,
    TopicCandidate,
)
from .digests import model_perception_projection_digest
from .schema import decode_model_projection, model_projection_schema
from .semantic import (
    EntityMention,
    IntentCandidateV2,
    ReferenceLinkSource,
    ReferenceMention,
    SemanticDecision,
    SemanticDecisionAction,
    SemanticProjectionV2,
    TextSpan,
    VersionedModelPerceptionProjection,
)


MODEL_PROJECTION_V2_SCHEMA_ID = "dududa.perception.model-projection"

_BASE_KEYS = (
    "schema_version",
    "target_identity_refs",
    "speech_acts",
    "topics",
    "intents",
    "entities",
    "references",
    "ambiguities",
    "need_tools",
    "capability_categories",
    "task_kind",
    "reasoning_depth",
    "expected_tool_steps",
    "verification_required",
    "complexity_signals",
    "confidence",
)
_V2_KEYS = _BASE_KEYS + ("semantic",)


def model_projection_v2_schema(
    limits: PerceptionLimits,
) -> Mapping[str, JsonValue]:
    if not isinstance(limits, PerceptionLimits):
        raise validation_error("invalid_perception_limits")
    base = model_projection_schema(limits)
    base_properties = base.get("properties")
    if not isinstance(base_properties, Mapping):
        raise validation_error("invalid_v1_projection_schema")
    properties = dict(base_properties)
    properties["schema_version"] = {"const": 2}
    properties["semantic"] = _semantic_schema(limits)
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:dududa:schema:perception:model-projection:v2",
        **_strict_object(_V2_KEYS, properties),
    }
    frozen = freeze_json(document)
    if not isinstance(frozen, Mapping):
        raise validation_error("invalid_model_projection_v2_schema")
    return frozen


def model_projection_v2_schema_ref(limits: PerceptionLimits) -> SchemaRef:
    schema = model_projection_v2_schema(limits)
    return SchemaRef(
        schema_id=MODEL_PROJECTION_V2_SCHEMA_ID,
        schema_version=2,
        digest=canonical_schema_digest(
            schema,
            schema_id=MODEL_PROJECTION_V2_SCHEMA_ID,
            schema_version=2,
        ),
    )


def decode_versioned_model_projection(
    value: JsonValue,
    *,
    context_digest: DigestString,
    projection_id: str,
    request_fingerprint: DigestString,
    route_receipt_digest: DigestString,
    component_revision: ComponentRevision,
    semantic_component_revision: ComponentRevision | None = None,
    taxonomy_revision: ComponentRevision | None = None,
    calibration_revision: ComponentRevision | None = None,
    threshold_policy_revision: ComponentRevision | None = None,
) -> VersionedModelPerceptionProjection:
    if not isinstance(value, Mapping):
        raise validation_error("invalid_model_projection")
    version = _integer(value.get("schema_version"), "schema_version")
    if version == 1:
        return VersionedModelPerceptionProjection(
            schema_version=1,
            base_projection=decode_model_projection(
                value,
                context_digest=context_digest,
                projection_id=projection_id,
                request_fingerprint=request_fingerprint,
                route_receipt_digest=route_receipt_digest,
                component_revision=component_revision,
            ),
            semantic=None,
        )
    if version != 2:
        raise validation_error("unsupported_model_projection_version")
    revisions = (
        semantic_component_revision,
        taxonomy_revision,
        calibration_revision,
        threshold_policy_revision,
    )
    if not all(isinstance(item, ComponentRevision) for item in revisions):
        raise validation_error("missing_semantic_authority_revision")

    root = _exact_object(value, _V2_KEYS, "model_projection_v2")
    base_payload = dict(root)
    semantic_payload = base_payload.pop("semantic")
    base_payload["schema_version"] = 1
    frozen_base = freeze_json(base_payload)
    try:
        base = decode_model_projection(
            frozen_base,
            context_digest=context_digest,
            projection_id=projection_id,
            request_fingerprint=request_fingerprint,
            route_receipt_digest=route_receipt_digest,
            component_revision=component_revision,
        )
    except OverflowError as exc:
        raise validation_error("invalid_v2_base_numeric_value") from exc
    semantic = _decode_semantic(
        semantic_payload,
        base=base,
        component_revision=cast(ComponentRevision, semantic_component_revision),
        taxonomy_revision=cast(ComponentRevision, taxonomy_revision),
        calibration_revision=cast(ComponentRevision, calibration_revision),
        threshold_policy_revision=cast(
            ComponentRevision,
            threshold_policy_revision,
        ),
    )
    return VersionedModelPerceptionProjection(2, base, semantic)


def encode_versioned_model_projection(
    value: VersionedModelPerceptionProjection,
) -> Mapping[str, JsonValue]:
    if not isinstance(value, VersionedModelPerceptionProjection):
        raise validation_error("invalid_versioned_model_projection")
    payload = _encode_base(value.base_projection)
    payload["schema_version"] = value.schema_version
    if value.schema_version == 2:
        if value.semantic is None:  # defensive; the envelope already rejects this
            raise validation_error("v2_projection_missing_semantic_extension")
        payload["semantic"] = _encode_semantic(value.semantic)
    frozen = freeze_json(payload)
    if not isinstance(frozen, Mapping):
        raise validation_error("invalid_encoded_model_projection")
    return frozen


def _decode_semantic(
    value: JsonValue,
    *,
    base: ModelPerceptionProjection,
    component_revision: ComponentRevision,
    taxonomy_revision: ComponentRevision,
    calibration_revision: ComponentRevision,
    threshold_policy_revision: ComponentRevision,
) -> SemanticProjectionV2:
    root = _exact_object(
        value,
        ("schema_version", "entities", "references", "intents", "decision"),
        "semantic_projection",
    )
    _exact_integer(root["schema_version"], 2, "semantic_schema_version")
    entities = tuple(
        _decode_entity(item)
        for item in _sequence(root["entities"], "semantic_entities")
    )
    references = tuple(
        _decode_reference(item)
        for item in _sequence(root["references"], "semantic_references")
    )
    intents = tuple(
        _decode_intent(item, taxonomy_revision)
        for item in _sequence(root["intents"], "semantic_intents")
    )
    decision_root = _exact_object(
        root["decision"],
        ("action", "reason_codes"),
        "semantic_decision",
    )
    decision = SemanticDecision(
        schema_version=1,
        action=_enum(
            decision_root["action"],
            SemanticDecisionAction,
            "semantic_decision_action",
        ),
        calibration_revision=calibration_revision,
        threshold_policy_revision=threshold_policy_revision,
        reason_codes=_strings(
            decision_root["reason_codes"],
            "semantic_decision_reason_codes",
        ),
    )
    return SemanticProjectionV2(
        schema_version=2,
        base_projection_digest=model_perception_projection_digest(base),
        entities=entities,
        references=references,
        intents=intents,
        taxonomy_revision=taxonomy_revision,
        decision=decision,
        component_revision=component_revision,
    )


def _decode_span(value: JsonValue) -> TextSpan:
    root = _exact_object(
        value,
        ("message_ref", "start", "end", "surface", "text_digest"),
        "text_span",
    )
    return TextSpan(
        schema_version=1,
        message_ref=_string(root["message_ref"], "span_message_ref"),
        start=_integer(root["start"], "span_start"),
        end=_integer(root["end"], "span_end"),
        surface=_string(root["surface"], "span_surface"),
        text_digest=DigestString(_string(root["text_digest"], "span_text_digest")),
    )


def _decode_entity(value: JsonValue) -> EntityMention:
    root = _exact_object(
        value,
        (
            "entity_id",
            "kind",
            "span",
            "normalized_value",
            "confidence",
            "evidence_refs",
        ),
        "entity_mention",
    )
    return EntityMention(
        schema_version=1,
        entity_id=_string(root["entity_id"], "entity_id"),
        kind=_enum(root["kind"], EntityKind, "entity_kind"),
        span=_decode_span(root["span"]),
        normalized_value=_string(
            root["normalized_value"],
            "entity_normalized_value",
        ),
        confidence=_number(root["confidence"], "entity_confidence"),
        evidence_refs=_strings(root["evidence_refs"], "entity_evidence_refs"),
    )


def _decode_reference(value: JsonValue) -> ReferenceMention:
    root = _exact_object(
        value,
        (
            "reference_id",
            "kind",
            "mention_span",
            "target_ref",
            "link_source",
            "confidence",
            "evidence_refs",
        ),
        "reference_mention",
    )
    target = root["target_ref"]
    if target is not None:
        target = _string(target, "reference_target")
    return ReferenceMention(
        schema_version=1,
        reference_id=_string(root["reference_id"], "reference_id"),
        kind=_enum(root["kind"], ReferenceKind, "reference_kind"),
        mention_span=_decode_span(root["mention_span"]),
        target_ref=target,
        link_source=_enum(
            root["link_source"],
            ReferenceLinkSource,
            "reference_link_source",
        ),
        confidence=_number(root["confidence"], "reference_confidence"),
        evidence_refs=_strings(root["evidence_refs"], "reference_evidence_refs"),
    )


def _decode_intent(
    value: JsonValue,
    taxonomy_revision: ComponentRevision,
) -> IntentCandidateV2:
    root = _exact_object(
        value,
        ("intent_id", "slot_entity_refs", "confidence", "evidence_refs"),
        "intent_candidate_v2",
    )
    return IntentCandidateV2(
        schema_version=1,
        intent_id=_string(root["intent_id"], "intent_id"),
        taxonomy_revision=taxonomy_revision,
        slot_entity_refs=_strings(
            root["slot_entity_refs"],
            "intent_slot_entity_refs",
        ),
        confidence=_number(root["confidence"], "intent_confidence"),
        evidence_refs=_strings(root["evidence_refs"], "intent_evidence_refs"),
    )


def _encode_base(value: ModelPerceptionProjection) -> dict[str, object]:
    return {
        "schema_version": 1,
        "target_identity_refs": list(value.target_identity_refs),
        "speech_acts": [item.value for item in value.speech_acts],
        "topics": [_encode_topic(item) for item in value.topics],
        "intents": [_encode_legacy_intent(item) for item in value.intents],
        "entities": [_encode_legacy_entity(item) for item in value.entities],
        "references": [_encode_legacy_reference(item) for item in value.references],
        "ambiguities": [_encode_ambiguity(item) for item in value.ambiguities],
        "need_tools": value.need_tools,
        "capability_categories": list(value.capability_categories),
        "task_kind": value.task_kind,
        "reasoning_depth": value.reasoning_depth.value,
        "expected_tool_steps": value.expected_tool_steps,
        "verification_required": value.verification_required,
        "complexity_signals": [
            _encode_complexity(item) for item in value.complexity_signals
        ],
        "confidence": value.confidence,
    }


def _encode_semantic(value: SemanticProjectionV2) -> dict[str, object]:
    return {
        "schema_version": 2,
        "entities": [
            {
                "entity_id": item.entity_id,
                "kind": item.kind.value,
                "span": _encode_span(item.span),
                "normalized_value": item.normalized_value,
                "confidence": item.confidence,
                "evidence_refs": list(item.evidence_refs),
            }
            for item in value.entities
        ],
        "references": [
            {
                "reference_id": item.reference_id,
                "kind": item.kind.value,
                "mention_span": _encode_span(item.mention_span),
                "target_ref": item.target_ref,
                "link_source": item.link_source.value,
                "confidence": item.confidence,
                "evidence_refs": list(item.evidence_refs),
            }
            for item in value.references
        ],
        "intents": [
            {
                "intent_id": item.intent_id,
                "slot_entity_refs": list(item.slot_entity_refs),
                "confidence": item.confidence,
                "evidence_refs": list(item.evidence_refs),
            }
            for item in value.intents
        ],
        "decision": {
            "action": value.decision.action.value,
            "reason_codes": list(value.decision.reason_codes),
        },
    }


def _encode_span(value: TextSpan) -> dict[str, object]:
    return {
        "message_ref": value.message_ref,
        "start": value.start,
        "end": value.end,
        "surface": value.surface,
        "text_digest": str(value.text_digest),
    }


def _encode_topic(value: TopicCandidate) -> dict[str, object]:
    return {
        "topic_id": value.topic_id,
        "label": value.label,
        "confidence": value.confidence,
        "evidence_refs": list(value.evidence_refs),
    }


def _encode_legacy_intent(value: IntentCandidate) -> dict[str, object]:
    return {
        "intent_id": value.intent_id,
        "confidence": value.confidence,
        "evidence_refs": list(value.evidence_refs),
    }


def _encode_legacy_entity(value: EntityCandidate) -> dict[str, object]:
    return {
        "entity_id": value.entity_id,
        "kind": value.kind.value,
        "value": value.value,
        "confidence": value.confidence,
        "evidence_refs": list(value.evidence_refs),
    }


def _encode_legacy_reference(value: ReferenceCandidate) -> dict[str, object]:
    return {
        "reference_id": value.reference_id,
        "kind": value.kind.value,
        "target_ref": value.target_ref,
        "confidence": value.confidence,
        "evidence_refs": list(value.evidence_refs),
    }


def _encode_ambiguity(value: AmbiguityCandidate) -> dict[str, object]:
    return {
        "ambiguity_id": value.ambiguity_id,
        "kind": value.kind.value,
        "clarification_key": (
            value.clarification_key.value
            if value.clarification_key is not None
            else None
        ),
        "confidence": value.confidence,
        "evidence_refs": list(value.evidence_refs),
    }


def _encode_complexity(value: ComplexitySignal) -> dict[str, object]:
    return {
        "code": value.code.value,
        "confidence": value.confidence,
        "evidence_refs": list(value.evidence_refs),
    }


def _semantic_schema(limits: PerceptionLimits) -> dict[str, object]:
    evidence_refs = _string_array(
        max_items=limits.max_evidence_refs_per_item,
        max_length=128,
        minimum=1,
    )
    span = _strict_object(
        ("message_ref", "start", "end", "surface", "text_digest"),
        {
            "message_ref": _bounded_string(128),
            "start": {
                "type": "integer",
                "minimum": 0,
                "maximum": limits.max_characters_per_message,
            },
            "end": {
                "type": "integer",
                "minimum": 1,
                "maximum": limits.max_characters_per_message,
            },
            "surface": _bounded_string(512),
            "text_digest": _bounded_string(256),
        },
    )
    confidence = {"type": "number", "minimum": 0, "maximum": 1}
    entity = _strict_object(
        (
            "entity_id",
            "kind",
            "span",
            "normalized_value",
            "confidence",
            "evidence_refs",
        ),
        {
            "entity_id": _bounded_string(128),
            "kind": {"enum": tuple(item.value for item in EntityKind)},
            "span": span,
            "normalized_value": _bounded_string(512),
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        },
    )
    reference = _strict_object(
        (
            "reference_id",
            "kind",
            "mention_span",
            "target_ref",
            "link_source",
            "confidence",
            "evidence_refs",
        ),
        {
            "reference_id": _bounded_string(128),
            "kind": {"enum": tuple(item.value for item in ReferenceKind)},
            "mention_span": span,
            "target_ref": {
                "type": ("string", "null"),
                "minLength": 1,
                "maxLength": 128,
            },
            "link_source": {"enum": tuple(item.value for item in ReferenceLinkSource)},
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        },
    )
    intent = _strict_object(
        ("intent_id", "slot_entity_refs", "confidence", "evidence_refs"),
        {
            "intent_id": _bounded_string(128),
            "slot_entity_refs": _string_array(
                max_items=limits.max_candidates_per_kind,
                max_length=128,
            ),
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        },
    )
    decision = _strict_object(
        ("action", "reason_codes"),
        {
            "action": {"enum": tuple(item.value for item in SemanticDecisionAction)},
            "reason_codes": _string_array(
                max_items=16,
                max_length=128,
                minimum=1,
            ),
        },
    )
    return _strict_object(
        ("schema_version", "entities", "references", "intents", "decision"),
        {
            "schema_version": {"const": 2},
            "entities": _object_array(entity, limits.max_candidates_per_kind),
            "references": _object_array(
                reference,
                limits.max_candidates_per_kind,
            ),
            "intents": _object_array(intent, limits.max_candidates_per_kind),
            "decision": decision,
        },
    )


def _strict_object(
    required: Sequence[str],
    properties: Mapping[str, object],
) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": tuple(required),
        "properties": dict(properties),
    }


def _bounded_string(max_length: int) -> dict[str, object]:
    return {"type": "string", "minLength": 1, "maxLength": max_length}


def _string_array(
    *,
    max_items: int,
    max_length: int,
    minimum: int = 0,
) -> dict[str, object]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": max_items,
        "uniqueItems": True,
        "items": _bounded_string(max_length),
    }


def _object_array(item: Mapping[str, object], maximum: int) -> dict[str, object]:
    return {"type": "array", "maxItems": maximum, "items": dict(item)}


def _exact_object(
    value: JsonValue,
    expected_keys: Sequence[str],
    field_name: str,
) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise validation_error("invalid_object", field_name)
    if set(value) != set(expected_keys):
        raise validation_error("invalid_object_keys", field_name)
    return value


def _sequence(value: JsonValue, field_name: str) -> tuple[JsonValue, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise validation_error("invalid_sequence", field_name)
    return tuple(value)


def _strings(value: JsonValue, field_name: str) -> tuple[str, ...]:
    values = _sequence(value, field_name)
    if not all(isinstance(item, str) for item in values):
        raise validation_error("invalid_string_sequence", field_name)
    return cast(tuple[str, ...], values)


def _string(value: JsonValue, field_name: str) -> str:
    if not isinstance(value, str):
        raise validation_error("invalid_string", field_name)
    return value


def _integer(value: JsonValue | None, field_name: str) -> int:
    if type(value) is not int:
        raise validation_error("invalid_integer", field_name)
    return value


def _exact_integer(value: JsonValue, expected: int, field_name: str) -> None:
    if type(value) is not int or value != expected:
        raise validation_error("invalid_integer", field_name)


def _number(value: JsonValue, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise validation_error("invalid_number", field_name)
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise validation_error("invalid_number", field_name) from exc
    if not math.isfinite(normalized):
        raise validation_error("invalid_number", field_name)
    return normalized


def _enum(value: JsonValue, expected: type[object], field_name: str):
    if not isinstance(value, str):
        raise validation_error("invalid_enum", field_name)
    try:
        return expected(value)
    except ValueError as exc:
        raise validation_error("invalid_enum", field_name) from exc
