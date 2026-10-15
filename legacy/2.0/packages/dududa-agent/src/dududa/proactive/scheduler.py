from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dududa.contracts.canonical import canonical_digest
from dududa.errors import DududaError, ErrorCategory, validation_error
from dududa.ports.context import ServiceCallContext

if TYPE_CHECKING:
    from dududa.ports.proactive import (
        ProactiveScheduleStore,
        ProactiveSubscriptionStore,
    )

from .contracts import (
    ProactiveTrigger,
    ProactiveTriggerKind,
    ScheduleClaimReceipt,
    ScheduleMaterializationReceipt,
    ScheduleOccurrence,
    ScheduleOccurrenceOrigin,
    ScheduleOccurrenceState,
    ScheduleTriggerClaim,
)


@dataclass(frozen=True, slots=True)
class DeterministicSchedulerConfig:
    schema_version: int
    maximum_scan_days: int = 8

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if (
            type(self.maximum_scan_days) is not int
            or not 8 <= self.maximum_scan_days <= 32
        ):
            raise validation_error("invalid_scheduler_scan_window")


class DeterministicProactiveScheduler:
    """Materializes time facts and delegates all durable ownership to the store."""

    def __init__(
        self,
        subscription_store: ProactiveSubscriptionStore,
        schedule_store: ProactiveScheduleStore,
        config: DeterministicSchedulerConfig | None = None,
    ) -> None:
        from dududa.ports.proactive import (
            ProactiveScheduleStore,
            ProactiveSubscriptionStore,
        )

        if not isinstance(subscription_store, ProactiveSubscriptionStore):
            raise TypeError(
                "subscription_store must implement ProactiveSubscriptionStore"
            )
        if not isinstance(schedule_store, ProactiveScheduleStore):
            raise TypeError("schedule_store must implement ProactiveScheduleStore")
        if config is not None and not isinstance(config, DeterministicSchedulerConfig):
            raise TypeError("invalid deterministic scheduler config")
        self._subscription_store = subscription_store
        self._schedule_store = schedule_store
        self._config = config or DeterministicSchedulerConfig(1)

    async def materialize_due(
        self,
        *,
        now: datetime,
        call: ServiceCallContext,
    ) -> tuple[ScheduleMaterializationReceipt, ...]:
        instant = _utc(now, "scheduler_now")
        subscriptions = await self._subscription_store.list_active(call=call)
        receipts: list[ScheduleMaterializationReceipt] = []
        for subscription in subscriptions:
            schedule = subscription.schedule
            zone = ZoneInfo(schedule.timezone)
            local_now = instant.astimezone(zone)
            scan_days = min(
                self._config.maximum_scan_days,
                math.ceil(schedule.misfire_grace / timedelta(days=1)) + 1,
            )
            for offset in range(scan_days - 1, -1, -1):
                local_date = local_now.date() - timedelta(days=offset)
                if local_date.weekday() not in schedule.weekdays:
                    continue
                wall = datetime.combine(local_date, schedule.local_time)
                updated_wall = subscription.updated_at.astimezone(zone).replace(
                    tzinfo=None
                )
                if wall < updated_wall:
                    continue
                scheduled_for = resolve_local_schedule(
                    schedule.timezone,
                    local_date,
                    schedule.local_time,
                )
                if scheduled_for is None:
                    if wall > local_now.replace(tzinfo=None):
                        continue
                    receipts.append(
                        await self._schedule_store.record_nonexistent(
                            subscription,
                            local_date,
                            at=instant,
                            call=call,
                        )
                    )
                    continue
                if scheduled_for < subscription.updated_at or scheduled_for > instant:
                    continue
                occurrence = _occurrence(subscription, local_date, scheduled_for)
                trigger = _trigger(subscription, occurrence)
                state = (
                    ScheduleOccurrenceState.READY
                    if instant <= occurrence.eligible_until
                    else ScheduleOccurrenceState.SKIPPED_EXPIRED
                )
                receipts.append(
                    await self._schedule_store.record_trigger(
                        trigger,
                        state,
                        at=instant,
                        call=call,
                    )
                )
        return tuple(receipts)

    async def claim_due(
        self,
        *,
        worker_id: str,
        limit: int,
        ttl: timedelta,
        now: datetime,
        call: ServiceCallContext,
    ) -> tuple[ScheduleTriggerClaim, ...]:
        instant = _utc(now, "scheduler_now")
        records = await self._schedule_store.list_due(
            at=instant,
            limit=limit,
            call=call,
        )
        claims: list[ScheduleTriggerClaim] = []
        for record in records:
            if record.trigger is None or record.trigger.occurrence is None:
                continue
            try:
                claim, _ = await self._schedule_store.claim(
                    record.trigger.occurrence.occurrence_digest,
                    worker_id=worker_id,
                    ttl=ttl,
                    at=instant,
                    call=call,
                )
            except DududaError as exc:
                if exc.info.category is ErrorCategory.CONFLICT:
                    continue
                raise
            claims.append(claim)
            if len(claims) >= limit:
                break
        return tuple(claims)

    async def acknowledge(
        self,
        claim: ScheduleTriggerClaim,
        *,
        now: datetime,
        call: ServiceCallContext,
    ) -> ScheduleClaimReceipt:
        return await self._schedule_store.acknowledge(
            claim,
            at=_utc(now, "scheduler_now"),
            call=call,
        )


