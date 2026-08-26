from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from astrbot_plugin_dududa_core.adapters.output import (
    ASTRBOT_OUTPUT_REVISION,
    AstrBotOutputAdapter,
    InMemoryDeliveryLedger,
)
from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.contracts.canonical import canonical_digest
from dududa.contracts.delivery import (
    delivery_authorization_metadata,
    delivery_authorization_resource,
    delivery_payload_digest,
    delivery_request_digest,
)
from dududa.domain.content import (
    ContentSafetyDecision,
    FinalResponse,
    GeneratedAssetRef,
    RenderedBlock,
    RenderedContent,
    RenderMetadata,
    RenderValidationResult,
    ResponseProfileValidationResult,
    SafetyStage,
    ValidatedFinalResponse,
)
from dududa.domain.delivery import (
    DeliveryConstraints,
    DeliveryPartStatus,
    DeliveryRequest,
    DeliveryStatus,
    plan_delivery_parts,
)
from dududa.domain.identity import (
    Actor,
    ActorRef,
    ConversationScope,
    ResolvedIdentityRef,
)
from dududa.domain.message import MessageReference
from dududa.domain.primitives import (
    ActionId,
    ComponentRevision,
    ConversationType,
    DigestString,
    Outcome,
    ResponseConstraints,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.security.digests import (
    actor_digest,
    authorization_metadata_digest,
    resource_digest,
    scope_digest,
)
from dududa.security.models import AuthorizationDecision, AuthorizationEffect


class FakeFactory:
    def plain(self, text: str):
        return ("plain", text)

    def at(self, user_id: str):
        return ("at", user_id)

    def reply(self, message_id: str):
        return ("reply", message_id)

    def node(self, text: str, *, name: str, uin: str):
        return ("node", name, uin, text)

    def nodes(self, nodes: list[object]):
        return ("nodes", tuple(nodes))

    def chain(self, components: list[object]):
        return tuple(components)


class FakeEvent:
    def __init__(
        self,
        *,
        fail_on_call: int | None = None,
        cancel: bool = False,
        group_id: str | None = "g-1",
    ) -> None:
        self.fail_on_call = fail_on_call
        self.cancel = cancel
        self.group_id = group_id
        self.sent: list[object] = []

    def get_platform_id(self):
        return "qq-adapter-1"

    def get_self_id(self):
        return "bot-1"

    def get_group_id(self):
        return self.group_id

    def get_sender_id(self):
        return "u-1"

    async def send(self, chain: object):
        self.sent.append(chain)
        if self.cancel:
            raise asyncio.CancelledError
        if self.fail_on_call == len(self.sent):
            raise RuntimeError("response lost")


class AstrBotOutputContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.scope = ConversationScope(
            "qq-adapter-1", "bot-1", ConversationType.GROUP, "g-1", "g-1", "dududa"
        )
        self.actor = Actor(
            "qq-adapter-1", "bot-1", "u-1", frozenset({RoleId("normal")}), frozenset()
        )
        self.revision = ComponentRevision("test", "1", "cfg", DigestString("artifact"))
        self.call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            self.now + timedelta(minutes=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 100, Decimal(0)),
            "policy-v1",
        )

    def response(
        self,
        text: str = "hello",
        *,
        scope: ConversationScope | None = None,
        target_users: tuple[ResolvedIdentityRef, ...] = (),
        attachments: tuple[GeneratedAssetRef, ...] = (),
        answer_profile: str | None = None,
    ) -> ValidatedFinalResponse:
        selected_scope = scope or self.scope
        draft_digest = DigestString("draft")
        response_plan_digest = (
            DigestString(f"plan-{answer_profile}")
            if answer_profile is not None
            else None
        )
        final = FinalResponse(
            1,
            "response-1",
            self.revision,
            (RenderedBlock("block-1", RenderedContent("text", text=text)),),
            (),
            (),
            (),
            (),
            None,
            ResponseConstraints(),
            target_users,
            attachments,
            RenderMetadata(
                "dududa",
                "1",
                self.revision,
                draft_digest,
                response_plan_digest,
            ),
        )
        rendered_digest = canonical_digest(final, domain="response:final:v1")
        validation = RenderValidationResult(
            1, True, draft_digest, rendered_digest, (), (), self.revision
        )
        safety = ContentSafetyDecision(
            1,
            "safety-1",
            SafetyStage.FINAL_OUTPUT,
            DigestString("safety-request"),
            rendered_digest,
            actor_digest(self.actor),
            scope_digest(selected_scope),
            True,
            ResponseConstraints(),
            (),
            "policy-v1",
            self.revision,
            self.now,
        )
        profile_validation = (
            ResponseProfileValidationResult(
                1,
                True,
                response_plan_digest,
                rendered_digest,
                answer_profile,
                len(text.split()),
                len(text),
                (),
                (),
                (),
                ("response_profile_validation_passed",),
                self.revision,
                self.revision,
            )
            if response_plan_digest is not None and answer_profile is not None
            else None
        )
        return ValidatedFinalResponse(
            1,
            final,
            validation,
            safety,
            profile_validation,
        )

    def request(
        self,
        *,
        text: str = "hello",
        delivery_id: str = "delivery-1",
        idempotency_key: str = "delivery-key-1",
        reply_to: MessageReference | None = None,
        allow_forward_bundle: bool = False,
        scope: ConversationScope | None = None,
        target_users: tuple[ResolvedIdentityRef, ...] = (),
        attachments: tuple[GeneratedAssetRef, ...] = (),
        answer_profile: str | None = None,
    ) -> DeliveryRequest:
        selected_scope = scope or self.scope
        response = self.response(
            text,
            scope=selected_scope,
            target_users=target_users,
            attachments=attachments,
            answer_profile=answer_profile,
        )
        authorization = AuthorizationDecision(
            1,
            "decision-1",
            AuthorizationEffect.ALLOW,
            DigestString("authorization-request"),
            actor_digest(self.actor),
            scope_digest(selected_scope),
            ActionId("message.send"),
            DigestString("pending-resource"),
            None,
            RiskLevel.LOW,
            DigestString("pending-metadata"),
            "policy-v1",
            (),
            self.now,
            self.now + timedelta(minutes=5),
        )
        binding = NegotiatedBindingReceipt(
            1,
            "output-adapter",
            "1.0.0",
            {"deliver": (DigestString("request"), DigestString("receipt"))},
            frozenset(),
            ASTRBOT_OUTPUT_REVISION,
            self.now,
        )
        constraints = DeliveryConstraints(
            1,
            4,
            5,
            allow_forward_bundle,
            frozenset(
                attachment.content_ref.partition(":")[0]
                for attachment in attachments
            ),
            timedelta(minutes=5),
        )
        payload_digest = delivery_payload_digest(response)
        request = DeliveryRequest(
            1,
            delivery_id,
            "run-1",
            DigestString("pending"),
            payload_digest,
            idempotency_key,
            1,
            Outcome.RESPONSE,
            response,
            None,
            selected_scope,
            reply_to,
            constraints,
            plan_delivery_parts(
                delivery_id,
                response,
                None,
                reply_to=reply_to,
                constraints=constraints,
                payload_digest=payload_digest,
            ),
            authorization,
            (),
            binding,
        )
        authorization = replace(
            authorization,
            resource_digest=resource_digest(delivery_authorization_resource(request)),
            metadata_digest=authorization_metadata_digest(
                delivery_authorization_metadata(
                    request,
                    policy_snapshot_id=self.call.policy_snapshot_id,
                )
            ),
        )
        request = replace(request, authorization=authorization)
        return replace(request, request_digest=delivery_request_digest(request))

    async def test_send_once_and_duplicate_returns_same_receipt(self) -> None:
        event = FakeEvent()
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        request = self.request(text="hello world")
        first = await adapter.deliver(request, call=self.call)
        duplicate = await adapter.deliver(request, call=self.call)
        self.assertEqual(first, duplicate)
        self.assertEqual(first.status, DeliveryStatus.SUCCEEDED)
        self.assertEqual(len(event.sent), 3)
        self.assertTrue(all(part.platform_message_ref is None for part in first.parts))

    async def test_forward_bundle_sends_all_parts_once(self) -> None:
        event = FakeEvent()
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )

        receipt = await adapter.deliver(
            self.request(
                text="hello world",
                allow_forward_bundle=True,
                answer_profile="long",
            ),
            call=self.call,
        )

        self.assertIs(receipt.status, DeliveryStatus.SUCCEEDED)
        self.assertTrue(
            all(part.status is DeliveryPartStatus.SUCCEEDED for part in receipt.parts)
        )
        self.assertEqual(len(event.sent), 1)
        self.assertEqual(event.sent[0][0][0], "nodes")
        self.assertEqual(len(event.sent[0][0][1]), len(receipt.parts))

    async def test_forward_bundle_requires_at_least_two_parts(self) -> None:
        event = FakeEvent()
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )

        receipt = await adapter.deliver(
            self.request(
                text="短",
                allow_forward_bundle=True,
                answer_profile="long",
            ),
            call=self.call,
        )

        self.assertIs(receipt.status, DeliveryStatus.SUCCEEDED)
        self.assertEqual(len(receipt.parts), 1)
        self.assertEqual(event.sent, [(('plain', '短'),)])

    async def test_forward_bundle_failure_marks_every_part_unknown(self) -> None:
        event = FakeEvent(fail_on_call=1)
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )

        receipt = await adapter.deliver(
            self.request(
                text="hello world",
                allow_forward_bundle=True,
                answer_profile="long",
            ),
            call=self.call,
        )

        self.assertIs(receipt.status, DeliveryStatus.UNKNOWN)
        self.assertTrue(
            all(part.status is DeliveryPartStatus.UNKNOWN for part in receipt.parts)
        )
        self.assertEqual(len(event.sent), 1)

    async def test_send_exception_is_unknown_and_is_not_retried(self) -> None:
        event = FakeEvent(fail_on_call=1)
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        request = self.request()
        receipt = await adapter.deliver(request, call=self.call)
        duplicate = await adapter.deliver(request, call=self.call)
        self.assertEqual(receipt.status, DeliveryStatus.UNKNOWN)
        self.assertEqual(receipt, duplicate)
        self.assertEqual(len(event.sent), 1)

    async def test_run_id_and_idempotency_key_conflicts_never_send(self) -> None:
        event = FakeEvent()
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        request = self.request()
        wrong_call = replace(self.call, run_id="other-run")
        with self.assertRaises(DududaError):
            await adapter.deliver(request, call=wrong_call)
        await adapter.deliver(request, call=self.call)
        conflict = self.request(delivery_id="delivery-2")
        with self.assertRaises(DududaError):
            await adapter.deliver(conflict, call=self.call)
        self.assertEqual(len(event.sent), 1)

    async def test_forward_bundle_is_not_blocked_by_direct_chat_reply(self) -> None:
        event = FakeEvent()
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        reply = MessageReference("qq-adapter-1", "bot-1", "g-1", "m-0")
        receipt = await adapter.deliver(
            self.request(
                text="hello world",
                reply_to=reply,
                allow_forward_bundle=True,
                answer_profile="long",
            ),
            call=self.call,
        )
        self.assertIs(receipt.status, DeliveryStatus.SUCCEEDED)
        self.assertEqual(len(event.sent), 1)
        self.assertEqual(event.sent[0][0][0], "nodes")

    async def test_forward_bundle_is_not_used_for_private_chat(self) -> None:
        event = FakeEvent(group_id=None)
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        private_scope = ConversationScope(
            "qq-adapter-1",
            "bot-1",
            ConversationType.PRIVATE,
            "private:u-1",
            None,
            "dududa",
        )

        receipt = await adapter.deliver(
            self.request(
                text="hello world",
                allow_forward_bundle=True,
                scope=private_scope,
                answer_profile="long",
            ),
            call=self.call,
        )

        self.assertIs(receipt.status, DeliveryStatus.SUCCEEDED)
        self.assertEqual(len(event.sent), 3)
        self.assertTrue(all(chain[0][0] != "nodes" for chain in event.sent))

    async def test_forward_bundle_supports_targeted_long_response(self) -> None:
        event = FakeEvent()
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        target = ResolvedIdentityRef(
            "identity-u-2",
            ActorRef("qq-adapter-1", "bot-1", "u-2"),
        )

        receipt = await adapter.deliver(
            self.request(
                text="hello world",
                allow_forward_bundle=True,
                target_users=(target,),
                answer_profile="long",
            ),
            call=self.call,
        )

        self.assertIs(receipt.status, DeliveryStatus.SUCCEEDED)
        self.assertEqual(len(event.sent), 1)
        self.assertEqual(event.sent[0][0][0], "nodes")
        self.assertEqual(len(event.sent[0][0][1]), len(receipt.parts))

    async def test_forward_bundle_is_not_used_for_response_with_attachment(
        self,
    ) -> None:
        event = FakeEvent()
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        attachment = GeneratedAssetRef(
            "asset-1",
            "asset:1",
            DigestString("asset-digest"),
            "image/png",
            Sensitivity.PUBLIC,
        )

        receipt = await adapter.deliver(
            self.request(
                text="hello world",
                allow_forward_bundle=True,
                attachments=(attachment,),
                answer_profile="long",
            ),
            call=self.call,
        )

        self.assertIs(receipt.status, DeliveryStatus.SUCCEEDED)
        self.assertEqual(len(event.sent), 3)
        self.assertTrue(all(chain[0][0] != "nodes" for chain in event.sent))

    async def test_forward_bundle_requires_validated_long_profile(self) -> None:
        for answer_profile in (None, "short", "medium"):
            with self.subTest(answer_profile=answer_profile):
                event = FakeEvent()
                adapter = AstrBotOutputAdapter(
                    event,
                    InMemoryDeliveryLedger(),
                    component_factory=FakeFactory(),
                    clock=lambda: self.now,
                )

                receipt = await adapter.deliver(
                    self.request(
                        text="hello world",
                        allow_forward_bundle=True,
                        answer_profile=answer_profile,
                    ),
                    call=self.call,
                )

                self.assertIs(receipt.status, DeliveryStatus.SUCCEEDED)
                self.assertEqual(len(event.sent), 3)
                self.assertTrue(
                    all(chain[0][0] != "nodes" for chain in event.sent)
                )

    async def test_cancellation_after_send_records_unknown_tombstone(self) -> None:
        event = FakeEvent(cancel=True)
        ledger = InMemoryDeliveryLedger()
        adapter = AstrBotOutputAdapter(
            event,
            ledger,
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        request = self.request()
        with self.assertRaises(asyncio.CancelledError):
            await adapter.deliver(request, call=self.call)
        event.cancel = False
        receipt = await adapter.deliver(request, call=self.call)
        self.assertEqual(receipt.status, DeliveryStatus.UNKNOWN)
        self.assertEqual(len(event.sent), 1)

    async def test_midstream_failure_is_partial_and_not_retried(self) -> None:
        event = FakeEvent(fail_on_call=2)
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        request = self.request(text="hello world")
        receipt = await adapter.deliver(request, call=self.call)
        duplicate = await adapter.deliver(request, call=self.call)
        self.assertEqual(receipt.status, DeliveryStatus.PARTIAL)
        self.assertEqual(receipt, duplicate)
        self.assertEqual(len(event.sent), 2)

    async def test_authorization_and_binding_are_bound_to_exact_payload(self) -> None:
        event = FakeEvent()
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        original = self.request()
        changed_response = self.response("changed")
        changed_payload_digest = delivery_payload_digest(changed_response)
        reused = replace(
            original,
            response=changed_response,
            payload_digest=changed_payload_digest,
            part_intents=plan_delivery_parts(
                original.delivery_id,
                changed_response,
                None,
                reply_to=original.reply_to,
                constraints=original.constraints,
                payload_digest=changed_payload_digest,
            ),
        )
        reused = replace(reused, request_digest=delivery_request_digest(reused))
        with self.assertRaises(DududaError):
            await adapter.deliver(reused, call=self.call)
        wrong_binding = replace(
            original.adapter_binding,
            component_revision=self.revision,
        )
        rebound = replace(original, adapter_binding=wrong_binding)
        rebound = replace(rebound, request_digest=delivery_request_digest(rebound))
        with self.assertRaises(DududaError):
            await adapter.deliver(rebound, call=self.call)
        self.assertEqual(event.sent, [])

    async def test_tamper_is_rejected_before_send(self) -> None:
        event = FakeEvent()
        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            clock=lambda: self.now,
        )
        with self.assertRaises(DududaError):
            await adapter.deliver(
                replace(self.request(), idempotency_key="changed"), call=self.call
            )
        self.assertEqual(event.sent, [])

    async def test_live_send_guard_runs_immediately_before_platform_send(self) -> None:
        event = FakeEvent()
        calls: list[tuple[str, int, int]] = []

        def deny(request: DeliveryRequest, part_number: int) -> str:
            calls.append((request.delivery_id, part_number, len(event.sent)))
            return "rollout_kill_switch_active"

        adapter = AstrBotOutputAdapter(
            event,
            InMemoryDeliveryLedger(),
            component_factory=FakeFactory(),
            send_guard=deny,
            clock=lambda: self.now,
        )

        receipt = await adapter.deliver(self.request(), call=self.call)

        self.assertEqual(calls, [("delivery-1", 1, 0)])
        self.assertEqual(event.sent, [])
        self.assertIs(receipt.status, DeliveryStatus.FAILED)
        self.assertEqual(receipt.error_code, "rollout_kill_switch_active")


if __name__ == "__main__":
    unittest.main()
