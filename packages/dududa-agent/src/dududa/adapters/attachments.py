from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import uuid

from dududa.contracts.attachments import (
    attachment_access_authorization_metadata,
    attachment_access_resource,
    attachment_delete_authorization_metadata,
    attachment_delete_resource,
)
from dududa.contracts.canonical import canonical_digest
from dududa.domain.attachments import (
    AttachmentAccessRequest,
    AttachmentDeleteCommand,
    AttachmentDeleteReceipt,
    AttachmentDescriptor,
    AttachmentIngestRequest,
    StoredContentRef,
)
from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.errors import ErrorCategory, error
from dududa.ports.attachments import BoundedAttachmentStream
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.security.digests import (
    authorization_metadata_digest,
    resource_digest,
    scope_digest,
)
from dududa.security.models import AuthorizationEffect


@dataclass(frozen=True, slots=True)
class _StoredAttachment:
    descriptor: AttachmentDescriptor
    content: bytes
    ingest_digest: DigestString


class _MemoryStream:
    def __init__(
        self,
        descriptor: AttachmentDescriptor,
        content: bytes,
        call: PortCallContext,
        clock: Callable[[], datetime],
    ) -> None:
        self._descriptor = descriptor
        self._content = content
        self._call = call
        self._clock = clock

    @property
    def descriptor(self) -> AttachmentDescriptor:
        return self._descriptor

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for offset in range(0, len(self._content), 64 * 1024):
            _validate_call(self._call, self._clock())
            yield self._content[offset : offset + 64 * 1024]


