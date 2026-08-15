from __future__ import annotations

from datetime import datetime, timezone

from dududa.control_plane.contracts import (
    CommandReceipt,
    GroupControlScope,
    GroupServiceAssignment,
    GroupServiceMutationExecution,
    GroupServicePreview,
    GroupServiceProfile,
    ManagedGroupsProjection,
    PendingGroupProjection,
    PendingInboxProjection,
    ProfileCatalogProjection,
    ProfilePreviewExecution,
    ServiceResolution,
)
from dududa.control_plane.operations import (
    GovernedMutationDescriptor,
    GovernedOperationsProjection,
    OperationalFact,
    OperationalProjection,
    OperationalScope,
)
from dududa.errors import validation_error


def project_pending_inbox(value: PendingInboxProjection) -> dict[str, object]:
    return {
        "platform": value.platform,
        "botId": value.bot_id,
        "items": [_pending_group(item) for item in value.items],
        "generatedAt": _timestamp(value.generated_at),
    }


def project_managed_groups(value: ManagedGroupsProjection) -> dict[str, object]:
    return {
        "platform": value.platform,
        "botId": value.bot_id,
        "items": [
            {
                "onboarding": _pending_group(item.onboarding),
                "assignment": _assignment(item.assignment),
            }
            for item in value.items
        ],
        "generatedAt": _timestamp(value.generated_at),
    }


def project_profile_catalog(value: ProfileCatalogProjection) -> dict[str, object]:
    return {
        "revision": value.revision,
        "profiles": [_profile(profile) for profile in value.profiles],
        "generatedAt": _timestamp(value.generated_at),
    }


def project_preview_execution(value: ProfilePreviewExecution) -> dict[str, object]:
    preview = value.preview
    digest = value.receipt.result_digest
    if preview is None or digest is None:
        raise validation_error("successful_web_preview_projection_requires_result")
    return {
        "preview": _preview(preview, str(digest)),
        "onboardingRevision": value.onboarding_revision,
        "receipt": _receipt(value.receipt),
    }


def project_mutation_execution(
    value: GroupServiceMutationExecution,
) -> dict[str, object]:
    return {
        "assignment": _assignment(value.assignment),
        "receipt": _receipt(value.receipt),
    }


def project_governed_operations(
    value: GovernedOperationsProjection,
) -> dict[str, object]:
    return {
        "scope": _operational_scope(value.scope),
        "projections": [_operational_projection(item) for item in value.projections],
        "mutations": [_governed_mutation(item) for item in value.mutations],
        "generatedAt": _timestamp(value.generated_at),
    }


def _scope(value: GroupControlScope) -> dict[str, object]:
    return {
        "platform": value.platform,
        "botId": value.bot_id,
        "groupId": value.group_id,
    }


def _operational_scope(value: OperationalScope) -> dict[str, object]:
    result: dict[str, object] = {
        "platform": value.platform,
        "botId": value.bot_id,
    }
    if value.group_id is not None:
        result["groupId"] = value.group_id
    return result


def _operational_fact(value: OperationalFact) -> dict[str, object]:
    return {
        "factId": value.fact_id,
        "label": value.label,
        "status": value.status.value,
        "revision": value.revision,
        "detail": value.detail,
        "reasonCodes": list(value.reason_codes),
        "observedAt": _timestamp(value.observed_at),
    }


def _operational_projection(value: OperationalProjection) -> dict[str, object]:
    return {
        "surface": value.surface.value,
        "scope": _operational_scope(value.scope),
        "revision": value.revision,
        "evidenceMode": value.evidence_mode.value,
        "status": value.status.value,
        "facts": [_operational_fact(item) for item in value.facts],
        "reasonCodes": list(value.reason_codes),
        "observedAt": _timestamp(value.observed_at),
    }


def _governed_mutation(value: GovernedMutationDescriptor) -> dict[str, object]:
    return {
        "action": str(value.action),
        "displayName": value.display_name,
        "handlerId": value.handler_id,
        "scopeKind": value.scope_kind.value,
        "riskLevel": value.risk_level.value,
    }


def _pending_group(value: PendingGroupProjection) -> dict[str, object]:
    result: dict[str, object] = {
        "scope": _scope(value.scope),
        "status": value.status.value,
        "revision": value.revision,
        "firstSeenAt": _timestamp(value.first_seen_at),
        "updatedAt": _timestamp(value.updated_at),
    }
    if value.preview_id is not None:
        result["previewId"] = value.preview_id
    return result


def _profile(value: GroupServiceProfile) -> dict[str, object]:
    return {
        "profileId": value.profile_id,
        "revision": value.revision,
        "displayName": value.display_name,
        "requestedServiceIds": list(value.requested_service_ids),
        "personaRef": value.persona_ref,
        "triggerPolicyRef": value.trigger_policy_ref,
        "responsePolicyRef": value.response_policy_ref,
        "modelBudgetPolicyRef": value.model_budget_policy_ref,
        "memoryMode": value.memory_mode.value,
        "proactiveDefaultEnabled": value.proactive_default_enabled,
        "strictServices": value.strict_services,
    }


def _resolution(value: ServiceResolution) -> dict[str, object]:
    return {
        "serviceId": value.service_id,
        "eligible": value.eligible,
        "reasonCodes": list(value.reason_codes),
    }


def _preview(value: GroupServicePreview, digest: str) -> dict[str, object]:
    result: dict[str, object] = {
        "previewId": value.preview_id,
        "scope": _scope(value.scope),
        "profileId": value.profile_ref.profile_id,
        "profileRevision": value.profile_ref.revision,
        "previewDigest": digest,
        "onboardingRevision": value.onboarding_revision,
        "catalogRevision": value.catalog_revision,
        "desiredServiceIds": list(value.desired_service_ids),
        "effectiveServiceIds": list(value.effective_service_ids),
        "resolutions": [_resolution(item) for item in value.resolutions],
        "expiresAt": _timestamp(value.expires_at),
    }
    if value.assignment_revision is not None:
        result["assignmentRevision"] = value.assignment_revision
    return result


def _assignment(value: GroupServiceAssignment) -> dict[str, object]:
    result: dict[str, object] = {
        "scope": _scope(value.scope),
        "assignmentRevision": value.assignment_revision,
        "status": value.status.value,
        "profileId": value.profile_ref.profile_id,
        "profileRevision": value.profile_ref.revision,
        "desiredServiceIds": list(value.desired_service_ids),
        "effectiveServiceIds": list(value.effective_service_ids),
        "lastKnownGoodRevision": value.last_known_good_revision,
        "activatedAt": _timestamp(value.activated_at),
    }
    if value.previous_revision is not None:
        result["previousRevision"] = value.previous_revision
    return result


def _receipt(value: CommandReceipt) -> dict[str, object]:
    return {
        "receiptId": value.receipt_id,
        "commandId": value.command_id,
        "action": str(value.action),
        "outcome": value.outcome.value,
        "reasonCodes": list(value.reason_codes),
        "committedAt": _timestamp(value.committed_at),
    }


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "project_governed_operations",
    "project_managed_groups",
    "project_mutation_execution",
    "project_pending_inbox",
    "project_preview_execution",
    "project_profile_catalog",
]
