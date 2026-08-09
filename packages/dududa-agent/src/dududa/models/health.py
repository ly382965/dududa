from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import uuid

from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    require_aware,
    require_non_empty,
)
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.ports.models import (
    ModelOperationalStateRegistry,
    ModelOperationalSnapshotPublisher,
    ModelOperationalSnapshotResolver,
    ModelRoutingRegistry,
)

from .contracts import (
    EndpointHealthStatus,
    EndpointLoadSnapshot,
    ModelEndpointHealth,
    ModelOperationalSnapshot,
    ModelProviderDescriptor,
    ModelProviderHealth,
)
from .digests import model_operational_snapshot_digest


CallContext = PortCallContext | ServiceCallContext


@dataclass(frozen=True, slots=True)
class _PublishedHealthBinding:
    snapshot_id: str
    snapshot_digest: str
    catalog_revision: str
    provider_evidence: tuple[tuple[str, datetime, str], ...]


@dataclass(frozen=True, slots=True)
class ModelHealthEvidence:
    schema_version: int
    provider_revision: ComponentRevision
    health: ModelProviderHealth
    expires_at: datetime
    evidence_revision: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.provider_revision, ComponentRevision):
            raise validation_error("invalid_health_provider_revision")
        if not isinstance(self.health, ModelProviderHealth):
            raise validation_error("invalid_health_evidence")
        require_aware(self.expires_at, "health_evidence_expires_at")
        require_non_empty(self.evidence_revision, "health_evidence_revision")
        if self.expires_at <= self.health.checked_at:
            raise validation_error("invalid_health_evidence_window")


