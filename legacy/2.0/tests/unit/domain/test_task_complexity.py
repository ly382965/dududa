from __future__ import annotations

import math
import unittest
from dataclasses import fields, replace

from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.domain.task import (
    ContextPressure,
    TaskAmbiguity,
    TaskComplexityAssessment,
    TaskComplexityLevel,
    TaskReasoningDepth,
)
from dududa.errors import DududaError
from dududa.models.digests import task_complexity_assessment_digest


def _revision() -> ComponentRevision:
    return ComponentRevision(
        component_id="complexity-assessor",
        implementation_version="1.0.0",
        config_revision="rules-v1",
        artifact_digest=DigestString("artifact-digest"),
    )


def _assessment() -> TaskComplexityAssessment:
    return TaskComplexityAssessment(
        schema_version=1,
        assessment_id="assessment-1",
        level=TaskComplexityLevel.MEDIUM,
        confidence=0.75,
        task_kind="direct_chat",
        context_pressure=ContextPressure.LOW,
        reasoning_depth=TaskReasoningDepth.MULTI_STEP,
        expected_tool_steps=0,
        ambiguity=TaskAmbiguity.MEDIUM,
        verification_required=False,
        conflicting_evidence=False,
        reason_codes=("multi_constraint",),
        evidence_refs=("message:m1",),
        assessor_revision=_revision(),
    )


class TaskComplexityContractTests(unittest.TestCase):
    def test_assessment_is_digestible_and_has_no_route_authority(self) -> None:
        assessment = _assessment()
        digest = task_complexity_assessment_digest(assessment)

        self.assertEqual(digest, task_complexity_assessment_digest(assessment))
        self.assertNotEqual(
            digest,
            task_complexity_assessment_digest(
                replace(assessment, reason_codes=("long_dependency_chain",))
            ),
        )
        names = {field.name for field in fields(TaskComplexityAssessment)}
        self.assertTrue(
            {"tier", "model_tier", "provider_id", "model_id", "endpoint_id"}.isdisjoint(
                names
            )
        )

    def test_invalid_confidence_enum_and_counts_fail_closed(self) -> None:
        for changes in (
            {"confidence": math.nan},
            {"confidence": 1.01},
            {"level": "medium"},
            {"expected_tool_steps": -1},
            {"verification_required": 1},
            {"conflicting_evidence": 0},
            {"reason_codes": ()},
            {"reason_codes": "abc"},
            {"evidence_refs": ("message:m1", "message:m1")},
        ):
            with self.subTest(changes=changes), self.assertRaises(DududaError):
                replace(_assessment(), **changes)


if __name__ == "__main__":
    unittest.main()
