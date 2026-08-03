from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from dududa._compat import StrEnum
from dududa.domain.primitives import DigestString, require_aware, require_non_empty
from dududa.errors import validation_error


class IdempotencyDisposition(StrEnum):
    ACQUIRED = "acquired"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class IdempotencyReceipt:
    key: str
    request_digest: DigestString
    disposition: IdempotencyDisposition
    expires_at: datetime


class InMemoryIdempotencyLedger:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._records: dict[str, tuple[DigestString, datetime]] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        key: str,
        request_digest: DigestString,
        *,
        expires_at: datetime,
    ) -> IdempotencyReceipt:
        require_non_empty(key, "idempotency_key")
        require_non_empty(str(request_digest), "request_digest")
        require_aware(expires_at, "expires_at")
        now = self._clock()
        if expires_at <= now:
            raise validation_error("idempotency_expiry_not_future")
        async with self._lock:
            self._records = {
                item_key: value
                for item_key, value in self._records.items()
                if value[1] > now
            }
            existing = self._records.get(key)
            if existing is None:
                self._records[key] = (request_digest, expires_at)
                disposition = IdempotencyDisposition.ACQUIRED
            elif existing[0] == request_digest:
                disposition = IdempotencyDisposition.DUPLICATE
                expires_at = existing[1]
            else:
                disposition = IdempotencyDisposition.CONFLICT
                expires_at = existing[1]
        return IdempotencyReceipt(key, request_digest, disposition, expires_at)
