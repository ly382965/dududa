from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timezone

from dududa.domain.primitives import DigestString
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext

from .contracts import (
    PersonaCatalogSnapshot,
    PersonaCatalogUpdate,
    PersonaDefinition,
    PersonaResolution,
    keys_for,
    persona_catalog_digest,
    validate_persona_resolution,
)

PersonaCatalogCallContext = PortCallContext | ServiceCallContext


class InMemoryPersonaRegistry:
    """Atomic, history-bounded, last-known-good Persona Catalog."""

    def __init__(
        self,
        definitions: tuple[PersonaDefinition, ...],
        *,
        fallback_persona_id: str,
        fallback_version: str,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        history_limit: int = 32,
    ) -> None:
        if type(history_limit) is not int or history_limit < 2:
            raise validation_error("invalid_persona_catalog_history_limit")
        if fallback_persona_id != "neutral":
            raise validation_error("invalid_persona_fallback_id")
        if not isinstance(fallback_version, str) or not fallback_version.strip():
            raise validation_error("invalid_persona_fallback_version")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._history_limit = history_limit
        self._publish_lock = asyncio.Lock()
        initial = self._build_snapshot(
            1,
            definitions,
            fallback_persona_id,
            fallback_version,
        )
        self._current = initial
        self._history: OrderedDict[str, PersonaCatalogSnapshot] = OrderedDict(
            ((initial.snapshot_id, initial),)
        )

    def acquire_snapshot(self) -> PersonaCatalogSnapshot:
        return self._current

    def snapshot_by_id(
        self,
        snapshot_id: str,
        *,
        expected_digest: DigestString | None = None,
    ) -> PersonaCatalogSnapshot:
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise validation_error("invalid_persona_snapshot_id")
        snapshot = self._history.get(snapshot_id)
        if snapshot is None:
            raise validation_error("unknown_persona_catalog_snapshot")
        if expected_digest is not None and snapshot.catalog_digest != expected_digest:
            raise validation_error("persona_catalog_snapshot_digest_mismatch")
        return snapshot

    def resolve(
        self,
        snapshot: PersonaCatalogSnapshot,
        persona_id: str,
        version: str | None = None,
    ) -> PersonaResolution:
        stored = self._stored_snapshot(snapshot)
        if not isinstance(persona_id, str) or not persona_id.strip():
            raise validation_error("invalid_requested_persona_id")
        try:
            definition = self._resolve_definition(stored, persona_id, version)
            fallback_used = False
            reason = "requested_persona_resolved"
        except LookupError:
            definition = self._resolve_definition(
                stored,
                stored.fallback_persona_id,
                stored.fallback_version,
            )
            fallback_used = True
            reason = "neutral_persona_fallback"
        resolution = PersonaResolution(
            schema_version=1,
            requested_persona_id=persona_id,
            requested_version=version,
            definition=definition,
            snapshot_id=stored.snapshot_id,
            catalog_digest=stored.catalog_digest,
            fallback_used=fallback_used,
            reason_code=reason,
        )
        return validate_persona_resolution(
            stored,
            resolution,
            requested_persona_id=persona_id,
            requested_version=version,
        )

    def list_versions(
        self,
        snapshot: PersonaCatalogSnapshot,
        persona_id: str,
    ) -> tuple[str, ...]:
        stored = self._stored_snapshot(snapshot)
        if not isinstance(persona_id, str) or not persona_id.strip():
            raise validation_error("invalid_requested_persona_id")
        return tuple(
            value.version
            for value in stored.definitions
            if value.persona_id == persona_id
        )

    async def publish(
        self,
        update: PersonaCatalogUpdate,
        *,
        call: PersonaCatalogCallContext,
    ) -> PersonaCatalogSnapshot:
        if not isinstance(update, PersonaCatalogUpdate):
            raise validation_error("invalid_persona_catalog_update")
        now = self._now()
        _validate_call(call, now)
        async with self._publish_lock:
            now = self._now()
            _validate_call(call, now)
            current = self._current
            if update.expected_revision != current.revision:
                raise error(
                    "persona_catalog_revision_conflict",
                    ErrorCategory.CONFLICT,
                    "request.conflict",
                    "expected_revision_mismatch",
                )
            candidate = self._build_snapshot(
                current.revision + 1,
                update.definitions,
                current.fallback_persona_id,
                current.fallback_version,
                acquired_at=now,
            )
            if candidate.snapshot_id in self._history:
                raise error(
                    "persona_catalog_snapshot_id_conflict",
                    ErrorCategory.CONFLICT,
                    "request.conflict",
                )
            self._current = candidate
            self._remember(candidate)
            return candidate

    def _stored_snapshot(
        self,
        snapshot: PersonaCatalogSnapshot,
    ) -> PersonaCatalogSnapshot:
        if not isinstance(snapshot, PersonaCatalogSnapshot):
            raise validation_error("invalid_persona_catalog_snapshot")
        stored = self.snapshot_by_id(
            snapshot.snapshot_id,
            expected_digest=snapshot.catalog_digest,
        )
        if stored != snapshot:
            raise validation_error("persona_catalog_snapshot_tampered")
        return stored

    def _build_snapshot(
        self,
        revision: int,
        definitions: tuple[PersonaDefinition, ...],
        fallback_persona_id: str,
        fallback_version: str,
        *,
        acquired_at: datetime | None = None,
    ) -> PersonaCatalogSnapshot:
        if isinstance(definitions, (str, bytes)):
            raise validation_error("empty_persona_catalog")
        try:
            values = tuple(definitions)
        except TypeError:
            raise validation_error("empty_persona_catalog") from None
        if not values or not all(
            isinstance(value, PersonaDefinition) for value in values
        ):
            raise validation_error("empty_persona_catalog")
        ordered = tuple(sorted(values, key=keys_for))
        now = acquired_at or self._now()
        return PersonaCatalogSnapshot(
            schema_version=1,
            snapshot_id=self._new_id(),
            revision=revision,
            definitions=ordered,
            fallback_persona_id=fallback_persona_id,
            fallback_version=fallback_version,
            acquired_at=now,
            catalog_digest=persona_catalog_digest(
                revision,
                ordered,
                fallback_persona_id,
                fallback_version,
            ),
        )

    def _remember(self, snapshot: PersonaCatalogSnapshot) -> None:
        self._history[snapshot.snapshot_id] = snapshot
        self._history.move_to_end(snapshot.snapshot_id)
        while len(self._history) > self._history_limit:
            self._history.popitem(last=False)

    def _new_id(self) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - factory failures are sanitized.
            raise error(
                "persona_catalog_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise validation_error("invalid_persona_snapshot_id")
        return f"persona-catalog:{value}"

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - clock failures are sanitized.
            raise error(
                "persona_catalog_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_persona_catalog_clock")
        return value

    @staticmethod
    def _resolve_definition(
        snapshot: PersonaCatalogSnapshot,
        persona_id: str,
        version: str | None,
    ) -> PersonaDefinition:
        candidates = tuple(
            value
            for value in snapshot.definitions
            if value.persona_id == persona_id
            and (version is None or value.version == version)
        )
        if not candidates:
            raise LookupError(persona_id, version)
        return max(candidates, key=lambda value: keys_for(value)[1])


def _validate_call(call: PersonaCatalogCallContext, now: datetime) -> None:
    if not isinstance(call, (PortCallContext, ServiceCallContext)):
        raise validation_error("invalid_persona_catalog_call_context")
    if call.cancellation.is_cancelled:
        raise error(
            "persona_catalog_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "persona_catalog_call_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


__all__ = ["InMemoryPersonaRegistry"]
