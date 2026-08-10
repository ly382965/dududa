from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from dududa.domain.content import (
    DraftResponse,
    FinalResponse,
    RenderValidationResult,
    ValidatedFinalResponse,
)
from dududa.domain.delivery import DeliveryReceipt
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import MessageDedupKey
from dududa.perception.contracts import PerceptionContext, SocialDecision
from dududa.persona.contracts import PersonaResolution
from dududa.responses.contracts import ResponsePlan
from dududa.runtime.contracts import (
    CurrentMessageContext,
    DeliveryReconciliationReceipt,
    DirectChatContent,
    PerceptionExecutionReceipt,
    ShadowRunReceipt,
)
from dududa.runtime.state import (
    CompletionReceipt,
    ConnectorResult,
    RuntimeCheckpoint,
    RuntimeCommitRequest,
    RuntimeCommitResult,
    RuntimeDedupRecord,
    RuntimeResult,
    RuntimeStartRequest,
)

from .context import PortCallContext, ServiceCallContext

RawEventT = TypeVar("RawEventT")


@runtime_checkable
class InputConnector(Protocol, Generic[RawEventT]):
    async def convert(
        self,
        event: RawEventT,
        *,
        operation: ServiceCallContext,
    ) -> ConnectorResult: ...


@runtime_checkable
class AgentRuntime(Protocol):
    async def run(
        self,
        request: RuntimeStartRequest,
        *,
        call: PortCallContext,
    ) -> RuntimeResult: ...

    async def acknowledge_delivery(
        self,
        receipt: DeliveryReceipt,
        *,
        call: PortCallContext,
    ) -> CompletionReceipt: ...

    async def reconcile_delivery(
        self,
        receipt: DeliveryReceipt,
        *,
        call: PortCallContext,
    ) -> DeliveryReconciliationReceipt: ...


@runtime_checkable
class ShadowReceiptSink(Protocol):
    async def write(
        self,
        receipt: ShadowRunReceipt,
        *,
        call: PortCallContext,
    ) -> None: ...


@runtime_checkable
class OfflineResponseComposer(Protocol):
    def compose(
        self,
        context: CurrentMessageContext,
        decision: SocialDecision,
        direct_content: DirectChatContent | None,
        response_plan: ResponsePlan | None = None,
    ) -> DraftResponse: ...


@runtime_checkable
class OfflinePersonaRenderer(Protocol):
    def render(
        self,
        draft: DraftResponse,
        response_plan: ResponsePlan | None = None,
        *,
        persona_resolution: PersonaResolution | None = None,
    ) -> FinalResponse: ...


@runtime_checkable
class OfflineRenderValidator(Protocol):
    def validate(
        self,
        draft: DraftResponse,
        rendered: FinalResponse,
        *,
        persona_resolution: PersonaResolution | None = None,
    ) -> RenderValidationResult: ...


@runtime_checkable
class OfflineFinalResponseValidator(Protocol):
    async def validate(
        self,
        draft: DraftResponse,
        rendered: FinalResponse,
        actor: Actor,
        scope: ConversationScope,
        *,
        response_plan: ResponsePlan | None = None,
        persona_resolution: PersonaResolution | None = None,
        call: PortCallContext,
    ) -> ValidatedFinalResponse: ...


@runtime_checkable
class RuntimePerceptionEngine(Protocol):
    async def perceive_with_receipt(
        self,
        context: PerceptionContext,
        *,
        call: PortCallContext,
    ) -> PerceptionExecutionReceipt: ...


@runtime_checkable
class RuntimeStateStore(Protocol):
    async def commit(
        self,
        request: RuntimeCommitRequest,
        *,
        call: PortCallContext,
    ) -> RuntimeCommitResult: ...

    async def load(
        self,
        run_id: str,
        *,
        call: PortCallContext,
    ) -> RuntimeCheckpoint | None: ...

    async def wait_for_revision(
        self,
        run_id: str,
        after_revision: int,
        *,
        call: PortCallContext,
    ) -> RuntimeCheckpoint | None: ...

    async def lookup_dedup(
        self,
        key: MessageDedupKey,
        *,
        call: PortCallContext,
    ) -> RuntimeDedupRecord | None: ...

    async def delete(
        self,
        run_id: str,
        expected_revision: int,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> None: ...
