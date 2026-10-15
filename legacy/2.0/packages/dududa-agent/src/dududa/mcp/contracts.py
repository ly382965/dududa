from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from dududa._compat import StrEnum
from dududa.contracts.canonical import (
    canonical_digest,
    canonical_json_bytes,
    canonical_schema_digest,
)
from dududa.domain.primitives import (
    DigestString,
    JsonValue,
    freeze_json,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext

MAX_IDENTIFIER_LENGTH = 128
MAX_DESCRIPTION_LENGTH = 4_096
MAX_TOOL_COUNT = 256
MAX_CONTENT_BLOCKS = 32
MAX_CONTENT_BYTES = 1_048_576
MAX_ARGUMENT_BYTES = 65_536
MAX_SCHEMA_BYTES = 262_144
MAX_SCHEMA_SNAPSHOT_BYTES = 4_194_304
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 10_000
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_SERVER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_DIGEST = re.compile(
    r"^(?:sha-256:[0-9a-f]{64}|"
    r"dududa-c14n-v1:[a-z0-9][a-z0-9._:/-]*:v[1-9][0-9]*:sha-256:[0-9a-f]{64})$"
)


class McpTransportKind(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class McpProtocolMode(StrEnum):
    AUTO = "auto"
    LEGACY = "legacy"


class McpSecretTarget(StrEnum):
    ENV = "env"
    HEADER = "header"


class McpOperationSemantics(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"


class McpContentKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    RESOURCE = "resource"
    EMBEDDED_RESOURCE = "embedded_resource"


class McpHealthStatus(StrEnum):
    INITIALIZING = "initializing"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    CIRCUIT_OPEN = "circuit_open"
    CLOSED = "closed"


class McpTransportPhase(StrEnum):
    CONNECT = "connect"
    DISCOVERY = "discovery"
    CALL = "call"
    CLOSE = "close"


class McpDispatchState(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    DISPATCHED = "dispatched"
    UNKNOWN = "unknown"


class McpTransportFailureKind(StrEnum):
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PROTOCOL = "protocol"
    CLOSED = "closed"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class McpSecretRef:
    secret_id: str
    target: McpSecretTarget
    target_name: str

    def __post_init__(self) -> None:
        _identifier(self.secret_id, "secret_id")
        if not isinstance(self.target, McpSecretTarget):
            raise validation_error("invalid_mcp_secret_target")
        target_name = _bounded(self.target_name, "secret_target_name")
        if (
            self.target is McpSecretTarget.ENV
            and _ENV_NAME.fullmatch(target_name) is None
        ):
            raise validation_error("invalid_mcp_environment_name")
        if self.target is McpSecretTarget.HEADER and any(
            character in target_name for character in "\r\n:"
        ):
            raise validation_error("invalid_mcp_header_name")


@dataclass(frozen=True, slots=True)
class McpStdioEndpoint:
    command: str
    args: tuple[str, ...]
    cwd: str
    env_allowlist: frozenset[str]

    def __post_init__(self) -> None:
        command = _bounded(self.command, "mcp_stdio_command", maximum=4_096)
        cwd = _bounded(self.cwd, "mcp_stdio_cwd", maximum=4_096)
        if not command.startswith("/") or not cwd.startswith("/"):
            raise validation_error("mcp_stdio_path_not_absolute")
        args = _string_tuple(
            self.args, "mcp_stdio_args", maximum_items=128, maximum_length=4_096
        )
        environment = frozenset(self.env_allowlist)
        if len(environment) > 64 or any(
            not isinstance(item, str) or _ENV_NAME.fullmatch(item) is None
            for item in environment
        ):
            raise validation_error("invalid_mcp_environment_allowlist")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "args", args)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "env_allowlist", environment)


@dataclass(frozen=True, slots=True)
class McpHttpEndpoint:
    url: str
    allowed_hosts: frozenset[str]

    def __post_init__(self) -> None:
        url = _bounded(self.url, "mcp_http_url", maximum=4_096)
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
        ):
            raise validation_error("invalid_mcp_http_url")
        hosts = frozenset(
            _bounded(item, "mcp_allowed_host", maximum=253).lower()
            for item in self.allowed_hosts
        )
        if not hosts or len(hosts) > 32 or parsed.hostname.lower() not in hosts:
            raise validation_error("mcp_http_host_not_allowed")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "allowed_hosts", hosts)


