from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable
from datetime import datetime, timezone

from dududa.domain.capability import CapabilityDefinition, ProviderRef
from dududa.domain.primitives import DigestString, SchemaRef
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.capabilities import CapabilityProvider, CapabilitySchemaValidator
from dududa.ports.context import PortCallContext, ServiceCallContext

from .contracts import (
    CapabilityCatalogPublishReceipt,
    CapabilityCatalogSnapshot,
    CapabilityCatalogUpdate,
    CapabilityProviderDescriptor,
    CapabilitySchemaDocument,
    McpCapabilityMapping,
)
from .digests import (
    capability_catalog_digest,
    capability_catalog_publish_receipt_digest,
)
from .mapping_policy import validate_mcp_mapping_policy

CapabilityCallContext = PortCallContext | ServiceCallContext


class InMemoryCapabilityProviderRegistry:
    """Bind Provider implementations to one exact immutable descriptor revision."""

    def __init__(self, providers: Iterable[CapabilityProvider] = ()) -> None:
        self._providers: dict[tuple[str, ProviderRef], CapabilityProvider] = {}
        self._catalog_bindings: dict[str, DigestString] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: CapabilityProvider) -> None:
        if any(
            not callable(getattr(provider, method, None))
            for method in ("health", "invoke", "close")
        ):
            raise validation_error("invalid_capability_provider")
        descriptor = _provider_descriptor(provider)
        key = (descriptor.provider.provider_id, descriptor.provider)
        existing = self._providers.get(key)
        if existing is provider:
            return
        if existing is not None:
            if _provider_descriptor(existing) != descriptor:
                raise validation_error("capability_provider_revision_binding_conflict")
            raise validation_error("duplicate_capability_provider_revision_binding")
        self._providers[key] = provider

    def resolve(
        self,
        snapshot: CapabilityCatalogSnapshot,
        provider: ProviderRef,
    ) -> CapabilityProvider:
        bound_digest = self._catalog_bindings.get(snapshot.snapshot_id)
        if bound_digest is None:
            raise validation_error("unbound_capability_catalog_snapshot")
        if bound_digest != snapshot.catalog_digest:
            raise validation_error("capability_catalog_snapshot_binding_mismatch")
        descriptor = _descriptor_from_snapshot(snapshot, provider)
        return self.resolve_descriptor(descriptor)

    def _bind_catalog(self, snapshot: CapabilityCatalogSnapshot) -> None:
        if not isinstance(snapshot, CapabilityCatalogSnapshot):
            raise validation_error("invalid_capability_catalog_snapshot")
        existing = self._catalog_bindings.get(snapshot.snapshot_id)
        if existing is not None and existing != snapshot.catalog_digest:
            raise validation_error("capability_catalog_snapshot_id_conflict")
        self._catalog_bindings[snapshot.snapshot_id] = snapshot.catalog_digest

    def _forget_catalog(self, snapshot: CapabilityCatalogSnapshot) -> None:
        if self._catalog_bindings.get(snapshot.snapshot_id) == snapshot.catalog_digest:
            del self._catalog_bindings[snapshot.snapshot_id]

    def resolve_descriptor(
        self,
        descriptor: CapabilityProviderDescriptor,
    ) -> CapabilityProvider:
        provider = self._providers.get(
            (descriptor.provider.provider_id, descriptor.provider)
        )
        if provider is None:
            raise validation_error(
                "capability_provider_revision_not_bound",
                descriptor.provider.provider_id,
            )
        if _provider_descriptor(provider) != descriptor:
            raise validation_error(
                "capability_provider_descriptor_binding_mismatch",
                descriptor.provider.provider_id,
            )
        return provider

    async def close(self) -> None:
        providers: list[CapabilityProvider] = []
        seen: set[int] = set()
        for provider in self._providers.values():
            if id(provider) not in seen:
                providers.append(provider)
                seen.add(id(provider))
        close_failed = False
        for provider in reversed(providers):
            try:
                await provider.close()
            except Exception:  # noqa: BLE001 - every Provider is attempted.
                close_failed = True
        if close_failed:
            raise error(
                "capability_provider_close_failed",
                ErrorCategory.EXTERNAL,
                "service.unavailable",
            ) from None


