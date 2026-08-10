from __future__ import annotations

import asyncio
import unittest
from copy import copy
from dataclasses import replace
from datetime import timedelta

from dududa.domain.delivery import (
    DeliveryPartReceipt,
    DeliveryPartStatus,
    DeliveryReceipt,
    DeliveryStatus,
)
from dududa.domain.message import MessageReference
from dududa.domain.primitives import DigestString
from dududa.errors import DududaError, ErrorCategory, error
from dududa.runtime.contracts import DeliveryReconciliationAction
from dududa.runtime.state import RuntimePhase
from dududa.runtime.store import (
    InMemoryRuntimeStateStore,
    InMemoryRuntimeStateStoreConfig,
)

from tests.unit.models.helpers import NOW

from .helpers import revision
from .test_orchestrator import OrchestratorFixture


class _StoreProxy:
    def __init__(self, inner) -> None:
        self.inner = inner

    async def commit(self, request, *, call):
        return await self.inner.commit(request, call=call)

    async def load(self, run_id, *, call):
        return await self.inner.load(run_id, call=call)

    async def wait_for_revision(self, run_id, after_revision, *, call):
        return await self.inner.wait_for_revision(
            run_id,
            after_revision,
            call=call,
        )

    async def lookup_dedup(self, key, *, call):
        return await self.inner.lookup_dedup(key, call=call)

    async def delete(self, run_id, expected_revision, *, call):
        return await self.inner.delete(run_id, expected_revision, call=call)


class _LoadBarrierStore(_StoreProxy):
    def __init__(self, inner, phase: RuntimePhase) -> None:
        super().__init__(inner)
        self.phase = phase
        self.waiters = 0
        self.release = asyncio.Event()

    async def load(self, run_id, *, call):
        checkpoint = await self.inner.load(run_id, call=call)
        if (
            checkpoint is not None
            and checkpoint.state.phase is self.phase
            and self.waiters < 2
        ):
            self.waiters += 1
            if self.waiters == 2:
                self.release.set()
            await asyncio.wait_for(self.release.wait(), timeout=1)
        return checkpoint


class _FailingCommitStore(_StoreProxy):
    def __init__(self, inner, fail_on: int) -> None:
        super().__init__(inner)
        self.fail_on = fail_on
        self.calls = 0

    async def commit(self, request, *, call):
        self.calls += 1
        if self.calls == self.fail_on:
            raise error(
                "injected_delivery_commit_failure",
                ErrorCategory.INTERNAL,
                "request.failed",
            )
        return await self.inner.commit(request, call=call)


def _receipt(
    request,
    status: DeliveryStatus,
    *,
    acknowledged_at=NOW,
    platform_suffix: str = "delivery",
) -> DeliveryReceipt:
    parts = []
    for index, intent in enumerate(request.part_intents):
        if status is DeliveryStatus.SUCCEEDED:
            part_status = DeliveryPartStatus.SUCCEEDED
        elif status is DeliveryStatus.FAILED:
            part_status = DeliveryPartStatus.FAILED
        elif status is DeliveryStatus.UNKNOWN:
            part_status = DeliveryPartStatus.UNKNOWN
        else:
            part_status = (
                DeliveryPartStatus.SUCCEEDED
                if index == 0
                else DeliveryPartStatus.UNKNOWN
            )
        error_code = None
        platform_ref = None
        if part_status is DeliveryPartStatus.SUCCEEDED:
            platform_ref = MessageReference(
                request.scope.platform,
                request.scope.bot_id,
                request.scope.conversation_id,
                f"{platform_suffix}:{index}",
            )
        elif part_status is DeliveryPartStatus.FAILED:
            error_code = "delivery_part_failed"
        else:
            error_code = "delivery_part_unknown"
        parts.append(
            DeliveryPartReceipt(
                schema_version=1,
                part_id=intent.part_id,
                content_digest=intent.content_digest,
                status=part_status,
                platform_message_ref=platform_ref,
                error_code=error_code,
            )
        )
    return DeliveryReceipt(
        schema_version=1,
        delivery_id=request.delivery_id,
        run_id=request.run_id,
        delivery_request_digest=request.request_digest,
        idempotency_key=request.idempotency_key,
        attempt=request.attempt,
        adapter_revision=request.adapter_binding.component_revision,
        status=status,
        parts=tuple(parts),
        acknowledged_at=acknowledged_at,
        error_code=(None if status is DeliveryStatus.SUCCEEDED else status.value),
    )


class RuntimeDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def _ready(self):
        fixture = OrchestratorFixture(direct_output="x" * 600)
        request, call = fixture.start()
        result = await fixture.runtime.run(request, call=call)
        assert result.delivery_request is not None
        self.assertGreater(len(result.delivery_request.part_intents), 1)
        return fixture, call, result.delivery_request

    async def test_all_real_statuses_complete_and_exact_ack_is_idempotent(self) -> None:
        for status in (
            DeliveryStatus.SUCCEEDED,
            DeliveryStatus.PARTIAL,
            DeliveryStatus.FAILED,
            DeliveryStatus.UNKNOWN,
        ):
            with self.subTest(status=status):
                fixture, call, request = await self._ready()
                receipt = _receipt(request, status)

                completion = await fixture.runtime.acknowledge_delivery(
                    receipt,
                    call=call,
                )
                checkpoint = await fixture.store.load(call.run_id, call=call)
                assert checkpoint is not None
                revision_before_replay = checkpoint.revision
                replay = await fixture.runtime.acknowledge_delivery(
                    receipt,
                    call=call,
                )
                replayed = await fixture.store.load(call.run_id, call=call)

                self.assertIs(completion.delivery_status, status)
                self.assertEqual(replay, completion)
                assert replayed is not None
                self.assertEqual(replayed.revision, revision_before_replay)
                self.assertIs(replayed.state.phase, RuntimePhase.COMPLETED)
                self.assertEqual(replayed.state.delivery_receipt, receipt)

    async def test_unknown_and_failed_evidence_improves_to_succeeded(self) -> None:
        fixture, call, request = await self._ready()
        unknown = _receipt(request, DeliveryStatus.UNKNOWN)
        await fixture.runtime.acknowledge_delivery(unknown, call=call)

        fixture.clock.now = NOW + timedelta(seconds=1)
        failed = _receipt(
            request,
            DeliveryStatus.FAILED,
            acknowledged_at=fixture.clock.now,
        )
        failed_result = await fixture.runtime.reconcile_delivery(failed, call=call)
        self.assertIs(failed_result.action, DeliveryReconciliationAction.IMPROVED)
        self.assertIs(failed_result.current_status, DeliveryStatus.FAILED)

        fixture.clock.now = NOW + timedelta(seconds=2)
        succeeded = _receipt(
            request,
            DeliveryStatus.SUCCEEDED,
            acknowledged_at=fixture.clock.now,
        )
        success_result = await fixture.runtime.reconcile_delivery(succeeded, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(success_result.action, DeliveryReconciliationAction.IMPROVED)
        self.assertIs(success_result.current_status, DeliveryStatus.SUCCEEDED)
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.COMPLETED)
        self.assertIs(
            checkpoint.state.completion.delivery_status,
            DeliveryStatus.SUCCEEDED,
        )

    async def test_success_regression_and_platform_reference_change_conflict(
        self,
    ) -> None:
        fixture, call, request = await self._ready()
        succeeded = _receipt(request, DeliveryStatus.SUCCEEDED)
        await fixture.runtime.acknowledge_delivery(succeeded, call=call)

        fixture.clock.now = NOW + timedelta(seconds=1)
        failed = _receipt(
            request,
            DeliveryStatus.FAILED,
            acknowledged_at=fixture.clock.now,
        )
        regression = await fixture.runtime.reconcile_delivery(failed, call=call)
        changed_reference = _receipt(
            request,
            DeliveryStatus.SUCCEEDED,
            acknowledged_at=fixture.clock.now,
            platform_suffix="different",
        )
        reference_conflict = await fixture.runtime.reconcile_delivery(
            changed_reference,
            call=call,
        )

        self.assertIs(regression.action, DeliveryReconciliationAction.CONFLICT)
        self.assertIs(reference_conflict.action, DeliveryReconciliationAction.CONFLICT)
        checkpoint = await fixture.store.load(call.run_id, call=call)
        assert checkpoint is not None
        self.assertEqual(checkpoint.state.delivery_receipt, succeeded)

    async def test_expired_and_mismatched_reconciliation_do_not_change_state(
        self,
    ) -> None:
        fixture, call, request = await self._ready()
        unknown = _receipt(request, DeliveryStatus.UNKNOWN)
        await fixture.runtime.acknowledge_delivery(unknown, call=call)
        before = await fixture.store.load(call.run_id, call=call)
        assert before is not None

        forged_digest = replace(
            _receipt(request, DeliveryStatus.SUCCEEDED),
            parts=(
                replace(
                    _receipt(request, DeliveryStatus.SUCCEEDED).parts[0],
                    content_digest=DigestString("forged"),
                ),
                *_receipt(request, DeliveryStatus.SUCCEEDED).parts[1:],
            ),
        )
        conflict = await fixture.runtime.reconcile_delivery(forged_digest, call=call)
        self.assertIs(conflict.action, DeliveryReconciliationAction.CONFLICT)

        adapter_conflict = replace(
            _receipt(request, DeliveryStatus.SUCCEEDED),
            adapter_revision=revision("different-output-adapter"),
        )
        conflict = await fixture.runtime.reconcile_delivery(adapter_conflict, call=call)
        self.assertIs(conflict.action, DeliveryReconciliationAction.CONFLICT)

        fixture.clock.now = NOW + request.constraints.reconciliation_window
        expired_receipt = _receipt(
            request,
            DeliveryStatus.SUCCEEDED,
            acknowledged_at=fixture.clock.now,
        )
        expired = await fixture.runtime.reconcile_delivery(expired_receipt, call=call)
        after = await fixture.store.load(call.run_id, call=call)

        self.assertIs(expired.action, DeliveryReconciliationAction.EXPIRED)
        assert after is not None
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.state.delivery_receipt, unknown)

    async def test_completion_cannot_precede_acknowledgement(self) -> None:
        fixture, call, request = await self._ready()
        future = _receipt(
            request,
            DeliveryStatus.SUCCEEDED,
            acknowledged_at=NOW + timedelta(seconds=1),
        )

        with self.assertRaises(DududaError) as captured:
            await fixture.runtime.acknowledge_delivery(future, call=call)

        self.assertEqual(
            captured.exception.info.code,
            "delivery_completion_precedes_acknowledgement",
        )
        checkpoint = await fixture.store.load(call.run_id, call=call)
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.READY_TO_EMIT)

    async def test_concurrent_exact_ack_across_runtimes_reuses_one_completion(
        self,
    ) -> None:
        fixture, call, request = await self._ready()
        before = await fixture.store.load(call.run_id, call=call)
        assert before is not None
        barrier = _LoadBarrierStore(fixture.store, RuntimePhase.READY_TO_EMIT)
        primary = fixture.runtime
        peer = copy(primary)
        primary._store = barrier
        peer._store = barrier
        receipt = _receipt(request, DeliveryStatus.SUCCEEDED)

        first, second = await asyncio.gather(
            primary.acknowledge_delivery(receipt, call=call),
            peer.acknowledge_delivery(receipt, call=call),
        )

        after = await fixture.store.load(call.run_id, call=call)
        assert after is not None
        self.assertEqual(first, second)
        self.assertEqual(after.revision, before.revision + 3)
        self.assertIs(after.state.phase, RuntimePhase.COMPLETED)

    async def test_concurrent_reconciliation_keeps_strongest_evidence(self) -> None:
        fixture, call, request = await self._ready()
        await fixture.runtime.acknowledge_delivery(
            _receipt(request, DeliveryStatus.UNKNOWN),
            call=call,
        )
        fixture.clock.now = NOW + timedelta(seconds=1)
        barrier = _LoadBarrierStore(fixture.store, RuntimePhase.COMPLETED)
        primary = fixture.runtime
        peer = copy(primary)
        primary._store = barrier
        peer._store = barrier

        await asyncio.gather(
            primary.reconcile_delivery(
                _receipt(
                    request,
                    DeliveryStatus.FAILED,
                    acknowledged_at=fixture.clock.now,
                ),
                call=call,
            ),
            peer.reconcile_delivery(
                _receipt(
                    request,
                    DeliveryStatus.SUCCEEDED,
                    acknowledged_at=fixture.clock.now,
                ),
                call=call,
            ),
        )

        checkpoint = await fixture.store.load(call.run_id, call=call)
        assert checkpoint is not None
        self.assertIs(
            checkpoint.state.delivery_receipt.status,
            DeliveryStatus.SUCCEEDED,
        )
        self.assertIs(
            checkpoint.state.completion.delivery_status,
            DeliveryStatus.SUCCEEDED,
        )

    async def test_acknowledgement_resumes_after_each_intermediate_commit(self) -> None:
        for fail_on, expected_phase in (
            (2, RuntimePhase.DELIVERY_ACKNOWLEDGED),
            (3, RuntimePhase.MEMORY_EVALUATED),
        ):
            with self.subTest(fail_on=fail_on):
                fixture, call, request = await self._ready()
                receipt = _receipt(request, DeliveryStatus.SUCCEEDED)
                fixture.runtime._store = _FailingCommitStore(
                    fixture.store,
                    fail_on,
                )

                with self.assertRaises(DududaError) as captured:
                    await fixture.runtime.acknowledge_delivery(receipt, call=call)
                self.assertEqual(
                    captured.exception.info.code,
                    "injected_delivery_commit_failure",
                )
                interrupted = await fixture.store.load(call.run_id, call=call)
                assert interrupted is not None
                self.assertIs(interrupted.state.phase, expected_phase)

                fixture.runtime._store = fixture.store
                completion = await fixture.runtime.acknowledge_delivery(
                    receipt,
                    call=call,
                )
                self.assertIs(completion.delivery_status, DeliveryStatus.SUCCEEDED)
                completed = await fixture.store.load(call.run_id, call=call)
                assert completed is not None
                self.assertIs(completed.state.phase, RuntimePhase.COMPLETED)

    async def test_incomplete_failed_ack_is_canonical_unknown_until_completed(
        self,
    ) -> None:
        fixture, call, request = await self._ready()
        full_failed = _receipt(request, DeliveryStatus.FAILED)
        incomplete = replace(full_failed, parts=full_failed.parts[:1])

        completion = await fixture.runtime.acknowledge_delivery(
            incomplete,
            call=call,
        )
        replay = await fixture.runtime.acknowledge_delivery(incomplete, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)
        assert checkpoint is not None
        self.assertIs(completion.delivery_status, DeliveryStatus.UNKNOWN)
        self.assertEqual(replay, completion)
        self.assertEqual(
            len(checkpoint.state.delivery_receipt.parts),
            len(request.part_intents),
        )

        fixture.clock.now = NOW + timedelta(seconds=1)
        reconciled = await fixture.runtime.reconcile_delivery(
            _receipt(
                request,
                DeliveryStatus.FAILED,
                acknowledged_at=fixture.clock.now,
            ),
            call=call,
        )
        self.assertIs(reconciled.action, DeliveryReconciliationAction.IMPROVED)
        self.assertIs(reconciled.previous_status, DeliveryStatus.UNKNOWN)
        self.assertIs(reconciled.current_status, DeliveryStatus.FAILED)

    async def test_checkpoint_ttl_cannot_truncate_reconciliation_window(self) -> None:
        fixture = OrchestratorFixture()
        fixture.store = InMemoryRuntimeStateStore(
            InMemoryRuntimeStateStoreConfig(
                schema_version=1,
                checkpoint_ttl=timedelta(seconds=1),
                tombstone_ttl=timedelta(minutes=1),
                maximum_checkpoints=100,
                maximum_dedup_records=100,
                component_revision=revision("short-runtime-store"),
            ),
            clock=fixture.clock,
        )
        fixture.runtime._store = fixture.store
        request, call = fixture.start()
        result = await fixture.runtime.run(request, call=call)
        assert result.delivery_request is not None
        await fixture.runtime.acknowledge_delivery(
            _receipt(result.delivery_request, DeliveryStatus.UNKNOWN),
            call=call,
        )

        fixture.clock.now = NOW + timedelta(seconds=2)
        reconciled = await fixture.runtime.reconcile_delivery(
            _receipt(
                result.delivery_request,
                DeliveryStatus.SUCCEEDED,
                acknowledged_at=fixture.clock.now,
            ),
            call=call,
        )

        self.assertIs(reconciled.action, DeliveryReconciliationAction.IMPROVED)
        self.assertIs(reconciled.current_status, DeliveryStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