McpEndpoint = McpStdioEndpoint | McpHttpEndpoint


@dataclass(frozen=True, slots=True)
class McpTimeoutPolicy:
    connect: timedelta
    discovery: timedelta
    call: timedelta
    maximum_call: timedelta
    close: timedelta

    def __post_init__(self) -> None:
        for field_name in ("connect", "discovery", "call", "maximum_call", "close"):
            value = getattr(self, field_name)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise validation_error("invalid_mcp_timeout", field_name)
            if value > timedelta(minutes=10):
                raise validation_error("mcp_timeout_too_large", field_name)
        if self.call > self.maximum_call:
            raise validation_error("invalid_mcp_call_timeout_order")


@dataclass(frozen=True, slots=True)
class McpRetryPolicy:
    maximum_attempts: int
    base_delay: timedelta

    def __post_init__(self) -> None:
        if (
            type(self.maximum_attempts) is not int
            or not 1 <= self.maximum_attempts <= 2
        ):
            raise validation_error("invalid_mcp_retry_attempts")
        if (
            not isinstance(self.base_delay, timedelta)
            or self.base_delay < timedelta(0)
            or self.base_delay > timedelta(seconds=5)
        ):
            raise validation_error("invalid_mcp_retry_delay")


@dataclass(frozen=True, slots=True)
class McpCircuitPolicy:
    failure_threshold: int
    failure_window: timedelta
    open_duration: timedelta

    def __post_init__(self) -> None:
        if (
            type(self.failure_threshold) is not int
            or not 1 <= self.failure_threshold <= 100
        ):
            raise validation_error("invalid_mcp_circuit_threshold")
        for field_name in ("failure_window", "open_duration"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, timedelta)
                or value <= timedelta(0)
                or value > timedelta(hours=1)
            ):
                raise validation_error("invalid_mcp_circuit_duration", field_name)


