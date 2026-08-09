from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import (
    ComponentRevision,
    JsonValue,
    freeze_json,
)
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.capabilities import CapabilityRegistry, CapabilitySchemaValidator
from dududa.ports.context import PortCallContext

from .contracts import (
    ArgumentBindingRequest,
    ArgumentBindingResult,
    ArgumentTemplate,
    CapabilityCandidate,
    CapabilityCatalogSnapshot,
    CapabilitySchemaDocument,
    ToolPlan,
    ToolPlanningRequest,
    ToolPlanValidationRequest,
    ToolPlanValidationResult,
    ToolStep,
)
from .digests import (
    argument_binding_result_digest,
    tool_plan_digest,
    tool_plan_validation_result_digest,
)


class DeterministicToolPlanner:
    """Reference one-step Planner for explicit, configuration-owned hints."""

    def __init__(
        self,
        argument_hints: Mapping[str, Mapping[str, JsonValue]] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        revision: ComponentRevision | None = None,
    ) -> None:
        hints: dict[str, Mapping[str, JsonValue]] = {}
        for capability_id, arguments in (argument_hints or {}).items():
            if not isinstance(capability_id, str) or not capability_id.strip():
                raise validation_error("invalid_tool_planner_hint_id")
            frozen = freeze_json(arguments, path="$.tool_planner_hint")
            if not isinstance(frozen, Mapping):
                raise validation_error("invalid_tool_planner_hint")
            hints[capability_id] = frozen
        self._hints = hints
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._revision = revision or _revision(
            "capability.planner",
            "deterministic-hints-v1",
        )

    async def plan(
        self,
        request: ToolPlanningRequest,
        *,
        call: PortCallContext,
    ) -> ToolPlan:
        if not isinstance(request, ToolPlanningRequest):
            raise validation_error("invalid_tool_planning_request")
        _validate_call(call, self._now(), phase="planning")
        if not request.retrieval.candidates:
            raise validation_error("tool_planning_has_no_candidate")
        candidate = request.retrieval.candidates[0]
        arguments = self._hints.get(candidate.capability_id, {})
        operation_material = {
            "query_digest": request.query.query_digest,
            "capability_id": candidate.capability_id,
            "definition_digest": candidate.definition_digest,
        }
        operation_suffix = str(
            canonical_digest(
                operation_material,
                domain="capability.logical-operation:v1",
            )
        ).rsplit(":", maxsplit=1)[1][:32]
        step = ToolStep(
            schema_version=1,
            step_id=f"step:{operation_suffix}",
            logical_operation_id=f"operation:{operation_suffix}",
            capability_id=candidate.capability_id,
            definition_digest=candidate.definition_digest,
            arguments=ArgumentTemplate(1, arguments, ()),
            purpose="approved_capability_execution",
            depends_on=(),
            expected_output_schema=candidate.output_schema,
        )
        values = {
            "schema_version": 1,
            "plan_id": self._new_id("tool-plan"),
            "query_digest": request.query.query_digest,
            "retrieval_result_digest": request.retrieval.result_digest,
            "steps": (step,),
            "completion_criteria": ("validated_result",),
            "planner_revision": self._revision,
        }
        return ToolPlan(plan_digest=tool_plan_digest(values), **values)

    def _new_id(self, prefix: str) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - factory failures are sanitized.
            raise error(
                "tool_planner_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise validation_error("invalid_tool_planner_id")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        return _now(self._clock, "tool_planner_clock_unavailable")


class DeterministicToolPlanValidator:
    """Own candidate membership, DAG, Schema and combined-cost plan gates."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        schema_validator: CapabilitySchemaValidator,
        *,
        revision: ComponentRevision | None = None,
    ) -> None:
        self._registry = registry
        self._schema_validator = schema_validator
        self._revision = revision or _revision(
            "capability.plan-validator",
            "deterministic-v1",
        )

    def validate(
        self,
        request: ToolPlanValidationRequest,
    ) -> ToolPlanValidationResult:
        if not isinstance(request, ToolPlanValidationRequest):
            raise validation_error("invalid_tool_plan_validation_request")
        try:
            reason = self._invalid_reason(request)
        except Exception:  # noqa: BLE001 - invalid proposals expose one stable reason.
            reason = "plan_validation_failed_closed"
        valid = reason is None
        values = {
            "schema_version": 1,
            "request_digest": request.request_digest,
            "plan_digest": request.plan.plan_digest,
            "valid": valid,
            "reason_codes": ("plan_valid",) if valid else (reason,),
            "validator_revision": self._revision,
        }
        return ToolPlanValidationResult(
            result_digest=tool_plan_validation_result_digest(values),
            **values,
        )

    def _invalid_reason(self, request: ToolPlanValidationRequest) -> str | None:
        try:
            catalog = self._registry.snapshot_by_id(
                request.retrieval.catalog_snapshot_id,
                expected_digest=request.retrieval.catalog_digest,
            )
        except Exception:  # noqa: BLE001 - Catalog internals are not an oracle.
            return "plan_catalog_binding_invalid"
        if not isinstance(catalog, CapabilityCatalogSnapshot):
            return "plan_catalog_binding_invalid"
        if len(request.plan.steps) > request.maximum_attempts:
            return "plan_step_limit_exceeded"
        candidates = {item.capability_id: item for item in request.retrieval.candidates}
        steps = {item.step_id: item for item in request.plan.steps}
        indexes = {item.step_id: index for index, item in enumerate(request.plan.steps)}
        total_cost = 0
        for step in request.plan.steps:
            candidate = candidates.get(step.capability_id)
            if not _candidate_matches_step(candidate, step):
                return "plan_candidate_binding_invalid"
            try:
                definition = self._registry.get_definition(
                    catalog,
                    step.capability_id,
                )
                input_schema = self._registry.get_schema(
                    catalog,
                    definition.input_schema,
                )
            except Exception:  # noqa: BLE001 - Catalog detail remains hidden.
                return "plan_catalog_binding_invalid"
            if (
                definition.definition_digest != step.definition_digest
                or definition.output_schema != step.expected_output_schema
            ):
                return "plan_candidate_binding_invalid"
            total_cost += definition.cost_hint.units
            if request.maximum_cost_units is not None and (
                total_cost > request.maximum_cost_units
            ):
                return "plan_cost_limit_exceeded"
            if any(
                dependency not in steps or indexes[dependency] >= indexes[step.step_id]
                for dependency in step.depends_on
            ):
                return "plan_dependency_invalid"
            fixed_arguments = self._fixed_arguments(catalog, step.capability_id)
            if _top_level_overlap(step.arguments.literal_template, fixed_arguments):
                return "plan_fixed_argument_override"
            if not _literal_keys_allowed(
                step.arguments.literal_template,
                input_schema,
            ):
                return "plan_argument_schema_invalid"
            for binding in step.arguments.bindings:
                if binding.source_step_id not in step.depends_on:
                    return "plan_binding_source_invalid"
                source_step = steps[binding.source_step_id]
                source_candidate = candidates.get(source_step.capability_id)
                if not _candidate_matches_step(source_candidate, source_step):
                    return "plan_binding_source_invalid"
                try:
                    source_schema = self._registry.get_schema(
                        catalog,
                        source_candidate.output_schema,
                    )
                except Exception:  # noqa: BLE001 - Schema detail remains hidden.
                    return "plan_catalog_binding_invalid"
                if not _schema_allows_pointer(
                    source_schema,
                    binding.source_json_pointer,
                ):
                    return "plan_binding_source_invalid"
                if not _schema_allows_pointer(
                    input_schema,
                    binding.target_json_pointer,
                ):
                    return "plan_binding_target_invalid"
                if _pointer_exists(
                    step.arguments.literal_template,
                    binding.target_json_pointer,
                ):
                    return "plan_binding_target_conflict"
                if _pointer_top_key(binding.target_json_pointer) in fixed_arguments:
                    return "plan_fixed_argument_override"
            if not _required_inputs_covered(
                step.arguments,
                fixed_arguments,
                input_schema,
            ):
                return "plan_argument_schema_invalid"
            if not step.arguments.bindings and not self._complete_arguments_valid(
                step.arguments.literal_template,
                fixed_arguments,
                input_schema,
            ):
                return "plan_argument_schema_invalid"
        return None

    def _fixed_arguments(
        self,
        catalog: CapabilityCatalogSnapshot,
        capability_id: str,
    ) -> Mapping[str, JsonValue]:
        mapping = self._registry.get_mcp_mapping(catalog, capability_id)
        return mapping.fixed_arguments if mapping is not None else {}

    def _complete_arguments_valid(
        self,
        literal: Mapping[str, JsonValue],
        fixed: Mapping[str, JsonValue],
        schema: CapabilitySchemaDocument,
    ) -> bool:
        value = dict(literal)
        value.update(fixed)
        try:
            validated = self._schema_validator.validate(value, schema)
        except Exception:  # noqa: BLE001 - Schema implementation details are hidden.
            return False
        return isinstance(validated, Mapping)


class DeterministicArgumentBinder:
    """Resolve approved JSON Pointers into one fully Schema-validated argument map."""

    def __init__(
        self,
        schema_validator: CapabilitySchemaValidator,
        *,
        revision: ComponentRevision | None = None,
    ) -> None:
        self._schema_validator = schema_validator
        self._revision = revision or _revision(
            "capability.argument-binder",
            "json-pointer-v1",
        )

    def bind(self, request: ArgumentBindingRequest) -> ArgumentBindingResult:
        if not isinstance(request, ArgumentBindingRequest):
            raise validation_error("invalid_argument_binding_request")
        observations = {item.step_id: item for item in request.accepted_observations}
        if len(observations) != len(request.accepted_observations):
            raise validation_error("duplicate_binding_observation_step")
        if _top_level_overlap(
            request.step.arguments.literal_template,
            request.fixed_arguments,
        ):
            raise validation_error("binding_fixed_argument_override")
        resolved = _thaw(request.step.arguments.literal_template)
        if not isinstance(resolved, dict):
            raise validation_error("invalid_binding_literal_template")
        source_invocation_ids: list[str] = []
        for binding in request.step.arguments.bindings:
            if binding.source_step_id not in request.step.depends_on:
                raise validation_error("binding_source_not_declared_dependency")
            observation = observations.get(binding.source_step_id)
            if observation is None or observation.data is None:
                raise validation_error("binding_source_observation_missing")
            if _pointer_top_key(binding.target_json_pointer) in request.fixed_arguments:
                raise validation_error("binding_fixed_argument_override")
            try:
                value = _resolve_pointer(
                    observation.data,
                    binding.source_json_pointer,
                )
                _set_pointer(resolved, binding.target_json_pointer, _thaw(value))
            except Exception:  # noqa: BLE001 - raw Observation data is never exposed.
                raise validation_error("argument_binding_pointer_failed") from None
            if observation.invocation_id not in source_invocation_ids:
                source_invocation_ids.append(observation.invocation_id)
        resolved.update(_thaw(request.fixed_arguments))
        try:
            validated = self._schema_validator.validate(
                resolved,
                request.input_schema,
            )
        except Exception:  # noqa: BLE001 - Schema implementation details are hidden.
            raise validation_error("argument_binding_schema_invalid") from None
        if not isinstance(validated, Mapping):
            raise validation_error("argument_binding_schema_invalid")
        values = {
            "schema_version": 1,
            "request_digest": request.request_digest,
            "step_id": request.step.step_id,
            "resolved_arguments": validated,
            "source_invocation_ids": tuple(source_invocation_ids),
            "binder_revision": self._revision,
        }
        return ArgumentBindingResult(
            result_digest=argument_binding_result_digest(values),
            **values,
        )


def _candidate_matches_step(
    candidate: CapabilityCandidate | None,
    step: ToolStep,
) -> bool:
    return bool(
        candidate is not None
        and candidate.definition_digest == step.definition_digest
        and candidate.output_schema == step.expected_output_schema
    )


def _schema_allows_pointer(
    schema: CapabilitySchemaDocument,
    pointer: str,
) -> bool:
    current: object = schema.document
    for token in _pointer_tokens(pointer):
        if not isinstance(current, Mapping):
            return False
        properties = current.get("properties")
        if isinstance(properties, Mapping) and token in properties:
            current = properties[token]
            continue
        if current.get("type") == "array" and token.isdigit():
            items = current.get("items")
            if isinstance(items, Mapping):
                current = items
                continue
        return False
    return True


def _literal_keys_allowed(
    literal: Mapping[str, JsonValue],
    schema: CapabilitySchemaDocument,
) -> bool:
    properties = schema.document.get("properties")
    if not isinstance(properties, Mapping):
        return not literal or schema.document.get("additionalProperties") is not False
    if schema.document.get("additionalProperties") is False:
        return set(literal) <= set(properties)
    return True


def _required_inputs_covered(
    arguments: ArgumentTemplate,
    fixed: Mapping[str, JsonValue],
    schema: CapabilitySchemaDocument,
) -> bool:
    required = schema.document.get("required", ())
    if not isinstance(required, (tuple, list)) or any(
        not isinstance(item, str) for item in required
    ):
        return False
    covered = set(arguments.literal_template) | set(fixed)
    covered.update(
        _pointer_top_key(binding.target_json_pointer) for binding in arguments.bindings
    )
    return set(required) <= covered


def _top_level_overlap(
    first: Mapping[str, JsonValue],
    second: Mapping[str, JsonValue],
) -> bool:
    return bool(set(first) & set(second))


def _pointer_exists(value: object, pointer: str) -> bool:
    try:
        _resolve_pointer(value, pointer)
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return True


def _resolve_pointer(value: object, pointer: str) -> object:
    current = value
    for token in _pointer_tokens(pointer):
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        elif isinstance(current, (tuple, list)):
            if not token.isdigit():
                raise TypeError("array pointer token must be an index")
            current = current[int(token)]
        else:
            raise TypeError("pointer traverses a scalar")
    return current


def _set_pointer(value: object, pointer: str, resolved: object) -> None:
    tokens = _pointer_tokens(pointer)
    current = value
    for token in tokens[:-1]:
        if isinstance(current, dict):
            if token not in current:
                existing = {}
                current[token] = existing
            else:
                existing = current[token]
            current = existing
        elif isinstance(current, list):
            if not token.isdigit():
                raise TypeError("array pointer token must be an index")
            current = current[int(token)]
        else:
            raise TypeError("pointer traverses a scalar")
    final = tokens[-1]
    if isinstance(current, dict):
        if final in current:
            raise ValueError("binding target already exists")
        current[final] = resolved
        return
    if isinstance(current, list):
        if not final.isdigit():
            raise TypeError("array pointer token must be an index")
        index = int(final)
        if index >= len(current):
            raise IndexError(index)
        raise KeyError("binding target already exists")
    raise TypeError("pointer target parent is scalar")


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("invalid JSON Pointer")
    return tuple(
        token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")
    )


def _pointer_top_key(pointer: str) -> str:
    return _pointer_tokens(pointer)[0]


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _revision(component_id: str, config_revision: str) -> ComponentRevision:
    return ComponentRevision(
        component_id,
        "1.0.0",
        config_revision,
        canonical_digest(
            {"component_id": component_id, "config_revision": config_revision},
            domain="capability.component-artifact:v1",
        ),
    )


def _now(clock: Callable[[], datetime], code: str) -> datetime:
    try:
        value = clock()
    except Exception:  # noqa: BLE001 - clock failures are sanitized.
        raise error(
            code,
            ErrorCategory.INTERNAL,
            "service.unavailable",
        ) from None
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise validation_error("invalid_capability_component_clock")
    return value


def _validate_call(call: PortCallContext, now: datetime, *, phase: str) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_capability_component_call_context", phase)
    if call.cancellation.is_cancelled:
        raise error(
            f"capability_{phase}_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            f"capability_{phase}_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


__all__ = [
    "DeterministicArgumentBinder",
    "DeterministicToolPlanValidator",
    "DeterministicToolPlanner",
]
