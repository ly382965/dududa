from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from dududa.domain.primitives import (
    ActionId,
    DigestString,
    RiskLevel,
    Sensitivity,
)
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext
from dududa.ports.control_plane import (
    GroupJoinSource,
    GroupServiceCatalog,
    GroupServiceRepository,
    OperatorSessionResolver,
)
from dududa.security.digests import actor_digest, audit_event_digest
from dududa.security.models import AuditEvent
from dududa.security.ports import AuditSink

from .authorization import ControlPlaneAuthorizer
from .contracts import (
    CommandOutcome,
    CommandReceipt,
    ControlPlaneAuditRecord,
    GroupOnboardingRecord,
    GroupServicePreview,
    PendingInboxProjection,
    PendingInboxQuery,
    PreviewCommitDisposition,
    ProfilePreviewCommand,
    ProfilePreviewExecution,
    ProfileRef,
    StoredPreviewCommand,
)
from .digests import (
    group_control_scope_digest,
    group_service_preview_digest,
    group_service_profile_digest,
    preview_command_payload_digest,
    preview_command_request_digest,
)
from .projector import ControlPlaneProjector
from .resolution import resolve_profile_services


class GroupJoinService:
    def __init__(
        self,
        source: GroupJoinSource,
        repository: GroupServiceRepository,
    ) -> None:
        self._source = source
        self._repository = repository

    async def ingest(
        self,
        *,
        call: ServiceCallContext,
    ) -> tuple[GroupOnboardingRecord, ...]:
        facts = await self._source.drain(call=call)
        return tuple(
            [await self._repository.observe_join(fact, call=call) for fact in facts]
        )


class ControlPlaneGateway:
    def __init__(
        self,
        *,
        sessions: OperatorSessionResolver,
        authorizer: ControlPlaneAuthorizer,
        repository: GroupServiceRepository,
        catalog: GroupServiceCatalog,
        projector: ControlPlaneProjector,
        audit_sink: AuditSink,
        preview_ttl: timedelta = timedelta(minutes=10),
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if preview_ttl <= timedelta(0):
            raise validation_error("invalid_preview_ttl")
        self._sessions = sessions
        self._authorizer = authorizer
        self._repository = repository
        self._catalog = catalog
        self._projector = projector
        self._audit_sink = audit_sink
        self._preview_ttl = preview_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def pending_inbox(
        self,
        query: PendingInboxQuery,
        *,
        call: ServiceCallContext,
    ) -> PendingInboxProjection:
        if not isinstance(query, PendingInboxQuery):
            raise validation_error("invalid_pending_inbox_query")
        self._validate_call(call)
        session = await self._sessions.resolve(query.session_ref, call=call)
        await self._authorizer.authorize_bot(
            session.actor,
            query.platform,
            query.bot_id,
            ActionId("group_service.query"),
            risk_level=RiskLevel.LOW,
            call=call,
        )
        return await self._projector.pending_inbox(
            query.platform,
            query.bot_id,
            call=call,
        )

    async def preview_profile(
        self,
        command: ProfilePreviewCommand,
        *,
        call: ServiceCallContext,
    ) -> ProfilePreviewExecution:
        if not isinstance(command, ProfilePreviewCommand):
            raise validation_error("invalid_profile_preview_command")
        self._validate_call(call)
        if preview_command_payload_digest(command) != command.payload_digest:
            raise validation_error("preview_payload_digest_mismatch")
        session = await self._sessions.resolve(command.session_ref, call=call)
        authorization = await self._authorizer.authorize_group(
            session.actor,
            command.scope,
            command.action,
            risk_level=RiskLevel.MEDIUM,
            call=call,
        )
        request_digest = preview_command_request_digest(command, session.actor)
        existing = await self._repository.lookup_preview_command(
            command.idempotency_key,
            call=call,
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise _conflict("control_plane_idempotency_conflict")
            return ProfilePreviewExecution(1, existing.receipt, existing.preview, False)

        onboarding = await self._repository.get_onboarding(command.scope, call=call)
        if onboarding is None:
            raise _not_found("group_onboarding_not_found")
        if onboarding.revision != command.expected_onboarding_revision:
            raise _conflict("group_onboarding_revision_conflict")
        profile = await self._catalog.get_profile(command.profile_ref, call=call)
        if profile is None:
            raise _not_found("group_service_profile_not_found")
        if ProfileRef(profile.profile_id, profile.revision) != command.profile_ref:
            raise validation_error("group_service_profile_ref_mismatch")
        catalog = await self._catalog.snapshot(command.scope, call=call)
        if catalog.scope != command.scope:
            raise validation_error("service_catalog_scope_mismatch")
        desired, effective, resolutions = resolve_profile_services(profile, catalog)
        now = self._clock()
        preview = GroupServicePreview(
            1,
            self._id_factory(),
            command.scope,
            command.profile_ref,
            group_service_profile_digest(profile),
            onboarding.revision,
            catalog.revision,
            desired,
            effective,
            resolutions,
            now,
            now + self._preview_ttl,
        )
        preview_digest = group_service_preview_digest(preview)
        scope_hash = group_control_scope_digest(command.scope)
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
            preview_digest,
            ("preview_ready",),
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
        stored = StoredPreviewCommand(
            1,
            request_digest,
            preview,
            receipt,
            audit_record,
        )
        committed = await self._repository.commit_preview(
            idempotency_key=command.idempotency_key,
            request_digest=request_digest,
            expected_onboarding_revision=command.expected_onboarding_revision,
            stored=stored,
            call=call,
        )
        if committed.disposition is PreviewCommitDisposition.DUPLICATE:
            return ProfilePreviewExecution(
                1,
                committed.stored.receipt,
                committed.stored.preview,
                False,
            )
        mirrored = await self._mirror_audit(
            committed.stored,
            authorization.policy_revision,
            authorization.resource_digest,
            call=call,
        )
        return ProfilePreviewExecution(
            1,
            committed.stored.receipt,
            committed.stored.preview,
            mirrored,
        )

    async def _mirror_audit(
        self,
        stored: StoredPreviewCommand,
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
        except Exception:  # noqa: BLE001 - the committed audit record remains authoritative.
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


__all__ = ["ControlPlaneGateway", "GroupJoinService"]
