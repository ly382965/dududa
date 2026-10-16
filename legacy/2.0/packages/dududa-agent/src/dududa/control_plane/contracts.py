from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dududa._compat import StrEnum
from dududa.domain.identity import Actor, ActorRef
from dududa.domain.primitives import (
    ActionId,
    DigestString,
    RiskLevel,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error
from dududa.security.models import ConfirmationGrant


class OnboardingStatus(StrEnum):
    PENDING_PROFILE = "pending_profile"
    PREVIEW_READY = "preview_ready"


class AssignmentStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ROLLED_BACK = "rolled_back"
    REVOKED = "revoked"


class ProfileMemoryMode(StrEnum):
    OFF = "off"
    READ = "read"
    MANUAL_WRITE = "manual_write"


class CommandOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    CONFLICT = "conflict"
    FAILED = "failed"


class PreviewCommitDisposition(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"


class AssignmentCommitDisposition(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class GroupControlScope:
    schema_version: int
    platform: str
    bot_id: str
    group_id: str

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in ("platform", "bot_id", "group_id"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise validation_error("invalid_group_control_scope_field", name)
            require_non_empty(value, name)


@dataclass(frozen=True, slots=True)
class ProfileRef:
    profile_id: str
    revision: int

    def __post_init__(self) -> None:
        require_non_empty(self.profile_id, "profile_id")
        _require_positive_int(self.revision, "profile_revision")


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    schema_version: int
    service_id: str
    display_name: str
    required_capability_ids: tuple[str, ...]
    risk_level: RiskLevel
    implementation_revision: str

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.service_id, "service_id")
        require_non_empty(self.display_name, "display_name")
        require_non_empty(self.implementation_revision, "implementation_revision")
        if not isinstance(self.risk_level, RiskLevel):
            raise validation_error("invalid_service_risk_level")
        object.__setattr__(
            self,
            "required_capability_ids",
            _unique_strings(
                self.required_capability_ids,
                "required_capability_ids",
                allow_empty=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class ServiceEligibilityFact:
    schema_version: int
    service_id: str
    installed: bool
    healthy: bool
    granted: bool
    rollout_eligible: bool
    evidence_revision: str

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.service_id, "service_id")
        require_non_empty(self.evidence_revision, "evidence_revision")
        for name in ("installed", "healthy", "granted", "rollout_eligible"):
            if type(getattr(self, name)) is not bool:
                raise validation_error("invalid_service_eligibility_boolean", name)


@dataclass(frozen=True, slots=True)
class ServiceCatalogSnapshot:
    schema_version: int
    scope: GroupControlScope
    revision: str
    definitions: tuple[ServiceDefinition, ...]
    eligibility: tuple[ServiceEligibilityFact, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        if not isinstance(self.scope, GroupControlScope):
            raise validation_error("invalid_group_control_scope")
        require_non_empty(self.revision, "catalog_revision")
        require_aware(self.captured_at, "catalog_captured_at")
        definitions = tuple(self.definitions)
        eligibility = tuple(self.eligibility)
        _require_unique_ids(definitions, "service_id", "duplicate_service_definition")
        _require_unique_ids(eligibility, "service_id", "duplicate_service_fact")
        object.__setattr__(self, "definitions", definitions)
        object.__setattr__(self, "eligibility", eligibility)


@dataclass(frozen=True, slots=True)
class GroupServiceProfile:
    schema_version: int
    profile_id: str
    revision: int
    display_name: str
    requested_service_ids: tuple[str, ...]
    persona_ref: str
    trigger_policy_ref: str
    response_policy_ref: str
    model_budget_policy_ref: str
    memory_mode: ProfileMemoryMode
    proactive_default_enabled: bool
    strict_services: bool

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in (
            "profile_id",
            "display_name",
            "persona_ref",
            "trigger_policy_ref",
            "response_policy_ref",
            "model_budget_policy_ref",
        ):
            require_non_empty(str(getattr(self, name)), name)
        _require_positive_int(self.revision, "profile_revision")
        object.__setattr__(
            self,
            "requested_service_ids",
            _unique_strings(self.requested_service_ids, "requested_service_ids"),
        )
        if not isinstance(self.memory_mode, ProfileMemoryMode):
            raise validation_error("invalid_profile_memory_mode")
        if type(self.proactive_default_enabled) is not bool:
            raise validation_error("invalid_proactive_default")
        if self.proactive_default_enabled:
            raise validation_error("profile_cannot_enable_proactive_delivery")
        if type(self.strict_services) is not bool:
            raise validation_error("invalid_strict_services")


@dataclass(frozen=True, slots=True)
class GroupJoinFact:
    schema_version: int
    event_id: str
    scope: GroupControlScope
    source_revision: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.event_id, "join_event_id")
        if not isinstance(self.scope, GroupControlScope):
            raise validation_error("invalid_group_control_scope")
        require_non_empty(self.source_revision, "join_source_revision")
        require_aware(self.observed_at, "join_observed_at")


@dataclass(frozen=True, slots=True)
class GroupOnboardingRecord:
    schema_version: int
    scope: GroupControlScope
    status: OnboardingStatus
    revision: int
    first_seen_at: datetime
    updated_at: datetime
    source_revision: str
    preview_id: str | None = None

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        if not isinstance(self.scope, GroupControlScope):
            raise validation_error("invalid_group_control_scope")
        if not isinstance(self.status, OnboardingStatus):
            raise validation_error("invalid_onboarding_status")
        _require_positive_int(self.revision, "onboarding_revision")
        require_aware(self.first_seen_at, "first_seen_at")
        require_aware(self.updated_at, "updated_at")
        require_non_empty(self.source_revision, "join_source_revision")
        if self.updated_at < self.first_seen_at:
            raise validation_error("onboarding_time_regression")
        if self.status is OnboardingStatus.PREVIEW_READY:
            require_non_empty(self.preview_id or "", "preview_id")
        elif self.preview_id is not None:
            raise validation_error("pending_onboarding_forbids_preview")


@dataclass(frozen=True, slots=True)
class GroupServiceAssignment:
    schema_version: int
    scope: GroupControlScope
    assignment_revision: int
    status: AssignmentStatus
    profile_ref: ProfileRef
    profile_digest: DigestString
    desired_service_ids: tuple[str, ...]
    effective_service_ids: tuple[str, ...]
    selected_by: ActorRef
    authorization_decision_id: str
    policy_revision: str
    previous_revision: int | None
    last_known_good_revision: int
    activated_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        if not isinstance(self.scope, GroupControlScope):
            raise validation_error("invalid_group_control_scope")
        if not isinstance(self.status, AssignmentStatus):
            raise validation_error("invalid_assignment_status")
        if not isinstance(self.profile_ref, ProfileRef):
            raise validation_error("invalid_profile_ref")
        if not isinstance(self.selected_by, ActorRef):
            raise validation_error("invalid_assignment_actor_ref")
        if (
            self.selected_by.platform != self.scope.platform
            or self.selected_by.bot_id != self.scope.bot_id
        ):
            raise validation_error("assignment_actor_scope_mismatch")
        _require_positive_int(self.assignment_revision, "assignment_revision")
        _require_positive_int(
            self.last_known_good_revision,
            "last_known_good_revision",
        )
        if self.previous_revision is not None:
            _require_positive_int(self.previous_revision, "previous_revision")
            if self.previous_revision >= self.assignment_revision:
                raise validation_error("invalid_assignment_previous_revision")
        if self.last_known_good_revision > self.assignment_revision:
            raise validation_error("invalid_assignment_lkg_revision")
        require_non_empty(str(self.profile_digest), "profile_digest")
        desired = _unique_strings(self.desired_service_ids, "desired_service_ids")
        effective = _unique_strings(
            self.effective_service_ids,
            "effective_service_ids",
            allow_empty=True,
        )
        if not set(effective).issubset(desired):
            raise validation_error("effective_service_not_desired")
        object.__setattr__(self, "desired_service_ids", desired)
        object.__setattr__(self, "effective_service_ids", effective)
        require_non_empty(
            self.authorization_decision_id,
            "authorization_decision_id",
        )
        require_non_empty(self.policy_revision, "policy_revision")
        require_aware(self.activated_at, "activated_at")


@dataclass(frozen=True, slots=True)
class OperatorSession:
    schema_version: int
    session_ref: str
    actor: Actor
    authentication_revision: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.session_ref, "session_ref")
        if not isinstance(self.actor, Actor):
            raise validation_error("invalid_operator_actor")
        require_non_empty(
            self.authentication_revision,
            "authentication_revision",
        )
        require_aware(self.issued_at, "session_issued_at")
        require_aware(self.expires_at, "session_expires_at")
        if self.expires_at <= self.issued_at:
            raise validation_error("invalid_operator_session_expiry")


@dataclass(frozen=True, slots=True)
class PendingInboxQuery:
    schema_version: int
    query_id: str
    session_ref: str
    platform: str
    bot_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in ("query_id", "session_ref", "platform", "bot_id"):
            require_non_empty(str(getattr(self, name)), name)
        require_aware(self.requested_at, "query_requested_at")


@dataclass(frozen=True, slots=True)
class ProfileCatalogQuery:
    schema_version: int
    query_id: str
    session_ref: str
    platform: str
    bot_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in ("query_id", "session_ref", "platform", "bot_id"):
            require_non_empty(str(getattr(self, name)), name)
        require_aware(self.requested_at, "query_requested_at")


@dataclass(frozen=True, slots=True)
class ManagedGroupsQuery:
    schema_version: int
    query_id: str
    session_ref: str
    platform: str
    bot_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in ("query_id", "session_ref", "platform", "bot_id"):
            require_non_empty(str(getattr(self, name)), name)
        require_aware(self.requested_at, "query_requested_at")


@dataclass(frozen=True, slots=True)
class ProfilePreviewCommand:
    schema_version: int
    command_id: str
    idempotency_key: str
    session_ref: str
    scope: GroupControlScope
    action: ActionId
    expected_onboarding_revision: int
    profile_ref: ProfileRef
    payload_digest: DigestString
    requested_at: datetime
    expected_assignment_revision: int | None = None

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in ("command_id", "idempotency_key", "session_ref"):
            require_non_empty(str(getattr(self, name)), name)
        if str(self.action) != "group_service.preview":
            raise validation_error("invalid_preview_action")
        if not isinstance(self.scope, GroupControlScope):
            raise validation_error("invalid_group_control_scope")
        if not isinstance(self.profile_ref, ProfileRef):
            raise validation_error("invalid_profile_ref")
        _require_positive_int(
            self.expected_onboarding_revision,
            "expected_onboarding_revision",
        )
        if self.expected_assignment_revision is not None:
            _require_positive_int(
                self.expected_assignment_revision,
                "expected_assignment_revision",
            )
        require_non_empty(str(self.payload_digest), "payload_digest")
        require_aware(self.requested_at, "command_requested_at")


@dataclass(frozen=True, slots=True)
class GroupServiceMutationCommand:
    schema_version: int
    command_id: str
    idempotency_key: str
    session_ref: str
    scope: GroupControlScope
    action: ActionId
    expected_onboarding_revision: int
    expected_assignment_revision: int | None
    preview_id: str | None
    preview_digest: DigestString | None
    rollback_revision: int | None
    confirmation: ConfirmationGrant | None
    payload_digest: DigestString
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in ("command_id", "idempotency_key", "session_ref"):
            require_non_empty(str(getattr(self, name)), name)
        if not isinstance(self.scope, GroupControlScope):
            raise validation_error("invalid_group_control_scope")
        _require_positive_int(
            self.expected_onboarding_revision,
            "expected_onboarding_revision",
        )
        if self.expected_assignment_revision is not None:
            _require_positive_int(
                self.expected_assignment_revision,
                "expected_assignment_revision",
            )
        action = str(self.action)
        if action not in {
            "group_service.activate",
            "group_service.update",
            "group_service.pause",
            "group_service.resume",
            "group_service.rollback",
        }:
            raise validation_error("invalid_group_service_mutation_action")
        if action == "group_service.activate":
            if self.expected_assignment_revision is not None:
                raise validation_error("activation_forbids_assignment_revision")
        elif self.expected_assignment_revision is None:
            raise validation_error("mutation_requires_assignment_revision")
        if action in {"group_service.activate", "group_service.update"}:
            require_non_empty(self.preview_id or "", "preview_id")
            require_non_empty(str(self.preview_digest or ""), "preview_digest")
            if not isinstance(self.confirmation, ConfirmationGrant):
                raise validation_error("mutation_requires_confirmation")
            if self.rollback_revision is not None:
                raise validation_error("preview_mutation_forbids_rollback_revision")
        elif action == "group_service.rollback":
            _require_positive_int(self.rollback_revision, "rollback_revision")
            if (
                self.preview_id is not None
                or self.preview_digest is not None
                or self.confirmation is not None
            ):
                raise validation_error("rollback_forbids_preview_or_confirmation")
        elif (
            self.preview_id is not None
            or self.preview_digest is not None
            or self.rollback_revision is not None
            or self.confirmation is not None
        ):
            raise validation_error("state_mutation_forbids_preview_or_confirmation")
        require_non_empty(str(self.payload_digest), "payload_digest")
        require_aware(self.requested_at, "command_requested_at")


@dataclass(frozen=True, slots=True)
class ServiceResolution:
    schema_version: int
    service_id: str
    eligible: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.service_id, "service_id")
        if type(self.eligible) is not bool:
            raise validation_error("invalid_service_resolution")
        reasons = _unique_strings(
            self.reason_codes,
            "service_reason_codes",
            allow_empty=self.eligible,
        )
        if self.eligible and reasons:
            raise validation_error("eligible_service_has_exclusion_reason")
        if not self.eligible and not reasons:
            raise validation_error("ineligible_service_requires_reason")
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class GroupServicePreview:
    schema_version: int
    preview_id: str
    scope: GroupControlScope
    profile_ref: ProfileRef
    profile_digest: DigestString
    onboarding_revision: int
    catalog_revision: str
    desired_service_ids: tuple[str, ...]
    effective_service_ids: tuple[str, ...]
    resolutions: tuple[ServiceResolution, ...]
    created_at: datetime
    expires_at: datetime
    assignment_revision: int | None = None

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.preview_id, "preview_id")
        require_non_empty(str(self.profile_digest), "profile_digest")
        require_non_empty(self.catalog_revision, "catalog_revision")
        _require_positive_int(self.onboarding_revision, "onboarding_revision")
        if self.assignment_revision is not None:
            _require_positive_int(
                self.assignment_revision,
                "assignment_revision",
            )
        desired = _unique_strings(self.desired_service_ids, "desired_service_ids")
        effective = _unique_strings(
            self.effective_service_ids,
            "effective_service_ids",
            allow_empty=True,
        )
        resolutions = tuple(self.resolutions)
        if not set(effective).issubset(desired):
            raise validation_error("effective_service_not_desired")
        if tuple(item.service_id for item in resolutions) != desired:
            raise validation_error("preview_resolution_order_mismatch")
        object.__setattr__(self, "desired_service_ids", desired)
        object.__setattr__(self, "effective_service_ids", effective)
        object.__setattr__(self, "resolutions", resolutions)
        require_aware(self.created_at, "preview_created_at")
        require_aware(self.expires_at, "preview_expires_at")
        if self.expires_at <= self.created_at:
            raise validation_error("invalid_preview_expiry")


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    schema_version: int
    receipt_id: str
    command_id: str
    idempotency_key: str
    action: ActionId
    outcome: CommandOutcome
    request_digest: DigestString
    scope_digest: DigestString
    authorization_decision_id: str
    result_digest: DigestString | None
    reason_codes: tuple[str, ...]
    committed_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in (
            "receipt_id",
            "command_id",
            "idempotency_key",
            "authorization_decision_id",
        ):
            require_non_empty(str(getattr(self, name)), name)
        require_non_empty(str(self.action), "action")
        if not isinstance(self.outcome, CommandOutcome):
            raise validation_error("invalid_command_outcome")
        require_non_empty(str(self.request_digest), "request_digest")
        require_non_empty(str(self.scope_digest), "scope_digest")
        if self.result_digest is not None:
            require_non_empty(str(self.result_digest), "result_digest")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(
                self.reason_codes,
                "command_reason_codes",
                allow_empty=True,
            ),
        )
        require_aware(self.committed_at, "command_committed_at")


