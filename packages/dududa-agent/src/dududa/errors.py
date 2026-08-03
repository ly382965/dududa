from __future__ import annotations

from dataclasses import dataclass

from ._compat import StrEnum


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    EXTERNAL = "external"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    BUDGET = "budget"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    schema_version: int
    code: str
    category: ErrorCategory
    retryable: bool
    outcome_unknown: bool
    public_message_key: str
    reason_codes: tuple[str, ...] = ()


class DududaError(Exception):
    """Stable domain error that never exposes an implementation exception."""

    def __init__(self, info: ErrorInfo, *, detail: str | None = None) -> None:
        super().__init__(info.public_message_key)
        self.info = info
        self.detail = detail


def validation_error(code: str, *reason_codes: str) -> DududaError:
    return error(
        code,
        ErrorCategory.VALIDATION,
        "request.invalid",
        *reason_codes,
    )


def error(
    code: str,
    category: ErrorCategory,
    public_message_key: str,
    *reason_codes: str,
    retryable: bool = False,
    outcome_unknown: bool = False,
    detail: str | None = None,
) -> DududaError:
    return DududaError(
        ErrorInfo(
            schema_version=1,
            code=code,
            category=category,
            retryable=retryable,
            outcome_unknown=outcome_unknown,
            public_message_key=public_message_key,
            reason_codes=tuple(reason_codes),
        ),
        detail=detail,
    )
