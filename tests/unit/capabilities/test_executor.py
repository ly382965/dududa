from __future__ import annotations

import asyncio
import itertools
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from dududa.capabilities import (
    CapabilityExecutionContext,
    CapabilityHealthStatus,
    CapabilityResult,
    GovernedToolExecutor,
    InMemoryToolInvocationLedger,
    ToolError,
    ToolExecutionRequest,
    ToolExecutionStatus,
    ToolPlanValidationResult,
    capability_result_digest,
    tool_execution_request_digest,
    tool_idempotency_key,
    tool_plan_validation_result_digest,
)
from dududa.capabilities.planning import (
    DeterministicToolPlanner,
    DeterministicToolPlanValidator,
)
from dududa.capabilities.registry import (
    InMemoryCapabilityProviderRegistry,
    InMemoryCapabilityRegistry,
)
from dududa.capabilities.retrieval import DeterministicCapabilityRetriever
from dududa.domain.primitives import (
    PrivacyLevel,
    ResourceUsage,
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError, ErrorCategory, ErrorInfo
from dududa.ports.capabilities import ToolExecutor
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
)
from dududa.security.audit import InMemoryAuditSink
from dududa.security.authorization import (
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.digests import usage_digest
from dududa.security.limits import InMemoryBudgetLedger, InMemoryInteractionLimiter
from dududa.security.models import AuditReceipt

from tests.unit.capabilities.test_contracts import NOW
from tests.unit.capabilities.test_planning import (
    planning_request,
    validation_request,
)
from tests.unit.capabilities.test_registry import SchemaValidator, catalog_fixture
from tests.unit.capabilities.test_retrieval import (
    StaticHealthRegistry,
    authorization_for,
    health_for,
    request_for,
)


class RecordingProvider:
    def __init__(self, descriptor) -> None:
        self._descriptor = descriptor
        self.mode = "success"
        self.sequence = []
        self.requests = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def descriptor(self):
        return self._descriptor

    async def health(self, *, call):
        raise NotImplementedError

    async def invoke(self, request, *, call):
        self.requests.append(request)
        self.started.set()
        mode = self.sequence.pop(0) if self.sequence else self.mode
        if mode == "blocked":
            await self.release.wait()
        if mode == "raise":
            raise RuntimeError("credential=private /srv/provider/command")
        status = {
            "failed": ToolExecutionStatus.FAILED,
            "unknown": ToolExecutionStatus.UNKNOWN,
        }.get(mode, ToolExecutionStatus.SUCCEEDED)
        data = {"query": "untrusted provider value"}
        if mode == "empty":
            data = {}
        failure = None
        if status is not ToolExecutionStatus.SUCCEEDED:
            data = None
            unknown = status is ToolExecutionStatus.UNKNOWN
            failure = ToolError(
                1,
                ErrorInfo(
                    1,
                    "fixture_provider_unknown"
                    if unknown
                    else "fixture_provider_failed",
                    ErrorCategory.EXTERNAL,
                    retryable=not unknown,
                    outcome_unknown=unknown,
                    public_message_key="service.unavailable",
                    reason_codes=("fixture",),
                ),
                None,
                {"ignored": "safe fixture detail"},
            )
        values = {
            "schema_version": 1,
            "provider_invocation_digest": request.invocation_digest,
            "invocation_id": request.invocation_id,
            "capability_id": request.capability_id,
            "definition_digest": request.definition_digest,
            "provider": request.provider,
            "status": status,
            "data": data,
            "error": failure,
            "source_refs": ("fixture-cache",),
            "sensitivity": (
                PrivacyLevel.RESTRICTED
                if mode == "oversensitive"
                else PrivacyLevel.PUBLIC
            ),
            "usage": ResourceUsage(1, cost_units=Decimal(1)),
            "observed_at": NOW,
            "truncated": mode == "truncated",
            "untrusted": True,
        }
        if mode == "wrong-binding":
            values["provider_invocation_digest"] = tool_idempotency_key(
                run_id="wrong",
                logical_operation_id="wrong",
                capability_id=request.capability_id,
                definition_digest=request.definition_digest,
                normalized_arguments={},
            )
        return CapabilityResult(
            result_digest=capability_result_digest(values),
            **values,
        )

    async def close(self) -> None:
        return None


class ProgrammableAuditSink:
    def __init__(self, *, fail_on: int | None = None) -> None:
        self.fail_on = fail_on
        self.events = []

    async def write(self, event, *, call):
        self.events.append(event)
        if len(self.events) == self.fail_on:
            raise RuntimeError("secret=/private/audit/path")
        return AuditReceipt(1, event.event_id, event.event_digest, True, "audit-v1")


class FailingSettlementBudget:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    async def reserve(self, request, *, call):
        return await self.delegate.reserve(request, call=call)

    async def settle(self, lease, usage, *, call):
        raise RuntimeError("credential=/private/budget/state")

    async def release(self, lease, *, call):
        return await self.delegate.release(lease, call=call)


class FailingCompletionLedger(InMemoryToolInvocationLedger):
    async def complete(self, claim, observation, *, call):
        raise RuntimeError("secret=/private/ledger/state")


class ForgedInteractionLeaseLimiter:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.release_calls = 0

    async def reserve(self, request, *, call):
        lease = await self.delegate.reserve(request, call=call)
        return replace(lease, actor_digest=lease.scope_digest)

    async def commit(self, lease, *, call):
        return await self.delegate.commit(lease, call=call)

    async def release(self, lease, *, call):
        self.release_calls += 1
        return await self.delegate.release(lease, call=call)


class ForgedBudgetLeaseLedger:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.release_calls = 0

    async def reserve(self, request, *, call):
        lease = await self.delegate.reserve(request, call=call)
        return replace(lease, resource_digest=lease.request_digest)

    async def settle(self, lease, usage, *, call):
        return await self.delegate.settle(lease, usage, call=call)

    async def release(self, lease, *, call):
        self.release_calls += 1
        return await self.delegate.release(lease, call=call)


class MissingCommitReceiptLimiter:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    async def reserve(self, request, *, call):
        return await self.delegate.reserve(request, call=call)

    async def commit(self, lease, *, call):
        await self.delegate.commit(lease, call=call)

    async def release(self, lease, *, call):
        return await self.delegate.release(lease, call=call)


class ForgedSettlementReceiptBudget:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    async def reserve(self, request, *, call):
        return await self.delegate.reserve(request, call=call)

    async def settle(self, lease, usage, *, call):
        receipt = await self.delegate.settle(lease, usage, call=call)
        return replace(receipt, usage_digest=lease.request_digest)

    async def release(self, lease, *, call):
        return await self.delegate.release(lease, call=call)


def execution_call(
    *,
    cancellation=None,
    tool_steps: int = 8,
    cost_units: Decimal = Decimal(100),
) -> PortCallContext:
    return PortCallContext(
        run_id="capability-run-v1",
        trace=TraceContext("capability-trace-v1"),
        deadline=NOW + timedelta(minutes=1),
        cancellation=cancellation or NeverCancelled(),
        budget=RuntimeBudget(0, tool_steps, 8, 0, 0, cost_units),
        policy_snapshot_id="policy-v1",
    )


class GovernedToolExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.catalog, self.definition, descriptor = catalog_fixture()
        self.schema_validator = SchemaValidator()
        self.provider = RecordingProvider(descriptor)
        self.provider_registry = InMemoryCapabilityProviderRegistry((self.provider,))
        self.registry = InMemoryCapabilityRegistry(
            self.catalog,
            schema_validator=self.schema_validator,
            provider_registry=self.provider_registry,
            clock=lambda: NOW,
        )
        self.health = StaticHealthRegistry(health_for(self.catalog))
        self.authorization = authorization_for((self.definition,))
        retriever = DeterministicCapabilityRetriever(
            self.registry,
            self.health,
            self.authorization,
            self.authorization,
            clock=lambda: NOW,
        )
        self.retrieval_request = request_for(self.definition)
        self.retrieval = await retriever.retrieve(
            self.retrieval_request,
            call=execution_call(),
        )
        identifiers = itertools.count()
        planner = DeterministicToolPlanner(
            {self.definition.capability_id: {"query": "database"}},
            clock=lambda: NOW,
            id_factory=lambda: f"plan-{next(identifiers)}",
        )
        self.plan = await planner.plan(
            planning_request(self.retrieval_request.query, self.retrieval),
            call=execution_call(),
        )
        self.plan_validator = DeterministicToolPlanValidator(
            self.registry,
            self.schema_validator,
        )
        self.plan_validation_request = validation_request(
            self.retrieval_request.query,
            self.retrieval,
            self.plan,
            maximum_cost_units=10,
        )
        self.plan_validation_result = self.plan_validator.validate(
            self.plan_validation_request
        )
        self.authorization.requests.clear()
        self.limiter = InMemoryInteractionLimiter(
            {"capability.invoke": 100},
            policy_revision="limit-v1",
            clock=lambda: NOW,
        )
        self.budget = InMemoryBudgetLedger(
            ResourceUsage(
                1,
                tool_steps=100,
                retries=100,
                cost_units=Decimal(1_000),
            ),
            policy_revision="budget-v1",
            clock=lambda: NOW,
        )
        self.audit = InMemoryAuditSink()
        self.ledger = InMemoryToolInvocationLedger(clock=lambda: NOW)
        self.executor = self._executor()
        self.assertIsInstance(self.executor, ToolExecutor)

    def _executor(self, **changes) -> GovernedToolExecutor:
        values = {
            "registry": self.registry,
            "provider_registry": self.provider_registry,
            "health_registry": self.health,
            "schema_validator": self.schema_validator,
            "plan_validator": self.plan_validator,
            "authorization": self.authorization,
            "authorization_verifier": self.authorization,
            "limiter": self.limiter,
            "budget_ledger": self.budget,
            "audit_sink": self.audit,
            "invocation_ledger": self.ledger,
            "clock": lambda: NOW,
        }
        values.update(changes)
        return GovernedToolExecutor(**values)

    def _request(
        self,
        *,
        attempt: int = 1,
        invocation_id: str = "invocation-v1",
        validation_result: ToolPlanValidationResult | None = None,
        key: str | None = None,
    ) -> ToolExecutionRequest:
        step = self.plan.steps[0]
        arguments = {"query": "database", "limit": 20}
        idempotency_key = key or tool_idempotency_key(
            run_id=execution_call().run_id,
            logical_operation_id=step.logical_operation_id,
            capability_id=step.capability_id,
            definition_digest=step.definition_digest,
            normalized_arguments=arguments,
        )
        values = {
            "schema_version": 1,
            "invocation_id": invocation_id,
            "plan_id": self.plan.plan_id,
            "plan_digest": self.plan.plan_digest,
            "plan_validation_request": self.plan_validation_request,
            "plan_validation_result": validation_result or self.plan_validation_result,
            "step_id": step.step_id,
            "logical_operation_id": step.logical_operation_id,
            "capability_id": step.capability_id,
            "definition_digest": step.definition_digest,
            "catalog_snapshot_id": self.catalog.snapshot_id,
            "catalog_digest": self.catalog.catalog_digest,
            "provider": self.definition.provider,
            "mapping_digest": self.catalog.mcp_mappings[0].mapping_digest,
            "resolved_arguments": arguments,
            "source_invocation_ids": (),
            "idempotency_key": idempotency_key,
            "attempt": attempt,
            "context": CapabilityExecutionContext(
                1,
                self.retrieval_request.actor,
                self.retrieval_request.conversation_scope,
                self.retrieval_request.data_classification,
            ),
        }
        return ToolExecutionRequest(
            request_digest=tool_execution_request_digest(values),
            **values,
        )

    async def test_success_reauthorizes_audits_and_calls_provider_once(self) -> None:
        observation = await self.executor.execute(
            self._request(),
            call=execution_call(),
        )
        self.assertIs(observation.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(observation.data["query"], "untrusted provider value")
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(len(self.authorization.requests), 1)
        self.assertEqual(len(self.audit.events), 2)
        self.assertTrue(
            all(
                "arguments" not in event.sanitized_detail for event in self.audit.events
            )
        )

    async def test_concurrent_duplicate_is_single_flight(self) -> None:
        self.provider.mode = "blocked"
        request = self._request()
        first = asyncio.create_task(
            self.executor.execute(request, call=execution_call())
        )
        await self.provider.started.wait()
        duplicate = asyncio.create_task(
            self.executor.execute(request, call=execution_call())
        )
        await asyncio.sleep(0)
        self.provider.release.set()
        first_result, duplicate_result = await asyncio.gather(first, duplicate)
        self.assertEqual(first_result, duplicate_result)
        self.assertEqual(len(self.provider.requests), 1)

    async def test_plan_idempotency_health_and_mapping_drift_fail_before_call(
        self,
    ) -> None:
        forged_values = {
            "schema_version": 1,
            "request_digest": self.plan_validation_request.request_digest,
            "plan_digest": self.plan.plan_digest,
            "valid": True,
            "reason_codes": ("plan_valid",),
            "validator_revision": replace(
                self.plan_validation_result.validator_revision,
                config_revision="forged",
            ),
        }
        forged = ToolPlanValidationResult(
            result_digest=tool_plan_validation_result_digest(forged_values),
            **forged_values,
        )
        cases = (
            self._request(validation_result=forged),
            self._request(key="wrong-business-key"),
            replace(
                self._request(),
                mapping_digest=self.catalog.mcp_mappings[
                    0
                ].expected_input_schema_digest,
                request_digest=tool_execution_request_digest(
                    {
                        **{
                            name: getattr(self._request(), name)
                            for name in self._request().__dataclass_fields__
                            if name != "request_digest"
                        },
                        "mapping_digest": self.catalog.mcp_mappings[
                            0
                        ].expected_input_schema_digest,
                    }
                ),
            ),
        )
        for item in cases:
            with (
                self.subTest(code=item.idempotency_key),
                self.assertRaises(DududaError),
            ):
                await self.executor.execute(item, call=execution_call())
        self.health.value = health_for(
            self.catalog,
            status=CapabilityHealthStatus.DEGRADED,
        )
        with self.assertRaises(DududaError):
            await self.executor.execute(self._request(), call=execution_call())
        self.assertEqual(self.provider.requests, [])

    async def test_execution_authorization_denial_calls_no_provider(self) -> None:
        denied = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                policy_revision="policy-v1",
                role_permissions={"member": frozenset()},
            ),
            clock=lambda: NOW,
        )
        executor = self._executor(
            authorization=denied,
            authorization_verifier=denied,
        )
        with self.assertRaises(DududaError) as caught:
            await executor.execute(self._request(), call=execution_call())
        self.assertIs(caught.exception.info.category, ErrorCategory.AUTHORIZATION)
        self.assertEqual(self.provider.requests, [])

    async def test_limiter_budget_and_audit_start_failures_terminalize_without_call(
        self,
    ) -> None:
        denied_limiter = InMemoryInteractionLimiter(
            {"capability.invoke": 0},
            policy_revision="limit-v1",
            clock=lambda: NOW,
        )
        denied = self._executor(limiter=denied_limiter)
        observation = await denied.execute(self._request(), call=execution_call())
        self.assertIs(observation.status, ToolExecutionStatus.FAILED)
        self.assertEqual(self.provider.requests, [])
        replay = await denied.execute(self._request(), call=execution_call())
        self.assertEqual(replay, observation)

        fresh_ledger = InMemoryToolInvocationLedger(clock=lambda: NOW)
        empty_budget = InMemoryBudgetLedger(
            ResourceUsage(1, tool_steps=0, retries=0, cost_units=Decimal(0)),
            policy_revision="budget-v1",
            clock=lambda: NOW,
        )
        exhausted = self._executor(
            budget_ledger=empty_budget,
            invocation_ledger=fresh_ledger,
        )
        failed = await exhausted.execute(self._request(), call=execution_call())
        self.assertIs(failed.status, ToolExecutionStatus.FAILED)

        audit = ProgrammableAuditSink(fail_on=1)
        audit_failed = self._executor(
            audit_sink=audit,
            invocation_ledger=InMemoryToolInvocationLedger(clock=lambda: NOW),
        )
        failed = await audit_failed.execute(self._request(), call=execution_call())
        self.assertIs(failed.status, ToolExecutionStatus.FAILED)
        self.assertEqual(self.provider.requests, [])

    async def test_provider_exception_and_binding_drift_become_terminal_unknown(
        self,
    ) -> None:
        for mode in ("raise", "wrong-binding", "oversensitive"):
            with self.subTest(mode=mode):
                self.provider.mode = mode
                ledger = InMemoryToolInvocationLedger(clock=lambda: NOW)
                executor = self._executor(invocation_ledger=ledger)
                observation = await executor.execute(
                    self._request(invocation_id=f"invocation-{mode}"),
                    call=execution_call(),
                )
                self.assertIs(observation.status, ToolExecutionStatus.UNKNOWN)
                self.assertNotIn("private", repr(observation))

    async def test_known_failure_retries_but_unknown_never_replays(self) -> None:
        self.provider.mode = "failed"
        first = await self.executor.execute(self._request(), call=execution_call())
        self.assertIs(first.status, ToolExecutionStatus.FAILED)
        self.provider.mode = "success"
        second = await self.executor.execute(
            self._request(attempt=2, invocation_id="invocation-v2"),
            call=execution_call(),
        )
        self.assertIs(second.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(len(self.provider.requests), 2)

        self.provider.mode = "unknown"
        unknown_ledger = InMemoryToolInvocationLedger(clock=lambda: NOW)
        unknown_executor = self._executor(invocation_ledger=unknown_ledger)
        unknown = await unknown_executor.execute(
            self._request(invocation_id="invocation-unknown"),
            call=execution_call(),
        )
        self.provider.mode = "success"
        replay = await unknown_executor.execute(
            self._request(attempt=2, invocation_id="invocation-after-unknown"),
            call=execution_call(),
        )
        self.assertEqual(replay, unknown)
        self.assertEqual(
            sum(
                request.invocation_id == "invocation-unknown"
                for request in self.provider.requests
            ),
            1,
        )

    async def test_cancellation_after_dispatch_is_unknown_and_terminal(self) -> None:
        self.provider.mode = "blocked"
        cancellation = ManualCancellationToken()
        running = asyncio.create_task(
            self.executor.execute(
                self._request(),
                call=execution_call(cancellation=cancellation),
            )
        )
        await self.provider.started.wait()
        cancellation.cancel()
        observation = await running
        self.assertIs(observation.status, ToolExecutionStatus.UNKNOWN)
        self.provider.release.set()
        replay = await self.executor.execute(self._request(), call=execution_call())
        self.assertEqual(replay, observation)
        self.assertEqual(len(self.provider.requests), 1)

    async def test_native_task_cancellation_terminalizes_before_propagating(
        self,
    ) -> None:
        self.provider.mode = "blocked"
        request = self._request()
        running = asyncio.create_task(
            self.executor.execute(request, call=execution_call())
        )
        await self.provider.started.wait()
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        replay = await self.executor.execute(request, call=execution_call())
        self.assertIs(replay.status, ToolExecutionStatus.UNKNOWN)
        self.assertEqual(len(self.provider.requests), 1)

    async def test_audit_finish_failure_downgrades_success(self) -> None:
        audit = ProgrammableAuditSink(fail_on=2)
        executor = self._executor(audit_sink=audit)
        observation = await executor.execute(self._request(), call=execution_call())
        self.assertIs(observation.status, ToolExecutionStatus.UNKNOWN)
        self.assertEqual(len(self.provider.requests), 1)

        self.provider.mode = "failed"
        failed_audit = ProgrammableAuditSink(fail_on=2)
        known_failure = self._executor(
            audit_sink=failed_audit,
            invocation_ledger=InMemoryToolInvocationLedger(clock=lambda: NOW),
        )
        unaudited = await known_failure.execute(
            self._request(invocation_id="invocation-unaudited-failure"),
            call=execution_call(),
        )
        self.assertIs(unaudited.status, ToolExecutionStatus.UNKNOWN)
        self.assertFalse(unaudited.error.info.retryable)

    async def test_attempt_limit_and_forged_leases_fail_before_dispatch(self) -> None:
        with self.assertRaises(DududaError) as caught:
            await self.executor.execute(
                self._request(attempt=5, invocation_id="attempt-over-limit"),
                call=execution_call(),
            )
        self.assertEqual(
            caught.exception.info.code,
            "tool_execution_attempt_limit_exceeded",
        )

        forged_limiter = ForgedInteractionLeaseLimiter(
            InMemoryInteractionLimiter(
                {"capability.invoke": 100},
                policy_revision="limit-v1",
                clock=lambda: NOW,
            )
        )
        limiter_executor = self._executor(
            limiter=forged_limiter,
            invocation_ledger=InMemoryToolInvocationLedger(clock=lambda: NOW),
        )
        limited = await limiter_executor.execute(self._request(), call=execution_call())
        self.assertIs(limited.status, ToolExecutionStatus.FAILED)
        self.assertEqual(forged_limiter.release_calls, 0)

        forged_budget = ForgedBudgetLeaseLedger(
            InMemoryBudgetLedger(
                ResourceUsage(1, tool_steps=10, retries=10, cost_units=Decimal(10)),
                policy_revision="budget-v1",
                clock=lambda: NOW,
            )
        )
        budget_executor = self._executor(
            limiter=InMemoryInteractionLimiter(
                {"capability.invoke": 100},
                policy_revision="limit-v1",
                clock=lambda: NOW,
            ),
            budget_ledger=forged_budget,
            invocation_ledger=InMemoryToolInvocationLedger(clock=lambda: NOW),
        )
        budgeted = await budget_executor.execute(self._request(), call=execution_call())
        self.assertIs(budgeted.status, ToolExecutionStatus.FAILED)
        self.assertEqual(forged_budget.release_calls, 0)
        self.assertEqual(self.provider.requests, [])

    async def test_finalization_receipts_and_finish_audit_bind_final_unknown(
        self,
    ) -> None:
        missing_commit = self._executor(
            limiter=MissingCommitReceiptLimiter(
                InMemoryInteractionLimiter(
                    {"capability.invoke": 100},
                    policy_revision="limit-v1",
                    clock=lambda: NOW,
                )
            ),
            budget_ledger=InMemoryBudgetLedger(
                ResourceUsage(1, tool_steps=10, retries=10, cost_units=Decimal(10)),
                policy_revision="budget-v1",
                clock=lambda: NOW,
            ),
            invocation_ledger=InMemoryToolInvocationLedger(clock=lambda: NOW),
        )
        limited = await missing_commit.execute(self._request(), call=execution_call())
        self.assertIs(limited.status, ToolExecutionStatus.UNKNOWN)

        audit = ProgrammableAuditSink()
        forged_settlement = self._executor(
            limiter=InMemoryInteractionLimiter(
                {"capability.invoke": 100},
                policy_revision="limit-v1",
                clock=lambda: NOW,
            ),
            budget_ledger=ForgedSettlementReceiptBudget(
                InMemoryBudgetLedger(
                    ResourceUsage(
                        1,
                        tool_steps=10,
                        retries=10,
                        cost_units=Decimal(10),
                    ),
                    policy_revision="budget-v1",
                    clock=lambda: NOW,
                )
            ),
            audit_sink=audit,
            invocation_ledger=InMemoryToolInvocationLedger(clock=lambda: NOW),
        )
        settled = await forged_settlement.execute(
            self._request(invocation_id="invocation-forged-settlement"),
            call=execution_call(),
        )
        self.assertIs(settled.status, ToolExecutionStatus.UNKNOWN)
        finish = audit.events[-1]
        self.assertEqual(finish.sanitized_detail["status"], "unknown")
        self.assertEqual(
            finish.sanitized_detail["observation_digest"],
            str(settled.observation_digest),
        )
        self.assertEqual(
            finish.sanitized_detail["usage_digest"],
            str(usage_digest(settled.usage)),
        )

    async def test_settlement_and_ledger_failures_never_return_success(self) -> None:
        settlement = self._executor(
            budget_ledger=FailingSettlementBudget(self.budget),
            invocation_ledger=InMemoryToolInvocationLedger(clock=lambda: NOW),
        )
        observation = await settlement.execute(
            self._request(invocation_id="invocation-settlement"),
            call=execution_call(),
        )
        self.assertIs(observation.status, ToolExecutionStatus.UNKNOWN)

        ledger_failure = self._executor(
            invocation_ledger=FailingCompletionLedger(clock=lambda: NOW),
        )
        uncommitted = await ledger_failure.execute(
            self._request(invocation_id="invocation-ledger"),
            call=execution_call(),
        )
        self.assertIs(uncommitted.status, ToolExecutionStatus.UNKNOWN)
        self.assertEqual(
            uncommitted.error.info.code,
            "tool_invocation_terminalization_failed",
        )
        self.assertNotIn("private", repr(uncommitted))


if __name__ == "__main__":
    unittest.main()
