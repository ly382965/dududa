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

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported ErrorInfo schema version")
        if not isinstance(self.category, ErrorCategory):
            raise TypeError("invalid ErrorInfo category")
        if type(self.retryable) is not bool or type(self.outcome_unknown) is not bool:
            raise TypeError("invalid ErrorInfo boolean")
        for field_name in ("code", "public_message_key"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"empty ErrorInfo {field_name}")
        if isinstance(self.reason_codes, (str, bytes)):
            raise TypeError("invalid ErrorInfo reason_codes")
        reason_codes = tuple(self.reason_codes)
        if any(
            not isinstance(reason, str) or not reason.strip() for reason in reason_codes
        ):
            raise ValueError("invalid ErrorInfo reason code")
        if len(reason_codes) != len(set(reason_codes)):
            raise ValueError("duplicate ErrorInfo reason code")
        object.__setattr__(self, "reason_codes", reason_codes)


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
