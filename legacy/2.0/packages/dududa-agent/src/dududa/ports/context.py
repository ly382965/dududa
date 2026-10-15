from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from dududa.domain.primitives import (
    RuntimeBudget,
    TraceContext,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error


@runtime_checkable
class CancellationToken(Protocol):
    @property
    def is_cancelled(self) -> bool: ...

    async def wait(self) -> None: ...


class NeverCancelled:
    @property
    def is_cancelled(self) -> bool:
        return False

    async def wait(self) -> None:
        await asyncio.Future()


class ManualCancellationToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def cancel(self) -> None:
        self._event.set()


@dataclass(frozen=True, slots=True)
class PortCallContext:
    run_id: str
    trace: TraceContext
    deadline: datetime
    cancellation: CancellationToken
    budget: RuntimeBudget
    policy_snapshot_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.run_id, "run_id")
        require_non_empty(self.policy_snapshot_id, "policy_snapshot_id")
        require_aware(self.deadline, "deadline")


@dataclass(frozen=True, slots=True)
class ServicePrincipal:
    service_id: str
    instance_id: str
    roles: frozenset[str]

    def __post_init__(self) -> None:
        require_non_empty(self.service_id, "service_id")
        require_non_empty(self.instance_id, "instance_id")
        if any(not role.strip() for role in self.roles):
            raise validation_error("empty_service_role")


@dataclass(frozen=True, slots=True)
class ServiceCallContext:
    operation_id: str
    principal: ServicePrincipal
    operation_kind: str
    trace: TraceContext
    deadline: datetime
    cancellation: CancellationToken
    budget: RuntimeBudget
    policy_snapshot_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.operation_id, "operation_id")
        require_non_empty(self.operation_kind, "operation_kind")
        require_non_empty(self.policy_snapshot_id, "policy_snapshot_id")
        require_aware(self.deadline, "deadline")
