from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from dududa.contracts.delivery import (
    delivery_authorization_metadata,
    delivery_authorization_resource,
    delivery_payload_digest,
    delivery_request_digest,
)
from dududa.domain.delivery import (
    DeliveryPartReceipt,
    DeliveryPartStatus,
    DeliveryReceipt,
    DeliveryRequest,
    DeliveryStatus,
)
from dududa.domain.primitives import ComponentRevision, DigestString, Outcome
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext
from dududa.security.digests import (
    authorization_metadata_digest,
    resource_digest,
    scope_digest,
)
from dududa.security.models import AuthorizationEffect


class ComponentFactory(Protocol):
    def plain(self, text: str) -> object: ...

    def at(self, user_id: str) -> object: ...

    def reply(self, message_id: str) -> object: ...

    def node(self, text: str, *, name: str, uin: str) -> object: ...

    def nodes(self, nodes: list[object]) -> object: ...

    def chain(self, components: list[object]) -> object: ...


class DeliverySendGuard(Protocol):
    def __call__(self, request: DeliveryRequest, part_number: int) -> str | None: ...


class _AstrBotComponentFactory:
    def __init__(self, event: object) -> None:
        from astrbot.api.message_components import At, Node, Nodes, Plain, Reply

        self._event = event
        self._at = At
        self._node = Node
        self._nodes = Nodes
        self._plain = Plain
        self._reply = Reply

    def plain(self, text: str) -> object:
        return self._plain(text)

    def at(self, user_id: str) -> object:
        return self._at(qq=user_id)

    def reply(self, message_id: str) -> object:
        return self._reply(id=message_id)

    def node(self, text: str, *, name: str, uin: str) -> object:
        return self._node(
            content=[self._plain(text)],
            name=name,
            uin=uin,
        )

    def nodes(self, nodes: list[object]) -> object:
        return self._nodes(nodes)

    def chain(self, components: list[object]) -> object:
        return self._event.chain_result(components)


class InMemoryDeliveryLedger:
    def __init__(self) -> None:
        self._receipts: dict[str, DeliveryReceipt] = {}
        self._idempotency: dict[str, str] = {}
        self.lock = asyncio.Lock()

    def get(self, delivery_id: str) -> DeliveryReceipt | None:
        return self._receipts.get(delivery_id)

    def get_by_idempotency_key(self, key: str) -> DeliveryReceipt | None:
        delivery_id = self._idempotency.get(key)
        return self._receipts.get(delivery_id) if delivery_id is not None else None

    def store(self, receipt: DeliveryReceipt) -> None:
        self._receipts[receipt.delivery_id] = receipt
        self._idempotency[receipt.idempotency_key] = receipt.delivery_id


ASTRBOT_OUTPUT_REVISION = ComponentRevision(
    "output.astrbot",
    "0.1.0",
    "s04-v1",
    DigestString("builtin"),
)


