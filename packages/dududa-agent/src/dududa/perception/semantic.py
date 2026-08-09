from __future__ import annotations

from dataclasses import dataclass
import math
import unicodedata

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.errors import validation_error

from .contracts import (
    EntityCandidate,
    EntityKind,
    IntentCandidate,
    ModelPerceptionProjection,
    ReferenceCandidate,
    ReferenceKind,
)


_REFERENCE_MAX_LENGTH = 128
_VALUE_MAX_LENGTH = 512
_MAX_CANDIDATES = 64
_MAX_EVIDENCE_REFS = 16


class ReferenceLinkSource(StrEnum):
    STRUCTURAL = "structural"
    LINGUISTIC = "linguistic"


class SemanticDecisionAction(StrEnum):
    ACCEPT = "accept"
    CLARIFY = "clarify"
    ABSTAIN = "abstain"


class TextOffsetUnit(StrEnum):
    CODE_POINT = "code_point"
    UTF8_BYTE = "utf8_byte"
    UTF16_CODE_UNIT = "utf16_code_unit"


@dataclass(frozen=True, slots=True)
class TextSpan:
    schema_version: int
    message_ref: str
    start: int
    end: int
    surface: str
    text_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.message_ref, "span_message_ref", _REFERENCE_MAX_LENGTH)
        _exact_nonnegative_int(self.start, "span_start")
        _exact_nonnegative_int(self.end, "span_end")
        if self.start >= self.end:
            raise validation_error("invalid_text_span_range")
        _bounded_string(self.surface, "span_surface", _VALUE_MAX_LENGTH)
        if len(self.surface) != self.end - self.start:
            raise validation_error("span_surface_length_mismatch")
        _bounded_digest(self.text_digest, "span_text_digest")


@dataclass(frozen=True, slots=True)
class EntityMention:
    schema_version: int
    entity_id: str
    kind: EntityKind
    span: TextSpan
    normalized_value: str
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.entity_id, "entity_id", _REFERENCE_MAX_LENGTH)
        _enum(self.kind, EntityKind, "entity_kind")
        if not isinstance(self.span, TextSpan):
            raise validation_error("invalid_entity_span")
        _bounded_string(
            self.normalized_value,
            "entity_normalized_value",
            _VALUE_MAX_LENGTH,
        )
        _rate(self.confidence, "entity_confidence")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(self.evidence_refs, "entity_evidence_refs"),
        )


@dataclass(frozen=True, slots=True)
class ReferenceMention:
    schema_version: int
    reference_id: str
    kind: ReferenceKind
    mention_span: TextSpan
    target_ref: str | None
    link_source: ReferenceLinkSource
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.reference_id, "reference_id", _REFERENCE_MAX_LENGTH)
        _enum(self.kind, ReferenceKind, "reference_kind")
        _enum(self.link_source, ReferenceLinkSource, "reference_link_source")
        if not isinstance(self.mention_span, TextSpan):
            raise validation_error("invalid_reference_span")
        if self.kind is ReferenceKind.UNRESOLVED:
            if self.target_ref is not None:
                raise validation_error("unresolved_reference_has_target")
            if self.link_source is ReferenceLinkSource.STRUCTURAL:
                raise validation_error("structural_reference_cannot_be_unresolved")
        elif self.target_ref is None:
            raise validation_error("resolved_reference_has_no_target")
        else:
            _bounded_string(
                self.target_ref,
                "reference_target",
                _REFERENCE_MAX_LENGTH,
            )
        _rate(self.confidence, "reference_confidence")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(self.evidence_refs, "reference_evidence_refs"),
        )


@dataclass(frozen=True, slots=True)
class IntentCandidateV2:
    schema_version: int
    intent_id: str
    taxonomy_revision: ComponentRevision
    slot_entity_refs: tuple[str, ...]
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.intent_id, "intent_id", _REFERENCE_MAX_LENGTH)
        if not isinstance(self.taxonomy_revision, ComponentRevision):
            raise validation_error("invalid_intent_taxonomy_revision")
        object.__setattr__(
            self,
            "slot_entity_refs",
            _unique_strings(
                self.slot_entity_refs,
                "intent_slot_entity_refs",
                required=False,
                maximum_items=_MAX_CANDIDATES,
            ),
        )
        _rate(self.confidence, "intent_confidence")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(self.evidence_refs, "intent_evidence_refs"),
        )


@dataclass(frozen=True, slots=True)
class SemanticDecision:
    schema_version: int
    action: SemanticDecisionAction
    calibration_revision: ComponentRevision
    threshold_policy_revision: ComponentRevision
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _enum(self.action, SemanticDecisionAction, "semantic_decision_action")
        if not isinstance(self.calibration_revision, ComponentRevision):
            raise validation_error("invalid_semantic_calibration_revision")
        if not isinstance(self.threshold_policy_revision, ComponentRevision):
            raise validation_error("invalid_semantic_threshold_revision")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(self.reason_codes, "semantic_decision_reason_codes"),
        )


