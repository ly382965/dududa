from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.domain.primitives import ResourceUsage, RuntimeBudget
from dududa.errors import DududaError, ErrorCategory, error, validation_error
from dududa.ports.capabilities import (
    ArgumentBinder,
    CapabilityRegistry,
    CapabilityRetriever,
    ToolExecutor,
    ToolPlanner,
    ToolPlanValidator,
    ToolResultValidator,
)
from dududa.ports.context import PortCallContext

from .contracts import (
    ArgumentBindingRequest,
    CapabilityExecutionContext,
    CapabilityRetrievalRequest,
    CapabilityRetrievalResult,
    CapabilityRunReceipt,
    CapabilityRunRequest,
    CapabilityRunStatus,
    ToolExecutionRequest,
    ToolObservation,
    ToolPlan,
    ToolPlanningRequest,
    ToolPlanValidationRequest,
    ToolPlanValidationResult,
    ToolValidationRequest,
    ToolValidationResult,
    UnobservedToolAttempt,
    ValidationAction,
)
from .digests import (
    argument_binding_request_digest,
    capability_retrieval_request_digest,
    capability_run_receipt_digest,
    tool_execution_request_digest,
    tool_idempotency_key,
    tool_plan_validation_request_digest,
    tool_planning_request_digest,
    tool_validation_request_digest,
    tool_validation_result_digest,
    unobserved_tool_attempt_digest,
)


