from __future__ import annotations

from collections.abc import Mapping, Sequence

from dududa.contracts.canonical import canonical_schema_digest
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    JsonValue,
    SchemaRef,
    freeze_json,
)
from dududa.domain.task import TaskReasoningDepth
from dududa.errors import validation_error

from .contracts import (
    AmbiguityCandidate,
    AmbiguityKind,
    ClarificationKey,
    ComplexitySignal,
    ComplexitySignalCode,
    EntityCandidate,
    EntityKind,
    EvidenceSource,
    IntentCandidate,
    ModelPerceptionProjection,
    PerceptionLimits,
    ReferenceCandidate,
    ReferenceKind,
    SpeechAct,
    TopicCandidate,
)


MODEL_PROJECTION_SCHEMA_ID = "dududa.perception.model-projection"


def model_projection_schema(limits: PerceptionLimits) -> Mapping[str, JsonValue]:
    if not isinstance(limits, PerceptionLimits):
        raise validation_error("invalid_perception_limits")
    evidence_refs = _string_array(
        max_items=limits.max_evidence_refs_per_item,
        max_length=128,
        minimum=1,
    )
    confidence = {"type": "number", "minimum": 0, "maximum": 1}
    topic = _strict_object(
        ("topic_id", "label", "confidence", "evidence_refs"),
        {
            "topic_id": _bounded_string(128),
            "label": _bounded_string(256),
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        },
    )
    intent = _strict_object(
        ("intent_id", "confidence", "evidence_refs"),
        {
            "intent_id": _bounded_string(128),
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        },
    )
    entity = _strict_object(
        ("entity_id", "kind", "value", "confidence", "evidence_refs"),
        {
            "entity_id": _bounded_string(128),
            "kind": _enum_schema(EntityKind),
            "value": _bounded_string(512),
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        },
    )
    reference = _strict_object(
        ("reference_id", "kind", "target_ref", "confidence", "evidence_refs"),
        {
            "reference_id": _bounded_string(128),
            "kind": _enum_schema(ReferenceKind),
            "target_ref": {
                "type": ("string", "null"),
                "minLength": 1,
                "maxLength": 128,
            },
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        },
    )
    ambiguity = _strict_object(
        (
            "ambiguity_id",
            "kind",
            "clarification_key",
            "confidence",
            "evidence_refs",
        ),
        {
            "ambiguity_id": _bounded_string(128),
            "kind": _enum_schema(AmbiguityKind),
            "clarification_key": {
                "enum": tuple(item.value for item in ClarificationKey) + (None,),
            },
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        },
    )
    complexity_signal = _strict_object(
        ("code", "confidence", "evidence_refs"),
        {
            "code": _enum_schema(ComplexitySignalCode),
            "confidence": confidence,
            "evidence_refs": evidence_refs,
        },
    )
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:dududa:schema:perception:model-projection:v1",
        **_strict_object(
            (
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
            ),
            {
                "schema_version": {"const": 1},
                "target_identity_refs": _string_array(
                    max_items=limits.max_identities,
                    max_length=128,
                ),
                "speech_acts": _enum_array(
                    SpeechAct,
                    max_items=len(tuple(SpeechAct)),
                ),
                "topics": _object_array(topic, limits.max_candidates_per_kind),
                "intents": _object_array(intent, limits.max_candidates_per_kind),
                "entities": _object_array(entity, limits.max_candidates_per_kind),
                "references": _object_array(
                    reference,
                    limits.max_candidates_per_kind,
                ),
                "ambiguities": _object_array(
                    ambiguity,
                    limits.max_candidates_per_kind,
                ),
                "need_tools": {"type": "boolean"},
                "capability_categories": _string_array(
                    max_items=limits.max_capability_categories,
                    max_length=128,
                ),
                "task_kind": _bounded_string(128),
                "reasoning_depth": _enum_schema(TaskReasoningDepth),
                "expected_tool_steps": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 64,
                },
                "verification_required": {"type": "boolean"},
                "complexity_signals": _object_array(
                    complexity_signal,
                    len(tuple(ComplexitySignalCode)),
                ),
                "confidence": confidence,
            },
        ),
    }
    frozen = freeze_json(document)
    if not isinstance(frozen, Mapping):
        raise validation_error("invalid_model_projection_schema")
    return frozen