@dataclass(frozen=True, slots=True)
class SemanticProjectionV2:
    schema_version: int
    base_projection_digest: DigestString
    entities: tuple[EntityMention, ...]
    references: tuple[ReferenceMention, ...]
    intents: tuple[IntentCandidateV2, ...]
    taxonomy_revision: ComponentRevision
    decision: SemanticDecision
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise validation_error("unsupported_semantic_schema_version")
        _bounded_digest(
            self.base_projection_digest,
            "semantic_base_projection_digest",
        )
        if not isinstance(self.decision, SemanticDecision):
            raise validation_error("invalid_semantic_decision")
        if not isinstance(self.taxonomy_revision, ComponentRevision):
            raise validation_error("invalid_semantic_taxonomy_revision")
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_semantic_component_revision")
        for field_name, expected, identity in (
            ("entities", EntityMention, "entity_id"),
            ("references", ReferenceMention, "reference_id"),
            ("intents", IntentCandidateV2, "intent_id"),
        ):
            values = tuple(getattr(self, field_name))
            if not all(isinstance(item, expected) for item in values):
                raise validation_error("invalid_semantic_collection", field_name)
            if len(values) > _MAX_CANDIDATES:
                raise validation_error("semantic_collection_too_large", field_name)
            identifiers = tuple(getattr(item, identity) for item in values)
            if len(set(identifiers)) != len(identifiers):
                raise validation_error("duplicate_semantic_identifier", field_name)
            object.__setattr__(
                self,
                field_name,
                tuple(sorted(values, key=lambda item: getattr(item, identity))),
            )
        if any(
            item.taxonomy_revision != self.taxonomy_revision for item in self.intents
        ):
            raise validation_error("semantic_taxonomy_revision_mismatch")


@dataclass(frozen=True, slots=True)
class VersionedModelPerceptionProjection:
    schema_version: int
    base_projection: ModelPerceptionProjection
    semantic: SemanticProjectionV2 | None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version not in {1, 2}:
            raise validation_error("unsupported_model_projection_version")
        if not isinstance(self.base_projection, ModelPerceptionProjection):
            raise validation_error("invalid_base_model_projection")
        if self.schema_version == 1:
            if self.semantic is not None:
                raise validation_error("v1_projection_has_semantic_extension")
            return
        if not isinstance(self.semantic, SemanticProjectionV2):
            raise validation_error("v2_projection_missing_semantic_extension")
        expected_digest = canonical_digest(
            self.base_projection,
            domain="perception:model-projection:v1",
        )
        if self.semantic.base_projection_digest != expected_digest:
            raise validation_error("semantic_base_projection_digest_mismatch")
        _validate_legacy_projection(self.base_projection, self.semantic)


def normalized_text(value: str) -> str:
    if not isinstance(value, str):
        raise validation_error("invalid_semantic_text")
    _require_scalar_text(value, "semantic_text")
    return unicodedata.normalize("NFC", value)


def semantic_text_digest(value: str) -> DigestString:
    return canonical_digest(normalized_text(value), domain="perception:text-nfc:v1")


def semantic_projection_digest(value: SemanticProjectionV2) -> DigestString:
    if not isinstance(value, SemanticProjectionV2):
        raise validation_error("invalid_semantic_projection")
    return canonical_digest(value, domain="perception:semantic-projection:v2")


def versioned_model_projection_digest(
    value: VersionedModelPerceptionProjection,
) -> DigestString:
    if not isinstance(value, VersionedModelPerceptionProjection):
        raise validation_error("invalid_versioned_model_projection")
    return canonical_digest(
        value,
        domain=f"perception:model-projection-envelope:v{value.schema_version}",
    )


def normalized_codepoint_offset(
    text: str,
    offset: int,
    unit: TextOffsetUnit,
) -> int:
    raw = _raw_boundary_index(text, offset, unit)
    full = normalized_text(text)
    prefix = normalized_text(text[:raw])
    if not full.startswith(prefix):
        raise validation_error("semantic_offset_crosses_normalization_boundary")
    return len(prefix)


def normalized_codepoint_span(
    text: str,
    start: int,
    end: int,
    unit: TextOffsetUnit,
) -> tuple[int, int]:
    normalized_start = normalized_codepoint_offset(text, start, unit)
    normalized_end = normalized_codepoint_offset(text, end, unit)
    if normalized_start >= normalized_end:
        raise validation_error("invalid_normalized_span_range")
    return normalized_start, normalized_end


