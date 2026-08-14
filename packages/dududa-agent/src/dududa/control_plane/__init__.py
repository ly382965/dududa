"""Governed Bot Control Plane contracts and application services."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .authorization import ControlPlaneAuthorizer
    from .contracts import (
        AssignmentStatus,
        CommandOutcome,
        CommandReceipt,
        ControlPlaneAuditRecord,
        GroupControlScope,
        GroupJoinFact,
        GroupOnboardingRecord,
        GroupServiceAssignment,
        GroupServicePreview,
        GroupServiceProfile,
        OnboardingStatus,
        OperatorSession,
        PendingInboxProjection,
        PendingInboxQuery,
        ProfileMemoryMode,
        ProfilePreviewCommand,
        ProfilePreviewExecution,
        ProfileRef,
        ServiceCatalogSnapshot,
        ServiceDefinition,
        ServiceEligibilityFact,
        ServiceResolution,
    )
    from .gateway import ControlPlaneGateway, GroupJoinService
    from .projector import ControlPlaneProjector
    from .repository import InMemoryGroupServiceRepository
    from .resolution import resolve_profile_services

__all__ = [
    "AssignmentStatus",
    "CommandOutcome",
    "CommandReceipt",
    "ControlPlaneAuditRecord",
    "ControlPlaneAuthorizer",
    "ControlPlaneGateway",
    "ControlPlaneProjector",
    "GroupControlScope",
    "GroupJoinFact",
    "GroupJoinService",
    "GroupOnboardingRecord",
    "GroupServiceAssignment",
    "GroupServicePreview",
    "GroupServiceProfile",
    "InMemoryGroupServiceRepository",
    "OnboardingStatus",
    "OperatorSession",
    "PendingInboxProjection",
    "PendingInboxQuery",
    "ProfileMemoryMode",
    "ProfilePreviewCommand",
    "ProfilePreviewExecution",
    "ProfileRef",
    "ServiceCatalogSnapshot",
    "ServiceDefinition",
    "ServiceEligibilityFact",
    "ServiceResolution",
    "resolve_profile_services",
]

_EXPORT_MODULES = {
    "AssignmentStatus": ".contracts",
    "CommandOutcome": ".contracts",
    "CommandReceipt": ".contracts",
    "ControlPlaneAuditRecord": ".contracts",
    "ControlPlaneAuthorizer": ".authorization",
    "ControlPlaneGateway": ".gateway",
    "ControlPlaneProjector": ".projector",
    "GroupControlScope": ".contracts",
    "GroupJoinFact": ".contracts",
    "GroupJoinService": ".gateway",
    "GroupOnboardingRecord": ".contracts",
    "GroupServiceAssignment": ".contracts",
    "GroupServicePreview": ".contracts",
    "GroupServiceProfile": ".contracts",
    "InMemoryGroupServiceRepository": ".repository",
    "OnboardingStatus": ".contracts",
    "OperatorSession": ".contracts",
    "PendingInboxProjection": ".contracts",
    "PendingInboxQuery": ".contracts",
    "ProfileMemoryMode": ".contracts",
    "ProfilePreviewCommand": ".contracts",
    "ProfilePreviewExecution": ".contracts",
    "ProfileRef": ".contracts",
    "ServiceCatalogSnapshot": ".contracts",
    "ServiceDefinition": ".contracts",
    "ServiceEligibilityFact": ".contracts",
    "ServiceResolution": ".contracts",
    "resolve_profile_services": ".resolution",
}


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
