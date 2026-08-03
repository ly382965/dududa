from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import math
from types import MappingProxyType
from typing import Mapping, NewType, TypeAlias

from dududa.errors import validation_error
from dududa._compat import StrEnum


DigestString = NewType("DigestString", str)
ActionId = NewType("ActionId", str)
RoleId = NewType("RoleId", str)
DenyFlag = NewType("DenyFlag", str)

JsonScalar: TypeAlias = None | bool | int | float | Decimal | str
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


class ConversationType(StrEnum):
    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PrivacyLevel(StrEnum):
    PUBLIC = "public"
    CONVERSATION = "conversation"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class SideEffect(StrEnum):
    NONE = "none"
    NETWORK_READ = "network_read"
    PERSISTENT_WRITE = "persistent_write"
    EXTERNAL_WRITE = "external_write"
    MESSAGE_SEND = "message_send"
    FILE_WRITE = "file_write"


class Outcome(StrEnum):
    NO_REPLY = "no_reply"
    REACTION = "reaction"
    RESPONSE = "response"
    DEFERRED = "deferred"
    FAILED = "failed"


def require_non_empty(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise validation_error("empty_field", field)
    return normalized


def require_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise validation_error("naive_datetime", field)
    return value


def freeze_json(value: object, *, path: str = "$") -> JsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise validation_error("non_finite_number", path)
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise validation_error("non_finite_number", path)
        return value
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item, path=f"{path}[]") for item in value)
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise validation_error("non_string_mapping_key", path)
            frozen[key] = freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    raise validation_error("unsupported_json_value", path, type(value).__name__)


@dataclass(frozen=True, slots=True)
class SchemaRef:
    schema_id: str
    schema_version: int
    digest: DigestString

    def __post_init__(self) -> None:
        require_non_empty(self.schema_id, "schema_id")
        if self.schema_version < 1:
            raise validation_error("invalid_schema_version", "schema_version")
        require_non_empty(str(self.digest), "digest")


@dataclass(frozen=True, slots=True)
class ComponentRevision:
    component_id: str
    implementation_version: str
    config_revision: str
    artifact_digest: DigestString

    def __post_init__(self) -> None:
        for field, value in (
            ("component_id", self.component_id),
            ("implementation_version", self.implementation_version),
            ("config_revision", self.config_revision),
            ("artifact_digest", str(self.artifact_digest)),
        ):
            require_non_empty(value, field)


@dataclass(frozen=True, slots=True)
class ResourceRef:
    resource_type: str
    resource_id: str
    scope_digest: DigestString

    def __post_init__(self) -> None:
        require_non_empty(self.resource_type, "resource_type")
        require_non_empty(self.resource_id, "resource_id")
        require_non_empty(str(self.scope_digest), "scope_digest")


@dataclass(frozen=True, slots=True)
class RuntimeBudget:
    model_calls_remaining: int
    tool_steps_remaining: int
    retries_remaining: int
    input_tokens_remaining: int
    output_tokens_remaining: int
    cost_units_remaining: Decimal | None

    def __post_init__(self) -> None:
        if any(
            type(value) is not int
            for value in (
                self.model_calls_remaining,
                self.tool_steps_remaining,
                self.retries_remaining,
                self.input_tokens_remaining,
                self.output_tokens_remaining,
            )
        ):
            raise validation_error("invalid_budget_type")
        counts = (
            self.model_calls_remaining,
            self.tool_steps_remaining,
            self.retries_remaining,
            self.input_tokens_remaining,
            self.output_tokens_remaining,
        )
        if any(value < 0 for value in counts):
            raise validation_error("negative_budget")
        if self.cost_units_remaining is not None:
            if (
                not isinstance(self.cost_units_remaining, Decimal)
                or not self.cost_units_remaining.is_finite()
            ):
                raise validation_error("invalid_budget_type", "cost_units_remaining")
            if self.cost_units_remaining < 0:
                raise validation_error("negative_budget", "cost_units_remaining")


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    schema_version: int
    model_calls: int = 0
    tool_steps: int = 0
    retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_units: Decimal | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        values = (
            self.model_calls,
            self.tool_steps,
            self.retries,
            self.input_tokens,
            self.output_tokens,
        )
        if any(type(value) is not int for value in values):
            raise validation_error("invalid_resource_usage_type")
        if any(value < 0 for value in values):
            raise validation_error("negative_resource_usage")
        if self.cost_units is not None:
            if (
                not isinstance(self.cost_units, Decimal)
                or not self.cost_units.is_finite()
            ):
                raise validation_error("invalid_resource_usage_type", "cost_units")
            if self.cost_units < 0:
                raise validation_error("negative_resource_usage", "cost_units")


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    parent_span_id: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.trace_id, "trace_id")


@dataclass(frozen=True, slots=True)
class ResponseConstraints:
    max_characters: int | None = None
    allow_markdown: bool = True
    allow_attachments: bool = True
    required_notice_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_characters is not None and self.max_characters < 1:
            raise validation_error("invalid_response_limit")
