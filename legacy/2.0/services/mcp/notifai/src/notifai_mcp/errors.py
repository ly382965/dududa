from __future__ import annotations


class NotifAIError(RuntimeError):
    """A safe, user-visible error boundary for the upstream API."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status = status


class NotifAIValidationError(NotifAIError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_arguments", message)
