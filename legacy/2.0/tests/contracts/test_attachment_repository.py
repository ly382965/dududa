from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from dududa.adapters.attachments import InMemoryAttachmentRepository
from dududa.contracts.attachments import (
    attachment_access_authorization_metadata,
    attachment_access_resource,
    attachment_delete_authorization_metadata,
    attachment_delete_resource,
)
from dududa.domain.attachments import (
    AttachmentAccessRequest,
    AttachmentDeleteCommand,
    AttachmentIngestRequest,
    AttachmentOrigin,
    AttachmentPurpose,
)
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    ConversationType,
    DigestString,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.security.digests import (
    actor_digest,
    authorization_metadata_digest,
    resource_digest,
    scope_digest,
)
from dududa.security.models import AuthorizationDecision, AuthorizationEffect


async def chunks(*values: bytes):
    for value in values:
        yield value


class BlockingChunks:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.cancelled.set()
        raise StopAsyncIteration


class AttachmentRepositoryContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.scope = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "g-1", "g-1", "dududa"
        )
        self.actor = Actor(
            "qq", "bot-1", "u-1", frozenset({RoleId("normal")}), frozenset()
        )
        budget = RuntimeBudget(0, 0, 0, 0, 0, Decimal("0"))
        self.call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            self.now + timedelta(hours=2),
            NeverCancelled(),
            budget,
            "policy-v1",
        )
        self.operation = ServiceCallContext(
            "attachment.ingest",
            ServicePrincipal("connector", "test", frozenset({"ingest"})),
            "platform_input",
            TraceContext("trace-1"),
            self.now + timedelta(hours=2),
            NeverCancelled(),
            budget,
            "policy-v1",
        )
        self.repository = InMemoryAttachmentRepository(
            clock=lambda: self.now,
            id_factory=lambda: "content-1",
        )

    def ingest_request(
        self, *, maximum: int = 32, key: str = "ingest-1"
    ) -> AttachmentIngestRequest:
        return AttachmentIngestRequest(
            1,
            "m-1:0",
            AttachmentOrigin.PLATFORM_INPUT,
            scope_digest(self.scope),
            "image/png",
            None,
            maximum,
            Sensitivity.PERSONAL,
            self.now + timedelta(hours=1),
            key,
        )

    def authorization(
        self,
        *,
        action: str,
        resource: DigestString,
        metadata: DigestString,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            1,
            "decision-1",
            AuthorizationEffect.ALLOW,
            DigestString("request"),
            actor_digest(self.actor),
            scope_digest(self.scope),
            ActionId(action),
            resource,
            None,
            RiskLevel.LOW,
            metadata,
            "policy-v1",
            (),
            self.now,
            self.now + timedelta(hours=1),
        )

    def access_request(
        self,
        content_ref: str,
        content_digest: DigestString,
        *,
        scope: ConversationScope | None = None,
        call: PortCallContext | None = None,
    ) -> AttachmentAccessRequest:
        selected_scope = scope or self.scope
        selected_call = call or self.call
        provisional = self.authorization(
            action="attachment.read",
            resource=DigestString("pending-resource"),
            metadata=DigestString("pending-metadata"),
        )
        request = AttachmentAccessRequest(
            1,
            content_ref,
            content_digest,
            selected_scope,
            AttachmentPurpose.PREPROCESS,
            frozenset({"image/png"}),
            32,
            provisional,
        )
        authorization = replace(
            provisional,
            scope_digest=scope_digest(selected_scope),
            resource_digest=resource_digest(attachment_access_resource(request)),
            metadata_digest=authorization_metadata_digest(
                attachment_access_authorization_metadata(
                    request,
                    run_id=selected_call.run_id,
                    policy_snapshot_id=selected_call.policy_snapshot_id,
                )
            ),
        )
        return replace(request, authorization=authorization)

    async def test_bounded_ingest_access_and_idempotency(self) -> None:
        content = b"\x89PNG\r\n\x1a\ncontent"
        request = self.ingest_request()
        first = await self.repository.ingest_input(
            request, chunks(content), operation=self.operation
        )
        duplicate = await self.repository.ingest_input(
            request, chunks(content), operation=self.operation
        )
        self.assertEqual(first, duplicate)
        self.assertNotIn("/", first.content_ref)
        self.assertNotIn("://", first.content_ref)
        access = self.access_request(first.content_ref, first.content_digest)
        descriptor = await self.repository.describe(access, call=self.call)
        self.assertEqual(descriptor.size_bytes, len(content))
        async with self.repository.open(access, call=self.call) as stream:
            loaded = b"".join([item async for item in stream])
        self.assertEqual(loaded, content)

    async def test_oversize_mime_and_cross_scope_fail_closed(self) -> None:
        with self.assertRaises(DududaError):
            await self.repository.ingest_input(
                self.ingest_request(maximum=8),
                chunks(b"\x89PNG\r\n\x1a\ncontent"),
                operation=self.operation,
            )
        wrong_mime = replace(
            self.ingest_request(key="mime"), declared_media_type="image/jpeg"
        )
        with self.assertRaises(DududaError):
            await self.repository.ingest_input(
                wrong_mime,
                chunks(b"\x89PNG\r\n\x1a\ncontent"),
                operation=self.operation,
            )
        stored = await self.repository.ingest_input(
            self.ingest_request(key="scope"),
            chunks(b"\x89PNG\r\n\x1a\ncontent"),
            operation=self.operation,
        )
        other_scope = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "g-2", "g-2", "dududa"
        )
        access = self.access_request(
            stored.content_ref,
            stored.content_digest,
            scope=other_scope,
        )
        with self.assertRaises(DududaError):
            await self.repository.describe(access, call=self.call)

    async def test_authorization_action_resource_purpose_and_call_are_bound(
        self,
    ) -> None:
        stored = await self.repository.ingest_input(
            self.ingest_request(),
            chunks(b"\x89PNG\r\n\x1a\ncontent"),
            operation=self.operation,
        )
        access = self.access_request(stored.content_ref, stored.content_digest)
        invalid = (
            replace(
                access,
                authorization=replace(
                    access.authorization,
                    action=ActionId("message.send"),
                ),
            ),
            replace(access, purpose=AttachmentPurpose.MODEL_INPUT),
        )
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(DududaError):
                await self.repository.describe(request, call=self.call)
        wrong_call = replace(self.call, run_id="other-run")
        with self.assertRaises(DududaError):
            await self.repository.describe(access, call=wrong_call)

    async def test_unknown_mime_and_cancelled_ingest_fail_closed(self) -> None:
        disguised = replace(
            self.ingest_request(key="script"),
            declared_size_bytes=len(b"<script>alert(1)</script>"),
        )
        with self.assertRaises(DududaError):
            await self.repository.ingest_input(
                disguised,
                chunks(b"<script>alert(1)</script>"),
                operation=self.operation,
            )
        cancellation = ManualCancellationToken()
        cancellation.cancel()
        cancelled = replace(self.operation, cancellation=cancellation)
        with self.assertRaises(DududaError):
            await self.repository.ingest_input(
                self.ingest_request(key="cancelled"),
                chunks(b"\x89PNG\r\n\x1a\ncontent"),
                operation=cancelled,
            )

    async def test_ingest_cancellation_reclaims_pending_source_task(self) -> None:
        source = BlockingChunks()
        task = asyncio.create_task(
            self.repository.ingest_input(
                self.ingest_request(key="outer-cancelled"),
                source,
                operation=self.operation,
            )
        )
        await source.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(source.cancelled.wait(), timeout=0.5)

        source = BlockingChunks()
        cancellation = ManualCancellationToken()
        operation = replace(self.operation, cancellation=cancellation)
        task = asyncio.create_task(
            self.repository.ingest_input(
                self.ingest_request(key="token-cancelled"),
                source,
                operation=operation,
            )
        )
        await source.started.wait()
        cancellation.cancel()
        with self.assertRaises(DududaError):
            await asyncio.wait_for(task, timeout=0.5)
        self.assertTrue(source.cancelled.is_set())

    async def test_delete_is_bound_idempotent_and_tombstones_ingest(self) -> None:
        ingest = self.ingest_request(key="delete-source")
        stored = await self.repository.ingest_input(
            ingest,
            chunks(b"\x89PNG\r\n\x1a\ncontent"),
            operation=self.operation,
        )
        provisional = self.authorization(
            action="attachment.delete",
            resource=DigestString("pending-resource"),
            metadata=DigestString("pending-metadata"),
        )
        command = AttachmentDeleteCommand(
            1,
            stored.content_ref,
            stored.content_digest,
            "retention_expired",
            provisional,
            "delete-key-1",
        )
        authorization = replace(
            provisional,
            resource_digest=resource_digest(
                attachment_delete_resource(
                    command,
                    scope=scope_digest(self.scope),
                )
            ),
            metadata_digest=authorization_metadata_digest(
                attachment_delete_authorization_metadata(
                    command,
                    operation_id=self.call.run_id,
                    policy_snapshot_id=self.call.policy_snapshot_id,
                )
            ),
        )
        command = replace(command, authorization=authorization)
        first = await self.repository.delete(command, call=self.call)
        duplicate = await self.repository.delete(command, call=self.call)
        self.assertEqual(first, duplicate)
        with self.assertRaises(DududaError):
            await self.repository.ingest_input(
                ingest,
                chunks(b"\x89PNG\r\n\x1a\ncontent"),
                operation=self.operation,
            )
        with self.assertRaises(DududaError):
            await self.repository.delete(
                replace(command, reason="different"),
                call=self.call,
            )


if __name__ == "__main__":
    unittest.main()
