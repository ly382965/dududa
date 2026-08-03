from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import stat

from dududa.contracts.canonical import canonical_json_bytes
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext, ServiceCallContext

from .digests import audit_event_digest
from .models import AuditEvent, AuditReceipt, RedactionRequest
from .redaction import DefaultRedactor


class InMemoryAuditSink:
    def __init__(
        self,
        *,
        redactor: DefaultRedactor | None = None,
        revision: str = "audit-memory-v1",
    ) -> None:
        self.revision = revision
        self._redactor = redactor or DefaultRedactor()
        self.events: list[AuditEvent] = []
        self._lock = asyncio.Lock()

    async def write(
        self,
        event: AuditEvent,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> AuditReceipt:
        _validate_write(event, call, self._redactor)
        async with self._lock:
            self.events.append(event)
        return AuditReceipt(1, event.event_id, event.event_digest, True, self.revision)


class JsonlAuditSink:
    def __init__(
        self,
        path: Path,
        *,
        redactor: DefaultRedactor | None = None,
        revision: str = "audit-jsonl-v1",
    ) -> None:
        self.path = path
        self.revision = revision
        self._redactor = redactor or DefaultRedactor()
        self._lock = asyncio.Lock()

    async def write(
        self,
        event: AuditEvent,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> AuditReceipt:
        _validate_write(event, call, self._redactor)
        payload = canonical_json_bytes(event) + b"\n"
        async with self._lock:
            _reject_symlink_components(self.path.parent)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                _reject_symlink_components(self.path.parent)
                descriptor = os.open(
                    self.path,
                    os.O_APPEND
                    | os.O_CREAT
                    | os.O_WRONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                try:
                    file_stat = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(file_stat.st_mode)
                        or file_stat.st_uid != os.geteuid()
                        or file_stat.st_mode & 0o077
                    ):
                        raise OSError("unsafe audit file")
                    remaining = memoryview(payload)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if written <= 0:
                            raise OSError("short audit write")
                        remaining = remaining[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except OSError as exc:
                raise error(
                    "audit_persist_failed",
                    ErrorCategory.INTERNAL,
                    "security.audit_unavailable",
                    detail=type(exc).__name__,
                ) from None
        return AuditReceipt(1, event.event_id, event.event_digest, True, self.revision)


def _validate_event(event: AuditEvent) -> None:
    if audit_event_digest(event) != event.event_digest:
        raise error(
            "audit_event_digest_mismatch",
            ErrorCategory.VALIDATION,
            "security.audit_rejected",
        )


def _validate_write(
    event: AuditEvent,
    call: PortCallContext | ServiceCallContext,
    redactor: DefaultRedactor,
) -> None:
    _validate_event(event)
    now = datetime.now(timezone.utc)
    if call.cancellation.is_cancelled or call.deadline <= now:
        raise error(
            "audit_call_cancelled_or_expired",
            ErrorCategory.VALIDATION,
            "security.audit_rejected",
        )
    redacted = redactor.redact(
        RedactionRequest(1, event.sanitized_detail, event.sensitivity, "audit")
    )
    if redacted.changed:
        raise error(
            "audit_detail_not_sanitized",
            ErrorCategory.VALIDATION,
            "security.audit_rejected",
        )


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise OSError("audit path contains symlink")