class BoundedModelHealthPublisher:
    """Publishes descriptor-bound health while synthesizing fail-closed gaps."""

    def __init__(
        self,
        routing_registry: ModelRoutingRegistry,
        operational_publisher: ModelOperationalSnapshotPublisher,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(routing_registry, ModelRoutingRegistry):
            raise validation_error("invalid_model_routing_registry")
        if not isinstance(operational_publisher, ModelOperationalSnapshotPublisher):
            raise validation_error("invalid_operational_snapshot_publisher")
        if not isinstance(operational_publisher, ModelOperationalStateRegistry):
            raise validation_error("invalid_operational_state_registry")
        if not isinstance(operational_publisher, ModelOperationalSnapshotResolver):
            raise validation_error("invalid_operational_snapshot_resolver")
        self._routing_registry = routing_registry
        self._operational_publisher = operational_publisher
        self._operational_registry = operational_publisher
        self._operational_resolver = operational_publisher
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._publish_lock = asyncio.Lock()
        self._published: _PublishedHealthBinding | None = None
        self._projection_lock = threading.RLock()
        self._projected_history: OrderedDict[str, ModelOperationalSnapshot] = (
            OrderedDict()
        )

    async def publish(
        self,
        evidence: Iterable[ModelHealthEvidence],
        endpoint_load: Iterable[EndpointLoadSnapshot],
        *,
        call: CallContext,
    ) -> ModelOperationalSnapshot:
        async with self._publish_lock:
            now = self._now()
            _validate_call(call, now)
            evidence_items = tuple(evidence)
            if not all(isinstance(item, ModelHealthEvidence) for item in evidence_items):
                raise validation_error("invalid_health_evidence")
            by_provider = {item.health.provider_id: item for item in evidence_items}
            if len(by_provider) != len(evidence_items):
                raise validation_error("duplicate_health_evidence_provider")

            catalog = self._routing_registry.acquire_snapshot()
            provider_health = tuple(
                self._project_provider_health(
                    descriptor,
                    by_provider.get(descriptor.provider_id),
                    now,
                )
                for descriptor in catalog.provider_descriptors
            )
            loads = tuple(endpoint_load)
            if not all(isinstance(item, EndpointLoadSnapshot) for item in loads):
                raise validation_error("invalid_endpoint_load")
            snapshot_id = self._id_factory()
            require_non_empty(snapshot_id, "operational_snapshot_id")
            snapshot = ModelOperationalSnapshot(
                schema_version=1,
                snapshot_id=f"health:{snapshot_id}",
                provider_health=provider_health,
                endpoint_load=loads,
                acquired_at=now,
            )
            published = await self._operational_publisher.publish(snapshot, call=call)
            self._published = _PublishedHealthBinding(
                snapshot_id=published.snapshot_id,
                snapshot_digest=str(model_operational_snapshot_digest(published)),
                catalog_revision=catalog.catalog_revision,
                provider_evidence=tuple(
                    (
                        descriptor.provider_id,
                        item.expires_at,
                        item.evidence_revision,
                    )
                    for descriptor in catalog.provider_descriptors
                    if (item := by_provider.get(descriptor.provider_id)) is not None
                    and item.health.status
                    not in {
                        EndpointHealthStatus.UNAVAILABLE,
                        EndpointHealthStatus.UNKNOWN,
                    }
                    and now < item.expires_at
                ),
            )
            return published

    def acquire_snapshot(self) -> ModelOperationalSnapshot:
        snapshot = self._operational_registry.acquire_snapshot()
        catalog = self._routing_registry.acquire_snapshot()
        now = self._now()
        published = self._published
        if published is None or published.snapshot_id != snapshot.snapshot_id:
            return self._remember_projection(
                _unknown_snapshot(
                    snapshot,
                    catalog.provider_descriptors,
                    snapshot.acquired_at,
                    "health_snapshot_unowned",
                )
            )
        if published.snapshot_digest != str(model_operational_snapshot_digest(snapshot)):
            return self._remember_projection(
                _unknown_snapshot(
                    snapshot,
                    catalog.provider_descriptors,
                    snapshot.acquired_at,
                    "health_snapshot_changed",
                )
            )
        if published.catalog_revision != catalog.catalog_revision:
            return self._remember_projection(
                _unknown_snapshot(
                    snapshot,
                    catalog.provider_descriptors,
                    max(snapshot.acquired_at, catalog.acquired_at),
                    "health_catalog_changed",
                )
            )
        if now < snapshot.acquired_at:
            return self._remember_projection(
                _unknown_snapshot(
                    snapshot,
                    catalog.provider_descriptors,
                    snapshot.acquired_at,
                    "health_clock_rollback",
                )
            )

        evidence = {
            provider_id: (expires_at, revision)
            for provider_id, expires_at, revision in published.provider_evidence
        }
        if len(catalog.provider_descriptors) != len(snapshot.provider_health):
            return self._remember_projection(
                _unknown_snapshot(
                    snapshot,
                    catalog.provider_descriptors,
                    max(snapshot.acquired_at, catalog.acquired_at),
                    "health_provider_set_changed",
                )
            )
        projected: list[ModelProviderHealth] = []
        changed = False
        transition_at = snapshot.acquired_at
        for descriptor, health in zip(
            catalog.provider_descriptors,
            snapshot.provider_health,
            strict=True,
        ):
            if health.provider_id != descriptor.provider_id:
                return self._remember_projection(
                    _unknown_snapshot(
                        snapshot,
                        catalog.provider_descriptors,
                        max(snapshot.acquired_at, catalog.acquired_at),
                        "health_provider_order_changed",
                    )
                )
            binding = evidence.get(descriptor.provider_id)
            if health.status not in {
                EndpointHealthStatus.UNAVAILABLE,
                EndpointHealthStatus.UNKNOWN,
            } and (binding is None or now >= binding[0]):
                reason = (
                    "health_evidence_missing"
                    if binding is None
                    else "health_evidence_stale"
                )
                revision = "none" if binding is None else binding[1]
                if binding is not None:
                    transition_at = max(transition_at, binding[0])
                projected.append(
                    _unknown_health(descriptor, transition_at, reason, revision)
                )
                changed = True
            else:
                projected.append(health)
        if not changed:
            return snapshot
        return self._remember_projection(
            _projected_snapshot(
                snapshot,
                tuple(projected),
                transition_at,
                "health_expired",
            )
        )

    def snapshot_by_id(
        self,
        snapshot_id: str,
        *,
        expected_digest: DigestString | None = None,
    ) -> ModelOperationalSnapshot:
        with self._projection_lock:
            snapshot = self._projected_history.get(snapshot_id)
        if snapshot is None:
            return self._operational_resolver.snapshot_by_id(
                snapshot_id,
                expected_digest=expected_digest,
            )
        if (
            expected_digest is not None
            and model_operational_snapshot_digest(snapshot) != expected_digest
        ):
            raise validation_error("operational_snapshot_digest_mismatch")
        return snapshot

    def _remember_projection(
        self,
        snapshot: ModelOperationalSnapshot,
    ) -> ModelOperationalSnapshot:
        with self._projection_lock:
            existing = self._projected_history.get(snapshot.snapshot_id)
            if existing is not None and existing != snapshot:
                raise validation_error("operational_snapshot_id_conflict")
            self._projected_history[snapshot.snapshot_id] = snapshot
            self._projected_history.move_to_end(snapshot.snapshot_id)
            while len(self._projected_history) > 128:
                self._projected_history.popitem(last=False)
        return snapshot

    def _project_provider_health(
        self,
        descriptor: ModelProviderDescriptor,
        evidence: ModelHealthEvidence | None,
        now: datetime,
    ) -> ModelProviderHealth:
        if evidence is None:
            return _unknown_health(descriptor, now, "health_evidence_missing", "none")
        _validate_evidence_binding(evidence, descriptor, now)
        if now >= evidence.expires_at:
            return _unknown_health(
                descriptor,
                now,
                "health_evidence_stale",
                evidence.evidence_revision,
            )
        if evidence.health.status in {
            EndpointHealthStatus.UNAVAILABLE,
            EndpointHealthStatus.UNKNOWN,
        }:
            return _unknown_health(
                descriptor,
                now,
                "health_probe_failed",
                evidence.evidence_revision,
            )
        return evidence.health

    def _now(self) -> datetime:
        now = self._clock()
        require_aware(now, "health_publisher_now")
        return now.astimezone(timezone.utc)


def _validate_evidence_binding(
    evidence: ModelHealthEvidence,
    descriptor: ModelProviderDescriptor,
    now: datetime,
) -> None:
    health = evidence.health
    if evidence.provider_revision != descriptor.revision:
        raise validation_error("health_provider_revision_mismatch")
    if health.provider_id != descriptor.provider_id:
        raise validation_error("health_provider_id_mismatch")
    if health.checked_at > now:
        raise validation_error("health_evidence_from_future")
    expected = {endpoint.endpoint_id: endpoint for endpoint in descriptor.endpoints}
    actual = {endpoint.endpoint_id: endpoint for endpoint in health.endpoints}
    if set(actual) != set(expected):
        raise validation_error("health_endpoint_set_mismatch")
    for endpoint_id, observation in actual.items():
        if (
            observation.endpoint_descriptor_digest
            != expected[endpoint_id].descriptor_digest
        ):
            raise validation_error("health_endpoint_descriptor_mismatch")


def _unknown_health(
    descriptor: ModelProviderDescriptor,
    checked_at: datetime,
    reason_code: str,
    evidence_revision: str,
) -> ModelProviderHealth:
    return ModelProviderHealth(
        schema_version=1,
        provider_id=descriptor.provider_id,
        status=EndpointHealthStatus.UNKNOWN,
        endpoints=tuple(
            ModelEndpointHealth(
                schema_version=1,
                endpoint_id=endpoint.endpoint_id,
                endpoint_descriptor_digest=endpoint.descriptor_digest,
                status=EndpointHealthStatus.UNKNOWN,
                reason_codes=(reason_code,),
            )
            for endpoint in descriptor.endpoints
        ),
        snapshot_revision=(
            f"bounded-health:{descriptor.revision.config_revision}:"
            f"{evidence_revision}:{reason_code}"
        ),
        checked_at=checked_at,
        reason_codes=(reason_code,),
    )


def _unknown_snapshot(
    snapshot: ModelOperationalSnapshot,
    descriptors: tuple[ModelProviderDescriptor, ...],
    now: datetime,
    reason_code: str,
) -> ModelOperationalSnapshot:
    projected_at = max(now, snapshot.acquired_at)
    health = tuple(
        _unknown_health(descriptor, projected_at, reason_code, "projection")
        for descriptor in descriptors
    )
    return _projected_snapshot(snapshot, health, projected_at, reason_code)


def _projected_snapshot(
    snapshot: ModelOperationalSnapshot,
    health: tuple[ModelProviderHealth, ...],
    projected_at: datetime,
    reason_code: str,
) -> ModelOperationalSnapshot:
    projection_time = int(projected_at.timestamp() * 1_000_000)
    return ModelOperationalSnapshot(
        schema_version=1,
        snapshot_id=(
            f"bounded:{snapshot.snapshot_id}:{reason_code}:{projection_time}"
        ),
        provider_health=health,
        endpoint_load=snapshot.endpoint_load,
        acquired_at=projected_at,
    )


def _validate_call(call: CallContext, now: datetime) -> None:
    if not isinstance(call, (PortCallContext, ServiceCallContext)):
        raise validation_error("invalid_health_publish_context")
    if call.cancellation.is_cancelled:
        raise error(
            "health_publish_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "health_publish_deadline_exceeded",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )
