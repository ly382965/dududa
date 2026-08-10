from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.domain.delivery import DeliveryConstraints
from dududa.domain.identity import ConversationScope
from dududa.domain.primitives import (
    DigestString,
    Outcome,
    PrivacyLevel,
    ResourceUsage,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    TraceContext,
)
from dududa.domain.task import TaskReasoningDepth
from dududa.errors import DududaError, ErrorCategory, error
from dududa.models.contracts import ModelTier
from dududa.models.tiering import DeterministicModelTierPolicy
from dududa.perception.complexity import DeterministicComplexityAssessor
from dududa.perception.contracts import (
    AmbiguityCandidate,
    AmbiguityKind,
    ClarificationKey,
    PerceptionModelStatus,
)
from dududa.perception.merge import DeterministicPerceptionMerger, PerceptionMergeConfig
from dududa.perception.rules import (
    DeterministicRulePerception,
    default_rule_perception_config,
)
from dududa.perception.social import DeterministicSocialDecisionPolicy
from dududa.perception.validation import validate_perception_result
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
)
from dududa.responses import (
    AnswerProfile,
    DeterministicResponseProfilePolicy,
    UnicodeVisibleTokenCounter,
    pilot_response_profile_policy_config,
    response_plan_digest,
)
from dududa.runtime.budget import RuntimeModelBudgetPlan, RuntimeToolBudgetPlan
from dududa.runtime.composition import (
    DeterministicRenderValidator,
    FinalResponseSafetyValidator,
)
from dududa.runtime.context import (
    CurrentMessageContextBuilder,
    CurrentMessageContextBuilderConfig,
)
from dududa.runtime.contracts import PerceptionExecutionReceipt
from dududa.runtime.delivery import DeliveryRequestBuilder, DeliveryRequestBuilderConfig
from dududa.runtime.direct_chat import DirectChatModelCall
from dududa.runtime.orchestrator import (
    OfflineRuntimeOrchestrator,
    OfflineRuntimeOrchestratorConfig,
)
from dududa.runtime.state import (
    ConnectorResult,
    RuntimeInvocationOptions,
    RuntimePhase,
    RuntimeStartRequest,
    runtime_start_digest,
)
from dududa.runtime.store import (
    InMemoryRuntimeStateStore,
    InMemoryRuntimeStateStoreConfig,
)
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.content_safety import DefaultContentSafetyPolicy
from dududa.testing.models import ProviderSuccess

from tests.unit.models.helpers import NOW
from tests.unit.perception.helpers import limits as perception_limits
from tests.unit.runtime.test_composition import _composer, _renderer
from tests.unit.runtime.test_direct_chat import _config as direct_config
from tests.unit.runtime.test_direct_chat import _fixture as direct_fixture
from tests.unit.runtime.test_perception import _RuntimePerceptionFixture
from tests.unit.runtime.test_s10_context_budget import actor, builder, message

from .helpers import revision, runtime_policy


