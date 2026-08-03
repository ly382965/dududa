from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
import uuid

from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.ports.models import ModelProvider

from .contracts import (
    EndpointLoadSnapshot,
    ModelEndpointDescriptor,
    ModelOperationalSnapshot,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRole,
)
from .digests import model_operational_snapshot_digest, routing_catalog_digest
from .policy import (
    ModelCatalogPublishReceipt,
    ModelCatalogUpdate,
    ModelRoutePolicy,
    ModelRoutingSnapshot,
    validate_routing_snapshot,
)


CallContext = PortCallContext | ServiceCallContext


class InMemoryModelRoutingRegistry:
    """Atomic last-known-good catalog with exact Provider revision lookup."""

    def __init__(
        self,
        providers: Iterable[ModelProvider],
        route_policies: Iterable[ModelRoutePolicy],
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        history_limit: int = 32,
    ) -> None:
        if type(history_limit) is not int or history_limit < 2:
            raise ValueError("history_limit must be at least two")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._history_limit = history_limit
        self._providers: dict[tuple[str, ComponentRevision], ModelProvider] = {}
        provider_descriptors: list[ModelProviderDescriptor] = []
        for provider in providers:
            self.register_provider(provider)
            provider_descriptors.append(provider.descriptor)
        policies = tuple(route_policies)
        descriptors = tuple(provider_descriptors)
        revision = str(routing_catalog_digest(descriptors, policies))
        initial = ModelRoutingSnapshot(
            schema_version=1,
            snapshot_id=self._new_id("catalog"),
            catalog_revision=revision,
            provider_descriptors=descriptors,
            route_policies=policies,
            acquired_at=self._now(),
        )
        self._validate_bound_snapshot(initial)
        self._current = initial
        self._history: OrderedDict[str, ModelRoutingSnapshot] = OrderedDict(
            ((initial.snapshot_id, initial),)
        )
        self._publish_lock = asyncio.Lock()

    def register_provider(self, provider: ModelProvider) -> None:
        if not isinstance(provider, ModelProvider):
            raise validation_error("invalid_model_provider")
        descriptor = provider.descriptor
        if not isinstance(descriptor, ModelProviderDescriptor):
            raise validation_error("invalid_model_provider_descriptor")
        key = (descriptor.provider_id, descriptor.revision)
        existing = self._providers.get(key)
        if existing is not None and existing is not provider:
            if existing.descriptor != descriptor:
                raise validation_error("provider_revision_binding_conflict")
            raise validation_error("duplicate_provider_revision_binding")
        self._providers[key] = provider

    def acquire_snapshot(self) -> ModelRoutingSnapshot:
        return self._current

    def snapshot_by_id(
        self,
        snapshot_id: str,
        *,
        expected_revision: str | None = None,
    ) -> ModelRoutingSnapshot:
        snapshot = self._history.get(snapshot_id)
        if snapshot is None:
            raise validation_error("unknown_routing_snapshot")
        if (
            expected_revision is not None
            and snapshot.catalog_revision != expected_revision
        ):
            raise validation_error("routing_snapshot_revision_mismatch")
        return snapshot

    def resolve_provider(
        self,
        snapshot: ModelRoutingSnapshot,
        provider_id: str,
        expected_revision: ComponentRevision,
    ) -> ModelProvider:
        stored = self.snapshot_by_id(
            snapshot.snapshot_id,
            expected_revision=snapshot.catalog_revision,
        )
        if stored != snapshot:
            raise validation_error("routing_snapshot_tampered")
        descriptor = _provider_descriptor(snapshot, provider_id)
        if descriptor.revision != expected_revision:
            raise validation_error("provider_revision_mismatch")
        provider = self._providers.get((provider_id, expected_revision))
        if provider is None:
            raise validation_error("provider_revision_not_bound")
        if provider.descriptor != descriptor:
            raise validation_error("provider_descriptor_binding_mismatch")
        return provider

    def list_enabled(
        self,
        snapshot: ModelRoutingSnapshot,
    ) -> tuple[ModelProviderDescriptor, ...]:
        self.snapshot_by_id(
            snapshot.snapshot_id,
            expected_revision=snapshot.catalog_revision,
        )
        return tuple(
            provider
            for provider in snapshot.provider_descriptors
            if any(endpoint.enabled for endpoint in provider.endpoints)
        )

    def policy_for(
        self,
        snapshot: ModelRoutingSnapshot,
        role: ModelRole,
    ) -> ModelRoutePolicy:
        self.snapshot_by_id(
            snapshot.snapshot_id,
            expected_revision=snapshot.catalog_revision,
        )
        for policy in snapshot.route_policies:
            if policy.role is role:
                return policy
        raise validation_error("model_route_policy_not_found", role.value)

    def resolve_endpoint_revision(
        self,
        provider_id: str,
        endpoint_id: str,
        expected_digest: DigestString,
    ) -> ModelEndpointDescriptor:
        for snapshot in reversed(tuple(self._history.values())):
            for provider in snapshot.provider_descriptors:
                if provider.provider_id != provider_id:
                    continue
                for endpoint in provider.endpoints:
                    if endpoint.endpoint_id == endpoint_id:
                        if endpoint.descriptor_digest != expected_digest:
                            continue
                        return endpoint
        raise validation_error(
            "endpoint_revision_not_found",
            provider_id,
            endpoint_id,
        )

    async def publish(
        self,
        update: ModelCatalogUpdate,
        *,
        call: CallContext,
    ) -> ModelCatalogPublishReceipt:
        now = self._now()
        _validate_call(call, now)
        async with self._publish_lock:
            current = self._current
            if update.expected_revision != current.catalog_revision:
                raise error(
                    "model_catalog_revision_conflict",
                    ErrorCategory.CONFLICT,
                    "request.conflict",
                    "expected_revision_mismatch",
                )
            revision = str(
                routing_catalog_digest(
                    update.provider_descriptors,
                    update.route_policies,
                )
            )
            candidate = ModelRoutingSnapshot(
                schema_version=1,
                snapshot_id=self._new_id("catalog"),
                catalog_revision=revision,
                provider_descriptors=update.provider_descriptors,
                route_policies=update.route_policies,
                acquired_at=now,
            )
            self._validate_bound_snapshot(candidate)
            self._current = candidate
            self._remember(candidate.snapshot_id, candidate)
            return ModelCatalogPublishReceipt(
                schema_version=1,
                previous_revision=current.catalog_revision,
                catalog_revision=candidate.catalog_revision,
                snapshot_id=candidate.snapshot_id,
                published_at=now,
            )

    def _validate_bound_snapshot(self, snapshot: ModelRoutingSnapshot) -> None:
        validate_routing_snapshot(snapshot)
        for descriptor in snapshot.provider_descriptors:
            provider = self._providers.get(
                (descriptor.provider_id, descriptor.revision)
            )
            if provider is None:
                raise validation_error(
                    "provider_revision_not_bound",
                    descriptor.provider_id,
                )
            if provider.descriptor != descriptor:
                raise validation_error(
                    "provider_descriptor_binding_mismatch",
                    descriptor.provider_id,
                )

    def _remember(self, key: str, snapshot: ModelRoutingSnapshot) -> None:
        self._history[key] = snapshot
        self._history.move_to_end(key)
        while len(self._history) > self._history_limit:
            self._history.popitem(last=False)

    def _new_id(self, prefix: str) -> str:
        value = self._id_factory()
        if not isinstance(value, str) or not value.strip():
            raise ValueError("id_factory returned an empty identifier")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock returned a naive datetime")
        return value


