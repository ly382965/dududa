from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString

from .models import (
    MemoryCandidate,
    MemoryDeleteCommand,
    MemoryDeleteReceipt,
    MemoryExportPage,
    MemoryRankRequest,
    MemoryRecord,
    MemoryRepositoryArchive,
    MemoryRestoreCommand,
    MemoryRestoreReceipt,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemoryScope,
    MemoryTombstone,
    MemoryTombstoneCheckpoint,
    MemoryWriteDecision,
    MemoryWriteRequest,
    ScopeSelector,
)


def memory_scope_digest(scope: MemoryScope) -> DigestString:
    return canonical_digest(scope, domain="memory:scope:v1")


def memory_content_hash(content: str) -> DigestString:
    return canonical_digest({"content": content}, domain="memory:content:v1")


def memory_record_digest(record: MemoryRecord) -> DigestString:
    return canonical_digest(record, domain="memory:record:v1")


def memory_candidate_digest(candidate: MemoryCandidate) -> DigestString:
    return canonical_digest(candidate, domain="memory:candidate:v1")


def memory_write_request_digest(request: MemoryWriteRequest) -> DigestString:
    values = {
        name: getattr(request, name)
        for name in request.__dataclass_fields__
        if name != "request_digest"
    }
    return canonical_digest(values, domain="memory:write-request:v1")


def memory_write_decision_digest(decision: MemoryWriteDecision) -> DigestString:
    return canonical_digest(decision, domain="memory:write-decision:v1")


def selector_digest(selector: ScopeSelector) -> DigestString:
    return canonical_digest(selector, domain="memory:scope-selector:v1")


def memory_delete_payload_digest(
    memory_id: str,
    expected_version: int,
    record_digest: DigestString,
) -> DigestString:
    return canonical_digest(
        {
            "memory_id": memory_id,
            "expected_version": expected_version,
            "record_digest": record_digest,
        },
        domain="memory:delete-payload:v1",
    )


def memory_delete_request_digest(command: MemoryDeleteCommand) -> DigestString:
    return canonical_digest(
        _without(command, "request_digest"),
        domain="memory:delete-request:v1",
    )


def memory_delete_command_digest(command: MemoryDeleteCommand) -> DigestString:
    return canonical_digest(command, domain="memory:delete-command:v1")


def memory_tombstone_digest(tombstone: MemoryTombstone) -> DigestString:
    return canonical_digest(
        _without(tombstone, "integrity_digest"),
        domain="memory:tombstone:v1",
    )


def memory_delete_receipt_digest(receipt: MemoryDeleteReceipt) -> DigestString:
    return canonical_digest(
        _without(receipt, "receipt_digest"),
        domain="memory:delete-receipt:v1",
    )


def memory_export_page_digest(page: MemoryExportPage) -> DigestString:
    return canonical_digest(
        _without(page, "export_digest"),
        domain="memory:export-page:v1",
    )


def memory_tombstone_checkpoint_digest(
    checkpoint: MemoryTombstoneCheckpoint,
) -> DigestString:
    return canonical_digest(
        _without(checkpoint, "checkpoint_digest"),
        domain="memory:tombstone-checkpoint:v1",
    )


def memory_repository_archive_digest(
    archive: MemoryRepositoryArchive,
) -> DigestString:
    return canonical_digest(
        _without(archive, "archive_digest"),
        domain="memory:repository-archive:v1",
    )


def memory_restore_request_digest(command: MemoryRestoreCommand) -> DigestString:
    return canonical_digest(
        _without(command, "request_digest"),
        domain="memory:restore-request:v1",
    )


def memory_restore_command_digest(command: MemoryRestoreCommand) -> DigestString:
    return canonical_digest(command, domain="memory:restore-command:v1")


def memory_restore_receipt_digest(receipt: MemoryRestoreReceipt) -> DigestString:
    return canonical_digest(
        _without(receipt, "receipt_digest"),
        domain="memory:restore-receipt:v1",
    )


def memory_rank_request_digest(request: MemoryRankRequest) -> DigestString:
    return canonical_digest(
        _without(request, "request_digest"),
        domain="memory:rank-request:v1",
    )


def memory_retrieval_request_digest(
    request: MemoryRetrievalRequest,
) -> DigestString:
    return canonical_digest(
        _without(request, "request_digest"),
        domain="memory:retrieval-request:v1",
    )


def memory_retrieval_result_digest(result: MemoryRetrievalResult) -> DigestString:
    return canonical_digest(
        _without(result, "result_digest"),
        domain="memory:retrieval-result:v1",
    )


def _without(value: object, *names: str) -> dict[str, object]:
    fields = getattr(value, "__dataclass_fields__", None)
    if fields is None:
        raise TypeError("digest value must be a dataclass")
    excluded = frozenset(names)
    return {name: getattr(value, name) for name in fields if name not in excluded}
