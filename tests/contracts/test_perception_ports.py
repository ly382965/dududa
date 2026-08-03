from __future__ import annotations

from inspect import Parameter, signature
import unittest

from dududa.ports.perception import (
    ModelPerception,
    PerceptionEngine,
    PerceptionMerger,
    PerceptionValidator,
    RulePerception,
    SocialDecisionEngine,
    TaskComplexityAssessor,
)


class _Rules:
    def perceive(self, context):
        raise NotImplementedError


class _Model:
    async def perceive(self, context, *, call):
        raise NotImplementedError


class _Engine(_Model):
    pass


class _Validator:
    def validate_model(self, context, projection):
        return projection

    def validate_result(self, context, result):
        return result


class _Merger:
    def merge(
        self,
        context,
        rules,
        model,
        *,
        model_status,
        model_route_receipt_digest=None,
    ):
        raise NotImplementedError


class _Assessor:
    def assess(self, context, perception):
        raise NotImplementedError


class _Social:
    async def decide(self, perception, signals, *, call):
        raise NotImplementedError


class PerceptionPortContractTests(unittest.TestCase):
    def test_minimal_implementations_structurally_conform(self) -> None:
        values = (
            (_Rules(), RulePerception),
            (_Model(), ModelPerception),
            (_Engine(), PerceptionEngine),
            (_Validator(), PerceptionValidator),
            (_Merger(), PerceptionMerger),
            (_Assessor(), TaskComplexityAssessor),
            (_Social(), SocialDecisionEngine),
        )
        for implementation, protocol in values:
            with self.subTest(protocol=protocol.__name__):
                self.assertIsInstance(implementation, protocol)

    def test_async_ports_keep_call_keyword_only(self) -> None:
        for method in (_Model.perceive, _Social.decide):
            with self.subTest(method=method.__qualname__):
                parameters = signature(method).parameters
                self.assertIs(parameters["call"].kind, Parameter.KEYWORD_ONLY)


if __name__ == "__main__":
    unittest.main()
