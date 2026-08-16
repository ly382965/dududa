from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from dududa.capabilities.contracts import (
    CapabilityRunReceipt,
    CapabilityRunRequest,
    CapabilityRunStatus,
    ToolObservation,
)
from dududa.capabilities.digests import (
    capability_run_receipt_digest,
    capability_run_request_digest,
)
from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.domain.delivery import DeliveryReceipt, DeliveryStatus
from dududa.domain.identity import ConversationScope
from dududa.domain.primitives import (
    ComponentRevision,
    Outcome,
    require_aware,
    require_non_empty,
)
from dududa.domain.task import TaskComplexityAssessment
from dududa.errors import DududaError, ErrorCategory, error, validation_error
from dududa.models.contracts import ModelRole
from dududa.models.digests import (
    route_decision_digest,
    task_complexity_assessment_digest,
    tier_decision_digest,
)
from dududa.perception.contracts import SocialAction, SocialDecision
from dududa.perception.digests import social_decision_digest
from dududa.persona.contracts import (
    PersonaCatalogSnapshot,
    PersonaResolution,
    validate_persona_resolution,
)
from dududa.ports.capabilities import BoundedCapabilityRuntime
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.ports.models import ModelTierPolicy
from dududa.ports.perception import SocialDecisionEngine, TaskComplexityAssessor
from dududa.ports.persona import PersonaRegistry
from dududa.ports.responses import ResponseProfilePolicy
from dududa.ports.runtime import (
    OfflineFinalResponseValidator,
    OfflinePersonaRenderer,
    OfflineResponseComposer,
    RuntimePerceptionEngine,
    RuntimeStateStore,
)
from dududa.responses.budget import project_response_reservation
from dududa.responses.contracts import (
    ResponsePlan,
    ResponseProfileSelectionRequest,
)
from dududa.responses.evidence import detect_detail_preference
from dududa.security.digests import actor_digest, scope_digest
from dududa.security.models import AuthorizationEffect
from dududa.security.ports import AuthorizationDecisionVerifier, AuthorizationPolicy

from .authorization import (
    build_capability_plan_authorization_request,
    build_response_authorization_request,
)
from .budget import (
    RuntimeModelBudgetPlan,
    RuntimeToolBudgetPlan,
    add_usage,
    charge_budget,
    reservation_budget,
    usage_within_tool_reservation,
    zero_usage_for_budget,
)
from .capabilities import (
    project_capability_run_request,
    tool_context_privacy_level,
    tool_context_tokens_upper_bound,
)
from .context import CurrentMessageContextBuilder
from .contracts import (
    CurrentMessageContext,
    DeliveryReconciliationReceipt,
    OfflineRuntimePolicySnapshot,
    RuntimeAdmissionAction,
)
from .delivery import (
    DeliveryRequestBuilder,
    delivery_acknowledgement_states,
    reconcile_completed_delivery,
)
from .direct_chat import DirectChatModelCall, RuntimeDirectChatFailure
from .selection import (
    project_s10_decision_signals,
    project_tier_selection_context,
    select_model_tier,
)
from .state import (
    CompletionReceipt,
    RuntimeCheckpoint,
    RuntimeCommitDisposition,
    RuntimeCommitRequest,
    RuntimePhase,
    RuntimeResult,
    RuntimeSelectionSummary,
    RuntimeStartRequest,
    RuntimeState,
    TraceSummary,
    append_runtime_phase_trace,
    runtime_start_digest,
    transition,
)


@dataclass(frozen=True, slots=True)
class OfflineRuntimeOrchestratorConfig:
    schema_version: int
    persona_id: str
    model_budget_plan: RuntimeModelBudgetPlan
    runtime_policy: OfflineRuntimePolicySnapshot
    negotiated_bindings: tuple[NegotiatedBindingReceipt, ...]
    component_revision: ComponentRevision
    tool_budget_plan: RuntimeToolBudgetPlan | None = None
    terminal_commit_grace: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        require_non_empty(self.persona_id, "runtime_persona_id")
        if not isinstance(self.model_budget_plan, RuntimeModelBudgetPlan):
            raise validation_error("invalid_runtime_model_budget_plan")
        if not isinstance(self.runtime_policy, OfflineRuntimePolicySnapshot):
            raise validation_error("invalid_offline_runtime_policy_snapshot")
        bindings = tuple(self.negotiated_bindings)
        if not all(isinstance(item, NegotiatedBindingReceipt) for item in bindings):
            raise validation_error("invalid_runtime_negotiated_binding")
        if len({item.port_id for item in bindings}) != len(bindings):
            raise validation_error("duplicate_runtime_negotiated_binding")
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_runtime_orchestrator_revision")
        if self.tool_budget_plan is not None and not isinstance(
            self.tool_budget_plan, RuntimeToolBudgetPlan
        ):
            raise validation_error("invalid_runtime_tool_budget_plan")
        if (
            self.tool_budget_plan is not None
            and self.tool_budget_plan.reservation.tool_steps
            < self.runtime_policy.capability_maximum_attempts
        ):
            raise validation_error("runtime_tool_attempt_budget_mismatch")
        if not isinstance(
            self.terminal_commit_grace, timedelta
        ) or self.terminal_commit_grace <= timedelta(0):
            raise validation_error("invalid_runtime_terminal_commit_grace")
        object.__setattr__(self, "negotiated_bindings", bindings)


