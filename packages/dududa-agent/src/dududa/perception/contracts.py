from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from dududa._compat import StrEnum
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    PrivacyLevel,
    ResponseConstraints,
    require_aware,
    require_non_empty,
)
from dududa.domain.task import TaskReasoningDepth
from dududa.errors import validation_error

_REFERENCE_MAX_LENGTH = 128
_LABEL_MAX_LENGTH = 256
_ENTITY_VALUE_MAX_LENGTH = 512
_MAX_EXPECTED_TOOL_STEPS = 64
_MAX_CANDIDATES_PER_KIND = 64


class SpeechAct(StrEnum):
    QUESTION = "question"
    REQUEST = "request"
    STATEMENT = "statement"
    CORRECTION = "correction"
    GREETING = "greeting"
    EMOTION = "emotion"
    COMMAND_LIKE = "command_like"


class EntityKind(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    DATETIME = "datetime"
    ARTIFACT = "artifact"
    CODE_SYMBOL = "code_symbol"
    CAPABILITY = "capability"
    OTHER = "other"


class ReferenceKind(StrEnum):
    IDENTITY = "identity"
    MESSAGE = "message"
    TOPIC = "topic"
    UNRESOLVED = "unresolved"


class AmbiguityKind(StrEnum):
    TARGET = "target"
    REFERENCE = "reference"
    SCOPE = "scope"
    TASK = "task"
    TOOL_INPUT = "tool_input"


class ClarificationKey(StrEnum):
    TARGET = "clarify.target"
    REFERENCE = "clarify.reference"
    SCOPE = "clarify.scope"
    TASK = "clarify.task"
    TOOL_INPUT = "clarify.tool_input"


class EvidenceSource(StrEnum):
    RULE = "rule"
    MODEL = "model"


class ComplexitySignalCode(StrEnum):
    SIMPLE_RETRIEVAL = "simple_retrieval"
    BOUNDED_TRANSFORMATION = "bounded_transformation"
    SHALLOW_CONVERSATION = "shallow_conversation"
    DEEP_REASONING = "deep_reasoning"
    MULTI_CONSTRAINT_SYNTHESIS = "multi_constraint_synthesis"
    INDEPENDENT_VERIFICATION = "independent_verification"
    MULTI_STEP_TOOL_PLAN = "multi_step_tool_plan"
    CROSS_ARTIFACT_ANALYSIS = "cross_artifact_analysis"


class PerceptionModelStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    VALID = "valid"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class SocialAction(StrEnum):
    IGNORE = "ignore"
    REACT = "react"
    DIRECT_REPLY = "direct_reply"
    USE_TOOLS = "use_tools"
    ASK_CLARIFICATION = "ask_clarification"
    DEFER = "defer"


class GroupInteractionMode(StrEnum):
    QUIET = "quiet"
    NORMAL = "normal"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class PerceptionLimits:
    schema_version: int
    max_messages: int
    max_identities: int
    max_characters_per_message: int
    max_total_characters: int
    max_capability_categories: int
    max_degraded_components: int
    max_candidates_per_kind: int
    max_evidence_refs_per_item: int

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        hard_limits = {
            "max_messages": 64,
            "max_identities": 128,
            "max_characters_per_message": 8_000,
            "max_total_characters": 64_000,
            "max_capability_categories": 64,
            "max_degraded_components": 64,
            "max_candidates_per_kind": 64,
            "max_evidence_refs_per_item": 16,
        }
        for field_name, hard_limit in hard_limits.items():
            value = getattr(self, field_name)
            _positive_int(value, field_name)
            if value > hard_limit:
                raise validation_error(
                    "perception_limit_exceeds_hard_ceiling", field_name
                )
        if self.max_total_characters < self.max_characters_per_message:
            raise validation_error("invalid_perception_character_limits")


@dataclass(frozen=True, slots=True)
class PerceptionIdentity:
    schema_version: int
    identity_ref: str
    is_bot: bool

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.identity_ref, "identity_ref", _REFERENCE_MAX_LENGTH)
        if type(self.is_bot) is not bool:
            raise validation_error("invalid_perception_identity_bot_flag")


