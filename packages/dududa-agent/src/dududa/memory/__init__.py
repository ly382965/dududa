"""Scoped Memory v2 contracts and local adapters."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .iris import IrisMemoryRepository
    from .json_repository import JsonMemoryRepository
    from .lexical import CjkBm25MemoryRanker, cjk_bm25_terms
    from .models import (
        IndexableMemoryProjection,
        MemoryCandidate,
        MemoryConflictGroup,
        MemoryDeleteCommand,
        MemoryDeleteReceipt,
        MemoryExportPage,
        MemoryMatch,
        MemoryQuery,
        MemoryRankRequest,
        MemoryRankScore,
        MemoryRecord,
        MemoryRepositoryArchive,
        MemoryRestoreCommand,
        MemoryRestoreReceipt,
        MemoryRetrievalRequest,
        MemoryRetrievalResult,
        MemoryRetrievalStrategy,
        MemoryScope,
        MemorySource,
        MemoryTombstone,
        MemoryTombstoneCheckpoint,
        MemoryType,
        ScopeSelector,
        SelectorMode,
        Visibility,
    )
    from .repository import InMemoryMemoryRepository
    from .retrieval import (
        DeterministicMemoryRetrievalPolicy,
        DeterministicScopedMemoryRetriever,
    )
    from .selectors import HmacScopeSelectorAuthority
    from .write_gate import ExplicitMemoryWriteGate

__all__ = [
    "CjkBm25MemoryRanker",
    "DeterministicMemoryRetrievalPolicy",
    "DeterministicScopedMemoryRetriever",
    "ExplicitMemoryWriteGate",
    "HmacScopeSelectorAuthority",
    "InMemoryMemoryRepository",
    "IndexableMemoryProjection",
    "IrisMemoryRepository",
    "JsonMemoryRepository",
    "MemoryCandidate",
    "MemoryConflictGroup",
    "MemoryDeleteCommand",
    "MemoryDeleteReceipt",
    "MemoryExportPage",
    "MemoryMatch",
    "MemoryQuery",
    "MemoryRankRequest",
    "MemoryRankScore",
    "MemoryRecord",
    "MemoryRepositoryArchive",
    "MemoryRestoreCommand",
    "MemoryRestoreReceipt",
    "MemoryRetrievalRequest",
    "MemoryRetrievalResult",
    "MemoryRetrievalStrategy",
    "MemoryScope",
    "MemorySource",
    "MemoryTombstone",
    "MemoryTombstoneCheckpoint",
    "MemoryType",
    "ScopeSelector",
    "SelectorMode",
    "Visibility",
    "cjk_bm25_terms",
]

_EXPORT_MODULES = {
    "ExplicitMemoryWriteGate": ".write_gate",
    "HmacScopeSelectorAuthority": ".selectors",
    "InMemoryMemoryRepository": ".repository",
    "IrisMemoryRepository": ".iris",
    "JsonMemoryRepository": ".json_repository",
    "CjkBm25MemoryRanker": ".lexical",
    "DeterministicMemoryRetrievalPolicy": ".retrieval",
    "DeterministicScopedMemoryRetriever": ".retrieval",
    "IndexableMemoryProjection": ".models",
    "MemoryCandidate": ".models",
    "MemoryConflictGroup": ".models",
    "MemoryDeleteCommand": ".models",
    "MemoryDeleteReceipt": ".models",
    "MemoryExportPage": ".models",
    "MemoryMatch": ".models",
    "MemoryQuery": ".models",
    "MemoryRankRequest": ".models",
    "MemoryRankScore": ".models",
    "MemoryRecord": ".models",
    "MemoryRepositoryArchive": ".models",
    "MemoryRestoreCommand": ".models",
    "MemoryRestoreReceipt": ".models",
    "MemoryRetrievalRequest": ".models",
    "MemoryRetrievalResult": ".models",
    "MemoryRetrievalStrategy": ".models",
    "MemoryScope": ".models",
    "MemorySource": ".models",
    "MemoryTombstone": ".models",
    "MemoryTombstoneCheckpoint": ".models",
    "MemoryType": ".models",
    "ScopeSelector": ".models",
    "SelectorMode": ".models",
    "Visibility": ".models",
    "cjk_bm25_terms": ".lexical",
}


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