class OfflineRuntimeOrchestrator:
    def __init__(
        self,
        config: OfflineRuntimeOrchestratorConfig,
        *,
        store: RuntimeStateStore,
        context_builder: CurrentMessageContextBuilder,
        authorization_policy: AuthorizationPolicy,
        authorization_verifier: AuthorizationDecisionVerifier,
        perception: RuntimePerceptionEngine,
        complexity: TaskComplexityAssessor,
        social: SocialDecisionEngine,
        tier_policy: ModelTierPolicy,
        direct_chat: DirectChatModelCall,
        composer: OfflineResponseComposer,
        renderer: OfflinePersonaRenderer,
        final_validator: OfflineFinalResponseValidator,
        delivery_builder: DeliveryRequestBuilder,
        response_profile_policy: ResponseProfilePolicy | None = None,
        detail_detector_revision: ComponentRevision | None = None,
        persona_registry: PersonaRegistry | None = None,
        capability_runtime: BoundedCapabilityRuntime | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, OfflineRuntimeOrchestratorConfig):
            raise TypeError("invalid Offline Runtime Orchestrator config")
        if not isinstance(store, RuntimeStateStore):
            raise TypeError("store does not implement RuntimeStateStore")
        if not isinstance(context_builder, CurrentMessageContextBuilder):
            raise TypeError("invalid Current Message Context Builder")
        if not isinstance(authorization_policy, AuthorizationPolicy):
            raise TypeError("authorization policy does not implement its port")
        if not callable(getattr(authorization_verifier, "verify", None)):
            raise TypeError("authorization verifier does not implement verify")
        if not isinstance(perception, RuntimePerceptionEngine):
            raise TypeError("perception does not implement RuntimePerceptionEngine")
        if not isinstance(complexity, TaskComplexityAssessor):
            raise TypeError("complexity assessor does not implement its port")
        if not isinstance(social, SocialDecisionEngine):
            raise TypeError("social decision does not implement its port")
        if not isinstance(tier_policy, ModelTierPolicy):
            raise TypeError("tier policy does not implement its port")
        for value, expected, name in (
            (direct_chat, DirectChatModelCall, "Direct Chat model call"),
            (composer, OfflineResponseComposer, "Response Composer"),
            (renderer, OfflinePersonaRenderer, "Persona Renderer"),
            (
                final_validator,
                OfflineFinalResponseValidator,
                "Final Response Validator",
            ),
            (delivery_builder, DeliveryRequestBuilder, "Delivery Request Builder"),
        ):
            if not isinstance(value, expected):
                raise TypeError(f"invalid {name}")
        if delivery_builder.config.adapter_binding not in config.negotiated_bindings:
            raise ValueError("delivery binding is not negotiated by Runtime")
        profile_components = (
            response_profile_policy,
            detail_detector_revision,
            persona_registry,
        )
        if any(value is None for value in profile_components) and any(
            value is not None for value in profile_components
        ):
            raise TypeError("incomplete Response Profile Runtime configuration")
        if response_profile_policy is not None and not isinstance(
            response_profile_policy, ResponseProfilePolicy
        ):
            raise TypeError("response profile policy does not implement its port")
        if detail_detector_revision is not None and not isinstance(
            detail_detector_revision, ComponentRevision
        ):
            raise TypeError("invalid detail detector revision")
        if persona_registry is not None and not isinstance(
            persona_registry, PersonaRegistry
        ):
            raise TypeError("persona registry does not implement its port")
        if capability_runtime is not None and not isinstance(
            capability_runtime, BoundedCapabilityRuntime
        ):
            raise TypeError("capability runtime does not implement its port")
        self._config = config
        self._store = store
        self._context_builder = context_builder
        self._authorization_policy = authorization_policy
        self._authorization_verifier = authorization_verifier
        self._perception = perception
        self._complexity = complexity
        self._social = social
        self._tier_policy = tier_policy
        self._direct_chat = direct_chat
        self._composer = composer
        self._renderer = renderer
        self._final_validator = final_validator
        self._delivery_builder = delivery_builder
        self._response_profile_policy = response_profile_policy
        self._detail_detector_revision = detail_detector_revision
        self._persona_registry = persona_registry
        self._capability_runtime = capability_runtime
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    @property
    def config(self) -> OfflineRuntimeOrchestratorConfig:
        return self._config

    async def run(
        self,
        request: RuntimeStartRequest,
        *,
        call: PortCallContext,
    ) -> RuntimeResult:
        now = self._now()
        self._validate_start(request, call, now)
        initial = self._initial_state(request, call)
        committed = await self._store.commit(
            RuntimeCommitRequest(
                schema_version=1,
                run_id=initial.run_id,
                message_dedup_key=initial.message.dedup_key,
                expected_revision=None,
                next_state=initial,
            ),
            call=call,
        )
        checkpoint = committed.checkpoint
        if checkpoint is None:
            raise _conflict("runtime_duplicate_checkpoint_unavailable")
        self._validate_duplicate_roots(initial, checkpoint.state)
        if committed.disposition is RuntimeCommitDisposition.DUPLICATE:
            return await self._wait_for_result(checkpoint, call)
        return await self._run_owner(checkpoint, call)

    async def acknowledge_delivery(
        self,
        receipt: DeliveryReceipt,
        *,
        call: PortCallContext,
    ) -> CompletionReceipt:
        if not isinstance(receipt, DeliveryReceipt):
            raise validation_error("invalid_delivery_acknowledgement_receipt")
        while True:
            self._validate_bound_call(call, receipt.run_id, self._now())
            checkpoint = await self._load_required(receipt.run_id, call)
            self._validate_call_policy(checkpoint.state, call)
            states = delivery_acknowledgement_states(
                checkpoint.state,
                receipt,
                completed_at=self._now(),
            )
            if len(states) == 1 and states[0] is checkpoint.state:
                completion = checkpoint.state.completion
                if completion is None:
                    raise validation_error("delivery_replay_missing_completion")
                return completion
            try:
                for state in states:
                    checkpoint = await self._commit_state(checkpoint, state, call)
            except DududaError as failure:
                if failure.info.code == "runtime_store_cas_conflict":
                    continue
                raise
            completion = checkpoint.state.completion
            if completion is None:
                raise validation_error("delivery_acknowledgement_missing_completion")
            return completion

    async def reconcile_delivery(
        self,
        receipt: DeliveryReceipt,
        *,
        call: PortCallContext,
    ) -> DeliveryReconciliationReceipt:
        if not isinstance(receipt, DeliveryReceipt):
            raise validation_error("invalid_delivery_reconciliation_receipt")
        while True:
            self._validate_bound_call(call, receipt.run_id, self._now())
            checkpoint = await self._load_required(receipt.run_id, call)
            self._validate_call_policy(checkpoint.state, call)
            updated, reconciliation = reconcile_completed_delivery(
                checkpoint.state,
                receipt,
                now=self._now(),
            )
            if updated != checkpoint.state:
                try:
                    await self._commit_state(checkpoint, updated, call)
                except DududaError as failure:
                    if failure.info.code == "runtime_store_cas_conflict":
                        continue
                    raise
            return reconciliation

    async def _run_owner(
        self,
        checkpoint: RuntimeCheckpoint,
        call: PortCallContext,
    ) -> RuntimeResult:
        try:
            state = checkpoint.state
            preprocess = self._context_builder.preprocess(state.message, state.actor)
            checkpoint = await self._commit_transition(
                checkpoint,
                RuntimePhase.PREPROCESSED,
                call,
                preprocess_result=preprocess,
            )
            if preprocess.action is RuntimeAdmissionAction.IGNORE:
                return await self._complete_no_reply(
                    checkpoint,
                    preprocess.reason_codes,
                    call,
                )
            if preprocess.action is RuntimeAdmissionAction.DEFER:
                return await self._complete_terminal(
                    checkpoint,
                    RuntimePhase.DEFERRED,
                    Outcome.DEFERRED,
                    preprocess.reason_codes,
                    call,
                )

            state = checkpoint.state
            context = self._context_builder.build(
                state.message,
                state.actor,
                state.conversation_scope,
                preprocess,
            )
            authorization_request = build_response_authorization_request(
                state.actor,
                state.conversation_scope,
                policy_snapshot_id=state.policy_snapshot_id,
            )
            response_authorization = await self._authorization_policy.decide(
                authorization_request,
                call=self._call_with_budget(call, state.budget),
            )
            if not self._authorization_verifier.verify(
                response_authorization,
                at=self._now(),
            ):
                raise error(
                    "runtime_response_authorization_unissued",
                    ErrorCategory.AUTHORIZATION,
                    "security.denied",
                )
            checkpoint = await self._commit_transition(
                checkpoint,
                RuntimePhase.CONTEXT_READY,
                call,
                current_context=context,
                response_authorization_request=authorization_request,
                response_authorization=response_authorization,
            )

            perception_call = self._call_with_budget(
                call,
                reservation_budget(
                    self._config.model_budget_plan.perception_reservation
                ),
            )
            perception = await self._perception.perceive_with_receipt(
                context.perception,
                call=perception_call,
            )
            perception_charge = (
                self._config.model_budget_plan.perception_reservation
                if perception.model_call_started
                else zero_usage_for_budget(checkpoint.state.initial_budget)
            )
            assessment = self._complexity.assess(context.perception, perception.result)
            checkpoint = await self._commit_transition(
                checkpoint,
                RuntimePhase.PERCEIVED,
                call,
                perception_execution=perception,
                complexity_assessment=assessment,
                complexity_source_digest=perception.result_digest,
                charged_usage=perception_charge,
                budget=charge_budget(
                    checkpoint.state.initial_budget,
                    perception_charge,
                ),
            )

            state = checkpoint.state
            known_target = bool(perception.result.target_identity_refs)
            if known_target:
                for identity_ref in perception.result.target_identity_refs:
                    context.resolve(identity_ref)
            tools_enabled = state.invocation_options.feature_flags.get("tools", False)
            capability_request = None
            capability_authorization_request = None
            capability_authorization = None
            if (
                perception.result.need_tools
                and tools_enabled
                and self._capability_runtime is not None
                and self._config.tool_budget_plan is not None
            ):
                capability_request = project_capability_run_request(
                    context,
                    perception.result,
                    state.actor,
                    state.conversation_scope,
                    available_input_schemas=(
                        self._config.runtime_policy.capability_input_schemas
                    ),
                    maximum_attempts=(
                        self._config.runtime_policy.capability_maximum_attempts
                    ),
                )
                capability_authorization_request = (
                    build_capability_plan_authorization_request(
                        state.actor,
                        state.conversation_scope,
                        run_id=state.run_id,
                        policy_snapshot_id=state.policy_snapshot_id,
                        query_digest=str(capability_request.query.query_digest),
                    )
                )
                capability_authorization = await self._authorization_policy.decide(
                    capability_authorization_request,
                    call=self._call_with_budget(call, state.budget),
                )
                if not self._authorization_verifier.verify(
                    capability_authorization,
                    at=self._now(),
                ):
                    raise error(
                        "runtime_capability_plan_authorization_unissued",
                        ErrorCategory.AUTHORIZATION,
                        "security.denied",
                    )
            signals = project_s10_decision_signals(
                authorization=response_authorization,
                duplicate_or_self_message=False,
                explicit_interaction=preprocess.explicit_interaction,
                conversation_type=state.message.conversation_type,
                data_classification=preprocess.data_classification,
                group_mode=self._config.runtime_policy.group_mode,
                known_target=known_target,
                tool_authorization=capability_authorization,
                tools_enabled=tools_enabled,
            )
            social = await self._social.decide(
                perception.result,
                signals,
                call=self._call_with_budget(call, state.budget),
            )

            response_profile_request = None
            response_plan = None
            persona_resolution = None
            response_reservation = (
                self._config.model_budget_plan.direct_chat_reservation
            )
            response_profiles_enabled = state.invocation_options.feature_flags.get(
                "response_profiles", False
            )
            visible_action = social.action in {
                SocialAction.DIRECT_REPLY,
                SocialAction.ASK_CLARIFICATION,
            }
            if visible_action:
                persona_resolution = self._resolve_persona(state)
            if response_profiles_enabled and visible_action:
                response_profile_request, response_plan = self._select_response_plan(
                    state,
                    context,
                    assessment,
                    social,
                )
                response_reservation = project_response_reservation(
                    response_reservation,
                    response_plan,
                )
            tier_context = None
            tier = None
            if social.action is SocialAction.DIRECT_REPLY:
                tier_context = project_tier_selection_context(
                    selection_id=self._id("tier-selection"),
                    role=ModelRole.DIRECT_CHAT,
                    assessment=assessment,
                    content_input_tokens_upper_bound=(
                        context.perception.content_input_tokens_upper_bound
                    ),
                    data_classification=context.perception.data_classification,
                    budget=reservation_budget(response_reservation),
                )
                tier = select_model_tier(
                    context=tier_context,
                    definition=self._config.runtime_policy.direct_chat_tier,
                    policy=self._tier_policy,
                    now=self._now(),
                )
            checkpoint = await self._commit_transition(
                checkpoint,
                RuntimePhase.DECIDED,
                call,
                decision_signals=signals,
                social_decision=social,
                response_profile_request=response_profile_request,
                response_plan=response_plan,
                persona_resolution=persona_resolution,
                tier_selection_context=tier_context,
                tier_decision=tier,
                capability_plan_authorization_request=(
                    capability_authorization_request
                ),
                capability_plan_authorization=capability_authorization,
                capability_run_request=capability_request,
            )

            if social.action is SocialAction.IGNORE:
                return await self._complete_no_reply(
                    checkpoint,
                    social.reason_codes,
                    call,
                )
            if social.action is SocialAction.DEFER:
                return await self._complete_terminal(
                    checkpoint,
                    RuntimePhase.DEFERRED,
                    Outcome.DEFERRED,
                    social.reason_codes,
                    call,
                )
            if social.action not in {
                SocialAction.DIRECT_REPLY,
                SocialAction.ASK_CLARIFICATION,
                SocialAction.USE_TOOLS,
            }:
                raise validation_error("s10_social_action_out_of_scope")

            capability_receipt = None
            if social.action is SocialAction.USE_TOOLS:
                if (
                    self._capability_runtime is None
                    or capability_request is None
                    or capability_authorization is None
                    or capability_authorization.effect is not AuthorizationEffect.ALLOW
                ):
                    raise validation_error(
                        "runtime_capability_execution_not_authorized"
                    )
                if not self._authorization_verifier.verify(
                    capability_authorization,
                    at=self._now(),
                ):
                    raise error(
                        "runtime_capability_plan_authorization_expired",
                        ErrorCategory.AUTHORIZATION,
                        "security.denied",
                    )
                if checkpoint.state.tool_budget_plan is None:
                    raise validation_error("runtime_tool_budget_plan_missing")
                tool_budget = reservation_budget(
                    checkpoint.state.tool_budget_plan.reservation
                )
                try:
                    capability_receipt = await self._run_capability(
                        capability_request,
                        call=self._call_with_budget(call, tool_budget),
                    )
                    self._validate_capability_receipt(
                        capability_receipt,
                        capability_request,
                        run_id=checkpoint.state.run_id,
                    )
                except asyncio.CancelledError:
                    raise
                except DududaError as failure:
                    conservative_charge = add_usage(
                        checkpoint.state.charged_usage,
                        checkpoint.state.tool_budget_plan.reservation,
                    )
                    conservative_budget = charge_budget(
                        checkpoint.state.initial_budget,
                        conservative_charge,
                    )
                    return await self._complete_terminal(
                        checkpoint,
                        RuntimePhase.FAILED,
                        Outcome.FAILED,
                        (failure.info.code,),
                        self._commit_call(call, conservative_budget),
                        capability_unverified_usage=(
                            checkpoint.state.tool_budget_plan.reservation
                        ),
                        charged_usage=conservative_charge,
                        budget=conservative_budget,
                    )
                pre_tool_charge = checkpoint.state.charged_usage
                if (
                    capability_receipt.retrieval is not None
                    and capability_receipt.plan is not None
                ):
                    checkpoint = await self._commit_transition(
                        checkpoint,
                        RuntimePhase.TOOLS_PLANNED,
                        self._commit_call(call, checkpoint.state.budget),
                        capability_retrieval=capability_receipt.retrieval,
                        tool_plan=capability_receipt.plan,
                    )
                if (
                    capability_receipt.observations
                    or capability_receipt.unobserved_attempts
                ):
                    if checkpoint.state.phase is not RuntimePhase.TOOLS_PLANNED:
                        raise validation_error(
                            "runtime_capability_observation_without_plan"
                        )
                    observation_usage = _attempt_usage(
                        checkpoint.state.initial_budget,
                        capability_receipt.observations,
                        capability_receipt.unobserved_attempts,
                    )
                    observed_charge = add_usage(pre_tool_charge, observation_usage)
                    observed_budget = charge_budget(
                        checkpoint.state.initial_budget,
                        observed_charge,
                    )
                    checkpoint = await self._commit_transition(
                        checkpoint,
                        RuntimePhase.TOOLS_EXECUTED,
                        self._commit_call(call, observed_budget),
                        tool_observations=capability_receipt.observations,
                        tool_unobserved_attempts=(
                            capability_receipt.unobserved_attempts
                        ),
                        charged_usage=observed_charge,
                        budget=observed_budget,
                    )

                tool_charge = add_usage(pre_tool_charge, capability_receipt.usage)
                budget_after_tools = charge_budget(
                    checkpoint.state.initial_budget,
                    tool_charge,
                )
                if capability_receipt.status is not CapabilityRunStatus.COMPLETED:
                    terminal_phase = (
                        RuntimePhase.DEFERRED
                        if capability_receipt.status is CapabilityRunStatus.DEFERRED
                        else RuntimePhase.FAILED
                    )
                    terminal_outcome = (
                        Outcome.DEFERRED
                        if terminal_phase is RuntimePhase.DEFERRED
                        else Outcome.FAILED
                    )
                    return await self._complete_terminal(
                        checkpoint,
                        terminal_phase,
                        terminal_outcome,
                        capability_receipt.reason_codes,
                        self._commit_call(call, budget_after_tools),
                        capability_retrieval=capability_receipt.retrieval,
                        tool_plan=capability_receipt.plan,
                        tool_observations=capability_receipt.observations,
                        tool_unobserved_attempts=(
                            capability_receipt.unobserved_attempts
                        ),
                        tool_validation=capability_receipt.validation,
                        capability_run_receipt=capability_receipt,
                        charged_usage=tool_charge,
                        budget=budget_after_tools,
                    )
                if checkpoint.state.phase is not RuntimePhase.TOOLS_EXECUTED:
                    raise validation_error(
                        "runtime_completed_capability_has_no_execution"
                    )
                if capability_receipt.validation is None:
                    raise validation_error(
                        "runtime_completed_capability_has_no_validation"
                    )
                response_profile_request = None
                response_plan = None
                persona_resolution = None
                response_reservation = (
                    self._config.model_budget_plan.direct_chat_reservation
                )
                persona_resolution = self._resolve_persona(checkpoint.state)
                if response_profiles_enabled:
                    (
                        response_profile_request,
                        response_plan,
                    ) = self._select_response_plan(
                        checkpoint.state,
                        context,
                        assessment,
                        social,
                    )
                    response_reservation = project_response_reservation(
                        response_reservation,
                        response_plan,
                    )
                tier_context = project_tier_selection_context(
                    selection_id=self._id("tier-selection"),
                    role=ModelRole.DIRECT_CHAT,
                    assessment=assessment,
                    content_input_tokens_upper_bound=(
                        context.perception.content_input_tokens_upper_bound
                        + tool_context_tokens_upper_bound(capability_receipt)
                    ),
                    data_classification=tool_context_privacy_level(
                        capability_receipt,
                        context.perception.data_classification,
                    ),
                    budget=reservation_budget(response_reservation),
                )
                tier = select_model_tier(
                    context=tier_context,
                    definition=self._config.runtime_policy.direct_chat_tier,
                    policy=self._tier_policy,
                    now=self._now(),
                )
                checkpoint = await self._commit_transition(
                    checkpoint,
                    RuntimePhase.VALIDATED,
                    self._commit_call(call, budget_after_tools),
                    tool_validation=capability_receipt.validation,
                    capability_run_receipt=capability_receipt,
                    response_profile_request=response_profile_request,
                    response_plan=response_plan,
                    persona_resolution=persona_resolution,
                    tier_selection_context=tier_context,
                    tier_decision=tier,
                    charged_usage=tool_charge,
                    budget=budget_after_tools,
                )

            response_plan = checkpoint.state.response_plan
            persona_resolution = checkpoint.state.persona_resolution
            response_reservation = (
                self._config.model_budget_plan.direct_chat_reservation
            )
            if response_plan is not None:
                response_reservation = project_response_reservation(
                    response_reservation,
                    response_plan,
                )
            elif response_profiles_enabled:
                raise validation_error("runtime_visible_response_plan_missing")
            if persona_resolution is None:
                raise validation_error("runtime_visible_persona_resolution_missing")

            direct = None
            direct_route = None
            charged_usage = checkpoint.state.charged_usage
            budget = checkpoint.state.budget
            if social.action in {SocialAction.DIRECT_REPLY, SocialAction.USE_TOOLS}:
                if tier is None:
                    raise validation_error("direct_reply_missing_tier_decision")
                try:
                    direct = await self._direct_chat.execute(
                        context,
                        assessment,
                        tier,
                        response_reservation,
                        response_plan=response_plan,
                        persona_resolution=persona_resolution,
                        route_hint=checkpoint.state.invocation_options.route_hint,
                        capability_receipt=capability_receipt,
                        call=self._call_with_budget(
                            call,
                            reservation_budget(response_reservation),
                        ),
                    )
                except RuntimeDirectChatFailure as failure:
                    failure_charge = add_usage(
                        checkpoint.state.charged_usage,
                        failure.receipt.charged_usage,
                    )
                    return await self._complete_terminal(
                        checkpoint,
                        RuntimePhase.FAILED,
                        Outcome.FAILED,
                        (failure.info.code,),
                        self._commit_call(call, checkpoint.state.budget),
                        direct_route_decision=failure.receipt.route_decision,
                        direct_chat_failure=failure.receipt,
                        charged_usage=failure_charge,
                        budget=charge_budget(
                            checkpoint.state.initial_budget,
                            failure_charge,
                        ),
                    )
                direct_route = direct.route_decision
                charged_usage = add_usage(
                    charged_usage,
                    response_reservation,
                )
                budget = charge_budget(
                    checkpoint.state.initial_budget,
                    charged_usage,
                )
            draft = self._composer.compose(
                context,
                social,
                direct.content if direct is not None else None,
                response_plan,
            )
            checkpoint = await self._commit_transition(
                checkpoint,
                RuntimePhase.COMPOSED,
                call,
                direct_route_decision=direct_route,
                direct_chat_execution=direct,
                draft_response=draft,
                charged_usage=charged_usage,
                budget=budget,
            )

            rendered = self._renderer.render(
                draft,
                response_plan,
                persona_resolution=persona_resolution,
            )
            final = await self._final_validator.validate(
                draft,
                rendered,
                checkpoint.state.actor,
                checkpoint.state.conversation_scope,
                response_plan=response_plan,
                persona_resolution=persona_resolution,
                call=self._call_with_budget(call, checkpoint.state.budget),
            )
            checkpoint = await self._commit_transition(
                checkpoint,
                RuntimePhase.RENDERED,
                call,
                final_response=final,
            )

            delivery_plan = self._delivery_builder.plan(
                run_id=checkpoint.state.run_id,
                response=final,
                actor=checkpoint.state.actor,
                scope=checkpoint.state.conversation_scope,
                reply_to=context.current_message_reference,
                policy_snapshot_id=checkpoint.state.policy_snapshot_id,
            )
            if response_plan is not None and (
                len(delivery_plan.intent.part_intents)
                > response_plan.delivery_part_limit
            ):
                raise validation_error("response_delivery_part_limit_exceeded")
            send_authorization = await self._authorization_policy.decide(
                delivery_plan.authorization_request,
                call=self._call_with_budget(call, checkpoint.state.budget),
            )
            delivery = self._delivery_builder.finalize(
                delivery_plan,
                send_authorization,
            )
            result = RuntimeResult(
                schema_version=1,
                run_id=checkpoint.state.run_id,
                outcome=Outcome.RESPONSE,
                final_response=final,
                reaction=None,
                delivery_request=delivery,
                completion=None,
                reason_codes=tuple(
                    sorted(set(social.reason_codes) | {"delivery_ready"})
                ),
                trace_summary=self._trace_summary(
                    checkpoint.state,
                    RuntimePhase.READY_TO_EMIT,
                    social.reason_codes,
                ),
                selection_summary=RuntimeSelectionSummary(
                    schema_version=1,
                    selected_tier=tier.selected_tier,
                    tier_decision_digest=tier_decision_digest(tier),
                    route_decision_digest=route_decision_digest(direct_route),
                )
                if tier is not None and direct_route is not None
                else None,
            )
            checkpoint = await self._commit_transition(
                checkpoint,
                RuntimePhase.READY_TO_EMIT,
                call,
                delivery_request=delivery,
                pending_result=result,
            )
            if checkpoint.state.pending_result is None:
                raise validation_error("runtime_ready_result_missing")
            return checkpoint.state.pending_result
        except DududaError as failure:
            if failure.info.category is ErrorCategory.CONFLICT:
                raise
            return await self._complete_terminal(
                checkpoint,
                RuntimePhase.FAILED,
                Outcome.FAILED,
                (failure.info.code,),
                self._commit_call(call, checkpoint.state.budget),
            )

    async def _complete_no_reply(
        self,
        checkpoint: RuntimeCheckpoint,
        reason_codes: tuple[str, ...],
        call: PortCallContext,
    ) -> RuntimeResult:
        checkpoint = await self._commit_transition(
            checkpoint,
            RuntimePhase.MEMORY_EVALUATED,
            call,
        )
        completion = CompletionReceipt(
            schema_version=1,
            run_id=checkpoint.state.run_id,
            final_phase=RuntimePhase.COMPLETED,
            delivery_status=DeliveryStatus.NOT_REQUIRED,
            completed_at=self._now(),
        )
        result = RuntimeResult(
            schema_version=1,
            run_id=checkpoint.state.run_id,
            outcome=Outcome.NO_REPLY,
            final_response=None,
            reaction=None,
            delivery_request=None,
            completion=completion,
            reason_codes=reason_codes,
            trace_summary=self._trace_summary(
                checkpoint.state,
                RuntimePhase.COMPLETED,
                reason_codes,
            ),
        )
        checkpoint = await self._commit_transition(
            checkpoint,
            RuntimePhase.COMPLETED,
            call,
            completion=completion,
            pending_result=result,
        )
        if checkpoint.state.pending_result is None:
            raise validation_error("runtime_completion_result_missing")
        return checkpoint.state.pending_result

    async def _complete_terminal(
        self,
        checkpoint: RuntimeCheckpoint,
        phase: RuntimePhase,
        outcome: Outcome,
        reason_codes: tuple[str, ...],
        call: PortCallContext,
        **state_changes: object,
    ) -> RuntimeResult:
        completion = CompletionReceipt(
            schema_version=1,
            run_id=checkpoint.state.run_id,
            final_phase=phase,
            delivery_status=DeliveryStatus.NOT_REQUIRED,
            completed_at=self._now(),
        )
        result = RuntimeResult(
            schema_version=1,
            run_id=checkpoint.state.run_id,
            outcome=outcome,
            final_response=None,
            reaction=None,
            delivery_request=None,
            completion=completion,
            reason_codes=reason_codes,
            trace_summary=self._trace_summary(
                checkpoint.state,
                phase,
                reason_codes,
            ),
        )
        checkpoint = await self._commit_transition(
            checkpoint,
            phase,
            call,
            completion=completion,
            pending_result=result,
            **state_changes,
        )
        if checkpoint.state.pending_result is None:
            raise validation_error("runtime_terminal_result_missing")
        return checkpoint.state.pending_result

    async def _wait_for_result(
        self,
        checkpoint: RuntimeCheckpoint,
        call: PortCallContext,
    ) -> RuntimeResult:
        while True:
            result = checkpoint.state.pending_result
            if result is not None and checkpoint.state.phase in {
                RuntimePhase.READY_TO_EMIT,
                RuntimePhase.COMPLETED,
                RuntimePhase.DEFERRED,
                RuntimePhase.FAILED,
            }:
                return result
            next_checkpoint = await self._store.wait_for_revision(
                checkpoint.state.run_id,
                checkpoint.revision,
                call=call,
            )
            if next_checkpoint is None:
                raise _conflict("runtime_duplicate_checkpoint_expired")
            checkpoint = next_checkpoint

    async def _commit_transition(
        self,
        checkpoint: RuntimeCheckpoint,
        phase: RuntimePhase,
        call: PortCallContext,
        **changes: object,
    ) -> RuntimeCheckpoint:
        pending_result = changes.get("pending_result")
        trace_reason_codes = (
            pending_result.reason_codes
            if isinstance(pending_result, RuntimeResult)
            else ()
        )
        return await self._commit_state(
            checkpoint,
            transition(
                checkpoint.state,
                phase,
                occurred_at=self._now(),
                trace_reason_codes=trace_reason_codes,
                **changes,
            ),
            call,
        )

    async def _commit_state(
        self,
        checkpoint: RuntimeCheckpoint,
        state: RuntimeState,
        call: PortCallContext,
    ) -> RuntimeCheckpoint:
        committed = await self._store.commit(
            RuntimeCommitRequest(
                schema_version=1,
                run_id=state.run_id,
                message_dedup_key=state.message.dedup_key,
                expected_revision=checkpoint.revision,
                next_state=state,
            ),
            call=call,
        )
        if committed.checkpoint is None or committed.checkpoint.state != state:
            raise _conflict("runtime_commit_state_mismatch")
        return committed.checkpoint

    async def _load_required(
        self,
        run_id: str,
        call: PortCallContext,
    ) -> RuntimeCheckpoint:
        checkpoint = await self._store.load(run_id, call=call)
        if checkpoint is None:
            raise _not_found("runtime_checkpoint_not_found")
        return checkpoint

    async def _run_capability(
        self,
        request: CapabilityRunRequest,
        *,
        call: PortCallContext,
    ) -> CapabilityRunReceipt:
        runtime = self._capability_runtime
        if runtime is None:
            raise validation_error("runtime_capability_runtime_missing")
        try:
            receipt = await runtime.run(request, call=call)
        except asyncio.CancelledError:
            raise
        except DududaError:
            raise
        except Exception:  # noqa: BLE001 - capability internals remain private.
            raise error(
                "runtime_capability_runtime_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if not isinstance(receipt, CapabilityRunReceipt):
            raise validation_error("invalid_runtime_capability_receipt")
        return receipt

    def _validate_capability_receipt(
        self,
        receipt: CapabilityRunReceipt,
        request: CapabilityRunRequest,
        *,
        run_id: str,
    ) -> None:
        if (
            receipt.run_id != run_id
            or receipt.request != request
            or receipt.request_digest != request.request_digest
            or request.request_digest != capability_run_request_digest(request)
            or receipt.receipt_digest != capability_run_receipt_digest(receipt)
        ):
            raise validation_error("runtime_capability_receipt_binding_mismatch")
        tool_budget_plan = self._config.tool_budget_plan
        if tool_budget_plan is None or not usage_within_tool_reservation(
            receipt.usage,
            tool_budget_plan.reservation,
        ):
            raise validation_error("runtime_capability_usage_exceeds_reservation")

    def _initial_state(
        self,
        request: RuntimeStartRequest,
        call: PortCallContext,
    ) -> RuntimeState:
        connector = request.connector_result
        message = connector.message
        state = RuntimeState(
            schema_version=1,
            run_id=call.run_id,
            phase=RuntimePhase.RECEIVED,
            message=message,
            actor=connector.actor,
            received_at=connector.received_at,
            connector_revision=connector.adapter_revision,
            invocation_options=request.options,
            start_digest=request.start_digest,
            conversation_scope=ConversationScope(
                platform=message.platform,
                bot_id=message.bot_id,
                conversation_type=message.conversation_type,
                conversation_id=message.conversation_id,
                group_id=message.group_id,
                persona_id=self._config.persona_id,
            ),
            initial_budget=call.budget,
            model_budget_plan=self._config.model_budget_plan,
            budget=call.budget,
            charged_usage=zero_usage_for_budget(call.budget),
            trace_context=call.trace,
            policy_snapshot_id=call.policy_snapshot_id,
            runtime_policy=self._config.runtime_policy,
            negotiated_bindings=self._config.negotiated_bindings,
            tool_budget_plan=(
                self._config.tool_budget_plan
                if request.options.feature_flags.get("tools", False)
                and self._capability_runtime is not None
                else None
            ),
        )
        return replace(
            state,
            trace=append_runtime_phase_trace(
                state,
                RuntimePhase.RECEIVED,
                connector.received_at,
            ),
        )

    def _select_response_plan(
        self,
        state: RuntimeState,
        context: CurrentMessageContext,
        assessment: TaskComplexityAssessment,
        social: SocialDecision,
    ) -> tuple[ResponseProfileSelectionRequest, ResponsePlan]:
        if (
            self._response_profile_policy is None
            or self._detail_detector_revision is None
        ):
            raise validation_error("response_profile_runtime_unavailable")
        current = next(
            message
            for message in context.perception.messages
            if message.message_ref == context.perception.current_message_ref
        )
        maximum_characters = self._direct_chat.config.maximum_response_characters
        if social.response_constraints.max_characters is not None:
            maximum_characters = min(
                maximum_characters,
                social.response_constraints.max_characters,
            )
        request = ResponseProfileSelectionRequest(
            schema_version=1,
            selection_id=self._id("response-profile-selection"),
            actor_digest=actor_digest(state.actor),
            scope_digest=scope_digest(state.conversation_scope),
            persona_id=state.conversation_scope.persona_id,
            conversation_type=state.conversation_scope.conversation_type,
            current_message_ref=context.perception.current_message_ref,
            complexity_level=assessment.level,
            reasoning_depth=assessment.reasoning_depth,
            expected_tool_steps=assessment.expected_tool_steps,
            verification_required=assessment.verification_required,
            social_action=social.action,
            assessment_digest=task_complexity_assessment_digest(assessment),
            social_decision_digest=social_decision_digest(social),
            detail_evidence=detect_detail_preference(
                context.perception.current_message_ref,
                current.text,
                detector_revision=self._detail_detector_revision,
            ),
            persistent_preference=None,
            available_generated_tokens=(
                state.model_budget_plan.direct_chat_reservation.output_tokens
            ),
            maximum_response_characters=maximum_characters,
            maximum_delivery_parts=(
                self._delivery_builder.config.constraints.max_parts
            ),
        )
        plan = self._response_profile_policy.select(request, now=self._now())
        if not isinstance(plan, ResponsePlan):
            raise validation_error("invalid_response_profile_policy_result")
        return request, plan

    def _resolve_persona(self, state: RuntimeState) -> PersonaResolution:
        registry = self._persona_registry
        if registry is None:
            raise validation_error("persona_registry_unavailable")
        snapshot = registry.acquire_snapshot()
        if not isinstance(snapshot, PersonaCatalogSnapshot):
            raise validation_error("invalid_persona_catalog_snapshot")
        requested_id = state.conversation_scope.persona_id
        resolution = registry.resolve(snapshot, requested_id, None)
        return validate_persona_resolution(
            snapshot,
            resolution,
            requested_persona_id=requested_id,
            requested_version=None,
        )

    def _validate_start(
        self,
        request: RuntimeStartRequest,
        call: PortCallContext,
        now: datetime,
    ) -> None:
        if not isinstance(request, RuntimeStartRequest):
            raise validation_error("invalid_runtime_start_request")
        if not isinstance(call, PortCallContext):
            raise validation_error("invalid_runtime_call")
        self._validate_bound_call(call, call.run_id, now)
        if call.policy_snapshot_id != self._config.runtime_policy.snapshot_id:
            raise validation_error("runtime_call_policy_snapshot_mismatch")
        if request.start_digest != runtime_start_digest(
            request.connector_result,
            request.options,
        ):
            raise validation_error("runtime_start_digest_mismatch")

    def _validate_bound_call(
        self,
        call: PortCallContext,
        run_id: str,
        now: datetime,
    ) -> None:
        if not isinstance(call, PortCallContext):
            raise validation_error("invalid_runtime_call")
        if call.run_id != run_id:
            raise validation_error("runtime_call_run_mismatch")
        if call.cancellation.is_cancelled:
            raise error(
                "runtime_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if call.deadline <= now:
            raise error(
                "runtime_deadline_exceeded",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )

    def _validate_call_policy(
        self,
        state: RuntimeState,
        call: PortCallContext,
    ) -> None:
        if call.policy_snapshot_id != state.policy_snapshot_id:
            raise validation_error("runtime_call_policy_snapshot_mismatch")

    def _validate_duplicate_roots(
        self,
        expected: RuntimeState,
        actual: RuntimeState,
    ) -> None:
        fields = (
            "run_id",
            "message",
            "actor",
            "received_at",
            "connector_revision",
            "invocation_options",
            "start_digest",
            "conversation_scope",
            "initial_budget",
            "model_budget_plan",
            "trace_context",
            "policy_snapshot_id",
            "runtime_policy",
            "negotiated_bindings",
            "tool_budget_plan",
        )
        if any(getattr(expected, name) != getattr(actual, name) for name in fields):
            raise _conflict("runtime_duplicate_root_mismatch")

    def _call_with_budget(
        self,
        call: PortCallContext,
        budget,
    ) -> PortCallContext:
        return PortCallContext(
            run_id=call.run_id,
            trace=call.trace,
            deadline=call.deadline,
            cancellation=call.cancellation,
            budget=budget,
            policy_snapshot_id=call.policy_snapshot_id,
        )

    def _commit_call(self, call: PortCallContext, budget) -> PortCallContext:
        now = self._now()
        if not call.cancellation.is_cancelled and call.deadline > now:
            return self._call_with_budget(call, budget)
        return PortCallContext(
            run_id=call.run_id,
            trace=call.trace,
            deadline=now + self._config.terminal_commit_grace,
            cancellation=NeverCancelled(),
            budget=budget,
            policy_snapshot_id=call.policy_snapshot_id,
        )

    def _trace_summary(
        self,
        state: RuntimeState,
        phase: RuntimePhase,
        reason_codes: tuple[str, ...],
    ) -> TraceSummary:
        phases = tuple(event.phase for event in state.trace)
        if not phases or phases[-1] is not phase:
            phases = (*phases, phase)
        return TraceSummary(
            schema_version=1,
            trace_id=state.trace_context.trace_id,
            phases=phases,
            degraded_components=(
                state.current_context.perception.degraded_components
                if state.current_context is not None
                else ()
            ),
            reason_codes=reason_codes,
        )

    def _id(self, prefix: str) -> str:
        return f"{prefix}:{self._id_factory()}"

    def _now(self) -> datetime:
        now = self._clock()
        require_aware(now, "runtime_orchestrator_clock")
        return now


def _conflict(code: str) -> DududaError:
    return error(code, ErrorCategory.CONFLICT, "request.conflict")


def _not_found(code: str) -> DududaError:
    return error(code, ErrorCategory.NOT_FOUND, "request.not_found")


def _attempt_usage(
    budget,
    observations: tuple[ToolObservation, ...],
    unobserved_attempts,
):
    usage = zero_usage_for_budget(budget)
    for attempt in (*observations, *unobserved_attempts):
        usage = add_usage(usage, attempt.usage)
    return usage
