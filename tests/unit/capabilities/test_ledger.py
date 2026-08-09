from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.capabilities import (
    InMemoryToolInvocationLedger,
    ProviderRef,
    ToolError,
    ToolExecutionStatus,
    ToolInvocationClaimRequest,
    ToolInvocationDisposition,
    ToolObservation,
    tool_invocation_claim_request_digest,
    tool_observation_digest,
)
from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import (
    ComponentRevision,
    PrivacyLevel,
    ResourceUsage,
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError, ErrorCategory, ErrorInfo
from dududa.ports.capabilities import ToolInvocationLedger
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
)

NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return str(self.value)


def _call(
    *,
    cancellation=None,
    deadline: datetime = NOW + timedelta(minutes=1),
) -> PortCallContext:
    return PortCallContext(
        run_id="run-v1",
        trace=TraceContext("trace-v1"),
        deadline=deadline,
        cancellation=cancellation or NeverCancelled(),
        budget=RuntimeBudget(0, 8, 8, 0, 0, Decimal(100)),
        policy_snapshot_id="policy-v1",
    )


def _request(
    execution: str,
    *,
    key: str = "tool-key-v1",
    expires_at: datetime = NOW + timedelta(seconds=30),
) -> ToolInvocationClaimRequest:
    values = {
        "schema_version": 1,
        "idempotency_key": key,
        "execution_request_digest": canonical_digest(
            {"execution": execution},
            domain="fixture.tool-execution:v1",
        ),
        "expires_at": expires_at,
    }
    return ToolInvocationClaimRequest(
        request_digest=tool_invocation_claim_request_digest(values),
        **values,
    )


def _provider() -> ProviderRef:
    revision = ComponentRevision(
        "fixture.provider",
        "1.0.0",
        "config-v1",
        canonical_digest({}, domain="fixture.provider-revision:v1"),
    )
    return ProviderRef("fixture.provider", revision)


def _observation(
    status: ToolExecutionStatus,
    *,
    key: str = "tool-key-v1",
    invocation_id: str = "invocation-v1",
    retryable: bool | None = None,
) -> ToolObservation:
    unknown = status is ToolExecutionStatus.UNKNOWN
    failure = None
    data = {"items": [{"text": "untrusted provider text"}]}
    if status is not ToolExecutionStatus.SUCCEEDED:
        data = None
        failure = ToolError(
            1,
            ErrorInfo(
                1,
                "provider_outcome_unknown" if unknown else "provider_failed",
                ErrorCategory.EXTERNAL,
                retryable=(not unknown if retryable is None else retryable),
                outcome_unknown=unknown,
                public_message_key="service.unavailable",
                reason_codes=("provider_failure",),
            ),
            None,
            {},
        )
    values = {
        "schema_version": 1,
        "provider_result_digest": canonical_digest(
            {"invocation_id": invocation_id, "status": status},
            domain="fixture.provider-result:v1",
        ),
        "invocation_id": invocation_id,
        "plan_id": "plan-v1",
        "plan_digest": canonical_digest({}, domain="fixture.plan:v1"),
        "step_id": "step-v1",
        "logical_operation_id": "operation-v1",
        "capability_id": "fixture.read.v1",
        "definition_digest": canonical_digest({}, domain="fixture.definition:v1"),
        "catalog_snapshot_id": "catalog-v1",
        "catalog_digest": canonical_digest({}, domain="fixture.catalog:v1"),
        "provider": _provider(),
        "mapping_digest": None,
        "policy_revision": "policy-v1",
        "idempotency_key": key,
        "attempt": 1,
        "status": status,
        "data": data,
        "error": failure,
        "source_refs": (),
        "observed_at": NOW,
        "latency_ms": 1,
        "cache_status": None,
        "sensitivity": PrivacyLevel.PUBLIC,
        "usage": ResourceUsage(1, tool_steps=1, cost_units=Decimal(1)),
        "truncated": False,
        "untrusted": True,
    }
    return ToolObservation(
        observation_digest=tool_observation_digest(values),
        **values,
    )


class ToolInvocationLedgerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.ledger = InMemoryToolInvocationLedger(
            clock=self.clock,
            id_factory=_Ids(),
            maximum_records=4,
            maximum_history=32,
        )
        self.assertIsInstance(self.ledger, ToolInvocationLedger)

    async def test_concurrent_duplicates_are_single_flight_and_share_receipt(
        self,
    ) -> None:
        request = _request("attempt-1")
        claims = await asyncio.gather(
            *(self.ledger.acquire(request, call=_call()) for _ in range(8))
        )
        owners = [
            item
            for item in claims
            if item.disposition is ToolInvocationDisposition.ACQUIRED
        ]
        self.assertEqual(len(owners), 1)
        self.assertEqual(
            sum(
                item.disposition is ToolInvocationDisposition.DUPLICATE_PENDING
                for item in claims
            ),
            7,
        )

        waiters = [
            asyncio.create_task(self.ledger.wait(item, call=_call()))
            for item in claims
            if item is not owners[0]
        ]
        await asyncio.sleep(0)
        receipt = await self.ledger.complete(
            owners[0],
            _observation(ToolExecutionStatus.SUCCEEDED),
            call=_call(),
        )
        self.assertEqual(await asyncio.gather(*waiters), [receipt] * 7)

    async def test_pending_conflict_never_waits_or_replays(self) -> None:
        owner = await self.ledger.acquire(_request("attempt-1"), call=_call())
        conflict = await self.ledger.acquire(_request("changed"), call=_call())
        self.assertIs(owner.disposition, ToolInvocationDisposition.ACQUIRED)
        self.assertIs(conflict.disposition, ToolInvocationDisposition.CONFLICT)
        self.assertIsNone(await self.ledger.wait(conflict, call=_call()))

    async def test_success_and_unknown_are_terminal_for_business_key(self) -> None:
        first = await self.ledger.acquire(_request("attempt-1"), call=_call())
        succeeded = await self.ledger.complete(
            first,
            _observation(ToolExecutionStatus.SUCCEEDED),
            call=_call(),
        )
        replay = await self.ledger.acquire(_request("attempt-2"), call=_call())
        self.assertIs(
            replay.disposition,
            ToolInvocationDisposition.DUPLICATE_COMPLETED,
        )
        self.assertEqual(await self.ledger.wait(replay, call=_call()), succeeded)

        other = await self.ledger.acquire(
            _request("attempt-1", key="tool-key-v2"),
            call=_call(),
        )
        unknown = await self.ledger.complete(
            other,
            _observation(
                ToolExecutionStatus.UNKNOWN,
                key="tool-key-v2",
                invocation_id="invocation-v2",
            ),
            call=_call(),
        )
        blocked = await self.ledger.acquire(
            _request("attempt-2", key="tool-key-v2"),
            call=_call(),
        )
        self.assertIs(
            blocked.disposition,
            ToolInvocationDisposition.DUPLICATE_COMPLETED,
        )
        self.assertEqual(await self.ledger.wait(blocked, call=_call()), unknown)

    async def test_explicit_failure_allows_new_attempt_but_not_exact_replay(
        self,
    ) -> None:
        first = await self.ledger.acquire(_request("attempt-1"), call=_call())
        failed = await self.ledger.complete(
            first,
            _observation(ToolExecutionStatus.FAILED),
            call=_call(),
        )
        exact = await self.ledger.acquire(_request("attempt-1"), call=_call())
        self.assertIs(
            exact.disposition,
            ToolInvocationDisposition.DUPLICATE_COMPLETED,
        )
        self.assertEqual(await self.ledger.wait(exact, call=_call()), failed)

        retry = await self.ledger.acquire(_request("attempt-2"), call=_call())
        self.assertIs(retry.disposition, ToolInvocationDisposition.ACQUIRED)
        self.assertEqual(
            await self.ledger.wait(exact, call=_call()),
            failed,
            "a waiter for the prior attempt must retain its terminal evidence",
        )
        await self.ledger.complete(
            retry,
            _observation(
                ToolExecutionStatus.FAILED,
                invocation_id="invocation-v2",
            ),
            call=_call(),
        )
        late = await self.ledger.acquire(_request("attempt-1"), call=_call())
        self.assertIs(
            late.disposition,
            ToolInvocationDisposition.DUPLICATE_COMPLETED,
        )
        self.assertEqual(await self.ledger.wait(late, call=_call()), failed)

    async def test_nonretryable_failure_and_attempt_ceiling_do_not_reopen(self) -> None:
        key = "tool-key-v2"
        owner = await self.ledger.acquire(
            _request("attempt-1", key=key),
            call=_call(),
        )
        terminal = await self.ledger.complete(
            owner,
            _observation(
                ToolExecutionStatus.FAILED,
                key=key,
                invocation_id="nonretryable",
                retryable=False,
            ),
            call=_call(),
        )
        blocked = await self.ledger.acquire(
            _request("attempt-2", key=key),
            call=_call(),
        )
        self.assertIs(
            blocked.disposition,
            ToolInvocationDisposition.DUPLICATE_COMPLETED,
        )
        self.assertEqual(await self.ledger.wait(blocked, call=_call()), terminal)

        previous = await self.ledger.acquire(_request("attempt-1"), call=_call())
        for attempt in range(1, 9):
            if attempt > 1:
                previous = await self.ledger.acquire(
                    _request(f"attempt-{attempt}"),
                    call=_call(),
                )
            self.assertIs(previous.disposition, ToolInvocationDisposition.ACQUIRED)
            await self.ledger.complete(
                previous,
                _observation(
                    ToolExecutionStatus.FAILED,
                    invocation_id=f"invocation-{attempt}",
                ),
                call=_call(),
            )
        ceiling = await self.ledger.acquire(_request("attempt-9"), call=_call())
        self.assertIs(
            ceiling.disposition,
            ToolInvocationDisposition.DUPLICATE_COMPLETED,
        )

    async def test_wait_honours_claim_expiry_and_cancellation(self) -> None:
        live_now = datetime.now(timezone.utc)
        live_ledger = InMemoryToolInvocationLedger(
            clock=lambda: datetime.now(timezone.utc),
            id_factory=_Ids(),
        )
        expiring = await live_ledger.acquire(
            _request(
                "short",
                expires_at=live_now + timedelta(milliseconds=20),
            ),
            call=_call(deadline=live_now + timedelta(seconds=1)),
        )
        self.assertIsNone(
            await live_ledger.wait(
                expiring,
                call=_call(deadline=live_now + timedelta(seconds=1)),
            )
        )

        cancellation = ManualCancellationToken()
        claim = await self.ledger.acquire(
            _request("cancel", key="tool-key-v2"),
            call=_call(cancellation=cancellation),
        )
        waiting = asyncio.create_task(
            self.ledger.wait(claim, call=_call(cancellation=cancellation))
        )
        await asyncio.sleep(0)
        cancellation.cancel()
        with self.assertRaises(DududaError) as caught:
            await waiting
        self.assertIs(caught.exception.info.category, ErrorCategory.CANCELLED)

        deadline_ledger = InMemoryToolInvocationLedger(
            clock=lambda: datetime.now(timezone.utc),
            id_factory=_Ids(),
        )
        deadline_now = datetime.now(timezone.utc)
        deadline_claim = await deadline_ledger.acquire(
            _request(
                "deadline",
                expires_at=deadline_now + timedelta(seconds=1),
            ),
            call=_call(deadline=deadline_now + timedelta(seconds=1)),
        )
        with self.assertRaises(DududaError) as deadline_error:
            await deadline_ledger.wait(
                deadline_claim,
                call=_call(
                    deadline=datetime.now(timezone.utc) + timedelta(milliseconds=20)
                ),
            )
        self.assertIs(deadline_error.exception.info.category, ErrorCategory.TIMEOUT)

    async def test_native_task_cancellation_does_not_corrupt_owner(self) -> None:
        claim = await self.ledger.acquire(_request("attempt-1"), call=_call())
        waiting = asyncio.create_task(self.ledger.wait(claim, call=_call()))
        await asyncio.sleep(0)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        receipt = await self.ledger.complete(
            claim,
            _observation(ToolExecutionStatus.SUCCEEDED),
            call=_call(),
        )
        replay = await self.ledger.acquire(_request("attempt-1"), call=_call())
        self.assertEqual(await self.ledger.wait(replay, call=_call()), receipt)

    async def test_claim_cannot_outlive_call_deadline(self) -> None:
        with self.assertRaises(DududaError) as caught:
            await self.ledger.acquire(
                _request("attempt-1", expires_at=NOW + timedelta(minutes=2)),
                call=_call(deadline=NOW + timedelta(minutes=1)),
            )
        self.assertEqual(
            caught.exception.info.code,
            "tool_invocation_claim_exceeds_call_deadline",
        )

    async def test_completion_is_durable_after_caller_cancellation(self) -> None:
        cancellation = ManualCancellationToken()
        claim = await self.ledger.acquire(
            _request("attempt-1"),
            call=_call(cancellation=cancellation),
        )
        cancellation.cancel()
        receipt = await self.ledger.complete(
            claim,
            _observation(ToolExecutionStatus.UNKNOWN),
            call=_call(cancellation=cancellation),
        )
        self.assertIs(receipt.observation.status, ToolExecutionStatus.UNKNOWN)

    async def test_capacity_never_evicts_pending_ownership(self) -> None:
        ledger = InMemoryToolInvocationLedger(
            maximum_records=1,
            maximum_history=8,
            clock=self.clock,
            id_factory=_Ids(),
        )
        await ledger.acquire(_request("first"), call=_call())
        with self.assertRaises(DududaError) as caught:
            await ledger.acquire(
                _request("second", key="tool-key-v2"),
                call=_call(),
            )
        self.assertIs(caught.exception.info.category, ErrorCategory.BUDGET)

    async def test_expired_terminal_retention_reclaims_capacity(self) -> None:
        ledger = InMemoryToolInvocationLedger(
            maximum_records=1,
            maximum_history=8,
            terminal_retention=timedelta(seconds=10),
            clock=self.clock,
            id_factory=_Ids(),
        )
        claim = await ledger.acquire(_request("first"), call=_call())
        await ledger.complete(
            claim,
            _observation(ToolExecutionStatus.SUCCEEDED),
            call=_call(),
        )
        self.clock.now = NOW + timedelta(seconds=31)
        replacement = await ledger.acquire(
            _request(
                "second",
                key="tool-key-v2",
                expires_at=self.clock.now + timedelta(seconds=10),
            ),
            call=_call(deadline=self.clock.now + timedelta(seconds=20)),
        )
        self.assertIs(replacement.disposition, ToolInvocationDisposition.ACQUIRED)

    async def test_claim_and_completion_conflicts_fail_closed(self) -> None:
        claim = await self.ledger.acquire(_request("attempt-1"), call=_call())
        duplicate = await self.ledger.acquire(_request("attempt-1"), call=_call())
        with self.assertRaises(DududaError):
            await self.ledger.complete(
                duplicate,
                _observation(ToolExecutionStatus.SUCCEEDED),
                call=_call(),
            )
        with self.assertRaises(DududaError):
            await self.ledger.complete(
                claim,
                _observation(ToolExecutionStatus.SUCCEEDED, key="wrong-key"),
                call=_call(),
            )

    async def test_callback_failures_are_sanitized(self) -> None:
        def fail() -> str:
            raise RuntimeError("credential=/private/value")

        ledger = InMemoryToolInvocationLedger(clock=self.clock, id_factory=fail)
        with self.assertRaises(DududaError) as caught:
            await ledger.acquire(_request("attempt-1"), call=_call())
        self.assertEqual(
            caught.exception.info.code, "tool_invocation_ledger_id_unavailable"
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