@dataclass(frozen=True, slots=True)
class PerceptionMessage:
    schema_version: int
    message_ref: str
    author_identity_ref: str
    text: str
    reply_to_message_ref: str | None
    mentioned_identity_refs: tuple[str, ...] = ()
    is_bot_authored: bool = False

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.message_ref, "message_ref", _REFERENCE_MAX_LENGTH)
        _bounded_string(
            self.author_identity_ref,
            "author_identity_ref",
            _REFERENCE_MAX_LENGTH,
        )
        if not isinstance(self.text, str):
            raise validation_error("invalid_perception_message_text")
        if self.reply_to_message_ref is not None:
            _bounded_string(
                self.reply_to_message_ref,
                "reply_to_message_ref",
                _REFERENCE_MAX_LENGTH,
            )
        if type(self.is_bot_authored) is not bool:
            raise validation_error("invalid_bot_authored_flag")
        object.__setattr__(
            self,
            "mentioned_identity_refs",
            _unique_strings(
                self.mentioned_identity_refs,
                "mentioned_identity_refs",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class PerceptionContext:
    schema_version: int
    context_id: str
    scope_digest: DigestString
    conversation_type: ConversationType
    identities: tuple[PerceptionIdentity, ...]
    messages: tuple[PerceptionMessage, ...]
    current_message_ref: str
    bot_identity_ref: str
    limits: PerceptionLimits
    available_capability_categories: tuple[str, ...]
    degraded_components: tuple[str, ...]
    content_input_tokens_upper_bound: int
    data_classification: PrivacyLevel

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(
            self.context_id,
            "perception_context_id",
            _REFERENCE_MAX_LENGTH,
        )
        require_non_empty(str(self.scope_digest), "scope_digest")
        _bounded_string(
            self.current_message_ref,
            "current_message_ref",
            _REFERENCE_MAX_LENGTH,
        )
        _bounded_string(
            self.bot_identity_ref,
            "bot_identity_ref",
            _REFERENCE_MAX_LENGTH,
        )
        _enum(self.conversation_type, ConversationType, "conversation_type")
        _enum(self.data_classification, PrivacyLevel, "data_classification")
        if not isinstance(self.limits, PerceptionLimits):
            raise validation_error("invalid_perception_limits")
        _positive_int(
            self.content_input_tokens_upper_bound,
            "content_input_tokens_upper_bound",
        )

        identities = tuple(self.identities)
        if not identities or not all(
            isinstance(identity, PerceptionIdentity) for identity in identities
        ):
            raise validation_error("invalid_perception_identities")
        if len(identities) > self.limits.max_identities:
            raise validation_error("too_many_perception_identities")
        identity_refs = tuple(identity.identity_ref for identity in identities)
        _unique(identity_refs, "identity_ref")
        identities = tuple(sorted(identities, key=lambda item: item.identity_ref))
        identity_by_ref = {item.identity_ref: item for item in identities}
        bot_identity = identity_by_ref.get(self.bot_identity_ref)
        if bot_identity is None or not bot_identity.is_bot:
            raise validation_error("unknown_perception_bot_identity")
        if sum(identity.is_bot for identity in identities) != 1:
            raise validation_error("perception_requires_one_bot_identity")

        messages = tuple(self.messages)
        if not messages or not all(
            isinstance(message, PerceptionMessage) for message in messages
        ):
            raise validation_error("invalid_perception_messages")
        if len(messages) > self.limits.max_messages:
            raise validation_error("too_many_perception_messages")
        message_refs = tuple(message.message_ref for message in messages)
        _unique(message_refs, "message_ref")
        if messages[-1].message_ref != self.current_message_ref:
            raise validation_error("current_perception_message_not_terminal")
        known_messages: set[str] = set()
        total_characters = 0
        for message in messages:
            identity = identity_by_ref.get(message.author_identity_ref)
            if identity is None:
                raise validation_error("unknown_message_author_identity")
            if message.is_bot_authored is not (
                message.author_identity_ref == self.bot_identity_ref
            ):
                raise validation_error("bot_authorship_identity_mismatch")
            if len(message.text) > self.limits.max_characters_per_message:
                raise validation_error("perception_message_too_long")
            total_characters += len(message.text)
            if any(
                reference not in identity_by_ref
                for reference in message.mentioned_identity_refs
            ):
                raise validation_error("unknown_mentioned_identity")
            if (
                message.reply_to_message_ref is not None
                and message.reply_to_message_ref not in known_messages
            ):
                raise validation_error("unknown_or_forward_reply_reference")
            known_messages.add(message.message_ref)
        if total_characters > self.limits.max_total_characters:
            raise validation_error("perception_context_too_long")

        object.__setattr__(self, "identities", identities)
        object.__setattr__(self, "messages", messages)
        object.__setattr__(
            self,
            "available_capability_categories",
            _unique_strings(
                self.available_capability_categories,
                "available_capability_categories",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
            ),
        )
        if (
            len(self.available_capability_categories)
            > self.limits.max_capability_categories
        ):
            raise validation_error("too_many_capability_categories")
        object.__setattr__(
            self,
            "degraded_components",
            _unique_strings(
                self.degraded_components,
                "degraded_components",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=self.limits.max_degraded_components,
            ),
        )

    @property
    def current_message(self) -> PerceptionMessage:
        return self.messages[-1]


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    schema_version: int
    topic_id: str
    label: str
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.topic_id, "topic_id", _REFERENCE_MAX_LENGTH)
        _bounded_string(self.label, "topic_label", _LABEL_MAX_LENGTH)
        _rate(self.confidence, "topic_confidence")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(
                self.evidence_refs,
                "topic_evidence_refs",
                required=True,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=16,
            ),
        )


