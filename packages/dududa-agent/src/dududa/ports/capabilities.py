from __future__ import annotations

from typing import Protocol, runtime_checkable

from dududa.capabilities.contracts import (
    ArgumentBindingRequest,
    ArgumentBindingResult,
    CapabilityCatalogPublishReceipt,
    CapabilityCatalogSnapshot,
    CapabilityCatalogUpdate,
    CapabilityHealthSnapshot,
    CapabilityProviderDescriptor,
    CapabilityProviderHealth,
    CapabilityResult,
    CapabilityRetrievalRequest,
    CapabilityRetrievalResult,
    CapabilityRunReceipt,
    CapabilityRunRequest,
    CapabilitySchemaDocument,
    McpCapabilityMapping,
    ProviderInvocation,
    ToolExecutionRequest,
    ToolInvocationClaim,
    ToolInvocationClaimRequest,
    ToolInvocationReceipt,
    ToolObservation,
    ToolPlan,
    ToolPlanningRequest,
    ToolPlanValidationRequest,
    ToolPlanValidationResult,
    ToolValidationRequest,
    ToolValidationResult,
)
from dududa.domain.capability import CapabilityDefinition, ProviderRef
from dududa.domain.primitives import JsonValue, SchemaRef

from .context import PortCallContext, ServiceCallContext

CapabilityCallerContext = PortCallContext | ServiceCallContext


@runtime_checkable
class CapabilitySchemaValidator(Protocol):
    def check_schema(self, document: CapabilitySchemaDocument) -> None: ...

    def validate(
        self,
        value: JsonValue,
        document: CapabilitySchemaDocument,
    ) -> JsonValue: ...


@runtime_checkable
class CapabilityRegistry(Protocol):
    def acquire_snapshot(self) -> CapabilityCatalogSnapshot: ...

    def snapshot_by_id(
        self,
        snapshot_id: str,
        *,
        expected_digest: str | None = None,
    ) -> CapabilityCatalogSnapshot: ...

    def get_definition(
        self,
        snapshot: CapabilityCatalogSnapshot,
        capability_id: str,
    ) -> CapabilityDefinition: ...

    def get_schema(
        self,
        snapshot: CapabilityCatalogSnapshot,
        schema_ref: SchemaRef,
    ) -> CapabilitySchemaDocument: ...

    def get_mcp_mapping(
        self,
        snapshot: CapabilityCatalogSnapshot,
        capability_id: str,
    ) -> McpCapabilityMapping | None: ...


@runtime_checkable
class CapabilityCatalogPublisher(Protocol):
    async def publish(
        self,
        update: CapabilityCatalogUpdate,
        *,
        call: CapabilityCallerContext,
    ) -> CapabilityCatalogPublishReceipt: ...


@runtime_checkable
class CapabilityProviderRegistry(Protocol):
    def resolve(
        self,
        snapshot: CapabilityCatalogSnapshot,
        provider: ProviderRef,
    ) -> CapabilityProvider: ...


@runtime_checkable
class CapabilityHealthRegistry(Protocol):
    async def snapshot(
        self,
        providers: tuple[CapabilityProviderDescriptor, ...],
        *,
        call: CapabilityCallerContext,
    ) -> CapabilityHealthSnapshot: ...


@runtime_checkable
class CapabilityRetriever(Protocol):
    async def retrieve(
        self,
        request: CapabilityRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> CapabilityRetrievalResult: ...


@runtime_checkable
class ToolPlanner(Protocol):
    async def plan(
        self,
        request: ToolPlanningRequest,
        *,
        call: PortCallContext,
    ) -> ToolPlan: ...


@runtime_checkable
class ToolPlanValidator(Protocol):
    def validate(
        self, request: ToolPlanValidationRequest
    ) -> ToolPlanValidationResult: ...


@runtime_checkable
class ArgumentBinder(Protocol):
    def bind(self, request: ArgumentBindingRequest) -> ArgumentBindingResult: ...


@runtime_checkable
class CapabilityProvider(Protocol):
    @property
    def descriptor(self) -> CapabilityProviderDescriptor: ...

    async def health(
        self,
        *,
        call: CapabilityCallerContext,
    ) -> CapabilityProviderHealth: ...

    async def invoke(
        self,
        request: ProviderInvocation,
        *,
        call: PortCallContext,
    ) -> CapabilityResult: ...

    async def close(self) -> None: ...


@runtime_checkable
class ToolExecutor(Protocol):
    async def execute(
        self,
        request: ToolExecutionRequest,
        *,
        call: PortCallContext,
    ) -> ToolObservation: ...


@runtime_checkable
class ToolResultValidator(Protocol):
    async def validate(
        self,
        request: ToolValidationRequest,
        *,
        call: PortCallContext,
    ) -> ToolValidationResult: ...


@runtime_checkable
class ToolInvocationLedger(Protocol):
    async def acquire(
        self,
        request: ToolInvocationClaimRequest,
        *,
        call: PortCallContext,
    ) -> ToolInvocationClaim: ...

    async def complete(
        self,
        claim: ToolInvocationClaim,
        observation: ToolObservation,
        *,
        call: PortCallContext,
    ) -> ToolInvocationReceipt: ...

    async def wait(
        self,
        claim: ToolInvocationClaim,
        *,
        call: PortCallContext,
    ) -> ToolInvocationReceipt | None: ...


@runtime_checkable
class BoundedCapabilityRuntime(Protocol):
    async def run(
        self,
        request: CapabilityRunRequest,
        *,
        call: PortCallContext,
    ) -> CapabilityRunReceipt: ...


__all__ = [
    "ArgumentBinder",
    "BoundedCapabilityRuntime",
    "CapabilityCallerContext",
    "CapabilityCatalogPublisher",
    "CapabilityHealthRegistry",
    "CapabilityProvider",
    "CapabilityProviderRegistry",
    "CapabilityRegistry",
    "CapabilityRetriever",
    "CapabilitySchemaValidator",
    "ToolExecutor",
    "ToolInvocationLedger",
    "ToolPlanner",
    "ToolPlanValidator",
    "ToolResultValidator",
]
