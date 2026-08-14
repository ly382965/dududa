from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from dududa.domain.identity import Actor, ActorRef
from dududa.domain.primitives import DigestString, RiskLevel, Sensitivity
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext
from dududa.ports.control_plane import (
    GroupServiceCatalog,
    GroupServiceRepository,
    OperatorSessionResolver,
)
from dududa.security.digests import (
    actor_digest,
    audit_event_digest,
    scope_digest,
)
from dududa.security.models import AuditEvent
from dududa.security.ports import AuditSink, ConfirmationGrantVerifier

from .authorization import ControlPlaneAuthorizer, group_conversation_scope
from .contracts import (
    AssignmentCommitDisposition,
    AssignmentStatus,
    CommandOutcome,
    CommandReceipt,
    ControlPlaneAuditRecord,
    GroupServiceAssignment,
    GroupServiceMutationCommand,
    GroupServiceMutationExecution,
    GroupServicePreview,
    GroupServiceProfile,
    StoredAssignmentCommand,
)
from .digests import (
    group_control_scope_digest,
    group_service_assignment_digest,
    group_service_mutation_payload_digest,
    group_service_mutation_request_digest,
    group_service_preview_digest,
    group_service_profile_digest,
)
from .resolution import resolve_profile_services


class GroupServiceLifecycle:
    def __init__(
        self,
        *,
        sessions: OperatorSessionResolver,
        authorizer: ControlPlaneAuthorizer,
        repository: GroupServiceRepository,
        catalog: GroupServiceCatalog,
        confirmation_verifier: ConfirmationGrantVerifier,
        audit_sink: AuditSink,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._sessions = sessions
        self._authorizer = authorizer
        self._repository = repository
        self._catalog = catalog
        self._confirmation_verifier = confirmation_verifier
        self._audit_sink = audit_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def mutate(
        self,
        command: GroupServiceMutationCommand,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceMutationExecution:
        if not isinstance(command, GroupServiceMutationCommand):
            raise validation_error("invalid_group_service_mutation_command")
        self._validate_call(call)
        if group_service_mutation_payload_digest(command) != command.payload_digest:
            raise validation_error("group_service_mutation_payload_mismatch")
        session = await self._sessions.resolve(command.session_ref, call=call)
        authorization = await self._authorizer.authorize_group(
            session.actor,
            command.scope,
            command.action,
            risk_level=RiskLevel.MEDIUM,
            call=call,
        )
        request_digest = group_service_mutation_request_digest(
            command,
            session.actor,
        )
        existing = await self._repository.lookup_assignment_command(
            command.idempotency_key,
            call=call,
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise _conflict("control_plane_idempotency_conflict")
            return GroupServiceMutationExecution(
                1,
                existing.receipt,
                existing.assignment,
                False,
            )

        onboarding = await self._repository.get_onboarding(command.scope, call=call)
        if onboarding is None:
            raise _not_found("group_onboarding_not_found")
        if onboarding.revision != command.expected_onboarding_revision:
            raise _conflict("group_onboarding_revision_conflict")
        current = await self._repository.get_assignment(command.scope, call=call)
        current_revision = current.assignment_revision if current is not None else None
        if current_revision != command.expected_assignment_revision:
            raise _conflict("group_assignment_revision_conflict")

        now = self._clock()
        assignment = await self._next_assignment(
            command,
            current,
            onboarding.preview_id,
            session.actor,
            authorization.decision_id,
            authorization.policy_revision,
            now,
            call=call,
        )
        assignment_digest = group_service_assignment_digest(assignment)
        scope_hash = group_control_scope_digest(command.scope)
        reason_code = f"{str(command.action).removeprefix('group_service.')}_committed"
        receipt = CommandReceipt(
            1,
            self._id_factory(),
            command.command_id,
            command.idempotency_key,
            command.action,
            CommandOutcome.SUCCEEDED,
            request_digest,
            scope_hash,
            authorization.decision_id,
            assignment_digest,
            (reason_code,),
            now,
        )
        audit_record = ControlPlaneAuditRecord(
            1,
            self._id_factory(),
            command.command_id,
            command.action,
            actor_digest(session.actor),
            scope_hash,
            request_digest,
            receipt.receipt_id,
            receipt.outcome,
            receipt.reason_codes,
            now,
        )
        stored = StoredAssignmentCommand(
            1,
            request_digest,
            assignment,
            receipt,
            audit_record,
        )
        committed = await self._repository.commit_assignment(
            idempotency_key=command.idempotency_key,
            request_digest=request_digest,
            expected_onboarding_revision=command.expected_onboarding_revision,
            expected_assignment_revision=command.expected_assignment_revision,
            stored=stored,
            call=call,
        )
        if committed.disposition is AssignmentCommitDisposition.DUPLICATE:
            return GroupServiceMutationExecution(
                1,
                committed.stored.receipt,
                committed.stored.assignment,
                False,
            )
        mirrored = await self._mirror_audit(
            committed.stored,
            authorization.policy_revision,
            authorization.resource_digest,
            call=call,
        )
        return GroupServiceMutationExecution(
            1,
            committed.stored.receipt,
            committed.stored.assignment,
            mirrored,
        )

    async def _next_assignment(
        self,
        command: GroupServiceMutationCommand,
        current: GroupServiceAssignment | None,
        current_preview_id: str | None,
        actor: Actor,
        authorization_decision_id: str,
        policy_revision: str,
        now: datetime,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment:
        action = str(command.action)
        next_revision = 1 if current is None else current.assignment_revision + 1
        actor_ref = ActorRef(
            actor.platform,
            actor.bot_id,
            str(actor_digest(actor)),
        )
        if action in {"group_service.activate", "group_service.update"}:
            preview = await self._validated_preview(
                command,
                current_preview_id,
                actor,
                now,
                call=call,
            )
            lkg_revision = 1 if current is None else current.assignment_revision
            return GroupServiceAssignment(
                1,
                command.scope,
                next_revision,
                AssignmentStatus.ACTIVE,
                preview.profile_ref,
                preview.profile_digest,
                preview.desired_service_ids,
                preview.effective_service_ids,
                actor_ref,
                authorization_decision_id,
                policy_revision,
                current.assignment_revision if current is not None else None,
                lkg_revision,
                now,
            )
        if current is None:
            raise _conflict("group_assignment_not_active")
        if action == "group_service.pause":
            if current.status not in {
                AssignmentStatus.ACTIVE,
                AssignmentStatus.ROLLED_BACK,
            }:
                raise _conflict("group_assignment_not_resumable")
            return GroupServiceAssignment(
                1,
                current.scope,
                next_revision,
                AssignmentStatus.PAUSED,
                current.profile_ref,
                current.profile_digest,
                current.desired_service_ids,
                (),
                actor_ref,
                authorization_decision_id,
                policy_revision,
                current.assignment_revision,
                current.last_known_good_revision,
                now,
            )
        if action == "group_service.resume":
            if current.status is not AssignmentStatus.PAUSED:
                raise _conflict("group_assignment_not_paused")
            profile, desired, effective = await self._current_resolution(
                current,
                call=call,
            )
            return GroupServiceAssignment(
                1,
                current.scope,
                next_revision,
                AssignmentStatus.ACTIVE,
                current.profile_ref,
                group_service_profile_digest(profile),
                desired,
                effective,
                actor_ref,
                authorization_decision_id,
                policy_revision,
                current.assignment_revision,
                current.last_known_good_revision,
                now,
            )
        if action == "group_service.rollback":
            target_revision = command.rollback_revision
            if target_revision != current.last_known_good_revision:
                raise _conflict("rollback_target_not_last_known_good")
            if target_revision >= current.assignment_revision:
                raise _conflict("rollback_target_not_older")
            target = await self._repository.get_assignment_revision(
                command.scope,
                target_revision,
                call=call,
            )
            if target is None or target.status not in {
                AssignmentStatus.ACTIVE,
                AssignmentStatus.ROLLED_BACK,
            }:
                raise _conflict("rollback_target_unavailable")
            return GroupServiceAssignment(
                1,
                current.scope,
                next_revision,
                AssignmentStatus.ROLLED_BACK,
                target.profile_ref,
                target.profile_digest,
                target.desired_service_ids,
                target.effective_service_ids,
                actor_ref,
                authorization_decision_id,
                policy_revision,
                current.assignment_revision,
                target.assignment_revision,
                now,
            )
        raise validation_error("unsupported_group_service_mutation")

    async def _validated_preview(
        self,
        command: GroupServiceMutationCommand,
        current_preview_id: str | None,
        actor: Actor,
        now: datetime,
        *,
        call: ServiceCallContext,
    ) -> GroupServicePreview:
        if current_preview_id != command.preview_id:
            raise _conflict("preview_not_current")
        preview = await self._repository.get_preview(
            command.preview_id or "", call=call
        )
        if preview is None:
            raise _not_found("group_service_preview_not_found")
        if preview.scope != command.scope:
            raise _conflict("preview_scope_mismatch")
        if group_service_preview_digest(preview) != command.preview_digest:
            raise _conflict("preview_digest_mismatch")
        if preview.expires_at <= now:
            raise _conflict("group_service_preview_expired")
        if preview.assignment_revision != command.expected_assignment_revision:
            raise _conflict("preview_assignment_revision_conflict")
        self._validate_confirmation(command, actor, preview, now)
        profile = await self._catalog.get_profile(preview.profile_ref, call=call)
        if profile is None:
            raise _not_found("group_service_profile_not_found")
        if (
            profile.profile_id != preview.profile_ref.profile_id
            or profile.revision != preview.profile_ref.revision
            or group_service_profile_digest(profile) != preview.profile_digest
        ):
            raise _conflict("group_service_profile_drift")
        catalog = await self._catalog.snapshot(command.scope, call=call)
        if (
            catalog.scope != command.scope
            or catalog.revision != preview.catalog_revision
        ):
            raise _conflict("service_catalog_drift")
        desired, effective, resolutions = resolve_profile_services(profile, catalog)
        if (
            desired != preview.desired_service_ids
            or effective != preview.effective_service_ids
            or resolutions != preview.resolutions
        ):
            raise _conflict("service_resolution_drift")
        if profile.strict_services and effective != desired:
            raise _conflict("strict_profile_has_ineligible_services")
        return preview

    async def _current_resolution(
        self,
        current: GroupServiceAssignment,
        *,
        call: ServiceCallContext,
    ) -> tuple[GroupServiceProfile, tuple[str, ...], tuple[str, ...]]:
        profile = await self._catalog.get_profile(current.profile_ref, call=call)
        if (
            profile is None
            or group_service_profile_digest(profile) != current.profile_digest
        ):
            raise _conflict("group_service_profile_drift")
        catalog = await self._catalog.snapshot(current.scope, call=call)
        if catalog.scope != current.scope:
            raise _conflict("service_catalog_scope_mismatch")
        desired, effective, _ = resolve_profile_services(profile, catalog)
        if profile.strict_services and desired != effective:
            raise _conflict("strict_profile_has_ineligible_services")
        return profile, desired, effective

    def _validate_confirmation(
        self,
        command: GroupServiceMutationCommand,
        actor: Actor,
        preview: GroupServicePreview,
        now: datetime,
    ) -> None:
        grant = command.confirmation
        if grant is None or not self._confirmation_verifier.verify_grant(grant, at=now):
            raise _denied("control_plane_confirmation_unverifiable")
        expected_scope = scope_digest(group_conversation_scope(command.scope))
        if (
            grant.actor_digest != actor_digest(actor)
            or grant.scope_digest != expected_scope
            or grant.action != command.action
            or grant.payload_digest != group_service_preview_digest(preview)
            or grant.required_permission != str(command.action)
            or grant.execution_id != command.command_id
            or grant.idempotency_key != command.idempotency_key
        ):
            raise _denied("control_plane_confirmation_binding_mismatch")

    async def _mirror_audit(
        self,
        stored: StoredAssignmentCommand,
        policy_revision: str,
        resource_digest: DigestString,
        *,
        call: ServiceCallContext,
    ) -> bool:
        record = stored.audit_record
        candidate = AuditEvent(
            1,
            record.audit_record_id,
            DigestString("pending"),
            record.recorded_at,
            None,
            call.operation_id,
            call.trace.trace_id,
            call.trace.parent_span_id,
            record.actor_digest,
            record.scope_digest,
            record.action,
            "allow",
            stored.receipt.authorization_decision_id,
            record.request_digest,
            (policy_revision,),
            (),
            record.reason_codes,
            resource_digest,
            {
                "command_id": record.command_id,
                "receipt_id": record.receipt_id,
                "outcome": record.outcome.value,
            },
            Sensitivity.PERSONAL,
            record.outcome.value,
        )
        event = replace(candidate, event_digest=audit_event_digest(candidate))
        try:
            receipt = await self._audit_sink.write(event, call=call)
        except Exception:  # noqa: BLE001 - the repository audit remains authoritative.
            return False
        return receipt.persisted and receipt.event_digest == event.event_digest

    def _validate_call(self, call: ServiceCallContext) -> None:
        if not isinstance(call, ServiceCallContext):
            raise validation_error("invalid_control_plane_call_context")
        now = self._clock()
        if call.cancellation.is_cancelled:
            raise error(
                "control_plane_call_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if call.deadline <= now:
            raise error(
                "control_plane_call_expired",
                ErrorCategory.TIMEOUT,
                "request.expired",
            )


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "control_plane.conflict")


def _not_found(code: str):
    return error(code, ErrorCategory.NOT_FOUND, "control_plane.not_found")


def _denied(code: str):
    return error(code, ErrorCategory.AUTHORIZATION, "control_plane.denied")


__all__ = ["GroupServiceLifecycle"]
