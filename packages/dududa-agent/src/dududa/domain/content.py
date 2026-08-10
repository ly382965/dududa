from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.errors import validation_error

from .identity import ResolvedIdentityRef
from .message import MessageReference
from .primitives import (
    ComponentRevision,
    DigestString,
    JsonValue,
    ResponseConstraints,
    Sensitivity,
    freeze_json,
    require_aware,
    require_non_empty,
)


@dataclass(frozen=True, slots=True)
class ContentBlock:
    block_id: str
    kind: str
    content: JsonValue
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.block_id, "block_id")
        require_non_empty(self.kind, "kind")
        object.__setattr__(self, "content", freeze_json(self.content))
        object.__setattr__(self, "source_refs", tuple(self.source_refs))


@dataclass(frozen=True, slots=True)
class FactAnchor:
    anchor_id: str
    value: JsonValue
    source_ids: tuple[str, ...]
    exact: bool

    def __post_init__(self) -> None:
        require_non_empty(self.anchor_id, "anchor_id")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "source_ids", tuple(self.source_ids))


@dataclass(frozen=True, slots=True)
class Citation:
    citation_id: str
    label: str
    source_ref: str


@dataclass(frozen=True, slots=True)
class UncertaintyNote:
    note_id: str
    message_key: str


@dataclass(frozen=True, slots=True)
class SafetyNotice:
    notice_id: str
    message_key: str


@dataclass(frozen=True, slots=True)
class Refusal:
    reason_code: str
    public_message_key: str


@dataclass(frozen=True, slots=True)
class GeneratedAssetRef:
    asset_id: str
    content_ref: str
    content_digest: DigestString
    media_type: str
    sensitivity: Sensitivity


@dataclass(frozen=True, slots=True)
class DraftResponse:
    schema_version: int
    response_id: str
    producer: ComponentRevision
    intent: str
    content_blocks: tuple[ContentBlock, ...]
    fact_anchors: tuple[FactAnchor, ...] = ()
    citations: tuple[Citation, ...] = ()
    uncertainty: tuple[UncertaintyNote, ...] = ()
    warnings: tuple[SafetyNotice, ...] = ()
    refusal: Refusal | None = None
    target_users: tuple[ResolvedIdentityRef, ...] = ()
    attachments: tuple[GeneratedAssetRef, ...] = ()
    immutable_constraints: ResponseConstraints = field(
        default_factory=ResponseConstraints
    )
    response_plan_digest: DigestString | None = None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.response_id, "response_id")
        require_non_empty(self.intent, "intent")
        content_blocks = tuple(self.content_blocks)
        fact_anchors = tuple(self.fact_anchors)
        citations = tuple(self.citations)
        uncertainty = tuple(self.uncertainty)
        warnings = tuple(self.warnings)
        target_users = tuple(self.target_users)
        attachments = tuple(self.attachments)
        if not content_blocks and self.refusal is None:
            raise validation_error("empty_draft_response")
        _ensure_unique((item.block_id for item in content_blocks), "block_id")
        _ensure_unique((item.anchor_id for item in fact_anchors), "anchor_id")
        object.__setattr__(self, "content_blocks", content_blocks)
        object.__setattr__(self, "fact_anchors", fact_anchors)
        object.__setattr__(self, "citations", citations)
        object.__setattr__(self, "uncertainty", uncertainty)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "target_users", target_users)
        object.__setattr__(self, "attachments", attachments)
        if self.response_plan_digest is not None:
            require_non_empty(
                str(self.response_plan_digest),
                "response_plan_digest",
            )


@dataclass(frozen=True, slots=True)
class RenderedContent:
    kind: str
    text: str | None = None
    asset: GeneratedAssetRef | None = None

    def __post_init__(self) -> None:
        if (self.text is None) == (self.asset is None):
            raise validation_error("rendered_content_requires_one_payload")


