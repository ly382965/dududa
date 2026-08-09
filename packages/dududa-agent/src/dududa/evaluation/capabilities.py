from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from dududa.capabilities.contracts import (
    CapabilityRetrievalRequest,
    CapabilityRetrievalResult,
)
from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString
from dududa.errors import validation_error
from dududa.ports.capabilities import CapabilityRetriever
from dududa.ports.context import PortCallContext


@dataclass(frozen=True, slots=True)
class CapabilityRetrievalEvalCase:
    case_id: str
    request: CapabilityRetrievalRequest
    expected_capability_ids: frozenset[str]
    forbidden_capability_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.expected_capability_ids, (str, bytes)) or isinstance(
            self.forbidden_capability_ids, (str, bytes)
        ):
            raise validation_error("invalid_capability_retrieval_eval_case")
        expected_ids = frozenset(self.expected_capability_ids)
        forbidden_ids = frozenset(self.forbidden_capability_ids)
        if (
            not isinstance(self.case_id, str)
            or not self.case_id.strip()
            or not isinstance(self.request, CapabilityRetrievalRequest)
            or not expected_ids
            or expected_ids & forbidden_ids
            or any(
                not isinstance(item, str) or not item.strip()
                for item in (expected_ids | forbidden_ids)
            )
        ):
            raise validation_error("invalid_capability_retrieval_eval_case")
        object.__setattr__(
            self,
            "expected_capability_ids",
            expected_ids,
        )
        object.__setattr__(
            self,
            "forbidden_capability_ids",
            forbidden_ids,
        )


@dataclass(frozen=True, slots=True)
class CapabilityRetrievalEvalReport:
    schema_version: int
    report_digest: DigestString
    case_count: int
    expected_total: int
    retrieved_expected: int
    selected_total: int
    exposed_forbidden: int
    empty_result_cases: int

    def __post_init__(self) -> None:
        values = (
            self.case_count,
            self.expected_total,
            self.retrieved_expected,
            self.selected_total,
            self.exposed_forbidden,
            self.empty_result_cases,
        )
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or any(type(value) is not int or value < 0 for value in values)
            or self.case_count < 1
            or self.retrieved_expected > self.expected_total
            or self.exposed_forbidden > self.selected_total
            or self.empty_result_cases > self.case_count
        ):
            raise validation_error("invalid_capability_retrieval_eval_report")
        expected = _report_digest(
            {
                "schema_version": self.schema_version,
                "case_count": self.case_count,
                "expected_total": self.expected_total,
                "retrieved_expected": self.retrieved_expected,
                "selected_total": self.selected_total,
                "exposed_forbidden": self.exposed_forbidden,
                "empty_result_cases": self.empty_result_cases,
            }
        )
        if self.report_digest != expected:
            raise validation_error("capability_retrieval_eval_digest_mismatch")

    @property
    def recall_at_k(self) -> Decimal:
        return Decimal(self.retrieved_expected) / Decimal(self.expected_total)

    @property
    def ineligible_exposure_rate(self) -> Decimal:
        if self.selected_total == 0:
            return Decimal(0)
        return Decimal(self.exposed_forbidden) / Decimal(self.selected_total)


async def evaluate_capability_retrieval(
    retriever: CapabilityRetriever,
    cases: tuple[CapabilityRetrievalEvalCase, ...],
    *,
    call_factory: Callable[[CapabilityRetrievalEvalCase], PortCallContext],
) -> CapabilityRetrievalEvalReport:
    if isinstance(cases, (str, bytes)):
        raise validation_error("invalid_capability_retrieval_eval_cases")
    cases = tuple(cases)
    if (
        not cases
        or len(cases) > 10_000
        or any(not isinstance(item, CapabilityRetrievalEvalCase) for item in cases)
        or len({item.case_id for item in cases}) != len(cases)
    ):
        raise validation_error("invalid_capability_retrieval_eval_cases")
    expected_total = 0
    retrieved_expected = 0
    selected_total = 0
    exposed_forbidden = 0
    empty_result_cases = 0
    for case in cases:
        result = await retriever.retrieve(
            case.request,
            call=call_factory(case),
        )
        if (
            not isinstance(result, CapabilityRetrievalResult)
            or result.request_digest != case.request.request_digest
        ):
            raise validation_error("invalid_capability_retrieval_eval_result")
        selected = frozenset(item.capability_id for item in result.candidates)
        expected_total += len(case.expected_capability_ids)
        retrieved_expected += len(selected & case.expected_capability_ids)
        selected_total += len(selected)
        exposed_forbidden += len(selected & case.forbidden_capability_ids)
        empty_result_cases += not selected
    values = {
        "schema_version": 1,
        "case_count": len(cases),
        "expected_total": expected_total,
        "retrieved_expected": retrieved_expected,
        "selected_total": selected_total,
        "exposed_forbidden": exposed_forbidden,
        "empty_result_cases": empty_result_cases,
    }
    return CapabilityRetrievalEvalReport(
        report_digest=_report_digest(values),
        **values,
    )


def _report_digest(value: object) -> DigestString:
    return canonical_digest(value, domain="evaluation.capability-retrieval:v1")


__all__ = [
    "CapabilityRetrievalEvalCase",
    "CapabilityRetrievalEvalReport",
    "evaluate_capability_retrieval",
]
