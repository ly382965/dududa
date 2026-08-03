"""Deterministic authorization, confirmation, limits, redaction, and audit."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .authorization import (
        AuthorizationConstraint,
        AuthorizationPolicyConfig,
        LegacyActorInput,
        LegacyRolePolicy,
        RoleAuthorizationPolicy,
    )
    from .models import (
        AuditEvent,
        AuditReceipt,
        AuthorizationDecision,
        AuthorizationEffect,
        AuthorizationRequest,
        BudgetLease,
        BudgetReceipt,
        BudgetReservationRequest,
        ConfirmationConsumeRequest,
        ConfirmationGrant,
        ConfirmationRequest,
        ConfirmationRequirement,
        InteractionLease,
        InteractionLeaseReceipt,
        InteractionLimitRequest,
        RedactionRequest,
        RedactionResult,
    )

__all__ = [
    "AuditEvent",
    "AuditReceipt",
    "AuthorizationDecision",
    "AuthorizationEffect",
    "AuthorizationPolicyConfig",
    "AuthorizationConstraint",
    "AuthorizationRequest",
    "BudgetLease",
    "BudgetReceipt",
    "BudgetReservationRequest",
    "ConfirmationConsumeRequest",
    "ConfirmationGrant",
    "ConfirmationRequest",
    "ConfirmationRequirement",
    "InteractionLease",
    "InteractionLeaseReceipt",
    "InteractionLimitRequest",
    "LegacyActorInput",
    "LegacyRolePolicy",
    "RedactionRequest",
    "RedactionResult",
    "RoleAuthorizationPolicy",
]

_AUTHORIZATION_EXPORTS = frozenset(
    {
        "AuthorizationPolicyConfig",
        "AuthorizationConstraint",
        "LegacyActorInput",
        "LegacyRolePolicy",
        "RoleAuthorizationPolicy",
    }
)
_MODEL_EXPORTS = frozenset(__all__) - _AUTHORIZATION_EXPORTS


def __getattr__(name: str) -> object:
    if name in _AUTHORIZATION_EXPORTS:
        return getattr(import_module(".authorization", __name__), name)
    if name in _MODEL_EXPORTS:
        return getattr(import_module(".models", __name__), name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
