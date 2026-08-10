from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol, runtime_checkable

from dududa.domain.content import ValidatedFinalResponse
from dududa.domain.identity import Actor, ActorRef, ConversationScope
from dududa.domain.primitives import DigestString
from dududa.ports.context import PortCallContext, ServiceCallContext
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
    ProactiveSubscription,
    ProactiveTargetPolicy,
    ProactiveTargetPolicyRef,
    ProactiveTrigger,
    ProactiveTriggerKind,
    ScheduleClaimDisposition,
    ScheduleClaimReceipt,
    ScheduleLedgerRecord,
    ScheduleMaterializationReceipt,
    ScheduleOccurrenceState,
    ScheduleTriggerClaim,
    SourceCategory,
    SubscriptionMutationReceipt,
)
from dududa.proactive.source_contracts import (
    SourceCapabilityObservation,
    SourceCursor,
    SourceDefinition,
    SourceFetchReceipt,
    SourceFetchRequest,
    SourcePolicySnapshot,
    SourceStateCommitPlan,
    SourceStateCommitReceipt,
)


@runtime_checkable
class SourcePolicyRegistry(Protocol):
    def resolve(
        self,
        policy_id: str,
        *,
        expected_digest: DigestString,
    ) -> SourcePolicySnapshot: ...


@runtime_checkable
class SourceCapabilityReader(Protocol):
    async def read(
        self,
        definition: SourceDefinition,
        cursor: SourceCursor | None,
        request: SourceFetchRequest,
        *,
        call: PortCallContext,
    ) -> SourceCapabilityObservation: ...


@runtime_checkable
class SourceStateStore(Protocol):
    async def load_cursor(
        self,
        subscription_id: str,
        source_id: str,
        *,
        call: PortCallContext,
    ) -> SourceCursor | None: ...

    async def commit_fetch(
        self,
        plan: SourceStateCommitPlan,
        *,
        call: PortCallContext,
    ) -> SourceStateCommitReceipt: ...


@runtime_checkable
class SourceProvider(Protocol):
    async def fetch(
        self,
        request: SourceFetchRequest,
        *,
        call: PortCallContext,
    ) -> SourceFetchReceipt: ...


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
class ProactiveSubscriptionStore(Protocol):
    async def publish(
        self,
        subscription: ProactiveSubscription,
        *,
        expected_revision: int | None,
        mutation_id: str,
        call: ServiceCallContext,
    ) -> SubscriptionMutationReceipt: ...

    async def load(
        self,
        subscription_id: str,
        *,
        call: ServiceCallContext,
    ) -> ProactiveSubscription | None: ...

    async def list_active(
        self,
        *,
        call: ServiceCallContext,
    ) -> tuple[ProactiveSubscription, ...]: ...


@runtime_checkable
class ProactiveScheduleStore(Protocol):
    async def record_trigger(
        self,
        trigger: ProactiveTrigger,
        state: ScheduleOccurrenceState,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ScheduleMaterializationReceipt: ...

    async def record_nonexistent(
        self,
        subscription: ProactiveSubscription,
        local_date: date,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ScheduleMaterializationReceipt: ...

    async def list_due(
        self,
        *,
        at: datetime,
        limit: int,
        call: ServiceCallContext,
    ) -> tuple[ScheduleLedgerRecord, ...]: ...

    async def claim(
        self,
        occurrence_digest: DigestString,
        *,
        worker_id: str,
        ttl: timedelta,
        at: datetime,
        call: ServiceCallContext,
    ) -> tuple[ScheduleTriggerClaim, ScheduleClaimDisposition]: ...

    async def acknowledge(
        self,
        claim: ScheduleTriggerClaim,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ScheduleClaimReceipt: ...

    async def load_schedule_record(
        self,
        subscription_id: str,
        local_date: date,
        *,
        call: ServiceCallContext,
    ) -> ScheduleLedgerRecord | None: ...


@runtime_checkable
class ProactiveScheduler(Protocol):
    async def materialize_due(
        self,
        *,
        now: datetime,
        call: ServiceCallContext,
    ) -> tuple[ScheduleMaterializationReceipt, ...]: ...

    async def claim_due(
        self,
        *,
        worker_id: str,
        limit: int,
        ttl: timedelta,
        now: datetime,
        call: ServiceCallContext,
    ) -> tuple[ScheduleTriggerClaim, ...]: ...

    async def acknowledge(
        self,
        claim: ScheduleTriggerClaim,
        *,
        now: datetime,
        call: ServiceCallContext,
    ) -> ScheduleClaimReceipt: ...


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
    "ProactiveScheduleStore",
    "ProactiveScheduler",
    "ProactiveSubscriptionStore",
    "ProactiveTargetRegistry",
    "SourceCapabilityReader",
    "SourcePolicyRegistry",
    "SourceProvider",
    "SourceStateStore",
]
