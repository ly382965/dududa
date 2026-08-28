from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType

from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.domain.task import TaskReasoningDepth
from dududa.errors import validation_error

from .contracts import (
    AmbiguityCandidate,
    ComplexitySignal,
    EntityCandidate,
    IntentCandidate,
    ModelPerceptionProjection,
    PerceptionContext,
    PerceptionModelStatus,
    PerceptionResult,
    ReferenceCandidate,
    RulePerceptionResult,
    TopicCandidate,
)
from .digests import (
    model_perception_projection_digest,
    rule_perception_result_digest,
)
from .validation import (
    validate_model_projection,
    validate_perception_result,
    validate_rule_result,
)


@dataclass(frozen=True, slots=True)
class PerceptionMergeConfig:
    pipeline_revision: ComponentRevision
    merger_revision: ComponentRevision
    validator_revision: ComponentRevision
    fallback_confidence_ceiling: float
    conflict_confidence_ceiling: float

    def __post_init__(self) -> None:
        revisions = (
            self.pipeline_revision,
            self.merger_revision,
            self.validator_revision,
        )
        if not all(isinstance(revision, ComponentRevision) for revision in revisions):
            raise ValueError("invalid Perception merge revision")
        if len({revision.component_id for revision in revisions}) != len(revisions):
            raise ValueError("duplicate Perception merge component revision")
        for value in (
            self.fallback_confidence_ceiling,
            self.conflict_confidence_ceiling,
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("invalid Perception confidence ceiling")
            if not 0 <= value <= 1:
                raise ValueError("invalid Perception confidence ceiling")


class DeterministicPerceptionMerger:
    def __init__(
        self,
        config: PerceptionMergeConfig,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, PerceptionMergeConfig):
            raise ValueError("invalid Perception merge config")
        self._config = config
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def merge(
        self,
        context: PerceptionContext,
        rules: RulePerceptionResult,
        model: ModelPerceptionProjection | None,
        *,
        model_status: PerceptionModelStatus,
        model_route_receipt_digest: DigestString | None = None,
    ) -> PerceptionResult:
        if not isinstance(model_status, PerceptionModelStatus):
            raise validation_error("invalid_perception_model_status")
        validate_rule_result(context, rules)
        if model is None:
            if model_status is PerceptionModelStatus.VALID:
                raise validation_error("valid_model_status_has_no_projection")
        else:
            if model_status is not PerceptionModelStatus.VALID:
                raise validation_error("model_projection_has_invalid_status")
            validate_model_projection(context, model)
            if (
                model_route_receipt_digest is not None
                and model_route_receipt_digest != model.route_receipt_digest
            ):
                raise validation_error("model_route_receipt_digest_mismatch")
            model_route_receipt_digest = model.route_receipt_digest

        reasons: set[str] = {"rule_evidence_applied"}
        components = [
            rules.component_revision,
            self._config.merger_revision,
            self._config.validator_revision,
        ]
        if model is None:
            topics: tuple[TopicCandidate, ...] = ()
            intents: tuple[IntentCandidate, ...] = ()
            entities: tuple[EntityCandidate, ...] = ()
            references: tuple[ReferenceCandidate, ...] = ()
            ambiguities: tuple[AmbiguityCandidate, ...] = ()
            target_identity_refs = rules.target_identity_refs
            speech_acts = rules.speech_acts
            need_tools = rules.need_tools
            capability_categories = rules.capability_categories
            task_kind = rules.task_kind
            reasoning_depth = rules.reasoning_depth
            expected_tool_steps = rules.expected_tool_steps
            verification_required = rules.verification_required
            complexity_signals = rules.complexity_signals
            confidence = min(
                rules.confidence,
                self._config.fallback_confidence_ceiling,
            )
            conflicting = False
            reasons.add(f"model_{model_status.value}_rule_fallback")
            model_projection_digest = None
        else:
            components.append(model.component_revision)
            evidence_limit = context.limits.max_evidence_refs_per_item
            topics = _merge_topics(model.topics, evidence_limit)
            intents = _merge_intents(model.intents, evidence_limit)
            entities = _merge_entities(model.entities, evidence_limit)
            references = _merge_references(model.references, evidence_limit)
            ambiguities = _merge_ambiguities(model.ambiguities, evidence_limit)
            rule_targets = set(rules.target_identity_refs)
            model_targets = set(model.target_identity_refs)
            target_identity_refs = rules.target_identity_refs
            speech_acts = tuple(sorted(set(rules.speech_acts) | set(model.speech_acts)))
            need_tools = rules.need_tools or model.need_tools
            capability_categories = tuple(
                sorted(
                    set(rules.capability_categories) | set(model.capability_categories)
                )
            )
            expected_tool_steps = max(
                rules.expected_tool_steps,
                model.expected_tool_steps,
            )
            verification_required = (
                rules.verification_required or model.verification_required
            )
            reasoning_depth = _maximum_reasoning_depth(
                rules.reasoning_depth,
                model.reasoning_depth,
            )
            task_kind, task_conflict = _merge_task_kind(
                rules.task_kind, model.task_kind
            )
            complexity_signals = _merge_complexity_signals(
                rules.complexity_signals,
                model.complexity_signals,
            )
            conflicting = any(
                (
                    task_conflict,
                    bool(model_targets) and model_targets != rule_targets,
                    rules.need_tools and not model.need_tools,
                    rules.verification_required and not model.verification_required,
                    rules.reasoning_depth is TaskReasoningDepth.DEEP
                    and model.reasoning_depth is TaskReasoningDepth.SHALLOW,
                )
            )
            confidence = min(rules.confidence, model.confidence)
            if conflicting:
                confidence = min(
                    confidence,
                    self._config.conflict_confidence_ceiling,
                )
                reasons.add("rule_model_conflict")
            else:
                reasons.add("rule_model_merged")
            model_projection_digest = model_perception_projection_digest(model)

        if need_tools and expected_tool_steps == 0:
            expected_tool_steps = 1
        result = PerceptionResult(
            schema_version=1,
            result_id=self._id_factory(),
            context_digest=rules.context_digest,
            pipeline_revision=self._config.pipeline_revision,
            component_revisions=tuple(components),
            model_status=model_status,
            rule_result_digest=rule_perception_result_digest(rules),
            model_projection_digest=model_projection_digest,
            model_route_receipt_digest=model_route_receipt_digest,
            should_consider_response=rules.should_consider_response,
            direct_mention=rules.direct_mention,
            replies_to_bot=rules.replies_to_bot,
            explicit_question=rules.explicit_question,
            explicit_command=rules.explicit_command,
            target_identity_refs=target_identity_refs,
            speech_acts=speech_acts,
            topics=topics,
            intents=intents,
            entities=entities,
            references=references,
            ambiguities=ambiguities,
            need_tools=need_tools,
            capability_categories=capability_categories,
            task_kind=task_kind,
            reasoning_depth=reasoning_depth,
            expected_tool_steps=expected_tool_steps,
            verification_required=verification_required,
            complexity_signals=complexity_signals,
            confidence=confidence,
            conflicting_evidence=conflicting,
            reason_codes=tuple(reasons),
        )
        return validate_perception_result(context, result)


def _merge_task_kind(rule_kind: str, model_kind: str) -> tuple[str, bool]:
    authoritative = {"explicit_command", "greeting", "bounded_transformation"}
    if rule_kind in authoritative:
        return rule_kind, rule_kind != model_kind
    return model_kind, False


def _maximum_reasoning_depth(
    left: TaskReasoningDepth,
    right: TaskReasoningDepth,
) -> TaskReasoningDepth:
    ranks = MappingProxyType(
        {
            TaskReasoningDepth.SHALLOW: 0,
            TaskReasoningDepth.MULTI_STEP: 1,
            TaskReasoningDepth.DEEP: 2,
        }
    )
    return left if ranks[left] >= ranks[right] else right


def _merge_topics(
    values: tuple[TopicCandidate, ...], evidence_limit: int
) -> tuple[TopicCandidate, ...]:
    grouped: dict[str, list[TopicCandidate]] = {}
    for value in values:
        grouped.setdefault(value.label.casefold(), []).append(value)
    return tuple(
        TopicCandidate(
            1,
            min(item.topic_id for item in group),
            min(
                (item.label for item in group),
                key=lambda label: (label.casefold(), label),
            ),
            min(item.confidence for item in group),
            _merged_evidence(group, evidence_limit),
        )
        for _, group in sorted(grouped.items())
    )


def _merge_intents(
    values: tuple[IntentCandidate, ...], evidence_limit: int
) -> tuple[IntentCandidate, ...]:
    grouped: dict[str, list[IntentCandidate]] = {}
    for value in values:
        grouped.setdefault(value.intent_id, []).append(value)
    return tuple(
        IntentCandidate(
            1,
            key,
            min(item.confidence for item in group),
            _merged_evidence(group, evidence_limit),
        )
        for key, group in sorted(grouped.items())
    )


def _merge_entities(
    values: tuple[EntityCandidate, ...], evidence_limit: int
) -> tuple[EntityCandidate, ...]:
    grouped: dict[tuple[str, str], list[EntityCandidate]] = {}
    for value in values:
        grouped.setdefault((value.kind.value, value.value.casefold()), []).append(value)
    return tuple(
        EntityCandidate(
            1,
            min(item.entity_id for item in group),
            group[0].kind,
            min(
                (item.value for item in group), key=lambda item: (item.casefold(), item)
            ),
            min(item.confidence for item in group),
            _merged_evidence(group, evidence_limit),
        )
        for _, group in sorted(grouped.items())
    )


def _merge_references(
    values: tuple[ReferenceCandidate, ...],
    evidence_limit: int,
) -> tuple[ReferenceCandidate, ...]:
    grouped: dict[tuple[str, str], list[ReferenceCandidate]] = {}
    for value in values:
        grouped.setdefault((value.kind.value, value.target_ref or ""), []).append(value)
    return tuple(
        ReferenceCandidate(
            1,
            min(item.reference_id for item in group),
            group[0].kind,
            group[0].target_ref,
            min(item.confidence for item in group),
            _merged_evidence(group, evidence_limit),
        )
        for _, group in sorted(grouped.items())
    )


def _merge_ambiguities(
    values: tuple[AmbiguityCandidate, ...],
    evidence_limit: int,
) -> tuple[AmbiguityCandidate, ...]:
    grouped: dict[tuple[str, str], list[AmbiguityCandidate]] = {}
    for value in values:
        grouped.setdefault(
            (
                value.kind.value,
                value.clarification_key.value if value.clarification_key else "",
            ),
            [],
        ).append(value)
    return tuple(
        AmbiguityCandidate(
            1,
            min(item.ambiguity_id for item in group),
            group[0].kind,
            group[0].clarification_key,
            min(item.confidence for item in group),
            _merged_evidence(group, evidence_limit),
        )
        for _, group in sorted(grouped.items())
    )


def _merge_complexity_signals(
    rules: tuple[ComplexitySignal, ...],
    model: tuple[ComplexitySignal, ...],
) -> tuple[ComplexitySignal, ...]:
    return tuple(
        sorted(
            (*rules, *model),
            key=lambda signal: (signal.code.value, signal.source.value),
        )
    )


def _merged_evidence(values: list[object], maximum: int) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                reference
                for value in values
                for reference in value.evidence_refs  # type: ignore[attr-defined]
            }
        )[:maximum]
    )
