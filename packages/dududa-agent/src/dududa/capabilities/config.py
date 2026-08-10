from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from dududa.domain.capability import (
    CapabilityDefinition,
    CostHint,
    Idempotency,
    LatencyHint,
    ProviderRef,
)
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    PrivacyLevel,
    RiskLevel,
    SchemaRef,
    SideEffect,
)
from dududa.errors import ErrorCategory, error, validation_error
from dududa.mcp.contracts import McpOperationSemantics
from dududa.ports.capabilities import CapabilitySchemaValidator

from .contracts import (
    MAX_CAPABILITY_DEFINITIONS,
    CapabilityCatalogSnapshot,
    CapabilityCatalogUpdate,
    CapabilityProviderDescriptor,
    CapabilityProviderKind,
    CapabilitySchemaDocument,
    McpCapabilityMapping,
)
from .digests import (
    capability_catalog_digest,
    capability_catalog_update_digest,
    capability_provider_descriptor_digest,
    mcp_capability_mapping_digest,
)
from .registry import (
    CapabilityCallContext,
    InMemoryCapabilityProviderRegistry,
    InMemoryCapabilityRegistry,
)
from .revisions import (
    capability_catalog_revision,
    capability_mapping_revision,
    capability_provider_registry_revision,
)

_MAX_DEFINITION_FILE_BYTES = 1_048_576
_MAX_MAPPING_FILE_BYTES = 262_144
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 10_000
_DEFINITION_FIELDS = frozenset(
    {
        "schema_version",
        "capability_id",
        "definition_digest",
        "name",
        "description",
        "category",
        "provider",
        "provider_kind",
        "input_schema",
        "output_schema",
        "risk_level",
        "privacy_level",
        "allowed_contexts",
        "required_permissions",
        "cost_hint_units",
        "latency_hint",
        "tags",
        "idempotency",
        "side_effects",
        "enabled",
    }
)
_PROVIDER_FIELDS = frozenset({"provider_id", "revision"})
_REVISION_FIELDS = frozenset(
    {
        "component_id",
        "implementation_version",
        "config_revision",
        "artifact_digest",
    }
)
_SCHEMA_FIELDS = frozenset({"schema_id", "schema_version", "digest", "document"})
_LATENCY_FIELDS = frozenset({"expected_ms", "maximum_ms"})
_MAPPING_FIELDS = frozenset(
    {
        "schema_version",
        "capability_id",
        "capability_definition_digest",
        "server_id",
        "tool_name",
        "expected_input_schema_digest",
        "expected_output_schema_digest",
        "semantics",
        "fixed_arguments",
        "argument_mapping_revision",
        "result_mapping_revision",
        "enabled",
        "mapping_digest",
    }
)


