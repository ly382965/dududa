from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dududa.domain.identity import Actor
from dududa.domain.message import Mention, MessageEnvelope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    RoleId,
)
from dududa.rollout import RolloutControlConfig, RolloutMode
from dududa.rollout.ledger import (
    SQLiteJournalMode,
    SQLiteRolloutLedger,
    SQLiteRolloutLedgerConfig,
)
from dududa.runtime.state import ConnectorResult


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def revision(name: str) -> ComponentRevision:
    return ComponentRevision(name, "1.0.0", "cfg-v1", DigestString(f"artifact:{name}"))


def connector(
    *,
    group_id: str | None = "g-1",
    mentioned_user: str | None = "bot-1",
    text: str = "hello",
    attachments: tuple[object, ...] = (),
) -> ConnectorResult:
    conversation_type = (
        ConversationType.GROUP if group_id is not None else ConversationType.PRIVATE
    )
    conversation_id = group_id or "private:u-1"
    message = MessageEnvelope(
        schema_version=1,
        message_id="m-1",
        platform="qq",
        bot_id="bot-1",
        conversation_type=conversation_type,
        conversation_id=conversation_id,
        group_id=group_id,
        user_id="u-1",
        reply_to=None,
        timestamp=NOW,
        text=text,
        attachments=attachments,
        mentions=(Mention("qq", mentioned_user),) if mentioned_user else (),
    )
    actor = Actor("qq", "bot-1", "u-1", frozenset({RoleId("user")}))
    return ConnectorResult(1, message, actor, NOW, revision("connector"))


def control(mode: RolloutMode = RolloutMode.CANARY, **changes: object):
    value = RolloutControlConfig(
        schema_version=1,
        mode=mode,
        revision="rollout-v1",
        delivery_enabled=True,
        allowlisted_group_ids=frozenset({"g-1"}),
        kill_switch=False,
        tools_enabled=False,
        memory_enabled=False,
        maximum_text_bytes=1_024,
        shadow_max_in_flight=2,
        shadow_timeout=timedelta(seconds=2),
        canary_timeout=timedelta(seconds=5),
    )
    return replace(value, **changes)


def ledger(
    path: Path,
    *,
    clock=lambda: NOW,
    journal_mode: SQLiteJournalMode = SQLiteJournalMode.DELETE,
) -> SQLiteRolloutLedger:
    return SQLiteRolloutLedger(
        SQLiteRolloutLedgerConfig(
            1,
            path,
            timedelta(seconds=2),
            timedelta(days=30),
            1_000,
            revision("rollout-ledger"),
            journal_mode,
        ),
        clock=clock,
    )