class _RuleOnlyRuntimePerception:
    def __init__(
        self,
        *,
        model_call_started: bool = False,
        transform=None,
        cancel_on_call: bool = False,
    ) -> None:
        self.calls = 0
        self.model_call_started = model_call_started
        self.transform = transform
        self.cancel_on_call = cancel_on_call
        self._rules = DeterministicRulePerception(
            default_rule_perception_config(revision("rule-perception")),
            id_factory=lambda: "rule-result-1",
        )
        self._merger = DeterministicPerceptionMerger(
            PerceptionMergeConfig(
                pipeline_revision=revision("perception-pipeline"),
                merger_revision=revision("perception-merger"),
                validator_revision=revision("perception-validator"),
                fallback_confidence_ceiling=0.59,
                conflict_confidence_ceiling=0.55,
            ),
            id_factory=lambda: "perception-result-1",
        )

    async def perceive_with_receipt(self, context, *, call):
        self.calls += 1
        if self.cancel_on_call:
            cancel = getattr(call.cancellation, "cancel", None)
            if callable(cancel):
                cancel()
            raise error(
                "perception_cancelled_during_execution",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        await asyncio.sleep(0)
        rules = self._rules.perceive(context)
        result = self._merger.merge(
            context,
            rules,
            None,
            model_status=PerceptionModelStatus.UNAVAILABLE,
        )
        if self.transform is not None:
            result = self.transform(result, context)
        validate_perception_result(context, result)
        return PerceptionExecutionReceipt(
            schema_version=1,
            result=result,
            model_call_started=self.model_call_started,
            request_fingerprint=(
                DigestString("perception-request-fingerprint")
                if self.model_call_started
                else None
            ),
            route_decision=None,
            reported_usage=None,
            model_status=PerceptionModelStatus.UNAVAILABLE,
            failure_code="model_unavailable",
        )


class _CountingRouter:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0
        self.requests = []

    async def invoke(self, request, tier_authority, *, call):
        self.calls += 1
        self.requests.append(request)
        await asyncio.sleep(0)
        return await self._inner.invoke(request, tier_authority, call=call)


class _RejectingAuthorizationVerifier:
    def verify(self, decision, *, at=None) -> bool:
        return False


class _MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self):
        return self.now


class _RecordingRuntimeStateStore(InMemoryRuntimeStateStore):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.committed_phases: list[RuntimePhase] = []
        self.committed_states = []

    async def commit(self, request, *, call):
        result = await super().commit(request, call=call)
        self.committed_phases.append(request.next_state.phase)
        self.committed_states.append(request.next_state)
        return result


def _binding() -> NegotiatedBindingReceipt:
    return NegotiatedBindingReceipt(
        schema_version=1,
        port_id="output-adapter",
        protocol_version="1.0.0",
        operation_schema_digests={
            "deliver": (DigestString("request"), DigestString("receipt"))
        },
        enabled_capability_flags=frozenset(),
        component_revision=revision("output-adapter"),
        negotiated_at=NOW,
    )


