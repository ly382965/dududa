from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from astrbot_plugin_dududa_core.adapters.message import AstrBotInputConnector
from dududa.adapters.attachments import InMemoryAttachmentRepository
from dududa.domain.primitives import ConversationType, RuntimeBudget, TraceContext
from dududa.errors import DududaError
from dududa.ports.context import NeverCancelled, ServiceCallContext, ServicePrincipal


class Reply:
    def __init__(self, message_id: str, group_id: str | None = None) -> None:
        self.id = message_id
        self.group_id = group_id


class At:
    def __init__(self, qq: str) -> None:
        self.qq = qq
        self.name = None


class Image:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.media_type = "image/png"
        self.size = len(content)


class BytesSource:
    async def iter_bytes(self, component: object, *, maximum_size_bytes: int):
        content = getattr(component, "content")
        yield content[:4]
        yield content[4:]


class FakeEvent:
    def __init__(
        self,
        *,
        platform: str = "qq-adapter-1",
        bot: str = "bot-1",
        user: str = "u-1",
        group: str = "g-1",
        message_id: str = "m-1",
        components: list[object] | None = None,
        raw_segments: list[dict[str, object]] | None = None,
    ) -> None:
        self._platform = platform
        self._bot = bot
        self._user = user
        self._group = group
        self.message_str = "hello"
        self.created_at = 1767225600
        components = components or []
        self.message_obj = SimpleNamespace(
            message_id=message_id,
            timestamp=1767225601,
            message=components,
            raw_message={"time": 1767225600, "message": raw_segments or []},
        )

    def get_platform_id(self):
        return self._platform

    def get_platform_name(self):
        return "aiocqhttp"

    def get_self_id(self):
        return self._bot

    def get_sender_id(self):
        return self._user

    def get_group_id(self):
        return self._group

    def get_message_type(self):
        return "group" if self._group else "private"

    def get_messages(self):
        return self.message_obj.message

    def is_admin(self):
        return False


class AstrBotConnectorContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.operation = ServiceCallContext(
            "connector.convert",
            ServicePrincipal("astrbot", "test", frozenset({"connector"})),
            "platform_input",
            TraceContext("trace-1"),
            self.now + timedelta(minutes=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal("0")),
            "policy-v1",
        )
        self.connector = AstrBotInputConnector(
            InMemoryAttachmentRepository(
                clock=lambda: self.now, id_factory=lambda: "image-1"
            ),
            attachment_source=BytesSource(),
            clock=lambda: self.now,
        )

    async def test_group_reply_mention_attachment_and_dedup(self) -> None:
        image = Image(b"\x89PNG\r\n\x1a\ncontent")
        event = FakeEvent(
            components=[Reply("m-0"), At("u-2"), image],
            raw_segments=[{"type": "image", "data": {}}],
        )
        first = await self.connector.convert(event, operation=self.operation)
        second = await self.connector.convert(event, operation=self.operation)
        message = first.message
        self.assertEqual(message.conversation_type, ConversationType.GROUP)
        self.assertEqual(message.reply_to.message_id, "m-0")  # type: ignore[union-attr]
        self.assertEqual(message.mentions[0].user_id, "u-2")
        self.assertEqual(len(message.attachments), 1)
        self.assertEqual(message.attachments, second.message.attachments)
        self.assertEqual(message.timestamp, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(
            tuple(message.dedup_key.__dict__.values())
            if hasattr(message.dedup_key, "__dict__")
            else (
                message.dedup_key.platform,
                message.dedup_key.bot_id,
                message.dedup_key.conversation_id,
                message.dedup_key.message_id,
            ),
            ("qq-adapter-1", "bot-1", "g-1", "m-1"),
        )

    async def test_private_scope_uses_user_identity(self) -> None:
        result = await self.connector.convert(
            FakeEvent(group=""), operation=self.operation
        )
        self.assertEqual(result.message.conversation_type, ConversationType.PRIVATE)
        self.assertEqual(result.message.conversation_id, "private:u-1")
        self.assertIsNone(result.message.group_id)

    async def test_missing_id_and_dropped_attachment_are_rejected(self) -> None:
        with self.assertRaises(DududaError):
            await self.connector.convert(
                FakeEvent(message_id=""), operation=self.operation
            )
        with self.assertRaises(DududaError):
            await self.connector.convert(
                FakeEvent(components=[], raw_segments=[{"type": "image", "data": {}}]),
                operation=self.operation,
            )

    async def test_cross_group_reply_is_rejected_when_source_scope_is_present(
        self,
    ) -> None:
        event = FakeEvent(components=[Reply("m-0", group_id="other-group")])
        with self.assertRaisesRegex(DududaError, "connector.message_rejected"):
            await self.connector.convert(event, operation=self.operation)

    async def test_scoped_reply_in_current_group_remains_supported(self) -> None:
        event = FakeEvent(components=[Reply("m-0", group_id="g-1")])
        result = await self.connector.convert(event, operation=self.operation)
        self.assertEqual(result.message.reply_to.message_id, "m-0")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
