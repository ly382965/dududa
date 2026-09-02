"""Pure, deterministic policy assets for the optional Dududa social plugin.

The PR #10 prototype put these rules in the Core ``ALL`` event chain.  This
module deliberately has no AstrBot imports and no I/O: callers can evaluate a
signal first and let the Dududa Runtime decide whether an explicit command or
an authorised output should be produced.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from enum import Enum
from json import dumps

MAX_ID_LENGTH = 128
MAX_TOPIC_LENGTH = 160
MAX_TEXT_LENGTH = 4_000
MAX_SLEEP_LOGS = 366


def _bounded_id(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise SocialPolicyError(f"invalid_{field_name}")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_ID_LENGTH
        or any(ord(char) < 32 for char in normalized)
    ):
        raise SocialPolicyError(f"invalid_{field_name}")
    return normalized


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise SocialPolicyError(f"invalid_{field_name}")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(
            ord(char) < 32 and char not in "\n\t" for char in normalized
        )
    ):
        raise SocialPolicyError(f"invalid_{field_name}")
    return normalized


class SocialPolicyError(ValueError):
    """A caller supplied an invalid social command or state value."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class SocialFeature(str, Enum):
    BIRTHDAY = "birthday"
    SLEEP = "sleep"
    VOTE = "vote"
    CP = "cp"
    MOOD = "mood"
    COMPLIMENT = "compliment"
    KEYWORD = "keyword"


class MoodSeverity(str, Enum):
    NONE = "none"
    SUPPORT = "support"
    ELEVATED = "elevated"
    CRISIS = "crisis"


