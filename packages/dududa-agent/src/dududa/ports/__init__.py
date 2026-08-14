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
    from .control_plane import (
        GroupJoinSource,
        GroupServiceCatalog,
        GroupServiceRepository,
        OperatorSessionResolver,
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
    from .persona import PersonaCatalogPublisher, PersonaRegistry
    from .proactive import (
        DigestComposer,
        DigestShadowMetadataSink,
        DigestShadowRunner,
        ProactiveActorResolver,
        ProactiveDeliveryOrchestrator,
        ProactiveDispatchStore,
        ProactivePreviewMetadataStore,
        ProactivePreviewPort,
        ProactivePreviewProducer,
        ProactiveQuotaLedger,
        ProactiveScheduler,
        ProactiveScheduleStore,
        ProactiveSubscriptionStore,
        ProactiveTargetRegistry,
        ProbeComposer,
        ProbeOpportunityDetector,
        ProbeShadowMetadataSink,
        ProbeShadowRunner,
        ProbeStateStore,
        SourceCapabilityReader,
        SourcePolicyRegistry,
        SourceProvider,
        SourceStateStore,
    )
    from .responses import (
        ResponseProfilePolicy,
        ResponseProfileValidator,
        VisibleTokenCounter,
    )
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
    "DigestComposer",
    "DigestShadowMetadataSink",
    "DigestShadowRunner",
    "GroupJoinSource",
    "GroupServiceCatalog",
    "GroupServiceRepository",
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
    "OperatorSessionResolver",
    "OutputAdapter",
    "PerceptionEngine",
    "PerceptionMerger",
    "PerceptionValidator",
    "PersonaCatalogPublisher",
    "PersonaRegistry",
    "PortCallContext",
    "ProactiveActorResolver",
    "ProactiveDeliveryOrchestrator",
    "ProactiveDispatchStore",
    "ProactivePreviewMetadataStore",
    "ProactivePreviewPort",
    "ProactivePreviewProducer",
    "ProactiveQuotaLedger",
    "ProactiveScheduleStore",
    "ProactiveScheduler",
    "ProactiveSubscriptionStore",
    "ProactiveTargetRegistry",
    "ProbeComposer",
    "ProbeOpportunityDetector",
    "ProbeShadowMetadataSink",
    "ProbeShadowRunner",
    "ProbeStateStore",
    "ResponseProfilePolicy",
    "ResponseProfileValidator",
    "RulePerception",
    "RuntimePerceptionEngine",
    "RuntimeStateStore",
    "ScopeSelectorVerifier",
    "ScopedMemoryRetriever",
    "ServiceCallContext",
    "ServicePrincipal",
    "ShadowReceiptSink",
    "SocialDecisionEngine",
    "SourceCapabilityReader",
    "SourcePolicyRegistry",
    "SourceProvider",
    "SourceStateStore",
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
        "GroupJoinSource",
        "GroupServiceCatalog",
        "GroupServiceRepository",
        "OperatorSessionResolver",
    }:
        from .control_plane import (
            GroupJoinSource,
            GroupServiceCatalog,
            GroupServiceRepository,
            OperatorSessionResolver,
        )

        return {
            "GroupJoinSource": GroupJoinSource,
            "GroupServiceCatalog": GroupServiceCatalog,
            "GroupServiceRepository": GroupServiceRepository,
            "OperatorSessionResolver": OperatorSessionResolver,
        }[name]
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
    if name in {
        "PersonaCatalogPublisher",
        "PersonaRegistry",
    }:
        from .persona import PersonaCatalogPublisher, PersonaRegistry

        return {
            "PersonaCatalogPublisher": PersonaCatalogPublisher,
            "PersonaRegistry": PersonaRegistry,
        }[name]
    if name in {
        "DigestComposer",
        "DigestShadowMetadataSink",
        "DigestShadowRunner",
        "ProbeComposer",
        "ProbeOpportunityDetector",
        "ProbeShadowMetadataSink",
        "ProbeShadowRunner",
        "ProbeStateStore",
        "ProactiveActorResolver",
        "ProactiveDeliveryOrchestrator",
        "ProactiveDispatchStore",
        "ProactivePreviewMetadataStore",
        "ProactivePreviewPort",
        "ProactivePreviewProducer",
        "ProactiveQuotaLedger",
        "ProactiveScheduleStore",
        "ProactiveScheduler",
        "ProactiveSubscriptionStore",
        "ProactiveTargetRegistry",
        "SourceCapabilityReader",
        "SourcePolicyRegistry",
        "SourceProvider",
        "SourceStateStore",
    }:
        from .proactive import (
            DigestComposer,
            DigestShadowMetadataSink,
            DigestShadowRunner,
            ProactiveActorResolver,
            ProactiveDeliveryOrchestrator,
            ProactiveDispatchStore,
            ProactivePreviewMetadataStore,
            ProactivePreviewPort,
            ProactivePreviewProducer,
            ProactiveQuotaLedger,
            ProactiveScheduler,
            ProactiveScheduleStore,
            ProactiveSubscriptionStore,
            ProactiveTargetRegistry,
            ProbeComposer,
            ProbeOpportunityDetector,
            ProbeShadowMetadataSink,
            ProbeShadowRunner,
            ProbeStateStore,
            SourceCapabilityReader,
            SourcePolicyRegistry,
            SourceProvider,
            SourceStateStore,
        )

        return {
            "DigestComposer": DigestComposer,
            "DigestShadowMetadataSink": DigestShadowMetadataSink,
            "DigestShadowRunner": DigestShadowRunner,
            "ProbeComposer": ProbeComposer,
            "ProbeOpportunityDetector": ProbeOpportunityDetector,
            "ProbeShadowMetadataSink": ProbeShadowMetadataSink,
            "ProbeShadowRunner": ProbeShadowRunner,
            "ProbeStateStore": ProbeStateStore,
            "ProactiveActorResolver": ProactiveActorResolver,
            "ProactiveDeliveryOrchestrator": ProactiveDeliveryOrchestrator,
            "ProactiveDispatchStore": ProactiveDispatchStore,
            "ProactivePreviewMetadataStore": ProactivePreviewMetadataStore,
            "ProactivePreviewPort": ProactivePreviewPort,
            "ProactivePreviewProducer": ProactivePreviewProducer,
            "ProactiveQuotaLedger": ProactiveQuotaLedger,
            "ProactiveScheduleStore": ProactiveScheduleStore,
            "ProactiveScheduler": ProactiveScheduler,
            "ProactiveSubscriptionStore": ProactiveSubscriptionStore,
            "ProactiveTargetRegistry": ProactiveTargetRegistry,
            "SourceCapabilityReader": SourceCapabilityReader,
            "SourcePolicyRegistry": SourcePolicyRegistry,
            "SourceProvider": SourceProvider,
            "SourceStateStore": SourceStateStore,
        }[name]
    if name in {
        "ResponseProfilePolicy",
        "ResponseProfileValidator",
        "VisibleTokenCounter",
    }:
        from .responses import (
            ResponseProfilePolicy,
            ResponseProfileValidator,
            VisibleTokenCounter,
        )

        return {
            "ResponseProfilePolicy": ResponseProfilePolicy,
            "ResponseProfileValidator": ResponseProfileValidator,
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
