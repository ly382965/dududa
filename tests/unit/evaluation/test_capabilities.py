from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from dududa.capabilities import (
    CapabilityRunRequest,
    CapabilityRunStatus,
    capability_run_request_digest,
)
from dududa.capabilities.retrieval import DeterministicCapabilityRetriever
from dududa.evaluation.capabilities import (
    CapabilityRetrievalEvalCase,
    CapabilityRuntimeEvalCase,
    evaluate_capability_retrieval,
    evaluate_capability_runtime,
)

from tests.unit.capabilities.test_executor import execution_call
from tests.unit.capabilities.test_registry import catalog_fixture
from tests.unit.capabilities.test_retrieval import (
    StaticHealthRegistry,
    authorization_for,
    catalog_for,
    health_for,
    request_for,
    retrieval_call,
)
from tests.unit.runtime.test_capabilities import _capability_harness


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


class CapabilityRuntimeEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_uses_receipt_evidence_and_fixed_denominators(self) -> None:
        fixture, runtime = await _capability_harness()
        source = fixture.retrieval_request
        request_values = {
            "schema_version": 1,
            "query": source.query,
            "actor": source.actor,
            "conversation_scope": source.conversation_scope,
            "data_classification": source.data_classification,
            "available_input_schemas": source.available_input_schemas,
            "maximum_attempts": 4,
        }
        request = CapabilityRunRequest(
            request_digest=capability_run_request_digest(request_values),
            **request_values,
        )
        cases = (
            CapabilityRuntimeEvalCase(
                case_id="synthetic-course-cache-hit",
                request=request,
                expected_status=CapabilityRunStatus.COMPLETED,
                assess_plan=True,
                assess_arguments=True,
            ),
            CapabilityRuntimeEvalCase(
                case_id="synthetic-course-budget-denied",
                request=request,
                expected_status=CapabilityRunStatus.DEFERRED,
                assess_plan=False,
                assess_arguments=False,
            ),
        )

        report = await evaluate_capability_runtime(
            runtime,
            cases,
            call_factory=lambda case: replace(
                execution_call(
                    cost_units=(
                        Decimal(0)
                        if case.case_id.endswith("budget-denied")
                        else Decimal(100)
                    )
                ),
                run_id=f"eval-{case.case_id}",
            ),
        )

        self.assertEqual(report.case_count, 2)
        self.assertEqual(report.plan_assessed_cases, 1)
        self.assertEqual(report.valid_plan_evidence_cases, 1)
        self.assertEqual(report.plan_validity_rate, Decimal(1))
        self.assertEqual(report.argument_assessed_cases, 1)
        self.assertEqual(report.valid_argument_evidence_cases, 1)
        self.assertEqual(report.argument_validity_rate, Decimal(1))
        self.assertEqual(report.completed_cases, 1)
        self.assertEqual(report.completion_rate, Decimal("0.5"))
        self.assertEqual(report.expected_status_matches, 2)
        self.assertEqual(report.expected_status_rate, Decimal(1))
        self.assertEqual(report.attempts_total, 1)
        self.assertEqual(report.average_attempts, Decimal("0.5"))
        self.assertEqual(
            report.report_digest,
            "dududa-c14n-v1:evaluation.capability-runtime:v1:sha-256:"
            "8aad9bc1374d3d388e674d7a96460a343aec6268f1fe48f10c91322857927ca3",
        )


if __name__ == "__main__":
    unittest.main()
