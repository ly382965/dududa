from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from dududa.domain.primitives import ComponentRevision, ResourceUsage, RuntimeBudget
from dududa.errors import ErrorCategory, error, validation_error


@dataclass(frozen=True, slots=True)
class RuntimeModelBudgetPlan:
    schema_version: int
    perception_reservation: ResourceUsage
    direct_chat_reservation: ResourceUsage
    revision: ComponentRevision

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.revision, ComponentRevision):
            raise validation_error("invalid_runtime_budget_plan_revision")
        for name in ("perception_reservation", "direct_chat_reservation"):
            reservation = getattr(self, name)
            if not isinstance(reservation, ResourceUsage):
                raise validation_error("invalid_model_budget_reservation", name)
            if (
                reservation.model_calls != 1
                or reservation.tool_steps != 0
                or reservation.input_tokens < 1
                or reservation.output_tokens < 1
            ):
                raise validation_error("invalid_model_budget_reservation", name)


@dataclass(frozen=True, slots=True)
class RuntimeToolBudgetPlan:
    schema_version: int
    reservation: ResourceUsage
    revision: ComponentRevision

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.reservation, ResourceUsage):
            raise validation_error("invalid_tool_budget_reservation")
        if (
            self.reservation.model_calls != 0
            or not 1 <= self.reservation.tool_steps <= 8
            or not 0 <= self.reservation.retries <= 8
            or self.reservation.input_tokens != 0
            or self.reservation.output_tokens != 0
        ):
            raise validation_error("invalid_tool_budget_reservation")
        if not isinstance(self.revision, ComponentRevision):
            raise validation_error("invalid_runtime_tool_budget_plan_revision")


def ensure_budget_covers_plan(
    budget: RuntimeBudget,
    plan: RuntimeModelBudgetPlan,
) -> None:
    if not isinstance(budget, RuntimeBudget):
        raise validation_error("invalid_runtime_budget")
    if not isinstance(plan, RuntimeModelBudgetPlan):
        raise validation_error("invalid_runtime_budget_plan")
    total = add_usage(plan.perception_reservation, plan.direct_chat_reservation)
    if not _covers(budget, total):
        raise error(
            "runtime_budget_plan_exhausted",
            ErrorCategory.BUDGET,
            "request.budget_exhausted",
            "two_model_call_budget_not_available",
        )


def ensure_budget_covers_tool_plan(
    budget: RuntimeBudget,
    model_plan: RuntimeModelBudgetPlan,
    tool_plan: RuntimeToolBudgetPlan,
) -> None:
    if not isinstance(tool_plan, RuntimeToolBudgetPlan):
        raise validation_error("invalid_runtime_tool_budget_plan")
    model_total = add_usage(
        model_plan.perception_reservation,
        model_plan.direct_chat_reservation,
    )
    total = add_usage(model_total, tool_plan.reservation)
    if not _covers(budget, total):
        raise error(
            "runtime_tool_budget_plan_exhausted",
            ErrorCategory.BUDGET,
            "request.budget_exhausted",
            "model_and_tool_budget_not_available",
        )


def usage_within_tool_reservation(
    usage: ResourceUsage,
    reservation: ResourceUsage,
) -> bool:
    if not isinstance(usage, ResourceUsage) or not isinstance(
        reservation, ResourceUsage
    ):
        return False
    return _covers(reservation_budget(reservation), usage)


def reservation_budget(reservation: ResourceUsage) -> RuntimeBudget:
    if not isinstance(reservation, ResourceUsage):
        raise validation_error("invalid_model_budget_reservation")
    return RuntimeBudget(
        model_calls_remaining=reservation.model_calls,
        tool_steps_remaining=reservation.tool_steps,
        retries_remaining=reservation.retries,
        input_tokens_remaining=reservation.input_tokens,
        output_tokens_remaining=reservation.output_tokens,
        cost_units_remaining=reservation.cost_units,
    )


def charge_budget(
    budget: RuntimeBudget,
    charge: ResourceUsage,
) -> RuntimeBudget:
    if not isinstance(budget, RuntimeBudget) or not isinstance(charge, ResourceUsage):
        raise validation_error("invalid_budget_charge")
    if not _covers(budget, charge):
        raise error(
            "runtime_budget_charge_exhausted",
            ErrorCategory.BUDGET,
            "request.budget_exhausted",
            "runtime_charge_exceeds_remaining_budget",
        )
    cost: Decimal | None
    if budget.cost_units_remaining is None:
        cost = None
    else:
        if charge.cost_units is None:
            raise validation_error("unbounded_charge_against_bounded_budget")
        cost = budget.cost_units_remaining - charge.cost_units
    return RuntimeBudget(
        model_calls_remaining=budget.model_calls_remaining - charge.model_calls,
        tool_steps_remaining=budget.tool_steps_remaining - charge.tool_steps,
        retries_remaining=budget.retries_remaining - charge.retries,
        input_tokens_remaining=budget.input_tokens_remaining - charge.input_tokens,
        output_tokens_remaining=budget.output_tokens_remaining - charge.output_tokens,
        cost_units_remaining=cost,
    )


def zero_usage_for_budget(budget: RuntimeBudget) -> ResourceUsage:
    if not isinstance(budget, RuntimeBudget):
        raise validation_error("invalid_runtime_budget")
    return ResourceUsage(
        schema_version=1,
        cost_units=(Decimal(0) if budget.cost_units_remaining is not None else None),
    )


def add_usage(left: ResourceUsage, right: ResourceUsage) -> ResourceUsage:
    if not isinstance(left, ResourceUsage) or not isinstance(right, ResourceUsage):
        raise validation_error("invalid_resource_usage")
    cost: Decimal | None
    if left.cost_units is None or right.cost_units is None:
        cost = None
    else:
        cost = left.cost_units + right.cost_units
    return ResourceUsage(
        schema_version=1,
        model_calls=left.model_calls + right.model_calls,
        tool_steps=left.tool_steps + right.tool_steps,
        retries=left.retries + right.retries,
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cost_units=cost,
    )


def usage_within_reservation(
    usage: object,
    reservation: ResourceUsage,
) -> bool:
    from dududa.models.contracts import ModelUsage

    if usage is None:
        return True
    if not isinstance(usage, ModelUsage):
        return False
    if usage.input_tokens > reservation.input_tokens:
        return False
    if usage.generated_tokens > reservation.output_tokens:
        return False
    return reservation.cost_units is None or (
        usage.cost_units is not None and usage.cost_units <= reservation.cost_units
    )


def _covers(budget: RuntimeBudget, usage: ResourceUsage) -> bool:
    if budget.model_calls_remaining < usage.model_calls:
        return False
    if budget.tool_steps_remaining < usage.tool_steps:
        return False
    if budget.retries_remaining < usage.retries:
        return False
    if budget.input_tokens_remaining < usage.input_tokens:
        return False
    if budget.output_tokens_remaining < usage.output_tokens:
        return False
    if budget.cost_units_remaining is not None:
        return (
            usage.cost_units is not None
            and budget.cost_units_remaining >= usage.cost_units
        )
    return True