@dataclass(frozen=True, slots=True)
class ControlPlaneAuditRecord:
    schema_version: int
    audit_record_id: str
    command_id: str
    action: ActionId
    actor_digest: DigestString
    scope_digest: DigestString
    request_digest: DigestString
    receipt_id: str
    outcome: CommandOutcome
    reason_codes: tuple[str, ...]
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        for name in ("audit_record_id", "command_id", "receipt_id"):
            require_non_empty(str(getattr(self, name)), name)
        require_non_empty(str(self.action), "action")
        for name in ("actor_digest", "scope_digest", "request_digest"):
            require_non_empty(str(getattr(self, name)), name)
        if not isinstance(self.outcome, CommandOutcome):
            raise validation_error("invalid_command_outcome")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(
                self.reason_codes,
                "audit_reason_codes",
                allow_empty=True,
            ),
        )
        require_aware(self.recorded_at, "audit_recorded_at")


@dataclass(frozen=True, slots=True)
class StoredPreviewCommand:
    schema_version: int
    request_digest: DigestString
    preview: GroupServicePreview
    receipt: CommandReceipt
    audit_record: ControlPlaneAuditRecord

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(str(self.request_digest), "request_digest")
        if not isinstance(self.preview, GroupServicePreview):
            raise validation_error("invalid_stored_preview")
        if not isinstance(self.receipt, CommandReceipt):
            raise validation_error("invalid_stored_command_receipt")
        if not isinstance(self.audit_record, ControlPlaneAuditRecord):
            raise validation_error("invalid_stored_audit_record")
        if self.receipt.request_digest != self.request_digest:
            raise validation_error("stored_command_request_mismatch")
        if (
            self.receipt.receipt_id != self.audit_record.receipt_id
            or self.receipt.command_id != self.audit_record.command_id
            or self.receipt.action != self.audit_record.action
            or self.receipt.scope_digest != self.audit_record.scope_digest
            or self.receipt.request_digest != self.audit_record.request_digest
            or self.receipt.outcome is not self.audit_record.outcome
            or self.receipt.reason_codes != self.audit_record.reason_codes
        ):
            raise validation_error("stored_command_audit_mismatch")


