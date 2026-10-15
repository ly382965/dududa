from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from dududa.contracts.canonical import canonical_digest
from dududa.domain.content import (
    ContentBlock,
    DraftResponse,
    FactAnchor,
    SafetyNotice,
    ValidatedFinalResponse,
)
from dududa.domain.identity import Actor
from dududa.domain.primitives import ResponseConstraints
from dududa.errors import validation_error
from dududa.persona.contracts import PersonaResolution
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.ports.persona import PersonaRegistry
from dududa.ports.runtime import (
    OfflineFinalResponseValidator,
    OfflinePersonaRenderer,
)
from dududa.responses.contracts import (
    AnswerProfile,
    ResponsePlan,
    profile_at_most,
)
from dududa.responses.digests import response_plan_digest
from dududa.security.digests import scope_digest

from .config import ProactiveControlConfig
from .contracts import (
    InitiatedRunRequest,
    ProactiveDisposition,
    ProactivePreviewRequest,
    ProactiveRunMode,
    ProactiveRunReceipt,
    ProactiveSubscription,
    ProactiveTriggerKind,
    SourceBatch,
    SubscriptionStatus,
)
from .digest_contracts import (
    DigestCompositionPolicySnapshot,
    DigestShadowMetadata,
)
from .source_contracts import (
    SourceFetchOriginKind,
    SourceFetchReceipt,
    SourceFetchRequest,
    SourceFetchStatus,
)

if TYPE_CHECKING:
    from dududa.ports.proactive import (
        DigestComposer,
        DigestShadowMetadataSink,
        ProactiveActorResolver,
        ProactiveSubscriptionStore,
        SourceProvider,
    )


@dataclass(frozen=True, slots=True)
class DigestCandidateOutcome:
    fetch_receipt: SourceFetchReceipt
    response_plan: ResponsePlan | None
    persona_resolution: PersonaResolution | None
    validated_response: ValidatedFinalResponse | None
    item_set_digest: str | None
    reason_code: str

    @property
    def candidate_built(self) -> bool:
        return self.validated_response is not None


class DeterministicDigestComposer:
    def __init__(self, *, id_factory: Callable[[], str] | None = None) -> None:
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def compose(
        self,
        batch: SourceBatch,
        plan: ResponsePlan,
        policy: DigestCompositionPolicySnapshot,
    ) -> DraftResponse:
        if not isinstance(batch, SourceBatch) or not batch.items:
            raise validation_error("digest_composer_requires_items")
        if not isinstance(plan, ResponsePlan) or not isinstance(
            policy,
            DigestCompositionPolicySnapshot,
        ):
            raise validation_error("invalid_digest_composition_input")
        plan_digest = response_plan_digest(plan)
        response_id = f"digest-response:{self._id_factory()}"
        blocks = []
        anchors = []
        citations = []
        for index, item in enumerate(batch.items, start=1):
            block_id = f"{response_id}:item:{index}"
            blocks.append(
                ContentBlock(
                    block_id,
                    "text",
                    f"{item.title}\n{item.summary}\n{item.canonical_url}",
                    (str(item.content_digest),),
                )
            )
            anchors.append(
                FactAnchor(
                    f"{response_id}:fact:{index}",
                    {
                        "title": item.title,
                        "summary": item.summary,
                        "canonical_url": item.canonical_url,
                        "published_at": (
                            item.published_at.isoformat()
                            if item.published_at is not None
                            else None
                        ),
                        "source_revision": item.source_revision,
                    },
                    (str(item.content_digest),),
                    True,
                )
            )
            citations.extend(item.citations)
        citation_ids = tuple(item.citation_id for item in citations)
        if len(citation_ids) != len(set(citation_ids)):
            raise validation_error("duplicate_digest_citation")
        warnings = tuple(
            SafetyNotice(
                f"source-failure:{failure.source_id}",
                f"source.{failure.error_code}",
            )
            for failure in batch.failed_sources
        )
        return DraftResponse(
            schema_version=1,
            response_id=response_id,
            producer=policy.component_revision,
            intent="scheduled_digest",
            content_blocks=tuple(blocks),
            fact_anchors=tuple(anchors),
            citations=tuple(citations),
            warnings=warnings,
            immutable_constraints=ResponseConstraints(
                max_characters=plan.visible_character_limit,
                allow_markdown=False,
                allow_attachments=False,
            ),
            response_plan_digest=plan_digest,
        )


