from __future__ import annotations

import itertools
import unittest
from collections.abc import Mapping

from dududa.capabilities.contracts import (
    ArgumentBindingRequest,
    ArgumentTemplate,
    ObservationBinding,
    ToolPlan,
    ToolPlanningRequest,
    ToolPlanValidationRequest,
    ToolStep,
)
from dududa.capabilities.digests import (
    argument_binding_request_digest,
    tool_plan_digest,
    tool_plan_validation_request_digest,
    tool_planning_request_digest,
)
from dududa.capabilities.planning import (
    DeterministicArgumentBinder,
    DeterministicToolPlanner,
    DeterministicToolPlanValidator,
)
from dududa.capabilities.retrieval import DeterministicCapabilityRetriever
from dududa.domain.primitives import freeze_json
from dududa.errors import DududaError, validation_error

from tests.unit.capabilities.test_contracts import observation
from tests.unit.capabilities.test_registry import catalog_fixture
from tests.unit.capabilities.test_retrieval import (
    StaticHealthRegistry,
    authorization_for,
    catalog_for,
    health_for,
    request_for,
    retrieval_call,
)


class SimpleSchemaValidator:
    def check_schema(self, document) -> None:
        if not isinstance(document.document, Mapping):
            raise validation_error("invalid_test_schema")

    def validate(self, value, document):
        schema = document.document
        if schema.get("type") == "object":
            if not isinstance(value, Mapping):
                raise validation_error("test_schema_expected_object")
            properties = schema.get("properties", {})
            required = schema.get("required", ())
            if any(key not in value for key in required):
                raise validation_error("test_schema_required_missing")
            if schema.get("additionalProperties") is False and any(
                key not in properties for key in value
            ):
                raise validation_error("test_schema_extra_property")
            for key, item in value.items():
                expected = properties.get(key, {}).get("type")
                if expected == "string" and not isinstance(item, str):
                    raise validation_error("test_schema_expected_string")
                if expected == "integer" and type(item) is not int:
                    raise validation_error("test_schema_expected_integer")
        return freeze_json(value)


def planning_request(query, retrieval, *, remaining_attempts: int = 4):
    values = {
        "schema_version": 1,
        "query": query,
        "retrieval": retrieval,
        "prior_observations": (),
        "remaining_attempts": remaining_attempts,
    }
    return ToolPlanningRequest(
        request_digest=tool_planning_request_digest(values),
        **values,
    )


def validation_request(
    query,
    retrieval,
    plan,
    *,
    maximum_attempts: int = 4,
    maximum_cost_units: int | None = None,
):
    values = {
        "schema_version": 1,
        "query": query,
        "retrieval": retrieval,
        "plan": plan,
        "maximum_attempts": maximum_attempts,
        "maximum_cost_units": maximum_cost_units,
    }
    return ToolPlanValidationRequest(
        request_digest=tool_plan_validation_request_digest(values),
        **values,
    )


def rebuilt_plan(plan: ToolPlan, steps: tuple[ToolStep, ...]) -> ToolPlan:
    values = {
        "schema_version": plan.schema_version,
        "plan_id": plan.plan_id,
        "query_digest": plan.query_digest,
        "retrieval_result_digest": plan.retrieval_result_digest,
        "steps": steps,
        "completion_criteria": plan.completion_criteria,
        "planner_revision": plan.planner_revision,
    }
    return ToolPlan(plan_digest=tool_plan_digest(values), **values)


def binding_request(plan, step, observations, input_schema, *, fixed=None):
    values = {
        "schema_version": 1,
        "plan": plan,
        "step": step,
        "accepted_observations": tuple(observations),
        "input_schema": input_schema,
        "fixed_arguments": fixed or {},
    }
    return ArgumentBindingRequest(
        request_digest=argument_binding_request_digest(values),
        **values,
    )


class CapabilityPlanningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        _, self.definition, _ = catalog_fixture()
        self.registry, self.catalog = catalog_for((self.definition,))
        authorization = authorization_for((self.definition,))
        retriever = DeterministicCapabilityRetriever(
            self.registry,
            StaticHealthRegistry(health_for(self.catalog)),
            authorization,
            authorization,
            clock=lambda: self.catalog.acquired_at,
        )
        self.retrieval_request = request_for(self.definition)
        self.retrieval = await retriever.retrieve(
            self.retrieval_request,
            call=retrieval_call(),
        )
        identifiers = itertools.count()
        self.planner = DeterministicToolPlanner(
            {self.definition.capability_id: {"query": "database"}},
            clock=lambda: self.catalog.acquired_at,
            id_factory=lambda: f"plan-{next(identifiers)}",
        )
        self.schema_validator = SimpleSchemaValidator()
        self.validator = DeterministicToolPlanValidator(
            self.registry,
            self.schema_validator,
        )
        self.plan_request = planning_request(
            self.retrieval_request.query,
            self.retrieval,
        )

    async def test_reference_planner_keeps_logical_operation_stable(self) -> None:
        first = await self.planner.plan(self.plan_request, call=retrieval_call())
        second = await self.planner.plan(self.plan_request, call=retrieval_call())
        self.assertNotEqual(first.plan_id, second.plan_id)
        self.assertEqual(
            first.steps[0].logical_operation_id,
            second.steps[0].logical_operation_id,
        )
        self.assertEqual(first.steps[0].arguments.literal_template["query"], "database")
        result = self.validator.validate(
            validation_request(
                self.retrieval_request.query,
                self.retrieval,
                first,
                maximum_cost_units=1,
            )
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.reason_codes, ("plan_valid",))

    async def test_candidate_dependency_step_and_cost_gates_are_fail_closed(
        self,
    ) -> None:
        plan = await self.planner.plan(self.plan_request, call=retrieval_call())
        base = plan.steps[0]
        unknown = ToolStep(
            schema_version=1,
            step_id="unknown-step",
            logical_operation_id="unknown-operation",
            capability_id="fixture.unknown.read.v1",
            definition_digest=base.definition_digest,
            arguments=base.arguments,
            purpose=base.purpose,
            depends_on=(),
            expected_output_schema=base.expected_output_schema,
        )
        extra_steps = tuple(
            ToolStep(
                schema_version=1,
                step_id=f"step-{index}",
                logical_operation_id=f"operation-{index}",
                capability_id=base.capability_id,
                definition_digest=base.definition_digest,
                arguments=base.arguments,
                purpose=base.purpose,
                depends_on=(),
                expected_output_schema=base.expected_output_schema,
            )
            for index in range(5)
        )
        second = ToolStep(
            schema_version=1,
            step_id="second",
            logical_operation_id="second-operation",
            capability_id=base.capability_id,
            definition_digest=base.definition_digest,
            arguments=base.arguments,
            purpose=base.purpose,
            depends_on=(),
            expected_output_schema=base.expected_output_schema,
        )
        future_dependency = ToolStep(
            schema_version=1,
            step_id="first",
            logical_operation_id="first-operation",
            capability_id=base.capability_id,
            definition_digest=base.definition_digest,
            arguments=base.arguments,
            purpose=base.purpose,
            depends_on=("second",),
            expected_output_schema=base.expected_output_schema,
        )
        cases = (
            (
                "candidate",
                rebuilt_plan(plan, (unknown,)),
                4,
                None,
                "plan_candidate_binding_invalid",
            ),
            (
                "step-limit",
                rebuilt_plan(plan, extra_steps),
                4,
                None,
                "plan_step_limit_exceeded",
            ),
            (
                "dependency",
                rebuilt_plan(plan, (future_dependency, second)),
                4,
                None,
                "plan_dependency_invalid",
            ),
            (
                "cost",
                rebuilt_plan(plan, (base, second)),
                4,
                1,
                "plan_cost_limit_exceeded",
            ),
        )
        for name, proposed, maximum_attempts, maximum_cost, reason in cases:
            with self.subTest(name=name):
                result = self.validator.validate(
                    validation_request(
                        self.retrieval_request.query,
                        self.retrieval,
                        proposed,
                        maximum_attempts=maximum_attempts,
                        maximum_cost_units=maximum_cost,
                    )
                )
                self.assertFalse(result.valid)
                self.assertEqual(result.reason_codes, (reason,))

    async def test_binding_plan_requires_direct_earlier_dependency_and_schema_paths(
        self,
    ) -> None:
        plan = await self.planner.plan(self.plan_request, call=retrieval_call())
        source = plan.steps[0]
        target = ToolStep(
            schema_version=1,
            step_id="target",
            logical_operation_id="target-operation",
            capability_id=source.capability_id,
            definition_digest=source.definition_digest,
            arguments=ArgumentTemplate(
                1,
                {},
                (ObservationBinding(1, source.step_id, "/query", "/query"),),
            ),
            purpose="bind_accepted_result",
            depends_on=(source.step_id,),
            expected_output_schema=source.expected_output_schema,
        )
        valid = rebuilt_plan(plan, (source, target))
        result = self.validator.validate(
            validation_request(
                self.retrieval_request.query,
                self.retrieval,
                valid,
                maximum_cost_units=2,
            )
        )
        self.assertTrue(result.valid)

        invalid_target = ToolStep(
            schema_version=1,
            step_id=target.step_id,
            logical_operation_id=target.logical_operation_id,
            capability_id=target.capability_id,
            definition_digest=target.definition_digest,
            arguments=ArgumentTemplate(
                1,
                {},
                (ObservationBinding(1, source.step_id, "/query", "/hidden"),),
            ),
            purpose=target.purpose,
            depends_on=target.depends_on,
            expected_output_schema=target.expected_output_schema,
        )
        invalid = self.validator.validate(
            validation_request(
                self.retrieval_request.query,
                self.retrieval,
                rebuilt_plan(plan, (source, invalid_target)),
            )
        )
        self.assertFalse(invalid.valid)
        self.assertEqual(invalid.reason_codes, ("plan_binding_target_invalid",))

    async def test_binder_reads_only_declared_success_data_and_validates_final_schema(
        self,
    ) -> None:
        plan = await self.planner.plan(self.plan_request, call=retrieval_call())
        source = plan.steps[0]
        target = ToolStep(
            schema_version=1,
            step_id="bind-target",
            logical_operation_id="bind-operation",
            capability_id=source.capability_id,
            definition_digest=source.definition_digest,
            arguments=ArgumentTemplate(
                1,
                {},
                (
                    ObservationBinding(
                        1,
                        source.step_id,
                        "/items/0/text",
                        "/query",
                    ),
                ),
            ),
            purpose="bind_untrusted_data",
            depends_on=(source.step_id,),
            expected_output_schema=source.expected_output_schema,
        )
        binding_plan = rebuilt_plan(plan, (source, target))
        source_observation = observation(self.definition, binding_plan)
        input_schema = self.registry.get_schema(
            self.catalog,
            self.definition.input_schema,
        )
        binder = DeterministicArgumentBinder(self.schema_validator)
        result = binder.bind(
            binding_request(
                binding_plan,
                target,
                (source_observation,),
                input_schema,
            )
        )
        self.assertEqual(result.resolved_arguments["query"], "untrusted text")
        self.assertEqual(
            result.source_invocation_ids,
            (source_observation.invocation_id,),
        )
        foreign_observation = observation(
            self.definition,
            rebuilt_plan(plan, (source,)),
        )
        with self.assertRaises(DududaError):
            binding_request(
                binding_plan,
                target,
                (foreign_observation,),
                input_schema,
            )

        fixed_override = ToolStep(
            schema_version=1,
            step_id="fixed-target",
            logical_operation_id="fixed-operation",
            capability_id=source.capability_id,
            definition_digest=source.definition_digest,
            arguments=ArgumentTemplate(1, {"query": "model-value"}, ()),
            purpose="attempt_fixed_override",
            depends_on=(),
            expected_output_schema=source.expected_output_schema,
        )
        with self.assertRaises(DududaError):
            fixed_plan = rebuilt_plan(plan, (fixed_override,))
            binder.bind(
                binding_request(
                    fixed_plan,
                    fixed_override,
                    (),
                    input_schema,
                    fixed={"query": "configured-value"},
                )
            )

        invalid_type = ToolStep(
            schema_version=1,
            step_id="invalid-type",
            logical_operation_id="invalid-type-operation",
            capability_id=source.capability_id,
            definition_digest=source.definition_digest,
            arguments=ArgumentTemplate(
                1,
                {},
                (
                    ObservationBinding(
                        1,
                        source.step_id,
                        "/items/0/course_id",
                        "/query",
                    ),
                ),
            ),
            purpose="bind_wrong_type",
            depends_on=(source.step_id,),
            expected_output_schema=source.expected_output_schema,
        )
        invalid_plan = rebuilt_plan(plan, (source, invalid_type))
        invalid_observation = observation(self.definition, invalid_plan)
        with self.assertRaises(DududaError):
            binder.bind(
                binding_request(
                    invalid_plan,
                    invalid_type,
                    (invalid_observation,),
                    input_schema,
                )
            )


if __name__ == "__main__":
    unittest.main()
