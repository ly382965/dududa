from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision, Sensitivity
from dududa.persona.registry import InMemoryPersonaRegistry
from dududa.proactive.config import (
    ProactiveBehaviorControl,
    ProactiveControlConfig,
    default_proactive_control_config,
)
from dududa.proactive.contracts import (
    ConversationOpportunitySnapshot,
    InitiatedRunRequest,
    ProactiveRunMode,
    ProactiveTrigger,
    ProactiveTriggerKind,
)
from dududa.proactive.probe_contracts import (
    ProbeConversationWindow,
    ProbeHardBlocker,
    ProbePolicySnapshot,
    ProbeShadowRequest,
)
from dududa.proactive.probe_shadow import (
    DeterministicProbeComposer,
    DeterministicProbeOpportunityDetector,
    InMemoryProbeStateStore,
    ProbeCandidateBuilder,
    ProbeShadowRuntime,
)
from dududa.proactive.registry import InMemoryProactiveTargetRegistry
from dududa.responses.contracts import ResponseProfileLimits
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
    RecordingProbeShadowMetadataSink,
)

from tests.unit.persona._fixtures import definition as persona_definition

from ._fixtures import ProactiveFixture


def revision(component_id: str) -> ComponentRevision:
    return ComponentRevision(
        component_id,
        "1.0.0",
        "probe-shadow-v1",
        canonical_digest(
            {"component_id": component_id},
            domain="test:probe-component:v1",
        ),
    )


