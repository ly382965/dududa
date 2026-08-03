"""AstrBot-facing adapters. Legacy handlers remain authoritative in S04."""

from .message import AstrBotInputConnector
from .model import (
    AstrBotModelProviderAdapter,
    AstrBotPromptArtifact,
    AstrBotProviderBindingEvidence,
    astrbot_prompt_artifact_digest,
)
from .model_codec import JsonSchemaDocumentRegistry, JsonSchemaOutputCodec
from .output import AstrBotOutputAdapter, InMemoryDeliveryLedger

__all__ = [
    "AstrBotInputConnector",
    "AstrBotModelProviderAdapter",
    "AstrBotOutputAdapter",
    "AstrBotPromptArtifact",
    "AstrBotProviderBindingEvidence",
    "InMemoryDeliveryLedger",
    "JsonSchemaDocumentRegistry",
    "JsonSchemaOutputCodec",
    "astrbot_prompt_artifact_digest",
]
