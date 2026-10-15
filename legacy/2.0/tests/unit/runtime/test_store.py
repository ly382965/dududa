from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import Mention, MessageEnvelope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    PrivacyLevel,
    ResourceUsage,
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError, ErrorCategory
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
)
from dududa.ports.runtime import RuntimeStateStore
from dududa.runtime.budget import RuntimeModelBudgetPlan, zero_usage_for_budget
from dududa.runtime.contracts import (
    OfflinePreprocessReceipt,
    RuntimeAdmissionAction,
)
from dududa.runtime.state import (
    ConnectorResult,
    RuntimeCommitDisposition,
    RuntimeCommitRequest,
    RuntimeInvocationOptions,
    RuntimePhase,
    RuntimeState,
    runtime_start_digest,
    transition,
)
from dududa.runtime.store import (
    InMemoryRuntimeStateStore,
    InMemoryRuntimeStateStoreConfig,
)
from dududa.security.digests import actor_digest

from .helpers import runtime_policy

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def _revision(name: str, config: str = "cfg-v1") -> ComponentRevision:
    return ComponentRevision(
        name,
        "1.0.0",
        config,
        DigestString(f"artifact:{name}:{config}"),
    )


def _state(
    *,
    run_id: str = "run-1",
    message_id: str = "message-1",
    entrypoint_id: str = "astrbot",
) -> RuntimeState:
    message = MessageEnvelope(
        schema_version=1,
        message_id=message_id,
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
    actor = Actor("qq", "bot-1", "user-1", frozenset())
    connector_revision = _revision("connector")
    options = RuntimeInvocationOptions(1, None, entrypoint_id, {}, "flags-v1")
    connector = ConnectorResult(1, message, actor, NOW, connector_revision)
    initial_budget = RuntimeBudget(2, 0, 0, 300, 120, Decimal(3))
    plan = RuntimeModelBudgetPlan(
        1,
        ResourceUsage(1, 1, 0, 0, 100, 40, Decimal(1)),
        ResourceUsage(1, 1, 0, 0, 200, 80, Decimal(2)),
        _revision("runtime-budget"),
    )
    return RuntimeState(
        schema_version=1,
        run_id=run_id,
        phase=RuntimePhase.RECEIVED,
        message=message,
        actor=actor,
        received_at=NOW,
        connector_revision=connector_revision,
        invocation_options=options,
        start_digest=runtime_start_digest(connector, options),
        conversation_scope=ConversationScope(
            "qq",
            "bot-1",
            ConversationType.GROUP,
            "group-1",
            "group-1",
            "dududa",
        ),
        initial_budget=initial_budget,
        model_budget_plan=plan,
        budget=initial_budget,
        charged_usage=zero_usage_for_budget(initial_budget),
        trace_context=TraceContext(f"trace:{run_id}"),
        policy_snapshot_id="policy-v1",
        runtime_policy=runtime_policy(),
    )


def _preprocessed(
    state: RuntimeState,
    *,
    config: str = "cfg-v1",
) -> RuntimeState:
    receipt = OfflinePreprocessReceipt(
        schema_version=1,
        message_digest=canonical_digest(
            state.message,
            domain="runtime:admission-message:v1",
        ),
        actor_digest=actor_digest(state.actor),
        action=RuntimeAdmissionAction.PROCEED,
        data_classification=PrivacyLevel.CONVERSATION,
        explicit_interaction=True,
        reason_codes=("s10_text_admitted",),
        component_revision=_revision("preprocess", config),
    )
    return transition(
        state,
        RuntimePhase.PREPROCESSED,
        preprocess_result=receipt,
    )


def _call(
    run_id: str,
    *,
    cancellation=None,
    now: datetime = NOW,
) -> PortCallContext:
    return PortCallContext(
        run_id,
        TraceContext(f"trace:{run_id}"),
        now + timedelta(hours=1),
        cancellation or NeverCancelled(),
        RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
        "policy-v1",
    )


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _store(
    *,
    clock=None,
    maximum_checkpoints: int = 16,
    maximum_dedup_records: int = 16,
) -> InMemoryRuntimeStateStore:
    return InMemoryRuntimeStateStore(
        InMemoryRuntimeStateStoreConfig(
            1,
            timedelta(seconds=10),
            timedelta(seconds=20),
            maximum_checkpoints,
            maximum_dedup_records,
            _revision("runtime-store"),
        ),
        clock=clock or (lambda: NOW),
    )


class InMemoryRuntimeStateStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_update_and_exact_commit_replay(self) -> None:
        store = _store()
        state = _state()
        create = RuntimeCommitRequest(1, "run-1", state.message.dedup_key, None, state)

        created = await store.commit(create, call=_call("run-1"))
        duplicate = await store.commit(create, call=_call("run-1"))
        updated_state = _preprocessed(state)
        update = RuntimeCommitRequest(
            1,
            "run-1",
            state.message.dedup_key,
            1,
            updated_state,
        )
        updated = await store.commit(update, call=_call("run-1"))
        replay = await store.commit(update, call=_call("run-1"))

        self.assertIsInstance(store, RuntimeStateStore)
        self.assertIs(created.disposition, RuntimeCommitDisposition.CREATED)
        self.assertIs(duplicate.disposition, RuntimeCommitDisposition.DUPLICATE)
        self.assertIs(updated.disposition, RuntimeCommitDisposition.UPDATED)
        self.assertEqual(updated.checkpoint.revision, 2)  # type: ignore[union-attr]
        self.assertIs(replay.disposition, RuntimeCommitDisposition.DUPLICATE)

    async def test_concurrent_create_has_one_owner(self) -> None:
        store = _store()
        state = _state()
        request = RuntimeCommitRequest(1, "run-1", state.message.dedup_key, None, state)

        results = await asyncio.gather(
            *(store.commit(request, call=_call("run-1")) for _ in range(50))
        )

        self.assertEqual(
            sum(
                result.disposition is RuntimeCommitDisposition.CREATED
                for result in results
            ),
            1,
        )
        self.assertEqual(
            sum(
                result.disposition is RuntimeCommitDisposition.DUPLICATE
                for result in results
            ),
            49,
        )

    async def test_same_key_changed_start_and_same_run_changed_key_conflict(
        self,
    ) -> None:
        store = _store()
        state = _state()
        await store.commit(
            RuntimeCommitRequest(1, "run-1", state.message.dedup_key, None, state),
            call=_call("run-1"),
        )
        changed_start = _state(run_id="run-2", entrypoint_id="other")
        changed_key = _state(run_id="run-1", message_id="message-2")

        for candidate, expected_code in (
            (changed_start, "runtime_store_dedup_payload_conflict"),
            (changed_key, "runtime_store_run_id_conflict"),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(DududaError) as raised:
                    await store.commit(
                        RuntimeCommitRequest(
                            1,
                            candidate.run_id,
                            candidate.message.dedup_key,
                            None,
                            candidate,
                        ),
                        call=_call(candidate.run_id),
                    )
                self.assertEqual(raised.exception.info.code, expected_code)
                self.assertIs(raised.exception.info.category, ErrorCategory.CONFLICT)

    async def test_stale_cas_conflicts_without_overwriting_newer_state(self) -> None:
        store = _store()
        state = _state()
        await store.commit(
            RuntimeCommitRequest(1, "run-1", state.message.dedup_key, None, state),
            call=_call("run-1"),
        )
        first = _preprocessed(state, config="first")
        second = _preprocessed(state, config="second")
        await store.commit(
            RuntimeCommitRequest(1, "run-1", state.message.dedup_key, 1, first),
            call=_call("run-1"),
        )

        with self.assertRaises(DududaError) as raised:
            await store.commit(
                RuntimeCommitRequest(1, "run-1", state.message.dedup_key, 1, second),
                call=_call("run-1"),
            )

        self.assertEqual(raised.exception.info.code, "runtime_store_cas_conflict")
        loaded = await store.load("run-1", call=_call("run-1"))
        self.assertEqual(loaded.state, first)  # type: ignore[union-attr]

    async def test_revision_wait_wakes_on_commit_and_honors_cancellation(self) -> None:
        store = _store()
        state = _state()
        await store.commit(
            RuntimeCommitRequest(1, "run-1", state.message.dedup_key, None, state),
            call=_call("run-1"),
        )
        waiting = asyncio.create_task(
            store.wait_for_revision("run-1", 1, call=_call("run-1"))
        )
        await asyncio.sleep(0)
        await store.commit(
            RuntimeCommitRequest(
                1,
                "run-1",
                state.message.dedup_key,
                1,
                _preprocessed(state),
            ),
            call=_call("run-1"),
        )
        checkpoint = await asyncio.wait_for(waiting, timeout=1)
        self.assertEqual(checkpoint.revision, 2)  # type: ignore[union-attr]

        cancellation = ManualCancellationToken()
        cancelled = asyncio.create_task(
            store.wait_for_revision(
                "run-1",
                2,
                call=_call("run-1", cancellation=cancellation),
            )
        )
        await asyncio.sleep(0)
        cancellation.cancel()
        with self.assertRaises(DududaError) as raised:
            await asyncio.wait_for(cancelled, timeout=1)
        self.assertIs(raised.exception.info.category, ErrorCategory.CANCELLED)

    async def test_checkpoint_expires_to_tombstone_without_duplicate_reexecution(
        self,
    ) -> None:
        clock = _Clock()
        store = _store(clock=clock)
        state = _state()
        request = RuntimeCommitRequest(1, "run-1", state.message.dedup_key, None, state)
        await store.commit(request, call=_call("run-1", now=clock.now))

        clock.advance(11)
        self.assertIsNone(await store.load("run-1", call=_call("run-1", now=clock.now)))
        record = await store.lookup_dedup(
            state.message.dedup_key,
            call=_call("run-1", now=clock.now),
        )
        self.assertIsNotNone(record)
        duplicate = await store.commit(request, call=_call("run-1", now=clock.now))
        self.assertIs(duplicate.disposition, RuntimeCommitDisposition.DUPLICATE)
        self.assertIsNone(duplicate.checkpoint)

        clock.advance(20)
        recreated = await store.commit(request, call=_call("run-1", now=clock.now))
        self.assertIs(recreated.disposition, RuntimeCommitDisposition.CREATED)

    async def test_live_capacity_is_never_evicted(self) -> None:
        store = _store(maximum_checkpoints=1, maximum_dedup_records=1)
        first = _state()
        second = _state(run_id="run-2", message_id="message-2")
        await store.commit(
            RuntimeCommitRequest(1, "run-1", first.message.dedup_key, None, first),
            call=_call("run-1"),
        )

        with self.assertRaises(DududaError) as raised:
            await store.commit(
                RuntimeCommitRequest(
                    1, "run-2", second.message.dedup_key, None, second
                ),
                call=_call("run-2"),
            )

        self.assertIs(raised.exception.info.category, ErrorCategory.BUDGET)
        loaded = await store.load("run-1", call=_call("run-1"))
        self.assertIsNotNone(loaded)

    async def test_delete_preserves_dedup_tombstone(self) -> None:
        store = _store()
        state = _state()
        await store.commit(
            RuntimeCommitRequest(1, "run-1", state.message.dedup_key, None, state),
            call=_call("run-1"),
        )

        await store.delete("run-1", 1, call=_call("run-1"))

        self.assertIsNone(await store.load("run-1", call=_call("run-1")))
        self.assertIsNotNone(
            await store.lookup_dedup(
                state.message.dedup_key,
                call=_call("run-1"),
            )
        )


if __name__ == "__main__":
    unittest.main()
