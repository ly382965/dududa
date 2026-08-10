"""Reusable fakes for contract and application tests."""

from .fakes import FakeAgentRuntime, FakeInputConnector
from .mcp import (
    FakeMcpSessionPlan,
    MappingMcpEnvironmentProvider,
    MappingMcpSecretResolver,
    RecordingFakeMcpSession,
    RecordingFakeMcpSessionFactory,
    RecordingMcpSchemaValidator,
)
from .models import (
    ProviderOutcome,
    ProviderSuccess,
    RecordingFakeModelProvider,
    provider_failure,
)
from .proactive import (
    MappingProactiveActorResolver,
    MutableClock,
    RecordingFakeProactiveOutput,
    RecordingProactivePreviewMetadataStore,
    StaticProactivePreviewProducer,
)

__all__ = [
    "FakeAgentRuntime",
    "FakeInputConnector",
    "FakeMcpSessionPlan",
    "MappingMcpEnvironmentProvider",
    "MappingMcpSecretResolver",
    "MappingProactiveActorResolver",
    "MutableClock",
    "ProviderOutcome",
    "ProviderSuccess",
    "RecordingFakeMcpSession",
    "RecordingFakeMcpSessionFactory",
    "RecordingFakeModelProvider",
    "RecordingFakeProactiveOutput",
    "RecordingMcpSchemaValidator",
    "RecordingProactivePreviewMetadataStore",
    "StaticProactivePreviewProducer",
    "provider_failure",
]
