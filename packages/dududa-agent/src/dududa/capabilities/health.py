from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext

from .contracts import (
    CapabilityCatalogSnapshot,
    CapabilityHealthSnapshot,
    CapabilityHealthStatus,
    CapabilityProviderDescriptor,
    CapabilityProviderHealth,
)
from .digests import (
    capability_health_snapshot_digest,
    capability_provider_health_digest,
)
from .registry import InMemoryCapabilityProviderRegistry

CapabilityCallContext = PortCallContext | ServiceCallContext


class PollingCapabilityHealthRegistry:
    """Observe exact Provider revisions and turn probe failures into unavailable facts."""

    def __init__(
        self,
        providers: InMemoryCapabilityProviderRegistry,
        *,
        failure_ttl: timedelta = timedelta(seconds=10),
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(providers, InMemoryCapabilityProviderRegistry):
            raise validation_error("invalid_capability_provider_registry")
        if failure_ttl <= timedelta(0):
            raise ValueError("failure_ttl must be positive")
        self._providers = providers
        self._failure_ttl = failure_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def snapshot(
        self,
        catalog: CapabilityCatalogSnapshot,
        *,
        call: CapabilityCallContext,
    ) -> CapabilityHealthSnapshot:
        now = self._now()
        _validate_call(call, now)
        if not isinstance(catalog, CapabilityCatalogSnapshot):
            raise validation_error("invalid_capability_health_catalog")
        descriptors = catalog.provider_descriptors
        provider_ids = tuple(item.provider.provider_id for item in descriptors)
        if provider_ids != tuple(sorted(provider_ids)) or len(provider_ids) != len(
            set(provider_ids)
        ):
            raise validation_error("invalid_capability_health_provider_order")
        observed: list[CapabilityProviderHealth] = []
        for descriptor in descriptors:
            _validate_call(call, self._now())
            try:
                provider = self._providers.resolve(catalog, descriptor.provider)
                health = await _bounded_probe(
                    provider.health(call=call),
                    call=call,
                    now=self._now(),
                )
                _validate_provider_health(
                    catalog,
                    descriptor,
                    health,
                    now=self._now(),
                )
            except Exception:  # noqa: BLE001 - a failed probe is an unavailable fact.
                _validate_call(call, self._now())
                health = self._unavailable(descriptor, observed_at=self._now())
            observed.append(health)
        completed_at = self._now()
        _validate_call(call, completed_at)
        observed = [
            health
            if health.expires_at > completed_at
            else self._unavailable(descriptor, observed_at=completed_at)
            for descriptor, health in zip(descriptors, observed, strict=True)
        ]
        expires_at = min(
            (item.expires_at for item in observed),
            default=completed_at + self._failure_ttl,
        )
        if expires_at <= completed_at:
            expires_at = completed_at + self._failure_ttl
        values = {
            "schema_version": 1,
            "providers": tuple(observed),
            "observed_at": now,
            "expires_at": expires_at,
        }
        return CapabilityHealthSnapshot(
            snapshot_id=self._new_id("capability-health"),
            snapshot_digest=capability_health_snapshot_digest(values),
            **values,
        )

    def _unavailable(
        self,
        descriptor: CapabilityProviderDescriptor,
        *,
        observed_at: datetime,
    ) -> CapabilityProviderHealth:
        values = {
            "schema_version": 1,
            "provider": descriptor.provider,
            "status": CapabilityHealthStatus.UNAVAILABLE,
            "capabilities": (),
            "observed_at": observed_at,
            "expires_at": observed_at + self._failure_ttl,
        }
        return CapabilityProviderHealth(
            health_digest=capability_provider_health_digest(values),
            **values,
        )

    def _new_id(self, prefix: str) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - factory failures are sanitized.
            raise error(
                "capability_health_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise validation_error("invalid_capability_health_id")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - clock failures are sanitized.
            raise error(
                "capability_health_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_capability_health_clock")
        return value


def _validate_provider_health(
    catalog: CapabilityCatalogSnapshot,
    descriptor: CapabilityProviderDescriptor,
    health: CapabilityProviderHealth,
    *,
    now: datetime,
) -> None:
    if not isinstance(health, CapabilityProviderHealth):
        raise validation_error("invalid_capability_provider_health")
    if health.provider != descriptor.provider:
        raise validation_error("capability_health_provider_revision_mismatch")
    definitions = {
        item.capability_id: item.definition_digest
        for item in catalog.definitions
        if item.provider == descriptor.provider
    }
    observed = {
        item.capability_id: item.definition_digest for item in health.capabilities
    }
    if observed != definitions:
        raise validation_error("capability_health_surface_mismatch")
    statuses = frozenset(item.status for item in health.capabilities)
    if health.status is CapabilityHealthStatus.HEALTHY and statuses != {
        CapabilityHealthStatus.HEALTHY
    }:
        raise validation_error("capability_health_status_inconsistent")
    if health.status is CapabilityHealthStatus.DEGRADED and (
        not statuses or statuses == {CapabilityHealthStatus.HEALTHY}
    ):
        raise validation_error("capability_health_status_inconsistent")
    if health.status is CapabilityHealthStatus.UNAVAILABLE and statuses - {
        CapabilityHealthStatus.UNAVAILABLE
    }:
        raise validation_error("capability_health_status_inconsistent")
    if health.observed_at > now:
        raise validation_error("future_capability_provider_health")
    if health.expires_at <= now:
        raise validation_error("stale_capability_provider_health")


async def _bounded_probe(
    awaitable,
    *,
    call: CapabilityCallContext,
    now: datetime,
):
    remaining = (call.deadline - now).total_seconds()
    if remaining <= 0:
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise error(
            "capability_health_probe_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )
    probe = asyncio.create_task(awaitable)
    cancelled = asyncio.create_task(call.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (probe, cancelled),
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled in done:
            probe.cancel()
            await asyncio.gather(probe, return_exceptions=True)
            raise error(
                "capability_health_probe_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if probe not in done:
            probe.cancel()
            await asyncio.gather(probe, return_exceptions=True)
            raise error(
                "capability_health_probe_timeout",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )
        return probe.result()
    finally:
        for task in (probe, cancelled):
            if not task.done():
                task.cancel()
        await asyncio.gather(probe, cancelled, return_exceptions=True)


def _validate_call(call: CapabilityCallContext, now: datetime) -> None:
    if not isinstance(call, (PortCallContext, ServiceCallContext)):
        raise validation_error("invalid_capability_health_call_context")
    if call.cancellation.is_cancelled:
        raise error(
            "capability_health_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "capability_health_call_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


__all__ = ["PollingCapabilityHealthRegistry"]
