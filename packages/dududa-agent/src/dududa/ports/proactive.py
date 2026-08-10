from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from dududa.domain.content import ValidatedFinalResponse
from dududa.domain.identity import Actor, ActorRef, ConversationScope
from dududa.domain.primitives import DigestString
from dududa.ports.context import ServiceCallContext
from dududa.proactive.contracts import (
    DispatchClaim,
    DispatchLedgerRecord,
    DispatchState,
    InitiatedRunRequest,
    PreparedDispatch,
    ProactiveAuthorizationGrant,
    ProactiveAuthorizationGrantRef,
    ProactivePreviewMetadata,
    ProactivePreviewRequest,
    ProactivePreviewResult,
    ProactiveQuotaLease,
    ProactiveRunReceipt,
    ProactiveTargetPolicy,
    ProactiveTargetPolicyRef,
    ProactiveTriggerKind,
    SourceCategory,
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

    async def validate_target(
        self,
        reference: ProactiveTargetPolicyRef,
        *,
        trigger_kind: ProactiveTriggerKind,
        categories: frozenset[SourceCategory],
        at: datetime,
        call: ServiceCallContext,
    ) -> ProactiveTargetPolicy: ...


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

    async def load_record(
        self,
        trigger_digest: DigestString,
        *,
        call: ServiceCallContext,
    ) -> DispatchLedgerRecord | None: ...

    async def record_attempt(
        self,
        trigger_digest: DigestString,
        *,
        expected_revision: int,
        delivery_request_digest: DigestString,
        call: ServiceCallContext,
    ) -> DispatchLedgerRecord: ...

    async def record_outcome(
        self,
        trigger_digest: DigestString,
        *,
        expected_revision: int,
        state: DispatchState,
        delivery_request_digest: DigestString,
        delivery_receipt_digest: DigestString,
        call: ServiceCallContext,
    ) -> DispatchLedgerRecord: ...

    async def recover(
        self,
        trigger_digest: DigestString,
        *,
        call: ServiceCallContext,
    ) -> DispatchLedgerRecord | None: ...

    async def claim(
        self,
        trigger_digest: DigestString,
        *,
        worker_id: str,
        ttl: timedelta,
        call: ServiceCallContext,
    ) -> DispatchClaim: ...


@runtime_checkable
class ProactivePreviewPort(Protocol):
    async def preview(
        self,
        request: ProactivePreviewRequest,
        *,
        call: ServiceCallContext,
    ) -> ProactivePreviewResult: ...


@runtime_checkable
class ProactivePreviewProducer(Protocol):
    async def build(
        self,
        request: ProactivePreviewRequest,
        *,
        call: ServiceCallContext,
    ) -> tuple[ValidatedFinalResponse, DigestString | None]: ...


@runtime_checkable
class ProactivePreviewMetadataStore(Protocol):
    async def record(
        self,
        metadata: ProactivePreviewMetadata,
        *,
        call: ServiceCallContext,
    ) -> None: ...


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
    "ProactivePreviewMetadataStore",
    "ProactivePreviewPort",
    "ProactivePreviewProducer",
    "ProactiveQuotaLedger",
    "ProactiveTargetRegistry",
]
