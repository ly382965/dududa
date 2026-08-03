from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dududa.domain.delivery import DeliveryStatus
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    ComponentRevision,
    ConversationType,
    DigestString,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.memory.digests import memory_write_request_digest
from dududa.memory.json_repository import JsonMemoryRepository
from dududa.memory.models import (
    DeliveryDependency,
    EvidenceReference,
    MemoryCandidate,
    MemoryScope,
    MemorySource,
    MemorySubmissionStatus,
    MemoryType,
    MemoryWriteAction,
    MemoryWriteRequest,
)
from dududa.memory.selectors import HmacScopeSelectorAuthority
from dududa.memory.write_gate import ExplicitMemoryWriteGate
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.security.digests import actor_digest, scope_digest
from dududa.security.models import AuthorizationDecision, AuthorizationEffect


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"id-{self.value}"


class MemoryWriteGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.actor = Actor(
            "qq", "bot-1", "u-1", frozenset({RoleId("normal")}), frozenset()
        )
        self.scope = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "g-1", "g-1", "dududa"
        )
        self.call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            self.now + timedelta(minutes=5),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal("0")),
            "policy-v1",
        )
        self.ids = SequentialIds()
        self.gate = ExplicitMemoryWriteGate(clock=lambda: self.now, id_factory=self.ids)
        self.authority = HmacScopeSelectorAuthority(
            b"0123456789abcdef0123456789abcdef",
            policy_revision="memory-policy-v1",
            clock=lambda: self.now,
        )

    def authorization(self) -> AuthorizationDecision:
        return AuthorizationDecision(
            1,
            "authorization-1",
            AuthorizationEffect.ALLOW,
            DigestString("authorization-request"),
            actor_digest(self.actor),
            scope_digest(self.scope),
            ActionId("memory.write"),
            DigestString("resource"),
            None,
            RiskLevel.MEDIUM,
            DigestString("metadata"),
            "policy-v1",
            (),
            self.now,
            self.now + timedelta(minutes=5),
        )

    def candidate(
        self,
        *,
        content: str = "我喜欢简洁回答",
        source: MemorySource = MemorySource.EXPLICIT_USER_REQUEST,
        user: str = "u-1",
        dependency: DeliveryDependency = DeliveryDependency.NONE,
    ) -> MemoryCandidate:
        return MemoryCandidate(
            1,
            "candidate-1",
            ComponentRevision("legacy.remember", "1", "cfg", DigestString("artifact")),
            content,
            source,
            MemoryType.EXPLICIT_USER_MEMORY,
            MemoryScope(
                1,
                "qq",
                "bot-1",
                ConversationType.GROUP,
                "g-1",
                "g-1",
                user,
                "dududa",
                MemoryType.EXPLICIT_USER_MEMORY,
            ),
            1.0,
            Sensitivity.PERSONAL,
            (EvidenceReference("e-1", "message", "m-1", "u-1"),),
            timedelta(days=30),
            dependency,
        )

    def request(
        self,
        candidate: MemoryCandidate,
        *,
        status: DeliveryStatus = DeliveryStatus.NOT_REQUIRED,
    ) -> MemoryWriteRequest:
        request = MemoryWriteRequest(
            1,
            DigestString("pending"),
            candidate,
            self.actor,
            self.scope,
            status,
            None,
            None,
            None,
            self.authorization(),
            "write-key-1",
        )
        return replace(request, request_digest=memory_write_request_digest(request))

    async def test_explicit_write_persists_idempotently_in_json_v2(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory-v2.json"
            repository = JsonMemoryRepository(
                path,
                self.authority,
                write_decision_verifier=self.gate,
                clock=lambda: self.now,
            )
            request = self.request(self.candidate())
            decision = await self.gate.evaluate(request, call=self.call)
            self.assertEqual(decision.action, MemoryWriteAction.ALLOW)
            command = self.gate.command(request, decision, command_id="command-1")
            first = await repository.commit_write(command, call=self.call)
            duplicate = await repository.commit_write(command, call=self.call)
            self.assertEqual(first, duplicate)
            self.assertEqual(first.status, MemorySubmissionStatus.PERSISTED)
            reloaded = JsonMemoryRepository(
                path,
                self.authority,
                clock=lambda: self.now,
            )
            self.assertIn(first.memory_id, reloaded._records)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    async def test_automatic_cross_user_secret_and_delivery_writes_are_rejected(
        self,
    ) -> None:
        cases = (
            self.candidate(source=MemorySource.OBSERVED_USER_STATEMENT),
            self.candidate(user="u-2"),
            self.candidate(content="Bearer abcdefghijklmnop"),
            self.candidate(dependency=DeliveryDependency.SUCCESS_REQUIRED),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate):
                decision = await self.gate.evaluate(
                    self.request(candidate), call=self.call
                )
                self.assertEqual(decision.action, MemoryWriteAction.REJECT)
                self.assertIsNone(decision.normalized_record)

    async def test_legacy_json_is_quarantined_and_never_rewritten(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "user_state.json"
            legacy = {"u-1": {"memories": [{"text": "legacy", "time": 1}]}}
            original = json.dumps(legacy, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            repository = JsonMemoryRepository(
                path,
                self.authority,
                write_decision_verifier=self.gate,
                clock=lambda: self.now,
            )
            self.assertEqual(repository.quarantined_legacy_count, 1)
            request = self.request(self.candidate())
            decision = await self.gate.evaluate(request, call=self.call)
            command = self.gate.command(request, decision, command_id="command-legacy")
            with self.assertRaises(DududaError):
                await repository.commit_write(command, call=self.call)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(repository._records, {})

    async def test_repository_rejects_tampered_or_unissued_gate_decision(self) -> None:
        with TemporaryDirectory() as directory:
            repository = JsonMemoryRepository(
                Path(directory) / "memory-v2.json",
                self.authority,
                write_decision_verifier=self.gate,
                clock=lambda: self.now,
            )
            request = self.request(self.candidate())
            decision = await self.gate.evaluate(request, call=self.call)
            with self.assertRaises(DududaError):
                replace(
                    decision.normalized_record,
                    content="tampered",
                )
            forged = replace(decision, decision_id="unissued-decision")
            command = self.gate.command(request, forged, command_id="forged-command")
            with self.assertRaises(DududaError):
                await repository.commit_write(command, call=self.call)

    async def test_json_temporary_symlink_is_rejected_without_touching_target(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "memory-v2.json"
            victim = root / "victim.txt"
            victim.write_text("unchanged", encoding="utf-8")
            os.symlink(victim, path.with_suffix(path.suffix + ".tmp"))
            repository = JsonMemoryRepository(
                path,
                self.authority,
                write_decision_verifier=self.gate,
                clock=lambda: self.now,
            )
            request = self.request(self.candidate())
            decision = await self.gate.evaluate(request, call=self.call)
            command = self.gate.command(request, decision, command_id="symlink-command")

            with self.assertRaises(DududaError):
                await repository.commit_write(command, call=self.call)

            self.assertEqual(victim.read_text(encoding="utf-8"), "unchanged")
            self.assertFalse(path.exists())
            self.assertEqual(repository._records, {})


if __name__ == "__main__":
    unittest.main()
