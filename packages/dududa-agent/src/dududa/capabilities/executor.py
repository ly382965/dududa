from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.contracts.canonical import canonical_digest
from dududa.domain.capability import CapabilityDefinition, Idempotency
from dududa.domain.primitives import (
    ActionId,
    ComponentRevision,
    PrivacyLevel,
    ResourceRef,
    ResourceUsage,
    RiskLevel,
    Sensitivity,
)
from dududa.errors import DududaError, ErrorCategory, ErrorInfo, error, validation_error
from dududa.ports.capabilities import (
    CapabilityHealthRegistry,
    CapabilityProvider,
    CapabilityProviderRegistry,
    CapabilityRegistry,
    CapabilitySchemaValidator,
    ToolInvocationLedger,
    ToolPlanValidator,
)
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.security.digests import (
    actor_digest,
    audit_event_digest,
    authorization_decision_digest,
    budget_reservation_request_digest,
    interaction_limit_request_digest,
    resource_digest,
    scope_digest,
    usage_digest,
)
from dududa.security.models import (
    AuditEvent,
    AuditReceipt,
    AuthorizationDecision,
    AuthorizationRequest,
    BudgetDisposition,
    BudgetLease,
    BudgetReceipt,
    BudgetReservationRequest,
    InteractionLease,
    InteractionLeaseReceipt,
    InteractionLimitRequest,
    LeaseDisposition,
)
from dududa.security.ports import (
    AuditSink,
    AuthorizationDecisionVerifier,
    AuthorizationPolicy,
    BudgetLedger,
    InteractionLimiter,
)

from .authorization import (
    CapabilityAuthorizationPurpose,
    build_capability_authorization_request,
    capability_authorization_allows,
    capability_authorization_resource,
)
from .contracts import (
    CapabilityCatalogSnapshot,
    CapabilityHealthSnapshot,
    CapabilityHealthStatus,
    CapabilityProviderKind,
    CapabilityResult,
    McpCapabilityMapping,
    ProviderInvocation,
    ToolError,
    ToolExecutionRequest,
    ToolExecutionStatus,
    ToolInvocationClaim,
    ToolInvocationClaimRequest,
    ToolInvocationDisposition,
    ToolInvocationReceipt,
    ToolObservation,
)
from .digests import (
    capability_result_digest,
    provider_invocation_digest,
    tool_idempotency_key,
    tool_invocation_claim_request_digest,
    tool_invocation_receipt_digest,
    tool_observation_digest,
)
from .mapping_policy import fixed_arguments_match

_PRIVACY_ORDER = {
    PrivacyLevel.PUBLIC: 0,
    PrivacyLevel.CONVERSATION: 1,
    PrivacyLevel.PERSONAL: 2,
    PrivacyLevel.SENSITIVE: 3,
    PrivacyLevel.RESTRICTED: 4,
}
_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


@dataclass(frozen=True, slots=True)
class _ExecutionFacts:
    catalog: CapabilityCatalogSnapshot
    definition: CapabilityDefinition
    mapping: McpCapabilityMapping | None
    provider: CapabilityProvider
    health: CapabilityHealthSnapshot
    authorizations: tuple[tuple[AuthorizationRequest, AuthorizationDecision], ...]
    invocation: ProviderInvocation
    reservation: ResourceUsage


