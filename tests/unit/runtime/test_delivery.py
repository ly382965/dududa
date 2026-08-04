from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.domain.delivery import (
    DeliveryConstraints,
    DeliveryPartReceipt,
    DeliveryPartStatus,
    DeliveryReceipt,
    DeliveryStatus,
    validate_delivery_receipt_against_request,
)
from dududa.domain.primitives import DigestString, RuntimeBudget, TraceContext
from dududa.errors import DududaError
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.runtime.composition import (
    DeterministicRenderValidator,
    FinalResponseSafetyValidator,
)
from dududa.runtime.delivery import (
    DeliveryRequestBuilder,
    DeliveryRequestBuilderConfig,
    _merge_delivery_receipts,
)
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.content_safety import DefaultContentSafetyPolicy

from plugins.astrbot_plugin_dududa_core.adapters.output import ASTRBOT_OUTPUT_REVISION
from tests.unit.models.helpers import NOW
from tests.unit.runtime.test_composition import (
    _composer,
    _context,
    _decision,
    _direct,
    _renderer,
    _revision,
)
from tests.unit.runtime.test_s10_context_budget import (
    actor as message_actor,
)
from tests.unit.runtime.test_s10_context_budget import (
    scope as message_scope,
)


def _call() -> PortCallContext:
    return PortCallContext(
        "run-1",
        TraceContext("trace-1"),
        NOW + timedelta(days=1),
        NeverCancelled(),
        RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
        "policy-v1",
    )


