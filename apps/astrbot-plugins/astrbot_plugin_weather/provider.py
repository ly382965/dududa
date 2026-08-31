from __future__ import annotations

from collections.abc import Callable, Mapping
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

from .weather import WeatherSourcePort, WttrWeatherSource


class WeatherCapabilityProvider:
    """Dududa 2.0 read-only Capability adapter for explicit city queries."""

    def __init__(
        self,
        descriptor: CapabilityProviderDescriptor,
        definition: CapabilityDefinition,
        output_schema,
        schema_validator: CapabilitySchemaValidator,
        *,
        source: WeatherSourcePort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if descriptor.kind is not CapabilityProviderKind.BUILTIN:
            raise ValueError("weather Provider requires a builtin descriptor")
        if descriptor.capability_ids != frozenset({definition.capability_id}):
            raise ValueError("weather Provider definition does not match descriptor")
        if definition.provider != descriptor.provider:
            raise ValueError("weather Provider reference mismatch")
        schema_validator.check_schema(output_schema)
        self._descriptor = descriptor
        self._definition = definition
        self._output_schema = output_schema
        self._schema_validator = schema_validator
        self._source = source or WttrWeatherSource()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._closed = False

    @classmethod
    def from_catalog(
        cls,
        snapshot: CapabilityCatalogSnapshot,
        descriptor: CapabilityProviderDescriptor,
        schema_validator: CapabilitySchemaValidator,
        *,
        source: WeatherSourcePort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> WeatherCapabilityProvider:
        if descriptor.provider.provider_id != "plugin.weather":
            raise validation_error("invalid_weather_provider_id")
        definitions = tuple(
            item
            for item in snapshot.definitions
            if item.provider == descriptor.provider
        )
        if len(definitions) != 1:
            raise validation_error("invalid_weather_provider_definition_count")
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
            raise validation_error("weather_output_schema_missing")
        return cls(
            descriptor,
            definition,
            output_schema,
            schema_validator,
            source=source,
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
                    reason_codes=("weather_source_adapter_ready",),
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
            raise validation_error("invalid_weather_provider_invocation")
        city = request.arguments.get("city")
        if not isinstance(city, str) or not city.strip():
            raise validation_error("invalid_weather_provider_arguments")

        data = await self._source.fetch(city)
        data = self._schema_validator.validate(data, self._output_schema)
        provenance = data.get("provenance") if isinstance(data, Mapping) else None
        source_url = (
            provenance.get("source_url")
            if isinstance(provenance, Mapping)
            else "https://wttr.in"
        )
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
            "source_refs": (str(source_url),),
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
        if self._closed:
            return
        self._closed = True
        await self._source.close()

    def _active_call(self, call: PortCallContext | ServiceCallContext) -> datetime:
        if not isinstance(call, (PortCallContext, ServiceCallContext)):
            raise validation_error("invalid_weather_provider_call")
        if self._closed:
            raise error(
                "weather_provider_closed",
                ErrorCategory.EXTERNAL,
                "service.unavailable",
            )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise validation_error("invalid_weather_provider_clock")
        if call.cancellation.is_cancelled:
            raise error(
                "weather_provider_call_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if call.deadline <= now:
            raise error(
                "weather_provider_call_expired",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )
        return now


__all__ = ["WeatherCapabilityProvider"]
