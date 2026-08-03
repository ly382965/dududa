from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Mapping
import uuid

from dududa.domain.primitives import (
    JsonValue,
    RiskLevel,
    freeze_json,
)
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext

from .digests import (
    actor_digest,
    authorization_metadata_digest,
    authorization_request_digest,
    resource_digest,
    scope_digest,
)
from .models import AuthorizationDecision, AuthorizationEffect, AuthorizationRequest


@dataclass(frozen=True, slots=True)
class AuthorizationConstraint:
    resource_types: frozenset[str]
    resource_ids: frozenset[str]
    capability_ids: frozenset[str] = frozenset()
    allow_without_capability: bool = True
    maximum_risk: RiskLevel = RiskLevel.CRITICAL
    required_metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        resource_types = frozenset(self.resource_types)
        resource_ids = frozenset(self.resource_ids)
        capability_ids = frozenset(self.capability_ids)
        if (
            not resource_types
            or not resource_ids
            or any(
                not item.strip()
                for item in resource_types | resource_ids | capability_ids
            )
            or type(self.allow_without_capability) is not bool
            or not isinstance(self.maximum_risk, RiskLevel)
        ):
            raise ValueError("invalid authorization constraint")
        object.__setattr__(self, "resource_types", resource_types)
        object.__setattr__(self, "resource_ids", resource_ids)
        object.__setattr__(self, "capability_ids", capability_ids)
        object.__setattr__(
            self,
            "required_metadata",
            freeze_json(dict(self.required_metadata)),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationPolicyConfig:
    policy_revision: str
    role_permissions: Mapping[str, frozenset[str]]
    role_constraints: Mapping[
        str,
        Mapping[str, AuthorizationConstraint],
    ] = field(default_factory=dict)
    confirmation_actions: frozenset[str] = frozenset()
    confirmation_risks: frozenset[RiskLevel] = frozenset(
        {RiskLevel.HIGH, RiskLevel.CRITICAL}
    )
    deny_flags: frozenset[str] = frozenset({"muted", "blocked"})
    decision_ttl: timedelta = timedelta(minutes=1)

    def __post_init__(self) -> None:
        if not self.policy_revision.strip() or self.decision_ttl <= timedelta(0):
            raise ValueError("invalid authorization policy config")
        frozen = {
            str(role): frozenset(str(action) for action in actions)
            for role, actions in self.role_permissions.items()
        }
        object.__setattr__(self, "role_permissions", MappingProxyType(frozen))
        constraints = {
            str(role): MappingProxyType(dict(actions))
            for role, actions in self.role_constraints.items()
        }
        object.__setattr__(
            self,
            "role_constraints",
            MappingProxyType(constraints),
        )
        object.__setattr__(
            self, "confirmation_actions", frozenset(self.confirmation_actions)
        )
        object.__setattr__(
            self, "confirmation_risks", frozenset(self.confirmation_risks)
        )
        object.__setattr__(self, "deny_flags", frozenset(self.deny_flags))


class RoleAuthorizationPolicy:
    def __init__(
        self,
        config: AuthorizationPolicyConfig,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._issued_decisions: dict[str, AuthorizationDecision] = {}

    async def decide(
        self,
        request: AuthorizationRequest,
        *,
        call: PortCallContext,
    ) -> AuthorizationDecision:
        expected = authorization_request_digest(request)
        if expected != request.request_digest:
            raise error(
                "authorization_request_digest_mismatch",
                ErrorCategory.AUTHORIZATION,
                "security.denied",
            )
        now = self._clock()
        if call.cancellation.is_cancelled or call.deadline <= now:
            raise error(
                "authorization_call_cancelled_or_expired",
                ErrorCategory.AUTHORIZATION,
                "security.denied",
            )
        actor_hash = actor_digest(request.actor)
        scope_hash = scope_digest(request.conversation_scope)
        resource_hash = resource_digest(request.resource)
        metadata_hash = authorization_metadata_digest(request.metadata)

        effect = AuthorizationEffect.DENY
        reasons: tuple[str, ...] = ("default_deny",)
        if request.resource.scope_digest != scope_hash:
            reasons = ("resource_scope_mismatch",)
        elif any(
            str(flag) in self._config.deny_flags for flag in request.actor.deny_flags
        ):
            reasons = ("actor_denied",)
        else:
            action = str(request.action)
            permitted = False
            constraints: list[AuthorizationConstraint] = []
            for role in request.actor.roles:
                role_permissions = self._config.role_permissions.get(
                    str(role),
                    frozenset(),
                )
                if action not in role_permissions and "*" not in role_permissions:
                    continue
                permitted = True
                role_constraints = self._config.role_constraints.get(str(role), {})
                action_constraint = role_constraints.get(action)
                wildcard_constraint = role_constraints.get("*")
                if action_constraint is not None:
                    constraints.append(action_constraint)
                if wildcard_constraint is not None:
                    constraints.append(wildcard_constraint)
            if permitted:
                if not any(_constraint_matches(item, request) for item in constraints):
                    reasons = ("resource_or_capability_denied",)
                elif (
                    action in self._config.confirmation_actions
                    or request.risk_level in self._config.confirmation_risks
                ):
                    effect = AuthorizationEffect.REQUIRE_CONFIRMATION
                    reasons = ("confirmation_required",)
                else:
                    effect = AuthorizationEffect.ALLOW
                    reasons = ("role_permission",)
        decision = AuthorizationDecision(
            schema_version=1,
            decision_id=self._id_factory(),
            effect=effect,
            request_digest=request.request_digest,
            actor_digest=actor_hash,
            scope_digest=scope_hash,
            action=request.action,
            resource_digest=resource_hash,
            capability_id=request.capability_id,
            risk_level=request.risk_level,
            metadata_digest=metadata_hash,
            policy_revision=self._config.policy_revision,
            reason_codes=reasons,
            decided_at=now,
            expires_at=now + self._config.decision_ttl,
        )
        self._issued_decisions[decision.decision_id] = decision
        return decision

    def verify(
        self,
        decision: AuthorizationDecision,
        *,
        at: datetime | None = None,
    ) -> bool:
        now = at or self._clock()
        return (
            self._issued_decisions.get(decision.decision_id) == decision
            and decision.policy_revision == self._config.policy_revision
            and decision.decided_at <= now < decision.expires_at
        )


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


def _constraint_matches(
    constraint: AuthorizationConstraint,
    request: AuthorizationRequest,
) -> bool:
    resource = request.resource
    if (
        resource.resource_type not in constraint.resource_types
        and "*" not in constraint.resource_types
    ):
        return False
    if (
        resource.resource_id not in constraint.resource_ids
        and "*" not in constraint.resource_ids
    ):
        return False
    if _RISK_ORDER[request.risk_level] > _RISK_ORDER[constraint.maximum_risk]:
        return False
    if request.capability_id is None:
        if not constraint.allow_without_capability:
            return False
    elif (
        request.capability_id not in constraint.capability_ids
        and "*" not in constraint.capability_ids
    ):
        return False
    return all(
        key in request.metadata and request.metadata[key] == value
        for key, value in constraint.required_metadata.items()
    )


@dataclass(frozen=True, slots=True)
class LegacyActorInput:
    user_id: str
    group_id: str
    is_platform_admin: bool


@dataclass(frozen=True, slots=True)
class LegacyRolePolicy:
    owners: frozenset[str] = field(default_factory=frozenset)
    global_admins: frozenset[str] = field(default_factory=frozenset)
    trusted_users: frozenset[str] = field(default_factory=frozenset)
    muted_users: frozenset[str] = field(default_factory=frozenset)
    group_admins: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("owners", "global_admins", "trusted_users", "muted_users"):
            object.__setattr__(self, name, frozenset(getattr(self, name)))
        object.__setattr__(
            self,
            "group_admins",
            MappingProxyType(
                {group: frozenset(users) for group, users in self.group_admins.items()}
            ),
        )

    def resolve(self, actor: LegacyActorInput) -> str:
        if actor.user_id in self.muted_users:
            return "muted_user"
        if actor.user_id in self.owners:
            return "owner"
        if actor.user_id in self.global_admins:
            return "admin"
        if actor.group_id and actor.user_id in self.group_admins.get(
            actor.group_id, frozenset()
        ):
            return "admin"
        if actor.is_platform_admin:
            return "admin"
        if actor.user_id in self.trusted_users:
            return "trusted_user"
        return "normal_user"
