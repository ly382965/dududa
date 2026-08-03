from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from dududa.domain.primitives import JsonValue, freeze_json
from dududa.models.contracts import (
    EndpointHealthStatus,
    ModelEndpointHealth,
    ModelFailureKind,
    ModelProcessingReceipt,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelUsage,
    ProviderRequest,
    ProviderResponse,
    SafetyAnnotation,
)
from dududa.models.digests import provider_request_digest
from dududa.models.errors import ModelProviderError, model_error_info
from dududa.ports.context import PortCallContext, ServiceCallContext


@dataclass(frozen=True, slots=True)
class ProviderSuccess:
    output: JsonValue
    finish_reason: str = "stop"
    usage: ModelUsage | None = None
    safety_annotations: tuple[SafetyAnnotation, ...] = ()
    effective_reasoning_profile_id: str | None = None
    effective_seed: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", freeze_json(self.output))
        object.__setattr__(
            self,
            "safety_annotations",
            tuple(self.safety_annotations),
        )


ProviderOutcome = ProviderSuccess | ModelProviderError


class RecordingFakeModelProvider:
    def __init__(
        self,
        descriptor: ModelProviderDescriptor,
        outcomes: Iterable[ProviderOutcome],
        *,
        clock: Callable[[], datetime] | None = None,
        health_status: EndpointHealthStatus = EndpointHealthStatus.HEALTHY,
    ) -> None:
        if not isinstance(descriptor, ModelProviderDescriptor):
            raise ValueError("descriptor must be ModelProviderDescriptor")
        self._descriptor = descriptor
        self._outcomes = deque(outcomes)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._health_status = health_status
        self.calls: list[tuple[ProviderRequest, PortCallContext]] = []
        self.health_calls: list[PortCallContext | ServiceCallContext] = []
        self.closed = False
        self._idempotency_results: dict[str, tuple[object, ProviderResponse]] = {}
        self._idempotency_lock = asyncio.Lock()

    @property
    def descriptor(self) -> ModelProviderDescriptor:
        return self._descriptor

    async def generate(
        self,
        request: ProviderRequest,
        *,
        call: PortCallContext,
    ) -> ProviderResponse:
        now = self._now()
        if call.cancellation.is_cancelled:
            raise provider_failure(
                ModelFailureKind.CANCELLED,
                "cancelled_before_provider_call",
            )
        if now >= call.deadline:
            raise provider_failure(
                ModelFailureKind.TIMEOUT,
                "deadline_before_provider_call",
            )
        endpoint = _validate_request(self._descriptor, request)
        request_digest = provider_request_digest(request)
        if request.idempotency_key is None:
            return self._generate_once(request, call, endpoint, request_digest)
        async with self._idempotency_lock:
            existing = self._idempotency_results.get(request.idempotency_key)
            if existing is not None:
                existing_digest, response = existing
                if existing_digest != request_digest:
                    raise provider_failure(
                        ModelFailureKind.INVALID_REQUEST,
                        "fake_idempotency_conflict",
                    )
                return response
            response = self._generate_once(request, call, endpoint, request_digest)
            self._idempotency_results[request.idempotency_key] = (
                request_digest,
                response,
            )
            return response

    def _generate_once(
        self,
        request: ProviderRequest,
        call: PortCallContext,
        endpoint,
        request_digest,
    ) -> ProviderResponse:
        self.calls.append((request, call))
        if not self._outcomes:
            raise provider_failure(
                ModelFailureKind.INTERNAL,
                "fake_outcome_script_exhausted",
            )
        outcome = self._outcomes.popleft()
        if isinstance(outcome, ModelProviderError):
            raise outcome
        processing = ModelProcessingReceipt(
            schema_version=1,
            provider_id=request.provider_id,
            provider_revision=request.provider_revision,
            endpoint_id=request.endpoint_id,
            endpoint_descriptor_digest=request.endpoint_descriptor_digest,
            model_id=request.model_id,
            provider_request_digest=request_digest,
            processing_boundary=endpoint.processing_boundary,
            data_residency=request.selected_data_residency,
            retention_mode=request.required_retention_mode,
            requested_reasoning_profile_id=request.reasoning_profile.profile_id,
            effective_reasoning_profile_id=(
                outcome.effective_reasoning_profile_id
                or request.reasoning_profile.profile_id
            ),
            requested_seed=request.random_seed,
            effective_seed=(
                outcome.effective_seed
                if outcome.effective_seed is not None
                else request.random_seed
            ),
        )
        return ProviderResponse(
            schema_version=1,
            request_id=request.request_id,
            provider_id=request.provider_id,
            endpoint_id=request.endpoint_id,
            model_id=request.model_id,
            provider_revision=request.provider_revision,
            output=outcome.output,
            finish_reason=outcome.finish_reason,
            usage=outcome.usage,
            safety_annotations=outcome.safety_annotations,
            processing=processing,
        )

    async def health(
        self,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ModelProviderHealth:
        self.health_calls.append(call)
        now = self._now()
        endpoints = tuple(
            ModelEndpointHealth(
                schema_version=1,
                endpoint_id=endpoint.endpoint_id,
                endpoint_descriptor_digest=endpoint.descriptor_digest,
                status=self._health_status,
                reason_codes=(),
            )
            for endpoint in self._descriptor.endpoints
        )
        return ModelProviderHealth(
            schema_version=1,
            provider_id=self._descriptor.provider_id,
            status=self._health_status,
            endpoints=endpoints,
            snapshot_revision="recording-fake-health-v1",
            checked_at=now,
            reason_codes=(),
        )

    async def close(self) -> None:
        self.closed = True

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock returned a naive datetime")
        return value


def provider_failure(
    failure_kind: ModelFailureKind,
    reason_code: str,
    *,
    outcome_unknown: bool = False,
) -> ModelProviderError:
    return ModelProviderError(
        failure_kind,
        model_error_info(
            failure_kind,
            code=f"provider_{failure_kind.value}",
            reason_codes=(reason_code,),
            outcome_unknown=outcome_unknown,
        ),
    )


def _validate_request(
    descriptor: ModelProviderDescriptor,
    request: ProviderRequest,
):
    if (
        request.provider_id != descriptor.provider_id
        or request.provider_revision != descriptor.revision
    ):
        raise provider_failure(
            ModelFailureKind.INVALID_REQUEST,
            "provider_binding_mismatch",
        )
    endpoint = next(
        (
            item
            for item in descriptor.endpoints
            if item.endpoint_id == request.endpoint_id
        ),
        None,
    )
    if endpoint is None:
        raise provider_failure(
            ModelFailureKind.INVALID_REQUEST,
            "endpoint_not_bound",
        )
    if (
        request.model_id != endpoint.model_id
        or request.endpoint_descriptor_digest != endpoint.descriptor_digest
        or request.selected_tier is not endpoint.tier
    ):
        raise provider_failure(
            ModelFailureKind.INVALID_REQUEST,
            "endpoint_binding_mismatch",
        )
    if request.reasoning_profile not in endpoint.reasoning_profiles:
        raise provider_failure(
            ModelFailureKind.CAPABILITY_MISMATCH,
            "reasoning_profile_not_supported",
        )
    if request.selected_data_residency not in endpoint.available_data_residencies:
        raise provider_failure(
            ModelFailureKind.INVALID_REQUEST,
            "residency_not_supported",
        )
    if request.required_retention_mode not in endpoint.supported_retention_modes:
        raise provider_failure(
            ModelFailureKind.INVALID_REQUEST,
            "retention_not_supported",
        )
    return endpoint
