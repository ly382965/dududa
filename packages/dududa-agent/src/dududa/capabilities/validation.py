from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from dududa.contracts.canonical import canonical_digest
from dududa.domain.capability import CapabilityDefinition, Idempotency
from dududa.domain.primitives import ComponentRevision, PrivacyLevel
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.capabilities import (
    CapabilityRegistry,
    CapabilitySchemaValidator,
    ToolPlanValidator,
)
from dududa.ports.context import PortCallContext

from .contracts import (
    CapabilityCatalogSnapshot,
    CapabilityProviderKind,
    CapabilitySchemaDocument,
    ToolExecutionStatus,
    ToolObservation,
    ToolValidationRequest,
    ToolValidationResult,
    ValidationAction,
)
from .digests import tool_validation_result_digest

_PRIVACY_ORDER = {
    PrivacyLevel.PUBLIC: 0,
    PrivacyLevel.CONVERSATION: 1,
    PrivacyLevel.PERSONAL: 2,
    PrivacyLevel.SENSITIVE: 3,
    PrivacyLevel.RESTRICTED: 4,
}


class DeterministicToolResultValidator:
    """Validate untrusted Observations without interpreting their text as control."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        schema_validator: CapabilitySchemaValidator,
        plan_validator: ToolPlanValidator,
        *,
        clock: Callable[[], datetime] | None = None,
        revision: ComponentRevision | None = None,
    ) -> None:
        self._registry = registry
        self._schemas = schema_validator
        self._plan_validator = plan_validator
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._revision = revision or _revision()

    async def validate(
        self,
        request: ToolValidationRequest,
        *,
        call: PortCallContext,
    ) -> ToolValidationResult:
        if not isinstance(request, ToolValidationRequest):
            raise validation_error("invalid_tool_validation_request")
        now = self._now()
        _validate_call(call, now)
        try:
            action, accepted, retry_step, reason = self._evaluate(
                request,
                call=call,
                now=now,
            )
        except Exception:  # noqa: BLE001 - invalid evidence exposes one reason only.
            action = ValidationAction.ABORT
            accepted = ()
            retry_step = None
            reason = "tool_validation_failed_closed"
        values = {
            "schema_version": 1,
            "request_digest": request.request_digest,
            "action": action,
            "accepted_observations": accepted,
            "retry_step_id": retry_step,
            "clarification_key": None,
            "reason_codes": (reason,),
            "validator_revision": self._revision,
        }
        return ToolValidationResult(
            result_digest=tool_validation_result_digest(values),
            **values,
        )

    def _evaluate(
        self,
        request: ToolValidationRequest,
        *,
        call: PortCallContext,
        now: datetime,
    ) -> tuple[
        ValidationAction,
        tuple[ToolObservation, ...],
        str | None,
        str,
    ]:
        if request.retrieval.policy_revision != call.policy_snapshot_id:
            return _abort("tool_validation_policy_mismatch")
        if (
            self._plan_validator.validate(request.plan_validation_request)
            != request.plan_validation_result
        ):
            return _abort("tool_validation_plan_evidence_invalid")
        try:
            catalog = self._registry.snapshot_by_id(
                request.retrieval.catalog_snapshot_id,
                expected_digest=request.retrieval.catalog_digest,
            )
        except Exception:  # noqa: BLE001 - Catalog internals remain hidden.
            return _abort("tool_validation_catalog_binding_invalid")
        definitions = self._definitions(request, catalog)
        expected_schemas = self._expected_schemas(request, catalog, definitions)
        if request.output_schemas != expected_schemas:
            return _abort("tool_validation_schema_set_mismatch")

        accepted_by_step: dict[str, ToolObservation] = {}
        attempts_by_step: dict[str, int] = {}
        seen_invocations: set[str] = set()
        last_failure: tuple[ToolObservation, CapabilityDefinition] | None = None
        step_by_id = {step.step_id: step for step in request.plan.steps}
        for observation in request.observations:
            step = step_by_id.get(observation.step_id)
            definition = definitions.get(observation.step_id)
            if step is None or definition is None:
                return _abort("tool_validation_unknown_step")
            expected_attempt = attempts_by_step.get(step.step_id, 0) + 1
            if observation.attempt != expected_attempt:
                return _abort("tool_validation_attempt_sequence_invalid")
            attempts_by_step[step.step_id] = expected_attempt
            if observation.invocation_id in seen_invocations:
                return _abort("tool_validation_duplicate_invocation")
            seen_invocations.add(observation.invocation_id)
            if step.step_id in accepted_by_step:
                return _abort("tool_validation_observation_after_success")
            if any(
                dependency not in accepted_by_step for dependency in step.depends_on
            ):
                return _abort("tool_validation_dependency_not_accepted")
            binding_reason = self._binding_reason(
                request,
                catalog,
                definition,
                observation,
                now=now,
                call=call,
            )
            if binding_reason is not None:
                return _abort(binding_reason)
            if observation.status is ToolExecutionStatus.UNKNOWN:
                return _abort("tool_validation_unknown_outcome")
            if observation.status is ToolExecutionStatus.FAILED:
                last_failure = (observation, definition)
                continue
            result_reason = self._result_reason(
                catalog,
                definition,
                observation,
                request.output_schemas,
            )
            if result_reason is not None:
                return _abort(result_reason)
            accepted_by_step[step.step_id] = observation
            last_failure = None

        accepted = tuple(
            accepted_by_step[step.step_id]
            for step in request.plan.steps
            if step.step_id in accepted_by_step
        )
        if len(accepted) == len(request.plan.steps):
            return (
                ValidationAction.FINISH,
                accepted,
                None,
                "tool_validation_all_steps_accepted",
            )
        if last_failure is not None:
            failed, definition = last_failure
            if (
                failed.error is not None
                and failed.error.info.retryable
                and not failed.error.info.outcome_unknown
                and definition.idempotency is not Idempotency.NON_IDEMPOTENT
                and len(request.observations) < request.maximum_attempts
                and call.budget.retries_remaining > 0
                and call.budget.tool_steps_remaining > 0
            ):
                return (
                    ValidationAction.RETRY,
                    accepted,
                    failed.step_id,
                    "tool_validation_retry_allowed",
                )
            return (
                ValidationAction.ABORT,
                accepted,
                None,
                "tool_validation_failure_terminal",
            )
        ready = next(
            (
                step
                for step in request.plan.steps
                if step.step_id not in accepted_by_step
                and all(
                    dependency in accepted_by_step for dependency in step.depends_on
                )
            ),
            None,
        )
        if ready is not None and len(request.observations) < request.maximum_attempts:
            return (
                ValidationAction.CONTINUE,
                accepted,
                None,
                "tool_validation_ready_step_available",
            )
        return (
            ValidationAction.ABORT,
            accepted,
            None,
            "tool_validation_no_progress",
        )

    def _definitions(
        self,
        request: ToolValidationRequest,
        catalog: CapabilityCatalogSnapshot,
    ) -> dict[str, CapabilityDefinition]:
        values: dict[str, CapabilityDefinition] = {}
        candidates = {item.capability_id: item for item in request.retrieval.candidates}
        for step in request.plan.steps:
            definition = self._registry.get_definition(catalog, step.capability_id)
            candidate = candidates.get(step.capability_id)
            if (
                candidate is None
                or candidate.definition_digest != step.definition_digest
                or candidate.provider != definition.provider
                or definition.definition_digest != step.definition_digest
                or definition.output_schema != step.expected_output_schema
            ):
                raise validation_error("tool_validation_definition_binding_invalid")
            values[step.step_id] = definition
        return values

    def _expected_schemas(
        self,
        request: ToolValidationRequest,
        catalog: CapabilityCatalogSnapshot,
        definitions: Mapping[str, CapabilityDefinition],
    ) -> tuple[CapabilitySchemaDocument, ...]:
        unique: dict[tuple[str, int, str], CapabilitySchemaDocument] = {}
        for step in request.plan.steps:
            document = self._registry.get_schema(
                catalog,
                definitions[step.step_id].output_schema,
            )
            key = (
                document.schema_ref.schema_id,
                document.schema_ref.schema_version,
                str(document.schema_ref.digest),
            )
            unique[key] = document
        return tuple(unique[key] for key in sorted(unique))

    def _binding_reason(
        self,
        request: ToolValidationRequest,
        catalog: CapabilityCatalogSnapshot,
        definition: CapabilityDefinition,
        observation: ToolObservation,
        *,
        now: datetime,
        call: PortCallContext,
    ) -> str | None:
        step = next(
            item for item in request.plan.steps if item.step_id == observation.step_id
        )
        mapping = self._registry.get_mcp_mapping(catalog, definition.capability_id)
        expected_mapping = mapping.mapping_digest if mapping is not None else None
        if (
            observation.plan_id != request.plan.plan_id
            or observation.plan_digest != request.plan.plan_digest
            or observation.logical_operation_id != step.logical_operation_id
            or observation.capability_id != step.capability_id
            or observation.definition_digest != step.definition_digest
            or observation.catalog_snapshot_id != request.retrieval.catalog_snapshot_id
            or observation.catalog_digest != request.retrieval.catalog_digest
            or observation.provider != definition.provider
            or observation.mapping_digest != expected_mapping
            or observation.policy_revision != request.retrieval.policy_revision
            or observation.observed_at > now
            or observation.observed_at > call.deadline
        ):
            return "tool_validation_observation_binding_invalid"
        return None

    def _result_reason(
        self,
        catalog: CapabilityCatalogSnapshot,
        definition: CapabilityDefinition,
        observation: ToolObservation,
        schemas: tuple[CapabilitySchemaDocument, ...],
    ) -> str | None:
        if observation.truncated:
            return "tool_validation_result_truncated"
        if (
            _PRIVACY_ORDER[observation.sensitivity]
            > _PRIVACY_ORDER[definition.privacy_level]
        ):
            return "tool_validation_sensitivity_exceeded"
        if not _non_empty(observation.data):
            return "tool_validation_result_empty"
        schema = next(
            (item for item in schemas if item.schema_ref == definition.output_schema),
            None,
        )
        if schema is None:
            return "tool_validation_output_schema_missing"
        try:
            validated = self._schemas.validate(observation.data, schema)
        except Exception:  # noqa: BLE001 - Schema implementation details are hidden.
            return "tool_validation_output_schema_invalid"
        if validated != observation.data:
            return "tool_validation_output_schema_invalid"
        descriptor = next(
            item
            for item in catalog.provider_descriptors
            if item.provider == definition.provider
        )
        if (
            descriptor.kind is CapabilityProviderKind.MCP
            and not observation.source_refs
        ):
            return "tool_validation_source_missing"
        return None

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - callback details are hidden.
            raise error(
                "tool_result_validator_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_tool_result_validator_clock")
        return value


def _non_empty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, tuple, list)):
        return bool(value)
    return True


def _abort(
    reason: str,
) -> tuple[ValidationAction, tuple[ToolObservation, ...], None, str]:
    return ValidationAction.ABORT, (), None, reason


def _revision() -> ComponentRevision:
    values = {
        "component_id": "capability.result-validator",
        "config_revision": "deterministic-v1",
    }
    return ComponentRevision(
        "capability.result-validator",
        "1.0.0",
        "deterministic-v1",
        canonical_digest(values, domain="capability.component-artifact:v1"),
    )


def _validate_call(call: PortCallContext, now: datetime) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_tool_result_validator_call")
    if call.cancellation.is_cancelled:
        raise error(
            "tool_result_validation_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "tool_result_validation_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


__all__ = ["DeterministicToolResultValidator"]
