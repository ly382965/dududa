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
    MappingProactiveSubscriptionStore,
    MutableClock,
    RecordingDigestShadowMetadataSink,
    RecordingFakeProactiveOutput,
    RecordingProactivePreviewMetadataStore,
    StaticProactivePreviewProducer,
)
from .sources import FixtureSourceCapabilityReader, load_source_fixture_bundle

__all__ = [
    "FakeAgentRuntime",
    "FakeInputConnector",
    "FakeMcpSessionPlan",
    "FixtureSourceCapabilityReader",
    "MappingMcpEnvironmentProvider",
    "MappingMcpSecretResolver",
    "MappingProactiveActorResolver",
    "MappingProactiveSubscriptionStore",
    "MutableClock",
    "ProviderOutcome",
    "ProviderSuccess",
    "RecordingDigestShadowMetadataSink",
    "RecordingFakeMcpSession",
    "RecordingFakeMcpSessionFactory",
    "RecordingFakeModelProvider",
    "RecordingFakeProactiveOutput",
    "RecordingMcpSchemaValidator",
    "RecordingProactivePreviewMetadataStore",
    "StaticProactivePreviewProducer",
    "load_source_fixture_bundle",
    "provider_failure",
]
