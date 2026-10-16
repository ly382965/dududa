#!/usr/bin/env python3
"""Replay local NapCat group history through Dududa's deterministic policies.

The runner keeps message text and QQ identifiers in memory only. Its JSON report
contains aggregate counts and stable reason codes, never message bodies, names,
group IDs, user IDs, media URLs, or raw OneBot responses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

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
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.models.contracts import ModelRole, ModelTier
from dududa.models.digests import task_complexity_assessment_digest
from dududa.models.policy import (
    TierBudgetRequirement,
    TierPolicyDefinition,
    TierSelectionContext,
)
from dududa.models.tiering import DeterministicModelTierPolicy
from dududa.perception.complexity import (
    DeterministicComplexityAssessor,
    default_complexity_assessor_config,
)
from dududa.perception.contracts import (
    AuthorizationView,
    DecisionSignals,
    GroupInteractionMode,
    PerceptionContext,
    PerceptionIdentity,
    PerceptionLimits,
    PerceptionMessage,
    PerceptionModelStatus,
    SocialAction,
)
from dududa.perception.digests import social_decision_digest
from dududa.perception.merge import (
    DeterministicPerceptionMerger,
    PerceptionMergeConfig,
)
from dududa.perception.rules import (
    DeterministicRulePerception,
    default_rule_perception_config,
)
from dududa.perception.social import (
    DeterministicSocialDecisionPolicy,
    SocialDecisionConfig,
)
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.responses.contracts import ResponseProfileSelectionRequest
from dududa.responses.evidence import detect_detail_preference
from dududa.responses.policy import (
    DeterministicResponseProfilePolicy,
    pilot_response_profile_policy_config,
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
GROUP_LOG_MARKER = "接收 <- 群聊 "
FULL_GROUP_LOG = re.compile(
    r"^\[(?P<group>.*?)\((?P<group_id>\d+)\)\]\s+"
    r"\[(?P<sender>.*?)\((?P<sender_id>\d+)\)\](?:\s+(?P<text>.*))?$"
)
GROUP_ONLY_LOG = re.compile(r"^\[(?P<group>.*?)\((?P<group_id>\d+)\)\]$")
ATTACHMENT_MARKERS = {
    "[图片]": AttachmentKind.IMAGE,
    "[语音]": AttachmentKind.AUDIO,
    "[视频]": AttachmentKind.VIDEO,
    "[文件": AttachmentKind.FILE,
}
MEDIA_TYPES = {
    AttachmentKind.IMAGE: "image/unknown",
    AttachmentKind.AUDIO: "audio/unknown",
    AttachmentKind.VIDEO: "video/unknown",
    AttachmentKind.FILE: "application/octet-stream",
}


class ReplayError(RuntimeError):
    """A content-free local replay failure."""


@dataclass(slots=True)
class OpaqueIds:
    values: dict[tuple[str, str], str] = field(default_factory=dict)
    counts: Counter[str] = field(default_factory=Counter)

    def get(self, kind: str, raw: object) -> str:
        key = (kind, str(raw))
        existing = self.values.get(key)
        if existing is not None:
            return existing
        self.counts[kind] += 1
        value = f"{kind}-{self.counts[kind]}"
        self.values[key] = value
        return value


@dataclass(frozen=True, slots=True)
class ReplayMessage:
    source: str
    account_ref: str
    message_ref: str
    group_ref: str
    sender_ref: str
    bot_ref: str
    timestamp: datetime
    text: str
    direct_mention: bool
    replies_to_bot: bool
    self_authored: bool
    attachment_kinds: tuple[AttachmentKind, ...]


@dataclass(slots=True)
class SourceStats:
    records_seen: int = 0
    records_loaded: int = 0
    malformed_records: int = 0
    duplicate_records: int = 0
    excluded_account_records: int = 0
    pages: int = 0
    request_failures: Counter[str] = field(default_factory=Counter)
    compatibility_fallbacks: Counter[str] = field(default_factory=Counter)
    account_records: Counter[str] = field(default_factory=Counter)
    segment_types: Counter[str] = field(default_factory=Counter)
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None

    def observe_time(self, value: datetime) -> None:
        if self.first_timestamp is None or value < self.first_timestamp:
            self.first_timestamp = value
        if self.last_timestamp is None or value > self.last_timestamp:
            self.last_timestamp = value

    def report(self) -> dict[str, object]:
        return {
            "records_seen": self.records_seen,
            "records_loaded": self.records_loaded,
            "malformed_records": self.malformed_records,
            "duplicate_records": self.duplicate_records,
            "excluded_account_records": self.excluded_account_records,
            "pages": self.pages,
            "request_failures": dict(sorted(self.request_failures.items())),
            "compatibility_fallbacks": dict(
                sorted(self.compatibility_fallbacks.items())
            ),
            "account_records": dict(sorted(self.account_records.items())),
            "segment_types": dict(sorted(self.segment_types.items())),
            "first_timestamp": _timestamp(self.first_timestamp),
            "last_timestamp": _timestamp(self.last_timestamp),
        }


@dataclass(slots=True)
class ReplayStats:
    attempted: int = 0
    envelope_valid: int = 0
    perception_valid: int = 0
    complexity_valid: int = 0
    social_valid: int = 0
    tier_valid: int = 0
    response_plan_valid: int = 0
    failures: Counter[str] = field(default_factory=Counter)
    admission_skips: Counter[str] = field(default_factory=Counter)
    message_shapes: Counter[str] = field(default_factory=Counter)
    speech_acts: Counter[str] = field(default_factory=Counter)
    task_kinds: Counter[str] = field(default_factory=Counter)
    complexity_levels: Counter[str] = field(default_factory=Counter)
    social_actions: Counter[str] = field(default_factory=Counter)
    selected_tiers: Counter[str] = field(default_factory=Counter)
    answer_profiles: Counter[str] = field(default_factory=Counter)
    tier_handling: Counter[str] = field(default_factory=Counter)

    def report(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "envelope_valid": self.envelope_valid,
            "perception_valid": self.perception_valid,
            "complexity_valid": self.complexity_valid,
            "social_valid": self.social_valid,
            "tier_valid": self.tier_valid,
            "response_plan_valid": self.response_plan_valid,
            "failures": dict(sorted(self.failures.items())),
            "admission_skips": dict(sorted(self.admission_skips.items())),
            "message_shapes": dict(sorted(self.message_shapes.items())),
            "speech_acts": dict(sorted(self.speech_acts.items())),
            "task_kinds": dict(sorted(self.task_kinds.items())),
            "complexity_levels": dict(sorted(self.complexity_levels.items())),
            "social_actions": dict(sorted(self.social_actions.items())),
            "selected_tiers": dict(sorted(self.selected_tiers.items())),
            "tier_confidence_handling": dict(sorted(self.tier_handling.items())),
            "answer_profiles": dict(sorted(self.answer_profiles.items())),
        }


JsonRequest = Callable[[str], Mapping[str, object]]


def parse_log_line(
    raw_line: str,
    *,
    bot_ids: set[str],
    ids: OpaqueIds,
    sequence: int,
) -> tuple[ReplayMessage | None, str | None]:
    line = ANSI_ESCAPE.sub("", raw_line.rstrip("\n"))
    if GROUP_LOG_MARKER not in line:
        return None, None
    timestamp_text, _, remainder = line.partition(" ")
    # Docker emits nanoseconds; datetime stores microseconds. Python 3.10
    # rejects the extra digits instead of truncating them like newer versions.
    timestamp_text = re.sub(r"(\.\d{6})\d+", r"\1", timestamp_text)
    try:
        timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
    except ValueError:
        return None, "invalid_timestamp"
    tail = remainder.split(GROUP_LOG_MARKER, 1)[1]
    match = FULL_GROUP_LOG.fullmatch(tail)
    if match is None:
        group_only = GROUP_ONLY_LOG.fullmatch(tail)
        if group_only is not None:
            ids.get("group", group_only.group("group_id"))
            return None, "missing_sender_or_content"
        return None, "unrecognized_group_log"

    group_id = match.group("group_id")
    sender_id = match.group("sender_id")
    text = match.group("text") or ""
    bot_ref = "bot-napcat"
    account_ref = ids.get("log_account", _log_account_label(line))
    direct_mention = any(_mentions_account(text, bot_id) for bot_id in bot_ids)
    replies_to_bot = text.startswith("[回复消息") and any(
        f"({bot_id})" in text[:300] for bot_id in bot_ids
    )
    attachments = tuple(
        kind for marker, kind in ATTACHMENT_MARKERS.items() if marker in text
    )
    return (
        ReplayMessage(
            source="docker_logs",
            account_ref=account_ref,
            message_ref=f"log-message-{sequence}",
            group_ref=ids.get("group", group_id),
            sender_ref=ids.get("sender", sender_id),
            bot_ref=bot_ref,
            timestamp=timestamp,
            text=text,
            direct_mention=direct_mention,
            replies_to_bot=replies_to_bot,
            self_authored=sender_id in bot_ids,
            attachment_kinds=attachments,
        ),
        None,
    )


def load_docker_logs(
    container: str,
    *,
    bot_ids: set[str],
    ids: OpaqueIds,
    allowed_account_labels: set[str] | None = None,
) -> tuple[list[ReplayMessage], SourceStats]:
    stats = SourceStats()
    messages: list[ReplayMessage] = []
    try:
        process = subprocess.Popen(
            ["docker", "logs", "--timestamps", container],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise ReplayError("docker_logs_unavailable") from exc
    assert process.stdout is not None
    for line in process.stdout:
        if GROUP_LOG_MARKER not in line:
            continue
        cleaned = ANSI_ESCAPE.sub("", line)
        account_label = _log_account_label(cleaned)
        if (
            allowed_account_labels is not None
            and account_label not in allowed_account_labels
        ):
            stats.excluded_account_records += 1
            continue
        stats.records_seen += 1
        stats.account_records[ids.get("log_account", account_label)] += 1
        message, error = parse_log_line(
            line,
            bot_ids=bot_ids,
            ids=ids,
            sequence=stats.records_seen,
        )
        if error is not None:
            stats.malformed_records += 1
            stats.request_failures[error] += 1
            continue
        assert message is not None
        messages.append(message)
        stats.records_loaded += 1
        stats.observe_time(message.timestamp)
    return_code = process.wait()
    if return_code != 0:
        raise ReplayError("docker_logs_failed")
    return messages, stats


def load_gateway_history(
    base_url: str,
    *,
    ids: OpaqueIds,
    allowed_bot_ids: set[str] | None = None,
    request_json: JsonRequest | None = None,
) -> tuple[list[ReplayMessage], SourceStats, set[str], set[str], int]:
    fetch = request_json or _request_json
    stats = SourceStats()
    messages: list[ReplayMessage] = []
    bot_ids: set[str] = set()
    account_labels: set[str] = set()
    workspace = fetch(f"{base_url.rstrip('/')}/api/workspace?refresh=1")
    accounts = _mapping_sequence(workspace.get("accounts"))
    conversations = _mapping_sequence(workspace.get("conversations"))
    bot_id_by_account: dict[str, str] = {}
    for account in accounts:
        account_id = account.get("id")
        if isinstance(account_id, str) and account_id:
            bot_id = account.get("botId")
            if not isinstance(bot_id, str) or not bot_id:
                bot_id = account_id.removeprefix("qq-")
            if allowed_bot_ids is not None and bot_id not in allowed_bot_ids:
                continue
            bot_ids.add(bot_id)
            bot_id_by_account[account_id] = bot_id
            label = account.get("name")
            if isinstance(label, str) and label.strip():
                account_labels.add(label.strip())
    group_conversations = [
        item
        for item in conversations
        if item.get("type") == "group"
        and isinstance(item.get("accountId"), str)
        and isinstance(item.get("peerId"), str)
        and item.get("accountId") in bot_id_by_account
    ]

    for conversation in group_conversations:
        account_id = str(conversation["accountId"])
        peer_id = str(conversation["peerId"])
        account_ref = ids.get("gateway_account", account_id)
        seen: set[tuple[str, str]] = set()
        seen_cursors: set[str] = set()
        before: str | None = None
        history_mode = "normal"
        while True:
            query = "limit=100"
            if before is not None:
                cursor_name = "before" if history_mode == "normal" else "after"
                query += f"&{cursor_name}=" + urllib.parse.quote(before, safe="")
            path = (
                f"{base_url.rstrip('/')}/api/accounts/"
                f"{urllib.parse.quote(account_id, safe='')}/conversations/group/"
                f"{urllib.parse.quote(peer_id, safe='')}/messages?{query}"
            )
            try:
                page = fetch(path)
            except (OSError, ReplayError, urllib.error.URLError) as exc:
                stats.request_failures[f"history_request:{type(exc).__name__}"] += 1
                break
            stats.pages += 1
            raw_messages = _mapping_sequence(page.get("messages"))
            page_keys = {
                (account_id, str(raw.get("messageId")))
                for raw in raw_messages
                if isinstance(raw.get("messageId"), str) and raw.get("messageId")
            }
            overlap = len(page_keys & seen)
            if (
                before is not None
                and history_mode == "normal"
                and page_keys
                and overlap * 10 >= len(page_keys) * 9
            ):
                history_mode = "legacy_reversed_direction"
                stats.compatibility_fallbacks["reversed_history_direction"] += 1
                continue
            for raw in raw_messages:
                stats.records_seen += 1
                stats.account_records[account_ref] += 1
                message_id = raw.get("messageId")
                if not isinstance(message_id, str) or not message_id:
                    stats.malformed_records += 1
                    stats.request_failures["gateway_missing_message_id"] += 1
                    continue
                key = (account_id, message_id)
                if key in seen:
                    stats.duplicate_records += 1
                    continue
                seen.add(key)
                try:
                    message = _gateway_message(
                        raw,
                        account_id=account_id,
                        bot_id=bot_id_by_account.get(
                            account_id, account_id.removeprefix("qq-")
                        ),
                        peer_id=peer_id,
                        account_ref=account_ref,
                        ids=ids,
                        sequence=stats.records_seen,
                        segment_types=stats.segment_types,
                    )
                except (TypeError, ValueError):
                    stats.malformed_records += 1
                    stats.request_failures["invalid_gateway_message"] += 1
                    continue
                messages.append(message)
                stats.records_loaded += 1
                stats.observe_time(message.timestamp)
            has_more_field = (
                "hasMoreBefore" if history_mode == "normal" else "hasMoreAfter"
            )
            if page.get(has_more_field) is not True:
                break
            cursor = page.get("beforeCursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                stats.request_failures["gateway_cursor_stalled"] += 1
                break
            seen_cursors.add(cursor)
            before = cursor
    return messages, stats, bot_ids, account_labels, len(group_conversations)


def _gateway_message(
    raw: Mapping[str, object],
    *,
    account_id: str,
    bot_id: str,
    peer_id: str,
    account_ref: str,
    ids: OpaqueIds,
    sequence: int,
    segment_types: Counter[str],
) -> ReplayMessage:
    sender_id = _required_string(raw.get("senderId"))
    text = raw.get("content")
    if not isinstance(text, str):
        raise TypeError("invalid_gateway_content")
    timestamp_ms = raw.get("timestampMs")
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, (int, float)):
        raise TypeError("invalid_gateway_timestamp")
    timestamp = datetime.fromtimestamp(float(timestamp_ms) / 1000, timezone.utc)
    direct_mention = False
    replies_to_bot = False
    attachment_kinds: list[AttachmentKind] = []
    for segment in _mapping_sequence(raw.get("segments")):
        segment_type = segment.get("type")
        if not isinstance(segment_type, str):
            segment_types["invalid"] += 1
            continue
        segment_types[segment_type] += 1
        if segment_type == "mention" and segment.get("userId") == bot_id:
            direct_mention = True
        if segment_type == "reply" and segment.get("senderId") == bot_id:
            replies_to_bot = True
        kind = {
            "image": AttachmentKind.IMAGE,
            "audio": AttachmentKind.AUDIO,
            "video": AttachmentKind.VIDEO,
            "file": AttachmentKind.FILE,
        }.get(segment_type)
        if kind is not None:
            attachment_kinds.append(kind)
    return ReplayMessage(
        source="gateway_history",
        account_ref=account_ref,
        message_ref=f"gateway-message-{sequence}",
        group_ref=ids.get("group", peer_id),
        sender_ref=ids.get("sender", sender_id),
        bot_ref=ids.get("bot", bot_id),
        timestamp=timestamp,
        text=text,
        direct_mention=direct_mention,
        replies_to_bot=replies_to_bot,
        self_authored=raw.get("mine") is True,
        attachment_kinds=tuple(attachment_kinds),
    )


class ReplayPipeline:
    def __init__(self) -> None:
        self._now = datetime.now(timezone.utc)
        self._revisions = {
            name: _revision(name)
            for name in (
                "real-replay-rules",
                "real-replay-pipeline",
                "real-replay-merger",
                "real-replay-validator",
                "real-replay-complexity",
                "real-replay-detail",
                "real-replay-response",
            )
        }
        self._rules = DeterministicRulePerception(
            default_rule_perception_config(self._revisions["real-replay-rules"]),
            id_factory=lambda: "real-replay-rule-result",
        )
        self._merger = DeterministicPerceptionMerger(
            PerceptionMergeConfig(
                self._revisions["real-replay-pipeline"],
                self._revisions["real-replay-merger"],
                self._revisions["real-replay-validator"],
                0.59,
                0.59,
            ),
            id_factory=lambda: "real-replay-perception-result",
        )
        self._complexity = DeterministicComplexityAssessor(
            default_complexity_assessor_config(
                self._revisions["real-replay-complexity"]
            ),
            id_factory=lambda: "real-replay-complexity-result",
        )
        self._tier = DeterministicModelTierPolicy(
            id_factory=lambda: "real-replay-tier-decision"
        )
        self._tier_definition = _tier_definition()
        self._social = DeterministicSocialDecisionPolicy(
            SocialDecisionConfig("real-replay-social-v1", 0.6),
            clock=lambda: self._now,
            id_factory=lambda: "real-replay-social-decision",
        )
        self._responses = DeterministicResponseProfilePolicy(
            pilot_response_profile_policy_config(
                self._revisions["real-replay-response"]
            ),
            id_factory=lambda: "real-replay-response-plan",
        )

    async def replay(self, messages: Iterable[ReplayMessage]) -> ReplayStats:
        stats = ReplayStats()
        for message in messages:
            stats.attempted += 1
            self._now = message.timestamp
            try:
                envelope = self._envelope(message)
                stats.envelope_valid += 1
                self._count_shape(message, stats)
            except (DududaError, TypeError, ValueError) as exc:
                stats.failures[f"envelope:{_error_code(exc)}"] += 1
                continue
            if message.self_authored:
                stats.admission_skips["self_authored"] += 1
                continue
            try:
                context = self._context(message, envelope)
                rules = self._rules.perceive(context)
                perception = self._merger.merge(
                    context,
                    rules,
                    None,
                    model_status=PerceptionModelStatus.UNAVAILABLE,
                )
                stats.perception_valid += 1
                stats.task_kinds[perception.task_kind] += 1
                for speech_act in perception.speech_acts:
                    stats.speech_acts[speech_act.value] += 1
            except (DududaError, TypeError, ValueError) as exc:
                stats.failures[f"perception:{_error_code(exc)}"] += 1
                continue
            try:
                assessment = self._complexity.assess(context, perception)
                stats.complexity_valid += 1
                stats.complexity_levels[assessment.level.value] += 1
            except (DududaError, TypeError, ValueError) as exc:
                stats.failures[f"complexity:{_error_code(exc)}"] += 1
                continue
            try:
                social = await self._social.decide(
                    perception,
                    DecisionSignals(
                        1,
                        AuthorizationView(1, True, False, ("private_replay",)),
                        message.self_authored,
                        perception.should_consider_response,
                        False,
                        GroupInteractionMode.NORMAL,
                        False,
                        False,
                        False,
                        bool(perception.target_identity_refs),
                    ),
                    call=self._call(message),
                )
                stats.social_valid += 1
                stats.social_actions[social.action.value] += 1
            except (DududaError, TypeError, ValueError) as exc:
                stats.failures[f"social:{_error_code(exc)}"] += 1
                continue
            try:
                tier = self._tier.decide(
                    TierSelectionContext(
                        1,
                        f"selection-{message.message_ref}",
                        ModelRole.DIRECT_CHAT,
                        assessment,
                        context.content_input_tokens_upper_bound,
                        PrivacyLevel.CONVERSATION,
                        _budget(),
                    ),
                    self._tier_definition,
                    now=message.timestamp,
                )
                stats.tier_valid += 1
                stats.selected_tiers[tier.selected_tier.value] += 1
                stats.tier_handling[tier.confidence_handling.value] += 1
            except (DududaError, TypeError, ValueError) as exc:
                stats.failures[f"tier:{_error_code(exc)}"] += 1
                continue
            if social.action not in {
                SocialAction.DIRECT_REPLY,
                SocialAction.USE_TOOLS,
                SocialAction.ASK_CLARIFICATION,
            }:
                continue
            try:
                plan = self._responses.select(
                    ResponseProfileSelectionRequest(
                        1,
                        f"response-{message.message_ref}",
                        DigestString(f"actor:{message.sender_ref}"),
                        context.scope_digest,
                        "dududa",
                        ConversationType.GROUP,
                        context.current_message_ref,
                        assessment.level,
                        assessment.reasoning_depth,
                        assessment.expected_tool_steps,
                        assessment.verification_required,
                        social.action,
                        task_complexity_assessment_digest(assessment),
                        social_decision_digest(social),
                        detect_detail_preference(
                            context.current_message_ref,
                            message.text,
                            detector_revision=self._revisions["real-replay-detail"],
                        ),
                        None,
                        2_000,
                        3_000,
                        6,
                    ),
                    now=message.timestamp,
                )
                stats.response_plan_valid += 1
                stats.answer_profiles[plan.selected_profile.value] += 1
            except (DududaError, TypeError, ValueError) as exc:
                stats.failures[f"response:{_error_code(exc)}"] += 1
        return stats

    def _envelope(self, message: ReplayMessage) -> MessageEnvelope:
        attachments = tuple(
            AttachmentRef(
                attachment_id=f"{message.message_ref}-attachment-{index}",
                kind=kind,
                media_type=MEDIA_TYPES[kind],
                size_bytes=None,
                content_ref=None,
                content_digest=None,
            )
            for index, kind in enumerate(message.attachment_kinds, start=1)
        )
        mentions = (
            (Mention("napcat-private-replay", message.bot_ref, "bot"),)
            if message.direct_mention
            else ()
        )
        return MessageEnvelope(
            schema_version=1,
            message_id=message.message_ref,
            platform="napcat-private-replay",
            bot_id=message.bot_ref,
            conversation_type=ConversationType.GROUP,
            conversation_id=message.group_ref,
            group_id=message.group_ref,
            user_id=message.sender_ref,
            reply_to=None,
            timestamp=message.timestamp,
            text=message.text,
            attachments=attachments,
            mentions=mentions,
            metadata={"source": message.source, "private_replay": True},
        )

    def _context(
        self,
        message: ReplayMessage,
        envelope: MessageEnvelope,
    ) -> PerceptionContext:
        bot_identity = "identity:bot"
        author_identity = (
            bot_identity if message.self_authored else "identity:current-user"
        )
        identities = [PerceptionIdentity(1, bot_identity, True)]
        if author_identity != bot_identity:
            identities.append(PerceptionIdentity(1, author_identity, False))
        prior: list[PerceptionMessage] = []
        reply_ref = None
        if message.replies_to_bot:
            reply_ref = "message:replied-bot"
            prior.append(
                PerceptionMessage(
                    1,
                    reply_ref,
                    bot_identity,
                    "quoted bot message",
                    None,
                    (),
                    True,
                )
            )
        current_ref = f"message:{message.message_ref}"
        prior.append(
            PerceptionMessage(
                1,
                current_ref,
                author_identity,
                envelope.text,
                reply_ref,
                (bot_identity,) if message.direct_mention else (),
                message.self_authored,
            )
        )
        return PerceptionContext(
            1,
            f"context:{message.message_ref}",
            DigestString(f"scope:{message.group_ref}"),
            ConversationType.GROUP,
            tuple(identities),
            tuple(prior),
            current_ref,
            bot_identity,
            PerceptionLimits(1, 2, 2, 8_000, 16_000, 8, 8, 16, 8),
            (),
            (),
            max(1, len(envelope.text)),
            PrivacyLevel.CONVERSATION,
        )

    def _call(self, message: ReplayMessage) -> PortCallContext:
        return PortCallContext(
            run_id=f"run-{message.message_ref}",
            trace=TraceContext(f"trace-{message.message_ref}"),
            deadline=message.timestamp + timedelta(seconds=30),
            cancellation=NeverCancelled(),
            budget=_budget(),
            policy_snapshot_id="real-replay-policy-v1",
        )

    @staticmethod
    def _count_shape(message: ReplayMessage, stats: ReplayStats) -> None:
        stats.message_shapes["empty" if not message.text else "text"] += 1
        if message.direct_mention:
            stats.message_shapes["direct_mention"] += 1
        if message.replies_to_bot:
            stats.message_shapes["reply_to_bot"] += 1
        if message.self_authored:
            stats.message_shapes["self_authored"] += 1
        for kind in message.attachment_kinds:
            stats.message_shapes[f"attachment_{kind.value}"] += 1


def build_report(
    *,
    docker_stats: SourceStats,
    gateway_stats: SourceStats,
    replay_stats: ReplayStats,
    ids: OpaqueIds,
    gateway_group_count: int,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "dataset_kind": "private_real_group_replay",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "docker_logs": docker_stats.report(),
            "gateway_history": {
                **gateway_stats.report(),
                "group_conversations": gateway_group_count,
            },
        },
        "opaque_cardinality": {
            "groups": ids.counts["group"],
            "senders": ids.counts["sender"],
            "bots": ids.counts["bot"],
            "log_accounts": ids.counts["log_account"],
            "gateway_accounts": ids.counts["gateway_account"],
        },
        "replay": replay_stats.report(),
        "interpretation": {
            "accuracy_claim": False,
            "raw_content_persisted": False,
            "raw_identifiers_persisted": False,
            "messages_sent": False,
            "models_called": False,
            "limitations": [
                "Docker logs are a lossy presentation format and may overlap gateway history.",
                "NapCat cannot guarantee QQ history that was never synchronized locally.",
                "No human labels are present, so distributions are not quality metrics.",
                "Rule fallback has no model perception and therefore cannot validate intent/entity accuracy.",
                "The corpus has no Bandit action set, propensity, or attributable reward.",
            ],
        },
    }


def write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _request_json(url: str) -> Mapping[str, object]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise ReplayError("gateway_request_failed") from exc
    if not isinstance(value, dict):
        raise ReplayError("gateway_response_not_object")
    return value


def _mapping_sequence(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError("required_string")
    return value


def _mentions_account(text: str, account_id: str) -> bool:
    location = text.find(f"({account_id})")
    if location < 0:
        return False
    return "@" in text[max(0, location - 100) : location]


def _log_account_label(line: str) -> str:
    prefix = line.split(f" | {GROUP_LOG_MARKER}", 1)[0]
    label = prefix.rsplit("] ", 1)[-1].strip()
    return label or "unknown"


def _revision(name: str) -> ComponentRevision:
    return ComponentRevision(
        name,
        "1.0.0",
        "private-replay-v1",
        DigestString(f"artifact:{name}"),
    )


def _budget() -> RuntimeBudget:
    return RuntimeBudget(1, 0, 0, 8_000, 2_000, Decimal(8))


def _tier_definition() -> TierPolicyDefinition:
    return TierPolicyDefinition(
        1,
        "real-replay-direct-chat-tier",
        ModelRole.DIRECT_CHAT,
        frozenset({ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS}),
        ModelTier.SONNET,
        ModelTier.HAIKU,
        ModelTier.OPUS,
        0.6,
        0.85,
        2,
        frozenset(
            {
                "deep_reasoning",
                "multi_constraint_synthesis",
                "independent_verification",
                "multi_step_tool_plan",
                "cross_artifact_analysis",
            }
        ),
        (
            TierBudgetRequirement(1, ModelTier.HAIKU, 1_000, 256, Decimal("0.1")),
            TierBudgetRequirement(1, ModelTier.SONNET, 2_000, 512, Decimal(1)),
            TierBudgetRequirement(1, ModelTier.OPUS, 4_000, 1_024, Decimal(4)),
        ),
        "real-replay-tier-policy-v1",
    )


def _error_code(error: Exception) -> str:
    info = getattr(error, "info", None)
    code = getattr(info, "code", None)
    return str(code) if isinstance(code, str) and code else type(error).__name__


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--container",
        default="mmdustc-bot-astrbot-qq-napcat-1",
        help="running NapCat container whose existing logs are replayed",
    )
    parser.add_argument(
        "--gateway",
        default="http://127.0.0.1:5173",
        help="local Dududa Web gateway used for paginated structured history",
    )
    parser.add_argument(
        "--account-id",
        default=os.environ.get("DUDUDA_REPLAY_ACCOUNT_ID"),
        help=(
            "only replay this explicitly approved QQ Bot account; may also be "
            "set with DUDUDA_REPLAY_ACCOUNT_ID"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(".TreeWork/out/napcat-real-replay-report.json"),
    )
    parser.add_argument("--skip-docker-logs", action="store_true")
    parser.add_argument("--skip-gateway", action="store_true")
    parser.add_argument(
        "--log-account-label",
        action="append",
        default=(
            [os.environ["DUDUDA_REPLAY_ACCOUNT_LABEL"]]
            if os.environ.get("DUDUDA_REPLAY_ACCOUNT_LABEL")
            else []
        ),
        help=(
            "only replay this approved NapCat account label; may also be set "
            "with DUDUDA_REPLAY_ACCOUNT_LABEL"
        ),
    )
    args = parser.parse_args()
    if not args.account_id:
        parser.error("--account-id or DUDUDA_REPLAY_ACCOUNT_ID is required")
    if not args.skip_docker_logs and not args.log_account_label:
        parser.error(
            "--log-account-label or DUDUDA_REPLAY_ACCOUNT_LABEL is required "
            "when Docker logs are enabled"
        )
    return args


def main() -> int:
    args = parse_args()
    ids = OpaqueIds()
    bot_ids = {args.account_id}
    gateway_messages: list[ReplayMessage] = []
    gateway_stats = SourceStats()
    gateway_groups = 0
    if not args.skip_gateway:
        try:
            (
                gateway_messages,
                gateway_stats,
                connected_ids,
                _gateway_account_labels,
                gateway_groups,
            ) = load_gateway_history(
                args.gateway,
                ids=ids,
                allowed_bot_ids={args.account_id},
            )
            bot_ids.update(connected_ids)
        except (OSError, ReplayError, urllib.error.URLError) as exc:
            gateway_stats.request_failures[f"workspace:{type(exc).__name__}"] += 1
    docker_messages: list[ReplayMessage] = []
    docker_stats = SourceStats()
    if not args.skip_docker_logs:
        try:
            docker_messages, docker_stats = load_docker_logs(
                args.container,
                bot_ids=bot_ids,
                ids=ids,
                allowed_account_labels=set(args.log_account_label),
            )
        except ReplayError as exc:
            docker_stats.request_failures[str(exc)] += 1
    replay_stats = asyncio.run(
        ReplayPipeline().replay((*docker_messages, *gateway_messages))
    )
    report = build_report(
        docker_stats=docker_stats,
        gateway_stats=gateway_stats,
        replay_stats=replay_stats,
        ids=ids,
        gateway_group_count=gateway_groups,
    )
    write_report(args.report, report)
    print(
        "napcat replay complete: "
        f"source_records={docker_stats.records_seen + gateway_stats.records_seen} "
        f"replayed={replay_stats.attempted} "
        f"failures={sum(replay_stats.failures.values())} "
        f"report={args.report}"
    )
    return 0 if replay_stats.attempted > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