@dataclass(frozen=True, slots=True)
class RenderedBlock:
    block_id: str
    content: RenderedContent
    fact_anchor_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    constraint_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RenderMetadata:
    persona_id: str
    persona_version: str
    renderer_revision: ComponentRevision
    draft_digest: DigestString
    response_plan_digest: DigestString | None = None
    persona_source_digest: DigestString | None = None
    persona_catalog_digest: DigestString | None = None
    persona_catalog_snapshot_id: str | None = None
    persona_fallback_used: bool | None = None
    persona_render_mode: str | None = None
    requested_persona_id: str | None = None
    requested_persona_version: str | None = None
    persona_resolution_reason: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "persona_id",
            "persona_version",
            "draft_digest",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise validation_error("invalid_render_metadata_field", field_name)
            require_non_empty(value, field_name)
        if self.response_plan_digest is not None:
            if not isinstance(self.response_plan_digest, str):
                raise validation_error("invalid_response_plan_digest")
            require_non_empty(
                self.response_plan_digest,
                "response_plan_digest",
            )
        typed_fields = (
            self.persona_source_digest,
            self.persona_catalog_digest,
            self.persona_catalog_snapshot_id,
            self.persona_fallback_used,
            self.persona_render_mode,
            self.requested_persona_id,
            self.persona_resolution_reason,
        )
        if self.persona_source_digest is None:
            if any(value is not None for value in typed_fields):
                raise validation_error("partial_persona_render_metadata")
            if self.requested_persona_version is not None:
                raise validation_error("partial_persona_render_metadata")
            return
        if any(value is None for value in typed_fields):
            raise validation_error("partial_persona_render_metadata")
        for field_name in (
            "persona_source_digest",
            "persona_catalog_digest",
            "persona_catalog_snapshot_id",
            "persona_render_mode",
            "requested_persona_id",
            "persona_resolution_reason",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise validation_error("invalid_render_metadata_field", field_name)
            require_non_empty(value, field_name)
        if type(self.persona_fallback_used) is not bool:
            raise validation_error("invalid_persona_fallback_flag")
        if self.persona_render_mode not in {"deterministic", "model", "hybrid"}:
            raise validation_error("invalid_persona_render_mode")
        if self.requested_persona_version is not None:
            if not isinstance(self.requested_persona_version, str):
                raise validation_error("invalid_requested_persona_version")
            require_non_empty(
                self.requested_persona_version,
                "requested_persona_version",
            )


@dataclass(frozen=True, slots=True)
class FinalResponse:
    schema_version: int
    response_id: str
    producer: ComponentRevision
    blocks: tuple[RenderedBlock, ...]
    fact_anchors: tuple[FactAnchor, ...]
    citations: tuple[Citation, ...]
    uncertainty: tuple[UncertaintyNote, ...]
    warnings: tuple[SafetyNotice, ...]
    refusal: Refusal | None
    immutable_constraints: ResponseConstraints
    target_users: tuple[ResolvedIdentityRef, ...]
    attachments: tuple[GeneratedAssetRef, ...]
    render_metadata: RenderMetadata

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.response_id, "response_id")
        if not self.blocks and self.refusal is None:
            raise validation_error("empty_final_response")
        for field_name in (
            "blocks",
            "fact_anchors",
            "citations",
            "uncertainty",
            "warnings",
            "target_users",
            "attachments",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))


@dataclass(frozen=True, slots=True)
class RenderValidationResult:
    schema_version: int
    valid: bool
    draft_digest: DigestString
    rendered_digest: DigestString
    reason_codes: tuple[str, ...]
    changed_anchor_ids: tuple[str, ...]
    validator_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(
            self,
            "changed_anchor_ids",
            tuple(self.changed_anchor_ids),
        )


