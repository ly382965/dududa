from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
import re
from typing import Generic, Mapping, TypeVar

from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    SchemaRef,
    require_aware,
    require_non_empty,
)
from dududa.errors import DududaError, ErrorCategory, ErrorInfo, validation_error


PortT = TypeVar("PortT")
_PROTOCOL_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)


@dataclass(frozen=True, slots=True)
class PortOperationDescriptor:
    operation_id: str
    accepted_input_schemas: tuple[SchemaRef, ...]
    emitted_output_schemas: tuple[SchemaRef, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.operation_id, "operation_id")
        accepted = tuple(self.accepted_input_schemas)
        emitted = tuple(self.emitted_output_schemas)
        if not accepted or not emitted:
            raise validation_error("empty_port_operation_schema", self.operation_id)
        _ensure_unique_schemas(accepted, self.operation_id)
        _ensure_unique_schemas(emitted, self.operation_id)
        object.__setattr__(self, "accepted_input_schemas", accepted)
        object.__setattr__(self, "emitted_output_schemas", emitted)


@dataclass(frozen=True, slots=True)
class PortDescriptor:
    port_id: str
    protocol_version: str
    operations: tuple[PortOperationDescriptor, ...]
    supported_capability_flags: frozenset[str]
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        require_non_empty(self.port_id, "port_id")
        _protocol_major(self.protocol_version)
        operations = tuple(self.operations)
        flags = frozenset(self.supported_capability_flags)
        if not operations:
            raise validation_error("empty_port_descriptor", self.port_id)
        _ensure_unique_operations(item.operation_id for item in operations)
        if any(not isinstance(flag, str) or not flag.strip() for flag in flags):
            raise validation_error("empty_capability_flag")
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "supported_capability_flags", flags)


@dataclass(frozen=True, slots=True)
class PortOperationRequirement:
    operation_id: str
    input_schema: SchemaRef
    accepted_output_schemas: tuple[SchemaRef, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.operation_id, "operation_id")
        accepted = tuple(self.accepted_output_schemas)
        if not accepted:
            raise validation_error("empty_required_output_schema", self.operation_id)
        _ensure_unique_schemas(accepted, self.operation_id)
        object.__setattr__(self, "accepted_output_schemas", accepted)


@dataclass(frozen=True, slots=True)
class PortBindingRequirement:
    port_id: str
    protocol_major: int
    operations: tuple[PortOperationRequirement, ...]
    required_capability_flags: frozenset[str]

    def __post_init__(self) -> None:
        require_non_empty(self.port_id, "port_id")
        if type(self.protocol_major) is not int or self.protocol_major < 1:
            raise validation_error("invalid_protocol_major")
        operations = tuple(self.operations)
        flags = frozenset(self.required_capability_flags)
        if not operations:
            raise validation_error("empty_port_requirement", self.port_id)
        _ensure_unique_operations(item.operation_id for item in operations)
        if any(not isinstance(flag, str) or not flag.strip() for flag in flags):
            raise validation_error("empty_capability_flag")
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "required_capability_flags", flags)


@dataclass(frozen=True, slots=True)
class PortBinding(Generic[PortT]):
    requirement: PortBindingRequirement
    descriptor: PortDescriptor
    implementation: PortT


@dataclass(frozen=True, slots=True)
class NegotiatedBindingReceipt:
    schema_version: int
    port_id: str
    protocol_version: str
    operation_schema_digests: Mapping[str, tuple[DigestString, DigestString]]
    enabled_capability_flags: frozenset[str]
    component_revision: ComponentRevision
    negotiated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise validation_error("unsupported_binding_receipt_version")
        require_non_empty(self.port_id, "port_id")
        _protocol_major(self.protocol_version)
        require_aware(self.negotiated_at, "negotiated_at")
        frozen = {
            operation_id: tuple(digests)
            for operation_id, digests in self.operation_schema_digests.items()
        }
        if any(len(digests) != 2 for digests in frozen.values()):
            raise validation_error("invalid_operation_schema_digest")
        object.__setattr__(self, "operation_schema_digests", MappingProxyType(frozen))
        object.__setattr__(
            self,
            "enabled_capability_flags",
            frozenset(self.enabled_capability_flags),
        )


