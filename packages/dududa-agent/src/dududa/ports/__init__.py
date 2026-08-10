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
    from .capabilities import (
        ArgumentBinder,
        BoundedCapabilityRuntime,
        CapabilityCatalogPublisher,
        CapabilityHealthRegistry,
        CapabilityProvider,
        CapabilityProviderRegistry,
        CapabilityRegistry,
        CapabilityRetriever,
        CapabilitySchemaValidator,
        ToolExecutor,
        ToolInvocationLedger,
        ToolPlanner,
        ToolPlanValidator,
        ToolResultValidator,
    )
    from .mcp import (
        McpEnvironmentProvider,
        McpSchemaValidator,
        McpSecretResolver,
        McpServerRegistry,
        McpTransportSession,
        McpTransportSessionFactory,
        UnifiedMcpClient,
    )
    from .memory import (
        MemoryAdministration,
        MemoryRanker,
        MemoryRepository,
        MemoryRetrievalPolicy,
        ScopedMemoryRetriever,
        ScopeSelectorVerifier,
    )
    from .models import (
        BootstrapModelTierPolicy,
        ModelAdmissionController,
        ModelCatalogPublisher,
        ModelInvocationEstimator,
        ModelOperationalSnapshotPublisher,
        ModelOperationalSnapshotResolver,
        ModelOperationalStateRegistry,
        ModelOutputCodec,
        ModelProvider,
        ModelRouter,
        ModelRoutingRegistry,
        ModelTierPolicy,
    )
    from .output import OutputAdapter
    from .perception import (
        ModelPerception,
        PerceptionEngine,
        PerceptionMerger,
        PerceptionValidator,
        RulePerception,
        SocialDecisionEngine,
        TaskComplexityAssessor,
    )
    from .responses import ResponseProfilePolicy, VisibleTokenCounter
    from .runtime import (
        AgentRuntime,
        InputConnector,
        OfflineFinalResponseValidator,
        OfflinePersonaRenderer,
        OfflineRenderValidator,
        OfflineResponseComposer,
        RuntimePerceptionEngine,
        RuntimeStateStore,
        ShadowReceiptSink,
    )

__all__ = [
    "AgentRuntime",
    "ArgumentBinder",
    "AttachmentRepository",
    "BootstrapModelTierPolicy",
    "BoundedAttachmentStream",
    "BoundedCapabilityRuntime",
    "CancellationToken",
    "CapabilityCatalogPublisher",
    "CapabilityHealthRegistry",
    "CapabilityProvider",
    "CapabilityProviderRegistry",
    "CapabilityRegistry",
    "CapabilityRetriever",
    "CapabilitySchemaValidator",
    "InputConnector",
    "ManualCancellationToken",
    "McpEnvironmentProvider",
    "McpSchemaValidator",
    "McpSecretResolver",
    "McpServerRegistry",
    "McpTransportSession",
    "McpTransportSessionFactory",
    "MemoryAdministration",
    "MemoryRanker",
    "MemoryRepository",
    "MemoryRetrievalPolicy",
    "ModelAdmissionController",
    "ModelCatalogPublisher",
    "ModelInvocationEstimator",
    "ModelOperationalSnapshotPublisher",
    "ModelOperationalSnapshotResolver",
    "ModelOperationalStateRegistry",
    "ModelOutputCodec",
    "ModelPerception",
    "ModelProvider",
    "ModelRouter",
    "ModelRoutingRegistry",
    "ModelTierPolicy",
    "NeverCancelled",
    "OfflineFinalResponseValidator",
    "OfflinePersonaRenderer",
    "OfflineRenderValidator",
    "OfflineResponseComposer",
    "OutputAdapter",
    "PerceptionEngine",
    "PerceptionMerger",
    "PerceptionValidator",
    "PortCallContext",
    "ResponseProfilePolicy",
    "RulePerception",
    "RuntimePerceptionEngine",
    "RuntimeStateStore",
    "ScopeSelectorVerifier",
    "ScopedMemoryRetriever",
    "ServiceCallContext",
    "ServicePrincipal",
    "ShadowReceiptSink",
    "SocialDecisionEngine",
    "TaskComplexityAssessor",
    "ToolExecutor",
    "ToolInvocationLedger",
    "ToolPlanValidator",
    "ToolPlanner",
    "ToolResultValidator",
    "UnifiedMcpClient",
    "VisibleTokenCounter",
]


