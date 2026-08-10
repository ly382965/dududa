from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from dududa.domain.identity import Actor, ActorRef, ConversationScope
from dududa.domain.primitives import DigestString
from dududa.ports.context import ServiceCallContext
from dududa.proactive.contracts import (
    InitiatedRunRequest,
    PreparedDispatch,
    ProactiveAuthorizationGrant,
    ProactiveAuthorizationGrantRef,
    ProactivePreviewRequest,
    ProactivePreviewResult,
    ProactiveQuotaLease,
    ProactiveRunReceipt,
    ProactiveTargetPolicy,
    ProactiveTargetPolicyRef,
)


@runtime_checkable
class ProactiveActorResolver(Protocol):
    async def resolve(
        self,
        reference: ActorRef,
        scope: ConversationScope,
        *,
        call: ServiceCallContext,
    ) -> Actor: ...


@runtime_checkable
class ProactiveTargetRegistry(Protocol):
    async def resolve_target(
        self,
        reference: ProactiveTargetPolicyRef,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ProactiveTargetPolicy: ...

    async def resolve_grant(
        self,
        reference: ProactiveAuthorizationGrantRef,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ProactiveAuthorizationGrant: ...


@runtime_checkable
class ProactiveQuotaLedger(Protocol):
    async def reserve(
        self,
        request_digest: DigestString,
        scope: ConversationScope,
        *,
        global_limit: int,
        scope_limit: int,
        window: timedelta,
        policy_revision: str,
        call: ServiceCallContext,
    ) -> tuple[ProactiveQuotaLease, ProactiveQuotaLease]: ...

    async def commit(
        self,
        leases: tuple[ProactiveQuotaLease, ProactiveQuotaLease],
        *,
        call: ServiceCallContext,
    ) -> None: ...

    async def release(
        self,
        leases: tuple[ProactiveQuotaLease, ProactiveQuotaLease],
        *,
        call: ServiceCallContext,
    ) -> None: ...


@runtime_checkable
class ProactiveDispatchStore(Protocol):
    async def prepare(
        self,
        dispatch: PreparedDispatch,
        *,
        call: ServiceCallContext,
    ) -> PreparedDispatch: ...

    async def load_for_trigger(
        self,
        trigger_digest: DigestString,
        *,
        call: ServiceCallContext,
    ) -> PreparedDispatch | None: ...


@runtime_checkable
class ProactivePreviewPort(Protocol):
    async def preview(
        self,
        request: ProactivePreviewRequest,
        *,
        call: ServiceCallContext,
    ) -> ProactivePreviewResult: ...


@runtime_checkable
class ProactiveDeliveryOrchestrator(Protocol):
    async def run(
        self,
        request: InitiatedRunRequest,
        *,
        call: ServiceCallContext,
    ) -> ProactiveRunReceipt: ...


__all__ = [
    "ProactiveActorResolver",
    "ProactiveDeliveryOrchestrator",
    "ProactiveDispatchStore",
    "ProactivePreviewPort",
    "ProactiveQuotaLedger",
    "ProactiveTargetRegistry",
]
