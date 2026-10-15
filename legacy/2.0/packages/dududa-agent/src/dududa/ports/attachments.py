from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import AsyncIterator, Protocol, runtime_checkable

from dududa.domain.attachments import (
    AttachmentAccessRequest,
    AttachmentDeleteCommand,
    AttachmentDeleteReceipt,
    AttachmentDescriptor,
    AttachmentIngestRequest,
    StoredContentRef,
)

from .context import PortCallContext, ServiceCallContext


class BoundedAttachmentStream(Protocol):
    @property
    def descriptor(self) -> AttachmentDescriptor: ...

    def __aiter__(self) -> AsyncIterator[bytes]: ...


@runtime_checkable
class AttachmentRepository(Protocol):
    async def ingest_input(
        self,
        request: AttachmentIngestRequest,
        source: AsyncIterator[bytes],
        *,
        operation: ServiceCallContext,
    ) -> StoredContentRef: ...

    async def ingest_generated(
        self,
        request: AttachmentIngestRequest,
        source: AsyncIterator[bytes],
        *,
        call: PortCallContext,
    ) -> StoredContentRef: ...

    async def describe(
        self,
        request: AttachmentAccessRequest,
        *,
        call: PortCallContext,
    ) -> AttachmentDescriptor: ...

    def open(
        self,
        request: AttachmentAccessRequest,
        *,
        call: PortCallContext,
    ) -> AbstractAsyncContextManager[BoundedAttachmentStream]: ...

    async def delete(
        self,
        command: AttachmentDeleteCommand,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> AttachmentDeleteReceipt: ...
