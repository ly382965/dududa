from __future__ import annotations

from datetime import datetime, timezone
import unittest

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import MessageEnvelope, MessageReference
from dududa.domain.primitives import ConversationType, DenyFlag, RoleId
from dududa.errors import DududaError


class IdentityMessageTests(unittest.TestCase):
    def test_group_message_builds_four_part_dedup_key(self) -> None:
        message = MessageEnvelope(
            schema_version=1,
            message_id="m-1",
            platform="qq",
            bot_id="bot-1",
            conversation_type=ConversationType.GROUP,
            conversation_id="g-1",
            group_id="g-1",
            user_id="u-1",
            reply_to=None,
            timestamp=datetime.now(timezone.utc),
            text="hello",
            metadata={"nested": {"allowed": True}},
        )
        self.assertEqual(
            (
                message.dedup_key.platform,
                message.dedup_key.bot_id,
                message.dedup_key.conversation_id,
                message.dedup_key.message_id,
            ),
            ("qq", "bot-1", "g-1", "m-1"),
        )

    def test_invalid_scope_and_cross_conversation_reply_fail_closed(self) -> None:
        with self.assertRaises(DududaError):
            ConversationScope(
                platform="qq",
                bot_id="bot-1",
                conversation_type=ConversationType.PRIVATE,
                conversation_id="private",
                group_id="g-1",
                persona_id="dududa",
            )
        with self.assertRaises(DududaError):
            MessageEnvelope(
                schema_version=1,
                message_id="m-1",
                platform="qq",
                bot_id="bot-1",
                conversation_type=ConversationType.GROUP,
                conversation_id="g-1",
                group_id="g-1",
                user_id="u-1",
                reply_to=MessageReference("qq", "bot-1", "g-2", "m-0"),
                timestamp=datetime.now(timezone.utc),
                text="hello",
            )

    def test_actor_requires_stable_identity(self) -> None:
        actor = Actor(
            platform="qq",
            bot_id="bot-1",
            user_id="u-1",
            roles=frozenset({RoleId("normal")}),
            deny_flags=frozenset({DenyFlag("muted")}),
        )
        self.assertIn(DenyFlag("muted"), actor.deny_flags)
        with self.assertRaises(DududaError):
            Actor("qq", "bot-1", "", frozenset())

    def test_collections_are_defensively_frozen_and_raw_enums_are_rejected(
        self,
    ) -> None:
        roles = {RoleId("normal")}
        actor = Actor("qq", "bot-1", "u-1", roles)
        roles.add(RoleId("owner"))
        self.assertEqual(actor.roles, frozenset({RoleId("normal")}))
        with self.assertRaises(DududaError):
            MessageEnvelope(
                1,
                "m-1",
                "qq",
                "bot-1",
                "group",  # type: ignore[arg-type]
                "g-1",
                None,
                "u-1",
                None,
                datetime.now(timezone.utc),
                "hello",
            )


if __name__ == "__main__":
    unittest.main()