@dataclass(frozen=True, slots=True)
class McpServerDefinition:
    schema_version: int
    server_id: str
    enabled: bool
    transport: McpTransportKind
    protocol_mode: McpProtocolMode
    endpoint: McpEndpoint
    secret_refs: tuple[McpSecretRef, ...]
    allowed_tools: frozenset[str]
    denied_tools: frozenset[str]
    timeouts: McpTimeoutPolicy
    retry: McpRetryPolicy
    circuit: McpCircuitPolicy
    maximum_concurrency: int
    schema_ttl: timedelta
    config_revision: str
    definition_digest: DigestString

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_mcp_server_schema_version")
        _server_id(self.server_id)
        if type(self.enabled) is not bool:
            raise validation_error("invalid_mcp_enabled")
        if not isinstance(self.transport, McpTransportKind):
            raise validation_error("invalid_mcp_transport")
        if not isinstance(self.protocol_mode, McpProtocolMode):
            raise validation_error("invalid_mcp_protocol_mode")
        if self.transport is McpTransportKind.STDIO and not isinstance(
            self.endpoint, McpStdioEndpoint
        ):
            raise validation_error("mcp_transport_endpoint_mismatch")
        if self.transport is McpTransportKind.STREAMABLE_HTTP and not isinstance(
            self.endpoint, McpHttpEndpoint
        ):
            raise validation_error("mcp_transport_endpoint_mismatch")
        refs = tuple(self.secret_refs)
        if len(refs) > 32 or not all(isinstance(item, McpSecretRef) for item in refs):
            raise validation_error("invalid_mcp_secret_refs")
        ref_targets = {(item.target, item.target_name.lower()) for item in refs}
        if len(ref_targets) != len(refs):
            raise validation_error("duplicate_mcp_secret_target")
        if isinstance(self.endpoint, McpStdioEndpoint) and any(
            item.target is not McpSecretTarget.ENV for item in refs
        ):
            raise validation_error("mcp_secret_target_transport_mismatch")
        if isinstance(self.endpoint, McpHttpEndpoint) and any(
            item.target is not McpSecretTarget.HEADER for item in refs
        ):
            raise validation_error("mcp_secret_target_transport_mismatch")
        allowed = _tool_set(self.allowed_tools, "allowed_tools", require_non_empty=True)
        denied = _tool_set(self.denied_tools, "denied_tools")
        if allowed & denied:
            raise validation_error("conflicting_mcp_tool_policy")
        if not isinstance(self.timeouts, McpTimeoutPolicy):
            raise validation_error("invalid_mcp_timeout_policy")
        if not isinstance(self.retry, McpRetryPolicy):
            raise validation_error("invalid_mcp_retry_policy")
        if not isinstance(self.circuit, McpCircuitPolicy):
            raise validation_error("invalid_mcp_circuit_policy")
        if (
            type(self.maximum_concurrency) is not int
            or not 1 <= self.maximum_concurrency <= 64
        ):
            raise validation_error("invalid_mcp_concurrency")
        if (
            not isinstance(self.schema_ttl, timedelta)
            or self.schema_ttl <= timedelta(0)
            or self.schema_ttl > timedelta(days=1)
        ):
            raise validation_error("invalid_mcp_schema_ttl")
        _identifier(self.config_revision, "mcp_config_revision")
        _digest(self.definition_digest, "mcp_definition_digest")
        object.__setattr__(self, "secret_refs", refs)
        object.__setattr__(self, "allowed_tools", allowed)
        object.__setattr__(self, "denied_tools", denied)
        expected_digest = canonical_digest(
            {
                "schema_version": self.schema_version,
                "server_id": self.server_id,
                "enabled": self.enabled,
                "transport": self.transport,
                "protocol_mode": self.protocol_mode,
                "endpoint": self.endpoint,
                "secret_refs": refs,
                "allowed_tools": allowed,
                "denied_tools": denied,
                "timeouts": self.timeouts,
                "retry": self.retry,
                "circuit": self.circuit,
                "maximum_concurrency": self.maximum_concurrency,
                "schema_ttl": self.schema_ttl,
                "config_revision": self.config_revision,
            },
            domain="mcp.server-definition:v1",
        )
        if self.definition_digest != expected_digest:
            raise validation_error("mcp_definition_digest_mismatch")


@dataclass(frozen=True, slots=True)
class McpRegistrySnapshot:
    schema_version: int
    snapshot_id: str
    registry_revision: str
    registry_digest: DigestString
    definitions: tuple[McpServerDefinition, ...]
    acquired_at: datetime

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_mcp_registry_schema_version")
        _identifier(self.snapshot_id, "mcp_registry_snapshot_id")
        _identifier(self.registry_revision, "mcp_registry_revision")
        _digest(self.registry_digest, "mcp_registry_digest")
        definitions = tuple(self.definitions)
        if (
            not definitions
            or len(definitions) > 128
            or not all(isinstance(item, McpServerDefinition) for item in definitions)
        ):
            raise validation_error("invalid_mcp_registry_definitions")
        ids = tuple(item.server_id for item in definitions)
        if len(ids) != len(set(ids)) or ids != tuple(sorted(ids)):
            raise validation_error("invalid_mcp_registry_definition_order")
        require_aware(self.acquired_at, "mcp_registry_acquired_at")
        object.__setattr__(self, "definitions", definitions)
        expected_digest = canonical_digest(
            tuple(
                (item.server_id, item.config_revision, item.definition_digest)
                for item in definitions
            ),
            domain="mcp.registry:v1",
        )
        if self.registry_digest != expected_digest:
            raise validation_error("mcp_registry_digest_mismatch")


@dataclass(frozen=True, slots=True)
class McpToolDescriptor:
    schema_version: int
    name: str
    description: str
    input_schema: Mapping[str, JsonValue]
    output_schema: Mapping[str, JsonValue] | None
    annotations: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_mcp_tool_schema_version")
        _tool_name(self.name)
        description = _bounded(
            self.description,
            "mcp_tool_description",
            maximum=MAX_DESCRIPTION_LENGTH,
            allow_empty=True,
        )
        input_schema = _schema(self.input_schema, f"mcp.tool.{self.name}.input")
        output_schema = (
            None
            if self.output_schema is None
            else _schema(self.output_schema, f"mcp.tool.{self.name}.output")
        )
        annotations = _mapping(self.annotations, "mcp_tool_annotations")
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "input_schema", input_schema)
        object.__setattr__(self, "output_schema", output_schema)
        object.__setattr__(self, "annotations", annotations)


