from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from dududa.domain.primitives import DigestString
from dududa.memory.models import (
    MemoryDeleteCommand,
    MemoryDeleteReceipt,
    MemoryExportPage,
    MemoryQuery,
    MemoryRankRequest,
    MemoryRankScore,
    MemoryRecord,
    MemoryRepositoryArchive,
    MemoryRepositorySnapshot,
    MemoryRestoreCommand,
    MemoryRestoreReceipt,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySubmissionReceipt,
    MemoryTombstoneCheckpoint,
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


class MemoryRetrievalPolicy(Protocol):
    @property
    def policy_revision(self) -> str: ...

    async def selectors_for(
        self,
        request: MemoryRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> tuple[ScopeSelector, ...]: ...


@runtime_checkable
class MemoryRanker(Protocol):
    async def rank(
        self,
        request: MemoryRankRequest,
        *,
        call: PortCallContext,
    ) -> tuple[MemoryRankScore, ...]: ...


@runtime_checkable
class ScopedMemoryRetriever(Protocol):
    async def retrieve(
        self,
        request: MemoryRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> MemoryRetrievalResult: ...


@runtime_checkable
class MemoryAdministration(Protocol):
    async def commit_delete(
        self,
        command: MemoryDeleteCommand,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> MemoryDeleteReceipt: ...

    async def export_page(
        self,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        page: PageRequest,
        *,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> MemoryExportPage: ...

    async def export_tombstone_checkpoint(
        self,
        *,
        call: ServiceCallContext,
    ) -> MemoryTombstoneCheckpoint: ...

    async def export_archive(
        self,
        *,
        call: ServiceCallContext,
    ) -> MemoryRepositoryArchive: ...

    async def restore(
        self,
        command: MemoryRestoreCommand,
        *,
        call: ServiceCallContext,
    ) -> MemoryRestoreReceipt: ...


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