class AstrBotOutputAdapter:
    def __init__(
        self,
        event: object,
        ledger: InMemoryDeliveryLedger,
        *,
        component_factory: ComponentFactory | None = None,
        send_guard: DeliverySendGuard | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._event = event
        self._ledger = ledger
        self._factory = component_factory or _AstrBotComponentFactory(event)
        self._send_guard = send_guard
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._revision = ASTRBOT_OUTPUT_REVISION

    async def deliver(
        self,
        request: DeliveryRequest,
        *,
        call: PortCallContext,
    ) -> DeliveryReceipt:
        now = self._clock()
        self._validate_request(request, call)
        async with self._ledger.lock:
            by_id = self._ledger.get(request.delivery_id)
            by_key = self._ledger.get_by_idempotency_key(request.idempotency_key)
            duplicates = tuple(item for item in (by_id, by_key) if item is not None)
            if duplicates:
                duplicate = duplicates[0]
                if any(item != duplicate for item in duplicates) or (
                    duplicate.delivery_id != request.delivery_id
                    or duplicate.idempotency_key != request.idempotency_key
                    or duplicate.delivery_request_digest != request.request_digest
                ):
                    raise _output_error("delivery_idempotency_conflict")
                return duplicate
            if call.cancellation.is_cancelled or call.deadline <= now:
                raise _output_error("delivery_cancelled_or_expired")
            self._validate_fresh_authorization(request, now)
            receipt = await self._send(request, call, now)
            self._ledger.store(receipt)
            return receipt

    def _validate_request(
        self,
        request: DeliveryRequest,
        call: PortCallContext,
    ) -> None:
        if call.run_id != request.run_id:
            raise _output_error("delivery_run_mismatch")
        if delivery_request_digest(request) != request.request_digest:
            raise _output_error("delivery_request_digest_mismatch")
        payload = request.response if request.response is not None else request.reaction
        if (
            payload is None
            or delivery_payload_digest(payload) != request.payload_digest
        ):
            raise _output_error("delivery_payload_digest_mismatch")
        expected_scope = scope_digest(request.scope)
        authorization = request.authorization
        expected_metadata = delivery_authorization_metadata(
            request,
            policy_snapshot_id=call.policy_snapshot_id,
        )
        if (
            authorization.effect is not AuthorizationEffect.ALLOW
            or authorization.scope_digest != expected_scope
            or authorization.resource_digest
            != resource_digest(delivery_authorization_resource(request))
            or authorization.metadata_digest
            != authorization_metadata_digest(expected_metadata)
            or str(authorization.action) != "message.send"
        ):
            raise _output_error("delivery_not_authorized")
        if request.response is not None:
            safety = request.response.content_safety
            if (
                safety.actor_digest != authorization.actor_digest
                or safety.scope_digest != expected_scope
            ):
                raise _output_error("delivery_content_safety_binding_mismatch")
        binding = request.adapter_binding
        try:
            protocol_major = int(binding.protocol_version.split(".", 1)[0])
        except (TypeError, ValueError):
            raise _output_error("delivery_adapter_binding_mismatch") from None
        if (
            binding.port_id != "output-adapter"
            or protocol_major != 1
            or "deliver" not in binding.operation_schema_digests
            or binding.component_revision != self._revision
        ):
            raise _output_error("delivery_adapter_binding_mismatch")
        platform = _safe_call(self._event, "get_platform_id")
        bot_id = _safe_call(self._event, "get_self_id")
        group_id = _safe_call(self._event, "get_group_id")
        sender_id = _safe_call(self._event, "get_sender_id")
        conversation_id = group_id or f"private:{sender_id}"
        conversation_type = "group" if group_id else "private"
        if (platform, bot_id, conversation_type, conversation_id, group_id or None) != (
            request.scope.platform,
            request.scope.bot_id,
            request.scope.conversation_type.value,
            request.scope.conversation_id,
            request.scope.group_id,
        ):
            raise _output_error("delivery_event_scope_mismatch")
        if request.attachment_access:
            raise _output_error("delivery_attachments_not_enabled")

    def _validate_fresh_authorization(
        self,
        request: DeliveryRequest,
        now: datetime,
    ) -> None:
        authorization = request.authorization
        if authorization.decided_at > now or authorization.expires_at <= now:
            raise _output_error("delivery_not_authorized")
        if (
            request.response is not None
            and request.response.content_safety.decided_at > now
        ):
            raise _output_error("delivery_content_safety_binding_mismatch")

    async def _send(
        self,
        request: DeliveryRequest,
        call: PortCallContext,
        now: datetime,
    ) -> DeliveryReceipt:
        if request.outcome is Outcome.REACTION:
            intent = request.part_intents[0]
            part = DeliveryPartReceipt(
                1,
                intent.part_id,
                intent.content_digest,
                DeliveryPartStatus.FAILED,
                None,
                "reaction_not_supported",
            )
            return self._receipt(
                request, DeliveryStatus.FAILED, (part,), now, "reaction_not_supported"
            )
        if self._can_send_forward_bundle(request):
            return await self._send_forward_bundle(request, call)
        receipts: list[DeliveryPartReceipt] = []
        for index, intent in enumerate(request.part_intents, start=1):
            if intent.text is None:
                raise _output_error("delivery_response_part_missing_text")
            text = intent.text
            part_id = intent.part_id
            target_ids = (
                tuple(
                    target.actor_ref.opaque_actor_id
                    for target in request.response.response.target_users
                )
                if index == 1 and request.response is not None
                else ()
            )
            reply_to = request.reply_to if index == 1 else None
            digest = intent.content_digest
            if call.cancellation.is_cancelled or call.deadline <= self._clock():
                receipts.append(
                    DeliveryPartReceipt(
                        1,
                        part_id,
                        digest,
                        DeliveryPartStatus.FAILED,
                        None,
                        "delivery_cancelled_before_part",
                    )
                )
                status = (
                    DeliveryStatus.PARTIAL
                    if any(
                        item.status is DeliveryPartStatus.SUCCEEDED for item in receipts
                    )
                    else DeliveryStatus.FAILED
                )
                return self._receipt(
                    request,
                    status,
                    tuple(receipts),
                    self._clock(),
                    "delivery_cancelled_before_part",
                )
            send_started = False
            try:
                components: list[object] = []
                if reply_to is not None:
                    components.append(self._factory.reply(reply_to.message_id))
                for target_id in target_ids:
                    components.append(self._factory.at(target_id))
                components.append(self._factory.plain(text))
                chain = self._factory.chain(components)
                guard_reason = self._check_send_guard(request, index)
                if guard_reason is not None:
                    receipts.append(
                        DeliveryPartReceipt(
                            1,
                            part_id,
                            digest,
                            DeliveryPartStatus.FAILED,
                            None,
                            guard_reason,
                        )
                    )
                    status = (
                        DeliveryStatus.PARTIAL
                        if any(
                            item.status is DeliveryPartStatus.SUCCEEDED
                            for item in receipts
                        )
                        else DeliveryStatus.FAILED
                    )
                    return self._receipt(
                        request,
                        status,
                        tuple(receipts),
                        self._clock(),
                        guard_reason,
                    )
                send_started = True
                await self._event.send(chain)
            except asyncio.CancelledError:
                receipts.append(
                    DeliveryPartReceipt(
                        1,
                        part_id,
                        digest,
                        DeliveryPartStatus.UNKNOWN,
                        None,
                        "platform_send_outcome_unknown",
                    )
                )
                status = DeliveryStatus.PARTIAL if index > 1 else DeliveryStatus.UNKNOWN
                receipt = self._receipt(
                    request,
                    status,
                    tuple(receipts),
                    self._clock(),
                    "platform_send_outcome_unknown",
                )
                self._ledger.store(receipt)
                raise
            except Exception:  # noqa: BLE001 - normalize platform boundary failures
                part_status = (
                    DeliveryPartStatus.UNKNOWN
                    if send_started
                    else DeliveryPartStatus.FAILED
                )
                error_code = (
                    "platform_send_outcome_unknown"
                    if send_started
                    else "delivery_component_build_failed"
                )
                receipts.append(
                    DeliveryPartReceipt(
                        1,
                        part_id,
                        digest,
                        part_status,
                        None,
                        error_code,
                    )
                )
                if index > 1:
                    status = DeliveryStatus.PARTIAL
                elif part_status is DeliveryPartStatus.UNKNOWN:
                    status = DeliveryStatus.UNKNOWN
                else:
                    status = DeliveryStatus.FAILED
                return self._receipt(
                    request,
                    status,
                    tuple(receipts),
                    self._clock(),
                    error_code,
                )
            receipts.append(
                DeliveryPartReceipt(
                    1,
                    part_id,
                    digest,
                    DeliveryPartStatus.SUCCEEDED,
                    None,
                    None,
                )
            )
        return self._receipt(
            request,
            DeliveryStatus.SUCCEEDED,
            tuple(receipts),
            self._clock(),
            None,
        )

    def _can_send_forward_bundle(self, request: DeliveryRequest) -> bool:
        response = request.response
        profile_validation = (
            response.profile_validation if response is not None else None
        )
        return (
            request.constraints.allow_forward_bundle
            and request.scope.conversation_type.value == "group"
            and len(request.part_intents) >= 2
            and all(intent.text is not None for intent in request.part_intents)
            and response is not None
            and profile_validation is not None
            and profile_validation.valid
            and profile_validation.selected_profile == "long"
            and not response.response.target_users
            and not response.response.attachments
            and not request.attachment_access
        )

    async def _send_forward_bundle(
        self,
        request: DeliveryRequest,
        call: PortCallContext,
    ) -> DeliveryReceipt:
        def parts(
            status: DeliveryPartStatus,
            error_code: str | None,
        ) -> tuple[DeliveryPartReceipt, ...]:
            return tuple(
                DeliveryPartReceipt(
                    1,
                    intent.part_id,
                    intent.content_digest,
                    status,
                    None,
                    error_code,
                )
                for intent in request.part_intents
            )

        if call.cancellation.is_cancelled or call.deadline <= self._clock():
            error_code = "delivery_cancelled_before_part"
            return self._receipt(
                request,
                DeliveryStatus.FAILED,
                parts(DeliveryPartStatus.FAILED, error_code),
                self._clock(),
                error_code,
            )

        send_started = False
        try:
            bot_id = _safe_call(self._event, "get_self_id") or "0"
            nodes = [
                self._factory.node(intent.text or "", name=bot_id, uin=bot_id)
                for intent in request.part_intents
            ]
            chain = self._factory.chain([self._factory.nodes(nodes)])
            guard_reason = self._check_send_guard(request, 1)
            if guard_reason is not None:
                return self._receipt(
                    request,
                    DeliveryStatus.FAILED,
                    parts(DeliveryPartStatus.FAILED, guard_reason),
                    self._clock(),
                    guard_reason,
                )
            send_started = True
            await self._event.send(chain)
        except asyncio.CancelledError:
            error_code = "platform_send_outcome_unknown"
            receipt = self._receipt(
                request,
                DeliveryStatus.UNKNOWN,
                parts(DeliveryPartStatus.UNKNOWN, error_code),
                self._clock(),
                error_code,
            )
            self._ledger.store(receipt)
            raise
        except Exception:  # noqa: BLE001 - normalize platform boundary failures
            part_status = (
                DeliveryPartStatus.UNKNOWN
                if send_started
                else DeliveryPartStatus.FAILED
            )
            error_code = (
                "platform_send_outcome_unknown"
                if send_started
                else "delivery_component_build_failed"
            )
            status = DeliveryStatus.UNKNOWN if send_started else DeliveryStatus.FAILED
            return self._receipt(
                request,
                status,
                parts(part_status, error_code),
                self._clock(),
                error_code,
            )
        return self._receipt(
            request,
            DeliveryStatus.SUCCEEDED,
            parts(DeliveryPartStatus.SUCCEEDED, None),
            self._clock(),
            None,
        )

    def _check_send_guard(
        self,
        request: DeliveryRequest,
        part_number: int,
    ) -> str | None:
        if self._send_guard is None:
            return None
        try:
            reason = self._send_guard(request, part_number)
        except Exception:  # noqa: BLE001 - a failed gate must deny platform send
            return "delivery_send_guard_failed"
        if reason is None:
            return None
        if (
            not isinstance(reason, str)
            or not reason
            or len(reason) > 128
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789._:-"
                for character in reason
            )
        ):
            return "delivery_send_guard_failed"
        return reason

    def _receipt(
        self,
        request: DeliveryRequest,
        status: DeliveryStatus,
        parts: tuple[DeliveryPartReceipt, ...],
        acknowledged_at: datetime,
        error_code: str | None,
    ) -> DeliveryReceipt:
        return DeliveryReceipt(
            1,
            request.delivery_id,
            request.run_id,
            request.request_digest,
            request.idempotency_key,
            request.attempt,
            self._revision,
            status,
            parts,
            acknowledged_at,
            error_code,
        )


def _safe_call(value: object, name: str) -> str:
    try:
        return str(getattr(value, name)() or "").strip()
    except Exception:  # noqa: BLE001 - platform accessors are untrusted callbacks
        return ""


def _output_error(code: str):
    return error(code, ErrorCategory.VALIDATION, "delivery.rejected")
