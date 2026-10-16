from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    ComponentRevision,
    ConversationType,
    DigestString,
    RiskLevel,
    RoleId,
    Sensitivity,
)
from dududa.errors import DududaError
from dududa.memory.digests import (
    memory_content_hash,
    memory_delete_receipt_digest,
    memory_delete_request_digest,
    memory_record_digest,
    memory_repository_archive_digest,
    memory_retrieval_request_digest,
    memory_retrieval_result_digest,
    memory_tombstone_checkpoint_digest,
    memory_tombstone_digest,
)
from dududa.memory.models import (
    EvidenceReference,
    MemoryDeleteCommand,
    MemoryDeleteReceipt,
    MemoryQuery,
    MemoryRecord,
    MemoryRepositoryArchive,
    MemoryRepositorySnapshot,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemoryRetrievalStrategy,
    MemoryScope,
    MemorySource,
    MemoryTombstone,
    MemoryTombstoneCheckpoint,
    MemoryType,
    Visibility,
)
from dududa.memory.serialization import (
    archive_from_dict,
    archive_to_dict,
    delete_receipt_from_dict,
    delete_receipt_to_dict,
    tombstone_from_dict,
    tombstone_to_dict,
)
from dududa.security.digests import actor_digest, scope_digest
from dududa.security.models import (
    AuthorizationDecision,
    AuthorizationEffect,
    ConfirmationGrant,
)


class MemoryLifecycleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.actor = Actor(
            "qq", "bot-1", "user-1", frozenset({RoleId("normal")}), frozenset()
        )
        self.conversation = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "group-1", "group-1", "dududa"
        )
        self.record = self._record("memory-1", "校园通知在周五发布")
        self.revision = ComponentRevision(
            "memory.repository", "2", "memory-json-v2", DigestString("builtin")
        )

    def test_delete_request_and_receipt_digests_bind_payload(self) -> None:
        authorization = self._authorization()
        command = MemoryDeleteCommand(
            1,
            "delete-1",
            DigestString("pending"),
            self.actor,
            self.conversation,
            self.record.memory_id,
            self.record.version,
            memory_record_digest(self.record),
            authorization,
            self._confirmation(authorization),
            "delete-key-1",
        )
        command = replace(command, request_digest=memory_delete_request_digest(command))
        self.assertNotEqual(
            memory_delete_request_digest(replace(command, expected_version=2)),
            command.request_digest,
        )

        tombstone = self._tombstone(self.record)
        receipt = MemoryDeleteReceipt(
            1,
            command.command_id,
            command.request_digest,
            command.idempotency_key,
            command.memory_id,
            command.expected_version,
            tombstone.integrity_digest,
            2,
            authorization.policy_revision,
            self.revision,
            self.now,
            DigestString("pending"),
        )
        receipt = replace(receipt, receipt_digest=memory_delete_receipt_digest(receipt))
        self.assertEqual(
            delete_receipt_from_dict(delete_receipt_to_dict(receipt)), receipt
        )
        tampered = delete_receipt_to_dict(receipt)
        tampered["state_revision"] = 3
        with self.assertRaises(DududaError):
            delete_receipt_from_dict(tampered)

    def test_tombstone_and_archive_round_trip_are_integrity_bound(self) -> None:
        tombstone = self._tombstone(self.record)
        self.assertEqual(tombstone_from_dict(tombstone_to_dict(tombstone)), tombstone)
        checkpoint = MemoryTombstoneCheckpoint(
            1,
            "checkpoint-1",
            "memory-json-v2",
            2,
            (tombstone,),
            self.now,
            DigestString("pending"),
        )
        checkpoint = replace(
            checkpoint,
            checkpoint_digest=memory_tombstone_checkpoint_digest(checkpoint),
        )
        archive = MemoryRepositoryArchive(
            1,
            "archive-1",
            "memory-json-v2",
            2,
            (self._record("memory-2", "Python 3.12"),),
            checkpoint,
            self.now,
            DigestString("pending"),
        )
        archive = replace(
            archive,
            archive_digest=memory_repository_archive_digest(archive),
        )
        self.assertEqual(archive_from_dict(archive_to_dict(archive)), archive)
        tampered = archive_to_dict(archive)
        tampered["records"] = []
        with self.assertRaises(DududaError):
            archive_from_dict(tampered)

    def test_snapshot_and_retrieval_time_are_generation_bound(self) -> None:
        snapshot = MemoryRepositorySnapshot(
            1,
            "snapshot-1",
            "memory-json-v2",
            7,
            (DigestString("selector"),),
            DigestString("request"),
            self.now,
            self.now + timedelta(minutes=1),
            DigestString("integrity"),
        )
        self.assertEqual(snapshot.state_revision, 7)
        with self.assertRaises(DududaError):
            MemoryRetrievalRequest(
                1,
                "query-1",
                DigestString("pending"),
                self.actor,
                self.conversation,
                MemoryQuery(1, "校园", "zh-CN", self.now - timedelta(seconds=1)),
                frozenset({MemoryType.EXPLICIT_USER_MEMORY}),
                MemoryRetrievalStrategy.RECENCY,
                2,
                10,
                10,
                self.now,
            )

    def test_no_memory_result_is_digest_bound_and_has_no_repository_evidence(
        self,
    ) -> None:
        request = MemoryRetrievalRequest(
            1,
            "query-1",
            DigestString("pending"),
            self.actor,
            self.conversation,
            MemoryQuery(1, "校园", "zh-CN", self.now),
            frozenset({MemoryType.EXPLICIT_USER_MEMORY}),
            MemoryRetrievalStrategy.NO_MEMORY,
            2,
            10,
            10,
            self.now,
        )
        request = replace(
            request, request_digest=memory_retrieval_request_digest(request)
        )
        result = MemoryRetrievalResult(
            1,
            request.request_digest,
            request.strategy,
            (),
            (),
            None,
            None,
            None,
            "memory-policy-v1",
            None,
            ComponentRevision(
                "memory.retriever", "1", "no-memory", DigestString("builtin")
            ),
            False,
            ("no_memory_control",),
            DigestString("pending"),
        )
        result = replace(result, result_digest=memory_retrieval_result_digest(result))
        self.assertEqual(memory_retrieval_result_digest(result), result.result_digest)

    def _record(self, memory_id: str, content: str) -> MemoryRecord:
        return MemoryRecord(
            1,
            memory_id,
            MemoryScope(
                1,
                "qq",
                "bot-1",
                ConversationType.GROUP,
                "group-1",
                "group-1",
                "user-1",
                "dududa",
                MemoryType.EXPLICIT_USER_MEMORY,
            ),
            content,
            MemorySource.EXPLICIT_USER_REQUEST,
            self.now - timedelta(days=1),
            self.now - timedelta(minutes=1),
            1.0,
            None,
            Sensitivity.PERSONAL,
            Visibility.CURRENT_CONVERSATION,
            (EvidenceReference(f"e-{memory_id}", "synthetic", "case-1"),),
            memory_content_hash(content),
            1,
        )

    def _authorization(self) -> AuthorizationDecision:
        return AuthorizationDecision(
            1,
            "authorization-1",
            AuthorizationEffect.ALLOW,
            DigestString("authorization-request"),
            actor_digest(self.actor),
            scope_digest(self.conversation),
            ActionId("memory.delete"),
            DigestString("resource"),
            None,
            RiskLevel.HIGH,
            DigestString("metadata"),
            "memory-policy-v1",
            (),
            self.now - timedelta(seconds=1),
            self.now + timedelta(minutes=5),
        )

    def _confirmation(self, authorization: AuthorizationDecision) -> ConfirmationGrant:
        from dududa.contracts.canonical import canonical_digest
        from dududa.security.digests import authorization_decision_digest

        return ConfirmationGrant(
            1,
            "confirmation-1",
            DigestString("consume-request"),
            actor_digest(self.actor),
            scope_digest(self.conversation),
            ActionId("memory.delete"),
            canonical_digest(
                {
                    "memory_id": self.record.memory_id,
                    "expected_version": self.record.version,
                    "record_digest": memory_record_digest(self.record),
                },
                domain="memory:delete-payload:v1",
            ),
            "memory.delete",
            "delete-1",
            "delete-key-1",
            authorization_decision_digest(authorization),
            authorization.policy_revision,
            self.now - timedelta(seconds=2),
            self.now - timedelta(seconds=1),
            self.now + timedelta(minutes=5),
        )

    def _tombstone(self, record: MemoryRecord) -> MemoryTombstone:
        tombstone = MemoryTombstone(
            1,
            "tombstone-1",
            record.memory_id,
            record.scope,
            memory_record_digest(record),
            record.content_hash,
            record.version,
            DigestString("delete-command"),
            DigestString("authorization"),
            DigestString("confirmation"),
            "memory-policy-v1",
            self.revision,
            self.now,
            2,
            DigestString("pending"),
        )
        return replace(
            tombstone,
            integrity_digest=memory_tombstone_digest(tombstone),
        )


if __name__ == "__main__":
    unittest.main()
