from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
import re
import uuid

from dududa.domain.primitives import ComponentRevision, ConversationType
from dududa.domain.task import TaskReasoningDepth
from dududa.errors import validation_error

from .contracts import (
    ComplexitySignal,
    ComplexitySignalCode,
    EvidenceSource,
    PerceptionContext,
    RulePerceptionResult,
    SpeechAct,
)
from .digests import perception_context_digest


_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_LIST_RE = re.compile(r"(?m)^\s*(?:[-*]|\d+[.)])\s+")


@dataclass(frozen=True, slots=True)
class RulePerceptionConfig:
    revision: ComponentRevision
    question_prefixes: tuple[str, ...]
    greeting_tokens: frozenset[str]
    transformation_tokens: frozenset[str]
    comparison_tokens: frozenset[str]
    verification_tokens: frozenset[str]
    deep_reasoning_tokens: frozenset[str]
    constraint_markers: frozenset[str]
    capability_keywords: Mapping[str, frozenset[str]] = field(default_factory=dict)
    multi_constraint_threshold: int = 3
    multi_tool_step_threshold: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.revision, ComponentRevision):
            raise ValueError("invalid Rule Perception revision")
        if (
            type(self.multi_constraint_threshold) is not int
            or self.multi_constraint_threshold < 2
            or type(self.multi_tool_step_threshold) is not int
            or self.multi_tool_step_threshold < 2
        ):
            raise ValueError("invalid Rule Perception thresholds")
        object.__setattr__(
            self,
            "question_prefixes",
            _normalized_tuple(self.question_prefixes, "question_prefixes"),
        )
        for name in (
            "greeting_tokens",
            "transformation_tokens",
            "comparison_tokens",
            "verification_tokens",
            "deep_reasoning_tokens",
            "constraint_markers",
        ):
            object.__setattr__(
                self,
                name,
                _normalized_set(getattr(self, name), name),
            )
        capability_keywords: dict[str, frozenset[str]] = {}
        for category, keywords in self.capability_keywords.items():
            normalized_category = category.strip().casefold()
            if not normalized_category or normalized_category in capability_keywords:
                raise ValueError("invalid capability keyword category")
            capability_keywords[normalized_category] = _normalized_set(
                keywords,
                "capability_keywords",
            )
        object.__setattr__(
            self,
            "capability_keywords",
            MappingProxyType(capability_keywords),
        )


def default_rule_perception_config(
    revision: ComponentRevision,
) -> RulePerceptionConfig:
    return RulePerceptionConfig(
        revision=revision,
        question_prefixes=(
            "what",
            "why",
            "how",
            "when",
            "where",
            "who",
            "can",
            "could",
            "would",
            "should",
            "is",
            "are",
            "do",
            "does",
            "\u4ec0\u4e48",
            "\u4e3a\u4ec0\u4e48",
            "\u600e\u4e48",
            "\u5982\u4f55",
            "\u80fd\u5426",
            "\u53ef\u4ee5",
            "\u8bf7\u95ee",
        ),
        greeting_tokens=frozenset(
            {
                "hi",
                "hello",
                "hey",
                "\u4f60\u597d",
                "\u65e9\u4e0a\u597d",
                "\u665a\u4e0a\u597d",
            }
        ),
        transformation_tokens=frozenset(
            {
                "rewrite",
                "rephrase",
                "translate",
                "summarize",
                "format",
                "\u6539\u5199",
                "\u7ffb\u8bd1",
                "\u603b\u7ed3",
                "\u683c\u5f0f\u5316",
                "\u6da6\u8272",
            }
        ),
        comparison_tokens=frozenset(
            {
                "compare",
                "tradeoff",
                "pros and cons",
                "difference",
                "\u6bd4\u8f83",
                "\u5bf9\u6bd4",
                "\u53d6\u820d",
                "\u533a\u522b",
            }
        ),
        verification_tokens=frozenset(
            {
                "verify",
                "validate",
                "prove",
                "cross-check",
                "citation",
                "test",
                "\u9a8c\u8bc1",
                "\u8bc1\u660e",
                "\u4ea4\u53c9\u68c0\u67e5",
                "\u5f15\u7528",
                "\u6d4b\u8bd5",
            }
        ),
        deep_reasoning_tokens=frozenset(
            {
                "formal proof",
                "root cause",
                "architecture",
                "threat model",
                "counterexample",
                "\u5f62\u5f0f\u5316\u8bc1\u660e",
                "\u6839\u56e0",
                "\u67b6\u6784",
                "\u5a01\u80c1\u5efa\u6a21",
                "\u53cd\u4f8b",
            }
        ),
        constraint_markers=frozenset(
            {
                "must",
                "should",
                "cannot",
                "without",
                "at least",
                "at most",
                "require",
                "constraint",
                "\u5fc5\u987b",
                "\u9700\u8981",
                "\u4e0d\u80fd",
                "\u81f3\u5c11",
                "\u81f3\u591a",
                "\u7ea6\u675f",
            }
        ),
        capability_keywords={},
    )


