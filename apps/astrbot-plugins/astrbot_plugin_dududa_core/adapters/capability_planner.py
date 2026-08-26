from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from dududa.capabilities import (
    TOOL_COMPLETION_ALL_STEPS,
    ArgumentTemplate,
    ToolPlan,
    ToolPlanningRequest,
    ToolStep,
    tool_plan_digest,
)
from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision, DigestString, JsonValue
from dududa.errors import validation_error
from dududa.ports.capabilities import CapabilityRegistry
from dududa.ports.context import PortCallContext

ICOURSE_PUBLIC_QUERY_CAPABILITY_ID = "icourse.public-query.v2"
ICOURSE_INTENT_OPERATIONS = {
    "icourse.course.search": "course",
    "icourse.review.search": "review",
    "icourse.teacher.search": "teacher",
    "icourse.ranking.read": "ranking",
    "icourse.stats.read": "stats",
}
_ICOURSE_DEFAULT_LIMIT = 20


class EntityQueryToolPlanner:
    """Turn model-extracted entities into one schema-bound read query.

    This adapter deliberately emits one step for a candidate whose only required
    input is `query`. Standard iCourse intents select the high-level public query
    operation; the existing deterministic validator still owns membership and
    argument validity.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        ignored_entity_terms: frozenset[str] = frozenset(),
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        revision: ComponentRevision | None = None,
    ) -> None:
        if not isinstance(registry, CapabilityRegistry):
            raise TypeError("registry does not implement CapabilityRegistry")
        ignored = frozenset(_normalize_term(value) for value in ignored_entity_terms)
        if "" in ignored:
            raise ValueError("ignored_entity_terms must contain non-empty strings")
        self._registry = registry
        self._ignored_entity_terms = ignored
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._revision = revision or ComponentRevision(
            "astrbot.entity-query-tool-planner",
            "1.0.0",
            "single-step-v1",
            DigestString(
                str(
                    canonical_digest(
                        {"planner": "entity-query-single-step"},
                        domain="astrbot:tool-planner-artifact:v1",
                    )
                )
            ),
        )

    async def plan(
        self,
        request: ToolPlanningRequest,
        *,
        call: PortCallContext,
    ) -> ToolPlan:
        if not isinstance(request, ToolPlanningRequest):
            raise validation_error("invalid_tool_planning_request")
        self._validate_call(call)
        catalog = self._registry.snapshot_by_id(
            request.retrieval.catalog_snapshot_id,
            expected_digest=request.retrieval.catalog_digest,
        )
        term = _primary_query_term(request, self._ignored_entity_terms)
        operation = _icourse_operation(request.query.intent_ids)
        candidates = request.retrieval.candidates
        if operation is not None:
            public_query_candidates = tuple(
                item
                for item in candidates
                if item.capability_id == ICOURSE_PUBLIC_QUERY_CAPABILITY_ID
            )
            legacy_course_candidates = (
                tuple(
                    item
                    for item in candidates
                    if item.capability_id != ICOURSE_PUBLIC_QUERY_CAPABILITY_ID
                )
                if operation == "course"
                else ()
            )
            candidates = public_query_candidates + legacy_course_candidates

        selected = None
        arguments: Mapping[str, JsonValue] | None = None
        for candidate in candidates:
            is_icourse_public_query = (
                candidate.capability_id == ICOURSE_PUBLIC_QUERY_CAPABILITY_ID
            )
            if is_icourse_public_query and operation is None:
                continue
            schema = self._registry.get_schema(catalog, candidate.input_schema)
            projected = _query_arguments(
                schema.document,
                term,
                goal=(
                    request.query.natural_language_goal
                    if is_icourse_public_query
                    else None
                ),
                operation=operation if is_icourse_public_query else None,
                limit=_ICOURSE_DEFAULT_LIMIT if is_icourse_public_query else None,
            )
            if projected is not None:
                selected = candidate
                arguments = projected
                break
        if selected is None or arguments is None:
            raise validation_error("tool_planning_query_candidate_unavailable")

        operation_suffix = str(
            canonical_digest(
                {
                    "query_digest": request.query.query_digest,
                    "capability_id": selected.capability_id,
                    "definition_digest": selected.definition_digest,
                    "arguments": arguments,
                },
                domain="capability.logical-operation:v1",
            )
        ).rsplit(":", maxsplit=1)[1][:32]
        step = ToolStep(
            schema_version=1,
            step_id=f"step:{operation_suffix}",
            logical_operation_id=f"operation:{operation_suffix}",
            capability_id=selected.capability_id,
            definition_digest=selected.definition_digest,
            arguments=ArgumentTemplate(1, arguments, ()),
            purpose="answer_with_approved_public_query",
            depends_on=(),
            expected_output_schema=selected.output_schema,
        )
        values = {
            "schema_version": 1,
            "plan_id": f"tool-plan:{self._new_id()}",
            "query_digest": request.query.query_digest,
            "retrieval_result_digest": request.retrieval.result_digest,
            "steps": (step,),
            "completion_criteria": (TOOL_COMPLETION_ALL_STEPS,),
            "planner_revision": self._revision,
        }
        return ToolPlan(plan_digest=tool_plan_digest(values), **values)

    def _validate_call(self, call: PortCallContext) -> None:
        if not isinstance(call, PortCallContext):
            raise validation_error("invalid_tool_planning_call")
        now = self._clock()
        if call.cancellation.is_cancelled or call.deadline <= now:
            raise validation_error("tool_planning_call_inactive")

    def _new_id(self) -> str:
        value = self._id_factory()
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(character.isspace() for character in value)
        ):
            raise validation_error("invalid_tool_planner_id")
        return value


def _primary_query_term(
    request: ToolPlanningRequest,
    ignored_entity_terms: frozenset[str],
) -> str:
    for value in request.query.entity_terms:
        if value.strip() and _normalize_term(value) not in ignored_entity_terms:
            return value.strip()
    goal = request.query.natural_language_goal.strip()
    if not goal:
        raise validation_error("tool_planning_query_term_missing")
    return goal


def _query_arguments(
    document: Mapping[str, JsonValue],
    term: str,
    *,
    goal: str | None = None,
    operation: str | None = None,
    limit: int | None = None,
) -> Mapping[str, JsonValue] | None:
    properties = document.get("properties")
    required = document.get("required")
    if not isinstance(properties, Mapping) or not isinstance(required, (list, tuple)):
        return None
    if "query" not in properties or set(required) != {"query"}:
        return None
    arguments: dict[str, JsonValue] = {"query": term}
    optional = {"goal": goal, "operation": operation, "limit": limit}
    for name, value in optional.items():
        if name in properties and value is not None:
            arguments[name] = value
    return arguments


def supports_entity_query_schema(document: Mapping[str, JsonValue]) -> bool:
    return (
        _query_arguments(
            document,
            "query",
            goal="query",
            operation="course",
            limit=_ICOURSE_DEFAULT_LIMIT,
        )
        is not None
    )


def _icourse_operation(intent_ids: tuple[str, ...]) -> str | None:
    for intent_id in intent_ids:
        operation = ICOURSE_INTENT_OPERATIONS.get(intent_id)
        if operation is not None:
            return operation
    if any(intent_id.startswith("icourse.") for intent_id in intent_ids):
        return "course"
    return None


def _normalize_term(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("entity term must be str")
    return "".join(value.split()).casefold()


__all__ = ["EntityQueryToolPlanner", "supports_entity_query_schema"]