class DeterministicBoundedCapabilityRuntime:
    """One-plan bounded Capability loop with no model, transport or send authority."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        retriever: CapabilityRetriever,
        planner: ToolPlanner,
        plan_validator: ToolPlanValidator,
        binder: ArgumentBinder,
        executor: ToolExecutor,
        result_validator: ToolResultValidator,
        *,
        retrieval_limit: int = 8,
        maximum_latency_ms: int = 600_000,
        execution_terminal_grace: timedelta = timedelta(seconds=5),
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if type(retrieval_limit) is not int or not 1 <= retrieval_limit <= 20:
            raise ValueError("retrieval_limit must be between one and twenty")
        if (
            type(maximum_latency_ms) is not int
            or not 0 <= maximum_latency_ms <= 600_000
        ):
            raise ValueError("maximum_latency_ms is out of range")
        if (
            not isinstance(execution_terminal_grace, timedelta)
            or execution_terminal_grace <= timedelta(0)
            or execution_terminal_grace > timedelta(seconds=30)
        ):
            raise ValueError("execution_terminal_grace is out of range")
        self._registry = registry
        self._retriever = retriever
        self._planner = planner
        self._plan_validator = plan_validator
        self._binder = binder
        self._executor = executor
        self._result_validator = result_validator
        self._retrieval_limit = retrieval_limit
        self._maximum_latency_ms = maximum_latency_ms
        self._execution_terminal_grace = execution_terminal_grace
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def run(
        self,
        request: CapabilityRunRequest,
        *,
        call: PortCallContext,
    ) -> CapabilityRunReceipt:
        if not isinstance(request, CapabilityRunRequest):
            raise validation_error("invalid_capability_run_request")
        now = self._now()
        _validate_call(call, now)
        retrieval = None
        plan = None
        validation_request = None
        validation = None
        observations: list[ToolObservation] = []
        unobserved_attempts: list[UnobservedToolAttempt] = []
        try:
            retrieval_request = self._retrieval_request(request, call=call, now=now)
            retrieval = await _bounded_await(
                self._retriever.retrieve(retrieval_request, call=call),
                call=call,
                now=self._now(),
                code="capability_runtime_retrieval_unavailable",
            )
            if not isinstance(retrieval, CapabilityRetrievalResult):
                return self._receipt(
                    request,
                    call,
                    CapabilityRunStatus.FAILED,
                    retrieval=None,
                    plan=None,
                    observations=(),
                    validation=None,
                    reason="capability_runtime_retrieval_invalid",
                )
            if (
                retrieval.request_digest != retrieval_request.request_digest
                or retrieval.query_digest != request.query.query_digest
                or retrieval.policy_revision != call.policy_snapshot_id
            ):
                return self._receipt(
                    request,
                    call,
                    CapabilityRunStatus.FAILED,
                    retrieval=retrieval,
                    plan=None,
                    observations=(),
                    validation=None,
                    reason="capability_runtime_retrieval_binding_invalid",
                )
            if not retrieval.candidates:
                return self._receipt(
                    request,
                    call,
                    CapabilityRunStatus.DEFERRED,
                    retrieval=retrieval,
                    plan=None,
                    observations=(),
                    validation=None,
                    reason="capability_runtime_no_eligible_candidate",
                )
            planning_values = {
                "schema_version": 1,
                "query": request.query,
                "retrieval": retrieval,
                "prior_observations": (),
                "remaining_attempts": request.maximum_attempts,
            }
            planning_request = ToolPlanningRequest(
                request_digest=tool_planning_request_digest(planning_values),
                **planning_values,
            )
            plan = await _bounded_await(
                self._planner.plan(planning_request, call=call),
                call=call,
                now=self._now(),
                code="capability_runtime_planning_unavailable",
            )
            if not isinstance(plan, ToolPlan):
                return self._receipt(
                    request,
                    call,
                    CapabilityRunStatus.FAILED,
                    retrieval=retrieval,
                    plan=None,
                    observations=(),
                    validation=None,
                    reason="capability_runtime_plan_invalid",
                )
            plan_validation_request = self._plan_validation_request(
                request,
                retrieval,
                plan,
                call=call,
            )
            plan_validation_result = self._plan_validator.validate(
                plan_validation_request
            )
            if (
                not isinstance(plan_validation_result, ToolPlanValidationResult)
                or plan_validation_result.request_digest
                != plan_validation_request.request_digest
                or plan_validation_result.plan_digest != plan.plan_digest
                or not plan_validation_result.valid
            ):
                return self._receipt(
                    request,
                    call,
                    CapabilityRunStatus.FAILED,
                    retrieval=retrieval,
                    plan=plan,
                    observations=(),
                    validation=None,
                    reason="capability_runtime_plan_rejected",
                )
            catalog = self._registry.snapshot_by_id(
                retrieval.catalog_snapshot_id,
                expected_digest=retrieval.catalog_digest,
            )
            output_schemas = self._output_schemas(catalog, plan)
            attempts_by_step: dict[str, int] = {}
            while True:
                validation_request = self._validation_request(
                    retrieval,
                    plan,
                    plan_validation_request,
                    plan_validation_result,
                    tuple(observations),
                    output_schemas,
                    maximum_attempts=request.maximum_attempts,
                )
                validation = await _bounded_await(
                    self._result_validator.validate(validation_request, call=call),
                    call=call,
                    now=self._now(),
                    code="capability_runtime_result_validation_unavailable",
                )
                if not _valid_validation_result(validation_request, validation):
                    return self._receipt(
                        request,
                        call,
                        CapabilityRunStatus.FAILED,
                        retrieval=retrieval,
                        plan=plan,
                        observations=tuple(observations),
                        validation=None,
                        reason="capability_runtime_validation_binding_invalid",
                    )
                if validation.action is ValidationAction.FINISH:
                    return self._receipt(
                        request,
                        call,
                        CapabilityRunStatus.COMPLETED,
                        retrieval=retrieval,
                        plan=plan,
                        observations=tuple(observations),
                        validation_request=validation_request,
                        validation=validation,
                        reason="capability_runtime_completed",
                    )
                if validation.action not in {
                    ValidationAction.CONTINUE,
                    ValidationAction.RETRY,
                }:
                    status = (
                        CapabilityRunStatus.CANCELLED
                        if call.cancellation.is_cancelled
                        else CapabilityRunStatus.FAILED
                    )
                    return self._receipt(
                        request,
                        call,
                        status,
                        retrieval=retrieval,
                        plan=plan,
                        observations=tuple(observations),
                        validation_request=validation_request,
                        validation=validation,
                        reason="capability_runtime_validation_stopped",
                    )
                if len(observations) >= request.maximum_attempts:
                    return self._receipt(
                        request,
                        call,
                        CapabilityRunStatus.FAILED,
                        retrieval=retrieval,
                        plan=plan,
                        observations=tuple(observations),
                        validation_request=validation_request,
                        validation=validation,
                        reason="capability_runtime_attempt_limit_reached",
                    )
                step = _next_step(plan, validation, tuple(observations))
                if step is None:
                    return self._receipt(
                        request,
                        call,
                        CapabilityRunStatus.FAILED,
                        retrieval=retrieval,
                        plan=plan,
                        observations=tuple(observations),
                        validation_request=validation_request,
                        validation=validation,
                        reason="capability_runtime_no_progress",
                    )
                definition = self._registry.get_definition(
                    catalog,
                    step.capability_id,
                )
                input_schema = self._registry.get_schema(
                    catalog,
                    definition.input_schema,
                )
                mapping = self._registry.get_mcp_mapping(
                    catalog,
                    definition.capability_id,
                )
                binding_values = {
                    "schema_version": 1,
                    "plan": plan,
                    "step": step,
                    "accepted_observations": validation.accepted_observations,
                    "input_schema": input_schema,
                    "fixed_arguments": (
                        mapping.fixed_arguments if mapping is not None else {}
                    ),
                }
                binding_request = ArgumentBindingRequest(
                    request_digest=argument_binding_request_digest(binding_values),
                    **binding_values,
                )
                binding = self._binder.bind(binding_request)
                if (
                    binding.request_digest != binding_request.request_digest
                    or binding.step_id != step.step_id
                ):
                    return self._receipt(
                        request,
                        call,
                        CapabilityRunStatus.FAILED,
                        retrieval=retrieval,
                        plan=plan,
                        observations=tuple(observations),
                        validation_request=validation_request,
                        validation=validation,
                        reason="capability_runtime_binding_invalid",
                    )
                attempt = attempts_by_step.get(step.step_id, 0) + 1
                attempts_by_step[step.step_id] = attempt
                key = tool_idempotency_key(
                    run_id=call.run_id,
                    logical_operation_id=step.logical_operation_id,
                    capability_id=step.capability_id,
                    definition_digest=step.definition_digest,
                    normalized_arguments=binding.resolved_arguments,
                )
                execution_values = {
                    "schema_version": 1,
                    "invocation_id": self._new_id("tool-invocation"),
                    "plan_id": plan.plan_id,
                    "plan_digest": plan.plan_digest,
                    "plan_validation_request": plan_validation_request,
                    "plan_validation_result": plan_validation_result,
                    "step_id": step.step_id,
                    "logical_operation_id": step.logical_operation_id,
                    "capability_id": step.capability_id,
                    "definition_digest": step.definition_digest,
                    "catalog_snapshot_id": retrieval.catalog_snapshot_id,
                    "catalog_digest": retrieval.catalog_digest,
                    "provider": definition.provider,
                    "mapping_digest": (
                        mapping.mapping_digest if mapping is not None else None
                    ),
                    "resolved_arguments": binding.resolved_arguments,
                    "source_invocation_ids": binding.source_invocation_ids,
                    "idempotency_key": key,
                    "attempt": attempt,
                    "context": CapabilityExecutionContext(
                        1,
                        request.actor,
                        request.conversation_scope,
                        request.data_classification,
                    ),
                }
                execution_request = ToolExecutionRequest(
                    request_digest=tool_execution_request_digest(execution_values),
                    **execution_values,
                )
                execution_call = _call_after_usage(
                    call,
                    _total_usage(tuple(observations), tuple(unobserved_attempts)),
                )
                try:
                    observation = await _bounded_execution(
                        self._executor.execute(execution_request, call=execution_call),
                        call=execution_call,
                        now=self._now(),
                        terminal_grace=self._execution_terminal_grace,
                    )
                except asyncio.CancelledError:
                    raise
                except DududaError as exc:
                    status = (
                        CapabilityRunStatus.CANCELLED
                        if exc.info.category is ErrorCategory.CANCELLED
                        else CapabilityRunStatus.FAILED
                    )
                    if exc.info.outcome_unknown:
                        unobserved_attempts.append(
                            self._unobserved_attempt(
                                execution_request,
                                definition,
                                tracked_cost=call.budget.cost_units_remaining
                                is not None,
                                reason="capability_runtime_execution_outcome_unknown",
                            )
                        )
                    return self._receipt(
                        request,
                        call,
                        status,
                        retrieval=retrieval,
                        plan=plan,
                        observations=tuple(observations),
                        unobserved_attempts=tuple(unobserved_attempts),
                        validation_request=(
                            None if unobserved_attempts else validation_request
                        ),
                        validation=None if unobserved_attempts else validation,
                        reason="capability_runtime_execution_failed",
                    )
                if not _observation_matches_execution(observation, execution_request):
                    unobserved_attempts.append(
                        self._unobserved_attempt(
                            execution_request,
                            definition,
                            tracked_cost=call.budget.cost_units_remaining is not None,
                            reason="capability_runtime_execution_binding_unknown",
                        )
                    )
                    return self._receipt(
                        request,
                        call,
                        CapabilityRunStatus.FAILED,
                        retrieval=retrieval,
                        plan=plan,
                        observations=tuple(observations),
                        unobserved_attempts=tuple(unobserved_attempts),
                        validation_request=None,
                        validation=None,
                        reason="capability_runtime_execution_binding_invalid",
                    )
                observations.append(observation)
                if call.cancellation.is_cancelled:
                    return self._receipt(
                        request,
                        call,
                        CapabilityRunStatus.CANCELLED,
                        retrieval=retrieval,
                        plan=plan,
                        observations=tuple(observations),
                        validation_request=None,
                        validation=None,
                        reason="capability_runtime_cancelled",
                    )
        except asyncio.CancelledError:
            raise
        except DududaError as exc:
            return self._receipt(
                request,
                call,
                (
                    CapabilityRunStatus.CANCELLED
                    if exc.info.category is ErrorCategory.CANCELLED
                    else CapabilityRunStatus.FAILED
                ),
                retrieval=retrieval,
                plan=plan,
                observations=tuple(observations),
                validation_request=validation_request,
                validation=validation,
                reason="capability_runtime_failed_closed",
            )
        except Exception:  # noqa: BLE001 - component details remain hidden.
            return self._receipt(
                request,
                call,
                CapabilityRunStatus.FAILED,
                retrieval=retrieval,
                plan=plan,
                observations=tuple(observations),
                validation_request=validation_request,
                validation=validation,
                reason="capability_runtime_failed_closed",
            )

    def _retrieval_request(
        self,
        request: CapabilityRunRequest,
        *,
        call: PortCallContext,
        now: datetime,
    ) -> CapabilityRetrievalRequest:
        remaining_ms = max(0, int((call.deadline - now).total_seconds() * 1_000))
        values = {
            "schema_version": 1,
            "query": request.query,
            "actor": request.actor,
            "conversation_scope": request.conversation_scope,
            "data_classification": request.data_classification,
            "available_input_schemas": request.available_input_schemas,
            "maximum_latency_ms": min(self._maximum_latency_ms, remaining_ms),
            "limit": self._retrieval_limit,
        }
        return CapabilityRetrievalRequest(
            request_digest=capability_retrieval_request_digest(values),
            **values,
        )

    def _plan_validation_request(
        self,
        request: CapabilityRunRequest,
        retrieval,
        plan: ToolPlan,
        *,
        call: PortCallContext,
    ) -> ToolPlanValidationRequest:
        maximum_cost = (
            None
            if call.budget.cost_units_remaining is None
            else min(1_000_000_000, int(call.budget.cost_units_remaining))
        )
        values = {
            "schema_version": 1,
            "query": request.query,
            "retrieval": retrieval,
            "plan": plan,
            "maximum_attempts": request.maximum_attempts,
            "maximum_cost_units": maximum_cost,
        }
        return ToolPlanValidationRequest(
            request_digest=tool_plan_validation_request_digest(values),
            **values,
        )

    def _output_schemas(
        self,
        catalog,
        plan: ToolPlan,
    ):
        unique = {}
        for step in plan.steps:
            definition = self._registry.get_definition(catalog, step.capability_id)
            document = self._registry.get_schema(catalog, definition.output_schema)
            key = (
                document.schema_ref.schema_id,
                document.schema_ref.schema_version,
                str(document.schema_ref.digest),
            )
            unique[key] = document
        return tuple(unique[key] for key in sorted(unique))

    def _validation_request(
        self,
        retrieval,
        plan,
        plan_validation_request,
        plan_validation_result,
        observations,
        output_schemas,
        *,
        maximum_attempts: int,
    ) -> ToolValidationRequest:
        values = {
            "schema_version": 1,
            "retrieval": retrieval,
            "plan": plan,
            "plan_validation_request": plan_validation_request,
            "plan_validation_result": plan_validation_result,
            "observations": observations,
            "output_schemas": output_schemas,
            "maximum_attempts": maximum_attempts,
        }
        return ToolValidationRequest(
            request_digest=tool_validation_request_digest(values),
            **values,
        )

    def _unobserved_attempt(
        self,
        request: ToolExecutionRequest,
        definition,
        *,
        tracked_cost: bool,
        reason: str,
    ) -> UnobservedToolAttempt:
        usage = ResourceUsage(
            1,
            tool_steps=1,
            retries=1 if request.attempt > 1 else 0,
            cost_units=(Decimal(definition.cost_hint.units) if tracked_cost else None),
        )
        values = {
            "schema_version": 1,
            "execution_request_digest": request.request_digest,
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
            "usage": usage,
            "reason_codes": (reason,),
            "recorded_at": self._now(),
            "dispatch_may_have_occurred": True,
            "outcome_unknown": True,
        }
        return UnobservedToolAttempt(
            attempt_digest=unobserved_tool_attempt_digest(values),
            **values,
        )

    def _receipt(
        self,
        request: CapabilityRunRequest,
        call: PortCallContext,
        status: CapabilityRunStatus,
        *,
        retrieval,
        plan,
        observations: tuple[ToolObservation, ...],
        unobserved_attempts: tuple[UnobservedToolAttempt, ...] = (),
        validation_request=None,
        validation,
        reason: str,
    ) -> CapabilityRunReceipt:
        if (
            validation_request is None
            or validation is None
            or validation_request.observations != observations
            or unobserved_attempts
        ):
            validation_request = None
            validation = None
        usage = _total_usage(observations, unobserved_attempts)
        values = {
            "schema_version": 1,
            "run_id": call.run_id,
            "request": request,
            "request_digest": request.request_digest,
            "status": status,
            "retrieval": retrieval,
            "plan": plan,
            "observations": observations,
            "unobserved_attempts": unobserved_attempts,
            "validation_request": validation_request,
            "validation": validation,
            "usage": usage,
            "reason_codes": (reason,),
            "completed_at": self._now(),
        }
        return CapabilityRunReceipt(
            receipt_digest=capability_run_receipt_digest(values),
            **values,
        )

    def _new_id(self, prefix: str) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - callback details remain hidden.
            raise error(
                "capability_runtime_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise validation_error("invalid_capability_runtime_id")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - callback details remain hidden.
            raise error(
                "capability_runtime_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_capability_runtime_clock")
        return value


def _next_step(
    plan: ToolPlan,
    validation: ToolValidationResult,
    observations: tuple[ToolObservation, ...],
):
    if validation.action is ValidationAction.RETRY:
        return next(
            (step for step in plan.steps if step.step_id == validation.retry_step_id),
            None,
        )
    accepted = {item.step_id for item in validation.accepted_observations}
    attempted = {item.step_id for item in observations}
    return next(
        (
            step
            for step in plan.steps
            if step.step_id not in accepted
            and step.step_id not in attempted
            and all(dependency in accepted for dependency in step.depends_on)
        ),
        None,
    )


def _valid_validation_result(
    request: ToolValidationRequest,
    result: ToolValidationResult,
) -> bool:
    return bool(
        isinstance(result, ToolValidationResult)
        and tool_validation_result_digest(result) == result.result_digest
        and result.request_digest == request.request_digest
        and all(item in request.observations for item in result.accepted_observations)
    )


def _observation_matches_execution(
    observation: ToolObservation,
    request: ToolExecutionRequest,
) -> bool:
    return bool(
        isinstance(observation, ToolObservation)
        and observation.execution_request_digest == request.request_digest
        and observation.invocation_id == request.invocation_id
        and observation.plan_id == request.plan_id
        and observation.plan_digest == request.plan_digest
        and observation.step_id == request.step_id
        and observation.logical_operation_id == request.logical_operation_id
        and observation.capability_id == request.capability_id
        and observation.definition_digest == request.definition_digest
        and observation.catalog_snapshot_id == request.catalog_snapshot_id
        and observation.catalog_digest == request.catalog_digest
        and observation.provider == request.provider
        and observation.mapping_digest == request.mapping_digest
        and observation.idempotency_key == request.idempotency_key
        and observation.attempt == request.attempt
    )


def _total_usage(
    observations: tuple[ToolObservation, ...],
    unobserved_attempts: tuple[UnobservedToolAttempt, ...],
) -> ResourceUsage:
    attempts = (*observations, *unobserved_attempts)
    cost_is_tracked = all(item.usage.cost_units is not None for item in attempts)
    return ResourceUsage(
        1,
        model_calls=sum(item.usage.model_calls for item in attempts),
        tool_steps=sum(item.usage.tool_steps for item in attempts),
        retries=sum(item.usage.retries for item in attempts),
        input_tokens=sum(item.usage.input_tokens for item in attempts),
        output_tokens=sum(item.usage.output_tokens for item in attempts),
        cost_units=(
            sum(
                (item.usage.cost_units or Decimal(0) for item in attempts),
                Decimal(0),
            )
            if cost_is_tracked
            else None
        ),
    )


def _validate_call(call: PortCallContext, now: datetime) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_capability_runtime_call")
    if call.cancellation.is_cancelled:
        raise error(
            "capability_runtime_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "capability_runtime_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


def _call_after_usage(
    call: PortCallContext,
    usage: ResourceUsage,
) -> PortCallContext:
    budget = _remaining_budget(call.budget, usage)
    return PortCallContext(
        run_id=call.run_id,
        trace=call.trace,
        deadline=call.deadline,
        cancellation=call.cancellation,
        budget=budget,
        policy_snapshot_id=call.policy_snapshot_id,
    )


def _remaining_budget(
    budget: RuntimeBudget,
    usage: ResourceUsage,
) -> RuntimeBudget:
    values = {
        "model_calls_remaining": budget.model_calls_remaining - usage.model_calls,
        "tool_steps_remaining": budget.tool_steps_remaining - usage.tool_steps,
        "retries_remaining": budget.retries_remaining - usage.retries,
        "input_tokens_remaining": budget.input_tokens_remaining - usage.input_tokens,
        "output_tokens_remaining": budget.output_tokens_remaining - usage.output_tokens,
    }
    if any(value < 0 for value in values.values()):
        raise error(
            "capability_runtime_budget_exhausted",
            ErrorCategory.BUDGET,
            "request.budget_exhausted",
        )
    if budget.cost_units_remaining is None:
        cost = None
    elif usage.cost_units is None or usage.cost_units > budget.cost_units_remaining:
        raise error(
            "capability_runtime_budget_exhausted",
            ErrorCategory.BUDGET,
            "request.budget_exhausted",
        )
    else:
        cost = budget.cost_units_remaining - usage.cost_units
    return RuntimeBudget(cost_units_remaining=cost, **values)


async def _bounded_await(
    awaitable: Awaitable[object],
    *,
    call: PortCallContext,
    now: datetime,
    code: str,
):
    _validate_call(call, now)
    task = asyncio.create_task(awaitable)
    cancelled = asyncio.create_task(call.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (task, cancelled),
            timeout=max(0.0, (call.deadline - now).total_seconds()),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if task in done:
            return task.result()
        if cancelled in done:
            await _cancel_task(task, drain_seconds=0.1)
            raise error(
                f"{code}_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if task not in done:
            await _cancel_task(task, drain_seconds=0.1)
            raise error(
                f"{code}_timeout",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )
    except asyncio.CancelledError:
        await _cancel_task(task, drain_seconds=0.1)
        raise
    finally:
        await _cancel_task(cancelled, drain_seconds=0.1)


async def _bounded_execution(
    awaitable: Awaitable[object],
    *,
    call: PortCallContext,
    now: datetime,
    terminal_grace: timedelta,
):
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_capability_runtime_call")
    if now >= call.deadline:
        raise error(
            "capability_runtime_execution_timeout",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )
    task = asyncio.create_task(awaitable)
    cancelled = asyncio.create_task(call.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (task, cancelled),
            timeout=max(0.0, (call.deadline - now).total_seconds()),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if task in done:
            return task.result()
        terminal, _ = await asyncio.wait(
            (task,),
            timeout=terminal_grace.total_seconds(),
        )
        if task in terminal:
            return task.result()
        await _cancel_task(task, drain_seconds=0.1)
        category = (
            ErrorCategory.CANCELLED if cancelled in done else ErrorCategory.TIMEOUT
        )
        raise error(
            "capability_runtime_execution_not_terminal",
            category,
            "request.cancelled"
            if category is ErrorCategory.CANCELLED
            else "request.timeout",
            outcome_unknown=True,
        )
    except asyncio.CancelledError:
        await _cancel_task(
            task,
            drain_seconds=terminal_grace.total_seconds(),
        )
        raise
    finally:
        await _cancel_task(cancelled, drain_seconds=0.1)


async def _cancel_task(
    task: asyncio.Task[object],
    *,
    drain_seconds: float,
) -> None:
    cleanup = asyncio.create_task(_bounded_cancel_task(task, drain_seconds))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
    cleanup.result()


async def _bounded_cancel_task(
    task: asyncio.Task[object],
    drain_seconds: float,
) -> None:
    if task.done():
        _consume_detached_task(task)
        return
    task.cancel()
    done, _ = await asyncio.wait((task,), timeout=max(0.0, drain_seconds))
    if task not in done:
        task.add_done_callback(_consume_detached_task)
        return
    _consume_detached_task(task)


def _consume_detached_task(task: asyncio.Task[object]) -> None:
    try:
        task.result()
    except BaseException:  # noqa: BLE001 - detached task outcome is intentionally consumed.
        return


__all__ = ["DeterministicBoundedCapabilityRuntime"]
