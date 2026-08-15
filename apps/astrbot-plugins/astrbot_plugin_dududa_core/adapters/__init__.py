"""AstrBot-facing adapters. Legacy handlers remain authoritative in S04."""

from .mcp_runtime import (
    AllowlistedEnvironmentProvider,
    RejectingMcpSecretResolver,
    build_icourse_client,
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
]