def _raw_boundary_index(text: str, offset: int, unit: TextOffsetUnit) -> int:
    if not isinstance(text, str):
        raise validation_error("invalid_semantic_text")
    _require_scalar_text(text, "semantic_text")
    _exact_nonnegative_int(offset, "external_text_offset")
    _enum(unit, TextOffsetUnit, "text_offset_unit")
    if unit is TextOffsetUnit.CODE_POINT:
        if offset > len(text):
            raise validation_error("semantic_offset_out_of_range")
        return offset

    consumed = 0
    for index, character in enumerate(text):
        width = (
            len(character.encode("utf-8"))
            if unit is TextOffsetUnit.UTF8_BYTE
            else len(character.encode("utf-16-le")) // 2
        )
        if consumed == offset:
            return index
        if consumed < offset < consumed + width:
            raise validation_error("semantic_offset_splits_code_point")
        consumed += width
    if consumed == offset:
        return len(text)
    raise validation_error("semantic_offset_out_of_range")


def _validate_legacy_projection(
    base: ModelPerceptionProjection,
    semantic: SemanticProjectionV2,
) -> None:
    legacy_entities = {item.entity_id: item for item in base.entities}
    if set(legacy_entities) != {item.entity_id for item in semantic.entities}:
        raise validation_error("semantic_entity_set_mismatch")
    for mention in semantic.entities:
        legacy = legacy_entities[mention.entity_id]
        if legacy != EntityCandidate(
            schema_version=1,
            entity_id=mention.entity_id,
            kind=mention.kind,
            value=mention.normalized_value,
            confidence=mention.confidence,
            evidence_refs=mention.evidence_refs,
        ):
            raise validation_error("semantic_entity_projection_mismatch")

    legacy_references = {item.reference_id: item for item in base.references}
    if set(legacy_references) != {item.reference_id for item in semantic.references}:
        raise validation_error("semantic_reference_set_mismatch")
    for mention in semantic.references:
        legacy = legacy_references[mention.reference_id]
        if legacy != ReferenceCandidate(
            schema_version=1,
            reference_id=mention.reference_id,
            kind=mention.kind,
            target_ref=mention.target_ref,
            confidence=mention.confidence,
            evidence_refs=mention.evidence_refs,
        ):
            raise validation_error("semantic_reference_projection_mismatch")

    legacy_intents = {item.intent_id: item for item in base.intents}
    if set(legacy_intents) != {item.intent_id for item in semantic.intents}:
        raise validation_error("semantic_intent_set_mismatch")
    for candidate in semantic.intents:
        legacy = legacy_intents[candidate.intent_id]
        if legacy != IntentCandidate(
            schema_version=1,
            intent_id=candidate.intent_id,
            confidence=candidate.confidence,
            evidence_refs=candidate.evidence_refs,
        ):
            raise validation_error("semantic_intent_projection_mismatch")
    if (
        semantic.decision.action is SemanticDecisionAction.ACCEPT
        and not semantic.intents
    ):
        raise validation_error("semantic_accept_has_no_intent")


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _enum(value: object, expected: type[StrEnum], field_name: str) -> None:
    if not isinstance(value, expected):
        raise validation_error("invalid_enum_value", field_name)


def _rate(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise validation_error("invalid_rate", field_name)
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise validation_error("invalid_rate", field_name) from exc
    if not math.isfinite(normalized) or not 0 <= normalized <= 1:
        raise validation_error("invalid_rate", field_name)


def _exact_nonnegative_int(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise validation_error("invalid_nonnegative_integer", field_name)


def _bounded_string(value: str, field_name: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise validation_error("invalid_bounded_string", field_name)
    _require_scalar_text(value, field_name)
    if not unicodedata.is_normalized("NFC", value):
        raise validation_error("semantic_string_not_nfc", field_name)


def _bounded_digest(value: DigestString, field_name: str) -> None:
    if not isinstance(value, str):
        raise validation_error("invalid_semantic_digest", field_name)
    _bounded_string(value, field_name, 256)


def _unique_strings(
    values: tuple[str, ...],
    field_name: str,
    *,
    required: bool = True,
    maximum_items: int = _MAX_EVIDENCE_REFS,
) -> tuple[str, ...]:
    result = tuple(values)
    if required and not result:
        raise validation_error("empty_string_collection", field_name)
    if len(result) > maximum_items:
        raise validation_error("string_collection_too_large", field_name)
    for value in result:
        _bounded_string(value, field_name, _REFERENCE_MAX_LENGTH)
    if len(set(result)) != len(result):
        raise validation_error("duplicate_string", field_name)
    return tuple(sorted(result))


def _require_scalar_text(value: str, field_name: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise validation_error("invalid_unicode_scalar", field_name)
