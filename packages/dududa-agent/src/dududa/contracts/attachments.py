from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.attachments import AttachmentAccessRequest, AttachmentDeleteCommand
from dududa.domain.primitives import DigestString, JsonValue, ResourceRef
from dududa.security.digests import scope_digest


def attachment_access_resource(request: AttachmentAccessRequest) -> ResourceRef:
    return ResourceRef(
        "attachment",
        request.content_ref,
        scope_digest(request.conversation_scope),
    )


def attachment_access_authorization_metadata(
    request: AttachmentAccessRequest,
    *,
    run_id: str,
    policy_snapshot_id: str,
) -> dict[str, JsonValue]:
    intent = {
        "schema_version": request.schema_version,
        "content_ref": request.content_ref,
        "expected_content_digest": request.expected_content_digest,
        "conversation_scope": request.conversation_scope,
        "purpose": request.purpose,
        "accepted_media_types": request.accepted_media_types,
        "maximum_size_bytes": request.maximum_size_bytes,
    }
    return {
        "attachment_access_intent_digest": canonical_digest(
            intent,
            domain="attachment:access-intent:v1",
        ),
        "run_id": run_id,
        "policy_snapshot_id": policy_snapshot_id,
    }


def attachment_delete_resource(
    command: AttachmentDeleteCommand,
    *,
    scope: DigestString,
) -> ResourceRef:
    return ResourceRef("attachment", command.content_ref, scope)


def attachment_delete_authorization_metadata(
    command: AttachmentDeleteCommand,
    *,
    operation_id: str,
    policy_snapshot_id: str,
) -> dict[str, JsonValue]:
    intent = {
        "schema_version": command.schema_version,
        "content_ref": command.content_ref,
        "expected_content_digest": command.expected_content_digest,
        "reason": command.reason,
        "idempotency_key": command.idempotency_key,
    }
    return {
        "attachment_delete_intent_digest": canonical_digest(
            intent,
            domain="attachment:delete-intent:v1",
        ),
        "operation_id": operation_id,
        "policy_snapshot_id": policy_snapshot_id,
    }