def _binding() -> NegotiatedBindingReceipt:
    return NegotiatedBindingReceipt(
        1,
        "output-adapter",
        "1.0.0",
        {"deliver": (DigestString("request"), DigestString("receipt"))},
        frozenset(),
        ASTRBOT_OUTPUT_REVISION,
        NOW,
    )


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context, self.envelope = _context()
        self.actor = message_actor(self.envelope)
        self.scope = message_scope(self.envelope)
        draft = _composer().compose(
            self.context,
            _decision(self.context),
            _direct(self.context, text="你好，abcdef"),
        )
        rendered = _renderer().render(draft)
        self.final = await FinalResponseSafetyValidator(
            DeterministicRenderValidator(_revision("render-validator")),
            DefaultContentSafetyPolicy(clock=lambda: NOW),
            clock=lambda: NOW,
            id_factory=lambda: "safety-1",
        ).validate(
            draft,
            rendered,
            self.actor,
            self.scope,
            call=_call(),
        )
        self.policy = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                "authorization-v1",
                {"user": frozenset({"message.send"})},
                {
                    "user": {
                        "message.send": AuthorizationConstraint(
                            frozenset({"delivery"}),
                            frozenset({"*"}),
                        )
                    }
                },
                decision_ttl=timedelta(minutes=5),
            ),
            clock=lambda: NOW,
            id_factory=lambda: "send-authorization-1",
        )
        self.builder = DeliveryRequestBuilder(
            DeliveryRequestBuilderConfig(
                1,
                DeliveryConstraints(
                    1,
                    8,
                    5,
                    False,
                    frozenset(),
                    timedelta(minutes=10),
                ),
                _binding(),
            ),
            self.policy,
            clock=lambda: NOW,
        )

    async def _request(self):
        plan = self.builder.plan(
            run_id="run-1",
            response=self.final,
            actor=self.actor,
            scope=self.scope,
            reply_to=self.context.current_message_reference,
            policy_snapshot_id="policy-v1",
        )
        decision = await self.policy.decide(plan.authorization_request, call=_call())
        return self.builder.finalize(plan, decision), plan, decision

    async def test_builder_binds_authorization_and_utf8_part_plan(self) -> None:
        request, plan, _ = await self._request()

        self.assertEqual(
            request.authorization.request_digest,
            plan.authorization_request.request_digest,
        )
        self.assertGreater(len(request.part_intents), 1)
        self.assertTrue(
            all(
                part.text is not None and len(part.text.encode("utf-8")) <= 5
                for part in request.part_intents
            )
        )
        self.assertEqual(
            "".join(part.text or "" for part in request.part_intents),
            "你好，abcdef",
        )
        repeated = self.builder.plan(
            run_id="run-1",
            response=self.final,
            actor=self.actor,
            scope=self.scope,
            reply_to=self.context.current_message_reference,
            policy_snapshot_id="policy-v1",
        )
        self.assertEqual(repeated.intent, plan.intent)

    async def test_unissued_or_changed_authorization_is_rejected(self) -> None:
        _, plan, decision = await self._request()
        for forged in (
            replace(decision, decision_id="unissued"),
            replace(decision, metadata_digest=DigestString("forged")),
        ):
            with (
                self.subTest(forged=forged.decision_id),
                self.assertRaises(DududaError),
            ):
                self.builder.finalize(plan, forged)

    async def test_receipt_parts_are_bound_to_immutable_plan(self) -> None:
        request, _, _ = await self._request()
        intent = request.part_intents[0]
        receipt = DeliveryReceipt(
            1,
            request.delivery_id,
            request.run_id,
            request.request_digest,
            request.idempotency_key,
            request.attempt,
            request.adapter_binding.component_revision,
            DeliveryStatus.FAILED,
            (
                DeliveryPartReceipt(
                    1,
                    intent.part_id,
                    intent.content_digest,
                    DeliveryPartStatus.FAILED,
                    None,
                    "send_failed",
                ),
            ),
            NOW,
            "send_failed",
        )
        self.assertIs(
            validate_delivery_receipt_against_request(request, receipt), receipt
        )
        with self.assertRaises(DududaError):
            validate_delivery_receipt_against_request(
                request,
                replace(
                    receipt,
                    parts=(
                        replace(
                            receipt.parts[0],
                            content_digest=DigestString("forged"),
                        ),
                    ),
                ),
            )

    async def test_receipt_merge_is_monotonic_and_detects_regression(self) -> None:
        request, _, _ = await self._request()
        first, second, third = request.part_intents[:3]
        previous = DeliveryReceipt(
            1,
            request.delivery_id,
            request.run_id,
            request.request_digest,
            request.idempotency_key,
            request.attempt,
            request.adapter_binding.component_revision,
            DeliveryStatus.PARTIAL,
            (
                DeliveryPartReceipt(
                    1,
                    first.part_id,
                    first.content_digest,
                    DeliveryPartStatus.SUCCEEDED,
                    None,
                    None,
                ),
                DeliveryPartReceipt(
                    1,
                    second.part_id,
                    second.content_digest,
                    DeliveryPartStatus.UNKNOWN,
                    None,
                    "unknown",
                ),
            ),
            NOW,
            "partial",
        )
        current = DeliveryReceipt(
            1,
            request.delivery_id,
            request.run_id,
            request.request_digest,
            request.idempotency_key,
            request.attempt,
            request.adapter_binding.component_revision,
            DeliveryStatus.PARTIAL,
            (
                DeliveryPartReceipt(
                    1,
                    second.part_id,
                    second.content_digest,
                    DeliveryPartStatus.SUCCEEDED,
                    None,
                    None,
                ),
                DeliveryPartReceipt(
                    1,
                    third.part_id,
                    third.content_digest,
                    DeliveryPartStatus.UNKNOWN,
                    None,
                    "unknown",
                ),
            ),
            NOW + timedelta(seconds=1),
            "partial",
        )

        merged, conflict = _merge_delivery_receipts(request, previous, current)

        self.assertIsNone(conflict)
        self.assertIs(merged.status, DeliveryStatus.PARTIAL)
        self.assertIs(merged.parts[1].status, DeliveryPartStatus.SUCCEEDED)
        regression = DeliveryReceipt(
            1,
            request.delivery_id,
            request.run_id,
            request.request_digest,
            request.idempotency_key,
            request.attempt,
            request.adapter_binding.component_revision,
            DeliveryStatus.FAILED,
            (
                DeliveryPartReceipt(
                    1,
                    first.part_id,
                    first.content_digest,
                    DeliveryPartStatus.FAILED,
                    None,
                    "regressed",
                ),
            ),
            NOW + timedelta(seconds=2),
            "regressed",
        )
        unchanged, conflict = _merge_delivery_receipts(request, merged, regression)
        self.assertEqual(unchanged, merged)
        self.assertEqual(conflict, "delivery_part_status_regression")


if __name__ == "__main__":
    unittest.main()
