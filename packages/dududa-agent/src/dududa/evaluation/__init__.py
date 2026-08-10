"""Offline, reproducible evaluation utilities."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .capabilities import (
        CapabilityRetrievalEvalCase,
        CapabilityRetrievalEvalReport,
        CapabilityRuntimeEvalCase,
        CapabilityRuntimeEvalReport,
        evaluate_capability_retrieval,
        evaluate_capability_runtime,
    )
    from .memory import (
        check_memory_retrieval_bundle,
        generate_memory_retrieval_bundle,
        run_memory_retrieval_eval,
    )
    from .response_profile import (
        check_response_profile_bundle,
        generate_response_profile_bundle,
        run_response_profile_eval,
    )
    from .s09 import generate_s09_bundle, run_s09_eval
    from .semantic_v2 import (
        check_semantic_schema_pilot,
        run_semantic_schema_pilot,
    )
    from .suite import (
        EvaluationSuiteError,
        SuiteCatalog,
        load_suite_catalog,
        run_suite_profile,
    )

__all__ = [
    "CapabilityRetrievalEvalCase",
    "CapabilityRetrievalEvalReport",
    "CapabilityRuntimeEvalCase",
    "CapabilityRuntimeEvalReport",
    "EvaluationSuiteError",
    "SuiteCatalog",
    "check_memory_retrieval_bundle",
    "check_response_profile_bundle",
    "check_semantic_schema_pilot",
    "evaluate_capability_retrieval",
    "evaluate_capability_runtime",
    "generate_memory_retrieval_bundle",
    "generate_response_profile_bundle",
    "generate_s09_bundle",
    "load_suite_catalog",
    "run_memory_retrieval_eval",
    "run_response_profile_eval",
    "run_s09_eval",
    "run_semantic_schema_pilot",
    "run_suite_profile",
]


def __getattr__(name: str) -> object:
    if name in {
        "CapabilityRetrievalEvalCase",
        "CapabilityRetrievalEvalReport",
        "CapabilityRuntimeEvalCase",
        "CapabilityRuntimeEvalReport",
        "evaluate_capability_retrieval",
        "evaluate_capability_runtime",
    }:
        return getattr(import_module(".capabilities", __name__), name)
    if name in {"generate_s09_bundle", "run_s09_eval"}:
        return getattr(import_module(".s09", __name__), name)
    if name in {
        "check_response_profile_bundle",
        "generate_response_profile_bundle",
        "run_response_profile_eval",
    }:
        return getattr(import_module(".response_profile", __name__), name)
    if name in {
        "check_memory_retrieval_bundle",
        "generate_memory_retrieval_bundle",
        "run_memory_retrieval_eval",
    }:
        return getattr(import_module(".memory", __name__), name)
    if name in {"check_semantic_schema_pilot", "run_semantic_schema_pilot"}:
        return getattr(import_module(".semantic_v2", __name__), name)
    if name in {
        "EvaluationSuiteError",
        "SuiteCatalog",
        "load_suite_catalog",
        "run_suite_profile",
    }:
        return getattr(import_module(".suite", __name__), name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