@dataclass(frozen=True, slots=True)
class IntentCandidate:
    schema_version: int
    intent_id: str
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.intent_id, "intent_id", _REFERENCE_MAX_LENGTH)
        _rate(self.confidence, "intent_confidence")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(
                self.evidence_refs,
                "intent_evidence_refs",
                required=True,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=16,
            ),
        )


@dataclass(frozen=True, slots=True)
class EntityCandidate:
    schema_version: int
    entity_id: str
    kind: EntityKind
    value: str
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.entity_id, "entity_id", _REFERENCE_MAX_LENGTH)
        _bounded_string(self.value, "entity_value", _ENTITY_VALUE_MAX_LENGTH)
        _enum(self.kind, EntityKind, "entity_kind")
        _rate(self.confidence, "entity_confidence")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(
                self.evidence_refs,
                "entity_evidence_refs",
                required=True,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=16,
            ),
        )


@dataclass(frozen=True, slots=True)
class ReferenceCandidate:
    schema_version: int
    reference_id: str
    kind: ReferenceKind
    target_ref: str | None
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.reference_id, "reference_id", _REFERENCE_MAX_LENGTH)
        _enum(self.kind, ReferenceKind, "reference_kind")
        if self.kind is ReferenceKind.UNRESOLVED:
            if self.target_ref is not None:
                raise validation_error("unresolved_reference_has_target")
        elif self.target_ref is None:
            raise validation_error("resolved_reference_has_no_target")
        else:
            _bounded_string(
                self.target_ref,
                "reference_target",
                _REFERENCE_MAX_LENGTH,
            )
        _rate(self.confidence, "reference_confidence")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(
                self.evidence_refs,
                "reference_evidence_refs",
                required=True,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=16,
            ),
        )


@dataclass(frozen=True, slots=True)
class AmbiguityCandidate:
    schema_version: int
    ambiguity_id: str
    kind: AmbiguityKind
    clarification_key: ClarificationKey | None
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _bounded_string(self.ambiguity_id, "ambiguity_id", _REFERENCE_MAX_LENGTH)
        _enum(self.kind, AmbiguityKind, "ambiguity_kind")
        if self.clarification_key is not None:
            _enum(
                self.clarification_key,
                ClarificationKey,
                "clarification_key",
            )
        _rate(self.confidence, "ambiguity_confidence")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(
                self.evidence_refs,
                "ambiguity_evidence_refs",
                required=True,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=16,
            ),
        )


@dataclass(frozen=True, slots=True)
class ComplexitySignal:
    schema_version: int
    code: ComplexitySignalCode
    source: EvidenceSource
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _enum(self.code, ComplexitySignalCode, "complexity_signal_code")
        _enum(self.source, EvidenceSource, "complexity_signal_source")
        _rate(self.confidence, "complexity_signal_confidence")
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(
                self.evidence_refs,
                "complexity_signal_evidence_refs",
                required=True,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=16,
            ),
        )


