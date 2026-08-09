from __future__ import annotations

from dududa._compat import StrEnum
from dududa.errors import DududaError, ErrorCategory, ErrorInfo, validation_error


class McpFailureKind(StrEnum):
    NOT_FOUND = "not_found"
    DISABLED = "disabled"
    TOOL_FORBIDDEN = "tool_forbidden"
    SCHEMA_UNAVAILABLE = "schema_unavailable"
    SCHEMA_STALE = "schema_stale"
    SCHEMA_INCOMPATIBLE = "schema_incompatible"
    ARGUMENT_INVALID = "argument_invalid"
    RESULT_INVALID = "result_invalid"
    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CIRCUIT_OPEN = "circuit_open"
    OUTCOME_UNKNOWN = "outcome_unknown"
    CLOSED = "closed"
    INTERNAL = "internal"


class McpClientError(DududaError):
    def __init__(self, failure_kind: McpFailureKind, info: ErrorInfo) -> None:
        if not isinstance(failure_kind, McpFailureKind):
            raise validation_error("invalid_mcp_failure_kind")
        expected = mcp_error_info(
            failure_kind,
            code=info.code,
            reason_codes=info.reason_codes,
            outcome_unknown=info.outcome_unknown,
        )
        if info != expected:
            raise validation_error("invalid_mcp_error_info")
        super().__init__(info)
        self.failure_kind = failure_kind


def mcp_client_error(
    failure_kind: McpFailureKind,
    code: str,
    *reason_codes: str,
    outcome_unknown: bool = False,
) -> McpClientError:
    return McpClientError(
        failure_kind,
        mcp_error_info(
            failure_kind,
            code=code,
            reason_codes=tuple(reason_codes),
            outcome_unknown=outcome_unknown,
        ),
    )


def mcp_error_info(
    failure_kind: McpFailureKind,
    *,
    code: str,
    reason_codes: tuple[str, ...],
    outcome_unknown: bool = False,
) -> ErrorInfo:
    if not isinstance(failure_kind, McpFailureKind):
        raise validation_error("invalid_mcp_failure_kind")
    categories = {
        McpFailureKind.NOT_FOUND: ErrorCategory.NOT_FOUND,
        McpFailureKind.DISABLED: ErrorCategory.AUTHORIZATION,
        McpFailureKind.TOOL_FORBIDDEN: ErrorCategory.AUTHORIZATION,
        McpFailureKind.SCHEMA_UNAVAILABLE: ErrorCategory.EXTERNAL,
        McpFailureKind.SCHEMA_STALE: ErrorCategory.EXTERNAL,
        McpFailureKind.SCHEMA_INCOMPATIBLE: ErrorCategory.EXTERNAL,
        McpFailureKind.ARGUMENT_INVALID: ErrorCategory.VALIDATION,
        McpFailureKind.RESULT_INVALID: ErrorCategory.EXTERNAL,
        McpFailureKind.TRANSPORT_UNAVAILABLE: ErrorCategory.EXTERNAL,
        McpFailureKind.TIMEOUT: ErrorCategory.TIMEOUT,
        McpFailureKind.CANCELLED: ErrorCategory.CANCELLED,
        McpFailureKind.BUDGET_EXHAUSTED: ErrorCategory.BUDGET,
        McpFailureKind.CIRCUIT_OPEN: ErrorCategory.EXTERNAL,
        McpFailureKind.OUTCOME_UNKNOWN: ErrorCategory.EXTERNAL,
        McpFailureKind.CLOSED: ErrorCategory.EXTERNAL,
        McpFailureKind.INTERNAL: ErrorCategory.INTERNAL,
    }
    retryable = not outcome_unknown and failure_kind in {
        McpFailureKind.SCHEMA_UNAVAILABLE,
        McpFailureKind.SCHEMA_STALE,
        McpFailureKind.TRANSPORT_UNAVAILABLE,
        McpFailureKind.TIMEOUT,
        McpFailureKind.CIRCUIT_OPEN,
    }
    if failure_kind is McpFailureKind.OUTCOME_UNKNOWN and not outcome_unknown:
        raise validation_error("mcp_unknown_outcome_flag_missing")
    public_message_key = {
        McpFailureKind.CANCELLED: "request.cancelled",
        McpFailureKind.ARGUMENT_INVALID: "request.invalid",
        McpFailureKind.TOOL_FORBIDDEN: "request.forbidden",
        McpFailureKind.DISABLED: "request.forbidden",
        McpFailureKind.NOT_FOUND: "mcp.not_found",
        McpFailureKind.BUDGET_EXHAUSTED: "request.budget_exhausted",
    }.get(failure_kind, "mcp.unavailable")
    return ErrorInfo(
        schema_version=1,
        code=code,
        category=categories[failure_kind],
        retryable=retryable,
        outcome_unknown=outcome_unknown,
        public_message_key=public_message_key,
        reason_codes=reason_codes,
    )
