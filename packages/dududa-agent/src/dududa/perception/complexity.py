from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import uuid

from dududa.domain.primitives import ComponentRevision
from dududa.domain.task import (
    ContextPressure,
    TaskAmbiguity,
    TaskComplexityAssessment,
    TaskComplexityLevel,
    TaskReasoningDepth,
)
from dududa.errors import validation_error

from .contracts import (
    ComplexitySignal,
    ComplexitySignalCode,
    PerceptionContext,
    PerceptionResult,
)
from .validation import validate_perception_result


@dataclass(frozen=True, slots=True)
class ComplexityAssessorConfig:
    revision: ComponentRevision
    high_signal_codes: frozenset[ComplexitySignalCode]
    low_signal_codes: frozenset[ComplexitySignalCode]
    minimum_high_signals: int
    context_pressure_medium_tokens: int
    context_pressure_high_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.revision, ComponentRevision):
            raise ValueError("invalid Complexity Assessor revision")
        high_codes = frozenset(self.high_signal_codes)
        low_codes = frozenset(self.low_signal_codes)
        if (
            not high_codes
            or not low_codes
            or not all(isinstance(code, ComplexitySignalCode) for code in high_codes)
            or not all(isinstance(code, ComplexitySignalCode) for code in low_codes)
            or high_codes & low_codes
        ):
            raise ValueError("invalid Complexity Assessor signal sets")
        if (
            type(self.minimum_high_signals) is not int
            or self.minimum_high_signals < 2
            or self.minimum_high_signals > len(high_codes)
        ):
            raise ValueError("invalid Complexity Assessor high-signal threshold")
        for value in (
            self.context_pressure_medium_tokens,
            self.context_pressure_high_tokens,
        ):
            if type(value) is not int or value < 1:
                raise ValueError("invalid context-pressure threshold")
        if self.context_pressure_high_tokens <= self.context_pressure_medium_tokens:
            raise ValueError("invalid ordered context-pressure thresholds")
        object.__setattr__(self, "high_signal_codes", high_codes)
        object.__setattr__(self, "low_signal_codes", low_codes)


def default_complexity_assessor_config(
    revision: ComponentRevision,
) -> ComplexityAssessorConfig:
    return ComplexityAssessorConfig(
        revision=revision,
        high_signal_codes=frozenset(
            {
                ComplexitySignalCode.DEEP_REASONING,
                ComplexitySignalCode.MULTI_CONSTRAINT_SYNTHESIS,
                ComplexitySignalCode.INDEPENDENT_VERIFICATION,
                ComplexitySignalCode.MULTI_STEP_TOOL_PLAN,
                ComplexitySignalCode.CROSS_ARTIFACT_ANALYSIS,
            }
        ),
        low_signal_codes=frozenset(
            {
                ComplexitySignalCode.SIMPLE_RETRIEVAL,
                ComplexitySignalCode.BOUNDED_TRANSFORMATION,
                ComplexitySignalCode.SHALLOW_CONVERSATION,
            }
        ),
        minimum_high_signals=2,
        context_pressure_medium_tokens=4_096,
        context_pressure_high_tokens=16_384,
    )


class DeterministicComplexityAssessor:
    def __init__(
        self,
        config: ComplexityAssessorConfig,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, ComplexityAssessorConfig):
            raise ValueError("invalid Complexity Assessor config")
        self._config = config
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    @property
    def config(self) -> ComplexityAssessorConfig:
        return self._config

    def assess(
        self,
        context: PerceptionContext,
        perception: PerceptionResult,
    ) -> TaskComplexityAssessment:
        validate_perception_result(context, perception)
        signal_codes = {signal.code for signal in perception.complexity_signals}
        high_codes = signal_codes & self._config.high_signal_codes
        low_codes = signal_codes & self._config.low_signal_codes
        ambiguity = _ambiguity_level(len(perception.ambiguities))
        context_pressure = _context_pressure(
            context.content_input_tokens_upper_bound,
            self._config,
        )
        clear_low = (
            bool(low_codes)
            and not high_codes
            and perception.reasoning_depth is TaskReasoningDepth.SHALLOW
            and perception.expected_tool_steps == 0
            and ambiguity is TaskAmbiguity.LOW
            and not perception.verification_required
            and not perception.conflicting_evidence
        )
        if len(high_codes) >= self._config.minimum_high_signals:
            level = TaskComplexityLevel.HIGH
            decisive = _signals_for_codes(perception.complexity_signals, high_codes)
        elif clear_low:
            level = TaskComplexityLevel.LOW
            decisive = _signals_for_codes(perception.complexity_signals, low_codes)
        else:
            level = TaskComplexityLevel.MEDIUM
            decisive = perception.complexity_signals

        confidence = perception.confidence
        if decisive:
            confidence = min(
                confidence,
                *(signal.confidence for signal in decisive),
            )
        reason_codes = {
            f"complexity_{level.value}",
            f"context_pressure_{context_pressure.value}",
            f"ambiguity_{ambiguity.value}",
            *(code.value for code in signal_codes),
        }
        if perception.conflicting_evidence:
            reason_codes.add("conflicting_evidence")
        if perception.model_status.value != "valid":
            reason_codes.add(f"model_{perception.model_status.value}")
        evidence_refs = tuple(
            sorted(
                {reference for signal in decisive for reference in signal.evidence_refs}
            )
        )
        if not evidence_refs:
            evidence_refs = (context.current_message_ref,)
        return TaskComplexityAssessment(
            schema_version=1,
            assessment_id=self._id_factory(),
            level=level,
            confidence=confidence,
            task_kind=perception.task_kind,
            context_pressure=context_pressure,
            reasoning_depth=perception.reasoning_depth,
            expected_tool_steps=perception.expected_tool_steps,
            ambiguity=ambiguity,
            verification_required=perception.verification_required,
            conflicting_evidence=perception.conflicting_evidence,
            reason_codes=tuple(sorted(reason_codes)),
            evidence_refs=evidence_refs,
            assessor_revision=self._config.revision,
        )


def _context_pressure(
    tokens: int,
    config: ComplexityAssessorConfig,
) -> ContextPressure:
    if tokens >= config.context_pressure_high_tokens:
        return ContextPressure.HIGH
    if tokens >= config.context_pressure_medium_tokens:
        return ContextPressure.MEDIUM
    return ContextPressure.LOW


def _ambiguity_level(count: int) -> TaskAmbiguity:
    if count == 0:
        return TaskAmbiguity.LOW
    if count == 1:
        return TaskAmbiguity.MEDIUM
    return TaskAmbiguity.HIGH


def _signals_for_codes(
    signals: tuple[ComplexitySignal, ...],
    codes: set[ComplexitySignalCode],
) -> tuple[ComplexitySignal, ...]:
    if not all(isinstance(code, ComplexitySignalCode) for code in codes):
        raise validation_error("invalid_complexity_signal_code")
    return tuple(signal for signal in signals if signal.code in codes)
