from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import time
import uuid

from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.errors import DududaError, ErrorInfo
from dududa.ports.context import PortCallContext
from dududa.ports.models import (
    ModelAdmissionController,
    ModelInvocationEstimator,
    ModelOperationalStateRegistry,
    ModelOutputCodec,
    ModelRoutingRegistry,
)

from .contracts import (
    AdmissionDisposition,
    EndpointAdmissionRequest,
    EndpointAdmissionResult,
    EndpointCapacityReceipt,
    EndpointHealthStatus,
    EndpointRejection,
    EndpointRouteCandidatePlan,
    ModelEndpointDescriptor,
    ModelEndpointRef,
    ModelFailureKind,
    ModelInvocationEstimate,
    ModelOperationalSnapshot,
    ModelProcessingBoundary,
    ModelProviderDescriptor,
    ModelRequest,
    ModelResponse,
    ModelRetentionMode,
    ModelRole,
    ModelTier,
    ProviderRequest,
    ProviderResponse,
    ReasoningProfile,
    RouteAttempt,
    RouteAttemptKind,
    RouteDecision,
    StaleSnapshotPolicy,
    StructuredOutputSupport,
    validate_model_failure_info,
)
from .digests import (
    bootstrap_tier_selection_fingerprint,
    model_invocation_estimate_digest,
    model_operational_snapshot_digest,
    model_request_digest,
    model_request_fingerprint,
    model_route_policy_digest,
    provider_request_digest,
    route_plan_fingerprint,
    tier_authority_digest,
)
from .errors import (
    ModelInvocationError,
    ModelProviderError,
    model_error_info,
)
from .policy import (
    BootstrapTierDecision,
    ModelRoutePolicy,
    ModelRoutingSnapshot,
    TierAuthority,
    validate_tier_authority,
)


@dataclass(frozen=True, slots=True)
class _RoutePlan:
    request: ModelRequest
    authority: TierAuthority
    routing: ModelRoutingSnapshot
    operational: ModelOperationalSnapshot
    policy: ModelRoutePolicy
    requested_tier: ModelTier
    output_schema_digest: DigestString | None
    output_codec_revision: ComponentRevision | None
    candidate_plans: tuple[EndpointRouteCandidatePlan, ...]
    rejected_endpoints: tuple[EndpointRejection, ...]
    planned_endpoint: ModelEndpointRef | None
    receipt_profile: ReasoningProfile
    fingerprint: DigestString


@dataclass(slots=True)
class _ExecutionState:
    admissions: list[EndpointAdmissionResult] = field(default_factory=list)
    capacity_receipts: list[EndpointCapacityReceipt] = field(default_factory=list)
    attempts: list[RouteAttempt] = field(default_factory=list)
    visited_endpoints: set[tuple[str, str]] = field(default_factory=set)
    endpoint_retries: dict[tuple[str, str], int] = field(
        default_factory=lambda: defaultdict(int)
    )
    same_tier_failovers: int = 0
    tier_hops: int = 0
    schema_repairs: int = 0
    used_calls: int = 0
    used_retries: int = 0
    used_input_tokens: int = 0
    used_generated_tokens: int = 0
    used_cost_units: Decimal = Decimal(0)
    total_latency_ms: int = 0