@dataclass(frozen=True, slots=True)
class PreviewCommitResult:
    schema_version: int
    disposition: PreviewCommitDisposition
    stored: StoredPreviewCommand

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        if not isinstance(self.disposition, PreviewCommitDisposition):
            raise validation_error("invalid_preview_commit_disposition")


@dataclass(frozen=True, slots=True)
class StoredAssignmentCommand:
    schema_version: int
    request_digest: DigestString
    assignment: GroupServiceAssignment
    receipt: CommandReceipt
    audit_record: ControlPlaneAuditRecord

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(str(self.request_digest), "request_digest")
        if not isinstance(self.assignment, GroupServiceAssignment):
            raise validation_error("invalid_stored_assignment")
        if not isinstance(self.receipt, CommandReceipt):
            raise validation_error("invalid_stored_command_receipt")
        if not isinstance(self.audit_record, ControlPlaneAuditRecord):
            raise validation_error("invalid_stored_audit_record")
        if self.receipt.request_digest != self.request_digest:
            raise validation_error("stored_command_request_mismatch")
        if (
            self.receipt.receipt_id != self.audit_record.receipt_id
            or self.receipt.command_id != self.audit_record.command_id
            or self.receipt.action != self.audit_record.action
            or self.receipt.scope_digest != self.audit_record.scope_digest
            or self.receipt.request_digest != self.audit_record.request_digest
            or self.receipt.outcome is not self.audit_record.outcome
            or self.receipt.reason_codes != self.audit_record.reason_codes
        ):
            raise validation_error("stored_command_audit_mismatch")


