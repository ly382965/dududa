from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import Actor
from dududa.domain.primitives import DigestString
from dududa.security.digests import actor_digest

from .contracts import (
    GroupControlScope,
    GroupServiceAssignment,
    GroupServicePreview,
    GroupServiceProfile,
    ProfilePreviewCommand,
    ProfileRef,
)


def group_control_scope_digest(scope: GroupControlScope) -> DigestString:
    return canonical_digest(scope, domain="control-plane:group-scope:v1")


def group_service_profile_digest(profile: GroupServiceProfile) -> DigestString:
    return canonical_digest(profile, domain="control-plane:service-profile:v1")


def profile_ref_digest(profile_ref: ProfileRef) -> DigestString:
    return canonical_digest(profile_ref, domain="control-plane:profile-ref:v1")


def preview_command_payload_digest(command: ProfilePreviewCommand) -> DigestString:
    return canonical_digest(
        {
            "schema_version": command.schema_version,
            "scope": command.scope,
            "action": command.action,
            "expected_onboarding_revision": command.expected_onboarding_revision,
            "profile_ref": command.profile_ref,
        },
        domain="control-plane:preview-payload:v1",
    )


def preview_command_request_digest(
    command: ProfilePreviewCommand,
    actor: Actor,
) -> DigestString:
    return canonical_digest(
        {
            "schema_version": command.schema_version,
            "command_id": command.command_id,
            "idempotency_key": command.idempotency_key,
            "actor_digest": actor_digest(actor),
            "scope": command.scope,
            "action": command.action,
            "expected_onboarding_revision": command.expected_onboarding_revision,
            "profile_ref": command.profile_ref,
            "payload_digest": command.payload_digest,
            "requested_at": command.requested_at,
        },
        domain="control-plane:preview-command:v1",
    )


def group_service_preview_digest(preview: GroupServicePreview) -> DigestString:
    return canonical_digest(preview, domain="control-plane:service-preview:v1")


def group_service_assignment_digest(
    assignment: GroupServiceAssignment,
) -> DigestString:
    return canonical_digest(assignment, domain="control-plane:assignment:v1")


__all__ = [
    "group_control_scope_digest",
    "group_service_assignment_digest",
    "group_service_preview_digest",
    "group_service_profile_digest",
    "preview_command_payload_digest",
    "preview_command_request_digest",
    "profile_ref_digest",
]