class StaticModelRouter:
    def __init__(
        self,
        routing_registry: ModelRoutingRegistry,
        operational_registry: ModelOperationalStateRegistry,
        admission_controller: ModelAdmissionController,
        estimator: ModelInvocationEstimator,
        *,
        output_codec: ModelOutputCodec | None,
        prompt_template_revisions: Mapping[ModelRole, ComponentRevision],
        schema_repair_prompt_revisions: Mapping[ModelRole, ComponentRevision],
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(routing_registry, ModelRoutingRegistry):
            raise ValueError("routing_registry does not implement its Protocol")
        if not isinstance(operational_registry, ModelOperationalStateRegistry):
            raise ValueError("operational_registry does not implement its Protocol")
        if not isinstance(admission_controller, ModelAdmissionController):
            raise ValueError("admission_controller does not implement its Protocol")
        if not isinstance(estimator, ModelInvocationEstimator):
            raise ValueError("estimator does not implement its Protocol")
        if output_codec is not None and not isinstance(output_codec, ModelOutputCodec):
            raise ValueError("output_codec does not implement its Protocol")
        self._routing_registry = routing_registry
        self._operational_registry = operational_registry
        self._admission = admission_controller
        self._estimator = estimator
        self._output_codec = output_codec
        self._prompt_revisions = _revision_mapping(prompt_template_revisions)
        self._repair_revisions = _revision_mapping(
            schema_repair_prompt_revisions,
            allow_empty=True,
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def invoke(
        self,
        request: ModelRequest,
        tier_authority: TierAuthority,
        *,
        call: PortCallContext,
    ) -> ModelResponse:
        if not isinstance(request, ModelRequest):
            raise _validation_failure("invalid_model_request")
        validate_tier_authority(request.role, tier_authority)
        self._validate_bootstrap_authority(tier_authority)
        plan = self._plan(request, tier_authority, call)
        state = _ExecutionState()
        initial_failure = _initial_gate_failure(plan, call, self._now())
        if initial_failure is not None:
            self._raise_failure(plan, state, *initial_failure)
        if plan.planned_endpoint is None:
            self._raise_failure(plan, state, *_no_route_failure(plan))

        candidates_by_tier = _candidates_by_tier(plan.candidate_plans)
        current = plan.candidate_plans[0]
        next_kind = RouteAttemptKind.PRIMARY
        while True:
            gate_failure = _attempt_gate_failure(
                plan, state, current, call, self._now()
            )
            if gate_failure is not None:
                if gate_failure[0] is ModelFailureKind.PROVIDER_UNAVAILABLE:
                    state.visited_endpoints.add(_endpoint_key(current.endpoint))
                    transition = _next_candidate(
                        plan,
                        state,
                        current,
                        gate_failure[0],
                        candidates_by_tier,
                        provider_invoked=False,
                        idempotent=request.idempotency_key is not None,
                    )
                    if transition is not None:
                        current, next_kind = transition
                        continue
                self._raise_failure(plan, state, *gate_failure)
            try:
                attempt_number = state.used_calls + 1
                attempt_kind = (
                    RouteAttemptKind.PRIMARY if not state.attempts else next_kind
                )
                prompt_revision = self._prompt_revision(request.role, attempt_kind)
                provider_request = self._provider_request(
                    plan,
                    current,
                    attempt_number,
                    attempt_kind,
                    prompt_revision,
                )
                provider_request_value_digest = provider_request_digest(
                    provider_request
                )
                provider_descriptor = _provider_descriptor(
                    plan.routing,
                    current.endpoint.provider_id,
                )
                endpoint_descriptor = _endpoint_descriptor(
                    plan.routing,
                    current.endpoint,
                )
                provider = self._routing_registry.resolve_provider(
                    plan.routing,
                    provider_descriptor.provider_id,
                    provider_descriptor.revision,
                )
            except ModelProviderError as exc:
                self._raise_model_error(plan, state, exc)
            except DududaError:
                self._raise_failure(
                    plan,
                    state,
                    ModelFailureKind.INTERNAL,
                    "model_provider_resolution_failed",
                    "provider_resolution_failed",
                )
            admission_request = self._admission_request(plan, current, call)
            admission = await self._admission.reserve(admission_request, call=call)
            state.admissions.append(admission)
            state.visited_endpoints.add(_endpoint_key(current.endpoint))
            if admission.disposition is AdmissionDisposition.REJECTED:
                rejection_failure = _admission_rejection_failure(
                    admission.reason_codes[0]
                )
                transition = None
                if rejection_failure[0] not in {
                    ModelFailureKind.CANCELLED,
                    ModelFailureKind.TIMEOUT,
                }:
                    transition = _next_candidate(
                        plan,
                        state,
                        current,
                        rejection_failure[0],
                        candidates_by_tier,
                        provider_invoked=False,
                        idempotent=request.idempotency_key is not None,
                    )
                if transition is None:
                    self._raise_failure(
                        plan,
                        state,
                        *rejection_failure,
                    )
                current, next_kind = transition
                continue

            lease = admission.lease
            if (
                lease is None
            ):  # defensive; EndpointAdmissionResult already enforces this
                self._raise_failure(
                    plan,
                    state,
                    ModelFailureKind.INTERNAL,
                    "model_admission_receipt_invalid",
                    "reserved_admission_missing_lease",
                )
            gate_failure = None
            post_reserve_gate_failed = False
            try:
                gate_failure = _attempt_gate_failure(
                    plan, state, current, call, self._now()
                )
            except asyncio.CancelledError:
                receipt = await self._release_capacity(lease, call)
                state.capacity_receipts.append(receipt)
                if receipt.disposition is AdmissionDisposition.SETTLED:
                    _charge_state(state, receipt)
                raise
            except BaseException as exc:
                receipt = await self._release_capacity(lease, call)
                state.capacity_receipts.append(receipt)
                if receipt.disposition is AdmissionDisposition.SETTLED:
                    _charge_state(state, receipt)
                if not isinstance(exc, Exception):
                    raise
                post_reserve_gate_failed = True
            if post_reserve_gate_failed:
                self._raise_failure(
                    plan,
                    state,
                    ModelFailureKind.INTERNAL,
                    "model_post_reserve_gate_failed",
                    "post_reserve_gate_failed",
                )
            if gate_failure is not None:
                receipt = await self._release_capacity(lease, call)
                state.capacity_receipts.append(receipt)
                if receipt.disposition is AdmissionDisposition.SETTLED:
                    _charge_state(state, receipt)
                self._raise_failure(plan, state, *gate_failure)

            provider_dispatch_clock_failed = False
            try:
                started_at = self._now()
            except asyncio.CancelledError:
                receipt = await self._release_capacity(lease, call)
                state.capacity_receipts.append(receipt)
                if receipt.disposition is AdmissionDisposition.SETTLED:
                    _charge_state(state, receipt)
                raise
            except BaseException as exc:
                receipt = await self._release_capacity(lease, call)
                state.capacity_receipts.append(receipt)
                if receipt.disposition is AdmissionDisposition.SETTLED:
                    _charge_state(state, receipt)
                if not isinstance(exc, Exception):
                    raise
                provider_dispatch_clock_failed = True
            if provider_dispatch_clock_failed:
                self._raise_failure(
                    plan,
                    state,
                    ModelFailureKind.INTERNAL,
                    "model_provider_dispatch_clock_failed",
                    "provider_dispatch_clock_failed",
                )
            try:
                (
                    response,
                    provider_failure,
                    latency_ms,
                    provider_dispatched,
                ) = await _call_provider(
                    provider,
                    provider_request,
                    call,
                    now=started_at,
                )
            except BaseException:
                capacity = await self._settle_unknown(lease, call)
                state.capacity_receipts.append(capacity)
                _charge_state(state, capacity)
                raise
            if provider_dispatched:
                state.used_calls += 1
                if attempt_number > 1:
                    state.used_retries += 1
            state.total_latency_ms += latency_ms

            if provider_failure is not None:
                capacity = (
                    await self._settle_unknown(lease, call)
                    if provider_dispatched
                    else await self._release_capacity(lease, call)
                )
                state.capacity_receipts.append(capacity)
                if capacity.disposition is AdmissionDisposition.SETTLED:
                    _charge_state(state, capacity)
                if not provider_dispatched:
                    self._raise_model_error(plan, state, provider_failure)
                state.attempts.append(
                    _route_attempt(
                        current,
                        attempt_number,
                        attempt_kind,
                        admission.request.reservation_id,
                        provider_request_value_digest,
                        prompt_revision,
                        started_at,
                        latency_ms,
                        provider_failure,
                    )
                )
                transition = _next_candidate(
                    plan,
                    state,
                    current,
                    provider_failure.failure_kind,
                    candidates_by_tier,
                    provider_invoked=True,
                    idempotent=request.idempotency_key is not None,
                    outcome_unknown=provider_failure.info.outcome_unknown,
                )
                if transition is None:
                    self._raise_model_error(plan, state, provider_failure)
                current, next_kind = transition
                continue

            if response is None:  # defensive
                internal = _provider_error(
                    ModelFailureKind.INTERNAL,
                    "provider_returned_no_result",
                )
                capacity = await self._settle_unknown(lease, call)
                state.capacity_receipts.append(capacity)
                _charge_state(state, capacity)
                state.attempts.append(
                    _route_attempt(
                        current,
                        attempt_number,
                        attempt_kind,
                        admission.request.reservation_id,
                        provider_request_value_digest,
                        prompt_revision,
                        started_at,
                        latency_ms,
                        internal,
                    )
                )
                self._raise_model_error(plan, state, internal)

            inspection_failure = None
            try:
                receipt_failure = _validate_provider_response(
                    response,
                    provider_request,
                    current,
                    endpoint_descriptor,
                    provider_request_value_digest,
                )
            except asyncio.CancelledError:
                capacity = await self._settle_unknown(lease, call)
                state.capacity_receipts.append(capacity)
                _charge_state(state, capacity)
                raise
            except BaseException:
                capacity = await self._settle_unknown(lease, call)
                state.capacity_receipts.append(capacity)
                _charge_state(state, capacity)
                inspection_failure = _provider_error(
                    ModelFailureKind.INTERNAL,
                    "provider_response_inspection_failed",
                    outcome_unknown=True,
                )
            if inspection_failure is not None:
                state.attempts.append(
                    _route_attempt(
                        current,
                        attempt_number,
                        attempt_kind,
                        admission.request.reservation_id,
                        provider_request_value_digest,
                        prompt_revision,
                        started_at,
                        latency_ms,
                        inspection_failure,
                    )
                )
                self._raise_model_error(plan, state, inspection_failure)
            if receipt_failure is not None:
                capacity = await self._settle_unknown(lease, call)
                state.capacity_receipts.append(capacity)
                _charge_state(state, capacity)
                state.attempts.append(
                    _route_attempt(
                        current,
                        attempt_number,
                        attempt_kind,
                        admission.request.reservation_id,
                        provider_request_value_digest,
                        prompt_revision,
                        started_at,
                        latency_ms,
                        receipt_failure,
                    )
                )
                self._raise_model_error(plan, state, receipt_failure)

            settlement_failure = None
            try:
                capacity = await self._admission.settle(
                    lease,
                    response.usage,
                    call=call,
                )
            except asyncio.CancelledError:
                capacity = await self._settle_unknown(lease, call)
                state.capacity_receipts.append(capacity)
                _charge_state(state, capacity)
                raise
            except BaseException:
                capacity = await self._settle_unknown(lease, call)
                state.capacity_receipts.append(capacity)
                _charge_state(state, capacity)
                settlement_failure = _provider_error(
                    ModelFailureKind.INTERNAL,
                    "provider_usage_receipt_invalid",
                )
            if settlement_failure is not None:
                state.attempts.append(
                    _route_attempt(
                        current,
                        attempt_number,
                        attempt_kind,
                        admission.request.reservation_id,
                        provider_request_value_digest,
                        prompt_revision,
                        started_at,
                        latency_ms,
                        settlement_failure,
                    )
                )
                self._raise_model_error(plan, state, settlement_failure)
            state.capacity_receipts.append(capacity)
            _charge_state(state, capacity)

            runtime_stop = _runtime_stop_failure(
                call,
                self._now(),
                stage="after_provider",
            )
            if runtime_stop is not None:
                stopped = _provider_error(runtime_stop[0], runtime_stop[2])
                state.attempts.append(
                    _route_attempt(
                        current,
                        attempt_number,
                        attempt_kind,
                        admission.request.reservation_id,
                        provider_request_value_digest,
                        prompt_revision,
                        started_at,
                        latency_ms,
                        stopped,
                    )
                )
                self._raise_model_error(plan, state, stopped)

            safety_failure = None
            if any(item.blocked for item in response.safety_annotations):
                safety_failure = _provider_error(
                    ModelFailureKind.SAFETY_REJECTED,
                    "provider_safety_blocked",
                )
            if safety_failure is not None:
                state.attempts.append(
                    _route_attempt(
                        current,
                        attempt_number,
                        attempt_kind,
                        admission.request.reservation_id,
                        provider_request_value_digest,
                        prompt_revision,
                        started_at,
                        latency_ms,
                        safety_failure,
                    )
                )
                self._raise_model_error(plan, state, safety_failure)

            output = response.output
            validation_failure = None
            if request.output_schema is not None:
                try:
                    if self._output_codec is None:
                        raise _validation_failure("model_output_codec_missing")
                    output = self._output_codec.validate(
                        response.output,
                        request.output_schema,
                    )
                except DududaError:
                    validation_failure = _provider_error(
                        ModelFailureKind.OUTPUT_INVALID,
                        "structured_output_validation_failed",
                    )
            runtime_stop = _runtime_stop_failure(
                call,
                self._now(),
                stage="after_output_validation",
            )
            if runtime_stop is not None:
                stopped = _provider_error(runtime_stop[0], runtime_stop[2])
                state.attempts.append(
                    _route_attempt(
                        current,
                        attempt_number,
                        attempt_kind,
                        admission.request.reservation_id,
                        provider_request_value_digest,
                        prompt_revision,
                        started_at,
                        latency_ms,
                        stopped,
                    )
                )
                self._raise_model_error(plan, state, stopped)
            if validation_failure is not None:
                state.attempts.append(
                    _route_attempt(
                        current,
                        attempt_number,
                        attempt_kind,
                        admission.request.reservation_id,
                        provider_request_value_digest,
                        prompt_revision,
                        started_at,
                        latency_ms,
                        validation_failure,
                    )
                )
                transition = _next_candidate(
                    plan,
                    state,
                    current,
                    ModelFailureKind.OUTPUT_INVALID,
                    candidates_by_tier,
                    provider_invoked=True,
                    idempotent=request.idempotency_key is not None,
                )
                if transition is None:
                    self._raise_model_error(plan, state, validation_failure)
                current, next_kind = transition
                continue

            state.attempts.append(
                _route_attempt(
                    current,
                    attempt_number,
                    attempt_kind,
                    admission.request.reservation_id,
                    provider_request_value_digest,
                    prompt_revision,
                    started_at,
                    latency_ms,
                    None,
                )
            )
            decision = self._decision(plan, state, None, None)
            return ModelResponse(
                schema_version=1,
                request_id=request.request_id,
                role=request.role,
                output_schema_digest=plan.output_schema_digest,
                output=output,
                finish_reason=response.finish_reason,
                usage=response.usage,
                latency_ms=state.total_latency_ms,
                route_decision=decision,
                safety_annotations=response.safety_annotations,
                processing=response.processing,
            )

    def _plan(
        self,
        request: ModelRequest,
        authority: TierAuthority,
        call: PortCallContext,
    ) -> _RoutePlan:
        routing = self._routing_registry.acquire_snapshot()
        operational = self._operational_registry.acquire_snapshot()
        policy = self._routing_registry.policy_for(routing, request.role)
        requested_tier = authority.selected_tier
        if requested_tier not in policy.allowed_tiers:
            raise _validation_failure("tier_not_allowed_for_role")
        if request.reasoning_profile_id != policy.requirements.reasoning_profile_id:
            raise _validation_failure("reasoning_profile_policy_mismatch")
        output_schema_digest = (
            request.output_schema.digest if request.output_schema is not None else None
        )
        if request.output_schema is not None and self._output_codec is None:
            raise _validation_failure("model_output_codec_missing")
        output_codec_revision = (
            self._output_codec.revision
            if request.output_schema is not None and self._output_codec is not None
            else None
        )
        tier_order = _reachable_tiers(requested_tier, policy)
        tier_index = {tier: index for index, tier in enumerate(tier_order)}
        refs = sorted(
            policy.candidate_endpoints,
            key=lambda ref: (
                tier_index.get(ref.tier, len(tier_order)),
                ref.priority,
                ref.endpoint_id,
                ref.provider_id,
            ),
        )
        accepted: list[EndpointRouteCandidatePlan] = []
        rejected: list[EndpointRejection] = []
        for ref in refs:
            candidate, reason = self._evaluate_candidate(
                request,
                ref,
                routing,
                operational,
                policy,
                tier_order,
                call,
            )
            if candidate is None:
                rejected.append(_rejection(ref, reason or "candidate_rejected"))
            else:
                accepted.append(candidate)
        accepted = _sort_candidates(accepted, request, tier_order)
        if not any(candidate.endpoint.tier is requested_tier for candidate in accepted):
            rejected.extend(
                _rejection(
                    candidate.endpoint,
                    "initial_tier_has_no_eligible_endpoint",
                )
                for candidate in accepted
            )
            accepted = []
        eligible = tuple(candidate.endpoint for candidate in accepted)
        planned_endpoint = eligible[0] if eligible else None
        receipt_profile = (
            accepted[0].reasoning_profile
            if accepted
            else _receipt_profile(request, routing, policy)
        )
        fingerprint = route_plan_fingerprint(
            model_request_fingerprint=model_request_fingerprint(request),
            tier_selection_fingerprint=authority.selection_fingerprint,
            requested_tier=requested_tier,
            catalog_revision=routing.catalog_revision,
            route_policy_digest=model_route_policy_digest(policy),
            output_schema_digest=output_schema_digest,
            output_codec_revision=output_codec_revision,
            candidate_plans=tuple(accepted),
            rejected_endpoints=tuple(rejected),
            planned_endpoint=planned_endpoint,
        )
        return _RoutePlan(
            request=request,
            authority=authority,
            routing=routing,
            operational=operational,
            policy=policy,
            requested_tier=requested_tier,
            output_schema_digest=output_schema_digest,
            output_codec_revision=output_codec_revision,
            candidate_plans=tuple(accepted),
            rejected_endpoints=tuple(rejected),
            planned_endpoint=planned_endpoint,
            receipt_profile=receipt_profile,
            fingerprint=fingerprint,
        )

    def _evaluate_candidate(
        self,
        request: ModelRequest,
        ref: ModelEndpointRef,
        routing: ModelRoutingSnapshot,
        operational: ModelOperationalSnapshot,
        policy: ModelRoutePolicy,
        reachable_tiers: tuple[ModelTier, ...],
        call: PortCallContext,
    ) -> tuple[EndpointRouteCandidatePlan | None, str | None]:
        if ref.tier not in reachable_tiers:
            return None, "tier_not_reachable"
        endpoint = _endpoint_descriptor(routing, ref)
        privacy_result = _privacy_selection(request, policy, endpoint)
        if isinstance(privacy_result, str):
            return None, privacy_result
        residency, retention = privacy_result
        capability_reason = _capability_reason(request, policy, endpoint)
        if capability_reason is not None:
            return None, capability_reason
        profile = next(
            (
                item
                for item in endpoint.reasoning_profiles
                if item.profile_id == request.reasoning_profile_id
            ),
            None,
        )
        if profile is None:
            return None, "reasoning_profile_not_supported"
        try:
            estimate = self._estimator.estimate(request, endpoint, profile)
        except DududaError as exc:
            return None, f"estimate:{exc.info.code}"
        context_reason = _context_reason(request, endpoint, estimate)
        if context_reason is not None:
            return None, context_reason
        budget_reason = _initial_budget_reason(call, estimate)
        if budget_reason is not None:
            return None, budget_reason
        operational_reason = _operational_reason(
            operational,
            ref,
            endpoint,
            estimate,
            call,
            self._now(),
        )
        if operational_reason is not None:
            return None, operational_reason
        return (
            EndpointRouteCandidatePlan(
                schema_version=1,
                endpoint=ref,
                estimate=estimate,
                reasoning_profile=profile,
                selected_data_residency=residency,
                required_retention_mode=retention,
            ),
            None,
        )

    def _admission_request(
        self,
        plan: _RoutePlan,
        candidate: EndpointRouteCandidatePlan,
        call: PortCallContext,
    ) -> EndpointAdmissionRequest:
        endpoint = _endpoint_descriptor(plan.routing, candidate.endpoint)
        estimate = candidate.estimate
        return EndpointAdmissionRequest(
            schema_version=1,
            reservation_id=self._new_id("reservation"),
            model_request_id=plan.request.request_id,
            model_request_digest=model_request_digest(plan.request),
            provider_id=candidate.endpoint.provider_id,
            endpoint_id=candidate.endpoint.endpoint_id,
            endpoint_descriptor_digest=candidate.endpoint.endpoint_descriptor_digest,
            quota_pool_id=endpoint.quota_pool_id,
            traffic_policy_id=endpoint.traffic_policy.policy_id,
            traffic_policy_revision=endpoint.traffic_policy.policy_revision,
            operational_snapshot_id=plan.operational.snapshot_id,
            operational_snapshot_digest=model_operational_snapshot_digest(
                plan.operational
            ),
            invocation_estimate_digest=model_invocation_estimate_digest(estimate),
            invocation_estimate=estimate,
            reserved_input_tokens=estimate.input_tokens_upper_bound,
            reserved_generated_tokens=estimate.generated_tokens_upper_bound,
            reserved_reasoning_tokens=estimate.reasoning_tokens_upper_bound,
            reserved_cost_units=estimate.cost_units_upper_bound,
            expires_at=call.deadline,
        )

    def _provider_request(
        self,
        plan: _RoutePlan,
        candidate: EndpointRouteCandidatePlan,
        attempt: int,
        attempt_kind: RouteAttemptKind,
        prompt_revision: ComponentRevision,
    ) -> ProviderRequest:
        provider = _provider_descriptor(
            plan.routing,
            candidate.endpoint.provider_id,
        )
        request = plan.request
        return ProviderRequest(
            schema_version=1,
            request_id=self._new_id("provider-request"),
            provider_id=provider.provider_id,
            provider_revision=provider.revision,
            endpoint_id=candidate.endpoint.endpoint_id,
            endpoint_descriptor_digest=candidate.endpoint.endpoint_descriptor_digest,
            model_id=candidate.endpoint.model_id,
            selected_tier=candidate.endpoint.tier,
            tier_authority_digest=tier_authority_digest(plan.authority),
            invocation_estimate_digest=model_invocation_estimate_digest(
                candidate.estimate
            ),
            route_policy_revision=plan.policy.policy_revision,
            attempt=attempt,
            attempt_kind=attempt_kind,
            prompt_template_revision=prompt_revision,
            selected_data_residency=candidate.selected_data_residency,
            required_retention_mode=candidate.required_retention_mode,
            role=request.role,
            input=request.input,
            output_schema=request.output_schema,
            max_output_tokens=request.max_output_tokens,
            temperature=request.temperature,
            privacy=request.privacy,
            reasoning_profile=candidate.reasoning_profile,
            random_seed=request.random_seed,
            idempotency_key=(
                f"{request.idempotency_key}:attempt:{attempt}"
                if request.idempotency_key is not None
                else None
            ),
        )

    async def _settle_unknown(self, lease, call) -> EndpointCapacityReceipt:
        return await self._admission.settle(lease, None, call=call)

    async def _release_capacity(self, lease, call) -> EndpointCapacityReceipt:
        try:
            return await self._admission.release(lease, call=call)
        except DududaError as exc:
            if exc.info.code != "capacity_lease_already_finalized":
                raise
            return await self._admission.settle(lease, None, call=call)

    def _decision(
        self,
        plan: _RoutePlan,
        state: _ExecutionState,
        failure_kind: ModelFailureKind | None,
        failure_info,
    ) -> RouteDecision:
        selected_endpoint = (
            _attempt_endpoint(plan.candidate_plans, state.attempts[-1])
            if state.attempts
            else None
        )
        selected_plan = (
            next(
                (
                    item
                    for item in plan.candidate_plans
                    if item.endpoint == selected_endpoint
                ),
                None,
            )
            if selected_endpoint is not None
            else None
        )
        return RouteDecision(
            schema_version=1,
            decision_id=self._new_id("route-decision"),
            request_id=plan.request.request_id,
            model_request_digest=model_request_digest(plan.request),
            model_request_fingerprint=model_request_fingerprint(plan.request),
            role=plan.request.role,
            requested_tier=plan.requested_tier,
            selected_tier=(
                selected_endpoint.tier if selected_endpoint is not None else None
            ),
            tier_authority_digest=tier_authority_digest(plan.authority),
            tier_selection_fingerprint=plan.authority.selection_fingerprint,
            routing_snapshot_id=plan.routing.snapshot_id,
            catalog_revision=plan.routing.catalog_revision,
            route_policy_revision=plan.policy.policy_revision,
            operational_snapshot_id=plan.operational.snapshot_id,
            operational_snapshot_digest=model_operational_snapshot_digest(
                plan.operational
            ),
            output_schema_digest=plan.output_schema_digest,
            output_codec_revision=plan.output_codec_revision,
            route_plan_fingerprint=plan.fingerprint,
            candidate_plans=plan.candidate_plans,
            eligible_endpoints=tuple(
                candidate.endpoint for candidate in plan.candidate_plans
            ),
            rejected_endpoints=plan.rejected_endpoints,
            planned_endpoint=plan.planned_endpoint,
            selected_endpoint=selected_endpoint,
            reasoning_profile=(
                selected_plan.reasoning_profile
                if selected_plan is not None
                else plan.receipt_profile
            ),
            admission_results=tuple(state.admissions),
            capacity_receipts=tuple(state.capacity_receipts),
            attempts=tuple(state.attempts),
            terminal_failure_kind=failure_kind,
            terminal_error=failure_info,
            decided_at=self._now(),
        )

    def _raise_failure(
        self,
        plan: _RoutePlan,
        state: _ExecutionState,
        failure_kind: ModelFailureKind,
        code: str,
        reason_code: str,
    ) -> None:
        info = model_error_info(
            failure_kind,
            code=code,
            reason_codes=(reason_code,),
        )
        decision = self._decision(plan, state, failure_kind, info)
        raise ModelInvocationError(failure_kind, info, decision)

    def _raise_model_error(
        self,
        plan: _RoutePlan,
        state: _ExecutionState,
        provider_error: ModelProviderError,
    ) -> None:
        decision = self._decision(
            plan,
            state,
            provider_error.failure_kind,
            provider_error.info,
        )
        raise ModelInvocationError(
            provider_error.failure_kind,
            provider_error.info,
            decision,
        )

    def _prompt_revision(
        self,
        role: ModelRole,
        attempt_kind: RouteAttemptKind,
    ) -> ComponentRevision:
        values = (
            self._repair_revisions
            if attempt_kind is RouteAttemptKind.SCHEMA_REPAIR
            else self._prompt_revisions
        )
        revision = values.get(role)
        if revision is None:
            raise _validation_failure("prompt_template_revision_missing")
        return revision

    @staticmethod
    def _validate_bootstrap_authority(authority: TierAuthority) -> None:
        if not isinstance(authority, BootstrapTierDecision):
            return
        expected = bootstrap_tier_selection_fingerprint(
            role=authority.role,
            selected_tier=authority.selected_tier,
            tier_policy_digest=authority.tier_policy_digest,
            policy_revision=authority.policy_revision,
            reason_codes=authority.reason_codes,
        )
        if expected != authority.selection_fingerprint:
            raise _validation_failure("bootstrap_tier_fingerprint_mismatch")

    def _new_id(self, prefix: str) -> str:
        value = self._id_factory()
        if not isinstance(value, str) or not value.strip():
            raise ValueError("id_factory returned an empty identifier")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock returned a naive datetime")
        return value


def _privacy_selection(
    request: ModelRequest,
    policy: ModelRoutePolicy,
    endpoint: ModelEndpointDescriptor,
) -> tuple[str, ModelRetentionMode] | str:
    classification = request.privacy.data_classification
    if classification not in policy.allowed_data_classes:
        return "privacy_class_not_allowed_by_policy"
    if classification not in endpoint.allowed_data_classes:
        return "privacy_class_not_allowed_by_endpoint"
    if (
        endpoint.processing_boundary is ModelProcessingBoundary.EXTERNAL
        and not request.privacy.allow_external_provider
    ):
        return "external_processing_forbidden"
    residencies = sorted(
        request.privacy.allowed_residencies & endpoint.available_data_residencies
    )
    if not residencies:
        return "data_residency_unavailable"
    if ModelRetentionMode.NO_RETENTION in endpoint.supported_retention_modes:
        retention = ModelRetentionMode.NO_RETENTION
    elif (
        request.privacy.allow_provider_retention
        and ModelRetentionMode.PROVIDER_MANAGED in endpoint.supported_retention_modes
    ):
        retention = ModelRetentionMode.PROVIDER_MANAGED
    else:
        return "retention_policy_unavailable"
    return residencies[0], retention


def _capability_reason(
    request: ModelRequest,
    policy: ModelRoutePolicy,
    endpoint: ModelEndpointDescriptor,
) -> str | None:
    capabilities = endpoint.capabilities
    input_modalities = frozenset(part.modality for part in request.input.parts)
    if not input_modalities <= policy.requirements.input_modalities:
        return "request_input_modality_not_allowed"
    if not input_modalities <= capabilities.input_modalities:
        return "endpoint_input_modality_unsupported"
    if not policy.requirements.output_modalities <= capabilities.output_modalities:
        return "endpoint_output_modality_unsupported"
    if request.output_schema is None and policy.requirements.requires_schema_validation:
        return "output_schema_required"
    if not _structured_supports(
        capabilities.native_structured_output,
        policy.requirements.minimum_native_structured_output,
    ):
        return "native_structured_output_insufficient"
    if request.temperature is not None and not capabilities.supports_temperature:
        return "temperature_not_supported"
    if request.random_seed is not None and not capabilities.supports_seed:
        return "seed_not_supported"
    if request.max_output_tokens > capabilities.max_output_tokens:
        return "output_token_limit_exceeded"
    return None


def _context_reason(
    request: ModelRequest,
    endpoint: ModelEndpointDescriptor,
    estimate: ModelInvocationEstimate,
) -> str | None:
    if estimate.generated_tokens_upper_bound > endpoint.capabilities.max_output_tokens:
        return "output_token_limit_exceeded"
    if (
        endpoint.capabilities.max_input_tokens is not None
        and estimate.input_tokens_upper_bound > endpoint.capabilities.max_input_tokens
    ):
        return "input_context_limit_exceeded"
    if (
        estimate.total_context_tokens_upper_bound
        > endpoint.capabilities.max_context_tokens
    ):
        return "total_context_limit_exceeded"
    if estimate.generated_tokens_upper_bound != request.max_output_tokens:
        return "generated_token_estimate_mismatch"
    return None


def _initial_budget_reason(
    call: PortCallContext,
    estimate: ModelInvocationEstimate,
) -> str | None:
    budget = call.budget
    if budget.model_calls_remaining < 1:
        return "model_call_budget_exhausted"
    if estimate.input_tokens_upper_bound > budget.input_tokens_remaining:
        return "input_token_budget_exhausted"
    if estimate.generated_tokens_upper_bound > budget.output_tokens_remaining:
        return "generated_token_budget_exhausted"
    if budget.cost_units_remaining is not None:
        if estimate.cost_units_upper_bound is None:
            return "model_cost_estimate_unknown"
        if estimate.cost_units_upper_bound > budget.cost_units_remaining:
            return "model_cost_budget_exhausted"
    return None


def _operational_reason(
    snapshot: ModelOperationalSnapshot,
    ref: ModelEndpointRef,
    endpoint: ModelEndpointDescriptor,
    estimate: ModelInvocationEstimate,
    call: PortCallContext,
    now: datetime,
) -> str | None:
    provider_health = next(
        (
            item
            for item in snapshot.provider_health
            if item.provider_id == ref.provider_id
        ),
        None,
    )
    if provider_health is None:
        return "provider_health_missing"
    if provider_health.status in {
        EndpointHealthStatus.UNAVAILABLE,
        EndpointHealthStatus.UNKNOWN,
    }:
        return "provider_health_unavailable"
    if provider_health.checked_at > now:
        return "provider_health_from_future"
    if (
        now - provider_health.checked_at
    ).total_seconds() > endpoint.traffic_policy.max_snapshot_age_seconds:
        return "provider_health_stale"
    endpoint_health = next(
        (
            item
            for item in provider_health.endpoints
            if item.endpoint_id == ref.endpoint_id
        ),
        None,
    )
    if endpoint_health is None:
        return "endpoint_health_missing"
    if endpoint_health.endpoint_descriptor_digest != endpoint.descriptor_digest:
        return "endpoint_health_revision_mismatch"
    if endpoint_health.status in {
        EndpointHealthStatus.UNAVAILABLE,
        EndpointHealthStatus.UNKNOWN,
    }:
        return "endpoint_health_unavailable"
    load = next(
        (
            item
            for item in snapshot.endpoint_load
            if item.provider_id == ref.provider_id
            and item.endpoint_id == ref.endpoint_id
        ),
        None,
    )
    if load is None:
        return "endpoint_load_missing"
    policy = endpoint.traffic_policy
    if (
        load.endpoint_descriptor_digest != endpoint.descriptor_digest
        or load.quota_pool_id != endpoint.quota_pool_id
        or load.traffic_policy_id != policy.policy_id
        or load.traffic_policy_revision != policy.policy_revision
    ):
        return "endpoint_load_revision_mismatch"
    if load.checked_at > now:
        return "endpoint_load_from_future"
    age = (now - load.checked_at).total_seconds()
    if (
        age > policy.max_snapshot_age_seconds
        and policy.stale_snapshot_policy is StaleSnapshotPolicy.EXCLUDE
    ):
        return "endpoint_load_stale"
    if load.sample_count < policy.minimum_samples:
        return "endpoint_load_samples_insufficient"
    if load.cooldown_until is not None and load.cooldown_until > now:
        return "endpoint_cooldown_active"
    if policy.max_p95_latency_ms is not None:
        if load.p95_latency_ms is None:
            return "endpoint_latency_missing"
        if load.p95_latency_ms > policy.max_p95_latency_ms:
            return "endpoint_latency_exceeded"
    if load.rate_429 > policy.max_429_rate:
        return "endpoint_429_rate_exceeded"
    if load.error_rate > policy.max_error_rate:
        return "endpoint_error_rate_exceeded"
    if load.queue_depth > policy.max_queue_depth:
        return "endpoint_queue_exceeded"
    if load.in_flight >= policy.max_concurrency and (
        policy.max_queue_depth == 0 or load.queue_depth >= policy.max_queue_depth
    ):
        return "endpoint_concurrency_exhausted"
    if policy.rpm_limit is not None and load.requests_per_minute + 1 > policy.rpm_limit:
        return "endpoint_rpm_exhausted"
    if (
        policy.tpm_limit is not None
        and load.tokens_per_minute
        + estimate.input_tokens_upper_bound
        + estimate.generated_tokens_upper_bound
        > policy.tpm_limit
    ):
        return "endpoint_tpm_exhausted"
    if load.p95_latency_ms is not None and (
        now + timedelta(milliseconds=load.p95_latency_ms) >= call.deadline
    ):
        return "endpoint_deadline_insufficient"
    return None


def _attempt_gate_failure(
    plan: _RoutePlan,
    state: _ExecutionState,
    candidate: EndpointRouteCandidatePlan,
    call: PortCallContext,
    now: datetime,
) -> tuple[ModelFailureKind, str, str] | None:
    if call.cancellation.is_cancelled:
        return (
            ModelFailureKind.CANCELLED,
            "model_invocation_cancelled",
            "cancelled_before_attempt",
        )
    if now >= call.deadline:
        return (
            ModelFailureKind.TIMEOUT,
            "model_invocation_deadline_exceeded",
            "deadline_before_attempt",
        )
    budget = call.budget
    estimate = candidate.estimate
    if state.used_calls + 1 > min(
        budget.model_calls_remaining,
        plan.policy.fallback.max_total_attempts,
    ):
        return (
            ModelFailureKind.BUDGET_EXHAUSTED,
            "model_call_budget_exhausted",
            "model_call_budget_exhausted",
        )
    if state.used_calls > 0 and state.used_retries + 1 > budget.retries_remaining:
        return (
            ModelFailureKind.BUDGET_EXHAUSTED,
            "model_retry_budget_exhausted",
            "retry_budget_exhausted",
        )
    if (
        state.used_input_tokens + estimate.input_tokens_upper_bound
        > budget.input_tokens_remaining
    ):
        return (
            ModelFailureKind.BUDGET_EXHAUSTED,
            "model_input_budget_exhausted",
            "input_token_budget_exhausted",
        )
    if (
        state.used_generated_tokens + estimate.generated_tokens_upper_bound
        > budget.output_tokens_remaining
    ):
        return (
            ModelFailureKind.BUDGET_EXHAUSTED,
            "model_output_budget_exhausted",
            "generated_token_budget_exhausted",
        )
    if budget.cost_units_remaining is not None:
        if estimate.cost_units_upper_bound is None:
            return (
                ModelFailureKind.BUDGET_EXHAUSTED,
                "model_cost_estimate_unknown",
                "model_cost_estimate_unknown",
            )
        if (
            state.used_cost_units + estimate.cost_units_upper_bound
            > budget.cost_units_remaining
        ):
            return (
                ModelFailureKind.BUDGET_EXHAUSTED,
                "model_cost_budget_exhausted",
                "model_cost_budget_exhausted",
            )
    endpoint = _endpoint_descriptor(plan.routing, candidate.endpoint)
    operational = _operational_reason(
        plan.operational,
        candidate.endpoint,
        endpoint,
        estimate,
        call,
        now,
    )
    if operational is not None:
        return (
            ModelFailureKind.PROVIDER_UNAVAILABLE,
            "model_endpoint_no_longer_eligible",
            operational,
        )
    return None


def _initial_gate_failure(
    plan: _RoutePlan,
    call: PortCallContext,
    now: datetime,
) -> tuple[ModelFailureKind, str, str] | None:
    if call.cancellation.is_cancelled:
        return (
            ModelFailureKind.CANCELLED,
            "model_invocation_cancelled",
            "cancelled_before_routing",
        )
    if now >= call.deadline:
        return (
            ModelFailureKind.TIMEOUT,
            "model_invocation_deadline_exceeded",
            "deadline_before_routing",
        )
    if call.budget.model_calls_remaining < 1:
        return (
            ModelFailureKind.BUDGET_EXHAUSTED,
            "model_call_budget_exhausted",
            "model_call_budget_exhausted",
        )
    return None


def _no_route_failure(plan: _RoutePlan) -> tuple[ModelFailureKind, str, str]:
    requested_keys = {
        (ref.provider_id, ref.endpoint_id)
        for ref in plan.policy.candidate_endpoints
        if ref.tier is plan.requested_tier
    }
    requested_reasons = tuple(
        rejection.reason_codes[0]
        for rejection in plan.rejected_endpoints
        if (rejection.provider_id, rejection.endpoint_id) in requested_keys
    )
    budget_reasons = {
        "model_call_budget_exhausted",
        "input_token_budget_exhausted",
        "generated_token_budget_exhausted",
        "model_cost_estimate_unknown",
        "model_cost_budget_exhausted",
    }
    if requested_reasons and all(
        reason in budget_reasons for reason in requested_reasons
    ):
        return (
            ModelFailureKind.BUDGET_EXHAUSTED,
            "model_budget_exhausted",
            requested_reasons[0],
        )
    if requested_reasons and all(
        reason == "endpoint_deadline_insufficient" for reason in requested_reasons
    ):
        return (
            ModelFailureKind.TIMEOUT,
            "model_invocation_deadline_exceeded",
            "endpoint_deadline_insufficient",
        )
    return (
        ModelFailureKind.ROUTE_NOT_FOUND,
        "model_route_not_found",
        "no_eligible_endpoint",
    )


def _runtime_stop_failure(
    call: PortCallContext,
    now: datetime,
    *,
    stage: str,
) -> tuple[ModelFailureKind, str, str] | None:
    if call.cancellation.is_cancelled:
        return (
            ModelFailureKind.CANCELLED,
            "model_invocation_cancelled",
            f"cancelled_{stage}",
        )
    if now >= call.deadline:
        return (
            ModelFailureKind.TIMEOUT,
            "model_invocation_deadline_exceeded",
            f"deadline_{stage}",
        )
    return None


def _admission_rejection_failure(
    reason: str,
) -> tuple[ModelFailureKind, str, str]:
    if reason == "admission_cancelled":
        return (
            ModelFailureKind.CANCELLED,
            "model_invocation_cancelled",
            reason,
        )
    if reason in {"admission_deadline_exceeded", "deadline_capacity_insufficient"}:
        return (
            ModelFailureKind.TIMEOUT,
            "model_invocation_deadline_exceeded",
            reason,
        )
    if reason in {
        "queue_capacity_exhausted",
        "observed_queue_exceeded",
        "rate_429_exceeded",
        "rpm_capacity_exhausted",
        "tpm_capacity_exhausted",
    }:
        return (
            ModelFailureKind.RATE_LIMITED,
            "model_admission_rejected",
            reason,
        )
    return (
        ModelFailureKind.PROVIDER_UNAVAILABLE,
        "model_admission_rejected",
        reason,
    )


def _next_candidate(
    plan: _RoutePlan,
    state: _ExecutionState,
    current: EndpointRouteCandidatePlan,
    failure_kind: ModelFailureKind,
    candidates_by_tier: Mapping[ModelTier, tuple[EndpointRouteCandidatePlan, ...]],
    *,
    provider_invoked: bool,
    idempotent: bool,
    outcome_unknown: bool = False,
) -> tuple[EndpointRouteCandidatePlan, RouteAttemptKind] | None:
    if outcome_unknown:
        return None
    if failure_kind is ModelFailureKind.OUTPUT_INVALID:
        if (
            provider_invoked
            and state.schema_repairs < plan.policy.fallback.max_schema_repairs
        ):
            state.schema_repairs += 1
            return current, RouteAttemptKind.SCHEMA_REPAIR
        return None
    terminal = {
        ModelFailureKind.ROUTE_NOT_FOUND,
        ModelFailureKind.AUTHENTICATION,
        ModelFailureKind.INVALID_REQUEST,
        ModelFailureKind.CAPABILITY_MISMATCH,
        ModelFailureKind.SAFETY_REJECTED,
        ModelFailureKind.CANCELLED,
        ModelFailureKind.BUDGET_EXHAUSTED,
        ModelFailureKind.INTERNAL,
    }
    if failure_kind in terminal:
        return None
    key = _endpoint_key(current.endpoint)
    if (
        provider_invoked
        and idempotent
        and failure_kind in plan.policy.fallback.retryable_failure_kinds
        and state.endpoint_retries[key] < plan.policy.fallback.max_retries_per_endpoint
    ):
        state.endpoint_retries[key] += 1
        return current, RouteAttemptKind.ENDPOINT_RETRY
    transitions_allowed = (not provider_invoked) or idempotent
    if not transitions_allowed:
        return None
    for candidate in candidates_by_tier.get(current.endpoint.tier, ()):
        if _endpoint_key(candidate.endpoint) in state.visited_endpoints:
            continue
        if state.same_tier_failovers >= plan.policy.fallback.max_same_tier_failovers:
            break
        state.same_tier_failovers += 1
        return candidate, RouteAttemptKind.SAME_TIER_FAILOVER
    if state.tier_hops >= plan.policy.fallback.max_tier_hops:
        return None
    for edge in plan.policy.tier_fallback_edges:
        if (
            edge.from_tier is not current.endpoint.tier
            or failure_kind not in edge.failure_kinds
        ):
            continue
        candidate = next(
            (
                item
                for item in candidates_by_tier.get(edge.to_tier, ())
                if _endpoint_key(item.endpoint) not in state.visited_endpoints
            ),
            None,
        )
        if candidate is not None:
            state.tier_hops += 1
            return candidate, RouteAttemptKind.CROSS_TIER_FALLBACK
    return None


async def _call_provider(
    provider,
    request: ProviderRequest,
    call: PortCallContext,
    *,
    now: datetime,
) -> tuple[ProviderResponse | None, ModelProviderError | None, int, bool]:
    started = time.monotonic()
    try:
        cancelled_before_dispatch = call.cancellation.is_cancelled
    except asyncio.CancelledError:
        return (
            None,
            _provider_error(
                ModelFailureKind.CANCELLED,
                "cancelled_before_provider_dispatch",
            ),
            _elapsed_ms(started),
            False,
        )
    except BaseException:
        return (
            None,
            _provider_error(
                ModelFailureKind.INTERNAL,
                "provider_pre_dispatch_check_failed",
            ),
            _elapsed_ms(started),
            False,
        )
    if cancelled_before_dispatch:
        return (
            None,
            _provider_error(
                ModelFailureKind.CANCELLED,
                "cancelled_before_provider_dispatch",
            ),
            _elapsed_ms(started),
            False,
        )
    if now >= call.deadline:
        return (
            None,
            _provider_error(
                ModelFailureKind.TIMEOUT,
                "deadline_before_provider_dispatch",
            ),
            _elapsed_ms(started),
            False,
        )
    try:
        provider_awaitable = provider.generate(request, call=call)
        provider_task = asyncio.create_task(provider_awaitable)
    except asyncio.CancelledError:
        return (
            None,
            _provider_error(
                ModelFailureKind.CANCELLED,
                "cancelled_while_starting_provider_call",
                outcome_unknown=True,
            ),
            _elapsed_ms(started),
            True,
        )
    except BaseException:
        return (
            None,
            _provider_error(
                ModelFailureKind.INTERNAL,
                "provider_call_start_failed",
                outcome_unknown=True,
            ),
            _elapsed_ms(started),
            True,
        )
    try:
        cancellation_task = asyncio.create_task(call.cancellation.wait())
    except BaseException:
        await _cancel_provider_task(provider_task)
        return (
            None,
            _provider_error(
                ModelFailureKind.INTERNAL,
                "provider_cancellation_watch_start_failed",
                outcome_unknown=True,
            ),
            _elapsed_ms(started),
            True,
        )
    remaining = max(
        0.0,
        (call.deadline - now).total_seconds(),
    )
    response = None
    provider_failure = None
    try:
        done, _ = await asyncio.wait(
            (provider_task, cancellation_task),
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation_task in done:
            watcher_failed = False
            try:
                cancellation_task.result()
            except BaseException:
                watcher_failed = True
            await _cancel_provider_task(provider_task)
            provider_failure = (
                _provider_error(
                    ModelFailureKind.INTERNAL,
                    "provider_cancellation_watch_failed",
                    outcome_unknown=True,
                )
                if watcher_failed
                else _provider_error(
                    ModelFailureKind.CANCELLED,
                    "cancelled_during_provider_call",
                    outcome_unknown=True,
                )
            )
        elif provider_task not in done:
            cancelled_during_cleanup = await _cancel_provider_task(provider_task)
            if cancelled_during_cleanup:
                provider_failure = _provider_error(
                    ModelFailureKind.CANCELLED,
                    "cancelled_while_stopping_provider_call",
                    outcome_unknown=True,
                )
            else:
                provider_failure = _provider_error(
                    ModelFailureKind.TIMEOUT,
                    "provider_call_deadline_exceeded",
                    outcome_unknown=True,
                )
        else:
            try:
                response = provider_task.result()
                if type(response) is not ProviderResponse:
                    provider_failure = _provider_error(
                        ModelFailureKind.INTERNAL,
                        "provider_returned_invalid_response",
                        outcome_unknown=True,
                    )
                    response = None
            except ModelProviderError as exc:
                provider_failure = _normalize_provider_error(exc)
            except asyncio.CancelledError:
                provider_failure = _provider_error(
                    ModelFailureKind.CANCELLED,
                    "provider_task_cancelled",
                    outcome_unknown=True,
                )
            except Exception:
                provider_failure = _provider_error(
                    ModelFailureKind.INTERNAL,
                    "provider_protocol_exception",
                    outcome_unknown=True,
                )
    except asyncio.CancelledError:
        await _cancel_provider_task(provider_task)
        response = None
        provider_failure = _provider_error(
            ModelFailureKind.CANCELLED,
            "router_task_cancelled_during_provider_call",
            outcome_unknown=True,
        )
    finally:
        cancelled_during_cleanup = await _cancel_provider_task(cancellation_task)
        if cancelled_during_cleanup and provider_failure is None:
            response = None
            provider_failure = _provider_error(
                ModelFailureKind.CANCELLED,
                "router_task_cancelled_during_provider_cleanup",
                outcome_unknown=True,
            )
    return response, provider_failure, _elapsed_ms(started), True


async def _cancel_provider_task(task: asyncio.Task[object]) -> bool:
    cleanup = asyncio.create_task(_bounded_cancel_provider_task(task))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
            continue
    cleanup.result()
    return cancelled


async def _bounded_cancel_provider_task(task: asyncio.Task[object]) -> None:
    if task.done():
        _consume_detached_task(task)
        return
    task.cancel()
    done, _ = await asyncio.wait((task,), timeout=0.1)
    if task not in done:
        task.add_done_callback(_consume_detached_task)
        return
    _consume_detached_task(task)


def _consume_detached_task(task: asyncio.Task[object]) -> None:
    try:
        task.result()
    except BaseException:
        pass


def _validate_provider_response(
    response: ProviderResponse,
    request: ProviderRequest,
    candidate: EndpointRouteCandidatePlan,
    endpoint_descriptor: ModelEndpointDescriptor,
    expected_request_digest: DigestString,
) -> ModelProviderError | None:
    endpoint = candidate.endpoint
    processing = response.processing
    if (
        response.request_id != request.request_id
        or response.provider_id != request.provider_id
        or response.provider_revision != request.provider_revision
        or response.endpoint_id != request.endpoint_id
        or response.model_id != request.model_id
        or processing.provider_request_digest != expected_request_digest
        or processing.endpoint_descriptor_digest != endpoint.endpoint_descriptor_digest
        or processing.processing_boundary is not endpoint_descriptor.processing_boundary
        or processing.data_residency != candidate.selected_data_residency
        or processing.retention_mode is not candidate.required_retention_mode
        or processing.requested_reasoning_profile_id
        != candidate.reasoning_profile.profile_id
        or (
            candidate.reasoning_profile.required
            and processing.effective_reasoning_profile_id
            != candidate.reasoning_profile.profile_id
        )
        or processing.requested_seed != request.random_seed
        or processing.effective_seed != request.random_seed
    ):
        return _provider_error(
            ModelFailureKind.INTERNAL,
            "provider_response_receipt_mismatch",
        )
    return None


def _route_attempt(
    candidate: EndpointRouteCandidatePlan,
    attempt_number: int,
    attempt_kind: RouteAttemptKind,
    admission_reservation_id: str,
    request_digest: DigestString,
    prompt_revision: ComponentRevision,
    started_at: datetime,
    latency_ms: int,
    failure: ModelProviderError | None,
) -> RouteAttempt:
    return RouteAttempt(
        schema_version=1,
        attempt=attempt_number,
        kind=attempt_kind,
        provider_id=candidate.endpoint.provider_id,
        endpoint_id=candidate.endpoint.endpoint_id,
        model_id=candidate.endpoint.model_id,
        tier=candidate.endpoint.tier,
        invocation_estimate_digest=model_invocation_estimate_digest(candidate.estimate),
        admission_reservation_id=admission_reservation_id,
        provider_request_digest=request_digest,
        prompt_template_revision=prompt_revision,
        started_at=started_at,
        latency_ms=latency_ms,
        failure_kind=(failure.failure_kind if failure is not None else None),
        error=(failure.info if failure is not None else None),
    )


def _charge_state(
    state: _ExecutionState,
    receipt: EndpointCapacityReceipt,
) -> None:
    if receipt.usage is None:
        raise _validation_failure("settled_capacity_usage_missing")
    state.used_input_tokens += receipt.usage.input_tokens
    state.used_generated_tokens += receipt.usage.generated_tokens
    if receipt.usage.cost_units is not None:
        state.used_cost_units += receipt.usage.cost_units


def _provider_error(
    failure_kind: ModelFailureKind,
    reason_code: str,
    *,
    outcome_unknown: bool = False,
) -> ModelProviderError:
    return ModelProviderError(
        failure_kind,
        model_error_info(
            failure_kind,
            code=f"model_{failure_kind.value}",
            reason_codes=(reason_code,),
            outcome_unknown=outcome_unknown,
        ),
    )


def _normalize_provider_error(error: ModelProviderError) -> ModelProviderError:
    try:
        failure_kind = error.failure_kind
        info = error.info
        if not isinstance(failure_kind, ModelFailureKind) or not isinstance(
            info, ErrorInfo
        ):
            raise TypeError
        validate_model_failure_info(failure_kind, info)
        if error.detail is not None:
            raise ValueError
    except Exception:
        return _provider_error(
            ModelFailureKind.INTERNAL,
            "provider_error_contract_violation",
            outcome_unknown=True,
        )
    return ModelProviderError(
        failure_kind,
        model_error_info(
            failure_kind,
            code=f"provider_{failure_kind.value}",
            reason_codes=("provider_reported_failure",),
            outcome_unknown=info.outcome_unknown,
        ),
    )


def _validation_failure(reason_code: str) -> DududaError:
    return _provider_error(ModelFailureKind.INVALID_REQUEST, reason_code)


def _rejection(ref: ModelEndpointRef, reason: str) -> EndpointRejection:
    return EndpointRejection(
        schema_version=1,
        provider_id=ref.provider_id,
        endpoint_id=ref.endpoint_id,
        reason_codes=(reason,),
    )


def _reachable_tiers(
    initial: ModelTier,
    policy: ModelRoutePolicy,
) -> tuple[ModelTier, ...]:
    result = [initial]
    index = 0
    while index < len(result):
        current = result[index]
        for edge in policy.tier_fallback_edges:
            if edge.from_tier is current and edge.to_tier not in result:
                result.append(edge.to_tier)
        index += 1
    return tuple(result)


def _sort_candidates(
    candidates: list[EndpointRouteCandidatePlan],
    request: ModelRequest,
    tier_order: tuple[ModelTier, ...],
) -> list[EndpointRouteCandidatePlan]:
    tier_index = {tier: index for index, tier in enumerate(tier_order)}
    return sorted(
        candidates,
        key=lambda item: (
            tier_index[item.endpoint.tier],
            0 if _hint_matches(request, item.endpoint) else 1,
            item.endpoint.priority,
            item.endpoint.endpoint_id,
            item.endpoint.provider_id,
        ),
    )


def _hint_matches(request: ModelRequest, ref: ModelEndpointRef) -> bool:
    hint = request.route_hint
    if hint is None:
        return False
    return all(
        expected is None or expected == actual
        for expected, actual in (
            (hint.provider_id, ref.provider_id),
            (hint.endpoint_id, ref.endpoint_id),
            (hint.model_id, ref.model_id),
        )
    )


def _candidates_by_tier(
    candidates: tuple[EndpointRouteCandidatePlan, ...],
) -> dict[ModelTier, tuple[EndpointRouteCandidatePlan, ...]]:
    values: dict[ModelTier, list[EndpointRouteCandidatePlan]] = defaultdict(list)
    for candidate in candidates:
        values[candidate.endpoint.tier].append(candidate)
    return {tier: tuple(items) for tier, items in values.items()}


def _provider_descriptor(
    snapshot: ModelRoutingSnapshot,
    provider_id: str,
) -> ModelProviderDescriptor:
    for provider in snapshot.provider_descriptors:
        if provider.provider_id == provider_id:
            return provider
    raise _validation_failure("provider_descriptor_not_found")


def _endpoint_descriptor(
    snapshot: ModelRoutingSnapshot,
    ref: ModelEndpointRef,
) -> ModelEndpointDescriptor:
    provider = _provider_descriptor(snapshot, ref.provider_id)
    for endpoint in provider.endpoints:
        if endpoint.endpoint_id == ref.endpoint_id:
            if (
                endpoint.model_id != ref.model_id
                or endpoint.tier is not ref.tier
                or endpoint.descriptor_digest != ref.endpoint_descriptor_digest
            ):
                raise _validation_failure("endpoint_reference_mismatch")
            return endpoint
    raise _validation_failure("endpoint_descriptor_not_found")


def _receipt_profile(
    request: ModelRequest,
    snapshot: ModelRoutingSnapshot,
    policy: ModelRoutePolicy,
) -> ReasoningProfile:
    for ref in policy.candidate_endpoints:
        endpoint = _endpoint_descriptor(snapshot, ref)
        for profile in endpoint.reasoning_profiles:
            if profile.profile_id == request.reasoning_profile_id:
                return profile
    raise _validation_failure("reasoning_profile_not_found")


def _attempt_endpoint(
    candidates: tuple[EndpointRouteCandidatePlan, ...],
    attempt: RouteAttempt,
) -> ModelEndpointRef:
    for candidate in candidates:
        endpoint = candidate.endpoint
        if (
            endpoint.provider_id == attempt.provider_id
            and endpoint.endpoint_id == attempt.endpoint_id
        ):
            return endpoint
    raise _validation_failure("attempt_endpoint_not_in_plan")


def _endpoint_key(ref: ModelEndpointRef) -> tuple[str, str]:
    return ref.provider_id, ref.endpoint_id


def _structured_supports(
    actual: StructuredOutputSupport,
    required: StructuredOutputSupport,
) -> bool:
    allowed = {
        StructuredOutputSupport.NONE: {
            StructuredOutputSupport.NONE,
            StructuredOutputSupport.JSON_OBJECT,
            StructuredOutputSupport.JSON_SCHEMA,
        },
        StructuredOutputSupport.JSON_OBJECT: {
            StructuredOutputSupport.JSON_OBJECT,
            StructuredOutputSupport.JSON_SCHEMA,
        },
        StructuredOutputSupport.JSON_SCHEMA: {StructuredOutputSupport.JSON_SCHEMA},
    }
    return actual in allowed[required]


def _revision_mapping(
    values: Mapping[ModelRole, ComponentRevision],
    *,
    allow_empty: bool = False,
) -> dict[ModelRole, ComponentRevision]:
    result = dict(values)
    if (not result and not allow_empty) or any(
        not isinstance(role, ModelRole) or not isinstance(revision, ComponentRevision)
        for role, revision in result.items()
    ):
        raise ValueError("invalid prompt revision mapping")
    return result


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))