@dataclass(frozen=True, slots=True)
class ResponseProfileValidationResult:
    schema_version: int
    valid: bool
    response_plan_digest: DigestString
    rendered_digest: DigestString
    selected_profile: str
    visible_token_units: int
    visible_characters: int
    required_content_ids: tuple[str, ...]
    missing_content_ids: tuple[str, ...]
    unexpected_content_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    counter_revision: ComponentRevision
    validator_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if type(self.valid) is not bool:
            raise validation_error("invalid_response_profile_validation_flag")
        for name in ("response_plan_digest", "rendered_digest"):
            require_non_empty(str(getattr(self, name)), name)
        if self.selected_profile not in {"short", "medium", "long"}:
            raise validation_error("invalid_validated_response_profile")
        for name in ("visible_token_units", "visible_characters"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise validation_error("invalid_visible_response_count", name)
        for name in (
            "required_content_ids",
            "missing_content_ids",
            "unexpected_content_ids",
            "reason_codes",
        ):
            values = tuple(getattr(self, name))
            if any(not isinstance(value, str) or not value for value in values):
                raise validation_error("invalid_profile_validation_collection", name)
            if len(values) != len(set(values)):
                raise validation_error("duplicate_identifier", name)
            object.__setattr__(self, name, values)
        if not self.reason_codes:
            raise validation_error("missing_profile_validation_reason")
        if self.valid and (self.missing_content_ids or self.unexpected_content_ids):
            raise validation_error("valid_profile_validation_has_content_drift")
        if not isinstance(self.counter_revision, ComponentRevision):
            raise validation_error("invalid_visible_counter_revision")
        if not isinstance(self.validator_revision, ComponentRevision):
            raise validation_error("invalid_profile_validator_revision")


class SafetyStage(StrEnum):
    MODEL_INPUT = "model_input"
    TOOL_OUTPUT = "tool_output"
    DRAFT_OUTPUT = "draft_output"
    FINAL_OUTPUT = "final_output"


@dataclass(frozen=True, slots=True)
class ContentSafetyDecision:
    schema_version: int
    request_id: str
    stage: SafetyStage
    request_digest: DigestString
    content_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    allowed: bool
    required_constraints: ResponseConstraints
    reason_codes: tuple[str, ...]
    policy_revision: str
    producer: ComponentRevision
    decided_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.request_id, "request_id")
        if not isinstance(self.stage, SafetyStage):
            raise validation_error("invalid_safety_stage")
        for name in (
            "request_digest",
            "content_digest",
            "actor_digest",
            "scope_digest",
        ):
            require_non_empty(str(getattr(self, name)), name)
        require_non_empty(self.policy_revision, "policy_revision")
        require_aware(self.decided_at, "decided_at")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ValidatedFinalResponse:
    schema_version: int
    response: FinalResponse
    render_validation: RenderValidationResult
    content_safety: ContentSafetyDecision
    profile_validation: ResponseProfileValidationResult | None = None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not self.render_validation.valid:
            raise validation_error("invalid_render_validation")
        if self.render_validation.changed_anchor_ids:
            raise validation_error("render_changed_fact_anchor")
        if not self.content_safety.allowed:
            raise validation_error("unsafe_final_response")
        if self.content_safety.stage is not SafetyStage.FINAL_OUTPUT:
            raise validation_error("invalid_content_safety_stage")
        if self.response.response_id == "":
            raise validation_error("empty_response_id")
        if (
            self.render_validation.draft_digest
            != self.response.render_metadata.draft_digest
        ):
            raise validation_error("draft_digest_mismatch")
        actual_rendered_digest = canonical_digest(
            self.response,
            domain="response:final:v1",
        )
        if (
            self.render_validation.rendered_digest != actual_rendered_digest
            or self.content_safety.content_digest != actual_rendered_digest
        ):
            raise validation_error("rendered_digest_mismatch")
        if self.profile_validation is not None and (
            not isinstance(
                self.profile_validation,
                ResponseProfileValidationResult,
            )
            or not self.profile_validation.valid
            or self.profile_validation.rendered_digest != actual_rendered_digest
            or self.profile_validation.response_plan_digest
            != self.response.render_metadata.response_plan_digest
        ):
            raise validation_error("profile_validation_mismatch")
        if not _constraints_satisfy(
            self.response.immutable_constraints,
            self.content_safety.required_constraints,
        ):
            raise validation_error("missing_required_safety_constraint")


@dataclass(frozen=True, slots=True)
class Reaction:
    schema_version: int
    reaction_id: str
    kind: str
    target_message: MessageReference
    target_users: tuple[ResolvedIdentityRef, ...] = ()

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.reaction_id, "reaction_id")
        require_non_empty(self.kind, "kind")
        object.__setattr__(self, "target_users", tuple(self.target_users))


def _ensure_unique(values: object, field: str) -> None:
    materialized = tuple(values)  # type: ignore[arg-type]
    if len(set(materialized)) != len(materialized):
        raise validation_error("duplicate_identifier", field)


def _constraints_satisfy(
    actual: ResponseConstraints,
    required: ResponseConstraints,
) -> bool:
    if required.max_characters is not None and (
        actual.max_characters is None or actual.max_characters > required.max_characters
    ):
        return False
    if not required.allow_markdown and actual.allow_markdown:
        return False
    if not required.allow_attachments and actual.allow_attachments:
        return False
    return set(required.required_notice_keys) <= set(actual.required_notice_keys)


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