class InMemoryCapabilityRegistry:
    """Atomic, history-bounded, last-known-good Capability Catalog."""

    def __init__(
        self,
        initial: CapabilityCatalogSnapshot,
        *,
        schema_validator: CapabilitySchemaValidator,
        provider_registry: InMemoryCapabilityProviderRegistry,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        history_limit: int = 32,
    ) -> None:
        if type(history_limit) is not int or history_limit < 2:
            raise ValueError("history_limit must be at least two")
        if not isinstance(initial, CapabilityCatalogSnapshot):
            raise validation_error("invalid_initial_capability_catalog")
        if not isinstance(schema_validator, CapabilitySchemaValidator):
            raise validation_error("invalid_capability_schema_validator")
        if not isinstance(provider_registry, InMemoryCapabilityProviderRegistry):
            raise validation_error("invalid_capability_provider_registry")
        self._schema_validator = schema_validator
        self._provider_registry = provider_registry
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._history_limit = history_limit
        self._retired_bindings: set[tuple[ProviderRef, str]] = {
            (definition.provider, definition.capability_id)
            for definition in initial.definitions
            for mapping in initial.mcp_mappings
            if mapping.capability_id == definition.capability_id and not mapping.enabled
        }
        self._validate_bound_snapshot(initial)
        self._provider_registry._bind_catalog(initial)
        self._current = initial
        self._history: OrderedDict[str, CapabilityCatalogSnapshot] = OrderedDict(
            ((initial.snapshot_id, initial),)
        )
        self._publish_lock = asyncio.Lock()

    def acquire_snapshot(self) -> CapabilityCatalogSnapshot:
        return self._current

    def snapshot_by_id(
        self,
        snapshot_id: str,
        *,
        expected_digest: DigestString | None = None,
    ) -> CapabilityCatalogSnapshot:
        snapshot = self._history.get(snapshot_id)
        if snapshot is None:
            raise validation_error("unknown_capability_catalog_snapshot")
        if expected_digest is not None and snapshot.catalog_digest != expected_digest:
            raise validation_error("capability_catalog_snapshot_digest_mismatch")
        return snapshot

    def get_definition(
        self,
        snapshot: CapabilityCatalogSnapshot,
        capability_id: str,
    ) -> CapabilityDefinition:
        stored = self._stored_snapshot(snapshot)
        for definition in stored.definitions:
            if definition.capability_id == capability_id:
                return definition
        raise validation_error("capability_definition_not_found")

    def get_schema(
        self,
        snapshot: CapabilityCatalogSnapshot,
        schema_ref: SchemaRef,
    ) -> CapabilitySchemaDocument:
        stored = self._stored_snapshot(snapshot)
        for document in stored.schema_documents:
            if document.schema_ref == schema_ref:
                return document
        raise validation_error("capability_schema_not_found")

    def get_mcp_mapping(
        self,
        snapshot: CapabilityCatalogSnapshot,
        capability_id: str,
    ) -> McpCapabilityMapping | None:
        stored = self._stored_snapshot(snapshot)
        for mapping in stored.mcp_mappings:
            if mapping.capability_id == capability_id:
                return mapping
        return None

    async def publish(
        self,
        update: CapabilityCatalogUpdate,
        *,
        call: CapabilityCallContext,
    ) -> CapabilityCatalogPublishReceipt:
        if not isinstance(update, CapabilityCatalogUpdate):
            raise validation_error("invalid_capability_catalog_update")
        now = self._now()
        _validate_call(call, now)
        async with self._publish_lock:
            now = self._now()
            _validate_call(call, now)
            current = self._current
            if update.expected_revision != current.catalog_revision:
                raise error(
                    "capability_catalog_revision_conflict",
                    ErrorCategory.CONFLICT,
                    "request.conflict",
                    "expected_revision_mismatch",
                )
            values = {
                "schema_version": 1,
                "catalog_revision": update.catalog_revision,
                "mapping_revision": update.mapping_revision,
                "provider_registry_revision": update.provider_registry_revision,
                "definitions": update.definitions,
                "schema_documents": update.schema_documents,
                "provider_descriptors": update.provider_descriptors,
                "mcp_mappings": update.mcp_mappings,
            }
            candidate_digest = capability_catalog_digest(values)
            if candidate_digest == current.catalog_digest:
                return self._receipt(current, current, now)
            snapshot_id = self._new_id("capability-catalog")
            if snapshot_id in self._history:
                raise error(
                    "capability_catalog_snapshot_id_conflict",
                    ErrorCategory.CONFLICT,
                    "request.conflict",
                )
            candidate = CapabilityCatalogSnapshot(
                snapshot_id=snapshot_id,
                catalog_digest=candidate_digest,
                acquired_at=now,
                **values,
            )
            _validate_catalog_transition(
                current,
                candidate,
                self._retired_bindings,
            )
            self._validate_bound_snapshot(candidate)
            receipt = self._receipt(current, candidate, now)
            self._provider_registry._bind_catalog(candidate)
            self._current = candidate
            self._remember(candidate)
            self._retired_bindings.update(_newly_retired_bindings(current, candidate))
            return receipt

    def _receipt(
        self,
        previous: CapabilityCatalogSnapshot,
        published: CapabilityCatalogSnapshot,
        published_at: datetime,
    ) -> CapabilityCatalogPublishReceipt:
        values = {
            "schema_version": 1,
            "previous_revision": previous.catalog_revision,
            "catalog_revision": published.catalog_revision,
            "snapshot_id": published.snapshot_id,
            "catalog_digest": published.catalog_digest,
            "published_at": published_at,
        }
        return CapabilityCatalogPublishReceipt(
            receipt_digest=capability_catalog_publish_receipt_digest(values),
            **values,
        )

    def _stored_snapshot(
        self,
        snapshot: CapabilityCatalogSnapshot,
    ) -> CapabilityCatalogSnapshot:
        if not isinstance(snapshot, CapabilityCatalogSnapshot):
            raise validation_error("invalid_capability_catalog_snapshot")
        stored = self.snapshot_by_id(
            snapshot.snapshot_id,
            expected_digest=snapshot.catalog_digest,
        )
        if stored != snapshot:
            raise validation_error("capability_catalog_snapshot_tampered")
        return stored

    def _validate_bound_snapshot(self, snapshot: CapabilityCatalogSnapshot) -> None:
        for document in snapshot.schema_documents:
            self._schema_validator.check_schema(document)
        definitions = {item.capability_id: item for item in snapshot.definitions}
        schemas = {item.schema_ref: item for item in snapshot.schema_documents}
        for mapping in snapshot.mcp_mappings:
            definition = definitions[mapping.capability_id]
            try:
                validate_mcp_mapping_policy(
                    definition,
                    mapping,
                    schemas[definition.input_schema],
                    schemas[definition.output_schema],
                    self._schema_validator,
                )
            except (KeyError, TypeError, ValueError):
                raise validation_error(
                    "unsupported_mcp_capability_mapping_policy"
                ) from None
        for descriptor in snapshot.provider_descriptors:
            self._provider_registry.resolve_descriptor(descriptor)

    def _remember(self, snapshot: CapabilityCatalogSnapshot) -> None:
        self._history[snapshot.snapshot_id] = snapshot
        self._history.move_to_end(snapshot.snapshot_id)
        while len(self._history) > self._history_limit:
            _, forgotten = self._history.popitem(last=False)
            self._provider_registry._forget_catalog(forgotten)

    def _new_id(self, prefix: str) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - factory failures are sanitized.
            raise error(
                "capability_catalog_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise validation_error("invalid_capability_catalog_id")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - clock failures are sanitized.
            raise error(
                "capability_catalog_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_capability_catalog_clock")
        return value


def _descriptor_from_snapshot(
    snapshot: CapabilityCatalogSnapshot,
    provider: ProviderRef,
) -> CapabilityProviderDescriptor:
    if not isinstance(snapshot, CapabilityCatalogSnapshot) or not isinstance(
        provider, ProviderRef
    ):
        raise validation_error("invalid_capability_provider_resolution")
    for descriptor in snapshot.provider_descriptors:
        if descriptor.provider.provider_id != provider.provider_id:
            continue
        if descriptor.provider != provider:
            raise validation_error("capability_provider_revision_mismatch")
        return descriptor
    raise validation_error("capability_provider_not_in_catalog")


def _provider_descriptor(provider: CapabilityProvider) -> CapabilityProviderDescriptor:
    try:
        descriptor = provider.descriptor
    except Exception:  # noqa: BLE001 - Provider details are never exposed.
        raise error(
            "capability_provider_descriptor_unavailable",
            ErrorCategory.EXTERNAL,
            "service.unavailable",
        ) from None
    if not isinstance(descriptor, CapabilityProviderDescriptor):
        raise validation_error("invalid_capability_provider_descriptor")
    return descriptor


def _validate_catalog_transition(
    current: CapabilityCatalogSnapshot,
    candidate: CapabilityCatalogSnapshot,
    retired_bindings: set[tuple[ProviderRef, str]],
) -> None:
    current_definitions = {item.capability_id: item for item in current.definitions}
    current_mappings = {item.capability_id: item for item in current.mcp_mappings}
    candidate_mappings = {item.capability_id: item for item in candidate.mcp_mappings}
    for definition in candidate.definitions:
        next_mapping = candidate_mappings.get(definition.capability_id)
        if (
            (definition.provider, definition.capability_id) in retired_bindings
            and definition.enabled
            and (next_mapping is None or next_mapping.enabled)
        ):
            raise validation_error("retired_capability_requires_provider_revision")
        previous_definition = current_definitions.get(definition.capability_id)
        if (
            previous_definition is None
            or previous_definition.provider != definition.provider
        ):
            continue
        if previous_definition.definition_digest != definition.definition_digest:
            raise validation_error(
                "capability_definition_change_requires_provider_revision"
            )
        previous_mapping = current_mappings.get(definition.capability_id)
        if previous_mapping == next_mapping:
            continue
        if (
            previous_mapping is None
            or next_mapping is None
            or not previous_mapping.enabled
            or next_mapping.enabled
            or not _same_mapping_contract(previous_mapping, next_mapping)
        ):
            raise validation_error("mcp_mapping_change_requires_provider_revision")


def _newly_retired_bindings(
    current: CapabilityCatalogSnapshot,
    candidate: CapabilityCatalogSnapshot,
) -> set[tuple[ProviderRef, str]]:
    candidate_definitions = {item.capability_id: item for item in candidate.definitions}
    candidate_mappings = {item.capability_id: item for item in candidate.mcp_mappings}
    retired: set[tuple[ProviderRef, str]] = set()
    for definition in current.definitions:
        next_definition = candidate_definitions.get(definition.capability_id)
        if next_definition is None or next_definition.provider != definition.provider:
            retired.add((definition.provider, definition.capability_id))
            continue
        previous_mapping = next(
            (
                item
                for item in current.mcp_mappings
                if item.capability_id == definition.capability_id
            ),
            None,
        )
        next_mapping = candidate_mappings.get(definition.capability_id)
        if (
            previous_mapping is not None
            and previous_mapping.enabled
            and next_mapping is not None
            and not next_mapping.enabled
        ):
            retired.add((definition.provider, definition.capability_id))
    return retired


def _same_mapping_contract(
    left: McpCapabilityMapping,
    right: McpCapabilityMapping,
) -> bool:
    return all(
        getattr(left, field) == getattr(right, field)
        for field in left.__dataclass_fields__
        if field not in {"enabled", "mapping_digest"}
    )


def _validate_call(call: CapabilityCallContext, now: datetime) -> None:
    if not isinstance(call, (PortCallContext, ServiceCallContext)):
        raise validation_error("invalid_capability_catalog_call_context")
    if call.cancellation.is_cancelled:
        raise error(
            "capability_catalog_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "capability_catalog_call_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


__all__ = [
    "InMemoryCapabilityProviderRegistry",
    "InMemoryCapabilityRegistry",
]