@dataclass(frozen=True, slots=True)
class AssignmentCommitResult:
    schema_version: int
    disposition: AssignmentCommitDisposition
    stored: StoredAssignmentCommand

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        if not isinstance(self.disposition, AssignmentCommitDisposition):
            raise validation_error("invalid_assignment_commit_disposition")


@dataclass(frozen=True, slots=True)
class PendingGroupProjection:
    schema_version: int
    scope: GroupControlScope
    status: OnboardingStatus
    revision: int
    first_seen_at: datetime
    updated_at: datetime
    preview_id: str | None

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        if not isinstance(self.scope, GroupControlScope):
            raise validation_error("invalid_group_control_scope")
        if not isinstance(self.status, OnboardingStatus):
            raise validation_error("invalid_onboarding_status")
        _require_positive_int(self.revision, "onboarding_revision")
        require_aware(self.first_seen_at, "first_seen_at")
        require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.first_seen_at:
            raise validation_error("onboarding_time_regression")
        if self.status is OnboardingStatus.PREVIEW_READY:
            require_non_empty(self.preview_id or "", "preview_id")
        elif self.preview_id is not None:
            raise validation_error("pending_onboarding_forbids_preview")


@dataclass(frozen=True, slots=True)
class PendingInboxProjection:
    schema_version: int
    platform: str
    bot_id: str
    items: tuple[PendingGroupProjection, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.platform, "platform")
        require_non_empty(self.bot_id, "bot_id")
        items = tuple(self.items)
        if any(
            item.scope.platform != self.platform or item.scope.bot_id != self.bot_id
            for item in items
        ):
            raise validation_error("pending_projection_scope_mismatch")
        object.__setattr__(self, "items", items)
        require_aware(self.generated_at, "projection_generated_at")