def model_projection_schema_ref(limits: PerceptionLimits) -> SchemaRef:
    schema = model_projection_schema(limits)
    return SchemaRef(
        schema_id=MODEL_PROJECTION_SCHEMA_ID,
        schema_version=1,
        digest=canonical_schema_digest(
            schema,
            schema_id=MODEL_PROJECTION_SCHEMA_ID,
            schema_version=1,
        ),
    )


def decode_model_projection(
    value: JsonValue,
    *,
    context_digest: DigestString,
    projection_id: str,
    request_fingerprint: DigestString,
    route_receipt_digest: DigestString,
    component_revision: ComponentRevision,
) -> ModelPerceptionProjection:
    root_keys = (
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
    root = _exact_object(value, root_keys, "model_projection")
    _require_exact_integer(root["schema_version"], 1, "schema_version")
    return ModelPerceptionProjection(
        schema_version=1,
        projection_id=projection_id,
        context_digest=context_digest,
        request_fingerprint=request_fingerprint,
        route_receipt_digest=route_receipt_digest,
        target_identity_refs=_strings(
            root["target_identity_refs"],
            "target_identity_refs",
        ),
        speech_acts=tuple(
            _enum(item, SpeechAct, "speech_acts")
            for item in _sequence(root["speech_acts"], "speech_acts")
        ),
        topics=tuple(
            _decode_topic(item) for item in _sequence(root["topics"], "topics")
        ),
        intents=tuple(
            _decode_intent(item) for item in _sequence(root["intents"], "intents")
        ),
        entities=tuple(
            _decode_entity(item) for item in _sequence(root["entities"], "entities")
        ),
        references=tuple(
            _decode_reference(item)
            for item in _sequence(root["references"], "references")
        ),
        ambiguities=tuple(
            _decode_ambiguity(item)
            for item in _sequence(root["ambiguities"], "ambiguities")
        ),
        need_tools=_boolean(root["need_tools"], "need_tools"),
        capability_categories=_strings(
            root["capability_categories"],
            "capability_categories",
        ),
        task_kind=_string(root["task_kind"], "task_kind"),
        reasoning_depth=_enum(
            root["reasoning_depth"],
            TaskReasoningDepth,
            "reasoning_depth",
        ),
        expected_tool_steps=_nonnegative_integer(
            root["expected_tool_steps"],
            "expected_tool_steps",
        ),
        verification_required=_boolean(
            root["verification_required"],
            "verification_required",
        ),
        complexity_signals=tuple(
            _decode_complexity_signal(item)
            for item in _sequence(root["complexity_signals"], "complexity_signals")
        ),
        confidence=_number(root["confidence"], "confidence"),
        component_revision=component_revision,
    )


def _decode_topic(value: JsonValue) -> TopicCandidate:
    item = _exact_object(
        value,
        ("topic_id", "label", "confidence", "evidence_refs"),
        "topic",
    )
    return TopicCandidate(
        1,
        _string(item["topic_id"], "topic_id"),
        _string(item["label"], "topic_label"),
        _number(item["confidence"], "topic_confidence"),
        _strings(item["evidence_refs"], "topic_evidence_refs"),
    )


def _decode_intent(value: JsonValue) -> IntentCandidate:
    item = _exact_object(
        value,
        ("intent_id", "confidence", "evidence_refs"),
        "intent",
    )
    return IntentCandidate(
        1,
        _string(item["intent_id"], "intent_id"),
        _number(item["confidence"], "intent_confidence"),
        _strings(item["evidence_refs"], "intent_evidence_refs"),
    )


def _decode_entity(value: JsonValue) -> EntityCandidate:
    item = _exact_object(
        value,
        ("entity_id", "kind", "value", "confidence", "evidence_refs"),
        "entity",
    )
    return EntityCandidate(
        1,
        _string(item["entity_id"], "entity_id"),
        _enum(item["kind"], EntityKind, "entity_kind"),
        _string(item["value"], "entity_value"),
        _number(item["confidence"], "entity_confidence"),
        _strings(item["evidence_refs"], "entity_evidence_refs"),
    )


def _decode_reference(value: JsonValue) -> ReferenceCandidate:
    item = _exact_object(
        value,
        ("reference_id", "kind", "target_ref", "confidence", "evidence_refs"),
        "reference",
    )
    target = item["target_ref"]
    if target is not None:
        target = _string(target, "reference_target")
    return ReferenceCandidate(
        1,
        _string(item["reference_id"], "reference_id"),
        _enum(item["kind"], ReferenceKind, "reference_kind"),
        target,
        _number(item["confidence"], "reference_confidence"),
        _strings(item["evidence_refs"], "reference_evidence_refs"),
    )


def _decode_ambiguity(value: JsonValue) -> AmbiguityCandidate:
    item = _exact_object(
        value,
        (
            "ambiguity_id",
            "kind",
            "clarification_key",
            "confidence",
            "evidence_refs",
        ),
        "ambiguity",
    )
    clarification = item["clarification_key"]
    if clarification is not None:
        clarification = _enum(
            clarification,
            ClarificationKey,
            "clarification_key",
        )
    return AmbiguityCandidate(
        1,
        _string(item["ambiguity_id"], "ambiguity_id"),
        _enum(item["kind"], AmbiguityKind, "ambiguity_kind"),
        clarification,
        _number(item["confidence"], "ambiguity_confidence"),
        _strings(item["evidence_refs"], "ambiguity_evidence_refs"),
    )


def _decode_complexity_signal(value: JsonValue) -> ComplexitySignal:
    item = _exact_object(
        value,
        ("code", "confidence", "evidence_refs"),
        "complexity_signal",
    )
    return ComplexitySignal(
        1,
        _enum(item["code"], ComplexitySignalCode, "complexity_signal_code"),
        EvidenceSource.MODEL,
        _number(item["confidence"], "complexity_signal_confidence"),
        _strings(item["evidence_refs"], "complexity_signal_evidence_refs"),
    )


def _strict_object(
    required: tuple[str, ...],
    properties: Mapping[str, object],
) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
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


def _enum_schema(expected: type[object]) -> dict[str, object]:
    return {"enum": tuple(item.value for item in expected)}  # type: ignore[attr-defined]


def _enum_array(expected: type[object], *, max_items: int) -> dict[str, object]:
    return {
        "type": "array",
        "maxItems": max_items,
        "uniqueItems": True,
        "items": _enum_schema(expected),
    }


def _object_array(item: Mapping[str, object], maximum: int) -> dict[str, object]:
    return {"type": "array", "maxItems": maximum, "items": dict(item)}


def _exact_object(
    value: JsonValue,
    keys: tuple[str, ...],
    field_name: str,
) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise validation_error("invalid_model_projection_object", field_name)
    return value


def _sequence(value: JsonValue, field_name: str) -> tuple[JsonValue, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise validation_error("invalid_model_projection_array", field_name)
    return tuple(value)


def _strings(value: JsonValue, field_name: str) -> tuple[str, ...]:
    values = _sequence(value, field_name)
    return tuple(_string(item, field_name) for item in values)


def _string(value: JsonValue, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_model_projection_string", field_name)
    return value


def _boolean(value: JsonValue, field_name: str) -> bool:
    if type(value) is not bool:
        raise validation_error("invalid_model_projection_boolean", field_name)
    return value


def _number(value: JsonValue, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise validation_error("invalid_model_projection_number", field_name)
    return float(value)


def _nonnegative_integer(value: JsonValue, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise validation_error("invalid_model_projection_integer", field_name)
    return value


def _require_exact_integer(value: JsonValue, expected: int, field_name: str) -> None:
    if type(value) is not int or value != expected:
        raise validation_error("invalid_model_projection_integer", field_name)


def _enum(value: JsonValue, expected: type[object], field_name: str) -> object:
    if not isinstance(value, str):
        raise validation_error("invalid_model_projection_enum", field_name)
    try:
        return expected(value)  # type: ignore[call-arg]
    except (TypeError, ValueError):
        raise validation_error("invalid_model_projection_enum", field_name) from None
