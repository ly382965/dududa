from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import JsonValue, TraceContext
from dududa.errors import DududaError
from dududa.ports.context import CancellationToken, NeverCancelled, PortCallContext
from dududa.proactive.contracts import SourceCategory
from dududa.proactive.source_contracts import (
    SourceDefinition,
    SourceFetchOriginKind,
    SourceFetchRequest,
    SourceIdentityRule,
    SourcePolicySnapshot,
)
from dududa.proactive.source_store import (
    InMemorySourcePolicyRegistry,
    InMemorySourceStateStore,
)
from dududa.proactive.sources import GovernedSourceProvider
from dududa.testing.sources import (
    FixtureSourceCapabilityReader,
    load_source_fixture_bundle,
)

from ._fixtures import MutableClock, budget

SOURCE_FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "fixtures/proactive/sources/v1"
)


class GovernedSourceFixture:
    def __init__(
        self,
        *,
        definitions: tuple[SourceDefinition, ...] | None = None,
        fixtures: Mapping[str, Mapping[str, object]] | None = None,
        failures: Mapping[str, DududaError] | None = None,
        state_store: InMemorySourceStateStore | None = None,
    ) -> None:
        self.now = datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc)
        self.clock = MutableClock(self.now)
        self.definitions = definitions or source_definitions()
        self.policy = source_policy(self.definitions, now=self.now)
        self.request = source_request(self.policy, now=self.now)
        self.fixtures = dict(
            fixtures or load_source_fixture_bundle(SOURCE_FIXTURE_DIRECTORY)
        )
        self.reader = FixtureSourceCapabilityReader(
            self.fixtures,
            failures=failures,
        )
        self.state_store = state_store or InMemorySourceStateStore(clock=self.clock)
        self.registry = InMemorySourcePolicyRegistry(
            (self.policy,),
            clock=self.clock,
        )
        self.provider = GovernedSourceProvider(
            self.registry,
            self.reader,
            self.state_store,
            clock=self.clock,
        )

    def call(
        self,
        *,
        cancellation: CancellationToken | None = None,
    ) -> PortCallContext:
        return PortCallContext(
            "source-test-run",
            TraceContext("trace-source-test"),
            self.clock.value + timedelta(minutes=1),
            cancellation or NeverCancelled(),
            budget(),
            self.policy.policy_id,
        )


def source_definitions() -> tuple[SourceDefinition, ...]:
    return (
        source_definition(
            "arxiv-fixture",
            SourceCategory.ARXIV,
            "research.list_recent_arxiv.v1",
            "arxiv.org",
            "/abs",
            SourceIdentityRule.ARXIV_BASE_ID,
            notify_revisions=True,
        ),
        source_definition(
            "campus-fixture",
            SourceCategory.CAMPUS,
            "campus.list_public_notices.v1",
            "campus.example.edu",
            "/notices",
            SourceIdentityRule.EXTERNAL_ID,
        ),
        source_definition(
            "industry-fixture",
            SourceCategory.INDUSTRY,
            "industry.list_allowlisted_updates.v1",
            "industry.example.org",
            "/updates",
            SourceIdentityRule.CANONICAL_URL,
        ),
    )


def source_definition(
    source_id: str,
    category: SourceCategory,
    capability_id: str,
    host: str,
    path_prefix: str,
    identity_rule: SourceIdentityRule,
    *,
    notify_revisions: bool = False,
    maximum_payload_bytes: int = 65_536,
) -> SourceDefinition:
    return SourceDefinition(
        schema_version=1,
        source_id=source_id,
        category=category,
        capability_id=capability_id,
        capability_definition_digest=canonical_digest(
            {"capability_id": capability_id, "revision": "v1"},
            domain="test:source-capability-definition:v1",
        ),
        allowed_hosts=frozenset({host}),
        allowed_path_prefixes=(path_prefix,),
        identity_rule=identity_rule,
        maximum_age=timedelta(days=7),
        maximum_items=20,
        maximum_payload_bytes=maximum_payload_bytes,
        require_published_at=True,
        notify_revisions=notify_revisions,
        schema_revision="source-schema-v1",
        result_mapping_revision="source-mapping-v1",
        definition_revision="source-definition-v1",
    )


def source_policy(
    definitions: tuple[SourceDefinition, ...],
    *,
    now: datetime,
) -> SourcePolicySnapshot:
    return SourcePolicySnapshot(
        schema_version=1,
        policy_id="source-policy-v1",
        policy_revision="source-policy-revision-v1",
        definitions=tuple(sorted(definitions, key=lambda item: item.source_id)),
        acquired_at=now - timedelta(days=1),
        valid_until=now + timedelta(days=30),
    )


def source_request(
    policy: SourcePolicySnapshot,
    *,
    now: datetime,
    source_ids: tuple[str, ...] | None = None,
) -> SourceFetchRequest:
    selected = source_ids or tuple(item.source_id for item in policy.definitions)
    definitions = tuple(policy.definition(source_id) for source_id in selected)
    return SourceFetchRequest(
        schema_version=1,
        request_id="source-request-1",
        subscription_id="subscription-1",
        subscription_revision=1,
        origin_kind=SourceFetchOriginKind.SCHEDULED_TRIGGER,
        origin_digest=canonical_digest(
            {"trigger_id": "trigger-1"},
            domain="test:source-trigger:v1",
        ),
        source_policy_id=policy.policy_id,
        source_policy_digest=policy.policy_digest,
        source_ids=tuple(sorted(selected)),
        categories=frozenset(item.category for item in definitions),
        maximum_age=timedelta(days=7),
        maximum_items=20,
        requested_at=now,
    )


def mutable_fixture(
    source_id: str,
    fixtures: Mapping[str, Mapping[str, object]],
) -> dict[str, JsonValue]:
    import copy

    value = copy.deepcopy(fixtures[source_id])
    assert isinstance(value, dict)
    return value


__all__ = [
    "SOURCE_FIXTURE_DIRECTORY",
    "GovernedSourceFixture",
    "mutable_fixture",
    "source_definition",
    "source_definitions",
    "source_policy",
    "source_request",
]
