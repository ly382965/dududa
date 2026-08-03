from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString

from .contracts import (
    ModelPerceptionProjection,
    PerceptionContext,
    PerceptionResult,
    RulePerceptionResult,
    SocialDecision,
)


def perception_context_digest(context: PerceptionContext) -> DigestString:
    return canonical_digest(context, domain="perception:context:v1")


def perception_context_fingerprint(context: PerceptionContext) -> DigestString:
    values = {
        name: getattr(context, name)
        for name in context.__dataclass_fields__
        if name != "context_id"
    }
    return canonical_digest(values, domain="perception:context-plan:v1")


def rule_perception_result_digest(result: RulePerceptionResult) -> DigestString:
    return canonical_digest(result, domain="perception:rule-result:v1")


def rule_perception_result_fingerprint(
    result: RulePerceptionResult,
) -> DigestString:
    values = {
        name: getattr(result, name)
        for name in result.__dataclass_fields__
        if name != "result_id"
    }
    return canonical_digest(values, domain="perception:rule-result-plan:v1")


def model_perception_projection_digest(
    projection: ModelPerceptionProjection,
) -> DigestString:
    return canonical_digest(projection, domain="perception:model-projection:v1")


def model_perception_projection_fingerprint(
    projection: ModelPerceptionProjection,
) -> DigestString:
    values = {
        name: getattr(projection, name)
        for name in projection.__dataclass_fields__
        if name not in {"projection_id", "route_receipt_digest"}
    }
    return canonical_digest(values, domain="perception:model-projection-plan:v1")


def perception_result_digest(result: PerceptionResult) -> DigestString:
    return canonical_digest(result, domain="perception:result:v1")


def perception_result_fingerprint(result: PerceptionResult) -> DigestString:
    values = {
        name: getattr(result, name)
        for name in result.__dataclass_fields__
        if name not in {"result_id", "model_route_receipt_digest"}
    }
    return canonical_digest(values, domain="perception:result-plan:v1")


def social_decision_digest(decision: SocialDecision) -> DigestString:
    return canonical_digest(decision, domain="perception:social-decision:v1")


def social_decision_fingerprint(decision: SocialDecision) -> DigestString:
    values = {
        name: getattr(decision, name)
        for name in decision.__dataclass_fields__
        if name not in {"decision_id", "decided_at"}
    }
    return canonical_digest(values, domain="perception:social-decision-plan:v1")
