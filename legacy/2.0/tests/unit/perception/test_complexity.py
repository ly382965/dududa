from __future__ import annotations

from dataclasses import replace
import unittest

from dududa.domain.primitives import ConversationType, DigestString, freeze_json
from dududa.domain.task import (
    ContextPressure,
    TaskAmbiguity,
    TaskComplexityLevel,
)
from dududa.perception.complexity import (
    DeterministicComplexityAssessor,
    default_complexity_assessor_config,
)
from dududa.perception.contracts import PerceptionModelStatus
from dududa.perception.digests import perception_context_digest
from dududa.perception.merge import (
    DeterministicPerceptionMerger,
    PerceptionMergeConfig,
)
from dududa.perception.rules import (
    DeterministicRulePerception,
    default_rule_perception_config,
)
from dududa.perception.schema import decode_model_projection

from .helpers import context, model_payload, revision


def _perception(value, payload=None, *, status=PerceptionModelStatus.VALID):
    rules = DeterministicRulePerception(
        default_rule_perception_config(revision("rule-perception")),
        id_factory=lambda: "rule-result",
    ).perceive(value)
    model = None
    if status is PerceptionModelStatus.VALID:
        model = decode_model_projection(
            freeze_json(payload or model_payload()),
            context_digest=perception_context_digest(value),
            projection_id="projection",
            request_fingerprint=DigestString("request-fingerprint"),
            route_receipt_digest=DigestString("route-receipt"),
            component_revision=revision("model-perception"),
        )
    return DeterministicPerceptionMerger(
        PerceptionMergeConfig(
            revision("perception-pipeline"),
            revision("perception-merger"),
            revision("perception-validator"),
            0.59,
            0.59,
        ),
        id_factory=lambda: "perception-result",
    ).merge(value, rules, model, model_status=status)


def _assessor():
    return DeterministicComplexityAssessor(
        default_complexity_assessor_config(revision("complexity-assessor")),
        id_factory=lambda: "assessment-1",
    )


class DeterministicComplexityAssessorTests(unittest.TestCase):
    def test_long_simple_task_is_low_complexity_with_high_context_pressure(
        self,
    ) -> None:
        current = replace(
            context().current_message,
            reply_to_message_ref=None,
            mentioned_identity_refs=(),
            text="hello",
        )
        value = context(
            conversation_type=ConversationType.PRIVATE,
            messages=(current,),
            content_input_tokens_upper_bound=20_000,
        )
        payload = model_payload(
            speech_acts=["greeting"],
            topics=[],
            intents=[],
            references=[],
            task_kind="greeting",
            reasoning_depth="shallow",
            verification_required=False,
            complexity_signals=[
                {
                    "code": "shallow_conversation",
                    "confidence": 0.95,
                    "evidence_refs": ["message:current"],
                }
            ],
            confidence=0.95,
        )

        assessment = _assessor().assess(value, _perception(value, payload))

        self.assertIs(assessment.level, TaskComplexityLevel.LOW)
        self.assertIs(assessment.context_pressure, ContextPressure.HIGH)

    def test_short_task_with_two_high_signals_is_high_complexity(self) -> None:
        value = context(content_input_tokens_upper_bound=128)

        assessment = _assessor().assess(value, _perception(value))

        self.assertIs(assessment.level, TaskComplexityLevel.HIGH)
        self.assertIs(assessment.context_pressure, ContextPressure.LOW)
        self.assertIn("multi_constraint_synthesis", assessment.reason_codes)
        self.assertIn("independent_verification", assessment.reason_codes)

    def test_one_high_signal_is_not_enough_for_high_complexity(self) -> None:
        value = context()
        payload = model_payload(
            verification_required=False,
            complexity_signals=[
                {
                    "code": "deep_reasoning",
                    "confidence": 0.9,
                    "evidence_refs": ["message:current"],
                }
            ],
        )

        assessment = _assessor().assess(value, _perception(value, payload))

        self.assertIs(assessment.level, TaskComplexityLevel.MEDIUM)

    def test_rule_fallback_can_label_low_but_keeps_low_confidence(self) -> None:
        current = replace(
            context().current_message,
            reply_to_message_ref=None,
            mentioned_identity_refs=(),
            text="hello",
        )
        value = context(
            conversation_type=ConversationType.PRIVATE,
            messages=(current,),
        )

        assessment = _assessor().assess(
            value,
            _perception(value, status=PerceptionModelStatus.UNAVAILABLE),
        )

        self.assertIs(assessment.level, TaskComplexityLevel.LOW)
        self.assertEqual(assessment.confidence, 0.59)
        self.assertIn("model_unavailable", assessment.reason_codes)

    def test_multiple_ambiguities_are_high_ambiguity_not_high_complexity(self) -> None:
        value = context()
        ambiguities = [
            {
                "ambiguity_id": f"ambiguity:{index}",
                "kind": kind,
                "clarification_key": clarification,
                "confidence": 0.9,
                "evidence_refs": ["message:current"],
            }
            for index, (kind, clarification) in enumerate(
                (("task", "clarify.task"), ("reference", "clarify.reference"))
            )
        ]
        payload = model_payload(
            ambiguities=ambiguities,
            verification_required=False,
            complexity_signals=[],
        )

        assessment = _assessor().assess(value, _perception(value, payload))

        self.assertIs(assessment.ambiguity, TaskAmbiguity.HIGH)
        self.assertIs(assessment.level, TaskComplexityLevel.MEDIUM)


if __name__ == "__main__":
    unittest.main()