@dataclass(frozen=True, slots=True)
class RulePerceptionResult:
    schema_version: int
    result_id: str
    context_digest: DigestString
    direct_mention: bool
    replies_to_bot: bool
    explicit_question: bool
    explicit_command: bool
    should_consider_response: bool
    target_identity_refs: tuple[str, ...]
    speech_acts: tuple[SpeechAct, ...]
    need_tools: bool
    capability_categories: tuple[str, ...]
    shape_signals: tuple[str, ...]
    task_kind: str
    reasoning_depth: TaskReasoningDepth
    expected_tool_steps: int
    verification_required: bool
    complexity_signals: tuple[ComplexitySignal, ...]
    confidence: float
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.result_id, "rule_perception_result_id")
        require_non_empty(str(self.context_digest), "context_digest")
        _bounded_string(self.task_kind, "rule_task_kind", _REFERENCE_MAX_LENGTH)
        for name in (
            "direct_mention",
            "replies_to_bot",
            "explicit_question",
            "explicit_command",
            "should_consider_response",
            "need_tools",
            "verification_required",
        ):
            if type(getattr(self, name)) is not bool:
                raise validation_error("invalid_rule_perception_flag", name)
        _enum(self.reasoning_depth, TaskReasoningDepth, "reasoning_depth")
        _bounded_nonnegative_int(
            self.expected_tool_steps,
            "expected_tool_steps",
            _MAX_EXPECTED_TOOL_STEPS,
        )
        _rate(self.confidence, "rule_perception_confidence")
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_rule_component_revision")
        object.__setattr__(
            self,
            "target_identity_refs",
            _unique_strings(
                self.target_identity_refs,
                "target_identity_refs",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=128,
            ),
        )
        object.__setattr__(
            self,
            "speech_acts",
            _enum_tuple(self.speech_acts, SpeechAct, "speech_acts"),
        )
        object.__setattr__(
            self,
            "capability_categories",
            _unique_strings(
                self.capability_categories,
                "capability_categories",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=64,
            ),
        )
        if self.need_tools:
            if self.expected_tool_steps < 1:
                raise validation_error("rule_tool_need_has_zero_expected_steps")
        elif self.capability_categories or self.expected_tool_steps:
            raise validation_error("rule_tool_free_has_tool_details")
        object.__setattr__(
            self,
            "shape_signals",
            _unique_strings(
                self.shape_signals,
                "shape_signals",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=32,
            ),
        )
        signals = _typed_tuple(
            self.complexity_signals,
            ComplexitySignal,
            "complexity_signals",
        )
        if any(signal.source is not EvidenceSource.RULE for signal in signals):
            raise validation_error("rule_result_has_non_rule_signal")
        _unique((signal.code for signal in signals), "complexity_signal_code")
        object.__setattr__(
            self,
            "complexity_signals",
            tuple(sorted(signals, key=lambda signal: signal.code.value)),
        )


