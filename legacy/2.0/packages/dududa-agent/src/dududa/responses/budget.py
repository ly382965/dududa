from __future__ import annotations

from dataclasses import replace

from dududa.domain.primitives import ResourceUsage
from dududa.errors import validation_error

from .contracts import ResponsePlan


def project_response_reservation(
    reservation: ResourceUsage,
    plan: ResponsePlan,
) -> ResourceUsage:
    if not isinstance(reservation, ResourceUsage):
        raise validation_error("invalid_response_base_reservation")
    if not isinstance(plan, ResponsePlan):
        raise validation_error("invalid_response_plan")
    if reservation.model_calls != 1 or reservation.tool_steps != 0:
        raise validation_error("invalid_response_base_reservation")
    if plan.generated_token_limit > reservation.output_tokens:
        raise validation_error("response_plan_exceeds_base_reservation")
    return replace(reservation, output_tokens=plan.generated_token_limit)


__all__ = ["project_response_reservation"]
