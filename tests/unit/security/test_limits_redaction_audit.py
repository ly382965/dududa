from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    ComponentRevision,
    ConversationType,
    DigestString,
    ResourceRef,
    ResourceUsage,
    RoleId,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.security.audit import InMemoryAuditSink, JsonlAuditSink
from dududa.security.digests import (
    audit_event_digest,
    budget_reservation_request_digest,
    interaction_limit_request_digest,
    scope_digest,
)
from dududa.security.idempotency import InMemoryIdempotencyLedger
from dududa.security.limits import InMemoryBudgetLedger, InMemoryInteractionLimiter
from dududa.security.models import (
    AuditEvent,
    BudgetDisposition,
    BudgetReservationRequest,
    InteractionLimitRequest,
    RedactionRequest,
)
from dududa.security.redaction import DefaultRedactor


class SecurityServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.actor = Actor(
            "qq", "bot-1", "u-1", frozenset({RoleId("normal")}), frozenset()
        )
        self.scope = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "g-1", "g-1", "dududa"
        )
        self.call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            self.now + timedelta(minutes=1),
            NeverCancelled(),
            RuntimeBudget(1, 1, 1, 100, 100, Decimal("1")),
            "policy-v1",
        )

    def limit_request(self, key: str) -> InteractionLimitRequest:
        request = InteractionLimitRequest(
            1,
            DigestString("pending"),
            self.actor,
            self.scope,
            ActionId("chat.reply"),
            1,
            key,
        )
        return replace(
            request, request_digest=interaction_limit_request_digest(request)
        )

    async def test_concurrent_limiter_reservations_are_atomic(self) -> None:
        limiter = InMemoryInteractionLimiter(
            {"chat.reply": 1},
            policy_revision="limit-v1",
        )
        leases = await asyncio.gather(
            limiter.reserve(self.limit_request("a"), call=self.call),
            limiter.reserve(self.limit_request("b"), call=self.call),
        )
        self.assertEqual(sum(item.allowed for item in leases), 1)
        allowed = next(item for item in leases if item.allowed)
        first = await limiter.commit(allowed, call=self.call)
        second = await limiter.commit(allowed, call=self.call)
        self.assertEqual(first.disposition.value, "committed")
        self.assertEqual(second.disposition.value, "already_committed")

    async def test_budget_reserve_settle_and_duplicate_are_bound(self) -> None:
        capacity = ResourceUsage(1, 3, 2, 1, 1000, 500, Decimal("10"))
        ledger = InMemoryBudgetLedger(capacity, policy_revision="budget-v1")
        maximum = ResourceUsage(1, 2, 1, 0, 200, 100, Decimal("4"))
        resource = ResourceRef("runtime", "run-1", scope_digest(self.scope))
        request = BudgetReservationRequest(
            1, DigestString("pending"), resource, maximum, "budget-1"
        )
        request = replace(
            request, request_digest=budget_reservation_request_digest(request)
        )
        lease = await ledger.reserve(request, call=self.call)
        usage = ResourceUsage(1, 1, 1, 0, 100, 50, Decimal("2"))
        receipt = await ledger.settle(lease, usage, call=self.call)
        duplicate = await ledger.settle(lease, usage, call=self.call)
        self.assertEqual(receipt.charged, usage)
        self.assertEqual(duplicate.disposition, BudgetDisposition.DUPLICATE)

    async def test_unknown_cost_is_charged_at_reservation_ceiling(self) -> None:
        capacity = ResourceUsage(1, 3, 2, 1, 1000, 500, Decimal("10"))
        ledger = InMemoryBudgetLedger(capacity, policy_revision="budget-v1")
        maximum = ResourceUsage(1, 2, 1, 0, 200, 100, Decimal("4"))
        resource = ResourceRef("runtime", "run-1", scope_digest(self.scope))
        request = BudgetReservationRequest(
            1, DigestString("pending"), resource, maximum, "budget-unknown"
        )
        request = replace(
            request, request_digest=budget_reservation_request_digest(request)
        )
        lease = await ledger.reserve(request, call=self.call)
        unknown = ResourceUsage(1, 1, 1, 0, 100, 50, None)
        receipt = await ledger.settle(lease, unknown, call=self.call)
        self.assertEqual(receipt.charged.cost_units, Decimal("4"))
        self.assertEqual(receipt.remaining.cost_units, Decimal("6"))

    async def test_idempotency_rejects_already_expired_acquisition(self) -> None:
        ledger = InMemoryIdempotencyLedger(clock=lambda: self.now)
        with self.assertRaises(DududaError):
            await ledger.acquire(
                "expired-key",
                DigestString("request"),
                expires_at=self.now,
            )

    def test_redaction_is_recursive_value_aware_and_idempotent(self) -> None:
        secret = "ordinarysecretvalue"
        redactor = DefaultRedactor(
            secret_fingerprints=frozenset({DefaultRedactor.fingerprint(secret)})
        )
        request = RedactionRequest(
            1,
            {
                "nested": {"api_token": "raw"},
                "note": f"prefix {secret} suffix and Bearer abcdefghijklmnop",
                "url": "https://user:pass@example.test/path?token=raw&ok=1",
                "path": "/home/user/private.txt",
                "embedded": "failed at /opt/dududa/config/private.json",
                "access_url": "https://example.test/path?access_token=raw",
                "invalid_url": "https://example.test:bad/path?access_token=raw",
                "access token": "short",
                "ＡＰＩ＿ＫＥＹ": "short",
                "dbPassword": "short",
            },
            Sensitivity.SENSITIVE,
            "test",
        )
        first = redactor.redact(request)
        serialized = json.dumps(_mutable(first.value), ensure_ascii=False)
        for raw in (
            "ordinarysecretvalue",
            "abcdefghijklmnop",
            "pass",
            "/home/user",
            "/opt/dududa",
            "access_token=raw",
            "example.test:bad",
            "short",
        ):
            self.assertNotIn(raw, serialized)
        second = redactor.redact(
            RedactionRequest(1, first.value, Sensitivity.SENSITIVE, "test")
        )
        self.assertFalse(second.changed)
        self.assertEqual(first.value, second.value)

    async def test_audit_digest_and_jsonl_persistence(self) -> None:
        event = AuditEvent(
            1,
            "event-1",
            DigestString("pending"),
            self.now,
            "run-1",
            "security.test",
            "trace-1",
            None,
            None,
            scope_digest(self.scope),
            ActionId("config.read"),
            "allow",
            None,
            DigestString("request"),
            ("policy-v1",),
            (ComponentRevision("test", "1", "cfg", DigestString("artifact")),),
            (),
            DigestString("resource"),
            {"safe": True},
            Sensitivity.PUBLIC,
            "succeeded",
        )
        event = replace(event, event_digest=audit_event_digest(event))
        memory = InMemoryAuditSink()
        receipt = await memory.write(event, call=self.call)
        self.assertTrue(receipt.persisted)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            sink = JsonlAuditSink(path)
            await sink.write(event, call=self.call)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(DududaError):
            await memory.write(replace(event, outcome="tampered"), call=self.call)
        unsafe = replace(
            event,
            sanitized_detail={"access token": "raw"},
            event_digest=DigestString("pending"),
        )
        unsafe = replace(unsafe, event_digest=audit_event_digest(unsafe))
        with self.assertRaises(DududaError):
            await memory.write(unsafe, call=self.call)

    async def test_jsonl_audit_rejects_symlink_and_public_file(self) -> None:
        event = AuditEvent(
            1,
            "event-file",
            DigestString("pending"),
            self.now,
            "run-1",
            "security.test",
            "trace-1",
            None,
            None,
            scope_digest(self.scope),
            ActionId("config.read"),
            "allow",
            None,
            DigestString("request"),
            ("policy-v1",),
            (ComponentRevision("test", "1", "cfg", DigestString("artifact")),),
            (),
            DigestString("resource"),
            {"safe": True},
            Sensitivity.PUBLIC,
            "succeeded",
        )
        event = replace(event, event_digest=audit_event_digest(event))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "public.jsonl"
            public.write_text("", encoding="utf-8")
            public.chmod(0o644)
            with self.assertRaises(DududaError):
                await JsonlAuditSink(public).write(event, call=self.call)
            target = root / "target.jsonl"
            target.write_text("unchanged", encoding="utf-8")
            target.chmod(0o600)
            link = root / "audit.jsonl"
            link.symlink_to(target)
            with self.assertRaises(DududaError):
                await JsonlAuditSink(link).write(event, call=self.call)
            self.assertEqual(target.read_text(encoding="utf-8"), "unchanged")


def _mutable(value: object) -> object:
    if hasattr(value, "items"):
        return {key: _mutable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_mutable(item) for item in value]
    return value


if __name__ == "__main__":
    unittest.main()
