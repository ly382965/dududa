"""AstrBot-facing adapters for Dududa 2.0 and its compatibility surfaces."""

from .api_key_pools import (
    API_KEY_POOL_SCHEMA_VERSION,
    API_KEY_POOL_TIERS,
    API_KEY_STORE_PATH_COMPAT_ENV,
    API_KEY_STORE_PATH_ENV,
    ApiKeyCredential,
    ApiKeyPool,
    ApiKeyPoolConfigError,
    ApiKeyPoolSnapshot,
    AstrBotProviderProjection,
    configured_api_key_store_path,
    load_api_key_pool_snapshot,
    parse_api_key_pool_snapshot,
    project_pool_to_astrbot,
)
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
    "API_KEY_POOL_SCHEMA_VERSION",
    "API_KEY_POOL_TIERS",
    "API_KEY_STORE_PATH_COMPAT_ENV",
    "API_KEY_STORE_PATH_ENV",
    "AllowlistedEnvironmentProvider",
    "ApiKeyCredential",
    "ApiKeyPool",
    "ApiKeyPoolConfigError",
    "ApiKeyPoolSnapshot",
    "AstrBotInputConnector",
    "AstrBotModelProviderAdapter",
    "AstrBotOutputAdapter",
    "AstrBotPromptArtifact",
    "AstrBotProviderBindingEvidence",
    "AstrBotProviderEvidenceStore",
    "AstrBotProviderProjection",
    "EntityQueryToolPlanner",
    "EnvironmentMcpSecretResolver",
    "InMemoryDeliveryLedger",
    "JsonSchemaDocumentRegistry",
    "JsonSchemaMcpValidator",
    "JsonSchemaOutputCodec",
    "ProductionCapabilityAssembly",
    "RejectingMcpSecretResolver",
    "astrbot_prompt_artifact_digest",
    "build_icourse_client",
    "build_production_capability_runtime",
    "build_unified_mcp_client",
    "configured_api_key_store_path",
    "load_api_key_pool_snapshot",
    "parse_api_key_pool_snapshot",
    "project_pool_to_astrbot",
]
