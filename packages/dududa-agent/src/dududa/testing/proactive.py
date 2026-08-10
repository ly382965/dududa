from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dududa.domain.content import ValidatedFinalResponse
from dududa.domain.delivery import (
    DeliveryPartReceipt,
    DeliveryPartStatus,
    DeliveryReceipt,
    DeliveryRequest,
    DeliveryStatus,
)
from dududa.domain.identity import Actor, ActorRef, ConversationScope
from dududa.domain.message import MessageReference
from dududa.domain.primitives import DigestString
from dududa.errors import validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.proactive.contracts import (
    ProactivePreviewMetadata,
    ProactivePreviewRequest,
    ProactiveSubscription,
    SubscriptionMutationDisposition,
    SubscriptionMutationReceipt,
    SubscriptionStatus,
)
from dududa.proactive.digest_contracts import DigestShadowMetadata


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta) -> None:
        self.value += delta


class MappingProactiveActorResolver:
    def __init__(self, values: dict[ActorRef, Actor]) -> None:
        self._values = dict(values)
        self.requests: list[tuple[ActorRef, ConversationScope]] = []

    async def resolve(
        self,
        reference: ActorRef,
        scope: ConversationScope,
        *,
        call: ServiceCallContext,
    ) -> Actor:
        self.requests.append((reference, scope))
        actor = self._values.get(reference)
        if actor is None:
            raise validation_error("proactive_actor_not_found")
        if actor.platform != scope.platform or actor.bot_id != scope.bot_id:
            raise validation_error("proactive_actor_scope_mismatch")
        return actor


class MappingProactiveSubscriptionStore:
    def __init__(self, values: tuple[ProactiveSubscription, ...]) -> None:
        subscriptions = {value.subscription_id: value for value in values}
        if len(subscriptions) != len(values) or any(
            not isinstance(value, ProactiveSubscription) for value in values
        ):
            raise validation_error("invalid_fake_proactive_subscriptions")
        self._values = subscriptions
        self.loads: list[str] = []

    async def publish(
        self,
        subscription: ProactiveSubscription,
        *,
        expected_revision: int | None,
        mutation_id: str,
        call: ServiceCallContext,
    ) -> SubscriptionMutationReceipt:
        if not isinstance(subscription, ProactiveSubscription):
            raise validation_error("invalid_fake_proactive_subscription")
        current = self._values.get(subscription.subscription_id)
        if current is None:
            if expected_revision is not None or subscription.revision != 1:
                raise validation_error("fake_subscription_create_conflict")
            previous = None
            disposition = SubscriptionMutationDisposition.CREATED
        else:
            if (
                expected_revision != current.revision
                or subscription.revision != current.revision + 1
            ):
                raise validation_error("fake_subscription_update_conflict")
            previous = current.revision
            disposition = SubscriptionMutationDisposition.UPDATED
        self._values[subscription.subscription_id] = subscription
        return SubscriptionMutationReceipt(
            1,
            mutation_id,
            subscription.subscription_id,
            previous,
            subscription.revision,
            subscription.subscription_digest,
            subscription.status,
            disposition,
            subscription.updated_at,
        )

    async def load(
        self,
        subscription_id: str,
        *,
        call: ServiceCallContext,
    ) -> ProactiveSubscription | None:
        self.loads.append(subscription_id)
        return self._values.get(subscription_id)

    async def list_active(
        self,
        *,
        call: ServiceCallContext,
    ) -> tuple[ProactiveSubscription, ...]:
        return tuple(
            sorted(
                (
                    value
                    for value in self._values.values()
                    if value.status is SubscriptionStatus.ACTIVE
                ),
                key=lambda value: value.subscription_id,
            )
        )


class RecordingDigestShadowMetadataSink:
    def __init__(self) -> None:
        self.records: list[DigestShadowMetadata] = []

    async def record(
        self,
        metadata: DigestShadowMetadata,
        *,
        call: ServiceCallContext,
    ) -> None:
        if not isinstance(metadata, DigestShadowMetadata):
            raise validation_error("invalid_digest_shadow_metadata")
        self.records.append(metadata)


class StaticProactivePreviewProducer:
    def __init__(
        self,
        response: ValidatedFinalResponse,
        *,
        source_batch_digest: DigestString | None = None,
    ) -> None:
        self._response = response
        self._source_batch_digest = source_batch_digest
        self.requests: list[ProactivePreviewRequest] = []

    async def build(
        self,
        request: ProactivePreviewRequest,
        *,
        call: ServiceCallContext,
    ) -> tuple[ValidatedFinalResponse, DigestString | None]:
        self.requests.append(request)
        return self._response, self._source_batch_digest


class RecordingProactivePreviewMetadataStore:
    def __init__(self) -> None:
        self.records: list[ProactivePreviewMetadata] = []

    async def record(
        self,
        metadata: ProactivePreviewMetadata,
        *,
        call: ServiceCallContext,
    ) -> None:
        if not isinstance(metadata, ProactivePreviewMetadata):
            raise validation_error("invalid_proactive_preview_metadata")
        self.records.append(metadata)


class RecordingFakeProactiveOutput:
    """Local Output fake; proactive policy/preview tests should leave calls empty."""

    def __init__(self) -> None:
        self.calls: list[DeliveryRequest] = []

    async def deliver(
        self,
        request: DeliveryRequest,
        *,
        call: PortCallContext,
    ) -> DeliveryReceipt:
        if not isinstance(request, DeliveryRequest):
            raise validation_error("invalid_fake_proactive_delivery_request")
        self.calls.append(request)
        parts = tuple(
            DeliveryPartReceipt(
                1,
                part.part_id,
                part.content_digest,
                DeliveryPartStatus.SUCCEEDED,
                MessageReference(
                    request.scope.platform,
                    request.scope.bot_id,
                    request.scope.conversation_id,
                    f"fake:{part.part_id}",
                ),
                None,
            )
            for part in request.part_intents
        )
        return DeliveryReceipt(
            1,
            request.delivery_id,
            request.run_id,
            request.request_digest,
            request.idempotency_key,
            request.attempt,
            request.adapter_binding.component_revision,
            DeliveryStatus.SUCCEEDED,
            parts,
            call.deadline,
        )


__all__ = [
    "MappingProactiveActorResolver",
    "MappingProactiveSubscriptionStore",
    "MutableClock",
    "RecordingDigestShadowMetadataSink",
    "RecordingFakeProactiveOutput",
    "RecordingProactivePreviewMetadataStore",
    "StaticProactivePreviewProducer",
]
