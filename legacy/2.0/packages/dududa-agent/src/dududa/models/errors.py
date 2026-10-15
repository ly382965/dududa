from __future__ import annotations

from dududa.errors import (
    DududaError,
    ErrorCategory,
    ErrorInfo,
    validation_error,
)

from .contracts import (
    ModelFailureKind,
    RouteDecision,
    validate_model_failure_info,
)


class ModelProviderError(DududaError):
    """Sanitized Provider failure that the Router can classify deterministically."""

    def __init__(
        self,
        failure_kind: ModelFailureKind,
        info: ErrorInfo,
        *,
        detail: str | None = None,
    ) -> None:
        if not isinstance(failure_kind, ModelFailureKind):
            raise validation_error("invalid_model_failure_kind")
        if not isinstance(info, ErrorInfo):
            raise validation_error("invalid_model_error_info")
        validate_model_failure_info(failure_kind, info)
        if detail is not None:
            raise validation_error("model_error_detail_forbidden")
        super().__init__(info)
        self.failure_kind = failure_kind


class ModelInvocationError(DududaError):
    """Terminal Router failure carrying the complete sanitized route receipt."""

    def __init__(
        self,
        failure_kind: ModelFailureKind,
        info: ErrorInfo,
        route_decision: RouteDecision,
        *,
        detail: str | None = None,
    ) -> None:
        if not isinstance(failure_kind, ModelFailureKind):
            raise validation_error("invalid_model_failure_kind")
        if not isinstance(info, ErrorInfo):
            raise validation_error("invalid_model_error_info")
        validate_model_failure_info(failure_kind, info)
        if not isinstance(route_decision, RouteDecision):
            raise validation_error("invalid_route_decision")
        if (
            route_decision.terminal_failure_kind is not failure_kind
            or route_decision.terminal_error != info
        ):
            raise validation_error("model_invocation_failure_receipt_mismatch")
        if detail is not None:
            raise validation_error("model_error_detail_forbidden")
        super().__init__(info)
        self.failure_kind = failure_kind
        self.route_decision = route_decision


def model_error_info(
    failure_kind: ModelFailureKind,
    *,
    code: str,
    reason_codes: tuple[str, ...],
    outcome_unknown: bool = False,
) -> ErrorInfo:
    categories = {
        ModelFailureKind.ROUTE_NOT_FOUND: ErrorCategory.NOT_FOUND,
        ModelFailureKind.TRANSIENT_NETWORK: ErrorCategory.EXTERNAL,
        ModelFailureKind.TIMEOUT: ErrorCategory.TIMEOUT,
        ModelFailureKind.RATE_LIMITED: ErrorCategory.EXTERNAL,
        ModelFailureKind.PROVIDER_UNAVAILABLE: ErrorCategory.EXTERNAL,
        ModelFailureKind.CONTEXT_TOO_LONG: ErrorCategory.VALIDATION,
        ModelFailureKind.AUTHENTICATION: ErrorCategory.EXTERNAL,
        ModelFailureKind.INVALID_REQUEST: ErrorCategory.VALIDATION,
        ModelFailureKind.CAPABILITY_MISMATCH: ErrorCategory.VALIDATION,
        ModelFailureKind.OUTPUT_INVALID: ErrorCategory.VALIDATION,
        ModelFailureKind.SAFETY_REJECTED: ErrorCategory.AUTHORIZATION,
        ModelFailureKind.CANCELLED: ErrorCategory.CANCELLED,
        ModelFailureKind.BUDGET_EXHAUSTED: ErrorCategory.BUDGET,
        ModelFailureKind.INTERNAL: ErrorCategory.INTERNAL,
    }
    retryable = failure_kind in {
        ModelFailureKind.TRANSIENT_NETWORK,
        ModelFailureKind.TIMEOUT,
        ModelFailureKind.RATE_LIMITED,
        ModelFailureKind.PROVIDER_UNAVAILABLE,
    }
    public_message_key = {
        ModelFailureKind.CANCELLED: "request.cancelled",
        ModelFailureKind.BUDGET_EXHAUSTED: "request.budget_exhausted",
        ModelFailureKind.ROUTE_NOT_FOUND: "model.route_not_found",
        ModelFailureKind.OUTPUT_INVALID: "model.output_invalid",
    }.get(failure_kind, "model.unavailable")
    return ErrorInfo(
        schema_version=1,
        code=code,
        category=categories[failure_kind],
        retryable=retryable,
        outcome_unknown=outcome_unknown,
        public_message_key=public_message_key,
        reason_codes=reason_codes,
    )