class ComplimentTarget(str, Enum):
    NONE = "none"
    BOT = "bot"
    OTHER = "other"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class SocialScope:
    """The minimum identity tuple used to isolate social state."""

    platform: str
    bot_id: str
    conversation_id: str
    group_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("platform", "bot_id", "conversation_id"):
            value = _bounded_id(getattr(self, name), name)
            object.__setattr__(self, name, value)
        if self.group_id is not None:
            object.__setattr__(self, "group_id", _bounded_id(self.group_id, "group_id"))

    @property
    def is_group(self) -> bool:
        return self.group_id is not None

    @property
    def key(self) -> str:
        """Collision-free, stable storage key (not a display identifier)."""

        return dumps(
            [self.platform, self.bot_id, self.conversation_id, self.group_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class SocialPolicyConfig:
    """Feature gates for the optional plugin.

    Empty ``allowed_groups`` is intentionally deny-by-default.  The Core
    Runtime remains the owner of model/tool/proactive decisions; these flags
    only decide whether an explicit adapter operation may inspect state.
    """

    enabled: bool = False
    allowed_groups: frozenset[str] = field(default_factory=frozenset)
    allow_private: bool = False
    enabled_features: frozenset[SocialFeature] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or type(self.allow_private) is not bool:
            raise SocialPolicyError("invalid_policy_flags")
        groups = frozenset(_bounded_id(value, "allowed_group") for value in self.allowed_groups)
        features: set[SocialFeature] = set()
        for value in self.enabled_features:
            try:
                features.add(value if isinstance(value, SocialFeature) else SocialFeature(str(value)))
            except ValueError as exc:
                raise SocialPolicyError("invalid_feature") from exc
        object.__setattr__(self, "allowed_groups", groups)
        object.__setattr__(self, "enabled_features", frozenset(features))

    def allows(self, scope: SocialScope, feature: SocialFeature) -> bool:
        if not self.enabled or feature not in self.enabled_features:
            return False
        if scope.is_group:
            return scope.group_id in self.allowed_groups
        return self.allow_private

    def allows_scope(self, scope: SocialScope) -> bool:
        """Return whether the explicit command surface is enabled for a Scope."""

        if not isinstance(scope, SocialScope) or not self.enabled:
            return False
        if scope.is_group:
            return scope.group_id in self.allowed_groups
        return self.allow_private


def parse_birthday(value: object) -> str | None:
    """Parse ``MMDD`` (or a separator variant) into a canonical ``MM-DD``.

    A three-digit input such as ``315`` is interpreted as ``03-15``.  Years
    are intentionally not accepted because this feature stores recurring
    month/day values.  ``date(2000, ...)`` validates leap day without making
    the result depend on the current year.
    """

    if not isinstance(value, str):
        return None
    digits = re.sub(r"\D", "", value.strip())
    if len(digits) == 3:
        digits = "0" + digits
    if len(digits) != 4:
        return None
    month, day = int(digits[:2]), int(digits[2:])
    try:
        date(2000, month, day)
    except ValueError:
        return None
    return f"{month:02d}-{day:02d}"


def birthday_matches(
    records: Mapping[str, str],
    month_day: str | date,
) -> tuple[str, ...]:
    """Return users whose stored birthday matches a month/day value."""

    target = (
        month_day.strftime("%m-%d")
        if isinstance(month_day, date)
        else parse_birthday(month_day)
    )
    if target is None:
        return ()
    result = [user_id for user_id, value in records.items() if parse_birthday(value) == target]
    return tuple(sorted({_bounded_id(user_id, "user_id") for user_id in result}))


@dataclass(frozen=True, slots=True)
class SleepLog:
    user_id: str
    local_date: date
    local_time: time

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _bounded_id(self.user_id, "user_id"))
        if not isinstance(self.local_date, date) or not isinstance(self.local_time, time):
            raise SocialPolicyError("invalid_sleep_log")

    @property
    def minutes(self) -> int:
        return self.local_time.hour * 60 + self.local_time.minute


@dataclass(frozen=True, slots=True)
class SleepSummary:
    user_id: str
    count: int
    average_minutes: float
    latest: time

    @property
    def average_time(self) -> time:
        # Values before noon are treated as the continuation of the previous
        # night (e.g. 01:00 becomes 25:00) while rendering wraps to 24h.
        minute = round(self.average_minutes) % (24 * 60)
        return time(minute // 60, minute % 60)


def make_sleep_log(user_id: str, at: datetime) -> SleepLog:
    if not isinstance(at, datetime):
        raise SocialPolicyError("invalid_sleep_timestamp")
    if at.tzinfo is None or at.utcoffset() is None:
        raise SocialPolicyError("naive_sleep_timestamp")
    return SleepLog(user_id, at.date(), at.timetz().replace(tzinfo=None))


def append_sleep_log(
    logs: Sequence[SleepLog],
    entry: SleepLog,
    *,
    maximum_logs: int = MAX_SLEEP_LOGS,
) -> tuple[tuple[SleepLog, ...], bool]:
    """Append one daily sleep marker; return ``(logs, recorded)``.

    A user can contribute at most one marker per local date.  The bounded
    tail keeps this optional feature from growing without limit.
    """

    if not isinstance(entry, SleepLog):
        raise SocialPolicyError("invalid_sleep_log")
    if type(maximum_logs) is not int or not 1 <= maximum_logs <= 10_000:
        raise SocialPolicyError("invalid_sleep_log_limit")
    if any(item.user_id == entry.user_id and item.local_date == entry.local_date for item in logs):
        return tuple(logs), False
    values = tuple(logs) + (entry,)
    return values[-maximum_logs:], True


def aggregate_sleep(logs: Iterable[SleepLog]) -> tuple[SleepSummary, ...]:
    """Aggregate sleep markers and rank later average bedtimes first."""

    grouped: dict[str, list[SleepLog]] = defaultdict(list)
    for item in logs:
        if not isinstance(item, SleepLog):
            raise SocialPolicyError("invalid_sleep_log")
        grouped[item.user_id].append(item)

    summaries: list[SleepSummary] = []
    for user_id, values in grouped.items():
        normalized = [item.minutes + (24 * 60 if item.minutes < 12 * 60 else 0) for item in values]
        summaries.append(
            SleepSummary(
                user_id=user_id,
                count=len(values),
                average_minutes=sum(normalized) / len(normalized),
                latest=max(values, key=lambda item: (item.local_date, item.local_time)).local_time,
            )
        )
    return tuple(
        sorted(
            summaries,
            key=lambda item: (-item.average_minutes, item.user_id),
        )
    )


@dataclass(frozen=True, slots=True)
class VoteState:
    topic: str
    creator_id: str
    participants: frozenset[str] = field(default_factory=frozenset)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        topic = _bounded_text(self.topic, "vote_topic", MAX_TOPIC_LENGTH)
        creator = _bounded_id(self.creator_id, "creator_id")
        if (
            not isinstance(self.started_at, datetime)
            or self.started_at.tzinfo is None
            or self.started_at.utcoffset() is None
        ):
            raise SocialPolicyError("naive_vote_timestamp")
        participants = frozenset(_bounded_id(value, "participant_id") for value in self.participants)
        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "creator_id", creator)
        object.__setattr__(self, "participants", participants)


@dataclass(frozen=True, slots=True)
class VoteTransition:
    action: str
    state: VoteState | None
    changed: bool


def apply_vote_action(
    state: VoteState | None,
    action: str,
    actor_id: str,
    *,
    topic: str | None = None,
    is_admin: bool = False,
    now: datetime | None = None,
) -> VoteTransition:
    """Apply one explicit vote command with creator/admin end authority."""

    actor = _bounded_id(actor_id, "actor_id")
    normalized = str(action or "").strip().casefold()
    if normalized in {"result", "结束"}:
        normalized = "end"
    if normalized in {"查看", "list", "show"}:
        normalized = "status"
    if normalized not in {"start", "join", "end", "status"}:
        raise SocialPolicyError("unknown_vote_action")
    if type(is_admin) is not bool:
        raise SocialPolicyError("invalid_admin_flag")

    if normalized == "start":
        if state is not None:
            raise SocialPolicyError("vote_already_active")
        started_at = now or datetime.now(timezone.utc)
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise SocialPolicyError("naive_vote_timestamp")
        if topic is None:
            raise SocialPolicyError("vote_topic_required")
        created = VoteState(str(topic), actor, frozenset(), started_at)
        return VoteTransition("start", created, True)

    if state is None:
        raise SocialPolicyError("vote_not_active")
    if normalized == "join":
        if actor in state.participants:
            return VoteTransition("join", state, False)
        updated = VoteState(
            state.topic,
            state.creator_id,
            state.participants | {actor},
            state.started_at,
        )
        return VoteTransition("join", updated, True)
    if normalized == "end":
        if actor != state.creator_id and not is_admin:
            raise SocialPolicyError("vote_end_forbidden")
        return VoteTransition("end", None, True)
    return VoteTransition("status", state, False)


@dataclass(frozen=True, order=True, slots=True)
class UserPair:
    first: str
    second: str

    def __post_init__(self) -> None:
        first = _bounded_id(self.first, "pair_user")
        second = _bounded_id(self.second, "pair_user")
        if first == second:
            raise SocialPolicyError("self_interaction_not_pair")
        if first > second:
            first, second = second, first
        object.__setattr__(self, "first", first)
        object.__setattr__(self, "second", second)

    @property
    def storage_key(self) -> str:
        return dumps([self.first, self.second], ensure_ascii=False, separators=(",", ":"))


def canonical_pair(first: str, second: str) -> UserPair:
    return UserPair(first, second)


def record_interaction(
    counts: Mapping[UserPair, int],
    first: str,
    second: str,
) -> tuple[dict[UserPair, int], UserPair, int]:
    pair = canonical_pair(first, second)
    current = counts.get(pair, 0)
    if type(current) is not int or current < 0:
        raise SocialPolicyError("invalid_pair_count")
    updated = dict(counts)
    updated[pair] = current + 1
    return updated, pair, current + 1


def rank_interactions(counts: Mapping[UserPair, int], limit: int = 10) -> tuple[tuple[UserPair, int], ...]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise SocialPolicyError("invalid_pair_limit")
    rows = []
    for pair, count in counts.items():
        if not isinstance(pair, UserPair) or type(count) is not int or count < 0:
            raise SocialPolicyError("invalid_pair_count")
        rows.append((pair, count))
    rows.sort(key=lambda item: (-item[1], item[0].first, item[0].second))
    return tuple(rows[:limit])


_CRISIS_TERMS = (
    "不想活了",
    "不想活",
    "想自杀",
    "自杀",
    "自残",
    "结束生命",
    "轻生",
)
_ELEVATED_TERMS = (
    "崩溃",
    "抑郁",
    "焦虑",
    "被孤立",
    "压力好大",
    "撑不住了",
    "想放弃",
    "失眠",
)
_SUPPORT_TERMS = (
    "emo",
    "难受",
    "好累",
    "想哭",
    "没意思",
    "烦死了",
    "好孤单",
    "没人理",
    "自闭了",
)


@dataclass(frozen=True, slots=True)
class MoodSignal:
    severity: MoodSeverity
    matched_terms: tuple[str, ...]

    @property
    def requires_human_support(self) -> bool:
        return self.severity is MoodSeverity.CRISIS


def classify_mood(text: object) -> MoodSignal:
    if not isinstance(text, str):
        return MoodSignal(MoodSeverity.NONE, ())
    normalized = re.sub(r"\s+", "", text.casefold())[:MAX_TEXT_LENGTH]
    for severity, terms in (
        (MoodSeverity.CRISIS, _CRISIS_TERMS),
        (MoodSeverity.ELEVATED, _ELEVATED_TERMS),
        (MoodSeverity.SUPPORT, _SUPPORT_TERMS),
    ):
        matched = tuple(sorted({term for term in terms if term.casefold() in normalized}, key=lambda item: (-len(item), item)))
        if matched:
            return MoodSignal(severity, matched)
    return MoodSignal(MoodSeverity.NONE, ())


_PRAISE_TERMS = (
    "太可爱",
    "好可爱",
    "好厉害",
    "太厉害",
    "漂亮",
    "好看",
    "优秀",
    "天才",
    "神仙",
    "yyds",
    "牛逼",
    "牛批",
    "靠谱",
    "贴心",
    "谢谢",
    "感谢",
    "喜欢",
    "可爱",
    "厉害",
    "聪明",
    "棒",
    "赞",
)
_BOT_TARGET_TERMS = ("嘟嘟哒", "机器人", "bot")
_OTHER_TARGET_TERMS = ("他", "她", "老师", "学长", "学姐", "同学", "室友", "朋友", "老板")


@dataclass(frozen=True, slots=True)
class ComplimentSignal:
    is_compliment: bool
    target: ComplimentTarget
    matched_terms: tuple[str, ...]


def classify_compliment(text: object, *, bot_mentioned: bool = False) -> ComplimentSignal:
    if not isinstance(text, str):
        return ComplimentSignal(False, ComplimentTarget.NONE, ())
    if type(bot_mentioned) is not bool:
        raise SocialPolicyError("invalid_bot_mention_flag")
    normalized = re.sub(r"\s+", "", text.casefold())[:MAX_TEXT_LENGTH]
    matched = tuple(sorted({term for term in _PRAISE_TERMS if term.casefold() in normalized}, key=lambda item: (-len(item), item)))
    if not matched:
        return ComplimentSignal(False, ComplimentTarget.NONE, ())
    bot_target = bot_mentioned or any(term in normalized for term in _BOT_TARGET_TERMS)
    other_target = any(term in normalized for term in _OTHER_TARGET_TERMS)
    if bot_target and other_target:
        target = ComplimentTarget.AMBIGUOUS
    elif bot_target:
        target = ComplimentTarget.BOT
    elif other_target:
        target = ComplimentTarget.OTHER
    else:
        target = ComplimentTarget.NONE
    return ComplimentSignal(True, target, matched)


@dataclass(frozen=True, slots=True)
class KeywordRule:
    keyword: str
    response: str
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "keyword", _bounded_text(self.keyword, "keyword", 64))
        object.__setattr__(self, "response", _bounded_text(self.response, "keyword_response", 256))
        if type(self.enabled) is not bool:
            raise SocialPolicyError("invalid_keyword_flag")


