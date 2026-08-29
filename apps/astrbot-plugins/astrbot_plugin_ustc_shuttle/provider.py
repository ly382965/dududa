from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.capabilities import (
    CapabilityCatalogSnapshot,
    CapabilityEndpointHealth,
    CapabilityHealthStatus,
    CapabilityProviderDescriptor,
    CapabilityProviderHealth,
    CapabilityProviderKind,
    CapabilityResult,
    ProviderInvocation,
    ToolExecutionStatus,
    capability_provider_health_digest,
    capability_result_digest,
    provider_invocation_digest,
)
from dududa.domain.capability import CapabilityDefinition
from dududa.domain.primitives import ResourceUsage
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.capabilities import CapabilitySchemaValidator
from dududa.ports.context import PortCallContext, ServiceCallContext

from .service import ShuttleSchedule


class UstcShuttleCapabilityProvider:
    """Local read-only Provider backed by the plugin's versioned JSON asset."""

    def __init__(
        self,
        descriptor: CapabilityProviderDescriptor,
        definition: CapabilityDefinition,
        output_schema,
        schema_validator: CapabilitySchemaValidator,
        *,
        schedule: ShuttleSchedule | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if descriptor.kind is not CapabilityProviderKind.BUILTIN:
            raise ValueError("shuttle Provider requires a builtin descriptor")
        if descriptor.capability_ids != frozenset({definition.capability_id}):
            raise ValueError("shuttle Provider definition does not match descriptor")
        if definition.provider != descriptor.provider:
            raise ValueError("shuttle Provider reference mismatch")
        schema_validator.check_schema(output_schema)
        self._descriptor = descriptor
        self._definition = definition
        self._output_schema = output_schema
        self._schema_validator = schema_validator
        self._schedule = schedule or ShuttleSchedule()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._closed = False

    @classmethod
    def from_catalog(
        cls,
        snapshot: CapabilityCatalogSnapshot,
        descriptor: CapabilityProviderDescriptor,
        schema_validator: CapabilitySchemaValidator,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> UstcShuttleCapabilityProvider:
        if descriptor.provider.provider_id != "plugin.ustc-shuttle":
            raise validation_error("invalid_shuttle_provider_id")
        definitions = tuple(
            item for item in snapshot.definitions if item.provider == descriptor.provider
        )
        if len(definitions) != 1:
            raise validation_error("invalid_shuttle_provider_definition_count")
        definition = definitions[0]
        output_schema = next(
            (
                item
                for item in snapshot.schema_documents
                if item.schema_ref == definition.output_schema
            ),
            None,
        )
        if output_schema is None:
            raise validation_error("shuttle_output_schema_missing")
        return cls(
            descriptor,
            definition,
            output_schema,
            schema_validator,
            clock=clock,
        )

    @property
    def descriptor(self) -> CapabilityProviderDescriptor:
        return self._descriptor

    async def health(
        self, *, call: PortCallContext | ServiceCallContext
    ) -> CapabilityProviderHealth:
        now = self._active_call(call)
        values = {
            "schema_version": 1,
            "provider": self._descriptor.provider,
            "status": CapabilityHealthStatus.HEALTHY,
            "capabilities": (
                CapabilityEndpointHealth(
                    schema_version=1,
                    capability_id=self._definition.capability_id,
                    definition_digest=self._definition.definition_digest,
                    status=CapabilityHealthStatus.HEALTHY,
                    reason_codes=("local_timetable_loaded",),
                ),
            ),
            "observed_at": now,
            "expires_at": now + timedelta(minutes=5),
        }
        return CapabilityProviderHealth(
            health_digest=capability_provider_health_digest(values),
            **values,
        )

    async def invoke(
        self, request: ProviderInvocation, *, call: PortCallContext
    ) -> CapabilityResult:
        now = self._active_call(call)
        if (
            not isinstance(request, ProviderInvocation)
            or provider_invocation_digest(request) != request.invocation_digest
            or request.provider != self._descriptor.provider
            or request.capability_id != self._definition.capability_id
            or request.definition_digest != self._definition.definition_digest
            or request.mapping_digest is not None
        ):
            raise validation_error("invalid_shuttle_provider_invocation")
        arguments = request.arguments
        query = arguments.get("goal") or arguments.get("query")
        at = arguments.get("at")
        if not isinstance(query, str) or (at is not None and not isinstance(at, str)):
            raise validation_error("invalid_shuttle_provider_arguments")
        try:
            data = self._schedule.query(query, at=at or now)
            data = self._schema_validator.validate(data, self._output_schema)
        except ValueError:
            raise validation_error("invalid_shuttle_provider_arguments") from None
        values = {
            "schema_version": 1,
            "provider_invocation_digest": request.invocation_digest,
            "invocation_id": request.invocation_id,
            "capability_id": request.capability_id,
            "definition_digest": request.definition_digest,
            "provider": request.provider,
            "status": ToolExecutionStatus.SUCCEEDED,
            "data": data,
            "error": None,
            "source_refs": (
                f"plugin://ustc-shuttle/{self._schedule.dataset_id}",
            ),
            "sensitivity": self._definition.privacy_level,
            "usage": ResourceUsage(
                schema_version=1,
                tool_steps=1,
                cost_units=Decimal(self._definition.cost_hint.units),
            ),
            "observed_at": now,
            "truncated": False,
            "untrusted": True,
        }
        return CapabilityResult(
            result_digest=capability_result_digest(values),
            **values,
        )

    async def close(self) -> None:
        self._closed = True

    def _active_call(
        self, call: PortCallContext | ServiceCallContext
    ) -> datetime:
        if not isinstance(call, (PortCallContext, ServiceCallContext)):
            raise validation_error("invalid_shuttle_provider_call")
        if self._closed:
            raise error(
                "shuttle_provider_closed",
                ErrorCategory.EXTERNAL,
                "service.unavailable",
            )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise validation_error("invalid_shuttle_provider_clock")
        if call.cancellation.is_cancelled:
            raise error(
                "shuttle_provider_call_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if call.deadline <= now:
            raise error(
                "shuttle_provider_call_expired",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )
        return now


__all__ = ["UstcShuttleCapabilityProvider"]
