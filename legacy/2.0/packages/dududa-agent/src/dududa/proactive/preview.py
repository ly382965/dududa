from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from dududa.contracts.canonical import canonical_digest
from dududa.domain.content import ValidatedFinalResponse
from dududa.errors import DududaError, validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.security.digests import authorization_decision_digest, scope_digest
from dududa.security.ports import AuthorizationDecisionVerifier, AuthorizationPolicy

from .authorization import (
    build_proactive_preview_authorization_request,
    proactive_authorization_allows,
)
from .contracts import (
    ProactiveDisposition,
    ProactivePreviewMetadata,
    ProactivePreviewRequest,
    ProactivePreviewResult,
    ProactiveRunMode,
)

if TYPE_CHECKING:
    from dududa.ports.proactive import (
        ProactivePreviewMetadataStore,
        ProactivePreviewProducer,
        ProactiveTargetRegistry,
    )


class IsolatedProactivePreviewService:
    """Authorized synchronous preview with no Dispatch Store or Output dependency."""

    def __init__(
        self,
        *,
        target_registry: ProactiveTargetRegistry,
        authorization_policy: AuthorizationPolicy,
        authorization_verifier: AuthorizationDecisionVerifier,
        authorization_policy_revision: str,
        producer: ProactivePreviewProducer,
        metadata_store: ProactivePreviewMetadataStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._target_registry = target_registry
        self._authorization_policy = authorization_policy
        self._authorization_verifier = authorization_verifier
        if (
            not isinstance(authorization_policy_revision, str)
            or not authorization_policy_revision.strip()
        ):
            raise validation_error("invalid_proactive_authorization_revision")
        self._authorization_policy_revision = authorization_policy_revision
        self._producer = producer
        self._metadata_store = metadata_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def preview(
        self,
        request: ProactivePreviewRequest,
        *,
        call: ServiceCallContext,
    ) -> ProactivePreviewResult:
        if not isinstance(request, ProactivePreviewRequest):
            raise validation_error("invalid_proactive_preview_request")
        now = self._now()
        _validate_call(call, now)
        placeholder = canonical_digest(
            {"request_digest": request.request_digest, "reason": "not_authorized"},
            domain="proactive:preview-authorization-evidence:v1",
        )
        try:
            await self._target_registry.resolve_target(
                request.target_policy_ref,
                at=now,
                call=call,
            )
        except DududaError:
            return await self._record_result(
                self._result(
                    request,
                    authorization_digest=placeholder,
                    final_response=None,
                    source_batch_digest=None,
                    disposition=ProactiveDisposition.DENIED,
                    reason="target_policy_invalid",
                    completed_at=now,
                ),
                call=call,
            )
        authorization_request = build_proactive_preview_authorization_request(
            request,
            policy_snapshot_id=call.policy_snapshot_id,
        )
        try:
            authorization = await self._authorization_policy.decide(
                authorization_request,
                call=_port_call(call, request.preview_id),
            )
        except Exception:  # noqa: BLE001 - policy outage denies before producer.
            return await self._record_result(
                self._result(
                    request,
                    authorization_digest=placeholder,
                    final_response=None,
                    source_batch_digest=None,
                    disposition=ProactiveDisposition.DENIED,
                    reason="preview_authorization_unavailable",
                    completed_at=now,
                ),
                call=call,
            )
        authorization_digest = authorization_decision_digest(authorization)
        if not proactive_authorization_allows(
            authorization_request,
            authorization,
            self._authorization_verifier,
            at=now,
            expected_policy_revision=self._authorization_policy_revision,
        ):
            return await self._record_result(
                self._result(
                    request,
                    authorization_digest=authorization_digest,
                    final_response=None,
                    source_batch_digest=None,
                    disposition=ProactiveDisposition.DENIED,
                    reason="preview_authorization_denied",
                    completed_at=now,
                ),
                call=call,
            )
        try:
            final_response, source_batch_digest = await self._producer.build(
                request,
                call=call,
            )
        except Exception:  # noqa: BLE001 - producer errors are sanitized.
            return await self._record_result(
                self._result(
                    request,
                    authorization_digest=authorization_digest,
                    final_response=None,
                    source_batch_digest=None,
                    disposition=ProactiveDisposition.FAILED,
                    reason="preview_producer_failed",
                    completed_at=self._now(),
                ),
                call=call,
            )
        if not isinstance(final_response, ValidatedFinalResponse):
            raise validation_error("invalid_proactive_preview_response")
        return await self._record_result(
            self._result(
                request,
                authorization_digest=authorization_digest,
                final_response=final_response,
                source_batch_digest=source_batch_digest,
                disposition=ProactiveDisposition.PREVIEWED,
                reason="preview_authorized",
                completed_at=self._now(),
            ),
            call=call,
        )

    async def _record_result(
        self,
        result: ProactivePreviewResult,
        *,
        call: ServiceCallContext,
    ) -> ProactivePreviewResult:
        metadata = ProactivePreviewMetadata(
            1,
            result.preview_id,
            result.request_digest,
            result.result_digest,
            result.target_scope_digest,
            result.authorization_decision_digest,
            result.disposition,
            result.validated_response_digest,
            result.response_plan_digest,
            result.source_batch_digest,
            result.reason_codes,
            result.completed_at,
        )
        await self._metadata_store.record(metadata, call=call)
        return result

    @staticmethod
    def _result(
        request: ProactivePreviewRequest,
        *,
        authorization_digest,
        final_response: ValidatedFinalResponse | None,
        source_batch_digest,
        disposition: ProactiveDisposition,
        reason: str,
        completed_at: datetime,
    ) -> ProactivePreviewResult:
        response_digest = (
            canonical_digest(final_response.response, domain="response:final:v1")
            if final_response is not None
            else None
        )
        response_plan_digest = (
            final_response.response.render_metadata.response_plan_digest
            if final_response is not None
            else None
        )
        return ProactivePreviewResult(
            1,
            request.preview_id,
            ProactiveRunMode.PREVIEW,
            disposition,
            request.request_digest,
            scope_digest(request.target_scope),
            authorization_digest,
            final_response,
            response_digest,
            response_plan_digest,
            source_batch_digest,
            (reason,),
            completed_at,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_proactive_preview_clock")
        return value


def _port_call(call: ServiceCallContext, run_id: str) -> PortCallContext:
    return PortCallContext(
        run_id,
        call.trace,
        call.deadline,
        call.cancellation,
        call.budget,
        call.policy_snapshot_id,
    )


def _validate_call(call: ServiceCallContext, now: datetime) -> None:
    if not isinstance(call, ServiceCallContext):
        raise validation_error("invalid_proactive_service_call")
    if call.cancellation.is_cancelled or call.deadline <= now:
        raise validation_error("proactive_call_cancelled_or_expired")


__all__ = ["IsolatedProactivePreviewService"]