class OrchestratorFixture:
    def __init__(
        self,
        *,
        direct_output: object = "A bounded answer.",
        verify_response_authorization: bool = True,
        perception_model_call_started: bool = False,
        perception_transform=None,
        cancel_during_perception: bool = False,
        runtime_perception=None,
        context_builder=None,
        budget_plan: RuntimeModelBudgetPlan | None = None,
        tool_budget_plan: RuntimeToolBudgetPlan | None = None,
        initial_budget: RuntimeBudget | None = None,
        capability_runtime=None,
        capability_input_schemas=(),
        capability_plan_authorized: bool = True,
        authorization_verifier=None,
        maximum_tool_context_bytes: int = 16_384,
        record_phases: bool = False,
    ) -> None:
        self.clock = _MutableClock()
        self.policy_snapshot = replace(
            runtime_policy(),
            capability_input_schemas=tuple(capability_input_schemas),
        )
        self.binding = _binding()
        self.perception = runtime_perception or _RuleOnlyRuntimePerception(
            model_call_started=perception_model_call_started,
            transform=perception_transform,
            cancel_on_call=cancel_during_perception,
        )
        store_type = (
            _RecordingRuntimeStateStore if record_phases else InMemoryRuntimeStateStore
        )
        self.store = store_type(
            InMemoryRuntimeStateStoreConfig(
                schema_version=1,
                checkpoint_ttl=timedelta(minutes=30),
                tombstone_ttl=timedelta(minutes=30),
                maximum_checkpoints=100,
                maximum_dedup_records=100,
                component_revision=revision("runtime-store"),
            ),
            clock=self.clock,
        )
        self.budget_plan = budget_plan or RuntimeModelBudgetPlan(
            schema_version=1,
            perception_reservation=ResourceUsage(
                1,
                1,
                0,
                1,
                1_000,
                200,
                Decimal(1),
            ),
            direct_chat_reservation=ResourceUsage(
                1,
                1,
                0,
                1,
                3_000,
                500,
                Decimal(3),
            ),
            revision=revision("runtime-budget"),
        )
        self.initial_budget = initial_budget or RuntimeBudget(
            2,
            0,
            2,
            4_000,
            700,
            Decimal(4),
        )
        constraints = {
            "message.respond": AuthorizationConstraint(
                resource_types=frozenset({"conversation"}),
                resource_ids=frozenset({"*"}),
                maximum_risk=RiskLevel.LOW,
            ),
            "message.send": AuthorizationConstraint(
                resource_types=frozenset({"delivery"}),
                resource_ids=frozenset({"*"}),
                maximum_risk=RiskLevel.LOW,
            ),
        }
        permissions = {"message.respond", "message.send"}
        if capability_runtime is not None or tool_budget_plan is not None:
            constraints["capability.plan"] = AuthorizationConstraint(
                resource_types=frozenset({"capability-plan"}),
                resource_ids=frozenset({"*"}),
                maximum_risk=RiskLevel.LOW,
            )
            if capability_plan_authorized:
                permissions.add("capability.plan")
        self.authorization = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                policy_revision=self.policy_snapshot.authorization_policy_revision,
                role_permissions={"user": frozenset(permissions)},
                role_constraints={"user": constraints},
                decision_ttl=timedelta(minutes=5),
            ),
            clock=self.clock,
        )
        self.router_fixture = direct_fixture(direct_output)
        self.router = _CountingRouter(self.router_fixture.router)
        profiles = {depth: "balanced" for depth in TaskReasoningDepth}
        self.direct_chat = DirectChatModelCall(
            self.router,
            replace(
                direct_config(),
                reasoning_profiles=profiles,
                max_output_tokens=(
                    self.budget_plan.direct_chat_reservation.output_tokens
                ),
                maximum_tool_context_bytes=maximum_tool_context_bytes,
            ),
            visible_token_counter=UnicodeVisibleTokenCounter(
                revision("visible-token-counter")
            ),
            clock=self.clock,
        )
        delivery_builder = DeliveryRequestBuilder(
            DeliveryRequestBuilderConfig(
                schema_version=1,
                constraints=DeliveryConstraints(
                    1,
                    64,
                    512,
                    False,
                    frozenset(),
                    timedelta(minutes=10),
                ),
                adapter_binding=self.binding,
            ),
            self.authorization,
            clock=self.clock,
        )
        self.runtime = OfflineRuntimeOrchestrator(
            OfflineRuntimeOrchestratorConfig(
                schema_version=1,
                persona_id="dududa",
                model_budget_plan=self.budget_plan,
                runtime_policy=self.policy_snapshot,
                negotiated_bindings=(self.binding,),
                component_revision=revision("runtime-orchestrator"),
                tool_budget_plan=tool_budget_plan,
            ),
            store=self.store,
            context_builder=context_builder or builder(),
            authorization_policy=self.authorization,
            authorization_verifier=(
                authorization_verifier
                or (
                    self.authorization
                    if verify_response_authorization
                    else _RejectingAuthorizationVerifier()
                )
            ),
            perception=self.perception,
            complexity=DeterministicComplexityAssessor(
                self.policy_snapshot.complexity_assessor
            ),
            social=DeterministicSocialDecisionPolicy(
                self.policy_snapshot.social_decision,
                clock=self.clock,
            ),
            tier_policy=DeterministicModelTierPolicy(),
            direct_chat=self.direct_chat,
            composer=_composer(),
            renderer=_renderer(),
            final_validator=FinalResponseSafetyValidator(
                DeterministicRenderValidator(revision("render-validator")),
                DefaultContentSafetyPolicy(clock=self.clock),
                clock=self.clock,
            ),
            delivery_builder=delivery_builder,
            response_profile_policy=DeterministicResponseProfilePolicy(
                pilot_response_profile_policy_config(
                    revision("response-profile-policy")
                )
            ),
            detail_detector_revision=revision("detail-detector"),
            capability_runtime=capability_runtime,
            clock=self.clock,
        )

    def start(
        self,
        *,
        mentioned: bool = True,
        run_id: str = "run-1",
        feature_flags=None,
        capability_member: bool = False,
    ):
        envelope = message(mentioned=mentioned)
        connector_actor = actor(envelope)
        if capability_member:
            connector_actor = replace(
                connector_actor,
                roles=frozenset({*connector_actor.roles, RoleId("member")}),
            )
        connector = ConnectorResult(
            1,
            envelope,
            connector_actor,
            self.clock.now,
            revision("connector"),
        )
        flags = {"response_profiles": True, **(feature_flags or {})}
        options = RuntimeInvocationOptions(
            1,
            None,
            "astrbot",
            flags,
            "flags-v1",
        )
        request = RuntimeStartRequest(
            1,
            connector,
            options,
            runtime_start_digest(connector, options),
        )
        call = PortCallContext(
            run_id=run_id,
            trace=TraceContext(f"trace:{run_id}"),
            deadline=self.clock.now + timedelta(hours=1),
            cancellation=NeverCancelled(),
            budget=self.initial_budget,
            policy_snapshot_id=self.policy_snapshot.snapshot_id,
        )
        return request, call


class OfflineRuntimeOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_profile_flag_off_preserves_legacy_runtime_shape(
        self,
    ) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start(feature_flags={"response_profiles": False})

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.RESPONSE)
        assert checkpoint is not None
        self.assertIsNone(checkpoint.state.response_profile_request)
        self.assertIsNone(checkpoint.state.response_plan)
        self.assertIsNone(fixture.router.requests[0].response_plan_digest)

    async def test_direct_reply_reaches_ready_through_real_static_router(self) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start()

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.RESPONSE)
        self.assertIsNotNone(result.delivery_request)
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.READY_TO_EMIT)
        self.assertIs(checkpoint.state.tier_decision.selected_tier, ModelTier.SONNET)
        self.assertIs(
            checkpoint.state.direct_route_decision.selected_tier,
            ModelTier.SONNET,
        )
        self.assertIsNotNone(checkpoint.state.response_profile_request)
        self.assertIsNotNone(checkpoint.state.response_plan)
        assert checkpoint.state.response_plan is not None
        self.assertIs(
            checkpoint.state.response_plan.selected_profile,
            AnswerProfile.MEDIUM,
        )
        plan_digest = response_plan_digest(checkpoint.state.response_plan)
        self.assertEqual(
            checkpoint.state.direct_chat_execution.content.response_plan_digest,
            plan_digest,
        )
        self.assertEqual(
            checkpoint.state.draft_response.response_plan_digest,
            plan_digest,
        )
        self.assertEqual(
            checkpoint.state.final_response.response.render_metadata.response_plan_digest,
            plan_digest,
        )
        self.assertLessEqual(
            len(checkpoint.state.delivery_request.part_intents),
            checkpoint.state.response_plan.delivery_part_limit,
        )
        with self.assertRaises(DududaError):
            replace(checkpoint.state, response_profile_request=None)
        with self.assertRaises(DududaError):
            replace(
                checkpoint.state,
                response_plan=replace(
                    checkpoint.state.response_plan,
                    assessment_digest=DigestString("assessment:forged"),
                ),
            )
        self.assertEqual(fixture.perception.calls, 1)
        self.assertEqual(fixture.router.calls, 1)

    async def test_concurrent_duplicate_runs_execute_one_model_chain(self) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start()

        results = await asyncio.gather(
            *(fixture.runtime.run(request, call=call) for _ in range(50))
        )

        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(fixture.perception.calls, 1)
        self.assertEqual(fixture.router.calls, 1)
        requests = tuple(result.delivery_request for result in results)
        self.assertTrue(all(item is not None for item in requests))
        self.assertEqual(
            len({item.request_digest for item in requests if item is not None}),
            1,
        )

    async def test_failed_perception_attempt_is_charged_before_rule_fallback(
        self,
    ) -> None:
        fixture = OrchestratorFixture(perception_model_call_started=True)
        request, call = fixture.start()

        await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        assert checkpoint is not None
        self.assertEqual(
            checkpoint.state.charged_usage,
            ResourceUsage(
                schema_version=1,
                model_calls=2,
                tool_steps=0,
                retries=2,
                input_tokens=4_000,
                output_tokens=700,
                cost_units=Decimal(4),
            ),
        )
        self.assertEqual(
            checkpoint.state.budget, RuntimeBudget(0, 0, 0, 0, 0, Decimal(0))
        )

    async def test_fixed_haiku_perception_and_sonnet_direct_route_are_one_chain(
        self,
    ) -> None:
        envelope = message()
        context_builder = CurrentMessageContextBuilder(
            CurrentMessageContextBuilderConfig(
                schema_version=1,
                limits=perception_limits(),
                maximum_content_input_tokens=100_000,
                private_data_classification=PrivacyLevel.PERSONAL,
                group_data_classification=PrivacyLevel.CONVERSATION,
                component_revision=revision("real-perception-context"),
            )
        )
        preprocess = context_builder.preprocess(envelope, actor(envelope))
        projected = context_builder.build(
            envelope,
            actor(envelope),
            ConversationScope(
                envelope.platform,
                envelope.bot_id,
                envelope.conversation_type,
                envelope.conversation_id,
                envelope.group_id,
                "dududa",
            ),
            preprocess,
        )
        author_ref = projected.current_author_identity_ref
        payload = {
            "schema_version": 1,
            "target_identity_refs": [author_ref],
            "speech_acts": ["request"],
            "topics": [],
            "intents": [],
            "entities": [],
            "references": [],
            "ambiguities": [],
            "need_tools": False,
            "capability_categories": [],
            "task_kind": "direct_chat",
            "reasoning_depth": "shallow",
            "expected_tool_steps": 0,
            "verification_required": False,
            "complexity_signals": [],
            "confidence": 0.9,
        }
        perception_fixture = _RuntimePerceptionFixture((ProviderSuccess(payload),))
        plan = RuntimeModelBudgetPlan(
            schema_version=1,
            perception_reservation=ResourceUsage(
                1,
                1,
                0,
                1,
                100_000,
                2_048,
                Decimal(100),
            ),
            direct_chat_reservation=ResourceUsage(
                1,
                1,
                0,
                1,
                3_000,
                500,
                Decimal(3),
            ),
            revision=revision("real-perception-budget"),
        )
        fixture = OrchestratorFixture(
            runtime_perception=perception_fixture.engine,
            context_builder=context_builder,
            budget_plan=plan,
            initial_budget=RuntimeBudget(
                2,
                0,
                2,
                103_000,
                2_548,
                Decimal(103),
            ),
        )
        request, call = fixture.start()

        await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        assert checkpoint is not None
        self.assertIs(
            checkpoint.state.perception_execution.route_decision.requested_tier,
            ModelTier.HAIKU,
        )
        self.assertIs(checkpoint.state.tier_decision.selected_tier, ModelTier.SONNET)
        self.assertIs(
            checkpoint.state.direct_route_decision.requested_tier,
            ModelTier.SONNET,
        )
        self.assertEqual(len(perception_fixture.router.calls), 1)
        perception_request, _, _ = perception_fixture.router.calls[0]
        self.assertIsNone(perception_request.route_hint)

    async def test_unmentioned_group_is_completed_without_model_or_delivery(
        self,
    ) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start(mentioned=False)

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.NO_REPLY)
        self.assertIsNone(result.delivery_request)
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.COMPLETED)
        self.assertEqual(fixture.perception.calls, 0)
        self.assertEqual(fixture.router.calls, 0)

    async def test_bounded_clarification_skips_tier_and_direct_model(self) -> None:
        def add_ambiguity(result, context):
            return replace(
                result,
                ambiguities=(
                    AmbiguityCandidate(
                        schema_version=1,
                        ambiguity_id="ambiguity:task",
                        kind=AmbiguityKind.TASK,
                        clarification_key=ClarificationKey.TASK,
                        confidence=0.9,
                        evidence_refs=(context.current_message_ref,),
                    ),
                ),
            )

        fixture = OrchestratorFixture(perception_transform=add_ambiguity)
        request, call = fixture.start()

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.RESPONSE)
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.READY_TO_EMIT)
        self.assertIsNone(checkpoint.state.tier_decision)
        self.assertIsNone(checkpoint.state.direct_route_decision)
        self.assertIsNotNone(checkpoint.state.response_plan)
        self.assertIs(
            checkpoint.state.response_plan.selected_profile,
            AnswerProfile.SHORT,
        )
        self.assertEqual(fixture.router.calls, 0)

    async def test_tool_requirement_defers_without_tool_or_direct_model(self) -> None:
        def require_tool(result, context):
            return replace(result, need_tools=True, expected_tool_steps=1)

        fixture = OrchestratorFixture(perception_transform=require_tool)
        request, call = fixture.start()

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.DEFERRED)
        self.assertIn("tool_use_not_authorized", result.reason_codes)
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.DEFERRED)
        self.assertIsNone(result.delivery_request)
        self.assertEqual(fixture.router.calls, 0)

    async def test_invalid_direct_output_becomes_typed_failed_result(self) -> None:
        fixture = OrchestratorFixture(direct_output="   ")
        request, call = fixture.start()

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.FAILED)
        self.assertIn("invalid_direct_chat_text_output", result.reason_codes)
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.FAILED)
        self.assertIsNone(result.delivery_request)
        self.assertIsNotNone(checkpoint.state.direct_chat_failure)
        self.assertEqual(
            checkpoint.state.direct_chat_failure.charged_usage,
            fixture.budget_plan.direct_chat_reservation,
        )
        self.assertEqual(
            checkpoint.state.charged_usage,
            fixture.budget_plan.direct_chat_reservation,
        )

    async def test_unissued_response_authorization_never_reaches_perception(
        self,
    ) -> None:
        fixture = OrchestratorFixture(verify_response_authorization=False)
        request, call = fixture.start()

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.FAILED)
        self.assertEqual(
            result.reason_codes,
            ("runtime_response_authorization_unissued",),
        )
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.FAILED)
        self.assertEqual(fixture.perception.calls, 0)
        self.assertEqual(fixture.router.calls, 0)

    async def test_pre_cancelled_start_creates_no_checkpoint(self) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start()
        cancellation = ManualCancellationToken()
        cancellation.cancel()
        cancelled_call = replace(call, cancellation=cancellation)

        with self.assertRaises(DududaError):
            await fixture.runtime.run(request, call=cancelled_call)
        active_call = replace(call, cancellation=NeverCancelled())
        self.assertIsNone(await fixture.store.load(call.run_id, call=active_call))

    async def test_cancellation_after_checkpoint_records_failure_without_routing(
        self,
    ) -> None:
        fixture = OrchestratorFixture(cancel_during_perception=True)
        request, call = fixture.start()
        cancellation = ManualCancellationToken()
        running_call = replace(call, cancellation=cancellation)

        result = await fixture.runtime.run(request, call=running_call)
        active_call = replace(call, cancellation=NeverCancelled())
        checkpoint = await fixture.store.load(call.run_id, call=active_call)

        self.assertTrue(cancellation.is_cancelled)
        self.assertIs(result.outcome, Outcome.FAILED)
        self.assertEqual(
            result.reason_codes,
            ("perception_cancelled_during_execution",),
        )
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.FAILED)
        self.assertEqual(fixture.router.calls, 0)


if __name__ == "__main__":
    unittest.main()
