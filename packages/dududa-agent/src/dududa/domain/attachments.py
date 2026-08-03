from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dududa._compat import StrEnum
from dududa.security.models import AuthorizationDecision

from .identity import ConversationScope
from .primitives import (
    ComponentRevision,
    DigestString,
    Sensitivity,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error


class AttachmentPurpose(StrEnum):
    PREPROCESS = "preprocess"
    MODEL_INPUT = "model_input"
    OUTPUT_DELIVERY = "output_delivery"


class AttachmentOrigin(StrEnum):
    PLATFORM_INPUT = "platform_input"
    MODEL_GENERATED = "model_generated"
    TOOL_GENERATED = "tool_generated"


@dataclass(frozen=True, slots=True)
class AttachmentIngestRequest:
    schema_version: int
    content_id: str
    origin: AttachmentOrigin
    scope_digest: DigestString
    declared_media_type: str
    declared_size_bytes: int | None
    maximum_size_bytes: int
    sensitivity: Sensitivity
    expires_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.content_id, "content_id")
        require_non_empty(str(self.scope_digest), "scope_digest")
        require_non_empty(self.declared_media_type, "declared_media_type")
        require_non_empty(self.idempotency_key, "idempotency_key")
        if not isinstance(self.origin, AttachmentOrigin):
            raise validation_error("invalid_attachment_origin")
        if not isinstance(self.sensitivity, Sensitivity):
            raise validation_error("invalid_sensitivity")
        if self.declared_size_bytes is not None and self.declared_size_bytes < 0:
            raise validation_error("negative_attachment_size")
        if self.maximum_size_bytes < 1:
            raise validation_error("invalid_attachment_size_limit")
        if (
            self.declared_size_bytes is not None
            and self.declared_size_bytes > self.maximum_size_bytes
        ):
            raise validation_error("declared_attachment_oversize")
        require_aware(self.expires_at, "expires_at")


@dataclass(frozen=True, slots=True)
class StoredContentRef:
    schema_version: int
    content_ref: str
    content_digest: DigestString
    media_type: str
    size_bytes: int
    repository_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _opaque_ref(self.content_ref)
        require_non_empty(str(self.content_digest), "content_digest")
        require_non_empty(self.media_type, "media_type")
        if self.size_bytes < 0:
            raise validation_error("negative_attachment_size")


@dataclass(frozen=True, slots=True)
class AttachmentAccessRequest:
    schema_version: int
    content_ref: str
    expected_content_digest: DigestString
    conversation_scope: ConversationScope
    purpose: AttachmentPurpose
    accepted_media_types: frozenset[str]
    maximum_size_bytes: int
    authorization: AuthorizationDecision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _opaque_ref(self.content_ref)
        require_non_empty(str(self.expected_content_digest), "expected_content_digest")
        if not isinstance(self.purpose, AttachmentPurpose):
            raise validation_error("invalid_attachment_purpose")
        accepted = frozenset(self.accepted_media_types)
        if not accepted or any(not item.strip() for item in accepted):
            raise validation_error("invalid_accepted_media_types")
        if self.maximum_size_bytes < 1:
            raise validation_error("invalid_attachment_size_limit")
        object.__setattr__(self, "accepted_media_types", accepted)


@dataclass(frozen=True, slots=True)
class AttachmentDescriptor:
    schema_version: int
    content_ref: str
    content_digest: DigestString
    media_type: str
    size_bytes: int
    scope_digest: DigestString
    sensitivity: Sensitivity
    created_at: datetime
    expires_at: datetime
    repository_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _opaque_ref(self.content_ref)
        require_non_empty(str(self.content_digest), "content_digest")
        require_non_empty(self.media_type, "media_type")
        require_non_empty(str(self.scope_digest), "scope_digest")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise validation_error("negative_attachment_size")
        if not isinstance(self.sensitivity, Sensitivity):
            raise validation_error("invalid_sensitivity")
        require_aware(self.created_at, "created_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise validation_error("invalid_attachment_expiry")


@dataclass(frozen=True, slots=True)
class AttachmentDeleteCommand:
    schema_version: int
    content_ref: str
    expected_content_digest: DigestString
    reason: str
    authorization: AuthorizationDecision
    idempotency_key: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _opaque_ref(self.content_ref)
        require_non_empty(str(self.expected_content_digest), "expected_content_digest")
        require_non_empty(self.reason, "reason")
        require_non_empty(self.idempotency_key, "idempotency_key")


@dataclass(frozen=True, slots=True)
class AttachmentDeleteReceipt:
    schema_version: int
    content_ref: str
    deleted: bool
    repository_revision: ComponentRevision
    deleted_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _opaque_ref(self.content_ref)
        if type(self.deleted) is not bool:
            raise validation_error("invalid_attachment_delete_result")
        require_aware(self.deleted_at, "deleted_at")


def _opaque_ref(value: str) -> None:
    require_non_empty(value, "content_ref")
    if "://" in value or "/" in value or "\\" in value or ".." in value:
        raise validation_error("non_opaque_content_ref")


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
