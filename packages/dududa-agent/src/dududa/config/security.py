from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Mapping

from dududa.domain.primitives import RiskLevel
from dududa.errors import validation_error
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
)


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    schema_version: int
    authorization: AuthorizationPolicyConfig
    interaction_limits: Mapping[str, int]
    redaction_maximum_characters: int


def parse_security_config(value: object) -> SecurityConfig:
    if not isinstance(value, Mapping):
        raise validation_error("security_config_not_mapping")
    allowed = {
        "schema_version",
        "policy_revision",
        "role_permissions",
        "role_constraints",
        "confirmation_actions",
        "confirmation_risks",
        "deny_flags",
        "decision_ttl_seconds",
        "interaction_limits",
        "redaction_maximum_characters",
    }
    unknown = set(value) - allowed
    if unknown:
        raise validation_error(
            "unknown_security_config_field", *sorted(map(str, unknown))
        )
    if type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
        raise validation_error("unsupported_security_config_version")
    revision = value.get("policy_revision")
    if not isinstance(revision, str) or not revision.strip():
        raise validation_error("invalid_security_policy_revision")
    raw_permissions = value.get("role_permissions")
    if not isinstance(raw_permissions, Mapping):
        raise validation_error("invalid_role_permissions")
    permissions: dict[str, frozenset[str]] = {}
    for role, actions in raw_permissions.items():
        if (
            not isinstance(role, str)
            or not role.strip()
            or not isinstance(actions, (list, tuple, set, frozenset))
        ):
            raise validation_error("invalid_role_permissions")
        if any(not isinstance(action, str) or not action.strip() for action in actions):
            raise validation_error("invalid_role_permissions")
        permissions[role] = frozenset(actions)
    constraints = _parse_role_constraints(value.get("role_constraints"))
    confirmation_actions = _string_set(
        value.get("confirmation_actions", ()), "confirmation_actions"
    )
    deny_flags = _string_set(
        value.get("deny_flags", ("muted", "blocked")), "deny_flags"
    )
    raw_risks = _string_set(
        value.get("confirmation_risks", ("high", "critical")), "confirmation_risks"
    )
    try:
        confirmation_risks = frozenset(RiskLevel(item) for item in raw_risks)
    except ValueError:
        raise validation_error("invalid_confirmation_risk") from None
    ttl = value.get("decision_ttl_seconds", 60)
    maximum = value.get("redaction_maximum_characters", 2048)
    limits = value.get("interaction_limits", {})
    if type(ttl) is not int or ttl < 1 or ttl > 3600:
        raise validation_error("invalid_decision_ttl")
    if type(maximum) is not int or maximum < 64 or maximum > 65536:
        raise validation_error("invalid_redaction_limit")
    if not isinstance(limits, Mapping) or any(
        not isinstance(key, str) or not key.strip() or type(item) is not int or item < 0
        for key, item in limits.items()
    ):
        raise validation_error("invalid_interaction_limits")
    authorization = AuthorizationPolicyConfig(
        policy_revision=revision,
        role_permissions=permissions,
        role_constraints=constraints,
        confirmation_actions=confirmation_actions,
        confirmation_risks=confirmation_risks,
        deny_flags=deny_flags,
        decision_ttl=timedelta(seconds=ttl),
    )
    return SecurityConfig(
        1,
        authorization,
        MappingProxyType(dict(limits)),
        maximum,
    )


def _string_set(value: object, field: str) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise validation_error(f"invalid_{field}")
    return frozenset(value)


def _parse_role_constraints(
    value: object,
) -> dict[str, dict[str, AuthorizationConstraint]]:
    if not isinstance(value, Mapping):
        raise validation_error("invalid_role_constraints")
    result: dict[str, dict[str, AuthorizationConstraint]] = {}
    try:
        for role, raw_actions in value.items():
            if (
                not isinstance(role, str)
                or not role.strip()
                or not isinstance(raw_actions, Mapping)
            ):
                raise ValueError
            actions: dict[str, AuthorizationConstraint] = {}
            for action, raw in raw_actions.items():
                if (
                    not isinstance(action, str)
                    or not action.strip()
                    or not isinstance(raw, Mapping)
                ):
                    raise ValueError
                allowed = {
                    "resource_types",
                    "resource_ids",
                    "capability_ids",
                    "allow_without_capability",
                    "maximum_risk",
                    "required_metadata",
                }
                if set(raw) - allowed:
                    raise ValueError
                raw_metadata = raw.get("required_metadata", {})
                if not isinstance(raw_metadata, Mapping):
                    raise ValueError
                allow_without = raw.get("allow_without_capability", True)
                if type(allow_without) is not bool:
                    raise ValueError
                actions[action] = AuthorizationConstraint(
                    _string_set(raw.get("resource_types"), "resource_types"),
                    _string_set(raw.get("resource_ids"), "resource_ids"),
                    _string_set(raw.get("capability_ids", ()), "capability_ids"),
                    allow_without,
                    RiskLevel(str(raw.get("maximum_risk", "critical"))),
                    dict(raw_metadata),
                )
            result[role] = actions
    except (TypeError, ValueError):
        raise validation_error("invalid_role_constraints") from None
    return result