class ProbeShadowFixture:
    def __init__(self) -> None:
        self.proactive = ProactiveFixture()
        self.clock = self.proactive.clock
        self.now = self.clock.value
        self.target_registry = InMemoryProactiveTargetRegistry(
            (
                self.proactive.operator_grant,
                self.proactive.group_grant,
                self.proactive.owner_grant,
            ),
            (self.proactive.policy,),
            clock=self.clock,
        )
        self.actor_resolver = MappingProactiveActorResolver(
            {self.proactive.actor_ref: self.proactive.actor}
        )
        self.persona_registry = InMemoryPersonaRegistry(
            (persona_definition(), persona_definition("neutral")),
            fallback_persona_id="neutral",
            fallback_version="1.0.0",
            clock=self.clock,
            id_factory=lambda: "probe-persona-catalog-v1",
        )
        persona_snapshot = self.persona_registry.acquire_snapshot()
        self.policy = ProbePolicySnapshot(
            schema_version=1,
            snapshot_id="probe-policy-v1",
            response_policy_revision="probe-response-policy-v1",
            persona_catalog_snapshot_id=persona_snapshot.snapshot_id,
            persona_catalog_digest=persona_snapshot.catalog_digest,
            persona_id="dududa",
            persona_version=None,
            minimum_silence=timedelta(minutes=5),
            maximum_topic_age=timedelta(hours=2),
            opportunity_ttl=timedelta(minutes=10),
            response_attribution_window=timedelta(hours=1),
            recent_bot_cooldown=timedelta(minutes=30),
            shadow_cooldown=timedelta(days=1),
            no_response_cooldown=timedelta(days=30),
            short_limits=ResponseProfileLimits(1, 128, 180, 1, 256),
            delivery_part_character_limit=180,
            detector_revision=revision("probe-detector"),
            composer_revision=revision("probe-composer"),
        )
        self.detector = DeterministicProbeOpportunityDetector()
        self.state_store = InMemoryProbeStateStore(clock=self.clock)
        self.metadata_sink = RecordingProbeShadowMetadataSink()
        self.composer = DeterministicProbeComposer(id_factory=lambda: "candidate-1")
        renderer = DeterministicPersonaRenderer(
            DeterministicPersonaRendererConfig(
                1,
                "dududa",
                "1.0.0",
                revision("probe-renderer"),
            )
        )
        profile_validator = DeterministicResponseProfileValidator(
            UnicodeVisibleTokenCounter(revision("probe-visible-counter")),
            revision("probe-profile-validator"),
        )
        final_validator = FinalResponseSafetyValidator(
            DeterministicRenderValidator(revision("probe-render-validator")),
            DefaultContentSafetyPolicy(clock=self.clock),
            profile_validator=profile_validator,
            clock=self.clock,
            id_factory=lambda: "probe-safety-request-1",
        )
        self.builder = ProbeCandidateBuilder(
            self.policy,
            composer=self.composer,
            persona_registry=self.persona_registry,
            renderer=renderer,
            final_validator=final_validator,
            clock=self.clock,
        )

    def window(
        self,
        suffix: str = "1",
        *,
        at: datetime | None = None,
        summary: str = "Campus shuttle timetable changed",
        sensitivity: Sensitivity = Sensitivity.PUBLIC,
        blockers: frozenset[ProbeHardBlocker] = frozenset(),
        last_human_delta: timedelta = timedelta(minutes=10),
        last_bot_delta: timedelta | None = timedelta(hours=1),
    ) -> ProbeConversationWindow:
        observed = at or self.clock.value
        return ProbeConversationWindow(
            schema_version=1,
            window_id=f"probe-window-{suffix}",
            scope=self.proactive.scope,
            target_policy_ref=self.proactive.policy.as_ref(),
            topic_refs=(f"topic-{suffix}",),
            topic_summary=summary,
            sensitivity=sensitivity,
            last_human_activity_at=observed - last_human_delta,
            last_bot_activity_at=(
                observed - last_bot_delta if last_bot_delta is not None else None
            ),
            observed_at=observed,
            hard_blockers=blockers,
            projection_revision=revision("probe-projection"),
        )

    def request(
        self,
        window: ProbeConversationWindow | None = None,
        mode: ProactiveRunMode = ProactiveRunMode.SHADOW,
        *,
        suffix: str = "1",
    ) -> ProbeShadowRequest:
        return ProbeShadowRequest(
            1,
            f"probe-request-{suffix}",
            window or self.window(suffix),
            mode,
            self.policy.snapshot_id,
            self.policy.response_policy_revision,
        )

    def control(
        self,
        mode: ProactiveRunMode = ProactiveRunMode.SHADOW,
        *,
        kill_switch: bool = False,
        quiet_hours=(),
        allowlisted: bool = True,
    ) -> ProactiveControlConfig:
        probe = ProactiveBehaviorControl(
            schema_version=1,
            mode=mode,
            revision=f"probe-{mode.value}-v1",
            timezone="Asia/Shanghai",
            delivery_enabled=mode is ProactiveRunMode.CANARY,
            allowlisted_scope_digests=(
                frozenset({scope_digest(self.proactive.scope)})
                if allowlisted
                else frozenset()
            ),
            kill_switch=kill_switch,
            maximum_global_messages=1,
            maximum_scope_messages=1,
            quota_window=timedelta(days=1),
            quiet_hours=tuple(quiet_hours),
        )
        return ProactiveControlConfig(
            1,
            "probe-control-v1",
            default_proactive_control_config().digest,
            probe,
        )

    def runtime(
        self,
        mode: ProactiveRunMode = ProactiveRunMode.SHADOW,
        *,
        kill_switch: bool = False,
        quiet_hours=(),
        allowlisted: bool = True,
    ) -> ProbeShadowRuntime:
        return ProbeShadowRuntime(
            self.control(
                mode,
                kill_switch=kill_switch,
                quiet_hours=quiet_hours,
                allowlisted=allowlisted,
            ),
            self.policy,
            target_registry=self.target_registry,
            actor_resolver=self.actor_resolver,
            detector=self.detector,
            state_store=self.state_store,
            candidate_builder=self.builder,
            metadata_sink=self.metadata_sink,
            clock=self.clock,
        )

    def bound_run(
        self,
        opportunity: ConversationOpportunitySnapshot,
        mode: ProactiveRunMode = ProactiveRunMode.SHADOW,
    ) -> InitiatedRunRequest:
        trigger = ProactiveTrigger(
            1,
            "probe-trigger-test",
            ProactiveTriggerKind.CONVERSATION_PROBE,
            opportunity.scope,
            None,
            opportunity,
            opportunity.target_policy_ref,
            self.clock.value,
            opportunity.expires_at,
        )
        return InitiatedRunRequest(
            1,
            "probe-run-test",
            trigger,
            opportunity.target_policy_ref,
            mode,
            self.policy.snapshot_id,
            "probe-no-source-v1",
            self.policy.response_policy_revision,
        )

    def call(self):
        return self.proactive.service_call("probe-shadow-test")

    def port_call(self):
        return self.proactive.port_call("probe-shadow-test")

    def replace_window(self, window: ProbeConversationWindow, **changes):
        return replace(window, window_digest="", **changes)


__all__ = ["ProbeShadowFixture", "revision"]
