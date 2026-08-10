from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from datetime import datetime, timezone

from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext

from .contracts import (
    ProactiveAuthorizationGrant,
    ProactiveAuthorizationGrantRef,
    ProactiveGrantKind,
    ProactiveTargetPolicy,
    ProactiveTargetPolicyRef,
    ProactiveTargetPolicyStatus,
    ProactiveTriggerKind,
    SourceCategory,
    validate_grant_ref,
    validate_target_policy_ref,
)


class InMemoryProactiveTargetRegistry:
    """Atomic current-revision Target/Grant registry for offline contracts."""

    def __init__(
        self,
        grants: Iterable[ProactiveAuthorizationGrant],
        policies: Iterable[ProactiveTargetPolicy],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = asyncio.Lock()
        self._generation = 1
        self._grants, self._policies = self._candidate(grants, policies)

    @property
    def generation(self) -> int:
        return self._generation

    async def publish(
        self,
        grants: Iterable[ProactiveAuthorizationGrant],
        policies: Iterable[ProactiveTargetPolicy],
        *,
        expected_generation: int,
        call: ServiceCallContext,
    ) -> int:
        now = self._now()
        _validate_call(call, now)
        if type(expected_generation) is not int or expected_generation < 1:
            raise validation_error("invalid_proactive_registry_generation")
        candidate_grants, candidate_policies = self._candidate(grants, policies)
        async with self._lock:
            now = self._now()
            _validate_call(call, now)
            if expected_generation != self._generation:
                raise error(
                    "proactive_registry_generation_conflict",
                    ErrorCategory.CONFLICT,
                    "request.conflict",
                )
            self._grants = candidate_grants
            self._policies = candidate_policies
            self._generation += 1
            return self._generation

    async def resolve_target(
        self,
        reference: ProactiveTargetPolicyRef,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ProactiveTargetPolicy:
        _aware(at, "proactive_registry_at")
        _validate_call(call, at)
        if not isinstance(reference, ProactiveTargetPolicyRef):
            raise validation_error("invalid_proactive_target_policy_ref")
        policy = self._policies.get(reference.target_policy_id)
        if policy is None:
            raise validation_error("proactive_target_policy_not_found")
        validate_target_policy_ref(policy, reference)
        if policy.status is not ProactiveTargetPolicyStatus.ACTIVE:
            raise validation_error("proactive_target_policy_inactive")
        if policy.activated_at > at or (
            policy.expires_at is not None and at >= policy.expires_at
        ):
            raise validation_error("proactive_target_policy_expired")
        return policy

    async def resolve_grant(
        self,
        reference: ProactiveAuthorizationGrantRef,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ProactiveAuthorizationGrant:
        _aware(at, "proactive_registry_at")
        _validate_call(call, at)
        if not isinstance(reference, ProactiveAuthorizationGrantRef):
            raise validation_error("invalid_proactive_grant_ref")
        grant = self._grants.get(reference.grant_id)
        if grant is None or grant.as_ref() != reference:
            raise validation_error("proactive_grant_not_found")
        _active_grant(grant, at)
        return grant

    async def validate_target(
        self,
        reference: ProactiveTargetPolicyRef,
        *,
        trigger_kind: ProactiveTriggerKind,
        categories: frozenset[SourceCategory],
        at: datetime,
        call: ServiceCallContext,
    ) -> ProactiveTargetPolicy:
        if not isinstance(trigger_kind, ProactiveTriggerKind) or any(
            not isinstance(value, SourceCategory) for value in categories
        ):
            raise validation_error("invalid_proactive_target_validation_input")
        policy = await self.resolve_target(reference, at=at, call=call)
        if trigger_kind not in policy.allowed_trigger_kinds:
            raise validation_error("proactive_trigger_kind_not_allowed")
        operator = await self.resolve_grant(
            policy.operator_authorization_grant_ref,
            at=at,
            call=call,
        )
        group = await self.resolve_grant(
            policy.group_policy_grant_ref,
            at=at,
            call=call,
        )
        validate_grant_ref(
            operator,
            policy.operator_authorization_grant_ref,
            expected_kind=ProactiveGrantKind.OPERATOR_ENABLE_TARGET,
        )
        validate_grant_ref(
            group,
            policy.group_policy_grant_ref,
            expected_kind=ProactiveGrantKind.GROUP_POLICY_ENABLE,
        )
        for grant in (operator, group):
            if (
                grant.target_scope_digest != reference.target_scope_digest
                or grant.policy_revision != policy.policy_revision
                or trigger_kind not in grant.allowed_trigger_kinds
                or not categories.issubset(grant.allowed_categories)
            ):
                raise validation_error("proactive_target_grant_binding_mismatch")
        return policy

    @staticmethod
    def _candidate(
        grants: Iterable[ProactiveAuthorizationGrant],
        policies: Iterable[ProactiveTargetPolicy],
    ) -> tuple[
        dict[str, ProactiveAuthorizationGrant],
        dict[str, ProactiveTargetPolicy],
    ]:
        try:
            grant_values = tuple(grants)
            policy_values = tuple(policies)
        except TypeError:
            raise validation_error("invalid_proactive_registry_content") from None
        if (
            not grant_values
            or not policy_values
            or any(
                not isinstance(value, ProactiveAuthorizationGrant)
                for value in grant_values
            )
            or any(
                not isinstance(value, ProactiveTargetPolicy) for value in policy_values
            )
        ):
            raise validation_error("invalid_proactive_registry_content")
        grant_map = {value.grant_id: value for value in grant_values}
        policy_map = {value.target_policy_id: value for value in policy_values}
        if len(grant_map) != len(grant_values) or len(policy_map) != len(policy_values):
            raise validation_error("duplicate_proactive_registry_id")
        for policy in policy_values:
            operator = grant_map.get(policy.operator_authorization_grant_ref.grant_id)
            group = grant_map.get(policy.group_policy_grant_ref.grant_id)
            if operator is None or group is None:
                raise validation_error("proactive_target_grant_not_found")
            validate_grant_ref(
                operator,
                policy.operator_authorization_grant_ref,
                expected_kind=ProactiveGrantKind.OPERATOR_ENABLE_TARGET,
            )
            validate_grant_ref(
                group,
                policy.group_policy_grant_ref,
                expected_kind=ProactiveGrantKind.GROUP_POLICY_ENABLE,
            )
            for grant in (operator, group):
                if (
                    grant.target_scope_digest != policy.as_ref().target_scope_digest
                    or grant.policy_revision != policy.policy_revision
                ):
                    raise validation_error("proactive_target_grant_binding_mismatch")
        return grant_map, policy_map

    def _now(self) -> datetime:
        try:
            return _aware(self._clock(), "proactive_registry_clock")
        except Exception as exc:
            if getattr(exc, "info", None) is not None:
                raise
            raise error(
                "proactive_registry_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None


def _active_grant(grant: ProactiveAuthorizationGrant, at: datetime) -> None:
    if grant.revoked_at is not None and at >= grant.revoked_at:
        raise validation_error("proactive_grant_revoked")
    if grant.issued_at > at or (
        grant.expires_at is not None and at >= grant.expires_at
    ):
        raise validation_error("proactive_grant_expired")


def _validate_call(call: ServiceCallContext, at: datetime) -> None:
    if not isinstance(call, ServiceCallContext):
        raise validation_error("invalid_proactive_service_call")
    if call.cancellation.is_cancelled:
        raise error(
            "proactive_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if call.deadline <= at:
        raise error(
            "proactive_call_deadline_exceeded",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


def _aware(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise validation_error("invalid_proactive_datetime", field_name)
    return value


__all__ = ["InMemoryProactiveTargetRegistry"]