class DeterministicRulePerception:
    def __init__(
        self,
        config: RulePerceptionConfig,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, RulePerceptionConfig):
            raise ValueError("invalid Rule Perception config")
        self._config = config
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def perceive(self, context: PerceptionContext) -> RulePerceptionResult:
        if not isinstance(context, PerceptionContext):
            raise validation_error("invalid_perception_context")
        current = context.current_message
        text = current.text.strip()
        normalized = text.casefold()
        message_ref = current.message_ref
        prior_by_ref = {
            message.message_ref: message for message in context.messages[:-1]
        }

        direct_mention = context.bot_identity_ref in current.mentioned_identity_refs
        replied = (
            prior_by_ref.get(current.reply_to_message_ref)
            if current.reply_to_message_ref is not None
            else None
        )
        replies_to_bot = replied is not None and replied.is_bot_authored
        explicit_command = normalized.startswith("/")
        explicit_question = _is_question(normalized, self._config.question_prefixes)
        private_direct = context.conversation_type is ConversationType.PRIVATE
        should_consider = (
            private_direct or direct_mention or replies_to_bot or explicit_command
        )

        speech_acts: set[SpeechAct] = set()
        if explicit_command:
            speech_acts.add(SpeechAct.COMMAND_LIKE)
        if explicit_question:
            speech_acts.update({SpeechAct.QUESTION, SpeechAct.REQUEST})
        elif text:
            speech_acts.add(SpeechAct.STATEMENT)
        if _is_greeting(normalized, self._config.greeting_tokens):
            speech_acts.add(SpeechAct.GREETING)

        code_blocks = normalized.count("```") // 2
        urls = tuple(_URL_RE.findall(text))
        list_items = len(_LIST_RE.findall(text))
        constraint_count = sum(
            _token_count(normalized, marker)
            for marker in self._config.constraint_markers
        )
        shape_signals: set[str] = set()
        if code_blocks:
            shape_signals.add("code_block")
        if urls:
            shape_signals.add("url")
        if list_items:
            shape_signals.add("list_structure")
        if constraint_count >= self._config.multi_constraint_threshold:
            shape_signals.add("multi_constraint")

        available = set(context.available_capability_categories)
        capability_categories = tuple(
            sorted(
                category
                for category, keywords in self._config.capability_keywords.items()
                if category in available and _matches_token(normalized, keywords)
            )
        )
        need_tools = bool(capability_categories)
        expected_tool_steps = len(capability_categories)
        verification_required = _matches_token(
            normalized,
            self._config.verification_tokens,
        )
        task_kind = _task_kind(
            normalized=normalized,
            explicit_command=explicit_command,
            explicit_question=explicit_question,
            code_blocks=code_blocks,
            constraint_count=constraint_count,
            config=self._config,
        )
        reasoning_depth = _reasoning_depth(
            normalized=normalized,
            code_blocks=code_blocks,
            list_items=list_items,
            constraint_count=constraint_count,
            need_tools=need_tools,
            config=self._config,
        )
        signals = _complexity_signals(
            message_ref=message_ref,
            normalized=normalized,
            task_kind=task_kind,
            reasoning_depth=reasoning_depth,
            verification_required=verification_required,
            expected_tool_steps=expected_tool_steps,
            artifact_count=code_blocks + len(urls),
            constraint_count=constraint_count,
            config=self._config,
        )
        targets = (current.author_identity_ref,) if should_consider else ()
        confidence = 0.95 if should_consider or explicit_question else 0.8
        return RulePerceptionResult(
            schema_version=1,
            result_id=self._id_factory(),
            context_digest=perception_context_digest(context),
            direct_mention=direct_mention,
            replies_to_bot=replies_to_bot,
            explicit_question=explicit_question,
            explicit_command=explicit_command,
            should_consider_response=should_consider,
            target_identity_refs=targets,
            speech_acts=tuple(speech_acts),
            need_tools=need_tools,
            capability_categories=capability_categories,
            shape_signals=tuple(shape_signals),
            task_kind=task_kind,
            reasoning_depth=reasoning_depth,
            expected_tool_steps=expected_tool_steps,
            verification_required=verification_required,
            complexity_signals=signals,
            confidence=confidence,
            component_revision=self._config.revision,
        )


def _is_question(text: str, prefixes: tuple[str, ...]) -> bool:
    if not text:
        return False
    if text.endswith(("?", "\uff1f")):
        return True
    return any(
        text == prefix
        or text.startswith(f"{prefix} ")
        or (not prefix.isascii() and text.startswith(prefix))
        for prefix in prefixes
    )


