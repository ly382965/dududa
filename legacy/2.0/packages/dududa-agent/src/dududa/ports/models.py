from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    JsonValue,
    SchemaRef,
)
from dududa.models.contracts import (
    EndpointAdmissionRequest,
    EndpointAdmissionResult,
    EndpointCapacityLease,
    EndpointCapacityReceipt,
    ModelEndpointDescriptor,
    ModelInvocationEstimate,
    ModelOperationalSnapshot,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelUsage,
    ProviderRequest,
    ProviderResponse,
    ReasoningProfile,
)
from dududa.models.policy import (
    BootstrapTierDecision,
    BootstrapTierPolicyDefinition,
    ModelCatalogPublishReceipt,
    ModelCatalogUpdate,
    ModelRoutePolicy,
    ModelRoutingSnapshot,
    TierAuthority,
    TierDecision,
    TierPolicyDefinition,
    TierSelectionContext,
)
from dududa.ports.context import PortCallContext, ServiceCallContext


@runtime_checkable
class ModelRouter(Protocol):
    async def invoke(
        self,
        request: ModelRequest,
        tier_authority: TierAuthority,
        *,
        call: PortCallContext,
    ) -> ModelResponse: ...


@runtime_checkable
class ModelProvider(Protocol):
    @property
    def descriptor(self) -> ModelProviderDescriptor: ...

    async def generate(
        self,
        request: ProviderRequest,
        *,
        call: PortCallContext,
    ) -> ProviderResponse: ...

    async def health(
        self,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ModelProviderHealth: ...

    async def close(self) -> None: ...


@runtime_checkable
class ModelRoutingRegistry(Protocol):
    def acquire_snapshot(self) -> ModelRoutingSnapshot: ...

    def resolve_provider(
        self,
        snapshot: ModelRoutingSnapshot,
        provider_id: str,
        expected_revision: ComponentRevision,
    ) -> ModelProvider: ...

    def list_enabled(
        self,
        snapshot: ModelRoutingSnapshot,
    ) -> tuple[ModelProviderDescriptor, ...]: ...

    def policy_for(
        self,
        snapshot: ModelRoutingSnapshot,
        role: ModelRole,
    ) -> ModelRoutePolicy: ...


@runtime_checkable
class ModelCatalogPublisher(Protocol):
    async def publish(
        self,
        update: ModelCatalogUpdate,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ModelCatalogPublishReceipt: ...


@runtime_checkable
class ModelOperationalStateRegistry(Protocol):
    def acquire_snapshot(self) -> ModelOperationalSnapshot: ...


@runtime_checkable
class ModelOperationalSnapshotResolver(Protocol):
    def snapshot_by_id(
        self,
        snapshot_id: str,
        *,
        expected_digest: DigestString | None = None,
    ) -> ModelOperationalSnapshot: ...


@runtime_checkable
class ModelOperationalSnapshotPublisher(Protocol):
    async def publish(
        self,
        snapshot: ModelOperationalSnapshot,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ModelOperationalSnapshot: ...


@runtime_checkable
class ModelAdmissionController(Protocol):
    async def reserve(
        self,
        request: EndpointAdmissionRequest,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> EndpointAdmissionResult: ...

    async def settle(
        self,
        lease: EndpointCapacityLease,
        usage: ModelUsage | None,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> EndpointCapacityReceipt: ...

    async def release(
        self,
        lease: EndpointCapacityLease,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> EndpointCapacityReceipt: ...


@runtime_checkable
class ModelOutputCodec(Protocol):
    @property
    def revision(self) -> ComponentRevision: ...

    def validate(
        self,
        output: JsonValue,
        schema: SchemaRef,
    ) -> JsonValue: ...


@runtime_checkable
class ModelInvocationEstimator(Protocol):
    def estimate(
        self,
        request: ModelRequest,
        endpoint: ModelEndpointDescriptor,
        reasoning_profile: ReasoningProfile,
    ) -> ModelInvocationEstimate: ...


@runtime_checkable
class ModelTierPolicy(Protocol):
    def decide(
        self,
        context: TierSelectionContext,
        definition: TierPolicyDefinition,
        *,
        now: datetime,
    ) -> TierDecision: ...


@runtime_checkable
class BootstrapModelTierPolicy(Protocol):
    def decide(
        self,
        definition: BootstrapTierPolicyDefinition,
        *,
        now: datetime | None = None,
    ) -> BootstrapTierDecision: ...
