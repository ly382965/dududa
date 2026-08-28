"""AstrBot-facing adapters for Dududa 2.0 and its compatibility surfaces."""

from .capability_planner import EntityQueryToolPlanner
from .capability_runtime import (
    ProductionCapabilityAssembly,
    build_production_capability_runtime,
)
from .mcp_runtime import (
    AllowlistedEnvironmentProvider,
    EnvironmentMcpSecretResolver,
    RejectingMcpSecretResolver,
    build_icourse_client,
    build_unified_mcp_client,
)
from .mcp_schema import JsonSchemaMcpValidator
from .message import AstrBotInputConnector
from .model import (
    AstrBotModelProviderAdapter,
    AstrBotPromptArtifact,
    AstrBotProviderBindingEvidence,
    astrbot_prompt_artifact_digest,
)
from .model_codec import JsonSchemaDocumentRegistry, JsonSchemaOutputCodec
from .model_evidence import AstrBotProviderEvidenceStore
from .output import AstrBotOutputAdapter, InMemoryDeliveryLedger

__all__ = [
    "AllowlistedEnvironmentProvider",
    "EnvironmentMcpSecretResolver",
    "AstrBotInputConnector",
    "AstrBotModelProviderAdapter",
    "AstrBotOutputAdapter",
    "AstrBotPromptArtifact",
    "AstrBotProviderBindingEvidence",
    "AstrBotProviderEvidenceStore",
    "InMemoryDeliveryLedger",
    "JsonSchemaDocumentRegistry",
    "JsonSchemaMcpValidator",
    "JsonSchemaOutputCodec",
    "RejectingMcpSecretResolver",
    "astrbot_prompt_artifact_digest",
    "build_icourse_client",
    "build_unified_mcp_client",
    "EntityQueryToolPlanner",
    "ProductionCapabilityAssembly",
    "build_production_capability_runtime",
]
