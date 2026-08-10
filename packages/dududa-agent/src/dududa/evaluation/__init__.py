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
    from .s09 import generate_s09_bundle, run_s09_eval
    from .semantic_v2 import (
        check_semantic_schema_pilot,
        run_semantic_schema_pilot,
    )

__all__ = [
    "CapabilityRetrievalEvalCase",
    "CapabilityRetrievalEvalReport",
    "CapabilityRuntimeEvalCase",
    "CapabilityRuntimeEvalReport",
    "check_semantic_schema_pilot",
    "evaluate_capability_retrieval",
    "evaluate_capability_runtime",
    "generate_s09_bundle",
    "run_s09_eval",
    "run_semantic_schema_pilot",
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
    if name in {"check_semantic_schema_pilot", "run_semantic_schema_pilot"}:
        return getattr(import_module(".semantic_v2", __name__), name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
