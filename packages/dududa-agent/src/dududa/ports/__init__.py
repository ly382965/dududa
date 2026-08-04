"""Framework-neutral Protocol ports owned by Dududa core."""

from typing import TYPE_CHECKING

from .context import (
    CancellationToken,
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
    ServiceCallContext,
    ServicePrincipal,
)

if TYPE_CHECKING:
    from .attachments import AttachmentRepository, BoundedAttachmentStream
    from .memory import MemoryRepository, ScopeSelectorVerifier
    from .models import (
        BootstrapModelTierPolicy,
        ModelAdmissionController,
        ModelCatalogPublisher,
        ModelInvocationEstimator,
        ModelOperationalStateRegistry,
        ModelOutputCodec,
        ModelProvider,
        ModelRouter,
        ModelRoutingRegistry,
        ModelTierPolicy,
    )
    from .perception import (
        ModelPerception,
        PerceptionEngine,
        PerceptionMerger,
        PerceptionValidator,
        RulePerception,
        SocialDecisionEngine,
        TaskComplexityAssessor,
    )
    from .output import OutputAdapter
    from .runtime import (
        AgentRuntime,
        OfflineFinalResponseValidator,
        OfflinePersonaRenderer,
        OfflineRenderValidator,
        OfflineResponseComposer,
        InputConnector,
        RuntimePerceptionEngine,
        RuntimeStateStore,
        ShadowReceiptSink,
    )

__all__ = [
    "AgentRuntime",
    "AttachmentRepository",
    "BoundedAttachmentStream",
    "BootstrapModelTierPolicy",
    "CancellationToken",
    "OfflineFinalResponseValidator",
    "OfflinePersonaRenderer",
    "OfflineRenderValidator",
    "OfflineResponseComposer",
    "InputConnector",
    "ManualCancellationToken",
    "MemoryRepository",
    "ModelAdmissionController",
    "ModelCatalogPublisher",
    "ModelInvocationEstimator",
    "ModelOperationalStateRegistry",
    "ModelOutputCodec",
    "ModelProvider",
    "ModelRouter",
    "ModelRoutingRegistry",
    "ModelTierPolicy",
    "ModelPerception",
    "NeverCancelled",
    "OutputAdapter",
    "PortCallContext",
    "PerceptionEngine",
    "PerceptionMerger",
    "PerceptionValidator",
    "RulePerception",
    "RuntimePerceptionEngine",
    "RuntimeStateStore",
    "ShadowReceiptSink",
    "ScopeSelectorVerifier",
    "ServiceCallContext",
    "ServicePrincipal",
    "SocialDecisionEngine",
    "TaskComplexityAssessor",
]


def __getattr__(name: str) -> object:
    if name in {"MemoryRepository", "ScopeSelectorVerifier"}:
        from .memory import MemoryRepository, ScopeSelectorVerifier

        return {
            "MemoryRepository": MemoryRepository,
            "ScopeSelectorVerifier": ScopeSelectorVerifier,
        }[name]
    if name in {"AttachmentRepository", "BoundedAttachmentStream"}:
        from .attachments import AttachmentRepository, BoundedAttachmentStream

        return {
            "AttachmentRepository": AttachmentRepository,
            "BoundedAttachmentStream": BoundedAttachmentStream,
        }[name]
    if name == "OutputAdapter":
        from .output import OutputAdapter

        return OutputAdapter
    if name in {
        "BootstrapModelTierPolicy",
        "ModelAdmissionController",
        "ModelCatalogPublisher",
        "ModelInvocationEstimator",
        "ModelOperationalStateRegistry",
        "ModelOutputCodec",
        "ModelProvider",
        "ModelRouter",
        "ModelRoutingRegistry",
        "ModelTierPolicy",
    }:
        from .models import (
            BootstrapModelTierPolicy,
            ModelAdmissionController,
            ModelCatalogPublisher,
            ModelInvocationEstimator,
            ModelOperationalStateRegistry,
            ModelOutputCodec,
            ModelProvider,
            ModelRouter,
            ModelRoutingRegistry,
            ModelTierPolicy,
        )

        return {
            "BootstrapModelTierPolicy": BootstrapModelTierPolicy,
            "ModelAdmissionController": ModelAdmissionController,
            "ModelCatalogPublisher": ModelCatalogPublisher,
            "ModelInvocationEstimator": ModelInvocationEstimator,
            "ModelOperationalStateRegistry": ModelOperationalStateRegistry,
            "ModelOutputCodec": ModelOutputCodec,
            "ModelProvider": ModelProvider,
            "ModelRouter": ModelRouter,
            "ModelRoutingRegistry": ModelRoutingRegistry,
            "ModelTierPolicy": ModelTierPolicy,
        }[name]
    if name in {
        "ModelPerception",
        "PerceptionEngine",
        "PerceptionMerger",
        "PerceptionValidator",
        "RulePerception",
        "SocialDecisionEngine",
        "TaskComplexityAssessor",
    }:
        from .perception import (
            ModelPerception,
            PerceptionEngine,
            PerceptionMerger,
            PerceptionValidator,
            RulePerception,
            SocialDecisionEngine,
            TaskComplexityAssessor,
        )

        return {
            "ModelPerception": ModelPerception,
            "PerceptionEngine": PerceptionEngine,
            "PerceptionMerger": PerceptionMerger,
            "PerceptionValidator": PerceptionValidator,
            "RulePerception": RulePerception,
            "SocialDecisionEngine": SocialDecisionEngine,
            "TaskComplexityAssessor": TaskComplexityAssessor,
        }[name]
    if name in {
        "AgentRuntime",
        "OfflineFinalResponseValidator",
        "OfflinePersonaRenderer",
        "OfflineRenderValidator",
        "OfflineResponseComposer",
        "InputConnector",
        "RuntimePerceptionEngine",
        "RuntimeStateStore",
        "ShadowReceiptSink",
    }:
        from .runtime import (
            AgentRuntime,
            OfflineFinalResponseValidator,
            OfflinePersonaRenderer,
            OfflineRenderValidator,
            OfflineResponseComposer,
            InputConnector,
            RuntimePerceptionEngine,
            RuntimeStateStore,
            ShadowReceiptSink,
        )

        return {
            "AgentRuntime": AgentRuntime,
            "OfflineFinalResponseValidator": OfflineFinalResponseValidator,
            "OfflinePersonaRenderer": OfflinePersonaRenderer,
            "OfflineRenderValidator": OfflineRenderValidator,
            "OfflineResponseComposer": OfflineResponseComposer,
            "InputConnector": InputConnector,
            "RuntimePerceptionEngine": RuntimePerceptionEngine,
            "RuntimeStateStore": RuntimeStateStore,
            "ShadowReceiptSink": ShadowReceiptSink,
        }[name]
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
