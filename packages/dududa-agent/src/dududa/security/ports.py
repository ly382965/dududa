from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypeVar, runtime_checkable

from dududa.domain.content import ContentSafetyDecision
from dududa.domain.primitives import ResourceUsage
from dududa.ports.context import PortCallContext, ServiceCallContext

from .models import (
    AuditEvent,
    AuditReceipt,
    AuthorizationDecision,
    AuthorizationRequest,
    BudgetLease,
    BudgetReceipt,
    BudgetReservationRequest,
    ConfirmationConsumeRequest,
    ConfirmationGrant,
    ConfirmationRequest,
    ConfirmationRequirement,
    ContentSafetyRequest,
    InteractionLease,
    InteractionLeaseReceipt,
    InteractionLimitRequest,
    RedactionRequest,
    RedactionResult,
    SecretRef,
)


T = TypeVar("T")


@runtime_checkable
class AuthorizationPolicy(Protocol):
    async def decide(
        self, request: AuthorizationRequest, *, call: PortCallContext
    ) -> AuthorizationDecision: ...


class AuthorizationDecisionVerifier(Protocol):
    def verify(
        self,
        decision: AuthorizationDecision,
        *,
        at: datetime | None = None,
    ) -> bool: ...


@runtime_checkable
class ConfirmationService(Protocol):
    async def issue(
        self, request: ConfirmationRequest, *, call: PortCallContext
    ) -> ConfirmationRequirement: ...

    async def consume(
        self, request: ConfirmationConsumeRequest, *, call: PortCallContext
    ) -> ConfirmationGrant: ...


@runtime_checkable
class InteractionLimiter(Protocol):
    async def reserve(
        self, request: InteractionLimitRequest, *, call: PortCallContext
    ) -> InteractionLease: ...

    async def commit(
        self, lease: InteractionLease, *, call: PortCallContext
    ) -> InteractionLeaseReceipt: ...

    async def release(
        self, lease: InteractionLease, *, call: PortCallContext
    ) -> InteractionLeaseReceipt: ...


@runtime_checkable
class BudgetLedger(Protocol):
    async def reserve(
        self,
        request: BudgetReservationRequest,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> BudgetLease: ...

    async def settle(
        self,
        lease: BudgetLease,
        usage: ResourceUsage,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> BudgetReceipt: ...

    async def release(
        self, lease: BudgetLease, *, call: PortCallContext | ServiceCallContext
    ) -> BudgetReceipt: ...


@runtime_checkable
class Redactor(Protocol):
    def redact(self, request: RedactionRequest) -> RedactionResult: ...


@runtime_checkable
class ContentSafetyPolicy(Protocol):
    async def evaluate(
        self, request: ContentSafetyRequest, *, call: PortCallContext
    ) -> ContentSafetyDecision: ...


@runtime_checkable
class AuditSink(Protocol):
    async def write(
        self, event: AuditEvent, *, call: PortCallContext | ServiceCallContext
    ) -> AuditReceipt: ...


class SecretValue(Protocol):
    def use_once(self, consumer: object) -> object: ...


class SecretResolver(Protocol):
    async def resolve(
        self, reference: SecretRef, *, call: PortCallContext | ServiceCallContext
    ) -> SecretValue: ...