@dataclass(frozen=True, slots=True)
class McpSchemaSnapshot:
    schema_version: int
    snapshot_id: str
    snapshot_digest: DigestString
    server_id: str
    config_revision: str
    definition_digest: DigestString
    schema_facts_digest: DigestString
    generation: int
    tools: tuple[McpToolDescriptor, ...]
    observed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_mcp_snapshot_schema_version")
        _identifier(self.snapshot_id, "mcp_schema_snapshot_id")
        _digest(self.snapshot_digest, "mcp_schema_snapshot_digest")
        _server_id(self.server_id)
        _identifier(self.config_revision, "mcp_schema_config_revision")
        _digest(self.definition_digest, "mcp_schema_definition_digest")
        _digest(self.schema_facts_digest, "mcp_schema_facts_digest")
        if type(self.generation) is not int or self.generation < 1:
            raise validation_error("invalid_mcp_generation")
        tools = tuple(self.tools)
        if (
            not tools
            or len(tools) > MAX_TOOL_COUNT
            or not all(isinstance(item, McpToolDescriptor) for item in tools)
        ):
            raise validation_error("invalid_mcp_schema_tools")
        names = tuple(item.name for item in tools)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise validation_error("invalid_mcp_schema_tool_order")
        if len(canonical_json_bytes(tools)) > MAX_SCHEMA_SNAPSHOT_BYTES:
            raise validation_error("mcp_schema_snapshot_size_limit")
        require_aware(self.observed_at, "mcp_schema_observed_at")
        require_aware(self.expires_at, "mcp_schema_expires_at")
        if self.expires_at <= self.observed_at:
            raise validation_error("invalid_mcp_schema_freshness")
        object.__setattr__(self, "tools", tools)
        expected_facts_digest = canonical_digest(
            tuple(
                {
                    "name": item.name,
                    "input_schema": item.input_schema,
                    "output_schema": item.output_schema,
                }
                for item in tools
            ),
            domain="mcp.tool-schema-facts:v1",
        )
        if self.schema_facts_digest != expected_facts_digest:
            raise validation_error("mcp_schema_facts_digest_mismatch")
        expected_digest = canonical_digest(
            {
                "server_id": self.server_id,
                "config_revision": self.config_revision,
                "definition_digest": self.definition_digest,
                "schema_facts_digest": self.schema_facts_digest,
                "generation": self.generation,
                "tools": tools,
            },
            domain="mcp.schema-snapshot:v1",
        )
        if self.snapshot_digest != expected_digest:
            raise validation_error("mcp_schema_snapshot_digest_mismatch")


@dataclass(frozen=True, slots=True)
class McpCallContext:
    schema_version: int
    caller: PortCallContext | ServiceCallContext
    schema_snapshot_id: str
    schema_snapshot_digest: DigestString
    request_digest: DigestString
    semantics: McpOperationSemantics
    business_idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_mcp_call_context_version")
        if not isinstance(self.caller, (PortCallContext, ServiceCallContext)):
            raise validation_error("invalid_mcp_caller_context")
        _identifier(self.schema_snapshot_id, "mcp_call_schema_snapshot_id")
        _digest(self.schema_snapshot_digest, "mcp_call_schema_snapshot_digest")
        _digest(self.request_digest, "mcp_call_request_digest")
        if not isinstance(self.semantics, McpOperationSemantics):
            raise validation_error("invalid_mcp_operation_semantics")
        if self.business_idempotency_key is not None:
            _identifier(self.business_idempotency_key, "mcp_business_idempotency_key")


