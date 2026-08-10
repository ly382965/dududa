from __future__ import annotations

import unittest
from dataclasses import replace

from dududa.capabilities import (
    DeterministicToolResultValidator,
    ToolObservation,
    ToolPlanValidationResult,
    ToolValidationRequest,
    ValidationAction,
    tool_observation_digest,
    tool_plan_validation_result_digest,
    tool_validation_request_digest,
)
from dududa.ports.capabilities import ToolResultValidator

from tests.unit.capabilities import test_executor as executor_fixtures
from tests.unit.capabilities.test_planning import SimpleSchemaValidator


def _rebuilt_observation(
    observation: ToolObservation,
    **changes,
) -> ToolObservation:
    values = {
        name: getattr(observation, name)
        for name in observation.__dataclass_fields__
        if name != "observation_digest"
    }
    values.update(changes)
    return ToolObservation(
        observation_digest=tool_observation_digest(values),
        **values,
    )


class ToolResultValidatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = executor_fixtures.GovernedToolExecutorTests(
            methodName="test_success_reauthorizes_audits_and_calls_provider_once"
        )
        await self.fixture.asyncSetUp()
        self.validator = DeterministicToolResultValidator(
            self.fixture.registry,
            SimpleSchemaValidator(),
            self.fixture.plan_validator,
            clock=lambda: self.fixture.catalog.acquired_at,
        )
        self.assertIsInstance(self.validator, ToolResultValidator)
        self.output_schema = self.fixture.registry.get_schema(
            self.fixture.catalog,
            self.fixture.definition.output_schema,
        )

    def _request(
        self,
        observations,
        *,
        output_schemas=None,
        maximum_attempts: int = 4,
    ) -> ToolValidationRequest:
        values = {
            "schema_version": 1,
            "retrieval": self.fixture.retrieval,
            "plan": self.fixture.plan,
            "plan_validation_request": self.fixture.plan_validation_request,
            "plan_validation_result": self.fixture.plan_validation_result,
            "observations": tuple(observations),
            "output_schemas": tuple(output_schemas or (self.output_schema,)),
            "maximum_attempts": maximum_attempts,
        }
        return ToolValidationRequest(
            request_digest=tool_validation_request_digest(values),
            **values,
        )

    async def test_valid_untrusted_result_finishes_without_interpreting_text(
        self,
    ) -> None:
        observation = await self.fixture.executor.execute(
            self.fixture._request(),
            call=executor_fixtures.execution_call(),
        )
        result = await self.validator.validate(
            self._request((observation,)),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(result.action, ValidationAction.FINISH)
        self.assertEqual(result.accepted_observations, (observation,))
        self.assertEqual(len(self.fixture.plan.steps), 1)
        self.assertIn("untrusted provider value", repr(observation.data))

    async def test_empty_run_continues_to_one_ready_step(self) -> None:
        result = await self.validator.validate(
            self._request(()),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(result.action, ValidationAction.CONTINUE)
        self.assertEqual(result.accepted_observations, ())

    async def test_known_retryable_failure_retries_within_attempt_budget(self) -> None:
        self.fixture.provider.mode = "failed"
        failed = await self.fixture.executor.execute(
            self.fixture._request(),
            call=executor_fixtures.execution_call(),
        )
        result = await self.validator.validate(
            self._request((failed,), maximum_attempts=2),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(result.action, ValidationAction.RETRY)
        self.assertEqual(result.retry_step_id, failed.step_id)

        exhausted = await self.validator.validate(
            self._request((failed,), maximum_attempts=1),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(exhausted.action, ValidationAction.ABORT)

    async def test_unknown_truncated_empty_and_schema_invalid_abort(self) -> None:
        cases = []
        for mode in ("unknown", "truncated", "empty"):
            self.fixture.provider.mode = mode
            ledger = self.fixture.ledger.__class__(
                clock=lambda: self.fixture.catalog.acquired_at
            )
            executor = self.fixture._executor(invocation_ledger=ledger)
            cases.append(
                await executor.execute(
                    self.fixture._request(invocation_id=f"invocation-{mode}"),
                    call=executor_fixtures.execution_call(),
                )
            )
        self.fixture.provider.mode = "success"
        valid = await self.fixture.executor.execute(
            self.fixture._request(invocation_id="invocation-valid"),
            call=executor_fixtures.execution_call(),
        )
        invalid_schema = _rebuilt_observation(
            valid,
            data={"unexpected": "value"},
        )
        cases.append(invalid_schema)
        for observation in cases:
            with self.subTest(status=observation.status, data=observation.data):
                result = await self.validator.validate(
                    self._request((observation,)),
                    call=executor_fixtures.execution_call(),
                )
                self.assertIs(result.action, ValidationAction.ABORT)
                self.assertEqual(result.accepted_observations, ())

    async def test_foreign_policy_attempt_and_schema_set_fail_closed(self) -> None:
        observation = await self.fixture.executor.execute(
            self.fixture._request(),
            call=executor_fixtures.execution_call(),
        )
        input_schema = self.fixture.registry.get_schema(
            self.fixture.catalog,
            self.fixture.definition.input_schema,
        )
        cases = (
            self._request(
                (_rebuilt_observation(observation, policy_revision="policy-v2"),)
            ),
            self._request((_rebuilt_observation(observation, attempt=2),)),
            self._request(
                (observation,),
                output_schemas=(self.output_schema, input_schema),
            ),
        )
        for request in cases:
            result = await self.validator.validate(
                request,
                call=executor_fixtures.execution_call(),
            )
            self.assertIs(result.action, ValidationAction.ABORT)
            self.assertEqual(result.accepted_observations, ())

    async def test_validator_rejects_forged_plan_result(self) -> None:
        observation = await self.fixture.executor.execute(
            self.fixture._request(),
            call=executor_fixtures.execution_call(),
        )
        forged_values = {
            "schema_version": 1,
            "request_digest": self.fixture.plan_validation_request.request_digest,
            "plan_digest": self.fixture.plan.plan_digest,
            "valid": True,
            "reason_codes": ("plan_valid",),
            "validator_revision": replace(
                self.fixture.plan_validation_result.validator_revision,
                config_revision="forged",
            ),
        }
        forged = ToolPlanValidationResult(
            result_digest=tool_plan_validation_result_digest(forged_values),
            **forged_values,
        )
        values = {
            "schema_version": 1,
            "retrieval": self.fixture.retrieval,
            "plan": self.fixture.plan,
            "plan_validation_request": self.fixture.plan_validation_request,
            "plan_validation_result": forged,
            "observations": (observation,),
            "output_schemas": (self.output_schema,),
            "maximum_attempts": 4,
        }
        request = ToolValidationRequest(
            request_digest=tool_validation_request_digest(values),
            **values,
        )
        result = await self.validator.validate(
            request,
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(result.action, ValidationAction.ABORT)


if __name__ == "__main__":
    unittest.main()
