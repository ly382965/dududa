from __future__ import annotations

import re
from dataclasses import dataclass

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.errors import validation_error

from .primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    PrivacyLevel,
    RiskLevel,
    SchemaRef,
    SideEffect,
    require_non_empty,
)

_CAPABILITY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,123}\.v[1-9][0-9]*$")
_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_MAX_NAME_LENGTH = 256
_MAX_DESCRIPTION_LENGTH = 4_096
_MAX_CATEGORY_LENGTH = 128
_MAX_PERMISSION_COUNT = 32
_MAX_TAG_COUNT = 64
_MAX_HINT_UNITS = 1_000_000_000
_MAX_LATENCY_MS = 600_000


class Idempotency(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    NON_IDEMPOTENT = "non_idempotent"


@dataclass(frozen=True, slots=True)
class ProviderRef:
    provider_id: str
    revision: ComponentRevision

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "provider_id", pattern=_PROVIDER_ID)
        if not isinstance(self.revision, ComponentRevision):
            raise validation_error("invalid_capability_provider_revision")


@dataclass(frozen=True, slots=True)
class CostHint:
    units: int

    def __post_init__(self) -> None:
        if type(self.units) is not int or not 0 <= self.units <= _MAX_HINT_UNITS:
            raise validation_error("invalid_cost_hint")


@dataclass(frozen=True, slots=True)
class LatencyHint:
    expected_ms: int
    maximum_ms: int

    def __post_init__(self) -> None:
        if (
            type(self.expected_ms) is not int
            or type(self.maximum_ms) is not int
            or self.expected_ms < 0
            or self.maximum_ms < self.expected_ms
            or self.maximum_ms > _MAX_LATENCY_MS
        ):
            raise validation_error("invalid_latency_hint")


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    schema_version: int
    capability_id: str
    definition_digest: DigestString
    name: str
    description: str
    category: str
    provider: ProviderRef
    input_schema: SchemaRef
    output_schema: SchemaRef
    risk_level: RiskLevel
    privacy_level: PrivacyLevel
    allowed_contexts: frozenset[ConversationType]
    required_permissions: frozenset[str]
    cost_hint: CostHint
    latency_hint: LatencyHint
    tags: frozenset[str]
    idempotency: Idempotency
    side_effects: frozenset[SideEffect]
    enabled: bool = True

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_capability_definition_version")
        _identifier(self.capability_id, "capability_id", pattern=_CAPABILITY_ID)
        _bounded(self.name, "capability_name", _MAX_NAME_LENGTH)
        _bounded(
            self.description,
            "capability_description",
            _MAX_DESCRIPTION_LENGTH,
        )
        _bounded(self.category, "capability_category", _MAX_CATEGORY_LENGTH)
        if not isinstance(self.provider, ProviderRef):
            raise validation_error("invalid_capability_provider")
        if not isinstance(self.input_schema, SchemaRef) or not isinstance(
            self.output_schema, SchemaRef
        ):
            raise validation_error("invalid_capability_schema_reference")
        if not isinstance(self.risk_level, RiskLevel) or not isinstance(
            self.privacy_level, PrivacyLevel
        ):
            raise validation_error("invalid_capability_classification")
        if not isinstance(self.cost_hint, CostHint) or not isinstance(
            self.latency_hint, LatencyHint
        ):
            raise validation_error("invalid_capability_hint")
        if not isinstance(self.idempotency, Idempotency):
            raise validation_error("invalid_capability_idempotency")
        if type(self.enabled) is not bool:
            raise validation_error("invalid_capability_enabled")

        allowed_contexts = frozenset(self.allowed_contexts)
        required_permissions = frozenset(self.required_permissions)
        tags = frozenset(self.tags)
        side_effects = frozenset(self.side_effects)
        if not allowed_contexts or any(
            not isinstance(item, ConversationType) for item in allowed_contexts
        ):
            raise validation_error("invalid_capability_context")
        _bounded_string_set(
            required_permissions,
            "capability_permission",
            maximum_items=_MAX_PERMISSION_COUNT,
            required=True,
        )
        _bounded_string_set(
            tags,
            "capability_tag",
            maximum_items=_MAX_TAG_COUNT,
            required=False,
        )
        if not side_effects or any(
            not isinstance(item, SideEffect) for item in side_effects
        ):
            raise validation_error("invalid_capability_side_effect")
        if SideEffect.NONE in side_effects and len(side_effects) != 1:
            raise validation_error("capability_none_side_effect_mixed")
        if self.idempotency is Idempotency.READ_ONLY and side_effects - {
            SideEffect.NONE,
            SideEffect.NETWORK_READ,
        }:
            raise validation_error("read_only_capability_has_write_effect")

        object.__setattr__(self, "allowed_contexts", allowed_contexts)
        object.__setattr__(self, "required_permissions", required_permissions)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "side_effects", side_effects)
        require_non_empty(str(self.definition_digest), "definition_digest")
        if self.definition_digest != capability_definition_digest(self):
            raise validation_error("capability_definition_digest_mismatch")


def capability_definition_digest(
    definition: CapabilityDefinition | dict[str, object],
) -> DigestString:
    if isinstance(definition, CapabilityDefinition):
        value: object = {
            "schema_version": definition.schema_version,
            "capability_id": definition.capability_id,
            "name": definition.name,
            "description": definition.description,
            "category": definition.category,
            "provider": definition.provider,
            "input_schema": definition.input_schema,
            "output_schema": definition.output_schema,
            "risk_level": definition.risk_level,
            "privacy_level": definition.privacy_level,
            "allowed_contexts": definition.allowed_contexts,
            "required_permissions": definition.required_permissions,
            "cost_hint": definition.cost_hint,
            "latency_hint": definition.latency_hint,
            "tags": definition.tags,
            "idempotency": definition.idempotency,
            "side_effects": definition.side_effects,
            "enabled": definition.enabled,
        }
    else:
        value = definition
    return canonical_digest(value, domain="capability.definition:v1")


def _bounded(value: str, field: str, maximum: int) -> str:
    normalized = require_non_empty(value, field)
    if len(normalized.encode("utf-8")) > maximum:
        raise validation_error("capability_string_too_large", field)
    return normalized


def _identifier(
    value: str,
    field: str,
    *,
    pattern: re.Pattern[str],
) -> str:
    normalized = _bounded(value, field, 128)
    if pattern.fullmatch(normalized) is None:
        raise validation_error("invalid_capability_identifier", field)
    return normalized


def _bounded_string_set(
    values: frozenset[str],
    field: str,
    *,
    maximum_items: int,
    required: bool,
) -> None:
    if (required and not values) or len(values) > maximum_items:
        raise validation_error("invalid_capability_string_set", field)
    for value in values:
        if not isinstance(value, str):
            raise validation_error("invalid_capability_string_set", field)
        _bounded(value, field, 128)


__all__ = [
    "CapabilityDefinition",
    "CostHint",
    "Idempotency",
    "LatencyHint",
    "ProviderRef",
    "capability_definition_digest",
]
