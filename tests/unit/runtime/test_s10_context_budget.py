from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import unittest

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import (
    AttachmentKind,
    AttachmentRef,
    Mention,
    MessageEnvelope,
)
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    PrivacyLevel,
    ResourceUsage,
    RoleId,
    RuntimeBudget,
)
from dududa.errors import DududaError
from dududa.perception.contracts import PerceptionLimits
from dududa.runtime.budget import (
    RuntimeModelBudgetPlan,
    charge_budget,
    ensure_budget_covers_plan,
    reservation_budget,
)
from dududa.runtime.context import (
    CurrentMessageContextBuilder,
    CurrentMessageContextBuilderConfig,
)
from dududa.runtime.contracts import RuntimeAdmissionAction
from dududa.runtime.perception import serialize_perception_context


def revision(name: str) -> ComponentRevision:
    return ComponentRevision(
        name, "1.0.0", "config-v1", DigestString(f"artifact-{name}")
    )


def limits() -> PerceptionLimits:
    return PerceptionLimits(1, 4, 8, 2_000, 4_000, 4, 4, 8, 4)


def message(*, private: bool = False, mentioned: bool = True) -> MessageEnvelope:
    conversation_type = ConversationType.PRIVATE if private else ConversationType.GROUP
    conversation_id = "private:user-123" if private else "group-456"
    return MessageEnvelope(
        schema_version=1,
        message_id="message-789",
        platform="qq",
        bot_id="bot-123",
        conversation_type=conversation_type,
        conversation_id=conversation_id,
        group_id=None if private else conversation_id,
        user_id="user-123",
        reply_to=None,
        timestamp=datetime(2026, 8, 4, tzinfo=timezone.utc),
        text="Please explain this task.",
        mentions=(Mention("qq", "bot-123"),) if mentioned else (),
    )


def actor(value: MessageEnvelope) -> Actor:
    return Actor(
        value.platform, value.bot_id, value.user_id, frozenset({RoleId("user")})
    )


def scope(value: MessageEnvelope) -> ConversationScope:
    return ConversationScope(
        value.platform,
        value.bot_id,
        value.conversation_type,
        value.conversation_id,
        value.group_id,
        "dududa",
    )


def builder() -> CurrentMessageContextBuilder:
    return CurrentMessageContextBuilder(
        CurrentMessageContextBuilderConfig(
            1,
            limits(),
            8_000,
            PrivacyLevel.PERSONAL,
            PrivacyLevel.CONVERSATION,
            revision("current-context"),
        )
    )


class CurrentMessageContextBuilderTests(unittest.TestCase):
    def test_group_mention_builds_deidentified_context_and_runtime_binding(
        self,
    ) -> None:
        value = message()
        preprocess = builder().preprocess(value, actor(value))

        result = builder().build(value, actor(value), scope(value), preprocess)

        self.assertIs(preprocess.action, RuntimeAdmissionAction.PROCEED)
        serialized = serialize_perception_context(result.perception).decode("utf-8")
        for raw in (
            value.bot_id,
            value.user_id,
            value.conversation_id,
            value.message_id,
        ):
            self.assertNotIn(raw, serialized)
        resolved = result.resolve(result.current_author_identity_ref)
        self.assertEqual(resolved.actor_ref.opaque_actor_id, value.user_id)
        self.assertNotEqual(result.current_author_identity_ref, value.user_id)

    def test_private_is_explicit_but_unmentioned_group_is_ignored(self) -> None:
        private = message(private=True, mentioned=False)
        group = message(mentioned=False)

        self.assertIs(
            builder().preprocess(private, actor(private)).action,
            RuntimeAdmissionAction.PROCEED,
        )
        self.assertIs(
            builder().preprocess(group, actor(group)).action,
            RuntimeAdmissionAction.IGNORE,
        )

    def test_attachment_is_deferred_and_cannot_build_context(self) -> None:
        value = replace(
            message(),
            attachments=(
                AttachmentRef(
                    "attachment-1",
                    AttachmentKind.IMAGE,
                    "image/png",
                    10,
                    None,
                    None,
                ),
            ),
        )
        preprocess = builder().preprocess(value, actor(value))
        self.assertIs(preprocess.action, RuntimeAdmissionAction.DEFER)
        with self.assertRaises(DududaError):
            builder().build(value, actor(value), scope(value), preprocess)

    def test_context_token_limit_fails_closed(self) -> None:
        value = message()
        tiny = CurrentMessageContextBuilder(
            replace(builder().config, maximum_content_input_tokens=1)
        )
        preprocess = tiny.preprocess(value, actor(value))
        with self.assertRaises(DududaError):
            tiny.build(value, actor(value), scope(value), preprocess)


class RuntimeBudgetPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.perception = ResourceUsage(1, 1, 0, 1, 1_000, 200, Decimal("1"))
        self.direct = ResourceUsage(1, 1, 0, 1, 2_000, 500, Decimal("2"))
        self.plan = RuntimeModelBudgetPlan(
            1,
            self.perception,
            self.direct,
            revision("runtime-budget"),
        )
        self.total = RuntimeBudget(2, 0, 2, 3_000, 700, Decimal("3"))

    def test_plan_reserves_two_non_overlapping_model_calls(self) -> None:
        ensure_budget_covers_plan(self.total, self.plan)
        remaining = charge_budget(self.total, self.perception)
        self.assertEqual(remaining, reservation_budget(self.direct))

    def test_insufficient_or_unbounded_charge_fails_closed(self) -> None:
        with self.assertRaises(DududaError):
            ensure_budget_covers_plan(
                replace(self.total, model_calls_remaining=1), self.plan
            )
        with self.assertRaises(DududaError):
            charge_budget(
                self.total,
                replace(self.perception, cost_units=None),
            )


if __name__ == "__main__":
    unittest.main()
