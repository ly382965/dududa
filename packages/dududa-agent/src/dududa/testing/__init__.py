"""Reusable fakes for contract and application tests."""

from .fakes import FakeAgentRuntime, FakeInputConnector
from .models import (
    ProviderOutcome,
    ProviderSuccess,
    RecordingFakeModelProvider,
    provider_failure,
)
from .mcp import (
    FakeMcpSessionPlan,
    MappingMcpEnvironmentProvider,
    MappingMcpSecretResolver,
    RecordingFakeMcpSession,
    RecordingFakeMcpSessionFactory,
    RecordingMcpSchemaValidator,
)

__all__ = [
    "FakeAgentRuntime",
    "FakeMcpSessionPlan",
    "MappingMcpEnvironmentProvider",
    "MappingMcpSecretResolver",
    "FakeInputConnector",
    "ProviderOutcome",
    "ProviderSuccess",
    "RecordingFakeModelProvider",
    "RecordingFakeMcpSession",
    "RecordingFakeMcpSessionFactory",
    "RecordingMcpSchemaValidator",
    "provider_failure",
]
