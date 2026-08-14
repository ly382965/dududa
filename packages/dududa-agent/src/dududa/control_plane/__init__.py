"""Governed Bot Control Plane contracts and application services."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import ControlPlaneApi
    from .authorization import ControlPlaneAuthorizer
    from .contracts import (
        AssignmentCommitDisposition,
        AssignmentCommitResult,
        AssignmentStatus,
        CommandOutcome,
        CommandReceipt,
        ControlPlaneAuditRecord,
        GroupControlScope,
        GroupJoinFact,
        GroupOnboardingRecord,
        GroupServiceAssignment,
        GroupServiceMutationCommand,
        GroupServiceMutationExecution,
        GroupServicePreview,
        GroupServiceProfile,
        ManagedGroupProjection,
        ManagedGroupsProjection,
        ManagedGroupsQuery,
        OnboardingStatus,
        OperatorSession,
        PendingInboxProjection,
        PendingInboxQuery,
        ProfileCatalogProjection,
        ProfileCatalogQuery,
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
    from .lifecycle import GroupServiceLifecycle
    from .projector import ControlPlaneProjector
    from .repository import InMemoryGroupServiceRepository
    from .resolution import resolve_profile_services
    from .snapshot import RepositoryGroupServiceSnapshotProvider
    from .sqlite_repository import (
        SQLiteGroupServiceRepository,
        SQLiteGroupServiceRepositoryConfig,
    )

__all__ = [
    "AssignmentCommitDisposition",
    "AssignmentCommitResult",
    "AssignmentStatus",
    "CommandOutcome",
    "CommandReceipt",
    "ControlPlaneApi",
    "ControlPlaneAuditRecord",
    "ControlPlaneAuthorizer",
    "ControlPlaneGateway",
    "ControlPlaneProjector",
    "GroupControlScope",
    "GroupJoinFact",
    "GroupJoinService",
    "GroupOnboardingRecord",
    "GroupServiceAssignment",
    "GroupServiceLifecycle",
    "GroupServiceMutationCommand",
    "GroupServiceMutationExecution",
    "GroupServicePreview",
    "GroupServiceProfile",
    "InMemoryGroupServiceRepository",
    "ManagedGroupProjection",
    "ManagedGroupsProjection",
    "ManagedGroupsQuery",
    "OnboardingStatus",
    "OperatorSession",
    "PendingInboxProjection",
    "PendingInboxQuery",
    "ProfileCatalogProjection",
    "ProfileCatalogQuery",
    "ProfileMemoryMode",
    "ProfilePreviewCommand",
    "ProfilePreviewExecution",
    "ProfileRef",
    "RepositoryGroupServiceSnapshotProvider",
    "SQLiteGroupServiceRepository",
    "SQLiteGroupServiceRepositoryConfig",
    "ServiceCatalogSnapshot",
    "ServiceDefinition",
    "ServiceEligibilityFact",
    "ServiceResolution",
    "resolve_profile_services",
]

_EXPORT_MODULES = {
    "AssignmentCommitDisposition": ".contracts",
    "AssignmentCommitResult": ".contracts",
    "AssignmentStatus": ".contracts",
    "CommandOutcome": ".contracts",
    "CommandReceipt": ".contracts",
    "ControlPlaneAuditRecord": ".contracts",
    "ControlPlaneApi": ".api",
    "ControlPlaneAuthorizer": ".authorization",
    "ControlPlaneGateway": ".gateway",
    "ControlPlaneProjector": ".projector",
    "GroupControlScope": ".contracts",
    "GroupJoinFact": ".contracts",
    "GroupJoinService": ".gateway",
    "GroupOnboardingRecord": ".contracts",
    "GroupServiceAssignment": ".contracts",
    "GroupServiceLifecycle": ".lifecycle",
    "GroupServiceMutationCommand": ".contracts",
    "GroupServiceMutationExecution": ".contracts",
    "GroupServicePreview": ".contracts",
    "GroupServiceProfile": ".contracts",
    "InMemoryGroupServiceRepository": ".repository",
    "ManagedGroupProjection": ".contracts",
    "ManagedGroupsProjection": ".contracts",
    "ManagedGroupsQuery": ".contracts",
    "OnboardingStatus": ".contracts",
    "OperatorSession": ".contracts",
    "PendingInboxProjection": ".contracts",
    "PendingInboxQuery": ".contracts",
    "ProfileCatalogProjection": ".contracts",
    "ProfileCatalogQuery": ".contracts",
    "ProfileMemoryMode": ".contracts",
    "ProfilePreviewCommand": ".contracts",
    "ProfilePreviewExecution": ".contracts",
    "ProfileRef": ".contracts",
    "RepositoryGroupServiceSnapshotProvider": ".snapshot",
    "SQLiteGroupServiceRepository": ".sqlite_repository",
    "SQLiteGroupServiceRepositoryConfig": ".sqlite_repository",
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
