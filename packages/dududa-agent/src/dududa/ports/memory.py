from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from dududa.domain.primitives import DigestString
from dududa.memory.models import (
    MemoryQuery,
    MemoryRecord,
    MemoryRepositorySnapshot,
    MemorySubmissionReceipt,
    MemoryWriteCommand,
    Page,
    PageRequest,
    ScopeSelector,
)

from .context import PortCallContext, ServiceCallContext


class ScopeSelectorVerifier(Protocol):
    def verify(
        self,
        selector: ScopeSelector,
        *,
        expected_request_digest: DigestString,
    ) -> bool: ...


@runtime_checkable
class MemoryRepository(Protocol):
    async def open_snapshot(
        self,
        selectors: tuple[ScopeSelector, ...],
        *,
        request_digest: DigestString,
        as_of: datetime,
        call: PortCallContext,
    ) -> MemoryRepositorySnapshot: ...

    async def get(
        self,
        snapshot: MemoryRepositorySnapshot,
        memory_id: str,
        selector: ScopeSelector,
        *,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> MemoryRecord | None: ...

    async def retrieve(
        self,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        query: MemoryQuery,
        *,
        candidate_limit: int,
        cursor: str | None,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> Page[MemoryRecord]: ...

    async def list(
        self,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        page: PageRequest,
        *,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> Page[MemoryRecord]: ...

    async def commit_write(
        self,
        command: MemoryWriteCommand,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> MemorySubmissionReceipt: ...