@dataclass(frozen=True, slots=True)
class ModelPerceptionProjection:
    schema_version: int
    projection_id: str
    context_digest: DigestString
    request_fingerprint: DigestString
    route_receipt_digest: DigestString
    target_identity_refs: tuple[str, ...]
    speech_acts: tuple[SpeechAct, ...]
    topics: tuple[TopicCandidate, ...]
    intents: tuple[IntentCandidate, ...]
    entities: tuple[EntityCandidate, ...]
    references: tuple[ReferenceCandidate, ...]
    ambiguities: tuple[AmbiguityCandidate, ...]
    need_tools: bool
    capability_categories: tuple[str, ...]
    task_kind: str
    reasoning_depth: TaskReasoningDepth
    expected_tool_steps: int
    verification_required: bool
    complexity_signals: tuple[ComplexitySignal, ...]
    confidence: float
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in (
            "projection_id",
            "task_kind",
        ):
            _bounded_string(getattr(self, name), name, _REFERENCE_MAX_LENGTH)
        for name in (
            "context_digest",
            "request_fingerprint",
            "route_receipt_digest",
        ):
            require_non_empty(str(getattr(self, name)), name)
        if type(self.need_tools) is not bool:
            raise validation_error("invalid_model_need_tools")
        if type(self.verification_required) is not bool:
            raise validation_error("invalid_model_verification_required")
        _enum(self.reasoning_depth, TaskReasoningDepth, "reasoning_depth")
        _bounded_nonnegative_int(
            self.expected_tool_steps,
            "expected_tool_steps",
            _MAX_EXPECTED_TOOL_STEPS,
        )
        _rate(self.confidence, "model_perception_confidence")
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_model_perception_revision")
        object.__setattr__(
            self,
            "target_identity_refs",
            _unique_strings(
                self.target_identity_refs,
                "target_identity_refs",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=128,
            ),
        )
        object.__setattr__(
            self,
            "speech_acts",
            _enum_tuple(self.speech_acts, SpeechAct, "speech_acts"),
        )
        object.__setattr__(
            self,
            "capability_categories",
            _unique_strings(
                self.capability_categories,
                "capability_categories",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=64,
            ),
        )
        for name, expected, identifier in (
            ("topics", TopicCandidate, "topic_id"),
            ("intents", IntentCandidate, "intent_id"),
            ("entities", EntityCandidate, "entity_id"),
            ("references", ReferenceCandidate, "reference_id"),
            ("ambiguities", AmbiguityCandidate, "ambiguity_id"),
        ):
            values = _typed_tuple(getattr(self, name), expected, name)
            if len(values) > _MAX_CANDIDATES_PER_KIND:
                raise validation_error(
                    "candidate_collection_exceeds_hard_ceiling", name
                )
            _unique((getattr(value, identifier) for value in values), identifier)
            object.__setattr__(
                self,
                name,
                tuple(sorted(values, key=lambda value: getattr(value, identifier))),
            )
        signals = _typed_tuple(
            self.complexity_signals,
            ComplexitySignal,
            "complexity_signals",
        )
        if any(signal.source is not EvidenceSource.MODEL for signal in signals):
            raise validation_error("model_projection_has_non_model_signal")
        _unique((signal.code for signal in signals), "complexity_signal_code")
        object.__setattr__(
            self,
            "complexity_signals",
            tuple(sorted(signals, key=lambda signal: signal.code.value)),
        )