def resolve_local_schedule(
    timezone_name: str,
    local_date: date,
    local_time: time,
) -> datetime | None:
    """Resolve a wall time, choosing the earliest UTC fold and rejecting gaps."""

    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise validation_error("invalid_schedule_timezone")
    if not isinstance(local_date, date) or isinstance(local_date, datetime):
        raise validation_error("invalid_schedule_local_date")
    if not isinstance(local_time, time) or local_time.tzinfo is not None:
        raise validation_error("invalid_schedule_local_time")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise validation_error("invalid_schedule_timezone") from None
    wall = datetime.combine(local_date, local_time)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        roundtrip = candidate.astimezone(zone).replace(tzinfo=None)
        if roundtrip == wall:
            candidates.add(candidate)
    return min(candidates) if candidates else None


def _occurrence(subscription, local_date: date, scheduled_for: datetime):
    identity = {
        "subscription_id": subscription.subscription_id,
        "subscription_revision": subscription.revision,
        "schedule_revision": subscription.schedule.schedule_revision,
        "local_date": local_date.isoformat(),
    }
    return ScheduleOccurrence(
        schema_version=1,
        occurrence_id=_stable_id(
            "occurrence",
            identity,
            domain="proactive:schedule-occurrence-id:v1",
        ),
        subscription_id=subscription.subscription_id,
        subscription_revision=subscription.revision,
        origin=ScheduleOccurrenceOrigin.SCHEDULED,
        local_date=local_date,
        scheduled_for=scheduled_for,
        eligible_until=scheduled_for + subscription.schedule.misfire_grace,
    )


def _trigger(subscription, occurrence: ScheduleOccurrence) -> ProactiveTrigger:
    return ProactiveTrigger(
        schema_version=1,
        trigger_id=_stable_id(
            "trigger",
            {
                "occurrence_digest": occurrence.occurrence_digest,
                "target_policy_digest": (
                    subscription.target_policy_ref.target_policy_digest
                ),
            },
            domain="proactive:schedule-trigger-id:v1",
        ),
        kind=ProactiveTriggerKind.SCHEDULED_DIGEST,
        target_scope=subscription.target_scope,
        occurrence=occurrence,
        opportunity=None,
        target_policy_ref=subscription.target_policy_ref,
        created_at=occurrence.scheduled_for,
        expires_at=occurrence.eligible_until,
    )


def _stable_id(prefix: str, value: object, *, domain: str) -> str:
    digest = str(canonical_digest(value, domain=domain))
    return f"{prefix}-{digest.rsplit(':', 1)[-1]}"


def _utc(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise validation_error("invalid_scheduler_datetime", field_name)
    return value.astimezone(timezone.utc)


__all__ = [
    "DeterministicProactiveScheduler",
    "DeterministicSchedulerConfig",
    "resolve_local_schedule",
]