def __getattr__(name: str) -> object:
    if name in {
        "ArgumentBinder",
        "BoundedCapabilityRuntime",
        "CapabilityCatalogPublisher",
        "CapabilityHealthRegistry",
        "CapabilityProvider",
        "CapabilityProviderRegistry",
        "CapabilityRegistry",
        "CapabilityRetriever",
        "CapabilitySchemaValidator",
        "ToolExecutor",
        "ToolInvocationLedger",
        "ToolPlanner",
        "ToolPlanValidator",
        "ToolResultValidator",
    }:
        from .capabilities import (
            ArgumentBinder,
            BoundedCapabilityRuntime,
            CapabilityCatalogPublisher,
            CapabilityHealthRegistry,
            CapabilityProvider,
            CapabilityProviderRegistry,
            CapabilityRegistry,
            CapabilityRetriever,
            CapabilitySchemaValidator,
            ToolExecutor,
            ToolInvocationLedger,
            ToolPlanner,
            ToolPlanValidator,
            ToolResultValidator,
        )

        return {
            "ArgumentBinder": ArgumentBinder,
            "BoundedCapabilityRuntime": BoundedCapabilityRuntime,
            "CapabilityCatalogPublisher": CapabilityCatalogPublisher,
            "CapabilityHealthRegistry": CapabilityHealthRegistry,
            "CapabilityProvider": CapabilityProvider,
            "CapabilityProviderRegistry": CapabilityProviderRegistry,
            "CapabilityRegistry": CapabilityRegistry,
            "CapabilityRetriever": CapabilityRetriever,
            "CapabilitySchemaValidator": CapabilitySchemaValidator,
            "ToolExecutor": ToolExecutor,
            "ToolInvocationLedger": ToolInvocationLedger,
            "ToolPlanner": ToolPlanner,
            "ToolPlanValidator": ToolPlanValidator,
            "ToolResultValidator": ToolResultValidator,
        }[name]
    if name in {
        "McpEnvironmentProvider",
        "McpSchemaValidator",
        "McpSecretResolver",
        "McpServerRegistry",
        "McpTransportSession",
        "McpTransportSessionFactory",
        "UnifiedMcpClient",
    }:
        from .mcp import (
            McpEnvironmentProvider,
            McpSchemaValidator,
            McpSecretResolver,
            McpServerRegistry,
            McpTransportSession,
            McpTransportSessionFactory,
            UnifiedMcpClient,
        )

        return {
            "McpEnvironmentProvider": McpEnvironmentProvider,
            "McpSchemaValidator": McpSchemaValidator,
            "McpSecretResolver": McpSecretResolver,
            "McpServerRegistry": McpServerRegistry,
            "McpTransportSession": McpTransportSession,
            "McpTransportSessionFactory": McpTransportSessionFactory,
            "UnifiedMcpClient": UnifiedMcpClient,
        }[name]
    if name in {
        "MemoryAdministration",
        "MemoryRanker",
        "MemoryRepository",
        "MemoryRetrievalPolicy",
        "ScopedMemoryRetriever",
        "ScopeSelectorVerifier",
    }:
        from .memory import (
            MemoryAdministration,
            MemoryRanker,
            MemoryRepository,
            MemoryRetrievalPolicy,
            ScopedMemoryRetriever,
            ScopeSelectorVerifier,
        )

        return {
            "MemoryAdministration": MemoryAdministration,
            "MemoryRanker": MemoryRanker,
            "MemoryRepository": MemoryRepository,
            "MemoryRetrievalPolicy": MemoryRetrievalPolicy,
            "ScopedMemoryRetriever": ScopedMemoryRetriever,
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
    if name in {"ResponseProfilePolicy", "VisibleTokenCounter"}:
        from .responses import ResponseProfilePolicy, VisibleTokenCounter

        return {
            "ResponseProfilePolicy": ResponseProfilePolicy,
            "VisibleTokenCounter": VisibleTokenCounter,
        }[name]
    if name in {
        "BootstrapModelTierPolicy",
        "ModelAdmissionController",
        "ModelCatalogPublisher",
        "ModelInvocationEstimator",
        "ModelOperationalStateRegistry",
        "ModelOperationalSnapshotPublisher",
        "ModelOperationalSnapshotResolver",
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
            ModelOperationalSnapshotPublisher,
            ModelOperationalSnapshotResolver,
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
            "ModelOperationalSnapshotPublisher": ModelOperationalSnapshotPublisher,
            "ModelOperationalSnapshotResolver": ModelOperationalSnapshotResolver,
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
            InputConnector,
            OfflineFinalResponseValidator,
            OfflinePersonaRenderer,
            OfflineRenderValidator,
            OfflineResponseComposer,
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