@dataclass(frozen=True, slots=True)
class ManagedGroupProjection:
    schema_version: int
    onboarding: PendingGroupProjection
    assignment: GroupServiceAssignment

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        if not isinstance(self.onboarding, PendingGroupProjection):
            raise validation_error("invalid_managed_group_onboarding")
        if not isinstance(self.assignment, GroupServiceAssignment):
            raise validation_error("invalid_managed_group_assignment")
        if self.onboarding.scope != self.assignment.scope:
            raise validation_error("managed_group_scope_mismatch")


@dataclass(frozen=True, slots=True)
class ManagedGroupsProjection:
    schema_version: int
    platform: str
    bot_id: str
    items: tuple[ManagedGroupProjection, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.platform, "platform")
        require_non_empty(self.bot_id, "bot_id")
        items = tuple(self.items)
        if any(
            item.onboarding.scope.platform != self.platform
            or item.onboarding.scope.bot_id != self.bot_id
            for item in items
        ):
            raise validation_error("managed_groups_projection_scope_mismatch")
        object.__setattr__(self, "items", items)
        require_aware(self.generated_at, "projection_generated_at")


@dataclass(frozen=True, slots=True)
class ProfileCatalogProjection:
    schema_version: int
    revision: str
    profiles: tuple[GroupServiceProfile, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        require_non_empty(self.revision, "profile_catalog_revision")
        profiles = tuple(self.profiles)
        _require_unique_ids(profiles, "profile_id", "duplicate_profile_id")
        object.__setattr__(self, "profiles", profiles)
        require_aware(self.generated_at, "projection_generated_at")


@dataclass(frozen=True, slots=True)
class ProfilePreviewExecution:
    schema_version: int
    receipt: CommandReceipt
    preview: GroupServicePreview | None
    onboarding_revision: int
    audit_mirror_persisted: bool

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        _require_positive_int(self.onboarding_revision, "onboarding_revision")
        if type(self.audit_mirror_persisted) is not bool:
            raise validation_error("invalid_audit_mirror_status")
        if self.receipt.outcome is CommandOutcome.SUCCEEDED and self.preview is None:
            raise validation_error("successful_preview_missing_result")


@dataclass(frozen=True, slots=True)
class GroupServiceMutationExecution:
    schema_version: int
    receipt: CommandReceipt
    assignment: GroupServiceAssignment
    audit_mirror_persisted: bool

    def __post_init__(self) -> None:
        _require_v1(self.schema_version)
        if not isinstance(self.receipt, CommandReceipt):
            raise validation_error("invalid_command_receipt")
        if not isinstance(self.assignment, GroupServiceAssignment):
            raise validation_error("invalid_group_service_assignment")
        if type(self.audit_mirror_persisted) is not bool:
            raise validation_error("invalid_audit_mirror_status")


def _require_v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _require_positive_int(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise validation_error("invalid_positive_integer", name)


def _unique_strings(
    values: tuple[str, ...],
    name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_string_sequence", name)
    result = tuple(values)
    if (not allow_empty and not result) or any(
        not isinstance(item, str) or not item.strip() for item in result
    ):
        raise validation_error("invalid_string_sequence", name)
    if len(result) != len(set(result)):
        raise validation_error("duplicate_string_sequence_item", name)
    return result


def _require_unique_ids(values: tuple[object, ...], field: str, code: str) -> None:
    identities = [getattr(item, field, None) for item in values]
    if len(identities) != len(set(identities)):
        raise validation_error(code)


__all__ = [
    "AssignmentCommitDisposition",
    "AssignmentCommitResult",
    "AssignmentStatus",
    "CommandOutcome",
    "CommandReceipt",
    "ControlPlaneAuditRecord",
    "GroupControlScope",
    "GroupJoinFact",
    "GroupOnboardingRecord",
    "GroupServiceAssignment",
    "GroupServiceMutationCommand",
    "GroupServiceMutationExecution",
    "GroupServicePreview",
    "GroupServiceProfile",
    "ManagedGroupProjection",
    "ManagedGroupsProjection",
    "ManagedGroupsQuery",
    "OnboardingStatus",
    "OperatorSession",
    "PendingGroupProjection",
    "PendingInboxProjection",
    "PendingInboxQuery",
    "PreviewCommitDisposition",
    "PreviewCommitResult",
    "ProfileCatalogProjection",
    "ProfileCatalogQuery",
    "ProfileMemoryMode",
    "ProfilePreviewCommand",
    "ProfilePreviewExecution",
    "ProfileRef",
    "ServiceCatalogSnapshot",
    "ServiceDefinition",
    "ServiceEligibilityFact",
    "ServiceResolution",
    "StoredAssignmentCommand",
    "StoredPreviewCommand",
]
