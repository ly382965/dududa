from importlib import import_module
from typing import TYPE_CHECKING

from .contracts import (
    CurrentMessageContext,
    DeliveryReconciliationAction,
    DeliveryReconciliationReceipt,
    DirectChatContent,
    DirectChatExecutionReceipt,
    DirectChatFailureReceipt,
    OfflinePreprocessReceipt,
    OfflineRuntimePolicySnapshot,
    PerceptionExecutionReceipt,
    RuntimeAdmissionAction,
    RuntimeIdentityBinding,
    ShadowRunReceipt,
    current_message_context_digest,
    direct_chat_content_digest,
)
from .state import (
    CompletionReceipt,
    ConnectorResult,
    Outcome,
    RuntimeCheckpoint,
    RuntimeCommitDisposition,
    RuntimeCommitRequest,
    RuntimeCommitResult,
    RuntimeDedupRecord,
    RuntimeInvocationOptions,
    RuntimePhase,
    RuntimeResult,
    RuntimeSelectionSummary,
    RuntimeStartRequest,
    RuntimeState,
    TraceEvent,
    TraceSummary,
    runtime_start_digest,
    transition,
    validate_runtime_state,
)

if TYPE_CHECKING:
    from .budget import RuntimeModelBudgetPlan
    from .composition import (
        DeterministicPersonaRenderer,
        DeterministicPersonaRendererConfig,
        DeterministicRenderValidator,
        FinalResponseSafetyValidator,
        MinimalResponseComposer,
        MinimalResponseComposerConfig,
    )
    from .context import (
        CurrentMessageContextBuilder,
        CurrentMessageContextBuilderConfig,
    )
    from .delivery import (
        DeliveryRequestBuilder,
        DeliveryRequestBuilderConfig,
        DeliveryRequestPlan,
        acknowledge_delivery_state,
        delivery_acknowledgement_states,
        reconcile_completed_delivery,
    )
    from .direct_chat import (
        DirectChatModelCall,
        DirectChatModelCallConfig,
        RuntimeDirectChatFailure,
    )
    from .offline import OfflineDeliveryDriver, OfflineDeliveryRunResult
    from .orchestrator import (
        OfflineRuntimeOrchestrator,
        OfflineRuntimeOrchestratorConfig,
    )
    from .perception import (
        HybridPerceptionEngine,
        RouterBackedModelPerception,
        RouterBackedModelPerceptionConfig,
        RuntimeModelPerceptionFailure,
        serialize_perception_context,
    )
    from .selection import (
        project_s10_decision_signals,
        project_tier_selection_context,
        select_model_tier,
        validate_selection_configuration,
    )
    from .shadow import ShadowRunner
    from .store import InMemoryRuntimeStateStore, InMemoryRuntimeStateStoreConfig

__all__ = [
    "CompletionReceipt",
    "ConnectorResult",
    "CurrentMessageContext",
    "CurrentMessageContextBuilder",
    "CurrentMessageContextBuilderConfig",
    "DeliveryReconciliationAction",
    "DeliveryReconciliationReceipt",
    "DeliveryRequestBuilder",
    "DeliveryRequestBuilderConfig",
    "DeliveryRequestPlan",
    "DeterministicPersonaRenderer",
    "DeterministicPersonaRendererConfig",
    "DeterministicRenderValidator",
    "DirectChatContent",
    "DirectChatExecutionReceipt",
    "DirectChatFailureReceipt",
    "DirectChatModelCall",
    "DirectChatModelCallConfig",
    "FinalResponseSafetyValidator",
    "HybridPerceptionEngine",
    "InMemoryRuntimeStateStore",
    "InMemoryRuntimeStateStoreConfig",
    "MinimalResponseComposer",
    "MinimalResponseComposerConfig",
    "OfflineDeliveryDriver",
    "OfflineDeliveryRunResult",
    "OfflinePreprocessReceipt",
    "OfflineRuntimeOrchestrator",
    "OfflineRuntimeOrchestratorConfig",
    "OfflineRuntimePolicySnapshot",
    "Outcome",
    "PerceptionExecutionReceipt",
    "RouterBackedModelPerception",
    "RouterBackedModelPerceptionConfig",
    "RuntimeAdmissionAction",
    "RuntimeIdentityBinding",
    "RuntimeInvocationOptions",
    "RuntimeModelBudgetPlan",
    "RuntimeCheckpoint",
    "RuntimeCommitDisposition",
    "RuntimeCommitRequest",
    "RuntimeCommitResult",
    "RuntimeDedupRecord",
    "RuntimePhase",
    "RuntimeResult",
    "RuntimeDirectChatFailure",
    "RuntimeModelPerceptionFailure",
    "RuntimeSelectionSummary",
    "RuntimeStartRequest",
    "RuntimeState",
    "ShadowRunReceipt",
    "ShadowRunner",
    "TraceEvent",
    "TraceSummary",
    "acknowledge_delivery_state",
    "current_message_context_digest",
    "delivery_acknowledgement_states",
    "direct_chat_content_digest",
    "project_s10_decision_signals",
    "project_tier_selection_context",
    "reconcile_completed_delivery",
    "runtime_start_digest",
    "select_model_tier",
    "serialize_perception_context",
    "transition",
    "validate_runtime_state",
    "validate_selection_configuration",
]

_LAZY_EXPORTS = {
    "RuntimeModelBudgetPlan": ".budget",
    "DeterministicPersonaRenderer": ".composition",
    "DeterministicPersonaRendererConfig": ".composition",
    "DeterministicRenderValidator": ".composition",
    "FinalResponseSafetyValidator": ".composition",
    "MinimalResponseComposer": ".composition",
    "MinimalResponseComposerConfig": ".composition",
    "CurrentMessageContextBuilder": ".context",
    "CurrentMessageContextBuilderConfig": ".context",
    "DeliveryRequestBuilder": ".delivery",
    "DeliveryRequestBuilderConfig": ".delivery",
    "DeliveryRequestPlan": ".delivery",
    "acknowledge_delivery_state": ".delivery",
    "delivery_acknowledgement_states": ".delivery",
    "reconcile_completed_delivery": ".delivery",
    "DirectChatModelCall": ".direct_chat",
    "DirectChatModelCallConfig": ".direct_chat",
    "RuntimeDirectChatFailure": ".direct_chat",
    "OfflineDeliveryDriver": ".offline",
    "OfflineDeliveryRunResult": ".offline",
    "OfflineRuntimeOrchestrator": ".orchestrator",
    "OfflineRuntimeOrchestratorConfig": ".orchestrator",
    "HybridPerceptionEngine": ".perception",
    "RouterBackedModelPerception": ".perception",
    "RouterBackedModelPerceptionConfig": ".perception",
    "RuntimeModelPerceptionFailure": ".perception",
    "serialize_perception_context": ".perception",
    "project_s10_decision_signals": ".selection",
    "project_tier_selection_context": ".selection",
    "select_model_tier": ".selection",
    "validate_selection_configuration": ".selection",
    "ShadowRunner": ".shadow",
    "InMemoryRuntimeStateStore": ".store",
    "InMemoryRuntimeStateStoreConfig": ".store",
}


def __getattr__(name: str) -> object:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        return getattr(import_module(module_name, __name__), name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