class ConfigCapabilityRegistry:
    """Strict two-directory loader over the atomic in-memory Catalog."""

    def __init__(
        self,
        definitions_directory: Path,
        mappings_directory: Path,
        *,
        schema_validator: CapabilitySchemaValidator,
        provider_registry: InMemoryCapabilityProviderRegistry,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        history_limit: int = 32,
        initial_snapshot: CapabilityCatalogSnapshot | None = None,
    ) -> None:
        self._definitions_directory = Path(definitions_directory)
        self._mappings_directory = Path(mappings_directory)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        if initial_snapshot is None:
            initial = load_capability_catalog_snapshot(
                self._definitions_directory,
                self._mappings_directory,
                snapshot_id=self._new_id("capability-catalog"),
                acquired_at=self._now(),
            )
        else:
            if not isinstance(initial_snapshot, CapabilityCatalogSnapshot):
                raise TypeError("initial_snapshot must be a CapabilityCatalogSnapshot")
            content = _load_content(
                self._definitions_directory,
                self._mappings_directory,
            )
            if not _snapshot_matches_content(initial_snapshot, content):
                raise validation_error(
                    "capability_bootstrap_snapshot_configuration_mismatch"
                )
            initial = initial_snapshot
        self._registry = InMemoryCapabilityRegistry(
            initial,
            schema_validator=schema_validator,
            provider_registry=provider_registry,
            clock=self._clock,
            id_factory=self._id_factory,
            history_limit=history_limit,
        )

    @property
    def definitions_directory(self) -> Path:
        return self._definitions_directory

    @property
    def mappings_directory(self) -> Path:
        return self._mappings_directory

    def acquire_snapshot(self) -> CapabilityCatalogSnapshot:
        return self._registry.acquire_snapshot()

    def snapshot_by_id(
        self,
        snapshot_id: str,
        *,
        expected_digest: DigestString | None = None,
    ) -> CapabilityCatalogSnapshot:
        return self._registry.snapshot_by_id(
            snapshot_id,
            expected_digest=expected_digest,
        )

    def get_definition(self, snapshot, capability_id):
        return self._registry.get_definition(snapshot, capability_id)

    def get_schema(self, snapshot, schema_ref):
        return self._registry.get_schema(snapshot, schema_ref)

    def get_mcp_mapping(self, snapshot, capability_id):
        return self._registry.get_mcp_mapping(snapshot, capability_id)

    async def publish(
        self,
        update: CapabilityCatalogUpdate,
        *,
        call: CapabilityCallContext,
    ):
        return await self._registry.publish(update, call=call)

    async def reload(
        self,
        *,
        call: CapabilityCallContext,
    ) -> CapabilityCatalogSnapshot:
        current = self._registry.acquire_snapshot()
        content = _load_content(
            self._definitions_directory,
            self._mappings_directory,
        )
        content = _apply_deleted_mapping_revocations(content, current)
        values = {
            **content,
            "expected_revision": current.catalog_revision,
        }
        update = CapabilityCatalogUpdate(
            update_digest=capability_catalog_update_digest(values),
            **values,
        )
        receipt = await self._registry.publish(update, call=call)
        return self._registry.snapshot_by_id(
            receipt.snapshot_id,
            expected_digest=receipt.catalog_digest,
        )

    def _new_id(self, prefix: str) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - factory failures are sanitized.
            raise error(
                "capability_config_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise validation_error("invalid_capability_config_id")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - clock failures are sanitized.
            raise error(
                "capability_config_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_capability_config_clock")
        return value


def load_capability_catalog_snapshot(
    definitions_directory: Path,
    mappings_directory: Path,
    *,
    snapshot_id: str,
    acquired_at: datetime,
) -> CapabilityCatalogSnapshot:
    """Load a strict, provider-independent bootstrap snapshot from configuration."""

    if (
        not isinstance(acquired_at, datetime)
        or acquired_at.tzinfo is None
        or acquired_at.utcoffset() is None
    ):
        raise validation_error("invalid_capability_bootstrap_acquired_at")
    content = _load_content(Path(definitions_directory), Path(mappings_directory))
    return CapabilityCatalogSnapshot(
        snapshot_id=snapshot_id,
        catalog_digest=capability_catalog_digest(content),
        acquired_at=acquired_at,
        **content,
    )


def _snapshot_matches_content(
    snapshot: CapabilityCatalogSnapshot,
    content: Mapping[str, object],
) -> bool:
    return (
        snapshot.schema_version == content["schema_version"]
        and snapshot.catalog_revision == content["catalog_revision"]
        and snapshot.mapping_revision == content["mapping_revision"]
        and snapshot.provider_registry_revision == content["provider_registry_revision"]
        and snapshot.definitions == content["definitions"]
        and snapshot.schema_documents == content["schema_documents"]
        and snapshot.provider_descriptors == content["provider_descriptors"]
        and snapshot.mcp_mappings == content["mcp_mappings"]
        and snapshot.catalog_digest == capability_catalog_digest(content)
    )


def _load_content(definitions_directory: Path, mappings_directory: Path):
    definition_paths = _configuration_paths(
        definitions_directory,
        maximum=MAX_CAPABILITY_DEFINITIONS,
        required=True,
    )
    mapping_paths = _configuration_paths(
        mappings_directory,
        maximum=MAX_CAPABILITY_DEFINITIONS,
        required=False,
    )
    loaded_definitions = tuple(_load_definition(path) for path in definition_paths)
    definitions = tuple(item[0] for item in loaded_definitions)
    definition_ids = tuple(item.capability_id for item in definitions)
    if len(definition_ids) != len(set(definition_ids)):
        raise validation_error("duplicate_capability_definition_id")
    schemas_by_ref: dict[SchemaRef, CapabilitySchemaDocument] = {}
    provider_entries: dict[
        str, tuple[ProviderRef, CapabilityProviderKind, set[str]]
    ] = {}
    for item, input_document, output_document, provider_kind in loaded_definitions:
        for document in (input_document, output_document):
            existing = schemas_by_ref.get(document.schema_ref)
            if existing is not None and existing != document:
                raise validation_error("capability_schema_reference_conflict")
            schemas_by_ref[document.schema_ref] = document
        provider_id = item.provider.provider_id
        existing_provider = provider_entries.get(provider_id)
        if existing_provider is None:
            provider_entries[provider_id] = (
                item.provider,
                provider_kind,
                {item.capability_id},
            )
        else:
            provider_ref, existing_kind, capability_ids = existing_provider
            if provider_ref != item.provider or existing_kind is not provider_kind:
                raise validation_error("capability_provider_configuration_conflict")
            capability_ids.add(item.capability_id)
    descriptors = tuple(
        _provider_descriptor(provider, kind, capability_ids)
        for provider, kind, capability_ids in sorted(
            provider_entries.values(),
            key=lambda item: item[0].provider_id,
        )
    )
    mappings = tuple(_load_mapping(path) for path in mapping_paths)
    mapping_ids = tuple(item.capability_id for item in mappings)
    if len(mapping_ids) != len(set(mapping_ids)):
        raise validation_error("duplicate_mcp_capability_mapping")
    definitions = tuple(sorted(definitions, key=lambda item: item.capability_id))
    schemas = tuple(
        sorted(
            schemas_by_ref.values(),
            key=lambda item: (
                item.schema_ref.schema_id,
                item.schema_ref.schema_version,
            ),
        )
    )
    mappings = tuple(sorted(mappings, key=lambda item: item.capability_id))
    return _catalog_content(definitions, schemas, descriptors, mappings)


def _apply_deleted_mapping_revocations(
    content: Mapping[str, object],
    current: CapabilityCatalogSnapshot,
) -> dict[str, object]:
    definitions = tuple(content["definitions"])
    schemas = tuple(content["schema_documents"])
    descriptors = tuple(content["provider_descriptors"])
    mappings = tuple(content["mcp_mappings"])
    definitions_by_id = {item.capability_id: item for item in definitions}
    current_definitions = {item.capability_id: item for item in current.definitions}
    loaded_ids = {item.capability_id for item in mappings}
    tombstones: list[McpCapabilityMapping] = []
    for previous in current.mcp_mappings:
        if previous.capability_id in loaded_ids:
            continue
        definition = definitions_by_id.get(previous.capability_id)
        if definition is None:
            continue
        current_definition = current_definitions.get(previous.capability_id)
        if current_definition != definition:
            raise validation_error("deleted_mcp_mapping_definition_revision_mismatch")
        tombstones.append(_disabled_mapping(previous))
    if not tombstones:
        return dict(content)
    merged = tuple(
        sorted((*mappings, *tombstones), key=lambda item: item.capability_id)
    )
    return _catalog_content(definitions, schemas, descriptors, merged)


def _disabled_mapping(mapping: McpCapabilityMapping) -> McpCapabilityMapping:
    values = {
        "schema_version": mapping.schema_version,
        "capability_id": mapping.capability_id,
        "capability_definition_digest": mapping.capability_definition_digest,
        "server_id": mapping.server_id,
        "tool_name": mapping.tool_name,
        "expected_input_schema_digest": mapping.expected_input_schema_digest,
        "expected_output_schema_digest": mapping.expected_output_schema_digest,
        "semantics": mapping.semantics,
        "fixed_arguments": mapping.fixed_arguments,
        "argument_mapping_revision": mapping.argument_mapping_revision,
        "result_mapping_revision": mapping.result_mapping_revision,
        "enabled": False,
    }
    return McpCapabilityMapping(
        mapping_digest=mcp_capability_mapping_digest(values),
        **values,
    )


def _catalog_content(
    definitions: tuple[CapabilityDefinition, ...],
    schemas: tuple[CapabilitySchemaDocument, ...],
    descriptors: tuple[CapabilityProviderDescriptor, ...],
    mappings: tuple[McpCapabilityMapping, ...],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "catalog_revision": capability_catalog_revision(
            definitions,
            schemas,
            descriptors,
            mappings,
        ),
        "mapping_revision": capability_mapping_revision(mappings),
        "provider_registry_revision": capability_provider_registry_revision(
            descriptors
        ),
        "definitions": definitions,
        "schema_documents": schemas,
        "provider_descriptors": descriptors,
        "mcp_mappings": mappings,
    }


def _configuration_paths(
    directory: Path,
    *,
    maximum: int,
    required: bool,
) -> tuple[Path, ...]:
    try:
        entries = tuple(sorted(directory.iterdir(), key=lambda item: item.name))
    except OSError:
        raise error(
            "capability_config_directory_unavailable",
            ErrorCategory.EXTERNAL,
            "service.unavailable",
        ) from None
    visible = tuple(item for item in entries if not item.name.startswith("."))
    if any(
        item.suffix != ".json" or not item.is_file() or item.is_symlink()
        for item in visible
    ):
        raise validation_error("invalid_capability_config_entry")
    if (required and not visible) or len(visible) > maximum:
        raise validation_error("invalid_capability_config_file_count")
    return visible


def _load_definition(path: Path):
    document = _read_document(path, maximum_bytes=_MAX_DEFINITION_FILE_BYTES)
    _exact_fields(document, _DEFINITION_FIELDS, "capability_definition")
    capability_id = _string(document["capability_id"], "capability_id")
    if path.stem != capability_id:
        raise validation_error("capability_definition_filename_mismatch")
    provider = _parse_provider(document["provider"])
    input_document = _parse_schema(document["input_schema"])
    output_document = _parse_schema(document["output_schema"])
    latency = _object(document["latency_hint"], "latency_hint")
    _exact_fields(latency, _LATENCY_FIELDS, "latency_hint")
    try:
        provider_kind = CapabilityProviderKind(document["provider_kind"])
        risk_level = RiskLevel(document["risk_level"])
        privacy_level = PrivacyLevel(document["privacy_level"])
        allowed_contexts = frozenset(
            ConversationType(item)
            for item in _string_array(document["allowed_contexts"], "allowed_contexts")
        )
        idempotency = Idempotency(document["idempotency"])
        side_effects = frozenset(
            SideEffect(item)
            for item in _string_array(document["side_effects"], "side_effects")
        )
    except (TypeError, ValueError):
        raise validation_error("invalid_capability_definition_enum") from None
    values = {
        "schema_version": _integer(document["schema_version"], "schema_version"),
        "capability_id": capability_id,
        "definition_digest": DigestString(
            _string(document["definition_digest"], "definition_digest")
        ),
        "name": _string(document["name"], "name"),
        "description": _string(document["description"], "description"),
        "category": _string(document["category"], "category"),
        "provider": provider,
        "input_schema": input_document.schema_ref,
        "output_schema": output_document.schema_ref,
        "risk_level": risk_level,
        "privacy_level": privacy_level,
        "allowed_contexts": allowed_contexts,
        "required_permissions": frozenset(
            _string_array(document["required_permissions"], "required_permissions")
        ),
        "cost_hint": CostHint(_integer(document["cost_hint_units"], "cost_hint_units")),
        "latency_hint": LatencyHint(
            _integer(latency["expected_ms"], "expected_ms"),
            _integer(latency["maximum_ms"], "maximum_ms"),
        ),
        "tags": frozenset(_string_array(document["tags"], "tags")),
        "idempotency": idempotency,
        "side_effects": side_effects,
        "enabled": _boolean(document["enabled"], "enabled"),
    }
    return (
        CapabilityDefinition(**values),
        input_document,
        output_document,
        provider_kind,
    )


def _parse_provider(value: object) -> ProviderRef:
    document = _object(value, "provider")
    _exact_fields(document, _PROVIDER_FIELDS, "provider")
    revision = _object(document["revision"], "provider_revision")
    _exact_fields(revision, _REVISION_FIELDS, "provider_revision")
    return ProviderRef(
        provider_id=_string(document["provider_id"], "provider_id"),
        revision=ComponentRevision(
            component_id=_string(revision["component_id"], "component_id"),
            implementation_version=_string(
                revision["implementation_version"],
                "implementation_version",
            ),
            config_revision=_string(
                revision["config_revision"],
                "config_revision",
            ),
            artifact_digest=DigestString(
                _string(revision["artifact_digest"], "artifact_digest")
            ),
        ),
    )


def _parse_schema(value: object) -> CapabilitySchemaDocument:
    document = _object(value, "schema")
    _exact_fields(document, _SCHEMA_FIELDS, "schema")
    schema_ref = SchemaRef(
        schema_id=_string(document["schema_id"], "schema_id"),
        schema_version=_integer(document["schema_version"], "schema_version"),
        digest=DigestString(_string(document["digest"], "schema_digest")),
    )
    return CapabilitySchemaDocument(
        schema_version=1,
        schema_ref=schema_ref,
        document=_object(document["document"], "schema_document"),
    )


def _provider_descriptor(
    provider: ProviderRef,
    kind: CapabilityProviderKind,
    capability_ids: set[str],
) -> CapabilityProviderDescriptor:
    values = {
        "schema_version": 1,
        "provider": provider,
        "kind": kind,
        "capability_ids": frozenset(capability_ids),
    }
    return CapabilityProviderDescriptor(
        descriptor_digest=capability_provider_descriptor_digest(values),
        **values,
    )


def _load_mapping(path: Path) -> McpCapabilityMapping:
    document = _read_document(path, maximum_bytes=_MAX_MAPPING_FILE_BYTES)
    _exact_fields(document, _MAPPING_FIELDS, "mcp_capability_mapping")
    capability_id = _string(document["capability_id"], "capability_id")
    if path.stem != capability_id:
        raise validation_error("mcp_capability_mapping_filename_mismatch")
    try:
        semantics = McpOperationSemantics(document["semantics"])
    except (TypeError, ValueError):
        raise validation_error("invalid_mcp_mapping_semantics") from None
    output_digest = document["expected_output_schema_digest"]
    if output_digest is not None:
        output_digest = DigestString(
            _string(output_digest, "expected_output_schema_digest")
        )
    values = {
        "schema_version": _integer(document["schema_version"], "schema_version"),
        "capability_id": capability_id,
        "capability_definition_digest": DigestString(
            _string(
                document["capability_definition_digest"],
                "capability_definition_digest",
            )
        ),
        "server_id": _string(document["server_id"], "server_id"),
        "tool_name": _string(document["tool_name"], "tool_name"),
        "expected_input_schema_digest": DigestString(
            _string(
                document["expected_input_schema_digest"],
                "expected_input_schema_digest",
            )
        ),
        "expected_output_schema_digest": output_digest,
        "semantics": semantics,
        "fixed_arguments": _object(document["fixed_arguments"], "fixed_arguments"),
        "argument_mapping_revision": _string(
            document["argument_mapping_revision"],
            "argument_mapping_revision",
        ),
        "result_mapping_revision": _string(
            document["result_mapping_revision"],
            "result_mapping_revision",
        ),
        "enabled": _boolean(document["enabled"], "enabled"),
    }
    expected_digest = DigestString(
        _string(document["mapping_digest"], "mapping_digest")
    )
    mapping = McpCapabilityMapping(mapping_digest=expected_digest, **values)
    if mapping.mapping_digest != mcp_capability_mapping_digest(values):
        raise validation_error("mcp_capability_mapping_digest_mismatch")
    return mapping


def _read_document(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    try:
        payload = path.read_bytes()
    except OSError:
        raise error(
            "capability_config_file_unavailable",
            ErrorCategory.EXTERNAL,
            "service.unavailable",
        ) from None
    if not payload or len(payload) > maximum_bytes:
        raise validation_error("invalid_capability_config_file_size")
    try:
        raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError):
        raise validation_error("invalid_capability_config_json") from None
    _validate_json_shape(raw)
    return _object(raw, "configuration_document")


def _validate_json_shape(value: object) -> None:
    nodes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise validation_error("capability_config_json_too_complex")
        if isinstance(current, Mapping):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _unique_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise validation_error("duplicate_capability_config_key")
        result[key] = value
    return result


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise validation_error("invalid_capability_config_object", field)
    return value


def _exact_fields(
    document: Mapping[str, object],
    expected: frozenset[str],
    field: str,
) -> None:
    if frozenset(document) != expected:
        raise validation_error("invalid_capability_config_fields", field)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_capability_config_string", field)
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise validation_error("invalid_capability_config_integer", field)
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise validation_error("invalid_capability_config_boolean", field)
    return value


def _string_array(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise validation_error("invalid_capability_config_array", field)
    result = tuple(_string(item, field) for item in value)
    if len(result) != len(set(result)):
        raise validation_error("duplicate_capability_config_array_item", field)
    return result


__all__ = ["ConfigCapabilityRegistry"]
