from __future__ import annotations

from dududa.errors import DududaError, ErrorInfo, validation_error

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
        super().__init__(info, detail=detail)
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
        if route_decision.attempts:
            terminal = route_decision.attempts[-1]
            if terminal.failure_kind is not failure_kind or terminal.error != info:
                raise validation_error("model_invocation_failure_receipt_mismatch")
        super().__init__(info, detail=detail)
        self.failure_kind = failure_kind
        self.route_decision = route_decision
