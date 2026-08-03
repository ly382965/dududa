from importlib import import_module

from .state import (
    ConnectorResult,
    Outcome,
    RuntimeInvocationOptions,
    RuntimePhase,
    RuntimeResult,
    RuntimeStartRequest,
    RuntimeState,
    runtime_start_digest,
    transition,
)

__all__ = [
    "ConnectorResult",
    "Outcome",
    "RuntimeInvocationOptions",
    "RuntimePhase",
    "RuntimeResult",
    "RuntimeStartRequest",
    "RuntimeState",
    "HybridPerceptionEngine",
    "RouterBackedModelPerception",
    "RouterBackedModelPerceptionConfig",
    "project_tier_selection_context",
    "runtime_start_digest",
    "select_model_tier",
    "serialize_perception_context",
    "transition",
    "validate_selection_configuration",
]


def __getattr__(name: str) -> object:
    if name in {
        "HybridPerceptionEngine",
        "RouterBackedModelPerception",
        "RouterBackedModelPerceptionConfig",
        "serialize_perception_context",
    }:
        return getattr(import_module(".perception", __name__), name)
    if name in {
        "project_tier_selection_context",
        "select_model_tier",
        "validate_selection_configuration",
    }:
        return getattr(import_module(".selection", __name__), name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
