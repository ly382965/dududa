from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision
from dududa.persona.registry import InMemoryPersonaRegistry
from dududa.proactive.config import (
    ProactiveBehaviorControl,
    ProactiveControlConfig,
    default_proactive_control_config,
)
from dududa.proactive.contracts import (
    InitiatedRunRequest,
    ProactiveRunMode,
    ProactiveTrigger,
    ProactiveTriggerKind,
    ScheduleOccurrence,
    ScheduleOccurrenceOrigin,
)
from dududa.proactive.digest_contracts import DigestCompositionPolicySnapshot
from dududa.proactive.digest_shadow import (
    DeterministicDigestComposer,
    DigestCandidateBuilder,
    DigestPreviewProducer,
    DigestShadowRuntime,
)
from dududa.responses.contracts import (
    AnswerProfile,
    ResponseProfileLimits,
)
from dududa.responses.counting import UnicodeVisibleTokenCounter
from dududa.responses.validation import DeterministicResponseProfileValidator
from dududa.runtime.composition import (
    DeterministicPersonaRenderer,
    DeterministicPersonaRendererConfig,
    DeterministicRenderValidator,
    FinalResponseSafetyValidator,
)
from dududa.security.content_safety import DefaultContentSafetyPolicy
from dududa.security.digests import scope_digest
from dududa.testing.proactive import (
    MappingProactiveActorResolver,
    MappingProactiveSubscriptionStore,
    RecordingDigestShadowMetadataSink,
)

from tests.unit.persona._fixtures import definition as persona_definition

from ._fixtures import ProactiveFixture
from ._source_fixtures import GovernedSourceFixture


def revision(component_id: str) -> ComponentRevision:
    return ComponentRevision(
        component_id,
        "1.0.0",
        "digest-shadow-v1",
        canonical_digest(
            {"component_id": component_id},
            domain="test:digest-component:v1",
        ),
    )