def bind_port(
    requirement: PortBindingRequirement,
    descriptor: PortDescriptor,
    implementation: PortT,
    *,
    implementation_protocol: type[object],
    negotiated_at: datetime,
) -> tuple[PortBinding[PortT], NegotiatedBindingReceipt]:
    """Fail-closed negotiation for every required operation and capability."""

    require_aware(negotiated_at, "negotiated_at")
    if not getattr(implementation_protocol, "_is_runtime_protocol", False):
        raise validation_error("binding_protocol_not_runtime_checkable")
    if not isinstance(implementation, implementation_protocol):
        raise _binding_error("implementation_protocol_mismatch")
    if descriptor.port_id != requirement.port_id:
        raise _binding_error("port_id_mismatch")
    if _protocol_major(descriptor.protocol_version) != requirement.protocol_major:
        raise _binding_error("protocol_major_mismatch")
    missing_flags = (
        requirement.required_capability_flags - descriptor.supported_capability_flags
    )
    if missing_flags:
        raise _binding_error("missing_required_capability", *sorted(missing_flags))

    offered = {item.operation_id: item for item in descriptor.operations}
    negotiated: dict[str, tuple[DigestString, DigestString]] = {}
    for operation in requirement.operations:
        candidate = offered.get(operation.operation_id)
        if candidate is None:
            raise _binding_error("missing_required_operation", operation.operation_id)
        input_schema = _exact_schema(
            operation.input_schema, candidate.accepted_input_schemas
        )
        if input_schema is None:
            raise _binding_error("input_schema_mismatch", operation.operation_id)
        output_candidates = tuple(
            schema
            for schema in operation.accepted_output_schemas
            if _exact_schema(schema, candidate.emitted_output_schemas) is not None
        )
        if not output_candidates:
            raise _binding_error("output_schema_mismatch", operation.operation_id)
        selected_output = max(
            output_candidates, key=lambda schema: schema.schema_version
        )
        negotiated[operation.operation_id] = (
            input_schema.digest,
            selected_output.digest,
        )

    binding = PortBinding(requirement, descriptor, implementation)
    receipt = NegotiatedBindingReceipt(
        schema_version=1,
        port_id=requirement.port_id,
        protocol_version=descriptor.protocol_version,
        operation_schema_digests=negotiated,
        enabled_capability_flags=requirement.required_capability_flags,
        component_revision=descriptor.component_revision,
        negotiated_at=negotiated_at,
    )
    return binding, receipt


def _protocol_major(value: str) -> int:
    match = _PROTOCOL_VERSION_RE.fullmatch(value)
    if match is None:
        raise validation_error("invalid_protocol_version", value)
    return int(match.group(1))


def _exact_schema(
    required: SchemaRef, offered: tuple[SchemaRef, ...]
) -> SchemaRef | None:
    return next((schema for schema in offered if schema == required), None)


def _ensure_unique_operations(operation_ids: object) -> None:
    values = tuple(operation_ids)  # type: ignore[arg-type]
    if len(values) != len(set(values)):
        raise validation_error("duplicate_port_operation")


def _ensure_unique_schemas(schemas: tuple[SchemaRef, ...], operation_id: str) -> None:
    keys = tuple((item.schema_id, item.schema_version, item.digest) for item in schemas)
    if len(keys) != len(set(keys)):
        raise validation_error("duplicate_operation_schema", operation_id)


def _binding_error(code: str, *reason_codes: str) -> DududaError:
    return DududaError(
        ErrorInfo(
            schema_version=1,
            code=code,
            category=ErrorCategory.CONFLICT,
            retryable=False,
            outcome_unknown=False,
            public_message_key="runtime.port_incompatible",
            reason_codes=tuple(reason_codes),
        )
    )