class InMemoryAttachmentRepository:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._revision = ComponentRevision(
            "attachment.memory", "1", "memory-v1", DigestString("builtin")
        )
        self._records: dict[str, _StoredAttachment] = {}
        self._idempotency: dict[str, str] = {}
        self._delete_keys: dict[
            str,
            tuple[DigestString, AttachmentDeleteReceipt],
        ] = {}
        self._lock = asyncio.Lock()

    async def ingest_input(
        self,
        request: AttachmentIngestRequest,
        source: AsyncIterator[bytes],
        *,
        operation: ServiceCallContext,
    ) -> StoredContentRef:
        if (
            request.origin.value != "platform_input"
            or not operation.principal.roles.intersection({"ingest", "connector"})
            or operation.operation_kind != "platform_input"
        ):
            raise _attachment_error("attachment_ingest_operation_denied")
        return await self._ingest(request, source, operation)

    async def ingest_generated(
        self,
        request: AttachmentIngestRequest,
        source: AsyncIterator[bytes],
        *,
        call: PortCallContext,
    ) -> StoredContentRef:
        if request.origin.value == "platform_input":
            raise _attachment_error("generated_attachment_origin_invalid")
        return await self._ingest(request, source, call)

    async def _ingest(
        self,
        request: AttachmentIngestRequest,
        source: AsyncIterator[bytes],
        call: PortCallContext | ServiceCallContext,
    ) -> StoredContentRef:
        now = self._clock()
        _validate_call(call, now)
        if request.expires_at <= now:
            raise _attachment_error("attachment_expired_before_ingest")
        request_digest = canonical_digest(
            request, domain="attachment:ingest-request:v1"
        )
        chunks: list[bytes] = []
        size = 0
        iterator = source.__aiter__()
        while True:
            try:
                chunk = await _next_chunk(iterator, call, self._clock)
            except StopAsyncIteration:
                break
            if not isinstance(chunk, bytes) or not chunk:
                raise _attachment_error("invalid_attachment_chunk")
            size += len(chunk)
            if size > request.maximum_size_bytes:
                raise _attachment_error("attachment_oversize")
            chunks.append(chunk)
        if (
            request.declared_size_bytes is not None
            and size != request.declared_size_bytes
        ):
            raise _attachment_error("attachment_size_mismatch")
        content = b"".join(chunks)
        media_type = _sniff_media_type(content, request.declared_media_type)
        digest = _blob_digest(content)
        async with self._lock:
            existing_ref = self._idempotency.get(request.idempotency_key)
            if existing_ref is not None:
                existing = self._records.get(existing_ref)
                if existing is None:
                    raise _attachment_error("attachment_ingest_tombstoned")
                if (
                    existing.ingest_digest != request_digest
                    or existing.descriptor.content_digest != digest
                ):
                    raise _attachment_error("attachment_idempotency_conflict")
                return _stored_ref(existing.descriptor)
            content_ref = f"att:{self._id_factory()}"
            descriptor = AttachmentDescriptor(
                1,
                content_ref,
                digest,
                media_type,
                size,
                request.scope_digest,
                request.sensitivity,
                now,
                request.expires_at,
                self._revision,
            )
            self._records[content_ref] = _StoredAttachment(
                descriptor, content, request_digest
            )
            self._idempotency[request.idempotency_key] = content_ref
            return _stored_ref(descriptor)

    async def describe(
        self,
        request: AttachmentAccessRequest,
        *,
        call: PortCallContext,
    ) -> AttachmentDescriptor:
        _validate_call(call, self._clock())
        async with self._lock:
            record = self._authorized_record(request, call)
            return record.descriptor

    @asynccontextmanager
    async def open(
        self,
        request: AttachmentAccessRequest,
        *,
        call: PortCallContext,
    ) -> AsyncIterator[BoundedAttachmentStream]:
        _validate_call(call, self._clock())
        async with self._lock:
            record = self._authorized_record(request, call)
        yield _MemoryStream(record.descriptor, record.content, call, self._clock)

    async def delete(
        self,
        command: AttachmentDeleteCommand,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> AttachmentDeleteReceipt:
        now = self._clock()
        _validate_call(call, now)
        command_digest = canonical_digest(
            command,
            domain="attachment:delete-command:v1",
        )
        async with self._lock:
            duplicate = self._delete_keys.get(command.idempotency_key)
            if duplicate is not None:
                if duplicate[0] != command_digest:
                    raise _attachment_error("attachment_delete_idempotency_conflict")
                return duplicate[1]
            record = self._records.get(command.content_ref)
            if record is None:
                raise _attachment_error("attachment_not_found")
            descriptor = record.descriptor
            if descriptor.content_digest != command.expected_content_digest:
                raise _attachment_error("attachment_digest_mismatch")
            operation_id = (
                call.run_id if isinstance(call, PortCallContext) else call.operation_id
            )
            authorization = command.authorization
            expected_metadata = attachment_delete_authorization_metadata(
                command,
                operation_id=operation_id,
                policy_snapshot_id=call.policy_snapshot_id,
            )
            if (
                authorization.effect is not AuthorizationEffect.ALLOW
                or str(authorization.action) != "attachment.delete"
                or authorization.scope_digest != descriptor.scope_digest
                or authorization.resource_digest
                != resource_digest(
                    attachment_delete_resource(
                        command,
                        scope=descriptor.scope_digest,
                    )
                )
                or authorization.metadata_digest
                != authorization_metadata_digest(expected_metadata)
                or authorization.decided_at > now
                or authorization.expires_at <= now
            ):
                raise _attachment_error("attachment_delete_not_authorized")
            self._records.pop(command.content_ref)
            receipt = AttachmentDeleteReceipt(
                1,
                command.content_ref,
                True,
                self._revision,
                now,
            )
            self._delete_keys[command.idempotency_key] = (command_digest, receipt)
            return receipt

    def _authorized_record(
        self,
        request: AttachmentAccessRequest,
        call: PortCallContext,
    ) -> _StoredAttachment:
        record = self._records.get(request.content_ref)
        if record is None:
            raise _attachment_error("attachment_not_found")
        descriptor = record.descriptor
        now = self._clock()
        expected_scope = scope_digest(request.conversation_scope)
        authorization = request.authorization
        expected_metadata = attachment_access_authorization_metadata(
            request,
            run_id=call.run_id,
            policy_snapshot_id=call.policy_snapshot_id,
        )
        if (
            descriptor.expires_at <= now
            or descriptor.scope_digest != expected_scope
            or authorization.effect is not AuthorizationEffect.ALLOW
            or str(authorization.action) != "attachment.read"
            or authorization.scope_digest != expected_scope
            or authorization.resource_digest
            != resource_digest(attachment_access_resource(request))
            or authorization.metadata_digest
            != authorization_metadata_digest(expected_metadata)
            or authorization.decided_at > now
            or authorization.expires_at <= now
        ):
            raise _attachment_error("attachment_access_denied")
        if descriptor.content_digest != request.expected_content_digest:
            raise _attachment_error("attachment_digest_mismatch")
        if descriptor.media_type not in request.accepted_media_types:
            raise _attachment_error("attachment_media_type_denied")
        if descriptor.size_bytes > request.maximum_size_bytes:
            raise _attachment_error("attachment_oversize")
        return record


def _blob_digest(content: bytes) -> DigestString:
    material = b"dududa-attachment-v1\x00" + content
    return DigestString(
        "dududa-c14n-v1:attachment-content:v1:sha-256:"
        + hashlib.sha256(material).hexdigest()
    )


def _sniff_media_type(content: bytes, declared: str) -> str:
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF8", "image/gif"),
        (b"%PDF-", "application/pdf"),
        (b"ID3", "audio/mpeg"),
        (b"OggS", "audio/ogg"),
        (b"RIFF", "audio/wav"),
    )
    detected = next(
        (media for signature, media in signatures if content.startswith(signature)),
        None,
    )
    if len(content) >= 12 and content[4:8] == b"ftyp":
        detected = "video/mp4"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        detected = "image/webp"
    if detected is not None and declared not in {detected, "application/octet-stream"}:
        raise _attachment_error("attachment_media_type_mismatch")
    if detected is not None:
        return detected
    if declared == "application/octet-stream":
        return declared
    if declared == "text/plain":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise _attachment_error("attachment_media_type_unrecognized") from None
        if b"\x00" not in content:
            return declared
    raise _attachment_error("attachment_media_type_unrecognized")


async def _next_chunk(
    iterator: AsyncIterator[bytes],
    call: PortCallContext | ServiceCallContext,
    clock: Callable[[], datetime],
) -> bytes:
    now = clock()
    _validate_call(call, now)
    remaining = (call.deadline - now).total_seconds()
    next_task = asyncio.ensure_future(iterator.__anext__())
    cancellation_task = asyncio.ensure_future(call.cancellation.wait())
    tasks = (next_task, cancellation_task)
    try:
        done, _ = await asyncio.wait(
            tasks,
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if next_task in done:
            return next_task.result()
        raise _attachment_error("attachment_operation_cancelled_or_expired")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)


def _validate_call(
    call: PortCallContext | ServiceCallContext,
    now: datetime,
) -> None:
    if call.cancellation.is_cancelled or call.deadline <= now:
        raise _attachment_error("attachment_operation_cancelled_or_expired")


def _stored_ref(descriptor: AttachmentDescriptor) -> StoredContentRef:
    return StoredContentRef(
        1,
        descriptor.content_ref,
        descriptor.content_digest,
        descriptor.media_type,
        descriptor.size_bytes,
        descriptor.repository_revision,
    )


def _attachment_error(code: str):
    return error(code, ErrorCategory.AUTHORIZATION, "attachment.unavailable")