class DigestShadowFixture:
    def __init__(self, *, source: GovernedSourceFixture | None = None) -> None:
        self.now = datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc)
        self.proactive = ProactiveFixture()
        self.proactive.now = self.now
        self.proactive.clock.value = self.now
        self.source = source or GovernedSourceFixture()
        self.subscription = replace(
            self.proactive.subscription,
            answer_profile=AnswerProfile.LONG,
            maximum_age=timedelta(days=7),
            created_at=self.now - timedelta(days=1),
            updated_at=self.now,
            subscription_digest="",
        )
        self.occurrence = ScheduleOccurrence(
            1,
            "digest-occurrence-1",
            self.subscription.subscription_id,
            self.subscription.revision,
            ScheduleOccurrenceOrigin.SCHEDULED,
            date(2026, 8, 9),
            self.now,
            self.now + timedelta(hours=1),
        )
        self.trigger = ProactiveTrigger(
            1,
            "digest-trigger-1",
            ProactiveTriggerKind.SCHEDULED_DIGEST,
            self.subscription.target_scope,
            self.occurrence,
            None,
            self.subscription.target_policy_ref,
            self.now,
            self.now + timedelta(hours=1),
        )
        definitions = (
            persona_definition(),
            persona_definition("neutral"),
        )
        self.persona_registry = InMemoryPersonaRegistry(
            definitions,
            fallback_persona_id="neutral",
            fallback_version="1.0.0",
            clock=self.proactive.clock,
            id_factory=lambda: "digest-persona-catalog-v1",
        )
        persona_snapshot = self.persona_registry.acquire_snapshot()
        self.policy = DigestCompositionPolicySnapshot(
            schema_version=1,
            snapshot_id="digest-composition-v1",
            source_policy_id=self.source.policy.policy_id,
            source_policy_revision=self.source.policy.policy_revision,
            source_policy_digest=self.source.policy.policy_digest,
            source_ids=tuple(
                definition.source_id for definition in self.source.policy.definitions
            ),
            response_policy_revision="digest-response-policy-v1",
            persona_catalog_snapshot_id=persona_snapshot.snapshot_id,
            persona_catalog_digest=persona_snapshot.catalog_digest,
            persona_id="dududa",
            persona_version=None,
            maximum_profile=AnswerProfile.MEDIUM,
            short_limits=ResponseProfileLimits(1, 256, 1_000, 2, 512),
            medium_limits=ResponseProfileLimits(1, 2_048, 5_000, 4, 2_048),
            delivery_part_character_limit=1_500,
            component_revision=revision("digest-composer"),
        )
        self.subscription_store = MappingProactiveSubscriptionStore(
            (self.subscription,)
        )
        self.actor_resolver = MappingProactiveActorResolver(
            {self.subscription.owner_ref: self.proactive.actor}
        )
        self.metadata_sink = RecordingDigestShadowMetadataSink()
        renderer = DeterministicPersonaRenderer(
            DeterministicPersonaRendererConfig(
                1,
                "dududa",
                "1.0.0",
                revision("digest-renderer"),
            )
        )
        profile_validator = DeterministicResponseProfileValidator(
            UnicodeVisibleTokenCounter(revision("digest-visible-counter")),
            revision("digest-profile-validator"),
        )
        final_validator = FinalResponseSafetyValidator(
            DeterministicRenderValidator(revision("digest-render-validator")),
            DefaultContentSafetyPolicy(clock=self.proactive.clock),
            profile_validator=profile_validator,
            clock=self.proactive.clock,
            id_factory=lambda: "digest-safety-request-1",
        )
        self.composer = DeterministicDigestComposer(id_factory=lambda: "candidate-1")
        self.builder = DigestCandidateBuilder(
            self.policy,
            source_provider=self.source.provider,
            composer=self.composer,
            persona_registry=self.persona_registry,
            renderer=renderer,
            final_validator=final_validator,
            clock=self.proactive.clock,
        )

    def run_request(
        self,
        mode: ProactiveRunMode = ProactiveRunMode.SHADOW,
    ) -> InitiatedRunRequest:
        return InitiatedRunRequest(
            1,
            "digest-run-1",
            self.trigger,
            self.subscription.target_policy_ref,
            mode,
            self.policy.snapshot_id,
            self.policy.source_policy_revision,
            self.policy.response_policy_revision,
        )

    def run_request_at(
        self,
        at: datetime,
        suffix: str,
        mode: ProactiveRunMode = ProactiveRunMode.SHADOW,
    ) -> InitiatedRunRequest:
        occurrence = replace(
            self.occurrence,
            occurrence_id=f"digest-occurrence-{suffix}",
            local_date=at.date(),
            scheduled_for=at,
            eligible_until=at + timedelta(hours=1),
            occurrence_digest="",
        )
        trigger = replace(
            self.trigger,
            trigger_id=f"digest-trigger-{suffix}",
            occurrence=occurrence,
            created_at=at,
            expires_at=at + timedelta(hours=1),
            trigger_digest="",
        )
        return InitiatedRunRequest(
            1,
            f"digest-run-{suffix}",
            trigger,
            self.subscription.target_policy_ref,
            mode,
            self.policy.snapshot_id,
            self.policy.source_policy_revision,
            self.policy.response_policy_revision,
        )

    def control(
        self,
        mode: ProactiveRunMode = ProactiveRunMode.SHADOW,
        *,
        kill_switch: bool = False,
    ) -> ProactiveControlConfig:
        behavior = ProactiveBehaviorControl(
            schema_version=1,
            mode=mode,
            revision=f"digest-{mode.value}-v1",
            timezone="Asia/Shanghai",
            delivery_enabled=False,
            allowlisted_scope_digests=frozenset(
                {scope_digest(self.subscription.target_scope)}
            ),
            kill_switch=kill_switch,
            maximum_global_messages=1,
            maximum_scope_messages=1,
            quota_window=timedelta(days=1),
            quiet_hours=(),
        )
        return ProactiveControlConfig(
            1,
            "digest-control-v1",
            behavior,
            default_proactive_control_config().probe,
        )

    def runtime(
        self,
        mode: ProactiveRunMode = ProactiveRunMode.SHADOW,
        *,
        kill_switch: bool = False,
    ) -> DigestShadowRuntime:
        return DigestShadowRuntime(
            self.control(mode, kill_switch=kill_switch),
            subscription_store=self.subscription_store,
            actor_resolver=self.actor_resolver,
            candidate_builder=self.builder,
            metadata_sink=self.metadata_sink,
            clock=self.proactive.clock,
        )

    def preview_producer(self) -> DigestPreviewProducer:
        return DigestPreviewProducer(
            subscription_store=self.subscription_store,
            candidate_builder=self.builder,
        )

    def preview_request(self):
        return replace(
            self.proactive.preview,
            subscription_id=self.subscription.subscription_id,
            subscription_revision=self.subscription.revision,
            config_snapshot_id=self.policy.snapshot_id,
            source_policy_revision=self.policy.source_policy_revision,
            response_policy_revision=self.policy.response_policy_revision,
            request_digest="",
        )

    def call(self):
        return self.proactive.service_call("digest-shadow-test")


__all__ = ["DigestShadowFixture", "revision"]
