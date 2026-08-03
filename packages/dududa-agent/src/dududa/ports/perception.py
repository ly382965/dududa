from __future__ import annotations

from typing import Protocol, runtime_checkable

from dududa.domain.task import TaskComplexityAssessment
from dududa.domain.primitives import DigestString
from dududa.perception.contracts import (
    DecisionSignals,
    ModelPerceptionProjection,
    PerceptionContext,
    PerceptionModelStatus,
    PerceptionResult,
    RulePerceptionResult,
    SocialDecision,
)

from .context import PortCallContext


@runtime_checkable
class RulePerception(Protocol):
    def perceive(self, context: PerceptionContext) -> RulePerceptionResult: ...


@runtime_checkable
class ModelPerception(Protocol):
    async def perceive(
        self,
        context: PerceptionContext,
        *,
        call: PortCallContext,
    ) -> ModelPerceptionProjection: ...


@runtime_checkable
class PerceptionValidator(Protocol):
    def validate_model(
        self,
        context: PerceptionContext,
        projection: ModelPerceptionProjection,
    ) -> ModelPerceptionProjection: ...

    def validate_result(
        self,
        context: PerceptionContext,
        result: PerceptionResult,
    ) -> PerceptionResult: ...


@runtime_checkable
class PerceptionMerger(Protocol):
    def merge(
        self,
        context: PerceptionContext,
        rules: RulePerceptionResult,
        model: ModelPerceptionProjection | None,
        *,
        model_status: PerceptionModelStatus,
        model_route_receipt_digest: DigestString | None = None,
    ) -> PerceptionResult: ...


@runtime_checkable
class PerceptionEngine(Protocol):
    async def perceive(
        self,
        context: PerceptionContext,
        *,
        call: PortCallContext,
    ) -> PerceptionResult: ...


@runtime_checkable
class TaskComplexityAssessor(Protocol):
    def assess(
        self,
        context: PerceptionContext,
        perception: PerceptionResult,
    ) -> TaskComplexityAssessment: ...


@runtime_checkable
class SocialDecisionEngine(Protocol):
    async def decide(
        self,
        perception: PerceptionResult,
        signals: DecisionSignals,
        *,
        call: PortCallContext,
    ) -> SocialDecision: ...