@dataclass(frozen=True, slots=True)
class PerceptionResult:
    schema_version: int
    result_id: str
    context_digest: DigestString
    pipeline_revision: ComponentRevision
    component_revisions: tuple[ComponentRevision, ...]
    model_status: PerceptionModelStatus
    rule_result_digest: DigestString
    model_projection_digest: DigestString | None
    model_route_receipt_digest: DigestString | None
    should_consider_response: bool
    direct_mention: bool
    replies_to_bot: bool
    explicit_question: bool
    explicit_command: bool
    target_identity_refs: tuple[str, ...]
    speech_acts: tuple[SpeechAct, ...]
    topics: tuple[TopicCandidate, ...]
    intents: tuple[IntentCandidate, ...]
    entities: tuple[EntityCandidate, ...]
    references: tuple[ReferenceCandidate, ...]
    ambiguities: tuple[AmbiguityCandidate, ...]
    need_tools: bool
    capability_categories: tuple[str, ...]
    task_kind: str
    reasoning_depth: TaskReasoningDepth
    expected_tool_steps: int
    verification_required: bool
    complexity_signals: tuple[ComplexitySignal, ...]
    confidence: float
    conflicting_evidence: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.result_id, "perception_result_id")
        require_non_empty(str(self.context_digest), "context_digest")
        require_non_empty(str(self.rule_result_digest), "rule_result_digest")
        _bounded_string(
            self.task_kind,
            "perception_task_kind",
            _REFERENCE_MAX_LENGTH,
        )
        if not isinstance(self.pipeline_revision, ComponentRevision):
            raise validation_error("invalid_perception_pipeline_revision")
        revisions = _typed_tuple(
            self.component_revisions,
            ComponentRevision,
            "component_revisions",
        )
        if not revisions:
            raise validation_error("missing_perception_component_revisions")
        _unique(
            (revision.component_id for revision in revisions),
            "component_revision_id",
        )
        object.__setattr__(
            self,
            "component_revisions",
            tuple(sorted(revisions, key=lambda item: item.component_id)),
        )
        _enum(self.model_status, PerceptionModelStatus, "model_status")
        if self.model_status is PerceptionModelStatus.VALID:
            if (
                self.model_projection_digest is None
                or self.model_route_receipt_digest is None
            ):
                raise validation_error("valid_model_projection_has_no_receipt")
        elif self.model_projection_digest is not None:
            raise validation_error("invalid_model_status_has_projection")
        if self.model_projection_digest is not None:
            require_non_empty(
                str(self.model_projection_digest),
                "model_projection_digest",
            )
        if self.model_route_receipt_digest is not None:
            require_non_empty(
                str(self.model_route_receipt_digest),
                "model_route_receipt_digest",
            )
        for name in (
            "should_consider_response",
            "direct_mention",
            "replies_to_bot",
            "explicit_question",
            "explicit_command",
            "need_tools",
            "verification_required",
            "conflicting_evidence",
        ):
            if type(getattr(self, name)) is not bool:
                raise validation_error("invalid_perception_result_flag", name)
        _enum(self.reasoning_depth, TaskReasoningDepth, "reasoning_depth")
        _bounded_nonnegative_int(
            self.expected_tool_steps,
            "expected_tool_steps",
            _MAX_EXPECTED_TOOL_STEPS,
        )
        _rate(self.confidence, "perception_confidence")
        object.__setattr__(
            self,
            "target_identity_refs",
            _unique_strings(
                self.target_identity_refs,
                "target_identity_refs",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=128,
            ),
        )
        object.__setattr__(
            self,
            "speech_acts",
            _enum_tuple(self.speech_acts, SpeechAct, "speech_acts"),
        )
        object.__setattr__(
            self,
            "capability_categories",
            _unique_strings(
                self.capability_categories,
                "capability_categories",
                required=False,
                sorted_output=True,
                maximum_length=_REFERENCE_MAX_LENGTH,
                maximum_items=64,
            ),
        )
        for name, expected, identifier in (
            ("topics", TopicCandidate, "topic_id"),
            ("intents", IntentCandidate, "intent_id"),
            ("entities", EntityCandidate, "entity_id"),
            ("references", ReferenceCandidate, "reference_id"),
            ("ambiguities", AmbiguityCandidate, "ambiguity_id"),
        ):
            values = _typed_tuple(getattr(self, name), expected, name)
            if len(values) > _MAX_CANDIDATES_PER_KIND:
                raise validation_error(
                    "candidate_collection_exceeds_hard_ceiling", name
                )
            _unique((getattr(value, identifier) for value in values), identifier)
            object.__setattr__(
                self,
                name,
                tuple(sorted(values, key=lambda value: getattr(value, identifier))),
            )
        signals = _typed_tuple(
            self.complexity_signals,
            ComplexitySignal,
            "complexity_signals",
        )
        signal_keys = tuple((signal.code, signal.source) for signal in signals)
        _unique(signal_keys, "complexity_signal_source_code")
        object.__setattr__(
            self,
            "complexity_signals",
            tuple(
                sorted(signals, key=lambda item: (item.code.value, item.source.value))
            ),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(
                self.reason_codes,
                "perception_reason_codes",
                required=True,
                sorted_output=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationView:
    schema_version: int
    can_respond: bool
    can_use_tools: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if type(self.can_respond) is not bool or type(self.can_use_tools) is not bool:
            raise validation_error("invalid_authorization_view")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(
                self.reason_codes,
                "authorization_view_reason_codes",
                required=True,
                sorted_output=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class DecisionSignals:
    schema_version: int
    authorization: AuthorizationView
    duplicate_or_self_message: bool
    explicit_interaction: bool
    private_conversation: bool
    group_mode: GroupInteractionMode
    rate_limited: bool
    private_data_boundary: bool
    tools_enabled: bool
    known_target: bool

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.authorization, AuthorizationView):
            raise validation_error("invalid_decision_authorization_view")
        _enum(self.group_mode, GroupInteractionMode, "group_mode")
        for name in (
            "duplicate_or_self_message",
            "explicit_interaction",
            "private_conversation",
            "rate_limited",
            "private_data_boundary",
            "tools_enabled",
            "known_target",
        ):
            if type(getattr(self, name)) is not bool:
                raise validation_error("invalid_decision_signal", name)


@dataclass(frozen=True, slots=True)
class SocialDecision:
    schema_version: int
    decision_id: str
    perception_result_digest: DigestString
    action: SocialAction
    confidence: float
    reason_codes: tuple[str, ...]
    target_identity_refs: tuple[str, ...]
    clarification_key: ClarificationKey | None
    response_constraints: ResponseConstraints = field(
        default_factory=ResponseConstraints
    )
    policy_revision: str = "social-policy-v1"
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.decision_id, "social_decision_id")
        require_non_empty(
            str(self.perception_result_digest),
            "perception_result_digest",
        )
        require_non_empty(self.policy_revision, "social_policy_revision")
        _enum(self.action, SocialAction, "social_action")
        _rate(self.confidence, "social_decision_confidence")
        if not isinstance(self.response_constraints, ResponseConstraints):
            raise validation_error("invalid_social_response_constraints")
        if self.decided_at is None:
            raise validation_error("missing_social_decided_at")
        require_aware(self.decided_at, "social_decided_at")
        proactive_group_reply = (
            self.action is SocialAction.DIRECT_REPLY
            and "proactive_group_direct_reply" in self.reason_codes
        )
        targets = _unique_strings(
            self.target_identity_refs,
            "social_target_identity_refs",
            required=(
                self.action is not SocialAction.IGNORE and not proactive_group_reply
            ),
            sorted_output=True,
        )
        object.__setattr__(self, "target_identity_refs", targets)
        if self.action is SocialAction.ASK_CLARIFICATION:
            if self.clarification_key is None:
                raise validation_error("clarification_action_has_no_key")
        elif self.clarification_key is not None:
            raise validation_error("non_clarification_action_has_key")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(
                self.reason_codes,
                "social_reason_codes",
                required=True,
                sorted_output=True,
            ),
        )


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _enum(value: object, expected: type[StrEnum], field_name: str) -> None:
    if not isinstance(value, expected):
        raise validation_error("invalid_enum", field_name)


