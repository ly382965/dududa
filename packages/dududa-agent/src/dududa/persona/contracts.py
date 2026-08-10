from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import (
    ConversationType,
    DigestString,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error

_PERSONA_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$"
)


class PersonaSentenceLength(StrEnum):
    SHORT = "short"
    BALANCED = "balanced"
    LONG = "long"


class PersonaRendererMode(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL = "model"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class PersonaChannelStyle:
    schema_version: int
    tone_tags: tuple[str, ...]
    emoji_budget: int
    prefer_short_sentences: bool

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        object.__setattr__(
            self,
            "tone_tags",
            _unique_strings(self.tone_tags, "channel_tone_tags", required=True),
        )
        if type(self.emoji_budget) is not int or not 0 <= self.emoji_budget <= 8:
            raise validation_error("invalid_persona_emoji_budget")
        if type(self.prefer_short_sentences) is not bool:
            raise validation_error("invalid_persona_sentence_preference")


@dataclass(frozen=True, slots=True)
class PersonaVoiceRules:
    schema_version: int
    tone_tags: tuple[str, ...]
    sentence_length: PersonaSentenceLength
    preferred_language: str
    emoji_budget: int
    avoid_patterns: tuple[str, ...]
    technical_style: str
    uncertainty_style: str
    instructions: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        object.__setattr__(
            self,
            "tone_tags",
            _unique_strings(self.tone_tags, "voice_tone_tags", required=True),
        )
        object.__setattr__(
            self,
            "avoid_patterns",
            _unique_strings(
                self.avoid_patterns,
                "voice_avoid_patterns",
                required=False,
            ),
        )
        object.__setattr__(
            self,
            "instructions",
            _unique_strings(
                self.instructions,
                "voice_instructions",
                required=True,
                maximum_length=512,
            ),
        )
        if not isinstance(self.sentence_length, PersonaSentenceLength):
            raise validation_error("invalid_persona_sentence_length")
        for name in (
            "preferred_language",
            "technical_style",
            "uncertainty_style",
        ):
            if not isinstance(getattr(self, name), str):
                raise validation_error("invalid_persona_voice_field", name)
            require_non_empty(getattr(self, name), name)
        if type(self.emoji_budget) is not int or not 0 <= self.emoji_budget <= 8:
            raise validation_error("invalid_persona_emoji_budget")


@dataclass(frozen=True, slots=True)
class PersonaDefinition:
    schema_version: int
    persona_id: str
    version: str
    display_name: str
    default_locale: str
    voice: PersonaVoiceRules
    channel_rules: Mapping[ConversationType, PersonaChannelStyle]
    renderer_mode: PersonaRendererMode
    safety_note_ids: tuple[str, ...]
    source_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if (
            not isinstance(self.persona_id, str)
            or _PERSONA_ID_RE.fullmatch(self.persona_id) is None
        ):
            raise validation_error("invalid_persona_id")
        if (
            not isinstance(self.version, str)
            or _VERSION_RE.fullmatch(self.version) is None
        ):
            raise validation_error("invalid_persona_version")
        for name in ("display_name", "default_locale"):
            if not isinstance(getattr(self, name), str):
                raise validation_error("invalid_persona_definition_field", name)
            require_non_empty(getattr(self, name), name)
        if not isinstance(self.voice, PersonaVoiceRules):
            raise validation_error("invalid_persona_voice_rules")
        try:
            channel_rules = dict(self.channel_rules)
        except (TypeError, ValueError):
            raise validation_error("invalid_persona_channel_rules") from None
        if set(channel_rules) != set(ConversationType) or any(
            not isinstance(kind, ConversationType)
            or not isinstance(style, PersonaChannelStyle)
            for kind, style in channel_rules.items()
        ):
            raise validation_error("invalid_persona_channel_rules")
        object.__setattr__(
            self,
            "channel_rules",
            MappingProxyType(channel_rules),
        )
        if not isinstance(self.renderer_mode, PersonaRendererMode):
            raise validation_error("invalid_persona_renderer_mode")
        object.__setattr__(
            self,
            "safety_note_ids",
            _unique_strings(
                self.safety_note_ids,
                "persona_safety_note_ids",
                required=False,
            ),
        )
        if not isinstance(self.source_digest, str):
            raise validation_error("invalid_persona_source_digest")
        require_non_empty(self.source_digest, "persona_source_digest")
        if self.source_digest != persona_definition_source_digest(self):
            raise validation_error("persona_source_digest_mismatch")


@dataclass(frozen=True, slots=True)
class PersonaCatalogSnapshot:
    schema_version: int
    snapshot_id: str
    revision: int
    definitions: tuple[PersonaDefinition, ...]
    fallback_persona_id: str
    fallback_version: str
    acquired_at: datetime
    catalog_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.snapshot_id, str):
            raise validation_error("invalid_persona_snapshot_id")
        require_non_empty(self.snapshot_id, "persona_snapshot_id")
        if type(self.revision) is not int or self.revision < 1:
            raise validation_error("invalid_persona_catalog_revision")
        definitions = _definitions(
            self.definitions,
            "empty_persona_catalog",
        )
        if not definitions or not all(
            isinstance(value, PersonaDefinition) for value in definitions
        ):
            raise validation_error("empty_persona_catalog")
        keys = tuple((value.persona_id, value.version) for value in definitions)
        if len(keys) != len(set(keys)):
            raise validation_error("duplicate_persona_version")
        if definitions != tuple(sorted(definitions, key=lambda value: keys_for(value))):
            raise validation_error("unsorted_persona_catalog")
        object.__setattr__(self, "definitions", definitions)
        if self.fallback_persona_id != "neutral":
            raise validation_error("invalid_persona_fallback_id")
        if (
            not isinstance(self.fallback_version, str)
            or _VERSION_RE.fullmatch(self.fallback_version) is None
        ):
            raise validation_error("invalid_persona_fallback_version")
        if not any(
            value.persona_id == self.fallback_persona_id
            and value.version == self.fallback_version
            for value in definitions
        ):
            raise validation_error("persona_fallback_not_found")
        if not isinstance(self.acquired_at, datetime):
            raise validation_error("invalid_persona_catalog_acquired_at")
        require_aware(self.acquired_at, "persona_catalog_acquired_at")
        if not isinstance(self.catalog_digest, str):
            raise validation_error("invalid_persona_catalog_digest")
        require_non_empty(self.catalog_digest, "persona_catalog_digest")
        if self.catalog_digest != persona_catalog_digest(
            self.revision,
            definitions,
            self.fallback_persona_id,
            self.fallback_version,
        ):
            raise validation_error("persona_catalog_digest_mismatch")


