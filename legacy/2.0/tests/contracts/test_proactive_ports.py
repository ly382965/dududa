from __future__ import annotations

import unittest

from dududa.ports.output import OutputAdapter
from dududa.ports.proactive import (
    ProactiveActorResolver,
    ProactiveDispatchStore,
    ProactivePreviewMetadataStore,
    ProactivePreviewPort,
    ProactivePreviewProducer,
    ProactiveQuotaLedger,
    ProactiveTargetRegistry,
    SourceCapabilityReader,
    SourcePolicyRegistry,
    SourceProvider,
    SourceStateStore,
)
from dududa.proactive.preview import IsolatedProactivePreviewService
from dududa.proactive.quota import InMemoryProactiveQuotaLedger
from dududa.proactive.registry import InMemoryProactiveTargetRegistry
from dududa.proactive.store import InMemoryProactiveDispatchStore
from dududa.testing.proactive import (
    MappingProactiveActorResolver,
    RecordingFakeProactiveOutput,
    RecordingProactivePreviewMetadataStore,
    StaticProactivePreviewProducer,
)

from tests.unit.proactive._fixtures import ProactiveFixture
from tests.unit.proactive._source_fixtures import GovernedSourceFixture
from tests.unit.proactive.test_digests import _response


class ProactivePortContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProactiveFixture()

    def test_local_fakes_implement_framework_neutral_ports(self) -> None:
        fixture = self.fixture
        registry = InMemoryProactiveTargetRegistry(
            (fixture.operator_grant, fixture.group_grant, fixture.owner_grant),
            (fixture.policy,),
            clock=fixture.clock,
        )
        actor_resolver = MappingProactiveActorResolver(
            {fixture.actor_ref: fixture.actor}
        )
        producer = StaticProactivePreviewProducer(_response(fixture))
        metadata_store = RecordingProactivePreviewMetadataStore()
        preview = IsolatedProactivePreviewService(
            target_registry=registry,
            authorization_policy=_RejectingAuthorizationPolicy(),
            authorization_verifier=_RejectingAuthorizationVerifier(),
            authorization_policy_revision="auth-v1",
            producer=producer,
            metadata_store=metadata_store,
            clock=fixture.clock,
        )

        self.assertIsInstance(registry, ProactiveTargetRegistry)
        self.assertIsInstance(InMemoryProactiveDispatchStore(), ProactiveDispatchStore)
        self.assertIsInstance(InMemoryProactiveQuotaLedger(), ProactiveQuotaLedger)
        self.assertIsInstance(actor_resolver, ProactiveActorResolver)
        self.assertIsInstance(producer, ProactivePreviewProducer)
        self.assertIsInstance(metadata_store, ProactivePreviewMetadataStore)
        self.assertIsInstance(preview, ProactivePreviewPort)
        self.assertIsInstance(RecordingFakeProactiveOutput(), OutputAdapter)

    def test_governed_source_references_implement_framework_neutral_ports(self) -> None:
        fixture = GovernedSourceFixture()

        self.assertIsInstance(fixture.registry, SourcePolicyRegistry)
        self.assertIsInstance(fixture.reader, SourceCapabilityReader)
        self.assertIsInstance(fixture.state_store, SourceStateStore)
        self.assertIsInstance(fixture.provider, SourceProvider)

    def test_preview_graph_has_no_output_dispatch_or_scheduler(self) -> None:
        fixture = self.fixture
        registry = InMemoryProactiveTargetRegistry(
            (fixture.operator_grant, fixture.group_grant, fixture.owner_grant),
            (fixture.policy,),
            clock=fixture.clock,
        )
        preview = IsolatedProactivePreviewService(
            target_registry=registry,
            authorization_policy=_RejectingAuthorizationPolicy(),
            authorization_verifier=_RejectingAuthorizationVerifier(),
            authorization_policy_revision="auth-v1",
            producer=StaticProactivePreviewProducer(_response(fixture)),
            metadata_store=RecordingProactivePreviewMetadataStore(),
            clock=fixture.clock,
        )
        names = set(vars(preview))
        self.assertFalse(
            names
            & {
                "_output",
                "_dispatch_store",
                "_scheduler",
                "_delivery_orchestrator",
            }
        )


class _RejectingAuthorizationPolicy:
    async def decide(self, request, *, call):
        raise AssertionError("not called by structural contract")


class _RejectingAuthorizationVerifier:
    def verify(self, decision, *, at=None):
        return False


if __name__ == "__main__":
    unittest.main()