def _rate(value: float, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise validation_error("invalid_confidence", field_name)


def _positive_int(value: int, field_name: str) -> None:
    if type(value) is not int or value < 1:
        raise validation_error("invalid_positive_integer", field_name)


def _nonnegative_int(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise validation_error("invalid_nonnegative_integer", field_name)


def _bounded_nonnegative_int(value: int, field_name: str, maximum: int) -> None:
    _nonnegative_int(value, field_name)
    if value > maximum:
        raise validation_error("integer_exceeds_hard_ceiling", field_name)


def _bounded_string(value: str, field_name: str, maximum: int) -> None:
    require_non_empty(value, field_name)
    if len(value) > maximum:
        raise validation_error("string_exceeds_hard_ceiling", field_name)


def _unique(values: object, field_name: str) -> None:
    materialized = tuple(values)  # type: ignore[arg-type]
    if len(materialized) != len(set(materialized)):
        raise validation_error("duplicate_identifier", field_name)


def _unique_strings(
    values: tuple[str, ...],
    field_name: str,
    *,
    required: bool,
    sorted_output: bool,
    maximum_length: int | None = None,
    maximum_items: int | None = None,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_string_collection", field_name)
    materialized = tuple(values)
    if required and not materialized:
        raise validation_error("empty_collection", field_name)
    if maximum_items is not None and len(materialized) > maximum_items:
        raise validation_error("collection_exceeds_hard_ceiling", field_name)
    if any(not isinstance(value, str) or not value.strip() for value in materialized):
        raise validation_error("empty_collection_item", field_name)
    if maximum_length is not None and any(
        len(value) > maximum_length for value in materialized
    ):
        raise validation_error("string_exceeds_hard_ceiling", field_name)
    _unique(materialized, field_name)
    if sorted_output:
        return tuple(sorted(materialized))
    return materialized


def _typed_tuple(
    values: object,
    expected: type[object],
    field_name: str,
) -> tuple[object, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_typed_collection", field_name)
    materialized = tuple(values)  # type: ignore[arg-type]
    if any(not isinstance(value, expected) for value in materialized):
        raise validation_error("invalid_collection_item", field_name)
    return materialized


def _enum_tuple(
    values: tuple[StrEnum, ...],
    expected: type[StrEnum],
    field_name: str,
) -> tuple[StrEnum, ...]:
    materialized = tuple(values)
    if any(not isinstance(value, expected) for value in materialized):
        raise validation_error("invalid_enum_collection", field_name)
    _unique(materialized, field_name)
    return tuple(sorted(materialized, key=lambda value: value.value))
