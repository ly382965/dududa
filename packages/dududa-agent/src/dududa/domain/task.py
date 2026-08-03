from __future__ import annotations

import math
from dataclasses import dataclass

from dududa._compat import StrEnum
from dududa.errors import validation_error

from .primitives import ComponentRevision, require_non_empty


class TaskComplexityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContextPressure(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskReasoningDepth(StrEnum):
    SHALLOW = "shallow"
    MULTI_STEP = "multi_step"
    DEEP = "deep"


class TaskAmbiguity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class TaskComplexityAssessment:
    schema_version: int
    assessment_id: str
    level: TaskComplexityLevel
    confidence: float
    task_kind: str
    context_pressure: ContextPressure
    reasoning_depth: TaskReasoningDepth
    expected_tool_steps: int
    ambiguity: TaskAmbiguity
    verification_required: bool
    conflicting_evidence: bool
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    assessor_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.assessment_id, "assessment_id")
        require_non_empty(self.task_kind, "task_kind")
        if not isinstance(self.assessor_revision, ComponentRevision):
            raise validation_error("invalid_assessor_revision")
        _require_enum(self.level, TaskComplexityLevel, "complexity_level")
        _require_enum(self.context_pressure, ContextPressure, "context_pressure")
        _require_enum(self.reasoning_depth, TaskReasoningDepth, "reasoning_depth")
        _require_enum(self.ambiguity, TaskAmbiguity, "ambiguity")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise validation_error("invalid_task_complexity_confidence")
        if type(self.expected_tool_steps) is not int or self.expected_tool_steps < 0:
            raise validation_error("invalid_expected_tool_steps")
        if type(self.verification_required) is not bool:
            raise validation_error("invalid_verification_required")
        if type(self.conflicting_evidence) is not bool:
            raise validation_error("invalid_conflicting_evidence")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(self.reason_codes, "reason_codes", required=True),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_strings(self.evidence_refs, "evidence_refs", required=False),
        )


def _unique_strings(
    values: tuple[str, ...],
    field: str,
    *,
    required: bool,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_string_collection", field)
    materialized = tuple(values)
    if required and not materialized:
        raise validation_error("empty_collection", field)
    if any(not isinstance(value, str) or not value.strip() for value in materialized):
        raise validation_error("empty_collection_item", field)
    if len(materialized) != len(set(materialized)):
        raise validation_error("duplicate_identifier", field)
    return materialized


def _require_enum(value: object, expected: type[StrEnum], field: str) -> None:
    if not isinstance(value, expected):
        raise validation_error("invalid_enum", field)


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
