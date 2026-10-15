from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import Mention, MessageEnvelope
from dududa.domain.primitives import (
    ConversationType,
    PrivacyLevel,
    ResourceRef,
    ResourceUsage,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    TraceContext,
)
from dududa.domain.task import ContextPressure, TaskComplexityLevel
from dududa.errors import DududaError
from dududa.models.contracts import ModelRole, ModelTier
from dududa.models.tiering import DeterministicModelTierPolicy
from dududa.perception.complexity import DeterministicComplexityAssessor
from dududa.perception.contracts import (
    GroupInteractionMode,
    PerceptionLimits,
    PerceptionModelStatus,
    SocialAction,
)
from dududa.perception.merge import DeterministicPerceptionMerger, PerceptionMergeConfig
from dududa.perception.rules import (
    DeterministicRulePerception,
    default_rule_perception_config,
)
from dududa.perception.social import DeterministicSocialDecisionPolicy
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.runtime.authorization import build_response_authorization_request
from dududa.runtime.budget import (
    RuntimeModelBudgetPlan,
    reservation_budget,
    zero_usage_for_budget,
)
from dududa.runtime.context import (
    CurrentMessageContextBuilder,
    CurrentMessageContextBuilderConfig,
)
from dududa.runtime.contracts import PerceptionExecutionReceipt
from dududa.runtime.selection import (
    project_s10_decision_signals,
    project_tier_selection_context,
)
from dududa.runtime.state import (
    ConnectorResult,
    RuntimeInvocationOptions,
    RuntimePhase,
    RuntimeState,
    runtime_start_digest,
    transition,
)
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.digests import (
    authorization_metadata_digest,
    authorization_request_digest,
    resource_digest,
)

from .helpers import revision, runtime_policy


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


class RuntimeSelectionEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.policy = runtime_policy()
        self.message = MessageEnvelope(
            schema_version=1,
            message_id="message-1",
            platform="qq",
            bot_id="bot-1",
            conversation_type=ConversationType.GROUP,
            conversation_id="group-1",
            group_id="group-1",
            user_id="user-1",
            reply_to=None,
            timestamp=NOW,
            text="hello",
            mentions=(Mention("qq", "bot-1"),),
        )
        self.actor = Actor(
            "qq",
            "bot-1",
            "user-1",
            frozenset({RoleId("normal")}),
        )
        self.scope = ConversationScope(
            "qq",
            "bot-1",
            ConversationType.GROUP,
            "group-1",
            "group-1",
            "dududa",
        )
        self.initial_budget = RuntimeBudget(2, 0, 0, 4_000, 1_000, Decimal("4"))
        self.budget_plan = RuntimeModelBudgetPlan(
            1,
            ResourceUsage(1, 1, 0, 0, 1_000, 200, Decimal("1")),
            ResourceUsage(1, 1, 0, 0, 3_000, 800, Decimal("3")),
            revision("runtime-budget"),
        )
        connector_revision = revision("connector")
        options = RuntimeInvocationOptions(1, None, "astrbot", {}, "flags-v1")
        connector = ConnectorResult(
            1,
            self.message,
            self.actor,
            NOW,
            connector_revision,
        )
        self.initial = RuntimeState(
            schema_version=1,
            run_id="run-1",
            phase=RuntimePhase.RECEIVED,
            message=self.message,
            actor=self.actor,
            received_at=NOW,
            connector_revision=connector_revision,
            invocation_options=options,
            start_digest=runtime_start_digest(connector, options),
            conversation_scope=self.scope,
            initial_budget=self.initial_budget,
            model_budget_plan=self.budget_plan,
            budget=self.initial_budget,
            charged_usage=zero_usage_for_budget(self.initial_budget),
            trace_context=TraceContext("trace-1"),
            policy_snapshot_id=self.policy.snapshot_id,
            runtime_policy=self.policy,
        )
        self.context_builder = CurrentMessageContextBuilder(
            CurrentMessageContextBuilderConfig(
                schema_version=1,
                limits=PerceptionLimits(1, 1, 4, 4_000, 4_000, 4, 4, 8, 8),
                maximum_content_input_tokens=4_000,
                private_data_classification=PrivacyLevel.CONVERSATION,
                group_data_classification=PrivacyLevel.CONVERSATION,
                component_revision=revision("context-builder"),
            )
        )

    def _call(self) -> PortCallContext:
        return PortCallContext(
            run_id="run-1",
            trace=TraceContext("trace-1"),
            deadline=NOW + timedelta(seconds=30),
            cancellation=NeverCancelled(),
            budget=self.initial_budget,
            policy_snapshot_id=self.policy.snapshot_id,
        )

    async def _context_ready(self, *, allow: bool) -> tuple[RuntimeState, object]:
        preprocess = self.context_builder.preprocess(self.message, self.actor)
        preprocessed = transition(
            self.initial,
            RuntimePhase.PREPROCESSED,
            preprocess_result=preprocess,
        )
        context = self.context_builder.build(
            self.message,
            self.actor,
            self.scope,
            preprocess,
        )
        request = build_response_authorization_request(
            self.actor,
            self.scope,
            policy_snapshot_id=self.policy.snapshot_id,
        )
        permissions = frozenset({"message.respond"}) if allow else frozenset()
        authorization = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                policy_revision=self.policy.authorization_policy_revision,
                role_permissions={"normal": permissions},
                role_constraints={
                    "normal": {
                        "message.respond": AuthorizationConstraint(
                            resource_types=frozenset({"conversation"}),
                            resource_ids=frozenset({"*"}),
                            maximum_risk=RiskLevel.LOW,
                        )
                    }
                },
            ),
            clock=lambda: NOW,
            id_factory=lambda: "response-authorization-1",
        )
        decision = await authorization.decide(request, call=self._call())
        return (
            transition(
                preprocessed,
                RuntimePhase.CONTEXT_READY,
                current_context=context,
                response_authorization_request=request,
                response_authorization=decision,
            ),
            authorization,
        )

    def _set_preview_history(self, *, long_message: bool = False) -> None:
        self.message = replace(self.message, metadata={"preview_history": {
            "accountId": "qq-bot-1", "conversationId": "qq-bot-1:group:group-1",
            "source": "synthetic", "truncated": False, "messages": [
                {"id": "h1", "senderId": "member-a", "senderName": "甲",
                 "content": "会议周五举行", "timestamp": None},
                {"id": "h2", "senderId": "member-b", "senderName": "乙",
                 "content": '"' * 2000 if long_message else "更正：周六晚上八点",
                 "timestamp": None, "replyToId": "h1"},
            ],
        }})
        self.initial = replace(self.initial, message=self.message,
            start_digest=runtime_start_digest(
                ConnectorResult(1, self.message, self.actor, NOW,
                                self.initial.connector_revision),
                self.initial.invocation_options,
            ))
        self.context_builder = CurrentMessageContextBuilder(replace(
            self.context_builder.config,
            limits=replace(self.context_builder.config.limits, max_messages=4,
                           max_identities=8, max_characters_per_message=2000),
        ))

    async def test_preview_history_passes_real_context_state_transition(self) -> None:
        self._set_preview_history()
        ready, _ = await self._context_ready(allow=True)
        self.assertIs(ready.phase, RuntimePhase.CONTEXT_READY)
        self.assertEqual(len(ready.current_context.perception.messages), 3)
        self.assertEqual(ready.current_context.perception.current_message.text, "hello")

    async def test_truncated_preview_history_reprojects_at_state_transition(self) -> None:
        self._set_preview_history(long_message=True)
        ready, _ = await self._context_ready(allow=True)
        self.assertGreater(len(ready.current_context.perception.messages), 1)
        self.assertIn("preview_history_truncated", ready.current_context.perception.degraded_components)

    async def test_preview_state_rejects_unbound_or_modified_history(self) -> None:
        self._set_preview_history()
        ready, _ = await self._context_ready(allow=True)
        context = ready.current_context
        for index, changes in ((0, {"text": "forged history"}),
                               (-1, {"text": "forged instruction"}),
                               (-1, {"mentioned_identity_refs": ()})):
            with self.subTest(index=index, changes=changes), self.assertRaises(DududaError):
                messages = list(context.perception.messages)
                messages[index] = replace(messages[index], **changes)
                replace(ready, current_context=replace(context,
                    perception=replace(context.perception, messages=tuple(messages))))
        self.message = replace(self.message, metadata={})
        self.initial = replace(self.initial, message=self.message,
            start_digest=runtime_start_digest(
                ConnectorResult(1, self.message, self.actor, NOW,
                                self.initial.connector_revision),
                self.initial.invocation_options,
            ))
        plain, _ = await self._context_ready(allow=True)
        with self.assertRaises(DududaError) as captured:
            replace(plain, current_context=context)
        self.assertEqual(captured.exception.info.code, "runtime_context_projection_mismatch")

    def _perception_evidence(self, state: RuntimeState):
        context = state.current_context
        assert context is not None
        rules = DeterministicRulePerception(
            default_rule_perception_config(revision("rule-perception")),
            id_factory=lambda: "rule-result-1",
        ).perceive(context.perception)
        perception = DeterministicPerceptionMerger(
            PerceptionMergeConfig(
                pipeline_revision=revision("perception-pipeline"),
                merger_revision=revision("perception-merger"),
                validator_revision=revision("perception-validator"),
                fallback_confidence_ceiling=0.59,
                conflict_confidence_ceiling=0.55,
            ),
            id_factory=lambda: "perception-result-1",
        ).merge(
            context.perception,
            rules,
            None,
            model_status=PerceptionModelStatus.UNAVAILABLE,
        )
        receipt = PerceptionExecutionReceipt(
            schema_version=1,
            result=perception,
            model_call_started=False,
            request_fingerprint=None,
            route_decision=None,
            reported_usage=None,
            model_status=PerceptionModelStatus.UNAVAILABLE,
            failure_code="model_unavailable",
        )
        assessment = DeterministicComplexityAssessor(
            self.policy.complexity_assessor,
            id_factory=lambda: "assessment-1",
        ).assess(context.perception, perception)
        return receipt, assessment

    async def _perceived(self, *, allow: bool):
        context_ready, authorization_policy = await self._context_ready(allow=allow)
        receipt, assessment = self._perception_evidence(context_ready)
        return (
            transition(
                context_ready,
                RuntimePhase.PERCEIVED,
                perception_execution=receipt,
                complexity_assessment=assessment,
                complexity_source_digest=receipt.result_digest,
            ),
            authorization_policy,
        )

    async def test_state_recomputes_complexity_and_rejects_forged_high(self) -> None:
        context_ready, _ = await self._context_ready(allow=True)
        receipt, assessment = self._perception_evidence(context_ready)
        for forged in (
            replace(assessment, level=TaskComplexityLevel.HIGH),
            replace(assessment, context_pressure=ContextPressure.HIGH),
            replace(assessment, confidence=assessment.confidence - 0.1),
            replace(
                assessment,
                reason_codes=assessment.reason_codes + ("forged_complexity",),
            ),
            replace(assessment, assessor_revision=revision("forged-assessor")),
        ):
            with (
                self.subTest(forged=forged),
                self.assertRaises(DududaError) as captured,
            ):
                transition(
                    context_ready,
                    RuntimePhase.PERCEIVED,
                    perception_execution=receipt,
                    complexity_assessment=forged,
                    complexity_source_digest=receipt.result_digest,
                )

            self.assertEqual(
                captured.exception.info.code,
                "task_complexity_assessment_binding_mismatch",
            )

    async def test_state_rejects_self_consistent_forged_authorization_input(
        self,
    ) -> None:
        context_ready, _ = await self._context_ready(allow=True)
        request = context_ready.response_authorization_request
        decision = context_ready.response_authorization
        assert request is not None and decision is not None
        forged_requests = (
            replace(
                request,
                resource=ResourceRef(
                    "conversation",
                    "different-conversation",
                    request.resource.scope_digest,
                ),
            ),
            replace(request, risk_level=RiskLevel.HIGH),
            replace(
                request,
                metadata={
                    "policy_snapshot_id": self.policy.snapshot_id,
                    "purpose": "different-purpose",
                },
            ),
            replace(request, capability_id="forged-capability"),
        )
        for candidate in forged_requests:
            candidate = replace(
                candidate,
                request_digest=authorization_request_digest(candidate),
            )
            forged_decision = replace(
                decision,
                request_digest=candidate.request_digest,
                resource_digest=resource_digest(candidate.resource),
                capability_id=candidate.capability_id,
                risk_level=candidate.risk_level,
                metadata_digest=authorization_metadata_digest(candidate.metadata),
            )
            with (
                self.subTest(candidate=candidate),
                self.assertRaises(DududaError) as captured,
            ):
                replace(
                    context_ready,
                    response_authorization_request=candidate,
                    response_authorization=forged_decision,
                )
            self.assertEqual(
                captured.exception.info.code,
                "runtime_response_authorization_scope_mismatch",
            )

    async def test_runtime_policy_is_an_immutable_state_root(self) -> None:
        context_ready, _ = await self._context_ready(allow=True)
        changed = replace(
            self.policy,
            group_mode=GroupInteractionMode.ACTIVE,
        )

        with self.assertRaises(DududaError) as captured:
            transition(
                context_ready,
                RuntimePhase.PERCEIVED,
                runtime_policy=changed,
            )

        self.assertEqual(captured.exception.info.code, "runtime_root_cannot_change")

    async def test_state_recomputes_social_action_and_rejects_forged_reply(
        self,
    ) -> None:
        perceived, _ = await self._perceived(allow=False)
        assert perceived.current_context is not None
        assert perceived.preprocess_result is not None
        assert perceived.response_authorization is not None
        assert perceived.perception_execution is not None
        result = perceived.perception_execution.result
        signals = project_s10_decision_signals(
            authorization=perceived.response_authorization,
            duplicate_or_self_message=False,
            explicit_interaction=perceived.preprocess_result.explicit_interaction,
            conversation_type=self.message.conversation_type,
            data_classification=perceived.preprocess_result.data_classification,
            group_mode=self.policy.group_mode,
            known_target=bool(result.target_identity_refs),
        )
        ignored = await DeterministicSocialDecisionPolicy(
            self.policy.social_decision,
            clock=lambda: NOW,
            id_factory=lambda: "social-decision-1",
        ).decide(result, signals, call=self._call())
        self.assertIs(ignored.action, SocialAction.IGNORE)
        forged = replace(
            ignored,
            action=SocialAction.DIRECT_REPLY,
            confidence=result.confidence,
            reason_codes=("explicit_direct_reply",),
            target_identity_refs=result.target_identity_refs,
        )

        with self.assertRaises(DududaError) as captured:
            transition(
                perceived,
                RuntimePhase.DECIDED,
                decision_signals=signals,
                social_decision=forged,
            )

        self.assertEqual(
            captured.exception.info.code, "social_decision_binding_mismatch"
        )

    async def test_state_recomputes_tier_and_rejects_forged_opus(self) -> None:
        perceived, _ = await self._perceived(allow=True)
        assert perceived.current_context is not None
        assert perceived.preprocess_result is not None
        assert perceived.response_authorization is not None
        assert perceived.perception_execution is not None
        assert perceived.complexity_assessment is not None
        result = perceived.perception_execution.result
        signals = project_s10_decision_signals(
            authorization=perceived.response_authorization,
            duplicate_or_self_message=False,
            explicit_interaction=perceived.preprocess_result.explicit_interaction,
            conversation_type=self.message.conversation_type,
            data_classification=perceived.preprocess_result.data_classification,
            group_mode=self.policy.group_mode,
            known_target=bool(result.target_identity_refs),
        )
        social = await DeterministicSocialDecisionPolicy(
            self.policy.social_decision,
            clock=lambda: NOW,
            id_factory=lambda: "social-decision-1",
        ).decide(result, signals, call=self._call())
        tier_context = project_tier_selection_context(
            selection_id="tier-selection-1",
            role=ModelRole.DIRECT_CHAT,
            assessment=perceived.complexity_assessment,
            content_input_tokens_upper_bound=(
                perceived.current_context.perception.content_input_tokens_upper_bound
            ),
            data_classification=(
                perceived.current_context.perception.data_classification
            ),
            budget=reservation_budget(self.budget_plan.direct_chat_reservation),
        )
        tier = DeterministicModelTierPolicy(
            id_factory=lambda: "tier-decision-1"
        ).decide(tier_context, self.policy.direct_chat_tier, now=NOW)
        self.assertIs(tier.selected_tier, ModelTier.SONNET)
        forged = replace(
            tier,
            selected_tier=ModelTier.OPUS,
            uncapped_tier=ModelTier.OPUS,
        )

        with self.assertRaises(DududaError) as captured:
            transition(
                perceived,
                RuntimePhase.DECIDED,
                decision_signals=signals,
                social_decision=social,
                tier_selection_context=tier_context,
                tier_decision=forged,
            )

        self.assertEqual(captured.exception.info.code, "tier_decision_binding_mismatch")


if __name__ == "__main__":
    unittest.main()
