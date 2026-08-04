from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from dududa.contracts.canonical import canonical_digest
from dududa.domain.delivery import DeliveryStatus
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import Mention, MessageEnvelope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DenyFlag,
    DigestString,
    PrivacyLevel,
    ResourceUsage,
    RoleId,
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.runtime.budget import RuntimeModelBudgetPlan, zero_usage_for_budget
from dududa.runtime.contracts import (
    OfflinePreprocessReceipt,
    RuntimeAdmissionAction,
)
from dududa.runtime.state import (
    CompletionReceipt,
    ConnectorResult,
    Outcome,
    RuntimeInvocationOptions,
    RuntimePhase,
    RuntimeResult,
    RuntimeStartRequest,
    RuntimeState,
    TraceSummary,
    runtime_start_digest,
    transition,
)
from dududa.security.digests import actor_digest

from .helpers import runtime_policy


class RuntimeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        now = datetime.now(timezone.utc)
        self.message = MessageEnvelope(
            schema_version=1,
            message_id="m-1",
            platform="qq",
            bot_id="bot-1",
            conversation_type=ConversationType.GROUP,
            conversation_id="g-1",
            group_id="g-1",
            user_id="u-1",
            reply_to=None,
            timestamp=now,
            text="hello",
            mentions=(Mention("qq", "bot-1"),),
        )
        self.actor = Actor(
            "qq",
            "bot-1",
            "u-1",
            frozenset({RoleId("normal")}),
            frozenset({DenyFlag("none")}),
        )
        revision = ComponentRevision(
            "connector.astrbot",
            "0.1.0",
            "cfg-1",
            DigestString("digest"),
        )
        initial_budget = RuntimeBudget(2, 0, 1, 1000, 500, Decimal(1))
        budget_plan = RuntimeModelBudgetPlan(
            1,
            ResourceUsage(1, 1, 0, 0, 300, 100, Decimal("0.3")),
            ResourceUsage(1, 1, 0, 1, 500, 200, Decimal("0.5")),
            ComponentRevision(
                "runtime.budget",
                "0.1.0",
                "cfg-1",
                DigestString("budget-plan"),
            ),
        )
        options = RuntimeInvocationOptions(
            1, None, "astrbot", {"runtime_v2": False}, "flags-1"
        )
        connector = ConnectorResult(1, self.message, self.actor, now, revision)
        self.state = RuntimeState(
            schema_version=1,
            run_id="run-1",
            phase=RuntimePhase.RECEIVED,
            message=self.message,
            actor=self.actor,
            received_at=now,
            connector_revision=revision,
            invocation_options=options,
            start_digest=runtime_start_digest(connector, options),
            conversation_scope=ConversationScope(
                "qq", "bot-1", ConversationType.GROUP, "g-1", "g-1", "dududa"
            ),
            initial_budget=initial_budget,
            model_budget_plan=budget_plan,
            budget=initial_budget,
            charged_usage=zero_usage_for_budget(initial_budget),
            trace_context=TraceContext("trace-1"),
            policy_snapshot_id="policy-1",
            runtime_policy=runtime_policy("policy-1"),
        )
        self.preprocess = OfflinePreprocessReceipt(
            schema_version=1,
            message_digest=canonical_digest(
                self.message,
                domain="runtime:admission-message:v1",
            ),
            actor_digest=actor_digest(self.actor),
            action=RuntimeAdmissionAction.PROCEED,
            data_classification=PrivacyLevel.CONVERSATION,
            explicit_interaction=True,
            reason_codes=("s10_text_admitted",),
            component_revision=revision,
        )

    def test_valid_transition_returns_new_state(self) -> None:
        updated = transition(
            self.state,
            RuntimePhase.PREPROCESSED,
            preprocess_result=self.preprocess,
        )
        self.assertEqual(updated.phase, RuntimePhase.PREPROCESSED)
        self.assertEqual(self.state.phase, RuntimePhase.RECEIVED)

    def test_invalid_transition_is_rejected(self) -> None:
        with self.assertRaises(DududaError):
            transition(self.state, RuntimePhase.COMPLETED)

    def test_admission_ignore_uses_memory_evaluated_completion_path(self) -> None:
        message = replace(self.message, mentions=())
        connector = ConnectorResult(
            1,
            message,
            self.actor,
            self.state.received_at,
            self.state.connector_revision,
        )
        initial = replace(
            self.state,
            message=message,
            start_digest=runtime_start_digest(
                connector,
                self.state.invocation_options,
            ),
        )
        ignored = replace(
            self.preprocess,
            message_digest=canonical_digest(
                message,
                domain="runtime:admission-message:v1",
            ),
            action=RuntimeAdmissionAction.IGNORE,
            explicit_interaction=False,
            reason_codes=("group_explicit_mention_required",),
        )
        preprocessed = transition(
            initial,
            RuntimePhase.PREPROCESSED,
            preprocess_result=ignored,
        )
        evaluated = transition(preprocessed, RuntimePhase.MEMORY_EVALUATED)
        completion = CompletionReceipt(
            1,
            "run-1",
            RuntimePhase.COMPLETED,
            DeliveryStatus.NOT_REQUIRED,
            self.message.timestamp,
        )
        result = RuntimeResult(
            1,
            "run-1",
            Outcome.NO_REPLY,
            None,
            None,
            None,
            completion,
            ("group_explicit_mention_required",),
            TraceSummary(1, "trace-1", (), (), ()),
        )

        completed = transition(
            evaluated,
            RuntimePhase.COMPLETED,
            completion=completion,
            pending_result=result,
        )

        self.assertEqual(completed.phase, RuntimePhase.COMPLETED)
        self.assertIs(completed.completion, completion)

    def test_runtime_scope_binds_conversation_type_and_group(self) -> None:
        private_scope = ConversationScope(
            "qq", "bot-1", ConversationType.PRIVATE, "g-1", None, "dududa"
        )
        with self.assertRaises(DududaError):
            replace(self.state, conversation_scope=private_scope)

    def test_runtime_start_digest_binds_connector_and_options(self) -> None:
        connector = ConnectorResult(
            1,
            self.message,
            self.actor,
            self.message.timestamp,
            self.state.connector_revision,
        )
        options = self.state.invocation_options
        digest = runtime_start_digest(connector, options)
        request = RuntimeStartRequest(1, connector, options, digest)
        self.assertEqual(request.start_digest, digest)
        changed_connector = replace(
            connector,
            message=replace(self.message, text="changed"),
        )
        with self.assertRaises(DududaError):
            RuntimeStartRequest(1, changed_connector, options, digest)

    def test_runtime_state_defensively_freezes_collections(self) -> None:
        trace: list[object] = []
        state = replace(self.state, trace=trace)  # type: ignore[arg-type]
        trace.append(object())
        self.assertEqual(state.trace, ())

    def test_transition_rejects_root_changes_and_future_artifacts(self) -> None:
        with self.assertRaises(DududaError):
            transition(
                self.state,
                RuntimePhase.PREPROCESSED,
                preprocess_result=self.preprocess,
                policy_snapshot_id="forged-policy",
            )
        with self.assertRaises(DududaError):
            transition(
                self.state,
                RuntimePhase.PREPROCESSED,
                preprocess_result=self.preprocess,
                completion=CompletionReceipt(
                    1,
                    "run-1",
                    RuntimePhase.COMPLETED,
                    DeliveryStatus.NOT_REQUIRED,
                    self.message.timestamp,
                ),
            )

    def test_state_rejects_budget_increase_or_unaccounted_charge(self) -> None:
        with self.assertRaises(DududaError):
            replace(
                self.state,
                budget=replace(self.state.budget, model_calls_remaining=3),
            )
        with self.assertRaises(DududaError):
            replace(
                self.state,
                charged_usage=self.state.model_budget_plan.perception_reservation,
            )

    def test_no_reply_requires_completion(self) -> None:
        completion = CompletionReceipt(
            schema_version=1,
            run_id="run-1",
            final_phase=RuntimePhase.COMPLETED,
            delivery_status=DeliveryStatus.NOT_REQUIRED,
            completed_at=datetime.now(timezone.utc),
        )
        result = RuntimeResult(
            schema_version=1,
            run_id="run-1",
            outcome=Outcome.NO_REPLY,
            final_response=None,
            reaction=None,
            delivery_request=None,
            completion=completion,
            reason_codes=("policy_ignore",),
            trace_summary=TraceSummary(1, "trace-1", (), (), ()),
        )
        self.assertEqual(result.outcome, Outcome.NO_REPLY)
        with self.assertRaises(DududaError):
            RuntimeResult(
                1,
                "run-1",
                Outcome.NO_REPLY,
                None,
                None,
                None,
                None,
                (),
                TraceSummary(1, "trace-1", (), (), ()),
            )


if __name__ == "__main__":
    unittest.main()