# Multi-character rules preserve the useful part of PR #10 without enabling
# its highly collision-prone one-character ``区``/``猪`` triggers by default.
DEFAULT_KEYWORD_RULES: tuple[KeywordRule, ...] = (
    KeywordRule("朋友", "xm朋友"),
    KeywordRule("学长", "xm学长"),
    KeywordRule("学姐", "xm学姐"),
    KeywordRule("没课", "xm没课"),
    KeywordRule("翘课", "xm翘课"),
    KeywordRule("没早八", "xm"),
    KeywordRule("区", "？！区区？！", enabled=False),
    KeywordRule("猪", "？！猪猪？！", enabled=False),
)


@dataclass(frozen=True, slots=True)
class KeywordMatch:
    keyword: str
    response: str


def match_keyword(
    text: object,
    rules: Sequence[KeywordRule] = DEFAULT_KEYWORD_RULES,
) -> KeywordMatch | None:
    if not isinstance(text, str):
        return None
    normalized = re.sub(r"\s+", "", text)[:MAX_TEXT_LENGTH]
    candidates = [rule for rule in rules if isinstance(rule, KeywordRule) and rule.enabled and rule.keyword in normalized]
    if not candidates:
        return None
    # Longest match wins; declaration order breaks ties deterministically.
    selected = max(enumerate(candidates), key=lambda item: (len(item[1].keyword), -item[0]))[1]
    return KeywordMatch(selected.keyword, selected.response)


__all__ = [
    "DEFAULT_KEYWORD_RULES",
    "MAX_SLEEP_LOGS",
    "ComplimentSignal",
    "ComplimentTarget",
    "KeywordMatch",
    "KeywordRule",
    "MoodSeverity",
    "MoodSignal",
    "SleepLog",
    "SleepSummary",
    "SocialFeature",
    "SocialPolicyConfig",
    "SocialPolicyError",
    "SocialScope",
    "UserPair",
    "VoteState",
    "VoteTransition",
    "aggregate_sleep",
    "append_sleep_log",
    "apply_vote_action",
    "birthday_matches",
    "canonical_pair",
    "classify_compliment",
    "classify_mood",
    "make_sleep_log",
    "match_keyword",
    "parse_birthday",
    "rank_interactions",
    "record_interaction",
]
