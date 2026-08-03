from __future__ import annotations

from dataclasses import dataclass

from dududa._compat import StrEnum
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


class Idempotency(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    NON_IDEMPOTENT = "non_idempotent"


@dataclass(frozen=True, slots=True)
class ProviderRef:
    provider_id: str
    revision: ComponentRevision


@dataclass(frozen=True, slots=True)
class CostHint:
    units: int

    def __post_init__(self) -> None:
        if self.units < 0:
            raise validation_error("negative_cost_hint")


@dataclass(frozen=True, slots=True)
class LatencyHint:
    expected_ms: int
    maximum_ms: int

    def __post_init__(self) -> None:
        if self.expected_ms < 0 or self.maximum_ms < self.expected_ms:
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
        if self.schema_version < 1:
            raise validation_error("invalid_schema_version")
        require_non_empty(self.capability_id, "capability_id")
        require_non_empty(self.name, "name")
        require_non_empty(self.description, "description")
        require_non_empty(self.category, "category")
        if not isinstance(self.risk_level, RiskLevel) or not isinstance(
            self.privacy_level, PrivacyLevel
        ):
            raise validation_error("invalid_capability_classification")
        if not isinstance(self.idempotency, Idempotency):
            raise validation_error("invalid_capability_idempotency")
        allowed_contexts = frozenset(self.allowed_contexts)
        required_permissions = frozenset(self.required_permissions)
        tags = frozenset(self.tags)
        side_effects = frozenset(self.side_effects)
        if any(not isinstance(item, ConversationType) for item in allowed_contexts):
            raise validation_error("invalid_capability_context")
        if any(not isinstance(item, SideEffect) for item in side_effects):
            raise validation_error("invalid_capability_side_effect")
        if not allowed_contexts:
            raise validation_error("capability_has_no_context")
        if self.idempotency is Idempotency.READ_ONLY and side_effects - {
            SideEffect.NONE,
            SideEffect.NETWORK_READ,
        }:
            raise validation_error("read_only_capability_has_write_effect")
        object.__setattr__(self, "allowed_contexts", allowed_contexts)
        object.__setattr__(self, "required_permissions", required_permissions)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "side_effects", side_effects)