class DigestCandidateBuilder:
    def __init__(
        self,
        policy: DigestCompositionPolicySnapshot,
        *,
        source_provider: SourceProvider,
        composer: DigestComposer,
        persona_registry: PersonaRegistry,
        renderer: OfflinePersonaRenderer,
        final_validator: OfflineFinalResponseValidator,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        from dududa.ports.proactive import DigestComposer, SourceProvider

        if not isinstance(policy, DigestCompositionPolicySnapshot):
            raise validation_error("invalid_digest_composition_policy")
        for value, expected, name in (
            (source_provider, SourceProvider, "source_provider"),
            (composer, DigestComposer, "composer"),
            (persona_registry, PersonaRegistry, "persona_registry"),
            (renderer, OfflinePersonaRenderer, "renderer"),
            (final_validator, OfflineFinalResponseValidator, "final_validator"),
        ):
            if not isinstance(value, expected):
                raise TypeError(f"{name} does not implement its Port")
        self._policy = policy
        self._source_provider = source_provider
        self._composer = composer
        self._persona_registry = persona_registry
        self._renderer = renderer
        self._final_validator = final_validator
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def policy(self) -> DigestCompositionPolicySnapshot:
        return self._policy

    async def build(
        self,
        subscription: ProactiveSubscription,
        actor: Actor,
        *,
        origin_kind: SourceFetchOriginKind,
        origin_digest: str,
        state_namespace: str,
        call: ServiceCallContext,
    ) -> DigestCandidateOutcome:
        if not isinstance(subscription, ProactiveSubscription) or not isinstance(
            actor,
            Actor,
        ):
            raise validation_error("invalid_digest_candidate_identity")
        if not isinstance(origin_kind, SourceFetchOriginKind):
            raise validation_error("invalid_digest_candidate_origin")
        now = _now(self._clock)
        _validate_service_call(call, now)
        fetch_request = SourceFetchRequest(
            schema_version=1,
            request_id=_bounded_id(
                "source-fetch",
                {
                    "origin_digest": origin_digest,
                    "state_namespace": state_namespace,
                    "policy_digest": self._policy.policy_digest,
                },
            ),
            subscription_id=state_namespace,
            subscription_revision=subscription.revision,
            origin_kind=origin_kind,
            origin_digest=origin_digest,
            source_policy_id=self._policy.source_policy_id,
            source_policy_digest=self._policy.source_policy_digest,
            source_ids=self._policy.source_ids,
            categories=subscription.categories,
            maximum_age=subscription.maximum_age,
            maximum_items=subscription.maximum_items,
            requested_at=now,
        )
        fetch_receipt = await self._source_provider.fetch(
            fetch_request,
            call=_port_call(call, fetch_request.request_id),
        )
        if fetch_receipt.status in {
            SourceFetchStatus.FAILED,
            SourceFetchStatus.CANCELLED,
        }:
            return DigestCandidateOutcome(
                fetch_receipt,
                None,
                None,
                None,
                None,
                f"source_{fetch_receipt.status.value}",
            )
        if fetch_receipt.batch is None or not fetch_receipt.batch.items:
            return DigestCandidateOutcome(
                fetch_receipt,
                None,
                None,
                None,
                None,
                "source_no_new_items",
            )
        plan = self._response_plan(subscription, origin_digest, fetch_receipt)
        snapshot = self._persona_registry.snapshot_by_id(
            self._policy.persona_catalog_snapshot_id,
            expected_digest=self._policy.persona_catalog_digest,
        )
        resolution = self._persona_registry.resolve(
            snapshot,
            self._policy.persona_id,
            self._policy.persona_version,
        )
        draft = self._composer.compose(fetch_receipt.batch, plan, self._policy)
        rendered = self._renderer.render(
            draft,
            plan,
            persona_resolution=resolution,
        )
        validated = await self._final_validator.validate(
            draft,
            rendered,
            actor,
            subscription.target_scope,
            response_plan=plan,
            persona_resolution=resolution,
            call=_port_call(call, fetch_request.request_id),
        )
        item_set_digest = str(
            canonical_digest(
                tuple(item.content_digest for item in fetch_receipt.batch.items),
                domain="proactive:digest-item-set:v1",
            )
        )
        return DigestCandidateOutcome(
            fetch_receipt,
            plan,
            resolution,
            validated,
            item_set_digest,
            "digest_candidate_built",
        )

    def _response_plan(
        self,
        subscription: ProactiveSubscription,
        origin_digest: str,
        fetch_receipt: SourceFetchReceipt,
    ) -> ResponsePlan:
        uncapped = subscription.answer_profile
        selected = profile_at_most(uncapped, self._policy.maximum_profile)
        limits = self._policy.limits_for(selected)
        assessment_digest = canonical_digest(
            {
                "subscription_digest": subscription.subscription_digest,
                "origin_digest": origin_digest,
                "source_fetch_receipt_digest": fetch_receipt.receipt_digest,
            },
            domain="proactive:digest-profile-assessment:v1",
        )
        social_digest = canonical_digest(
            {
                "kind": "scheduled_digest",
                "target_scope_digest": scope_digest(subscription.target_scope),
            },
            domain="proactive:digest-social-projection:v1",
        )
        detail_digest = canonical_digest(
            {"current_message": None, "source": "subscription"},
            domain="proactive:digest-detail-evidence:v1",
        )
        selection_fingerprint = canonical_digest(
            {
                "assessment_digest": assessment_digest,
                "selected_profile": selected,
                "policy_digest": self._policy.policy_digest,
            },
            domain="proactive:digest-profile-selection:v1",
        )
        reasons = ["scheduled_digest_profile"]
        if uncapped is AnswerProfile.LONG:
            reasons.append("digest_long_capped_to_medium")
        return ResponsePlan(
            schema_version=1,
            plan_id=_bounded_id("digest-plan", selection_fingerprint),
            requested_profile=None,
            uncapped_profile=uncapped,
            selected_profile=selected,
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
            selection_fingerprint=selection_fingerprint,
            reason_codes=tuple(reasons),
            decided_at=_now(self._clock),
        )


class DigestShadowRuntime:
    def __init__(
        self,
        control: ProactiveControlConfig,
        *,
        subscription_store: ProactiveSubscriptionStore,
        actor_resolver: ProactiveActorResolver,
        candidate_builder: DigestCandidateBuilder,
        metadata_sink: DigestShadowMetadataSink,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(control, ProactiveControlConfig):
            raise validation_error("invalid_digest_shadow_control")
        if not isinstance(candidate_builder, DigestCandidateBuilder):
            raise validation_error("invalid_digest_candidate_builder")
        self._control = control
        self._subscription_store = subscription_store
        self._actor_resolver = actor_resolver
        self._builder = candidate_builder
        self._metadata_sink = metadata_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def run(
        self,
        request: InitiatedRunRequest,
        *,
        call: ServiceCallContext,
    ) -> ProactiveRunReceipt:
        if not isinstance(request, InitiatedRunRequest):
            raise validation_error("invalid_digest_shadow_request")
        now = _now(self._clock)
        _validate_service_call(call, now)
        if request.mode not in {ProactiveRunMode.COLLECT, ProactiveRunMode.SHADOW}:
            return self._receipt(
                request,
                ProactiveDisposition.DENIED,
                "digest_mode_not_supported",
                completed_at=now,
            )
        identity = _scheduled_identity(request)
        denial = self._admission_denial(request, now)
        subscription = await self._subscription_store.load(identity[0], call=call)
        if denial is None:
            denial = _subscription_denial(
                request,
                subscription,
                source_policy_id=self._builder.policy.source_policy_id,
            )
        if denial is not None or subscription is None:
            reason = denial or "digest_subscription_not_found"
            await self._record(
                request,
                identity,
                ProactiveDisposition.DENIED,
                reason,
                outcome=None,
                call=call,
            )
            return self._receipt(
                request,
                ProactiveDisposition.DENIED,
                reason,
                completed_at=_now(self._clock),
            )
        if request.mode is ProactiveRunMode.COLLECT:
            await self._record(
                request,
                identity,
                ProactiveDisposition.COLLECTED,
                "digest_trigger_collected",
                outcome=None,
                call=call,
            )
            return self._receipt(
                request,
                ProactiveDisposition.COLLECTED,
                "digest_trigger_collected",
                completed_at=_now(self._clock),
            )
        try:
            actor = await self._actor_resolver.resolve(
                subscription.owner_ref,
                subscription.target_scope,
                call=call,
            )
            source_now = _now(self._clock)
            if request.trigger.expires_at <= source_now:
                reason = "digest_trigger_expired"
                await self._record(
                    request,
                    identity,
                    ProactiveDisposition.DENIED,
                    reason,
                    outcome=None,
                    call=call,
                )
                return self._receipt(
                    request,
                    ProactiveDisposition.DENIED,
                    reason,
                    completed_at=source_now,
                )
            _validate_service_call(call, source_now)
            outcome = await self._builder.build(
                subscription,
                actor,
                origin_kind=SourceFetchOriginKind.SCHEDULED_TRIGGER,
                origin_digest=request.trigger.trigger_digest,
                state_namespace=subscription.subscription_id,
                call=call,
            )
        except Exception:  # noqa: BLE001 - dependency details stay private.
            await self._record(
                request,
                identity,
                ProactiveDisposition.FAILED,
                "digest_shadow_dependency_failed",
                outcome=None,
                call=call,
            )
            return self._receipt(
                request,
                ProactiveDisposition.FAILED,
                "digest_shadow_dependency_failed",
                completed_at=_now(self._clock),
            )
        disposition = (
            ProactiveDisposition.FAILED
            if outcome.fetch_receipt.status
            in {SourceFetchStatus.FAILED, SourceFetchStatus.CANCELLED}
            else ProactiveDisposition.SHADOWED
        )
        await self._record(
            request,
            identity,
            disposition,
            outcome.reason_code,
            outcome=outcome,
            call=call,
        )
        batch_digest = (
            outcome.fetch_receipt.batch.batch_digest
            if outcome.fetch_receipt.batch is not None
            else None
        )
        return self._receipt(
            request,
            disposition,
            outcome.reason_code,
            source_batch_digest=batch_digest,
            completed_at=_now(self._clock),
        )

    def _admission_denial(
        self,
        request: InitiatedRunRequest,
        now: datetime,
    ) -> str | None:
        if (
            request.trigger.kind is not ProactiveTriggerKind.SCHEDULED_DIGEST
            or request.trigger.occurrence is None
        ):
            return "digest_requires_scheduled_trigger"
        if request.trigger.expires_at <= now:
            return "digest_trigger_expired"
        behavior = self._control.for_trigger(request.trigger.kind)
        if behavior.mode is not request.mode:
            return "digest_control_mode_mismatch"
        if behavior.kill_switch:
            return "digest_kill_switch_active"
        if scope_digest(request.trigger.target_scope) not in (
            behavior.allowlisted_scope_digests
        ):
            return "digest_scope_not_allowlisted"
        policy = self._builder.policy
        if (
            request.config_snapshot_id != policy.snapshot_id
            or request.source_policy_revision != policy.source_policy_revision
            or request.response_policy_revision != policy.response_policy_revision
        ):
            return "digest_composition_policy_mismatch"
        return None

    async def _record(
        self,
        request: InitiatedRunRequest,
        identity: tuple[str, int],
        disposition: ProactiveDisposition,
        reason: str,
        *,
        outcome: DigestCandidateOutcome | None,
        call: ServiceCallContext,
    ) -> None:
        batch = (
            outcome.fetch_receipt.batch
            if outcome is not None and outcome.fetch_receipt.batch is not None
            else None
        )
        response = outcome.validated_response if outcome is not None else None
        plan = outcome.response_plan if outcome is not None else None
        persona = outcome.persona_resolution if outcome is not None else None
        metadata = DigestShadowMetadata(
            schema_version=1,
            run_id=request.run_id,
            origin_digest=request.start_digest,
            target_scope_digest=scope_digest(request.trigger.target_scope),
            subscription_id=identity[0],
            subscription_revision=identity[1],
            mode=request.mode,
            disposition=disposition,
            policy_digest=self._builder.policy.policy_digest,
            source_fetch_status=(
                outcome.fetch_receipt.status if outcome is not None else None
            ),
            source_fetch_receipt_digest=(
                outcome.fetch_receipt.receipt_digest if outcome is not None else None
            ),
            source_batch_digest=(batch.batch_digest if batch is not None else None),
            item_set_digest=(outcome.item_set_digest if outcome is not None else None),
            response_plan_digest=(
                response_plan_digest(plan) if plan is not None else None
            ),
            candidate_response_digest=(
                canonical_digest(response.response, domain="response:final:v1")
                if response is not None
                else None
            ),
            persona_catalog_digest=(
                persona.catalog_digest if persona is not None else None
            ),
            persona_source_digest=(
                persona.definition.source_digest if persona is not None else None
            ),
            reason_codes=(reason,),
            completed_at=_now(self._clock),
        )
        await self._metadata_sink.record(metadata, call=call)

    @staticmethod
    def _receipt(
        request: InitiatedRunRequest,
        disposition: ProactiveDisposition,
        reason: str,
        *,
        source_batch_digest=None,
        completed_at: datetime,
    ) -> ProactiveRunReceipt:
        return ProactiveRunReceipt(
            1,
            request.run_id,
            request.trigger.trigger_id,
            request.mode,
            disposition,
            None,
            source_batch_digest,
            None,
            None,
            (reason,),
            completed_at,
        )


class DigestPreviewProducer:
    def __init__(
        self,
        *,
        subscription_store: ProactiveSubscriptionStore,
        candidate_builder: DigestCandidateBuilder,
    ) -> None:
        self._subscription_store = subscription_store
        self._builder = candidate_builder

    async def build(
        self,
        request: ProactivePreviewRequest,
        *,
        call: ServiceCallContext,
    ) -> tuple[ValidatedFinalResponse, str | None]:
        if not isinstance(request, ProactivePreviewRequest):
            raise validation_error("invalid_digest_preview_request")
        policy = self._builder.policy
        if (
            request.config_snapshot_id != policy.snapshot_id
            or request.source_policy_revision != policy.source_policy_revision
            or request.response_policy_revision != policy.response_policy_revision
        ):
            raise validation_error("digest_preview_policy_mismatch")
        subscription = await self._subscription_store.load(
            request.subscription_id,
            call=call,
        )
        if (
            subscription is None
            or subscription.revision != request.subscription_revision
            or subscription.status is not SubscriptionStatus.ACTIVE
            or subscription.target_scope != request.target_scope
            or subscription.target_policy_ref != request.target_policy_ref
            or subscription.source_policy_id != policy.source_policy_id
        ):
            raise validation_error("digest_preview_subscription_mismatch")
        namespace = _bounded_id(
            "preview",
            {
                "preview_id": request.preview_id,
                "subscription_id": subscription.subscription_id,
                "subscription_revision": subscription.revision,
            },
        )
        outcome = await self._builder.build(
            subscription,
            request.requested_by,
            origin_kind=SourceFetchOriginKind.PREVIEW_REQUEST,
            origin_digest=request.request_digest,
            state_namespace=namespace,
            call=call,
        )
        if outcome.validated_response is None:
            raise validation_error(
                "digest_preview_has_no_candidate", outcome.reason_code
            )
        batch = outcome.fetch_receipt.batch
        assert batch is not None
        return outcome.validated_response, batch.batch_digest


def _scheduled_identity(request: InitiatedRunRequest) -> tuple[str, int]:
    occurrence = request.trigger.occurrence
    if occurrence is None:
        return "invalid-scheduled-digest", 1
    return occurrence.subscription_id, occurrence.subscription_revision


def _subscription_denial(
    request: InitiatedRunRequest,
    subscription: ProactiveSubscription | None,
    *,
    source_policy_id: str,
) -> str | None:
    occurrence = request.trigger.occurrence
    if occurrence is None:
        return "digest_occurrence_missing"
    if subscription is None:
        return "digest_subscription_not_found"
    if (
        subscription.subscription_id != occurrence.subscription_id
        or subscription.revision != occurrence.subscription_revision
        or subscription.status is not SubscriptionStatus.ACTIVE
        or subscription.target_scope != request.trigger.target_scope
        or subscription.target_policy_ref != request.target_policy_ref
        or subscription.source_policy_id != source_policy_id
    ):
        return "digest_subscription_binding_invalid"
    return None


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
        raise validation_error("invalid_digest_service_call")
    if call.cancellation.is_cancelled or call.deadline <= now:
        raise validation_error("digest_call_cancelled_or_expired")


def _now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise validation_error("invalid_digest_clock")
    return value.astimezone(timezone.utc)


__all__ = [
    "DeterministicDigestComposer",
    "DigestCandidateBuilder",
    "DigestCandidateOutcome",
    "DigestPreviewProducer",
    "DigestShadowRuntime",
]