class GovernedToolExecutor:
    """Deterministic authority boundary around one proposed tool attempt."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        provider_registry: CapabilityProviderRegistry,
        health_registry: CapabilityHealthRegistry,
        schema_validator: CapabilitySchemaValidator,
        plan_validator: ToolPlanValidator,
        authorization: AuthorizationPolicy,
        authorization_verifier: AuthorizationDecisionVerifier,
        limiter: InteractionLimiter,
        budget_ledger: BudgetLedger,
        audit_sink: AuditSink,
        invocation_ledger: ToolInvocationLedger,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        terminal_commit_grace: timedelta = timedelta(seconds=5),
    ) -> None:
        if terminal_commit_grace <= timedelta(0):
            raise ValueError("terminal_commit_grace must be positive")
        self._registry = registry
        self._providers = provider_registry
        self._health = health_registry
        self._schemas = schema_validator
        self._plan_validator = plan_validator
        self._authorization = authorization
        self._authorization_verifier = authorization_verifier
        self._limiter = limiter
        self._budget = budget_ledger
        self._audit = audit_sink
        self._ledger = invocation_ledger
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._terminal_commit_grace = terminal_commit_grace

    async def execute(
        self,
        request: ToolExecutionRequest,
        *,
        call: PortCallContext,
    ) -> ToolObservation:
        if not isinstance(request, ToolExecutionRequest):
            raise validation_error("invalid_tool_execution_request")
        now = self._now()
        _validate_active_call(call, now)
        try:
            facts = await self._preflight(request, call=call)
        except DududaError:
            raise
        except Exception:  # noqa: BLE001 - implementation details are hidden.
            raise error(
                "tool_execution_preflight_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None

        claim_request_values = {
            "schema_version": 1,
            "idempotency_key": request.idempotency_key,
            "execution_request_digest": request.request_digest,
            "attempt": request.attempt,
            "maximum_attempts": request.plan_validation_request.maximum_attempts,
            "expires_at": call.deadline,
        }
        claim_request = ToolInvocationClaimRequest(
            request_digest=tool_invocation_claim_request_digest(claim_request_values),
            **claim_request_values,
        )
        claim = await _bounded_await(
            self._ledger.acquire(claim_request, call=call),
            call=call,
            now=self._now(),
            code="tool_invocation_claim_unavailable",
        )
        self._validate_claim(claim_request, claim)
        if claim.disposition is ToolInvocationDisposition.CONFLICT:
            raise _conflict("tool_invocation_key_conflict")
        if claim.disposition is not ToolInvocationDisposition.ACQUIRED:
            receipt = await _bounded_await(
                self._ledger.wait(claim, call=call),
                call=call,
                now=self._now(),
                code="tool_invocation_wait_unavailable",
            )
            return self._duplicate_observation(claim, receipt)
        return await self._execute_owner(request, facts, claim, call=call)

    async def _preflight(
        self,
        request: ToolExecutionRequest,
        *,
        call: PortCallContext,
    ) -> _ExecutionFacts:
        expected_validation = self._plan_validator.validate(
            request.plan_validation_request
        )
        if expected_validation != request.plan_validation_result:
            raise validation_error("tool_execution_plan_evidence_untrusted")
        planned_catalog = self._registry.snapshot_by_id(
            request.catalog_snapshot_id,
            expected_digest=request.catalog_digest,
        )
        planned_definition = self._registry.get_definition(
            planned_catalog,
            request.capability_id,
        )
        self._validate_definition(request, planned_definition)
        planned_mapping = self._mapping(
            planned_catalog,
            request,
            planned_definition,
        )
        catalog = self._registry.acquire_snapshot()
        definition = self._registry.get_definition(catalog, request.capability_id)
        self._validate_definition(request, definition)
        mapping = self._mapping(catalog, request, definition)
        if definition != planned_definition or mapping != planned_mapping:
            raise validation_error("tool_execution_current_catalog_mismatch")
        input_schema = self._registry.get_schema(catalog, definition.input_schema)
        validated_arguments = self._schemas.validate(
            request.resolved_arguments,
            input_schema,
        )
        if not isinstance(validated_arguments, Mapping) or (
            validated_arguments != request.resolved_arguments
        ):
            raise validation_error("tool_execution_argument_schema_mismatch")
        expected_key = tool_idempotency_key(
            run_id=call.run_id,
            logical_operation_id=request.logical_operation_id,
            capability_id=request.capability_id,
            definition_digest=request.definition_digest,
            normalized_arguments=request.resolved_arguments,
        )
        if expected_key != request.idempotency_key:
            raise validation_error("tool_execution_idempotency_key_mismatch")
        reservation = _reservation(definition, request, call, now=self._now())
        provider = self._providers.resolve(catalog, request.provider)
        health = await _bounded_await(
            self._health.snapshot(catalog, call=call),
            call=call,
            now=self._now(),
            code="tool_execution_health_unavailable",
        )
        self._validate_health(definition, health, at=self._now())
        authorizations = await self._authorize(
            definition,
            catalog,
            request,
            call=call,
        )
        invocation_values = {
            "schema_version": 1,
            "invocation_id": request.invocation_id,
            "logical_operation_id": request.logical_operation_id,
            "capability_id": request.capability_id,
            "definition_digest": request.definition_digest,
            "provider": request.provider,
            "mapping_digest": request.mapping_digest,
            "arguments": request.resolved_arguments,
            "idempotency_key": request.idempotency_key,
            "attempt": request.attempt,
            "context": request.context,
            "authorizations": tuple(item[1] for item in authorizations),
        }
        invocation = ProviderInvocation(
            invocation_digest=provider_invocation_digest(invocation_values),
            **invocation_values,
        )
        return _ExecutionFacts(
            catalog,
            definition,
            mapping,
            provider,
            health,
            authorizations,
            invocation,
            reservation,
        )

    def _validate_definition(
        self,
        request: ToolExecutionRequest,
        definition: CapabilityDefinition,
    ) -> None:
        query = request.plan_validation_request.query
        if (
            definition.definition_digest != request.definition_digest
            or definition.provider != request.provider
            or not definition.enabled
            or request.context.conversation_scope.conversation_type
            not in definition.allowed_contexts
            or _PRIVACY_ORDER[request.context.data_classification]
            > _PRIVACY_ORDER[definition.privacy_level]
            or _RISK_ORDER[definition.risk_level]
            > _RISK_ORDER[query.maximum_risk_level]
            or bool(definition.side_effects & query.excluded_side_effects)
            or (
                query.required_output_schema is not None
                and definition.output_schema != query.required_output_schema
            )
        ):
            raise validation_error("tool_execution_definition_ineligible")
        if request.attempt > 1 and definition.idempotency is Idempotency.NON_IDEMPOTENT:
            raise validation_error("non_idempotent_tool_retry_forbidden")
        if request.attempt > request.plan_validation_request.maximum_attempts:
            raise validation_error("tool_execution_attempt_limit_exceeded")

    def _mapping(
        self,
        catalog: CapabilityCatalogSnapshot,
        request: ToolExecutionRequest,
        definition: CapabilityDefinition,
    ) -> McpCapabilityMapping | None:
        descriptor = next(
            (
                item
                for item in catalog.provider_descriptors
                if item.provider == definition.provider
            ),
            None,
        )
        if descriptor is None:
            raise validation_error("tool_execution_provider_not_in_catalog")
        mapping = self._registry.get_mcp_mapping(catalog, definition.capability_id)
        if descriptor.kind is CapabilityProviderKind.MCP:
            if (
                mapping is None
                or not mapping.enabled
                or mapping.capability_definition_digest != definition.definition_digest
                or mapping.mapping_digest != request.mapping_digest
                or not fixed_arguments_match(
                    request.resolved_arguments,
                    mapping.fixed_arguments,
                )
            ):
                raise validation_error("tool_execution_mapping_mismatch")
        elif mapping is not None or request.mapping_digest is not None:
            raise validation_error("unexpected_tool_execution_mapping")
        return mapping

    async def _authorize(
        self,
        definition: CapabilityDefinition,
        catalog: CapabilityCatalogSnapshot,
        request: ToolExecutionRequest,
        *,
        call: PortCallContext,
    ) -> tuple[tuple[AuthorizationRequest, AuthorizationDecision], ...]:
        if (
            request.plan_validation_request.retrieval.policy_revision
            != call.policy_snapshot_id
        ):
            raise _authorization_error("tool_execution_policy_revision_mismatch")
        evidence: list[tuple[AuthorizationRequest, AuthorizationDecision]] = []
        for permission in sorted(definition.required_permissions):
            authorization_request = build_capability_authorization_request(
                definition,
                request.context.actor,
                request.context.conversation_scope,
                catalog,
                permission=permission,
                purpose=CapabilityAuthorizationPurpose.EXECUTION,
                policy_snapshot_id=call.policy_snapshot_id,
            )
            try:
                decision = await _bounded_await(
                    self._authorization.decide(authorization_request, call=call),
                    call=call,
                    now=self._now(),
                    code="tool_execution_authorization_unavailable",
                )
            except DududaError as exc:
                if exc.info.category in {
                    ErrorCategory.CANCELLED,
                    ErrorCategory.TIMEOUT,
                }:
                    raise
                raise _authorization_error(
                    "tool_execution_authorization_denied"
                ) from None
            except Exception:  # noqa: BLE001 - authorization failures always deny.
                raise _authorization_error(
                    "tool_execution_authorization_denied"
                ) from None
            now = self._now()
            if not capability_authorization_allows(
                authorization_request,
                decision,
                self._authorization_verifier,
                at=now,
                expected_policy_revision=call.policy_snapshot_id,
            ):
                raise _authorization_error("tool_execution_authorization_denied")
            evidence.append((authorization_request, decision))
        self._validate_authorizations(tuple(evidence), call=call, at=self._now())
        return tuple(evidence)

    async def _execute_owner(
        self,
        request: ToolExecutionRequest,
        facts: _ExecutionFacts,
        claim: ToolInvocationClaim,
        *,
        call: PortCallContext,
    ) -> ToolObservation:
        limiter_lease: InteractionLease | None = None
        budget_lease: BudgetLease | None = None
        audit_started = False
        dispatched = False
        native_cancellation: asyncio.CancelledError | None = None
        started_at = self._now()
        observation: ToolObservation
        try:
            interaction_request = _interaction_request(request)
            candidate_limiter_lease = await _bounded_await(
                self._limiter.reserve(
                    interaction_request,
                    call=call,
                ),
                call=call,
                now=self._now(),
                code="tool_execution_limiter_unavailable",
            )
            _validate_interaction_lease(
                interaction_request,
                candidate_limiter_lease,
                at=self._now(),
            )
            limiter_lease = candidate_limiter_lease
            if not limiter_lease.allowed:
                raise _gate_error("tool_execution_interaction_denied")
            budget_request = _budget_request(
                request,
                facts.reservation,
                run_id=call.run_id,
            )
            candidate_budget_lease = await _bounded_await(
                self._budget.reserve(
                    budget_request,
                    call=call,
                ),
                call=call,
                now=self._now(),
                code="tool_execution_budget_unavailable",
            )
            _validate_budget_lease(
                budget_request,
                candidate_budget_lease,
                at=self._now(),
            )
            budget_lease = candidate_budget_lease
            await self._write_audit(
                request,
                facts,
                call=call,
                phase="start",
                observation=None,
            )
            audit_started = True
            self._validate_dispatch_gate(
                request,
                facts,
                limiter_lease,
                budget_lease,
                call=call,
            )
            dispatched = True
            try:
                result = await _bounded_await(
                    facts.provider.invoke(facts.invocation, call=call),
                    call=call,
                    now=self._now(),
                    code="tool_provider_invoke_unavailable",
                )
                observation = self._result_observation(
                    request,
                    facts,
                    result,
                    started_at=started_at,
                )
            except asyncio.CancelledError as exc:
                native_cancellation = exc
                observation = self._internal_observation(
                    request,
                    facts,
                    ToolExecutionStatus.UNKNOWN,
                    "tool_provider_cancelled_after_dispatch",
                    started_at=started_at,
                )
            except Exception:  # noqa: BLE001 - dispatch exceptions have unknown outcome.
                observation = self._internal_observation(
                    request,
                    facts,
                    ToolExecutionStatus.UNKNOWN,
                    "tool_provider_outcome_unknown",
                    started_at=started_at,
                )
        except asyncio.CancelledError as exc:
            native_cancellation = exc
            observation = self._internal_observation(
                request,
                facts,
                (
                    ToolExecutionStatus.UNKNOWN
                    if dispatched
                    else ToolExecutionStatus.FAILED
                ),
                (
                    "tool_execution_cancelled_after_dispatch"
                    if dispatched
                    else "tool_execution_cancelled_before_dispatch"
                ),
                started_at=started_at,
            )
        except Exception:  # noqa: BLE001 - raw prerequisite failures are sanitized.
            observation = self._internal_observation(
                request,
                facts,
                (
                    ToolExecutionStatus.UNKNOWN
                    if dispatched
                    else ToolExecutionStatus.FAILED
                ),
                (
                    "tool_execution_failed_after_dispatch"
                    if dispatched
                    else "tool_execution_failed_before_dispatch"
                ),
                started_at=started_at,
            )

        terminal_call = self._terminal_call(call)
        finalization = asyncio.create_task(
            self._finalize(
                request,
                facts,
                claim,
                observation,
                limiter_lease=limiter_lease,
                budget_lease=budget_lease,
                audit_started=audit_started,
                dispatched=dispatched,
                call=terminal_call,
                started_at=started_at,
            )
        )
        while not finalization.done():
            try:
                await asyncio.shield(finalization)
            except asyncio.CancelledError as exc:
                if native_cancellation is None:
                    native_cancellation = exc
                continue
        final = finalization.result()
        if native_cancellation is not None:
            raise native_cancellation
        return final

    async def _finalize(
        self,
        request: ToolExecutionRequest,
        facts: _ExecutionFacts,
        claim: ToolInvocationClaim,
        observation: ToolObservation,
        *,
        limiter_lease: InteractionLease | None,
        budget_lease: BudgetLease | None,
        audit_started: bool,
        dispatched: bool,
        call: PortCallContext,
        started_at: datetime,
    ) -> ToolObservation:
        if dispatched:
            if (
                limiter_lease is None
                or budget_lease is None
                or not await self._settle_limiter(
                    limiter_lease,
                    commit=True,
                    call=call,
                )
            ):
                observation = self._internal_observation(
                    request,
                    facts,
                    ToolExecutionStatus.UNKNOWN,
                    "tool_execution_limiter_state_unknown",
                    started_at=started_at,
                )
            if budget_lease is not None:
                usage = (
                    facts.reservation
                    if observation.status is ToolExecutionStatus.UNKNOWN
                    else observation.usage
                )
                if not await self._settle_budget(budget_lease, usage, call=call):
                    observation = self._internal_observation(
                        request,
                        facts,
                        ToolExecutionStatus.UNKNOWN,
                        "tool_execution_budget_settlement_unknown",
                        started_at=started_at,
                    )
                    if usage != facts.reservation:
                        await self._settle_budget(
                            budget_lease,
                            facts.reservation,
                            call=call,
                        )
        else:
            if budget_lease is not None and not await self._release_budget(
                budget_lease,
                call=call,
            ):
                observation = self._internal_observation(
                    request,
                    facts,
                    ToolExecutionStatus.FAILED,
                    "tool_execution_budget_release_failed",
                    started_at=started_at,
                )
            if limiter_lease is not None and not await self._settle_limiter(
                limiter_lease,
                commit=False,
                call=call,
            ):
                observation = self._internal_observation(
                    request,
                    facts,
                    ToolExecutionStatus.FAILED,
                    "tool_execution_limiter_release_failed",
                    started_at=started_at,
                )
        if audit_started:
            try:
                await self._write_audit(
                    request,
                    facts,
                    call=call,
                    phase="finish",
                    observation=observation,
                )
            except Exception:  # noqa: BLE001 - unaudited success is never accepted.
                if dispatched:
                    observation = self._internal_observation(
                        request,
                        facts,
                        ToolExecutionStatus.UNKNOWN,
                        "tool_execution_audit_finish_unknown",
                        started_at=started_at,
                    )
        try:
            receipt = await _bounded_await(
                self._ledger.complete(claim, observation, call=call),
                call=call,
                now=self._now(),
                code="tool_invocation_terminalization_unavailable",
            )
        except Exception:  # noqa: BLE001 - no receipt means no acceptable fact.
            return self._internal_observation(
                request,
                facts,
                (
                    ToolExecutionStatus.UNKNOWN
                    if dispatched
                    else ToolExecutionStatus.FAILED
                ),
                "tool_invocation_terminalization_failed",
                started_at=started_at,
            )
        if (
            not isinstance(receipt, ToolInvocationReceipt)
            or tool_invocation_receipt_digest(receipt) != receipt.receipt_digest
            or receipt.observation != observation
            or receipt.idempotency_key != request.idempotency_key
            or receipt.execution_request_digest != request.request_digest
        ):
            return self._internal_observation(
                request,
                facts,
                (
                    ToolExecutionStatus.UNKNOWN
                    if dispatched
                    else ToolExecutionStatus.FAILED
                ),
                "tool_invocation_terminal_receipt_invalid",
                started_at=started_at,
            )
        return observation

    def _result_observation(
        self,
        request: ToolExecutionRequest,
        facts: _ExecutionFacts,
        result: CapabilityResult,
        *,
        started_at: datetime,
    ) -> ToolObservation:
        now = self._now()
        if (
            not isinstance(result, CapabilityResult)
            or capability_result_digest(result) != result.result_digest
            or result.provider_invocation_digest != facts.invocation.invocation_digest
            or result.invocation_id != request.invocation_id
            or result.capability_id != request.capability_id
            or result.definition_digest != request.definition_digest
            or result.provider != request.provider
            or result.observed_at > now
            or _PRIVACY_ORDER[result.sensitivity]
            > _PRIVACY_ORDER[facts.definition.privacy_level]
        ):
            raise validation_error("invalid_capability_provider_result")
        usage = _result_usage(result, facts.reservation, request.attempt)
        error_value = None
        if result.status is not ToolExecutionStatus.SUCCEEDED:
            error_value = _tool_error(
                "capability_provider_failed"
                if result.status is ToolExecutionStatus.FAILED
                else "capability_provider_outcome_unknown",
                status=result.status,
                retryable=bool(
                    result.status is ToolExecutionStatus.FAILED
                    and result.error is not None
                    and result.error.info.retryable
                ),
            )
        return _observation(
            request,
            facts.invocation,
            provider_result_digest=result.result_digest,
            status=result.status,
            data=result.data,
            error_value=error_value,
            source_refs=result.source_refs,
            observed_at=result.observed_at,
            latency_ms=_latency_ms(started_at, now),
            sensitivity=result.sensitivity,
            usage=usage,
            truncated=result.truncated,
        )

    def _internal_observation(
        self,
        request: ToolExecutionRequest,
        facts: _ExecutionFacts,
        status: ToolExecutionStatus,
        reason: str,
        *,
        started_at: datetime,
    ) -> ToolObservation:
        now = self._now()
        usage = (
            facts.reservation
            if status is ToolExecutionStatus.UNKNOWN
            else _known_failure_usage(facts.reservation, request.attempt)
        )
        result_digest = canonical_digest(
            {
                "execution_request_digest": request.request_digest,
                "provider_invocation_digest": facts.invocation.invocation_digest,
                "status": status,
                "reason": reason,
            },
            domain="capability.internal-provider-result:v1",
        )
        return _observation(
            request,
            facts.invocation,
            provider_result_digest=result_digest,
            status=status,
            data=None,
            error_value=_tool_error(reason, status=status, retryable=False),
            source_refs=(),
            observed_at=now,
            latency_ms=_latency_ms(started_at, now),
            sensitivity=request.context.data_classification,
            usage=usage,
            truncated=False,
        )

    def _validate_health(
        self,
        definition: CapabilityDefinition,
        snapshot: CapabilityHealthSnapshot,
        *,
        at: datetime,
    ) -> None:
        if (
            not isinstance(snapshot, CapabilityHealthSnapshot)
            or snapshot.observed_at > at
            or snapshot.expires_at <= at
        ):
            raise _gate_error("tool_execution_health_stale")
        provider = next(
            (
                item
                for item in snapshot.providers
                if item.provider == definition.provider
            ),
            None,
        )
        endpoint = (
            next(
                (
                    item
                    for item in provider.capabilities
                    if item.capability_id == definition.capability_id
                ),
                None,
            )
            if provider is not None
            else None
        )
        if (
            provider is None
            or provider.status is not CapabilityHealthStatus.HEALTHY
            or provider.observed_at > at
            or provider.expires_at <= at
            or endpoint is None
            or endpoint.status is not CapabilityHealthStatus.HEALTHY
            or endpoint.definition_digest != definition.definition_digest
        ):
            raise _gate_error("tool_execution_provider_not_healthy")

    def _validate_authorizations(
        self,
        evidence: tuple[tuple[AuthorizationRequest, AuthorizationDecision], ...],
        *,
        call: PortCallContext,
        at: datetime,
    ) -> None:
        if not evidence or any(
            not capability_authorization_allows(
                request,
                decision,
                self._authorization_verifier,
                at=at,
                expected_policy_revision=call.policy_snapshot_id,
            )
            for request, decision in evidence
        ):
            raise _authorization_error("tool_execution_authorization_expired")

    def _validate_dispatch_gate(
        self,
        request: ToolExecutionRequest,
        facts: _ExecutionFacts,
        limiter_lease: InteractionLease,
        budget_lease: BudgetLease,
        *,
        call: PortCallContext,
    ) -> None:
        now = self._now()
        _validate_active_call(call, now)
        _validate_interaction_lease(
            _interaction_request(request),
            limiter_lease,
            at=now,
        )
        _validate_budget_lease(
            _budget_request(request, facts.reservation, run_id=call.run_id),
            budget_lease,
            at=now,
        )
        catalog = self._registry.acquire_snapshot()
        if (
            catalog != facts.catalog
            or self._registry.get_definition(catalog, request.capability_id)
            != facts.definition
            or self._registry.get_mcp_mapping(catalog, request.capability_id)
            != facts.mapping
            or self._providers.resolve(catalog, request.provider) is not facts.provider
        ):
            raise _gate_error("tool_execution_catalog_evidence_drifted")
        self._validate_health(facts.definition, facts.health, at=now)
        self._validate_authorizations(facts.authorizations, call=call, at=now)
        if (
            not limiter_lease.allowed
            or limiter_lease.expires_at <= now
            or budget_lease.expires_at <= now
            or budget_lease.reserved != facts.reservation
            or request.plan_validation_result
            != self._plan_validator.validate(request.plan_validation_request)
        ):
            raise _gate_error("tool_execution_dispatch_evidence_stale")

    async def _write_audit(
        self,
        request: ToolExecutionRequest,
        facts: _ExecutionFacts,
        *,
        call: PortCallContext,
        phase: str,
        observation: ToolObservation | None,
    ) -> None:
        status = observation.status if observation is not None else None
        event_id = self._new_id("tool-audit")
        values = {
            "schema_version": 1,
            "event_id": event_id,
            "event_digest": canonical_digest({}, domain="pending:v1"),
            "timestamp": self._now(),
            "run_id": call.run_id,
            "operation_id": request.logical_operation_id,
            "trace_id": call.trace.trace_id,
            "span_id": call.trace.parent_span_id,
            "actor_digest": actor_digest(request.context.actor),
            "scope_digest": scope_digest(request.context.conversation_scope),
            "action": ActionId("capability.invoke"),
            "decision": "allow",
            "authorization_decision_id": None,
            "request_digest": request.request_digest,
            "policy_revisions": tuple(
                sorted({item[1].policy_revision for item in facts.authorizations})
            ),
            "component_revisions": (facts.definition.provider.revision,),
            "reason_codes": (f"tool_execution_{phase}",),
            "resource_digest": resource_digest(
                capability_authorization_resource(
                    facts.definition,
                    request.context.conversation_scope,
                )
            ),
            "sanitized_detail": {
                "phase": phase,
                "capability_id": request.capability_id,
                "definition_digest": str(request.definition_digest),
                "execution_request_digest": str(request.request_digest),
                "provider_invocation_digest": str(facts.invocation.invocation_digest),
                "observation_digest": (
                    str(observation.observation_digest)
                    if observation is not None
                    else None
                ),
                "usage_digest": (
                    str(usage_digest(observation.usage))
                    if observation is not None
                    else None
                ),
                "decision_count": len(facts.authorizations),
                "decision_digests": tuple(
                    str(authorization_decision_digest(item[1]))
                    for item in facts.authorizations
                ),
                "status": status.value if status is not None else "pending",
            },
            "sensitivity": _sensitivity(request.context.data_classification),
            "outcome": (
                f"candidate_{status.value}" if status is not None else "pending"
            ),
        }
        event = AuditEvent(**values)
        event = replace(event, event_digest=audit_event_digest(event))
        receipt = await _bounded_await(
            self._audit.write(event, call=call),
            call=call,
            now=self._now(),
            code="tool_execution_audit_unavailable",
        )
        if (
            not isinstance(receipt, AuditReceipt)
            or receipt.schema_version != 1
            or not receipt.persisted
            or receipt.event_id != event.event_id
            or receipt.event_digest != event.event_digest
            or not isinstance(receipt.sink_revision, str)
            or not receipt.sink_revision.strip()
        ):
            raise _gate_error("tool_execution_audit_rejected")

    async def _settle_limiter(
        self,
        lease: InteractionLease,
        *,
        commit: bool,
        call: PortCallContext,
    ) -> bool:
        try:
            receipt = await _bounded_await(
                (
                    self._limiter.commit(lease, call=call)
                    if commit
                    else self._limiter.release(lease, call=call)
                ),
                call=call,
                now=self._now(),
                code="tool_execution_limiter_finalization_unavailable",
            )
        except Exception:  # noqa: BLE001 - finalization remains best effort.
            return False
        return _valid_interaction_receipt(
            lease,
            receipt,
            commit=commit,
            at=self._now(),
        )

    async def _settle_budget(
        self,
        lease: BudgetLease,
        usage: ResourceUsage,
        *,
        call: PortCallContext,
    ) -> bool:
        try:
            receipt = await _bounded_await(
                self._budget.settle(lease, usage, call=call),
                call=call,
                now=self._now(),
                code="tool_execution_budget_settlement_unavailable",
            )
        except Exception:  # noqa: BLE001 - finalization remains best effort.
            return False
        return _valid_budget_receipt(
            lease,
            receipt,
            expected_usage=usage,
            release=False,
            at=self._now(),
        )

    async def _release_budget(
        self,
        lease: BudgetLease,
        *,
        call: PortCallContext,
    ) -> bool:
        try:
            receipt = await _bounded_await(
                self._budget.release(lease, call=call),
                call=call,
                now=self._now(),
                code="tool_execution_budget_release_unavailable",
            )
        except Exception:  # noqa: BLE001 - finalization remains best effort.
            return False
        return _valid_budget_receipt(
            lease,
            receipt,
            expected_usage=_zero_usage(lease.reserved),
            release=True,
            at=self._now(),
        )

    def _validate_claim(
        self,
        request: ToolInvocationClaimRequest,
        claim: ToolInvocationClaim,
    ) -> None:
        if (
            not isinstance(claim, ToolInvocationClaim)
            or claim.claim_request_digest != request.request_digest
            or claim.idempotency_key != request.idempotency_key
            or claim.execution_request_digest != request.execution_request_digest
            or claim.attempt != request.attempt
            or claim.maximum_attempts != request.maximum_attempts
            or claim.expires_at != request.expires_at
        ):
            raise _conflict("tool_invocation_claim_binding_invalid")

    def _duplicate_observation(
        self,
        claim: ToolInvocationClaim,
        receipt: ToolInvocationReceipt | None,
    ) -> ToolObservation:
        if (
            not isinstance(receipt, ToolInvocationReceipt)
            or tool_invocation_receipt_digest(receipt) != receipt.receipt_digest
            or receipt.idempotency_key != claim.idempotency_key
            or (
                claim.terminal_receipt_digest is not None
                and receipt.receipt_digest != claim.terminal_receipt_digest
            )
        ):
            raise _conflict("tool_invocation_duplicate_receipt_invalid")
        return receipt.observation

    def _terminal_call(self, call: PortCallContext) -> PortCallContext:
        return PortCallContext(
            run_id=call.run_id,
            trace=call.trace,
            deadline=self._now() + self._terminal_commit_grace,
            cancellation=NeverCancelled(),
            budget=call.budget,
            policy_snapshot_id=call.policy_snapshot_id,
        )

    def _new_id(self, prefix: str) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - callback details are hidden.
            raise error(
                "tool_executor_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise validation_error("invalid_tool_executor_id")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - callback details are hidden.
            raise error(
                "tool_executor_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_tool_executor_clock")
        return value


def _validate_interaction_lease(
    request: InteractionLimitRequest,
    lease: object,
    *,
    at: datetime,
) -> None:
    if (
        interaction_limit_request_digest(request) != request.request_digest
        or not isinstance(lease, InteractionLease)
        or lease.schema_version != 1
        or type(lease.allowed) is not bool
        or lease.request_digest != request.request_digest
        or lease.actor_digest != actor_digest(request.actor)
        or lease.scope_digest != scope_digest(request.conversation_scope)
        or lease.action != request.action
        or lease.units != request.units
        or lease.idempotency_key != request.idempotency_key
        or not isinstance(lease.policy_revision, str)
        or not lease.policy_revision.strip()
        or not _within_lease(lease.reserved_at, lease.expires_at, at)
    ):
        raise _gate_error("tool_execution_interaction_lease_invalid")


def _validate_budget_lease(
    request: BudgetReservationRequest,
    lease: object,
    *,
    at: datetime,
) -> None:
    if (
        budget_reservation_request_digest(request) != request.request_digest
        or not isinstance(lease, BudgetLease)
        or lease.schema_version != 1
        or lease.request_digest != request.request_digest
        or lease.resource_digest != resource_digest(request.resource)
        or lease.idempotency_key != request.idempotency_key
        or lease.reserved != request.maximum
        or not isinstance(lease.policy_revision, str)
        or not lease.policy_revision.strip()
        or not _within_lease(lease.reserved_at, lease.expires_at, at)
    ):
        raise _gate_error("tool_execution_budget_lease_invalid")


def _valid_interaction_receipt(
    lease: InteractionLease,
    receipt: object,
    *,
    commit: bool,
    at: datetime,
) -> bool:
    dispositions = (
        {LeaseDisposition.COMMITTED, LeaseDisposition.ALREADY_COMMITTED}
        if commit
        else {LeaseDisposition.RELEASED, LeaseDisposition.ALREADY_RELEASED}
    )
    return bool(
        isinstance(receipt, InteractionLeaseReceipt)
        and receipt.schema_version == 1
        and receipt.lease_id == lease.lease_id
        and receipt.idempotency_key == lease.idempotency_key
        and receipt.disposition in dispositions
        and isinstance(receipt.limiter_revision, ComponentRevision)
        and receipt.limiter_revision.config_revision == lease.policy_revision
        and _recorded_after(lease.reserved_at, receipt.recorded_at, at)
    )


def _valid_budget_receipt(
    lease: BudgetLease,
    receipt: object,
    *,
    expected_usage: ResourceUsage,
    release: bool,
    at: datetime,
) -> bool:
    dispositions = (
        {BudgetDisposition.RELEASED, BudgetDisposition.DUPLICATE}
        if release
        else {BudgetDisposition.SETTLED, BudgetDisposition.DUPLICATE}
    )
    return bool(
        isinstance(receipt, BudgetReceipt)
        and receipt.schema_version == 1
        and receipt.lease_id == lease.lease_id
        and receipt.request_digest == lease.request_digest
        and receipt.idempotency_key == lease.idempotency_key
        and receipt.disposition in dispositions
        and receipt.charged == expected_usage
        and receipt.usage_digest == usage_digest(expected_usage)
        and isinstance(receipt.remaining, ResourceUsage)
        and _recorded_after(lease.reserved_at, receipt.recorded_at, at)
    )


def _within_lease(reserved_at: datetime, expires_at: datetime, at: datetime) -> bool:
    return bool(
        _aware(reserved_at) and _aware(expires_at) and reserved_at <= at < expires_at
    )


def _recorded_after(reserved_at: datetime, recorded_at: datetime, at: datetime) -> bool:
    return bool(
        _aware(reserved_at) and _aware(recorded_at) and reserved_at <= recorded_at <= at
    )


def _aware(value: object) -> bool:
    return bool(
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _interaction_request(request: ToolExecutionRequest) -> InteractionLimitRequest:
    values = {
        "schema_version": 1,
        "actor": request.context.actor,
        "conversation_scope": request.context.conversation_scope,
        "action": ActionId("capability.invoke"),
        "units": 1,
        "idempotency_key": f"{request.idempotency_key}:attempt:{request.attempt}:limit",
    }
    pending = InteractionLimitRequest(
        request_digest=canonical_digest({}, domain="pending:v1"),
        **values,
    )
    return replace(
        pending,
        request_digest=interaction_limit_request_digest(pending),
    )


def _budget_request(
    request: ToolExecutionRequest,
    reservation: ResourceUsage,
    *,
    run_id: str,
) -> BudgetReservationRequest:
    resource = ResourceRef(
        "runtime",
        run_id,
        scope_digest(request.context.conversation_scope),
    )
    values = {
        "schema_version": 1,
        "resource": resource,
        "maximum": reservation,
        "idempotency_key": f"{request.idempotency_key}:attempt:{request.attempt}:budget",
    }
    pending = BudgetReservationRequest(
        request_digest=canonical_digest({}, domain="pending:v1"),
        **values,
    )
    return replace(
        pending,
        request_digest=budget_reservation_request_digest(pending),
    )


def _reservation(
    definition: CapabilityDefinition,
    request: ToolExecutionRequest,
    call: PortCallContext,
    *,
    now: datetime,
) -> ResourceUsage:
    remaining_ms = max(0, int((call.deadline - now).total_seconds() * 1000))
    required_retry = 1 if request.attempt > 1 else 0
    cost = (
        None
        if call.budget.cost_units_remaining is None
        else Decimal(definition.cost_hint.units)
    )
    if (
        call.budget.tool_steps_remaining < 1
        or call.budget.retries_remaining < required_retry
        or (
            cost is not None and cost > (call.budget.cost_units_remaining or Decimal(0))
        )
        or definition.latency_hint.maximum_ms > remaining_ms
    ):
        raise _gate_error("tool_execution_budget_or_deadline_exhausted")
    return ResourceUsage(
        1,
        tool_steps=1,
        retries=required_retry,
        cost_units=cost,
    )


def _result_usage(
    result: CapabilityResult,
    reservation: ResourceUsage,
    attempt: int,
) -> ResourceUsage:
    actual_cost = result.usage.cost_units
    if reservation.cost_units is None:
        actual_cost = None
    elif actual_cost is None:
        actual_cost = reservation.cost_units
    if (
        result.usage.model_calls != 0
        or result.usage.input_tokens != 0
        or result.usage.output_tokens != 0
        or result.usage.tool_steps > 1
        or result.usage.retries > (1 if attempt > 1 else 0)
        or (
            actual_cost is not None
            and reservation.cost_units is not None
            and actual_cost > reservation.cost_units
        )
    ):
        raise validation_error("capability_provider_usage_exceeds_reservation")
    return ResourceUsage(
        1,
        tool_steps=1,
        retries=1 if attempt > 1 else 0,
        cost_units=actual_cost,
    )


def _known_failure_usage(reservation: ResourceUsage, attempt: int) -> ResourceUsage:
    return ResourceUsage(
        1,
        tool_steps=1,
        retries=1 if attempt > 1 else 0,
        cost_units=(Decimal(0) if reservation.cost_units is not None else None),
    )


def _zero_usage(reservation: ResourceUsage) -> ResourceUsage:
    return ResourceUsage(
        1,
        cost_units=(Decimal(0) if reservation.cost_units is not None else None),
    )


def _observation(
    request: ToolExecutionRequest,
    invocation: ProviderInvocation,
    *,
    provider_result_digest,
    status: ToolExecutionStatus,
    data,
    error_value: ToolError | None,
    source_refs: tuple[str, ...],
    observed_at: datetime,
    latency_ms: int,
    sensitivity: PrivacyLevel,
    usage: ResourceUsage,
    truncated: bool,
) -> ToolObservation:
    values = {
        "schema_version": 1,
        "execution_request_digest": request.request_digest,
        "provider_invocation_digest": invocation.invocation_digest,
        "provider_result_digest": provider_result_digest,
        "invocation_id": request.invocation_id,
        "plan_id": request.plan_id,
        "plan_digest": request.plan_digest,
        "step_id": request.step_id,
        "logical_operation_id": request.logical_operation_id,
        "capability_id": request.capability_id,
        "definition_digest": request.definition_digest,
        "catalog_snapshot_id": request.catalog_snapshot_id,
        "catalog_digest": request.catalog_digest,
        "provider": request.provider,
        "mapping_digest": request.mapping_digest,
        "policy_revision": request.plan_validation_request.retrieval.policy_revision,
        "idempotency_key": request.idempotency_key,
        "attempt": request.attempt,
        "status": status,
        "data": data,
        "error": error_value,
        "source_refs": source_refs,
        "observed_at": observed_at,
        "latency_ms": latency_ms,
        "cache_status": None,
        "sensitivity": sensitivity,
        "usage": usage,
        "truncated": truncated,
        "untrusted": True,
    }
    return ToolObservation(
        observation_digest=tool_observation_digest(values),
        **values,
    )


def _tool_error(
    code: str,
    *,
    status: ToolExecutionStatus,
    retryable: bool,
) -> ToolError:
    unknown = status is ToolExecutionStatus.UNKNOWN
    return ToolError(
        1,
        ErrorInfo(
            1,
            code,
            ErrorCategory.EXTERNAL,
            retryable=retryable and not unknown,
            outcome_unknown=unknown,
            public_message_key="service.unavailable",
            reason_codes=("governed_tool_failure",),
        ),
        None,
        {},
    )


def _latency_ms(started_at: datetime, completed_at: datetime) -> int:
    return min(
        3_600_000,
        max(0, int((completed_at - started_at).total_seconds() * 1_000)),
    )


def _sensitivity(level: PrivacyLevel) -> Sensitivity:
    return {
        PrivacyLevel.PUBLIC: Sensitivity.PUBLIC,
        PrivacyLevel.CONVERSATION: Sensitivity.PERSONAL,
        PrivacyLevel.PERSONAL: Sensitivity.PERSONAL,
        PrivacyLevel.SENSITIVE: Sensitivity.SENSITIVE,
        PrivacyLevel.RESTRICTED: Sensitivity.RESTRICTED,
    }[level]


def _validate_active_call(call: PortCallContext, now: datetime) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_tool_executor_call")
    try:
        cancelled = call.cancellation.is_cancelled
    except Exception:  # noqa: BLE001 - cancellation details are hidden.
        raise error(
            "tool_executor_cancellation_unavailable",
            ErrorCategory.INTERNAL,
            "service.unavailable",
        ) from None
    if cancelled:
        raise error(
            "tool_execution_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "tool_execution_deadline_exceeded",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


async def _bounded_await(
    awaitable: Awaitable[object],
    *,
    call: PortCallContext,
    now: datetime,
    code: str,
):
    _validate_active_call(call, now)
    remaining = (call.deadline - now).total_seconds()
    task = asyncio.create_task(awaitable)
    cancelled = asyncio.create_task(call.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (task, cancelled),
            timeout=max(0.0, remaining),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled in done:
            await _cancel_task(task)
            raise error(
                f"{code}_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
                outcome_unknown="provider_invoke" in code,
            )
        if task not in done:
            await _cancel_task(task)
            raise error(
                f"{code}_timeout",
                ErrorCategory.TIMEOUT,
                "request.timeout",
                outcome_unknown="provider_invoke" in code,
            )
        return task.result()
    finally:
        await _cancel_task(task)
        await _cancel_task(cancelled)


async def _cancel_task(task: asyncio.Task[object]) -> None:
    cleanup = asyncio.create_task(_bounded_cancel_task(task))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
    cleanup.result()


async def _bounded_cancel_task(task: asyncio.Task[object]) -> None:
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
    except BaseException:  # noqa: BLE001 - detached task outcome is intentionally consumed.
        return


def _gate_error(code: str):
    return error(code, ErrorCategory.CONFLICT, "request.conflict")


def _authorization_error(code: str):
    return error(code, ErrorCategory.AUTHORIZATION, "security.denied")


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "request.conflict")


__all__ = ["GovernedToolExecutor"]
