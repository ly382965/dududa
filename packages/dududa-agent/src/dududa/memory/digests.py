from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString

from .models import (
    MemoryCandidate,
    MemoryScope,
    MemoryWriteDecision,
    MemoryWriteRequest,
    ScopeSelector,
)


def memory_scope_digest(scope: MemoryScope) -> DigestString:
    return canonical_digest(scope, domain="memory:scope:v1")


def memory_content_hash(content: str) -> DigestString:
    return canonical_digest({"content": content}, domain="memory:content:v1")


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
