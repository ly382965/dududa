from __future__ import annotations

from dataclasses import replace
import unittest

from dududa.domain.primitives import DigestString, freeze_json
from dududa.domain.task import TaskReasoningDepth
from dududa.errors import DududaError
from dududa.perception.contracts import PerceptionIdentity, PerceptionModelStatus
from dududa.perception.digests import (
    perception_context_digest,
    perception_result_fingerprint,
)
from dududa.perception.merge import (
    DeterministicPerceptionMerger,
    PerceptionMergeConfig,
)
from dududa.perception.rules import (
    DeterministicRulePerception,
    default_rule_perception_config,
)
from dududa.perception.schema import decode_model_projection
from dududa.perception.validation import validate_perception_result

from .helpers import context, limits, model_payload, revision


def _rules(value):
    return DeterministicRulePerception(
        default_rule_perception_config(revision("rule-perception")),
        id_factory=lambda: "rule-result-1",
    ).perceive(value)


def _projection(value, payload=None):
    return decode_model_projection(
        freeze_json(payload or model_payload()),
        context_digest=perception_context_digest(value),
        projection_id="projection-1",
        request_fingerprint=DigestString("request-fingerprint"),
        route_receipt_digest=DigestString("route-receipt"),
        component_revision=revision("model-perception"),
    )


def _merger(result_id: str = "perception-result-1"):
    return DeterministicPerceptionMerger(
        PerceptionMergeConfig(
            pipeline_revision=revision("perception-pipeline"),
            merger_revision=revision("perception-merger"),
            validator_revision=revision("perception-validator"),
            fallback_confidence_ceiling=0.59,
            conflict_confidence_ceiling=0.59,
        ),
        id_factory=lambda: result_id,
    )


class DeterministicPerceptionMergerTests(unittest.TestCase):
    def test_valid_model_semantics_merge_with_rule_authority(self) -> None:
        value = context()
        result = _merger().merge(
            value,
            _rules(value),
            _projection(value),
            model_status=PerceptionModelStatus.VALID,
        )

        self.assertEqual(result.task_kind, "comparison")
        self.assertIs(result.reasoning_depth, TaskReasoningDepth.MULTI_STEP)
        self.assertEqual(result.target_identity_refs, ("identity:user",))
        self.assertEqual(result.model_route_receipt_digest, "route-receipt")
        self.assertFalse(result.conflicting_evidence)
        self.assertIn("rule_model_merged", result.reason_codes)

    def test_rule_only_fallback_is_confidence_capped(self) -> None:
        value = context()
        result = _merger().merge(
            value,
            _rules(value),
            None,
            model_status=PerceptionModelStatus.UNAVAILABLE,
            model_route_receipt_digest=DigestString("failed-route-receipt"),
        )

        self.assertEqual(result.confidence, 0.59)
        self.assertIsNone(result.model_projection_digest)
        self.assertEqual(result.model_route_receipt_digest, "failed-route-receipt")
        self.assertIn("model_unavailable_rule_fallback", result.reason_codes)

    def test_trusted_rule_conflict_caps_confidence_and_wins(self) -> None:
        value = context()
        rules = replace(
            _rules(value),
            task_kind="explicit_command",
            explicit_command=True,
            verification_required=True,
            reasoning_depth=TaskReasoningDepth.DEEP,
        )
        model = replace(
            _projection(value),
            target_identity_refs=(),
            task_kind="greeting",
            verification_required=False,
            reasoning_depth=TaskReasoningDepth.SHALLOW,
        )

        result = _merger().merge(
            value,
            rules,
            model,
            model_status=PerceptionModelStatus.VALID,
        )

        self.assertEqual(result.task_kind, "explicit_command")
        self.assertTrue(result.verification_required)
        self.assertIs(result.reasoning_depth, TaskReasoningDepth.DEEP)
        self.assertTrue(result.conflicting_evidence)
        self.assertEqual(result.confidence, 0.59)

    def test_unknown_model_reference_rejects_the_whole_projection(self) -> None:
        value = context()
        model = replace(_projection(value), target_identity_refs=("identity:outside",))

        with self.assertRaises(DududaError):
            _merger().merge(
                value,
                _rules(value),
                model,
                model_status=PerceptionModelStatus.VALID,
            )

    def test_model_cannot_expand_the_rule_authoritative_response_target(self) -> None:
        base = context()
        value = context(
            identities=(
                *base.identities,
                PerceptionIdentity(1, "identity:other", False),
            )
        )
        model = replace(
            _projection(value),
            target_identity_refs=("identity:user", "identity:other"),
        )

        result = _merger().merge(
            value,
            _rules(value),
            model,
            model_status=PerceptionModelStatus.VALID,
        )

        self.assertEqual(result.target_identity_refs, ("identity:user",))
        self.assertTrue(result.conflicting_evidence)
        self.assertEqual(result.confidence, 0.59)

    def test_plan_fingerprint_ignores_result_identity(self) -> None:
        value = context()
        first = _merger("result-first").merge(
            value,
            _rules(value),
            _projection(value),
            model_status=PerceptionModelStatus.VALID,
        )
        second = replace(first, result_id="result-second")

        self.assertEqual(
            perception_result_fingerprint(first),
            perception_result_fingerprint(second),
        )

    def test_duplicate_candidate_evidence_is_merged_with_a_hard_bound(self) -> None:
        value = context(limits=limits(max_evidence_refs_per_item=1))
        payload = model_payload(
            topics=[
                {
                    "topic_id": "topic:a",
                    "label": "same topic",
                    "confidence": 0.9,
                    "evidence_refs": ["message:bot"],
                },
                {
                    "topic_id": "topic:b",
                    "label": "same topic",
                    "confidence": 0.8,
                    "evidence_refs": ["message:current"],
                },
            ]
        )

        result = _merger().merge(
            value,
            _rules(value),
            _projection(value, payload),
            model_status=PerceptionModelStatus.VALID,
        )

        self.assertEqual(len(result.topics), 1)
        self.assertEqual(len(result.topics[0].evidence_refs), 1)

    def test_final_result_validator_rechecks_semantic_evidence(self) -> None:
        value = context()
        result = _merger().merge(
            value,
            _rules(value),
            _projection(value),
            model_status=PerceptionModelStatus.VALID,
        )
        forged_topic = replace(
            result.topics[0],
            evidence_refs=("message:outside",),
        )

        with self.assertRaises(DududaError):
            validate_perception_result(
                value,
                replace(result, topics=(forged_topic,)),
            )


if __name__ == "__main__":
    unittest.main()
