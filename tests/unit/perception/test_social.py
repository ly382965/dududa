from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.errors import DududaError, ErrorCategory
from dududa.perception.contracts import (
    AuthorizationView,
    DecisionSignals,
    GroupInteractionMode,
    SocialAction,
)
from dududa.perception.social import (
    DeterministicSocialDecisionPolicy,
    SocialDecisionConfig,
    validate_social_decision,
)
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
)

from .helpers import NOW, context, model_payload
from .test_complexity import _perception


def _signals(**overrides: object) -> DecisionSignals:
    values: dict[str, object] = {
        "schema_version": 1,
        "authorization": AuthorizationView(1, True, False, ("direct_reply",)),
        "duplicate_or_self_message": False,
        "explicit_interaction": True,
        "private_conversation": False,
        "group_mode": GroupInteractionMode.NORMAL,
        "rate_limited": False,
        "private_data_boundary": False,
        "tools_enabled": False,
        "known_target": True,
    }
    values.update(overrides)
    return DecisionSignals(**values)


def _call(*, cancellation=None, deadline=None) -> PortCallContext:
    return PortCallContext(
        run_id="run-1",
        trace=TraceContext("trace-1"),
        deadline=deadline or NOW + timedelta(seconds=30),
        cancellation=cancellation or NeverCancelled(),
        budget=RuntimeBudget(2, 0, 1, 8_000, 2_000, Decimal(8)),
        policy_snapshot_id="policy-snapshot-1",
    )


def _policy() -> DeterministicSocialDecisionPolicy:
    return DeterministicSocialDecisionPolicy(
        SocialDecisionConfig("social-v1", 0.6),
        clock=lambda: NOW,
        id_factory=lambda: "social-decision-1",
    )


class DeterministicSocialDecisionPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_supported_request_becomes_direct_reply(self) -> None:
        perception = _perception(context())

        decision = await _policy().decide(
            perception,
            _signals(),
            call=_call(),
        )

        self.assertIs(decision.action, SocialAction.DIRECT_REPLY)
        self.assertEqual(decision.target_identity_refs, ("identity:user",))

    async def test_active_proactive_group_reply_is_group_level(self) -> None:
        perception = _perception(context())

        decision = await _policy().decide(
            perception,
            _signals(
                explicit_interaction=False,
                known_target=False,
                group_mode=GroupInteractionMode.ACTIVE,
            ),
            call=_call(),
        )

        self.assertIs(decision.action, SocialAction.DIRECT_REPLY)
        self.assertEqual(decision.reason_codes, ("proactive_group_direct_reply",))
        self.assertEqual(decision.target_identity_refs, ())

    async def test_active_proactive_group_skips_non_chat_opportunities(self) -> None:
        authorized = AuthorizationView(1, True, True, ("bounded_tools",))
        cases = (
            (
                _perception(
                    context(),
                    model_payload(
                        need_tools=True,
                        capability_categories=["search"],
                        expected_tool_steps=1,
                    ),
                ),
                _signals(
                    authorization=authorized,
                    tools_enabled=False,
                    private_data_boundary=False,
                ),
                "proactive_group_tool_use_skipped",
            ),
            (
                _perception(
                    context(),
                    model_payload(
                        ambiguities=[
                            {
                                "ambiguity_id": "ambiguity:task",
                                "kind": "task",
                                "clarification_key": "clarify.task",
                                "confidence": 0.9,
                                "evidence_refs": ["message:current"],
                            }
                        ]
                    ),
                ),
                _signals(),
                "proactive_group_clarification_skipped",
            ),
        )
        for perception, signals, expected_reason in cases:
            proactive = _signals(
                authorization=signals.authorization,
                explicit_interaction=False,
                known_target=False,
                group_mode=GroupInteractionMode.ACTIVE,
                private_data_boundary=signals.private_data_boundary,
                tools_enabled=signals.tools_enabled,
            )
            with self.subTest(reason=expected_reason):
                decision = await _policy().decide(
                    perception,
                    proactive,
                    call=_call(),
                )
                self.assertIs(decision.action, SocialAction.IGNORE)
                self.assertEqual(decision.reason_codes, (expected_reason,))
                self.assertEqual(decision.target_identity_refs, ())

    async def test_hard_ignore_gates_precede_soft_semantics(self) -> None:
        perception = _perception(context())
        cases = (
            _signals(duplicate_or_self_message=True),
            _signals(known_target=False),
            _signals(authorization=AuthorizationView(1, False, False, ("denied",))),
            _signals(rate_limited=True),
            _signals(explicit_interaction=False),
        )
        for signals in cases:
            with self.subTest(signals=signals):
                decision = await _policy().decide(
                    perception,
                    signals,
                    call=_call(),
                )
                self.assertIs(decision.action, SocialAction.IGNORE)
                self.assertEqual(decision.target_identity_refs, ())

    async def test_privacy_and_tools_defer_without_emitting_tool_action(self) -> None:
        privacy = await _policy().decide(
            _perception(context()),
            _signals(private_data_boundary=True),
            call=_call(),
        )
        tool_payload = model_payload(
            need_tools=True,
            capability_categories=["search"],
            expected_tool_steps=1,
        )
        tool = await _policy().decide(
            _perception(context(), tool_payload),
            _signals(),
            call=_call(),
        )

        self.assertIs(privacy.action, SocialAction.DEFER)
        self.assertIs(tool.action, SocialAction.DEFER)
        self.assertNotEqual(tool.action, SocialAction.USE_TOOLS)

    async def test_tools_require_both_authorization_and_feature_gate(self) -> None:
        perception = _perception(
            context(),
            model_payload(
                need_tools=True,
                capability_categories=["search"],
                expected_tool_steps=1,
            ),
        )
        authorized = AuthorizationView(1, True, True, ("bounded_tools",))

        disabled = await _policy().decide(
            perception,
            _signals(authorization=authorized, tools_enabled=False),
            call=_call(),
        )
        enabled = await _policy().decide(
            perception,
            _signals(authorization=authorized, tools_enabled=True),
            call=_call(),
        )

        self.assertIs(disabled.action, SocialAction.DEFER)
        self.assertEqual(disabled.reason_codes, ("tools_disabled",))
        self.assertIs(enabled.action, SocialAction.USE_TOOLS)
        self.assertEqual(enabled.reason_codes, ("bounded_tool_execution",))

    async def test_bounded_ambiguity_asks_one_clarification(self) -> None:
        payload = model_payload(
            ambiguities=[
                {
                    "ambiguity_id": "ambiguity:task",
                    "kind": "task",
                    "clarification_key": "clarify.task",
                    "confidence": 0.9,
                    "evidence_refs": ["message:current"],
                }
            ]
        )
        perception = _perception(context(), payload)

        decision = await _policy().decide(
            perception,
            _signals(),
            call=_call(),
        )

        self.assertIs(decision.action, SocialAction.ASK_CLARIFICATION)
        self.assertEqual(decision.clarification_key, "clarify.task")

    async def test_conflict_deferral_preserves_only_fixed_diagnostic_codes(self) -> None:
        codes = (
            "rule_model_conflict_task_kind", "rule_model_conflict_targets",
            "rule_model_conflict_tools", "rule_model_conflict_depth",
        )
        perception = replace(
            _perception(context()), conflicting_evidence=True,
            reason_codes=(*codes, "rule_model_conflict", "untrusted_projection_label"),
        )
        signals = _signals()
        decision = await _policy().decide(perception, signals, call=_call())
        self.assertIs(decision.action, SocialAction.DEFER)
        self.assertEqual(set(decision.reason_codes), {
            "conflicting_evidence_without_clarification", *codes,
        })
        self.assertEqual(validate_social_decision(
            decision, perception, signals, SocialDecisionConfig("social-v1", 0.6),
        ), decision)

    async def test_cancellation_and_deadline_are_not_soft_fallbacks(self) -> None:
        perception = _perception(context())
        cancellation = ManualCancellationToken()
        cancellation.cancel()
        cases = (
            _call(cancellation=cancellation),
            _call(deadline=NOW),
        )
        expected = (ErrorCategory.CANCELLED, ErrorCategory.TIMEOUT)
        for call, category in zip(cases, expected):
            with (
                self.subTest(category=category),
                self.assertRaises(DududaError) as captured,
            ):
                await _policy().decide(perception, _signals(), call=call)
            self.assertIs(captured.exception.info.category, category)


if __name__ == "__main__":
    unittest.main()