@dataclass(frozen=True, slots=True)
class PersonaCatalogUpdate:
    schema_version: int
    expected_revision: int
    definitions: tuple[PersonaDefinition, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise validation_error("invalid_expected_persona_revision")
        definitions = _definitions(
            self.definitions,
            "empty_persona_catalog_update",
        )
        keys = tuple((value.persona_id, value.version) for value in definitions)
        if len(keys) != len(set(keys)):
            raise validation_error("duplicate_persona_version")
        object.__setattr__(
            self,
            "definitions",
            tuple(sorted(definitions, key=keys_for)),
        )


@dataclass(frozen=True, slots=True)
class PersonaResolution:
    schema_version: int
    requested_persona_id: str
    requested_version: str | None
    definition: PersonaDefinition
    snapshot_id: str
    catalog_digest: DigestString
    fallback_used: bool
    reason_code: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if (
            not isinstance(self.requested_persona_id, str)
            or _PERSONA_ID_RE.fullmatch(self.requested_persona_id) is None
        ):
            raise validation_error("invalid_requested_persona_id")
        if self.requested_version is not None and (
            not isinstance(self.requested_version, str)
            or _VERSION_RE.fullmatch(self.requested_version) is None
        ):
            raise validation_error("invalid_requested_persona_version")
        if not isinstance(self.definition, PersonaDefinition):
            raise validation_error("invalid_persona_resolution_definition")
        if not isinstance(self.snapshot_id, str):
            raise validation_error("invalid_persona_resolution_snapshot_id")
        require_non_empty(self.snapshot_id, "persona_resolution_snapshot_id")
        if not isinstance(self.catalog_digest, str):
            raise validation_error("invalid_persona_resolution_catalog_digest")
        require_non_empty(self.catalog_digest, "persona_resolution_catalog_digest")
        if type(self.fallback_used) is not bool:
            raise validation_error("invalid_persona_fallback_flag")
        if not isinstance(self.reason_code, str):
            raise validation_error("invalid_persona_resolution_reason")
        require_non_empty(self.reason_code, "persona_resolution_reason")


def build_persona_definition(
    *,
    persona_id: str,
    version: str,
    display_name: str,
    default_locale: str,
    voice: PersonaVoiceRules,
    channel_rules: Mapping[ConversationType, PersonaChannelStyle],
    renderer_mode: PersonaRendererMode,
    safety_note_ids: tuple[str, ...],
) -> PersonaDefinition:
    values = {
        "schema_version": 1,
        "persona_id": persona_id,
        "version": version,
        "display_name": display_name,
        "default_locale": default_locale,
        "voice": voice,
        "channel_rules": _channel_mapping(channel_rules),
        "renderer_mode": renderer_mode,
        "safety_note_ids": tuple(safety_note_ids),
    }
    return PersonaDefinition(
        **values,
        source_digest=canonical_digest(
            values,
            domain="persona:definition-source:v1",
        ),
    )


def persona_definition_source_digest(value: PersonaDefinition) -> DigestString:
    return canonical_digest(
        {
            name: getattr(value, name)
            for name in value.__dataclass_fields__
            if name != "source_digest"
        },
        domain="persona:definition-source:v1",
    )


def persona_catalog_digest(
    revision: int,
    definitions: tuple[PersonaDefinition, ...],
    fallback_persona_id: str,
    fallback_version: str,
) -> DigestString:
    return canonical_digest(
        {
            "revision": revision,
            "definitions": tuple(definitions),
            "fallback_persona_id": fallback_persona_id,
            "fallback_version": fallback_version,
        },
        domain="persona:catalog:v1",
    )


def validate_persona_resolution(
    snapshot: PersonaCatalogSnapshot,
    resolution: PersonaResolution,
    *,
    requested_persona_id: str,
    requested_version: str | None,
) -> PersonaResolution:
    if not isinstance(snapshot, PersonaCatalogSnapshot) or not isinstance(
        resolution, PersonaResolution
    ):
        raise validation_error("invalid_persona_resolution_binding")
    if (
        resolution.snapshot_id != snapshot.snapshot_id
        or resolution.catalog_digest != snapshot.catalog_digest
        or resolution.requested_persona_id != requested_persona_id
        or resolution.requested_version != requested_version
        or resolution.definition not in snapshot.definitions
    ):
        raise validation_error("persona_resolution_binding_mismatch")
    candidates = tuple(
        value
        for value in snapshot.definitions
        if value.persona_id == requested_persona_id
        and (requested_version is None or value.version == requested_version)
    )
    if candidates:
        expected = max(candidates, key=lambda value: keys_for(value)[1])
        if (
            resolution.definition != expected
            or resolution.fallback_used
            or resolution.reason_code != "requested_persona_resolved"
        ):
            raise validation_error("persona_resolution_semantics_mismatch")
    elif (
        resolution.definition.persona_id != snapshot.fallback_persona_id
        or resolution.definition.version != snapshot.fallback_version
        or not resolution.fallback_used
        or resolution.reason_code != "neutral_persona_fallback"
    ):
        raise validation_error("persona_resolution_semantics_mismatch")
    return resolution


def keys_for(value: PersonaDefinition) -> tuple[str, tuple[int, int, int]]:
    if not isinstance(value, PersonaDefinition):
        raise validation_error("invalid_persona_definition")
    match = _VERSION_RE.fullmatch(value.version)
    if match is None:
        raise validation_error("invalid_persona_version")
    return value.persona_id, tuple(int(item) for item in match.groups())


def _unique_strings(
    values: tuple[str, ...],
    field: str,
    *,
    required: bool,
    maximum_length: int = 128,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_string_collection", field)
    try:
        result = tuple(values)
    except TypeError:
        raise validation_error("invalid_string_collection", field) from None
    if required and not result:
        raise validation_error("empty_collection", field)
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > maximum_length
        for value in result
    ):
        raise validation_error("invalid_collection_item", field)
    if len(result) != len(set(result)):
        raise validation_error("duplicate_identifier", field)
    return result


def _definitions(
    values: object,
    empty_code: str,
) -> tuple[PersonaDefinition, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error(empty_code)
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError:
        raise validation_error(empty_code) from None
    if not result or not all(isinstance(value, PersonaDefinition) for value in result):
        raise validation_error(empty_code)
    return result


def _channel_mapping(
    value: Mapping[ConversationType, PersonaChannelStyle],
) -> dict[ConversationType, PersonaChannelStyle]:
    try:
        return dict(value)
    except (TypeError, ValueError):
        raise validation_error("invalid_persona_channel_rules") from None


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


__all__ = [
    "PersonaCatalogSnapshot",
    "PersonaCatalogUpdate",
    "PersonaChannelStyle",
    "PersonaDefinition",
    "PersonaRendererMode",
    "PersonaResolution",
    "PersonaSentenceLength",
    "PersonaVoiceRules",
    "build_persona_definition",
    "keys_for",
    "persona_catalog_digest",
    "persona_definition_source_digest",
    "validate_persona_resolution",
]
