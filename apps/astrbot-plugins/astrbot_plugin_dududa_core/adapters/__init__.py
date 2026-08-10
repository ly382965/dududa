"""AstrBot-facing adapters. Legacy handlers remain authoritative in S04."""

from .message import AstrBotInputConnector
from .model import (
    AstrBotModelProviderAdapter,
    AstrBotPromptArtifact,
    AstrBotProviderBindingEvidence,
    astrbot_prompt_artifact_digest,
)
from .model_codec import JsonSchemaDocumentRegistry, JsonSchemaOutputCodec
from .mcp_schema import JsonSchemaMcpValidator
from .mcp_runtime import (
    AllowlistedEnvironmentProvider,
    RejectingMcpSecretResolver,
    build_icourse_client,
)
from .output import AstrBotOutputAdapter, InMemoryDeliveryLedger

__all__ = [
    "AstrBotInputConnector",
    "AstrBotModelProviderAdapter",
    "AstrBotOutputAdapter",
    "AstrBotPromptArtifact",
    "AstrBotProviderBindingEvidence",
    "AllowlistedEnvironmentProvider",
    "InMemoryDeliveryLedger",
    "JsonSchemaDocumentRegistry",
    "JsonSchemaMcpValidator",
    "JsonSchemaOutputCodec",
    "RejectingMcpSecretResolver",
    "astrbot_prompt_artifact_digest",
    "build_icourse_client",
]