def _task_kind(
    *,
    normalized: str,
    explicit_command: bool,
    explicit_question: bool,
    code_blocks: int,
    constraint_count: int,
    config: RulePerceptionConfig,
) -> str:
    if explicit_command:
        return "explicit_command"
    if _is_greeting(normalized, config.greeting_tokens):
        return "greeting"
    if _matches_token(normalized, config.transformation_tokens):
        return "bounded_transformation"
    if code_blocks:
        return "code_analysis"
    if constraint_count >= config.multi_constraint_threshold:
        return "multi_constraint_analysis"
    if _matches_token(normalized, config.comparison_tokens):
        return "comparison"
    if explicit_question:
        return "simple_retrieval"
    return "direct_chat"


def _reasoning_depth(
    *,
    normalized: str,
    code_blocks: int,
    list_items: int,
    constraint_count: int,
    need_tools: bool,
    config: RulePerceptionConfig,
) -> TaskReasoningDepth:
    if (
        _matches_token(normalized, config.deep_reasoning_tokens)
        or constraint_count >= config.multi_constraint_threshold
    ):
        return TaskReasoningDepth.DEEP
    if (
        code_blocks
        or list_items >= 2
        or need_tools
        or _matches_token(normalized, config.comparison_tokens)
    ):
        return TaskReasoningDepth.MULTI_STEP
    return TaskReasoningDepth.SHALLOW


def _complexity_signals(
    *,
    message_ref: str,
    normalized: str,
    task_kind: str,
    reasoning_depth: TaskReasoningDepth,
    verification_required: bool,
    expected_tool_steps: int,
    artifact_count: int,
    constraint_count: int,
    config: RulePerceptionConfig,
) -> tuple[ComplexitySignal, ...]:
    codes: set[ComplexitySignalCode] = set()
    if task_kind == "simple_retrieval":
        codes.add(ComplexitySignalCode.SIMPLE_RETRIEVAL)
    elif task_kind == "bounded_transformation":
        codes.add(ComplexitySignalCode.BOUNDED_TRANSFORMATION)
    elif task_kind == "greeting":
        codes.add(ComplexitySignalCode.SHALLOW_CONVERSATION)
    if reasoning_depth is TaskReasoningDepth.DEEP:
        codes.add(ComplexitySignalCode.DEEP_REASONING)
    if constraint_count >= config.multi_constraint_threshold:
        codes.add(ComplexitySignalCode.MULTI_CONSTRAINT_SYNTHESIS)
    if verification_required:
        codes.add(ComplexitySignalCode.INDEPENDENT_VERIFICATION)
    if expected_tool_steps >= config.multi_tool_step_threshold:
        codes.add(ComplexitySignalCode.MULTI_STEP_TOOL_PLAN)
    if artifact_count >= 2:
        codes.add(ComplexitySignalCode.CROSS_ARTIFACT_ANALYSIS)
    high_codes = {
        ComplexitySignalCode.DEEP_REASONING,
        ComplexitySignalCode.MULTI_CONSTRAINT_SYNTHESIS,
        ComplexitySignalCode.INDEPENDENT_VERIFICATION,
        ComplexitySignalCode.MULTI_STEP_TOOL_PLAN,
        ComplexitySignalCode.CROSS_ARTIFACT_ANALYSIS,
    }
    if codes & high_codes:
        codes -= {
            ComplexitySignalCode.SIMPLE_RETRIEVAL,
            ComplexitySignalCode.BOUNDED_TRANSFORMATION,
            ComplexitySignalCode.SHALLOW_CONVERSATION,
        }
    return tuple(
        ComplexitySignal(
            schema_version=1,
            code=code,
            source=EvidenceSource.RULE,
            confidence=1.0,
            evidence_refs=(message_ref,),
        )
        for code in sorted(codes, key=lambda item: item.value)
    )


def _matches_token(text: str, tokens: frozenset[str]) -> bool:
    return any(_token_count(text, token) > 0 for token in tokens)


def _token_count(text: str, token: str) -> int:
    if token.isascii() and token[0].isalnum() and token[-1].isalnum():
        return len(re.findall(rf"(?<!\w){re.escape(token)}(?!\w)", text))
    return text.count(token)


def _is_greeting(text: str, tokens: frozenset[str]) -> bool:
    normalized = text.strip().strip(".!?,;:\uff01\uff1f\u3002\uff0c\uff1b\uff1a")
    return any(
        normalized == token or normalized.startswith(f"{token} ") for token in tokens
    )


def _normalized_set(values: object, field_name: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"invalid {field_name}")
    normalized = frozenset(
        value.strip().casefold()
        for value in values  # type: ignore[union-attr]
        if isinstance(value, str) and value.strip()
    )
    if not normalized:
        raise ValueError(f"empty {field_name}")
    return normalized


def _normalized_tuple(values: object, field_name: str) -> tuple[str, ...]:
    normalized = _normalized_set(values, field_name)
    return tuple(sorted(normalized))