@dataclass(frozen=True, slots=True)
class McpContentBlock:
    schema_version: int
    kind: McpContentKind
    text: str | None
    mime_type: str | None
    uri: str | None
    data_digest: DigestString | None
    size_bytes: int
    data_base64: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_mcp_content_version")
        if not isinstance(self.kind, McpContentKind):
            raise validation_error("invalid_mcp_content_kind")
        if (
            type(self.size_bytes) is not int
            or not 0 <= self.size_bytes <= MAX_CONTENT_BYTES
        ):
            raise validation_error("invalid_mcp_content_size")
        if self.text is not None:
            _bounded(
                self.text,
                "mcp_content_text",
                maximum=MAX_CONTENT_BYTES,
                allow_empty=True,
            )
        if self.mime_type is not None:
            _bounded(self.mime_type, "mcp_content_mime", maximum=255)
        if self.uri is not None:
            _bounded(self.uri, "mcp_content_uri", maximum=4_096)
        if self.data_digest is not None:
            _digest(self.data_digest, "mcp_content_data_digest")
        decoded_data: bytes | None = None
        if self.data_base64 is not None:
            encoded = _bounded(
                self.data_base64,
                "mcp_content_base64",
                maximum=((MAX_CONTENT_BYTES + 2) // 3) * 4,
                allow_empty=True,
            )
            try:
                decoded_data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise validation_error("invalid_mcp_content_base64") from exc
            if len(decoded_data) != self.size_bytes:
                raise validation_error("mcp_binary_size_mismatch")
            object.__setattr__(self, "data_base64", encoded)
        if self.kind is McpContentKind.TEXT:
            if (
                self.text is None
                or self.uri is not None
                or self.data_digest is not None
                or self.data_base64 is not None
            ):
                raise validation_error("invalid_mcp_text_content")
            if len(self.text.encode("utf-8")) != self.size_bytes:
                raise validation_error("mcp_text_size_mismatch")
        elif self.kind is McpContentKind.IMAGE:
            if (
                self.text is not None
                or self.uri is not None
                or self.mime_type is None
                or self.data_digest is None
                or decoded_data is None
                or self.size_bytes == 0
            ):
                raise validation_error("invalid_mcp_image_content")
        elif self.kind is McpContentKind.RESOURCE:
            if (
                self.uri is None
                or self.text is not None
                or self.data_digest is not None
                or self.data_base64 is not None
                or self.size_bytes != 0
            ):
                raise validation_error("invalid_mcp_resource_content")
        elif self.kind is McpContentKind.EMBEDDED_RESOURCE:
            if (
                self.uri is None
                or (self.text is None) == (decoded_data is None)
                or (decoded_data is None) != (self.data_digest is None)
            ):
                raise validation_error("invalid_mcp_embedded_resource_content")
            if (
                self.text is not None
                and len(self.text.encode("utf-8")) != self.size_bytes
            ):
                raise validation_error("mcp_embedded_resource_size_mismatch")
            if self.data_digest is not None and self.size_bytes == 0:
                raise validation_error("invalid_mcp_embedded_resource_size")
        if decoded_data is not None:
            expected = f"sha-256:{hashlib.sha256(decoded_data).hexdigest()}"
            if str(self.data_digest) != expected:
                raise validation_error("mcp_binary_digest_mismatch")


@dataclass(frozen=True, slots=True)
class McpTransportToolResult:
    """Normalized, untrusted transport observation before client binding."""

    schema_version: int
    is_error: bool
    structured_content: JsonValue | None
    content: tuple[McpContentBlock, ...]
    total_size_bytes: int

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_mcp_transport_result_version")
        if type(self.is_error) is not bool:
            raise validation_error("invalid_mcp_transport_result_flags")
        structured = (
            None
            if self.structured_content is None
            else freeze_mcp_json(
                self.structured_content,
                "mcp_transport_result",
                maximum_bytes=MAX_CONTENT_BYTES,
            )
        )
        content = tuple(self.content)
        if len(content) > MAX_CONTENT_BLOCKS or not all(
            isinstance(item, McpContentBlock) for item in content
        ):
            raise validation_error("invalid_mcp_transport_result_content")
        if (
            type(self.total_size_bytes) is not int
            or not 0 <= self.total_size_bytes <= MAX_CONTENT_BYTES
        ):
            raise validation_error("invalid_mcp_transport_result_size")
        measured_size = sum(item.size_bytes for item in content) + (
            0 if structured is None else len(canonical_json_bytes(structured))
        )
        if measured_size != self.total_size_bytes:
            raise validation_error("invalid_mcp_transport_result_size_accounting")
        object.__setattr__(self, "structured_content", structured)
        object.__setattr__(self, "content", content)


@dataclass(frozen=True, slots=True)
class McpToolResult:
    schema_version: int
    server_id: str
    tool_name: str
    generation: int
    schema_snapshot_id: str
    schema_snapshot_digest: DigestString
    request_digest: DigestString
    result_digest: DigestString
    is_error: bool
    structured_content: JsonValue | None
    content: tuple[McpContentBlock, ...]
    total_size_bytes: int
    untrusted: bool = True

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_mcp_result_version")
        _server_id(self.server_id)
        _tool_name(self.tool_name)
        if type(self.generation) is not int or self.generation < 1:
            raise validation_error("invalid_mcp_generation")
        _identifier(self.schema_snapshot_id, "mcp_result_schema_snapshot_id")
        _digest(self.schema_snapshot_digest, "mcp_result_schema_snapshot_digest")
        _digest(self.request_digest, "mcp_result_request_digest")
        _digest(self.result_digest, "mcp_result_digest")
        if type(self.is_error) is not bool or self.untrusted is not True:
            raise validation_error("invalid_mcp_result_flags")
        structured = (
            None
            if self.structured_content is None
            else freeze_mcp_json(
                self.structured_content,
                "mcp_result",
                maximum_bytes=MAX_CONTENT_BYTES,
            )
        )
        content = tuple(self.content)
        if len(content) > MAX_CONTENT_BLOCKS or not all(
            isinstance(item, McpContentBlock) for item in content
        ):
            raise validation_error("invalid_mcp_result_content")
        if (
            type(self.total_size_bytes) is not int
            or not 0 <= self.total_size_bytes <= MAX_CONTENT_BYTES
        ):
            raise validation_error("invalid_mcp_result_size")
        measured_size = sum(item.size_bytes for item in content) + (
            0 if structured is None else len(canonical_json_bytes(structured))
        )
        if measured_size != self.total_size_bytes:
            raise validation_error("invalid_mcp_result_size_accounting")
        object.__setattr__(self, "structured_content", structured)
        object.__setattr__(self, "content", content)
        expected_digest = canonical_digest(
            {
                "server_id": self.server_id,
                "tool_name": self.tool_name,
                "generation": self.generation,
                "schema_snapshot_id": self.schema_snapshot_id,
                "schema_snapshot_digest": self.schema_snapshot_digest,
                "request_digest": self.request_digest,
                "is_error": self.is_error,
                "structured_content": structured,
                "content": content,
            },
            domain="mcp.tool-result:v1",
        )
        if self.result_digest != expected_digest:
            raise validation_error("mcp_tool_result_digest_mismatch")


@dataclass(frozen=True, slots=True)
class McpServerHealth:
    schema_version: int
    server_id: str
    config_revision: str
    generation: int
    status: McpHealthStatus
    schema_snapshot_id: str | None
    observed_at: datetime
    circuit_open_until: datetime | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_mcp_health_version")
        _server_id(self.server_id)
        _identifier(self.config_revision, "mcp_health_config_revision")
        if type(self.generation) is not int or self.generation < 0:
            raise validation_error("invalid_mcp_generation")
        if not isinstance(self.status, McpHealthStatus):
            raise validation_error("invalid_mcp_health_status")
        if self.schema_snapshot_id is not None:
            _identifier(self.schema_snapshot_id, "mcp_health_schema_snapshot_id")
        require_aware(self.observed_at, "mcp_health_observed_at")
        if self.circuit_open_until is not None:
            require_aware(self.circuit_open_until, "mcp_circuit_open_until")
        reasons = _string_tuple(
            self.reason_codes,
            "mcp_health_reason_codes",
            maximum_items=16,
            maximum_length=128,
        )
        if len(reasons) != len(set(reasons)):
            raise validation_error("duplicate_mcp_health_reason_code")
        object.__setattr__(self, "reason_codes", reasons)


def _schema(value: object, schema_id: str) -> Mapping[str, JsonValue]:
    frozen = _mapping(value, "mcp_tool_schema", maximum_bytes=MAX_SCHEMA_BYTES)
    canonical_schema_digest(frozen, schema_id=schema_id, schema_version=1)
    return frozen


def _mapping(
    value: object,
    field: str,
    *,
    maximum_bytes: int = MAX_ARGUMENT_BYTES,
) -> Mapping[str, JsonValue]:
    frozen = freeze_mcp_json(value, field, maximum_bytes=maximum_bytes)
    if not isinstance(frozen, Mapping):
        raise validation_error("invalid_mcp_mapping", field)
    return MappingProxyType(dict(frozen))


def freeze_mcp_json(value: object, field: str, *, maximum_bytes: int) -> JsonValue:
    stack: list[tuple[object, int, bool]] = [(value, 0, False)]
    active: set[int] = set()
    nodes = 0
    while stack:
        item, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise validation_error("mcp_json_node_limit", field)
        if depth > MAX_JSON_DEPTH:
            raise validation_error("mcp_json_depth_limit", field)
        if isinstance(item, Mapping):
            identity = id(item)
            if identity in active:
                raise validation_error("cyclic_mcp_json", field)
            active.add(identity)
            stack.append((item, depth, True))
            for key, child in item.items():
                if not isinstance(key, str):
                    raise validation_error("non_string_mapping_key", field)
                stack.append((child, depth + 1, False))
        elif isinstance(item, (list, tuple)):
            identity = id(item)
            if identity in active:
                raise validation_error("cyclic_mcp_json", field)
            active.add(identity)
            stack.append((item, depth, True))
            for child in item:
                stack.append((child, depth + 1, False))
    frozen = freeze_json(value, path=f"$.{field}")
    if len(canonical_json_bytes(frozen)) > maximum_bytes:
        raise validation_error("mcp_json_size_limit", field)
    return frozen


def _server_id(value: str) -> str:
    normalized = _bounded(value, "mcp_server_id")
    if _SERVER_ID.fullmatch(normalized) is None:
        raise validation_error("invalid_mcp_server_id")
    return normalized


def _tool_name(value: str) -> str:
    normalized = _bounded(value, "mcp_tool_name")
    if _TOOL_NAME.fullmatch(normalized) is None:
        raise validation_error("invalid_mcp_tool_name")
    return normalized


def _tool_set(
    value: object, field: str, *, require_non_empty: bool = False
) -> frozenset[str]:
    if isinstance(value, (str, bytes)) or not isinstance(
        value, (set, frozenset, tuple, list)
    ):
        raise validation_error("invalid_mcp_tool_set", field)
    tools = frozenset(_tool_name(item) for item in value)
    if len(tools) > MAX_TOOL_COUNT or (require_non_empty and not tools):
        raise validation_error("invalid_mcp_tool_set", field)
    return tools


def _identifier(value: str, field: str) -> str:
    normalized = _bounded(value, field)
    if any(character.isspace() for character in normalized):
        raise validation_error("invalid_identifier", field)
    return normalized


def _digest(value: DigestString, field: str) -> None:
    encoded = _bounded(str(value), field, maximum=512)
    if _DIGEST.fullmatch(encoded) is None:
        raise validation_error("invalid_digest", field)


def _bounded(
    value: object,
    field: str,
    *,
    maximum: int = MAX_IDENTIFIER_LENGTH,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise validation_error("invalid_string", field)
    if not allow_empty:
        require_non_empty(value, field)
    if len(value.encode("utf-8")) > maximum:
        raise validation_error("string_too_large", field)
    return value


def _string_tuple(
    value: object,
    field: str,
    *,
    maximum_items: int,
    maximum_length: int,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(
        value, (tuple, list, set, frozenset)
    ):
        raise validation_error("invalid_string_collection", field)
    items = tuple(_bounded(item, field, maximum=maximum_length) for item in value)
    if len(items) > maximum_items:
        raise validation_error("string_collection_too_large", field)
    return items
