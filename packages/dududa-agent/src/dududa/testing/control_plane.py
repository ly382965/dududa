from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone

from dududa.control_plane.contracts import (
    GroupControlScope,
    GroupJoinFact,
    GroupServiceProfile,
    OperatorSession,
    ProfileRef,
    ServiceCatalogSnapshot,
)
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext


class MappingOperatorSessionResolver:
    def __init__(
        self,
        sessions: Mapping[str, OperatorSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = dict(sessions)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.calls: list[tuple[str, ServiceCallContext]] = []

    async def resolve(
        self,
        session_ref: str,
        *,
        call: ServiceCallContext,
    ) -> OperatorSession:
        _validate_call(call, self._clock())
        session = self._sessions.get(session_ref)
        if session is None or session.session_ref != session_ref:
            raise _session_error("operator_session_not_found")
        if not session.issued_at <= self._clock() < session.expires_at:
            raise _session_error("operator_session_expired")
        self.calls.append((session_ref, call))
        return session


class FakeGroupJoinSource:
    def __init__(
        self,
        facts: Iterable[GroupJoinFact] = (),
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._facts = list(facts)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.calls: list[ServiceCallContext] = []

    def append(self, fact: GroupJoinFact) -> None:
        if not isinstance(fact, GroupJoinFact):
            raise validation_error("invalid_group_join_fact")
        self._facts.append(fact)

    async def drain(
        self,
        *,
        call: ServiceCallContext,
    ) -> tuple[GroupJoinFact, ...]:
        _validate_call(call, self._clock())
        self.calls.append(call)
        facts = tuple(self._facts)
        self._facts.clear()
        return facts


class StaticFakeServiceCatalog:
    def __init__(
        self,
        profiles: Iterable[GroupServiceProfile],
        snapshot: ServiceCatalogSnapshot,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        profile_values = tuple(profiles)
        self._profiles = {
            (profile.profile_id, profile.revision): profile
            for profile in profile_values
        }
        if len(self._profiles) != len(profile_values):
            raise validation_error("duplicate_profile_ref")
        self._snapshot = snapshot
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.profile_calls: list[tuple[ProfileRef, ServiceCallContext]] = []
        self.snapshot_calls: list[tuple[GroupControlScope, ServiceCallContext]] = []

    async def get_profile(
        self,
        profile_ref: ProfileRef,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceProfile | None:
        _validate_call(call, self._clock())
        self.profile_calls.append((profile_ref, call))
        return self._profiles.get((profile_ref.profile_id, profile_ref.revision))

    async def snapshot(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> ServiceCatalogSnapshot:
        _validate_call(call, self._clock())
        self.snapshot_calls.append((scope, call))
        return self._snapshot


def _validate_call(call: ServiceCallContext, now: datetime) -> None:
    if not isinstance(call, ServiceCallContext):
        raise validation_error("invalid_control_plane_call_context")
    if call.cancellation.is_cancelled:
        raise error(
            "control_plane_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if call.deadline <= now:
        raise error(
            "control_plane_call_expired",
            ErrorCategory.TIMEOUT,
            "request.expired",
        )


def _session_error(code: str):
    return error(code, ErrorCategory.AUTHORIZATION, "control_plane.session_denied")


__all__ = [
    "FakeGroupJoinSource",
    "MappingOperatorSessionResolver",
    "StaticFakeServiceCatalog",
]