class InMemoryModelOperationalStateRegistry:
    """Atomic operational snapshots bound to exact catalog endpoint revisions."""

    def __init__(
        self,
        routing_registry: InMemoryModelRoutingRegistry,
        initial_snapshot: ModelOperationalSnapshot,
        *,
        clock: Callable[[], datetime] | None = None,
        history_limit: int = 64,
    ) -> None:
        if type(history_limit) is not int or history_limit < 2:
            raise ValueError("history_limit must be at least two")
        self._routing_registry = routing_registry
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._history_limit = history_limit
        self._validate_snapshot(initial_snapshot)
        self._current = initial_snapshot
        self._history: OrderedDict[str, ModelOperationalSnapshot] = OrderedDict(
            ((initial_snapshot.snapshot_id, initial_snapshot),)
        )
        self._publish_lock = asyncio.Lock()

    def acquire_snapshot(self) -> ModelOperationalSnapshot:
        return self._current

    def snapshot_by_id(
        self,
        snapshot_id: str,
        *,
        expected_digest: DigestString | None = None,
    ) -> ModelOperationalSnapshot:
        snapshot = self._history.get(snapshot_id)
        if snapshot is None:
            raise validation_error("unknown_operational_snapshot")
        if (
            expected_digest is not None
            and model_operational_snapshot_digest(snapshot) != expected_digest
        ):
            raise validation_error("operational_snapshot_digest_mismatch")
        return snapshot

    async def publish(
        self,
        snapshot: ModelOperationalSnapshot,
        *,
        call: CallContext,
    ) -> ModelOperationalSnapshot:
        now = self._now()
        _validate_call(call, now)
        async with self._publish_lock:
            self._validate_snapshot(snapshot)
            existing = self._history.get(snapshot.snapshot_id)
            if existing is not None and existing != snapshot:
                raise error(
                    "operational_snapshot_id_conflict",
                    ErrorCategory.CONFLICT,
                    "request.conflict",
                    "snapshot_id_reused",
                )
            self._current = snapshot
            self._history[snapshot.snapshot_id] = snapshot
            self._history.move_to_end(snapshot.snapshot_id)
            while len(self._history) > self._history_limit:
                self._history.popitem(last=False)
            return snapshot

    def _validate_snapshot(self, snapshot: ModelOperationalSnapshot) -> None:
        catalog = self._routing_registry.acquire_snapshot()
        providers = {
            provider.provider_id: provider for provider in catalog.provider_descriptors
        }
        endpoints = {
            (provider.provider_id, endpoint.endpoint_id): endpoint
            for provider in catalog.provider_descriptors
            for endpoint in provider.endpoints
        }
        for health in snapshot.provider_health:
            descriptor = providers.get(health.provider_id)
            if descriptor is None:
                raise validation_error("unknown_health_provider", health.provider_id)
            self._validate_health(health, descriptor)
        pool_counters: dict[str, tuple[int, int, int, int]] = {}
        for load in snapshot.endpoint_load:
            endpoint = endpoints.get((load.provider_id, load.endpoint_id))
            if endpoint is None:
                raise validation_error(
                    "unknown_load_endpoint",
                    load.provider_id,
                    load.endpoint_id,
                )
            self._validate_load(load, endpoint)
            counters = (
                load.in_flight,
                load.requests_per_minute,
                load.tokens_per_minute,
                load.queue_depth,
            )
            existing = pool_counters.get(load.quota_pool_id)
            if existing is not None and existing != counters:
                raise validation_error("quota_pool_load_counter_mismatch")
            pool_counters[load.quota_pool_id] = counters

    @staticmethod
    def _validate_health(
        health: ModelProviderHealth,
        provider: ModelProviderDescriptor,
    ) -> None:
        endpoints = {item.endpoint_id: item for item in provider.endpoints}
        for observation in health.endpoints:
            endpoint = endpoints.get(observation.endpoint_id)
            if endpoint is None:
                raise validation_error(
                    "unknown_health_endpoint",
                    provider.provider_id,
                    observation.endpoint_id,
                )
            if observation.endpoint_descriptor_digest != endpoint.descriptor_digest:
                raise validation_error("health_endpoint_descriptor_mismatch")

    @staticmethod
    def _validate_load(
        load: EndpointLoadSnapshot,
        endpoint: ModelEndpointDescriptor,
    ) -> None:
        policy = endpoint.traffic_policy
        if (
            load.endpoint_descriptor_digest != endpoint.descriptor_digest
            or load.quota_pool_id != endpoint.quota_pool_id
            or load.traffic_policy_id != policy.policy_id
            or load.traffic_policy_revision != policy.policy_revision
        ):
            raise validation_error("load_endpoint_policy_mismatch")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock returned a naive datetime")
        return value


def _provider_descriptor(
    snapshot: ModelRoutingSnapshot,
    provider_id: str,
) -> ModelProviderDescriptor:
    for descriptor in snapshot.provider_descriptors:
        if descriptor.provider_id == provider_id:
            return descriptor
    raise validation_error("model_provider_not_found", provider_id)


def _validate_call(call: CallContext, now: datetime) -> None:
    if call.cancellation.is_cancelled:
        raise error(
            "model_operation_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
            "cancelled_before_operation",
        )
    if now >= call.deadline:
        raise error(
            "model_operation_deadline_exceeded",
            ErrorCategory.TIMEOUT,
            "request.timeout",
            "deadline_exceeded",
        )
