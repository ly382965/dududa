from __future__ import annotations

from typing import Protocol, runtime_checkable

from dududa.domain.delivery import DeliveryReceipt
from dududa.domain.primitives import DigestString

from .contracts import (
    RolloutClaimResult,
    RolloutOwnershipRecord,
    RolloutOwnershipState,
)
from .metrics import (
    RolloutMetricObservation,
    RolloutMetricSummary,
)


@runtime_checkable
class RolloutOwnershipLedger(Protocol):
    def claim(
        self,
        message_key_digest: DigestString,
        invocation_digest: DigestString,
        control_revision: str,
    ) -> RolloutClaimResult: ...

    def load(
        self, message_key_digest: DigestString
    ) -> RolloutOwnershipRecord | None: ...

    def mark_runtime_started(
        self, message_key_digest: DigestString, expected_revision: int
    ) -> RolloutOwnershipRecord: ...

    def mark_ready_to_send(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        delivery_id: str,
        delivery_request_digest: DigestString,
    ) -> RolloutOwnershipRecord: ...

    def begin_delivery(
        self,
        message_key_digest: DigestString,
        delivery_id: str,
        delivery_request_digest: DigestString,
    ) -> RolloutOwnershipRecord: ...

    def finish_delivery(
        self, message_key_digest: DigestString, receipt: DeliveryReceipt
    ) -> RolloutOwnershipRecord: ...

    def mark_no_delivery(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        reason_code: str,
    ) -> RolloutOwnershipRecord: ...

    def mark_suppressed(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        reason_code: str,
    ) -> RolloutOwnershipRecord: ...

    def mark_aborted(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        expected_state: RolloutOwnershipState,
        reason_code: str,
    ) -> RolloutOwnershipRecord: ...

    def mark_send_unknown(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        reason_code: str,
    ) -> RolloutOwnershipRecord: ...


@runtime_checkable
class RolloutMetricSink(Protocol):
    def record(self, observation: RolloutMetricObservation) -> None: ...


@runtime_checkable
class RolloutSummaryReader(Protocol):
    def summary(self) -> RolloutMetricSummary: ...
