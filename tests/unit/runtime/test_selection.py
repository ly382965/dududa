from __future__ import annotations

from dataclasses import replace
import inspect
import unittest

from dududa.domain.primitives import DigestString, PrivacyLevel
from dududa.errors import DududaError
from dududa.models.contracts import ModelRole
from dududa.models.tiering import DeterministicModelTierPolicy
from dududa.perception.complexity import default_complexity_assessor_config
from dududa.perception.merge import PerceptionMergeConfig
from dududa.runtime.selection import (
    project_tier_selection_context,
    select_model_tier,
    validate_selection_configuration,
)

from tests.unit.models.test_tiering import NOW, _assessment, _budget, _definition
from tests.unit.perception.helpers import revision


def _merge_config(**overrides: float) -> PerceptionMergeConfig:
    values = {
        "pipeline_revision": revision("perception-pipeline"),
        "merger_revision": revision("perception-merger"),
        "validator_revision": revision("perception-validator"),
        "fallback_confidence_ceiling": 0.59,
        "conflict_confidence_ceiling": 0.59,
    }
    values.update(overrides)
    return PerceptionMergeConfig(**values)


class RuntimeSelectionTests(unittest.TestCase):
    def test_projection_accepts_no_tier_provider_model_or_raw_message(self) -> None:
        parameters = inspect.signature(project_tier_selection_context).parameters
        forbidden = {"tier", "provider_id", "model_id", "route_hint", "message"}
        self.assertFalse(forbidden & set(parameters))

        context = project_tier_selection_context(
            selection_id="selection-1",
            role=ModelRole.DIRECT_CHAT,
            assessment=_assessment(),
            content_input_tokens_upper_bound=512,
            data_classification=PrivacyLevel.CONVERSATION,
            budget=_budget(),
        )
        self.assertIs(context.role, ModelRole.DIRECT_CHAT)

    def test_cross_module_confidence_and_reason_codes_are_validated(self) -> None:
        assessor = default_complexity_assessor_config(revision("complexity-assessor"))
        validate_selection_configuration(
            merge=_merge_config(),
            assessor=assessor,
            tier=_definition(),
        )

        with self.assertRaises(DududaError):
            validate_selection_configuration(
                merge=_merge_config(fallback_confidence_ceiling=0.6),
                assessor=assessor,
                tier=_definition(),
            )
        with self.assertRaises(DududaError):
            validate_selection_configuration(
                merge=_merge_config(),
                assessor=assessor,
                tier=replace(
                    _definition(),
                    high_complexity_reason_codes=frozenset(
                        {"deep_reasoning", "impossible_signal"}
                    ),
                ),
            )

    def test_runtime_revalidates_policy_decision_before_router_use(self) -> None:
        context = project_tier_selection_context(
            selection_id="selection-1",
            role=ModelRole.DIRECT_CHAT,
            assessment=_assessment(),
            content_input_tokens_upper_bound=512,
            data_classification=PrivacyLevel.CONVERSATION,
            budget=_budget(),
        )
        definition = _definition()
        real = DeterministicModelTierPolicy(id_factory=lambda: "decision-1")

        class ForgingPolicy:
            def decide(self, context, definition, *, now):
                decision = real.decide(context, definition, now=now)
                return replace(
                    decision,
                    selection_fingerprint=DigestString("forged"),
                )

        with self.assertRaises(DududaError):
            select_model_tier(
                context=context,
                definition=definition,
                policy=ForgingPolicy(),
                now=NOW,
            )

        decision = select_model_tier(
            context=context,
            definition=definition,
            policy=real,
            now=NOW,
        )
        self.assertEqual(decision.decision_id, "decision-1")


if __name__ == "__main__":
    unittest.main()
