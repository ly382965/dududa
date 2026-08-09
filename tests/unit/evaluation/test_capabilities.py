from __future__ import annotations

import unittest
from decimal import Decimal

from dududa.capabilities.retrieval import DeterministicCapabilityRetriever
from dududa.evaluation.capabilities import (
    CapabilityRetrievalEvalCase,
    evaluate_capability_retrieval,
)

from tests.unit.capabilities.test_registry import catalog_fixture
from tests.unit.capabilities.test_retrieval import (
    StaticHealthRegistry,
    authorization_for,
    catalog_for,
    health_for,
    request_for,
    retrieval_call,
)


class CapabilityRetrievalEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_keeps_exact_recall_and_exposure_denominators(self) -> None:
        _, definition, _ = catalog_fixture()
        registry, catalog = catalog_for((definition,))
        authorization = authorization_for((definition,))
        retriever = DeterministicCapabilityRetriever(
            registry,
            StaticHealthRegistry(health_for(catalog)),
            authorization,
            authorization,
            clock=lambda: catalog.acquired_at,
        )
        request = request_for(definition, limit=1)
        cases = (
            CapabilityRetrievalEvalCase(
                "eligible",
                request,
                frozenset({definition.capability_id}),
                frozenset({"fixture.forbidden.read.v1"}),
            ),
            CapabilityRetrievalEvalCase(
                "budget-denied",
                request,
                frozenset({definition.capability_id}),
                frozenset({"fixture.forbidden.read.v1"}),
            ),
        )
        report = await evaluate_capability_retrieval(
            retriever,
            cases,
            call_factory=lambda case: retrieval_call(
                cost_units=(Decimal(10) if case.case_id == "eligible" else Decimal(0))
            ),
        )
        self.assertEqual(report.case_count, 2)
        self.assertEqual(report.expected_total, 2)
        self.assertEqual(report.retrieved_expected, 1)
        self.assertEqual(report.recall_at_k, Decimal("0.5"))
        self.assertEqual(report.selected_total, 1)
        self.assertEqual(report.exposed_forbidden, 0)
        self.assertEqual(report.ineligible_exposure_rate, Decimal(0))
        self.assertEqual(report.empty_result_cases, 1)
        self.assertEqual(
            report.report_digest,
            "dududa-c14n-v1:evaluation.capability-retrieval:v1:sha-256:"
            "91b7582c3b1538c8ff1fd23bc2af247942ef5ce9453c8cad4463aa51a0da3985",
        )


if __name__ == "__main__":
    unittest.main()
