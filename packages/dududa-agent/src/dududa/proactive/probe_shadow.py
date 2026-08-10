from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from dududa.contracts.canonical import canonical_digest
from dududa.domain.content import (
    ContentBlock,
    DraftResponse,
    FactAnchor,
    ValidatedFinalResponse,
)
from dududa.domain.identity import Actor
from dududa.domain.primitives import ResponseConstraints, Sensitivity
from dududa.errors import validation_error
from dududa.persona.contracts import PersonaResolution
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.ports.persona import PersonaRegistry
from dududa.ports.runtime import OfflineFinalResponseValidator, OfflinePersonaRenderer
from dududa.responses.contracts import AnswerProfile, ResponsePlan
from dududa.responses.digests import response_plan_digest
from dududa.security.digests import scope_digest

from .config import ProactiveControlConfig
from .contracts import (
    ConversationOpportunitySnapshot,
    InitiatedRunRequest,
    ProactiveDisposition,
    ProactiveRunMode,
    ProactiveTrigger,
    ProactiveTriggerKind,
)
from .probe_contracts import (
    ProbeConversationWindow,
    ProbeDetectionResult,
    ProbeDetectionStatus,
    ProbeOutcomeKind,
    ProbeOutcomeObservation,
    ProbePolicySnapshot,
    ProbeShadowMetadata,
    ProbeShadowRequest,
    ProbeStateClaimDisposition,
    ProbeStateClaimReceipt,
    ProbeStateSnapshot,
)

if TYPE_CHECKING:
    from dududa.ports.proactive import (
        ProactiveActorResolver,
        ProactiveTargetRegistry,
        ProbeComposer,
        ProbeOpportunityDetector,
        ProbeShadowMetadataSink,
        ProbeStateStore,
    )

