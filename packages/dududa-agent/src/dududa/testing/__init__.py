"""Reusable fakes for contract and application tests."""

from .control_plane import (
    FakeGroupJoinSource,
    MappingOperatorSessionResolver,
    StaticFakeServiceCatalog,
)
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
    RecordingProbeShadowMetadataSink,
    StaticProactivePreviewProducer,
)
from .sources import FixtureSourceCapabilityReader, load_source_fixture_bundle

__all__ = [
    "FakeAgentRuntime",
    "FakeGroupJoinSource",
    "FakeInputConnector",
    "FakeMcpSessionPlan",
    "FixtureSourceCapabilityReader",
    "MappingMcpEnvironmentProvider",
    "MappingMcpSecretResolver",
    "MappingOperatorSessionResolver",
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
    "RecordingProbeShadowMetadataSink",
    "StaticFakeServiceCatalog",
    "StaticProactivePreviewProducer",
    "load_source_fixture_bundle",
    "provider_failure",
]
