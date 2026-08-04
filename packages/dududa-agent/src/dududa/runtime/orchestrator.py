from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid

from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.domain.delivery import DeliveryReceipt, DeliveryStatus
from dududa.domain.identity import ConversationScope
from dududa.domain.primitives import (
    ComponentRevision,
    Outcome,
    require_aware,
    require_non_empty,
)
from dududa.errors import DududaError, ErrorCategory, error, validation_error
from dududa.models.contracts import ModelRole
from dududa.models.digests import route_decision_digest, tier_decision_digest
from dududa.perception.contracts import SocialAction
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.ports.models import ModelTierPolicy
from dududa.ports.perception import SocialDecisionEngine, TaskComplexityAssessor
from dududa.ports.runtime import (
    OfflineFinalResponseValidator,
    OfflinePersonaRenderer,
    OfflineResponseComposer,
    RuntimePerceptionEngine,
    RuntimeStateStore,
)
from dududa.security.ports import AuthorizationDecisionVerifier, AuthorizationPolicy

from .authorization import build_response_authorization_request
from .budget import (
    RuntimeModelBudgetPlan,
    add_usage,
    charge_budget,
    reservation_budget,
    zero_usage_for_budget,
)
from .context import CurrentMessageContextBuilder
from .contracts import (
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
            signals = project_s10_decision_signals(
                authorization=response_authorization,
                duplicate_or_self_message=False,
                explicit_interaction=preprocess.explicit_interaction,
                conversation_type=state.message.conversation_type,
                data_classification=preprocess.data_classification,
                group_mode=self._config.runtime_policy.group_mode,
                known_target=known_target,
            )
            social = await self._social.decide(
                perception.result,
                signals,
                call=self._call_with_budget(call, state.budget),
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
                    budget=reservation_budget(
                        self._config.model_budget_plan.direct_chat_reservation
                    ),
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
                tier_selection_context=tier_context,
                tier_decision=tier,
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
            }:
                raise validation_error("s10_social_action_out_of_scope")

            direct = None
            direct_route = None
            charged_usage = checkpoint.state.charged_usage
            budget = checkpoint.state.budget
            if social.action is SocialAction.DIRECT_REPLY:
                if tier is None:
                    raise validation_error("direct_reply_missing_tier_decision")
                try:
                    direct = await self._direct_chat.execute(
                        context,
                        assessment,
                        tier,
                        self._config.model_budget_plan.direct_chat_reservation,
                        route_hint=checkpoint.state.invocation_options.route_hint,
                        call=self._call_with_budget(
                            call,
                            reservation_budget(
                                self._config.model_budget_plan.direct_chat_reservation
                            ),
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
                    self._config.model_budget_plan.direct_chat_reservation,
                )
                budget = charge_budget(
                    checkpoint.state.initial_budget,
                    charged_usage,
                )
            draft = self._composer.compose(
                context,
                social,
                direct.content if direct is not None else None,
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

            rendered = self._renderer.render(draft)
            final = await self._final_validator.validate(
                draft,
                rendered,
                checkpoint.state.actor,
                checkpoint.state.conversation_scope,
                call=self._call_with_budget(call, checkpoint.state.budget),
            )
            checkpoint = await self._commit_transition(
                checkpoint,
                RuntimePhase.RENDERED,
                call,
                final_response=final,
            )

            plan = self._delivery_builder.plan(
                run_id=checkpoint.state.run_id,
                response=final,
                actor=checkpoint.state.actor,
                scope=checkpoint.state.conversation_scope,
                reply_to=context.current_message_reference,
                policy_snapshot_id=checkpoint.state.policy_snapshot_id,
            )
            send_authorization = await self._authorization_policy.decide(
                plan.authorization_request,
                call=self._call_with_budget(call, checkpoint.state.budget),
            )
            delivery = self._delivery_builder.finalize(plan, send_authorization)
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
        return await self._commit_state(
            checkpoint,
            transition(checkpoint.state, phase, **changes),
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

    def _initial_state(
        self,
        request: RuntimeStartRequest,
        call: PortCallContext,
    ) -> RuntimeState:
        connector = request.connector_result
        message = connector.message
        return RuntimeState(
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
        return TraceSummary(
            schema_version=1,
            trace_id=state.trace_context.trace_id,
            phases=(phase,),
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