_MENTION_PATTERN = re.compile(
    r"(?:@|＠|\[CQ:at|<@|\bqq\s*=|\buser[_-]?id\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ProbeCandidateOutcome:
    response_plan: ResponsePlan
    persona_resolution: PersonaResolution
    validated_response: ValidatedFinalResponse


class DeterministicProbeOpportunityDetector:
    def __init__(self, *, id_factory: Callable[[], str] | None = None) -> None:
        self._id_factory = id_factory

    def detect(
        self,
        window: ProbeConversationWindow,
        policy: ProbePolicySnapshot,
        *,
        at: datetime,
    ) -> ProbeDetectionResult:
        if not isinstance(window, ProbeConversationWindow) or not isinstance(
            policy,
            ProbePolicySnapshot,
        ):
            raise validation_error("invalid_probe_detection_input")
        at = _utc(at, "probe_detection_at")
        reasons: list[str] = []
        if window.observed_at > at:
            reasons.append("probe_projection_from_future")
        if window.sensitivity is not Sensitivity.PUBLIC:
            reasons.append("probe_topic_not_public")
        reasons.extend(
            f"probe_blocked_{value.value}"
            for value in sorted(window.hard_blockers, key=lambda item: item.value)
        )
        if _contains_mention(window.topic_summary):
            reasons.append("probe_topic_mentions_individual")
        candidate_characters = len(window.topic_summary) + (
            0 if window.topic_summary.endswith(("?", "\uff1f")) else 1
        )
        if candidate_characters > policy.short_limits.visible_characters:
            reasons.append("probe_topic_exceeds_short_limit")
        silence = at - window.last_human_activity_at
        if silence < policy.minimum_silence:
            reasons.append("probe_silence_too_short")
        if silence >= policy.maximum_topic_age:
            reasons.append("probe_topic_expired")
        if window.last_bot_activity_at is not None and (
            at - window.last_bot_activity_at < policy.recent_bot_cooldown
        ):
            reasons.append("probe_bot_activity_too_recent")
        if reasons:
            return ProbeDetectionResult(
                1,
                window.window_digest,
                ProbeDetectionStatus.INELIGIBLE,
                None,
                tuple(dict.fromkeys(reasons)),
                at,
            )
        expires_at = min(
            window.last_human_activity_at + policy.maximum_topic_age,
            at + policy.opportunity_ttl,
        )
        if expires_at <= at:
            return ProbeDetectionResult(
                1,
                window.window_digest,
                ProbeDetectionStatus.INELIGIBLE,
                None,
                ("probe_topic_expired",),
                at,
            )
        opportunity = ConversationOpportunitySnapshot(
            schema_version=1,
            opportunity_id=self._opportunity_id(window, policy),
            scope=window.scope,
            target_policy_ref=window.target_policy_ref,
            topic_refs=window.topic_refs,
            topic_summary=window.topic_summary,
            sensitivity=window.sensitivity,
            last_human_activity_at=window.last_human_activity_at,
            last_bot_activity_at=window.last_bot_activity_at,
            expires_at=expires_at,
            producer_revision=policy.detector_revision,
        )
        return ProbeDetectionResult(
            1,
            window.window_digest,
            ProbeDetectionStatus.ELIGIBLE,
            opportunity,
            ("probe_public_pause_eligible",),
            at,
        )

    def _opportunity_id(
        self,
        window: ProbeConversationWindow,
        policy: ProbePolicySnapshot,
    ) -> str:
        if self._id_factory is not None:
            value = self._id_factory()
            if not isinstance(value, str) or not value.strip():
                raise validation_error("invalid_probe_opportunity_id")
            return value
        return _bounded_id(
            "probe-opportunity",
            {
                "window_digest": window.window_digest,
                "policy_digest": policy.policy_digest,
            },
        )


class InMemoryProbeStateStore:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._states: dict[tuple[str, str], ProbeStateSnapshot] = {}
        self._lock = asyncio.Lock()

    async def load(
        self,
        namespace: str,
        target_scope_digest: str,
        *,
        call: PortCallContext,
    ) -> ProbeStateSnapshot | None:
        now = _now(self._clock)
        _validate_port_call(call, now)
        _state_key(namespace, target_scope_digest)
        async with self._lock:
            return self._states.get((namespace, target_scope_digest))

    async def claim(
        self,
        opportunity: ConversationOpportunitySnapshot,
        *,
        namespace: str,
        cooldown: timedelta,
        at: datetime,
        call: PortCallContext,
    ) -> ProbeStateClaimReceipt:
        if not isinstance(opportunity, ConversationOpportunitySnapshot):
            raise validation_error("invalid_probe_claim_opportunity")
        at = _utc(at, "probe_claim_at")
        _validate_port_call(call, at)
        if not isinstance(cooldown, timedelta) or cooldown <= timedelta(0):
            raise validation_error("invalid_probe_claim_cooldown")
        target_digest = str(scope_digest(opportunity.scope))
        _state_key(namespace, target_digest)
        if opportunity.expires_at <= at:
            raise validation_error("probe_claim_opportunity_expired")
        key = (namespace, target_digest)
        async with self._lock:
            current = self._states.get(key)
            disposition = _claim_denial(current, opportunity.snapshot_digest, at)
            if disposition is not None:
                return ProbeStateClaimReceipt(
                    1,
                    namespace,
                    target_digest,
                    opportunity.snapshot_digest,
                    disposition,
                    current.revision if current is not None else None,
                    current.revision if current is not None else None,
                    current.state_digest if current is not None else None,
                    at,
                )
            revision = 1 if current is None else current.revision + 1
            state = ProbeStateSnapshot(
                schema_version=1,
                namespace=namespace,
                scope_digest=target_digest,
                revision=revision,
                last_opportunity_digest=opportunity.snapshot_digest,
                active_until=opportunity.expires_at,
                cooldown_until=max(opportunity.expires_at, at + cooldown),
                last_outcome=None,
                last_attribution_digest=None,
                updated_at=at,
            )
            self._states[key] = state
            return ProbeStateClaimReceipt(
                1,
                namespace,
                target_digest,
                opportunity.snapshot_digest,
                ProbeStateClaimDisposition.ACQUIRED,
                current.revision if current is not None else None,
                state.revision,
                state.state_digest,
                at,
            )

    async def record_outcome(
        self,
        observation: ProbeOutcomeObservation,
        *,
        attribution_window: timedelta,
        ordinary_cooldown: timedelta,
        no_response_cooldown: timedelta,
        call: PortCallContext,
    ) -> ProbeStateSnapshot:
        if not isinstance(observation, ProbeOutcomeObservation):
            raise validation_error("invalid_probe_outcome_observation")
        now = _now(self._clock)
        _validate_port_call(call, now)
        if observation.observed_at > now:
            raise validation_error("probe_outcome_from_future")
        for value in (
            attribution_window,
            ordinary_cooldown,
            no_response_cooldown,
        ):
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise validation_error("invalid_probe_outcome_cooldown")
        if no_response_cooldown < ordinary_cooldown:
            raise validation_error("probe_no_response_cooldown_too_short")
        key = _state_key(observation.namespace, observation.scope_digest)
        async with self._lock:
            current = self._states.get(key)
            if (
                current is None
                or current.revision != observation.expected_revision
                or current.last_opportunity_digest != observation.opportunity_digest
                or observation.observed_at < current.updated_at
            ):
                raise validation_error("probe_outcome_state_conflict")
            if (
                observation.outcome is ProbeOutcomeKind.NO_OBSERVED_RESPONSE
                and observation.observed_at < current.updated_at + attribution_window
            ):
                raise validation_error("probe_no_response_attribution_open")
            cooldown = (
                no_response_cooldown
                if observation.outcome is ProbeOutcomeKind.NO_OBSERVED_RESPONSE
                else ordinary_cooldown
            )
            state = ProbeStateSnapshot(
                schema_version=1,
                namespace=current.namespace,
                scope_digest=current.scope_digest,
                revision=current.revision + 1,
                last_opportunity_digest=current.last_opportunity_digest,
                active_until=None,
                cooldown_until=observation.observed_at + cooldown,
                last_outcome=observation.outcome,
                last_attribution_digest=observation.attribution_digest,
                updated_at=observation.observed_at,
            )
            self._states[key] = state
            return state


class DeterministicProbeComposer:
    def __init__(self, *, id_factory: Callable[[], str] | None = None) -> None:
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def compose(
        self,
        opportunity: ConversationOpportunitySnapshot,
        plan: ResponsePlan,
        policy: ProbePolicySnapshot,
    ) -> DraftResponse:
        if not isinstance(opportunity, ConversationOpportunitySnapshot):
            raise validation_error("invalid_probe_composer_opportunity")
        if not isinstance(plan, ResponsePlan) or not isinstance(
            policy,
            ProbePolicySnapshot,
        ):
            raise validation_error("invalid_probe_composition_input")
        if plan.selected_profile is not AnswerProfile.SHORT:
            raise validation_error("probe_requires_short_profile")
        if _contains_mention(opportunity.topic_summary):
            raise validation_error("probe_topic_mentions_individual")
        text = opportunity.topic_summary
        if not text.endswith(("?", "\uff1f")):
            text = f"{text}?"
        if _contains_mention(text):
            raise validation_error("probe_candidate_mentions_individual")
        response_id = f"probe-response:{self._id_factory()}"
        plan_digest = response_plan_digest(plan)
        return DraftResponse(
            schema_version=1,
            response_id=response_id,
            producer=policy.composer_revision,
            intent="conversation_probe",
            content_blocks=(
                ContentBlock(
                    f"{response_id}:topic",
                    "text",
                    text,
                    opportunity.topic_refs,
                ),
            ),
            fact_anchors=(
                FactAnchor(
                    f"{response_id}:topic-fact",
                    {
                        "topic_summary": opportunity.topic_summary,
                        "topic_refs": opportunity.topic_refs,
                    },
                    opportunity.topic_refs,
                    True,
                ),
            ),
            immutable_constraints=ResponseConstraints(
                max_characters=plan.visible_character_limit,
                allow_markdown=False,
                allow_attachments=False,
            ),
            response_plan_digest=plan_digest,
        )


class ProbeCandidateBuilder:
    def __init__(
        self,
        policy: ProbePolicySnapshot,
        *,
        composer: ProbeComposer,
        persona_registry: PersonaRegistry,
        renderer: OfflinePersonaRenderer,
        final_validator: OfflineFinalResponseValidator,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        from dududa.ports.proactive import ProbeComposer

        if not isinstance(policy, ProbePolicySnapshot):
            raise validation_error("invalid_probe_policy")
        for value, expected, name in (
            (composer, ProbeComposer, "probe_composer"),
            (persona_registry, PersonaRegistry, "persona_registry"),
            (renderer, OfflinePersonaRenderer, "renderer"),
            (final_validator, OfflineFinalResponseValidator, "final_validator"),
        ):
            if not isinstance(value, expected):
                raise TypeError(f"{name} does not implement its Port")
        self._policy = policy
        self._composer = composer
        self._persona_registry = persona_registry
        self._renderer = renderer
        self._final_validator = final_validator
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def policy(self) -> ProbePolicySnapshot:
        return self._policy

    async def build(
        self,
        opportunity: ConversationOpportunitySnapshot,
        run: InitiatedRunRequest,
        actor: Actor,
        *,
        call: ServiceCallContext,
    ) -> ProbeCandidateOutcome:
        now = _now(self._clock)
        _validate_service_call(call, now)
        if (
            not isinstance(opportunity, ConversationOpportunitySnapshot)
            or not isinstance(run, InitiatedRunRequest)
            or not isinstance(actor, Actor)
            or run.trigger.opportunity != opportunity
            or run.trigger.kind is not ProactiveTriggerKind.CONVERSATION_PROBE
        ):
            raise validation_error("invalid_probe_candidate_binding")
        plan = self._response_plan(opportunity, run, now)
        snapshot = self._persona_registry.snapshot_by_id(
            self._policy.persona_catalog_snapshot_id,
            expected_digest=self._policy.persona_catalog_digest,
        )
        resolution = self._persona_registry.resolve(
            snapshot,
            self._policy.persona_id,
            self._policy.persona_version,
        )
        draft = self._composer.compose(opportunity, plan, self._policy)
        rendered = self._renderer.render(
            draft,
            plan,
            persona_resolution=resolution,
        )
        validated = await self._final_validator.validate(
            draft,
            rendered,
            actor,
            opportunity.scope,
            response_plan=plan,
            persona_resolution=resolution,
            call=_port_call(call, run.run_id),
        )
        _validate_probe_candidate(validated, plan)
        return ProbeCandidateOutcome(plan, resolution, validated)

    def _response_plan(
        self,
        opportunity: ConversationOpportunitySnapshot,
        run: InitiatedRunRequest,
        now: datetime,
    ) -> ResponsePlan:
        limits = self._policy.short_limits
        assessment_digest = canonical_digest(
            {
                "opportunity_digest": opportunity.snapshot_digest,
                "run_digest": run.start_digest,
            },
            domain="proactive:probe-profile-assessment:v1",
        )
        social_digest = canonical_digest(
            {
                "kind": "conversation_probe",
                "target_scope_digest": scope_digest(opportunity.scope),
            },
            domain="proactive:probe-social-projection:v1",
        )
        detail_digest = canonical_digest(
            {"current_message": None, "source": "opportunity"},
            domain="proactive:probe-detail-evidence:v1",
        )
        fingerprint = canonical_digest(
            {
                "assessment_digest": assessment_digest,
                "selected_profile": AnswerProfile.SHORT,
                "policy_digest": self._policy.policy_digest,
            },
            domain="proactive:probe-profile-selection:v1",
        )
        return ResponsePlan(
            schema_version=1,
            plan_id=_bounded_id("probe-plan", fingerprint),
            requested_profile=None,
            uncapped_profile=AnswerProfile.SHORT,
            selected_profile=AnswerProfile.SHORT,
            visible_token_limit=limits.visible_token_units,
            visible_character_limit=limits.visible_characters,
            delivery_part_limit=limits.delivery_parts,
            delivery_part_character_limit=min(
                limits.visible_characters,
                self._policy.delivery_part_character_limit,
            ),
            generated_token_limit=limits.generated_tokens,
            assessment_digest=assessment_digest,
            social_decision_digest=social_digest,
            detail_evidence_digest=detail_digest,
            persistent_preference_digest=None,
            policy_digest=self._policy.policy_digest,
            policy_revision=self._policy.response_policy_revision,
            selection_fingerprint=fingerprint,
            reason_codes=("conversation_probe_fixed_short",),
            decided_at=now,
        )


class ProbeShadowRuntime:
    def __init__(
        self,
        control: ProactiveControlConfig,
        policy: ProbePolicySnapshot,
        *,
        target_registry: ProactiveTargetRegistry,
        actor_resolver: ProactiveActorResolver,
        detector: ProbeOpportunityDetector,
        state_store: ProbeStateStore,
        candidate_builder: ProbeCandidateBuilder,
        metadata_sink: ProbeShadowMetadataSink,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(control, ProactiveControlConfig) or not isinstance(
            policy,
            ProbePolicySnapshot,
        ):
            raise validation_error("invalid_probe_shadow_configuration")
        if candidate_builder.policy != policy:
            raise validation_error("probe_builder_policy_mismatch")
        self._control = control
        self._policy = policy
        self._target_registry = target_registry
        self._actor_resolver = actor_resolver
        self._detector = detector
        self._state_store = state_store
        self._candidate_builder = candidate_builder
        self._metadata_sink = metadata_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._namespace = f"shadow:{policy.snapshot_id}"

    async def run(
        self,
        request: ProbeShadowRequest,
        *,
        call: ServiceCallContext,
    ) -> ProbeShadowMetadata:
        if not isinstance(request, ProbeShadowRequest):
            raise validation_error("invalid_probe_shadow_request")
        now = _now(self._clock)
        _validate_service_call(call, now)
        denial = self._admission_denial(request, now)
        if denial is not None:
            return await self._record(
                request,
                ProactiveDisposition.DENIED,
                denial,
                call=call,
            )
        try:
            target = await self._target_registry.validate_target(
                request.window.target_policy_ref,
                trigger_kind=ProactiveTriggerKind.CONVERSATION_PROBE,
                categories=frozenset(),
                at=now,
                call=call,
            )
        except Exception:  # noqa: BLE001 - registry detail stays private.
            return await self._record(
                request,
                ProactiveDisposition.DENIED,
                "probe_target_or_grant_invalid",
                call=call,
            )
        detection_at = _now(self._clock)
        denial = self._admission_denial(request, detection_at)
        if denial is not None:
            return await self._record(
                request,
                ProactiveDisposition.DENIED,
                denial,
                call=call,
            )
        detection = self._detector.detect(request.window, self._policy, at=detection_at)
        if detection.opportunity is None:
            return await self._record(
                request,
                ProactiveDisposition.DENIED,
                detection.reason_codes[0],
                detection=detection,
                call=call,
            )
        opportunity = detection.opportunity
        try:
            claim = await self._state_store.claim(
                opportunity,
                namespace=self._namespace,
                cooldown=self._policy.shadow_cooldown,
                at=detection_at,
                call=_port_call(call, request.request_id),
            )
        except Exception:  # noqa: BLE001 - state detail stays private.
            return await self._record(
                request,
                ProactiveDisposition.FAILED,
                "probe_state_unavailable",
                detection=detection,
                opportunity=opportunity,
                call=call,
            )
        if not claim.acquired:
            return await self._record(
                request,
                ProactiveDisposition.DENIED,
                f"probe_state_{claim.disposition.value}",
                detection=detection,
                opportunity=opportunity,
                claim=claim,
                call=call,
            )
        run_at = _now(self._clock)
        if opportunity.expires_at <= run_at:
            return await self._record(
                request,
                ProactiveDisposition.DENIED,
                "probe_opportunity_expired_before_run",
                detection=detection,
                opportunity=opportunity,
                claim=claim,
                call=call,
            )
        trigger, run = _build_probe_run(request, opportunity, run_at)
        if request.mode is ProactiveRunMode.COLLECT:
            return await self._record(
                request,
                ProactiveDisposition.COLLECTED,
                "probe_opportunity_collected",
                detection=detection,
                opportunity=opportunity,
                claim=claim,
                trigger=trigger,
                run=run,
                call=call,
            )
        try:
            operator_grant = await self._target_registry.resolve_grant(
                target.operator_authorization_grant_ref,
                at=run_at,
                call=call,
            )
            actor = await self._actor_resolver.resolve(
                operator_grant.issuer_ref,
                opportunity.scope,
                call=call,
            )
            compose_at = _now(self._clock)
            denial = self._admission_denial(request, compose_at)
            if denial is not None or opportunity.expires_at <= compose_at:
                return await self._record(
                    request,
                    ProactiveDisposition.DENIED,
                    denial or "probe_opportunity_expired_before_composition",
                    detection=detection,
                    opportunity=opportunity,
                    claim=claim,
                    trigger=trigger,
                    run=run,
                    call=call,
                )
            candidate = await self._candidate_builder.build(
                opportunity,
                run,
                actor,
                call=call,
            )
        except Exception:  # noqa: BLE001 - dependency detail stays private.
            return await self._record(
                request,
                ProactiveDisposition.FAILED,
                "probe_shadow_dependency_failed",
                detection=detection,
                opportunity=opportunity,
                claim=claim,
                trigger=trigger,
                run=run,
                call=call,
            )
        return await self._record(
            request,
            ProactiveDisposition.SHADOWED,
            "probe_candidate_built",
            detection=detection,
            opportunity=opportunity,
            claim=claim,
            trigger=trigger,
            run=run,
            candidate=candidate,
            call=call,
        )

    def _admission_denial(
        self,
        request: ProbeShadowRequest,
        now: datetime,
    ) -> str | None:
        behavior = self._control.probe
        if request.mode not in {ProactiveRunMode.COLLECT, ProactiveRunMode.SHADOW}:
            return "probe_mode_not_supported"
        if behavior.mode is not request.mode:
            return "probe_control_mode_mismatch"
        if behavior.kill_switch:
            return "probe_kill_switch_active"
        if not behavior.allowlisted_scope_digests:
            return "probe_scope_allowlist_empty"
        if scope_digest(request.window.scope) not in behavior.allowlisted_scope_digests:
            return "probe_scope_not_allowlisted"
        if (
            request.config_snapshot_id != self._policy.snapshot_id
            or request.response_policy_revision != self._policy.response_policy_revision
        ):
            return "probe_policy_snapshot_mismatch"
        local = (
            now.astimezone(ZoneInfo(behavior.timezone)).timetz().replace(tzinfo=None)
        )
        if any(window.contains(local) for window in behavior.quiet_hours):
            return "probe_quiet_hours"
        return None

    async def _record(
        self,
        request: ProbeShadowRequest,
        disposition: ProactiveDisposition,
        reason: str,
        *,
        detection: ProbeDetectionResult | None = None,
        opportunity: ConversationOpportunitySnapshot | None = None,
        claim: ProbeStateClaimReceipt | None = None,
        trigger: ProactiveTrigger | None = None,
        run: InitiatedRunRequest | None = None,
        candidate: ProbeCandidateOutcome | None = None,
        call: ServiceCallContext,
    ) -> ProbeShadowMetadata:
        response = candidate.validated_response if candidate is not None else None
        resolution = candidate.persona_resolution if candidate is not None else None
        metadata = ProbeShadowMetadata(
            schema_version=1,
            request_id=request.request_id,
            window_digest=request.window.window_digest,
            target_scope_digest=scope_digest(request.window.scope),
            mode=request.mode,
            disposition=disposition,
            policy_digest=self._policy.policy_digest,
            detection_result_digest=(
                detection.result_digest if detection is not None else None
            ),
            opportunity_digest=(
                opportunity.snapshot_digest if opportunity is not None else None
            ),
            state_claim_receipt_digest=(
                claim.receipt_digest if claim is not None else None
            ),
            trigger_digest=trigger.trigger_digest if trigger is not None else None,
            run_digest=run.start_digest if run is not None else None,
            response_plan_digest=(
                response_plan_digest(candidate.response_plan)
                if candidate is not None
                else None
            ),
            candidate_response_digest=(
                canonical_digest(response.response, domain="response:final:v1")
                if response is not None
                else None
            ),
            persona_catalog_digest=(
                resolution.catalog_digest if resolution is not None else None
            ),
            persona_source_digest=(
                resolution.definition.source_digest if resolution is not None else None
            ),
            reason_codes=(reason,),
            completed_at=_now(self._clock),
        )
        await self._metadata_sink.record(metadata, call=call)
        return metadata


def _build_probe_run(
    request: ProbeShadowRequest,
    opportunity: ConversationOpportunitySnapshot,
    at: datetime,
) -> tuple[ProactiveTrigger, InitiatedRunRequest]:
    trigger = ProactiveTrigger(
        schema_version=1,
        trigger_id=_bounded_id("probe-trigger", opportunity.snapshot_digest),
        kind=ProactiveTriggerKind.CONVERSATION_PROBE,
        target_scope=opportunity.scope,
        occurrence=None,
        opportunity=opportunity,
        target_policy_ref=opportunity.target_policy_ref,
        created_at=at,
        expires_at=opportunity.expires_at,
    )
    run = InitiatedRunRequest(
        schema_version=1,
        run_id=_bounded_id("probe-run", trigger.trigger_digest),
        trigger=trigger,
        target_policy_ref=opportunity.target_policy_ref,
        mode=request.mode,
        config_snapshot_id=request.config_snapshot_id,
        source_policy_revision="probe-no-source-v1",
        response_policy_revision=request.response_policy_revision,
    )
    return trigger, run


def _claim_denial(
    state: ProbeStateSnapshot | None,
    opportunity_digest: str,
    at: datetime,
) -> ProbeStateClaimDisposition | None:
    if state is None:
        return None
    if state.last_opportunity_digest == opportunity_digest:
        return ProbeStateClaimDisposition.DUPLICATE
    if state.active_until is not None and at < state.active_until:
        return ProbeStateClaimDisposition.ACTIVE
    if state.cooldown_until is not None and at < state.cooldown_until:
        return ProbeStateClaimDisposition.COOLDOWN
    return None


def _validate_probe_candidate(
    response: ValidatedFinalResponse,
    plan: ResponsePlan,
) -> None:
    final = response.response
    if (
        plan.selected_profile is not AnswerProfile.SHORT
        or len(final.blocks) != 1
        or final.target_users
        or final.attachments
    ):
        raise validation_error("invalid_probe_candidate_shape")
    text = final.blocks[0].content.text
    if text is None or _contains_mention(text):
        raise validation_error("probe_candidate_mentions_individual")


def _contains_mention(value: str) -> bool:
    return _MENTION_PATTERN.search(value) is not None


def _state_key(namespace: object, target_scope_digest: object) -> tuple[str, str]:
    if not isinstance(namespace, str) or not namespace.strip():
        raise validation_error("invalid_probe_state_namespace")
    if not isinstance(target_scope_digest, str) or not target_scope_digest.strip():
        raise validation_error("invalid_probe_state_scope_digest")
    return namespace, target_scope_digest


def _bounded_id(prefix: str, value: object) -> str:
    digest = str(
        canonical_digest(
            value,
            domain=f"proactive:{prefix}-identity:v1",
        )
    )
    return f"{prefix}:{digest.rsplit(':', 1)[-1]}"


def _port_call(call: ServiceCallContext, run_id: str) -> PortCallContext:
    return PortCallContext(
        run_id,
        call.trace,
        call.deadline,
        call.cancellation,
        call.budget,
        call.policy_snapshot_id,
    )


def _validate_service_call(call: ServiceCallContext, now: datetime) -> None:
    if not isinstance(call, ServiceCallContext):
        raise validation_error("invalid_probe_service_call")
    if call.cancellation.is_cancelled or call.deadline <= now:
        raise validation_error("probe_call_cancelled_or_expired")


def _validate_port_call(call: PortCallContext, now: datetime) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_probe_port_call")
    if call.cancellation.is_cancelled or call.deadline <= now:
        raise validation_error("probe_call_cancelled_or_expired")


def _utc(value: datetime, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise validation_error("invalid_probe_datetime", field_name)
    return value.astimezone(timezone.utc)


def _now(clock: Callable[[], datetime]) -> datetime:
    return _utc(clock(), "probe_clock")


__all__ = [
    "DeterministicProbeComposer",
    "DeterministicProbeOpportunityDetector",
    "InMemoryProbeStateStore",
    "ProbeCandidateBuilder",
    "ProbeCandidateOutcome",
    "ProbeShadowRuntime",
]
