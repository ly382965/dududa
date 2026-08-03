from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from dududa.contracts.canonical import canonical_digest
from dududa.domain.content import ContentSafetyDecision
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    ResponseConstraints,
    Sensitivity,
)
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext

from .digests import content_safety_request_digest
from .models import ContentSafetyRequest, RedactionRequest
from .redaction import DefaultRedactor


class DefaultContentSafetyPolicy:
    def __init__(
        self,
        *,
        redactor: DefaultRedactor | None = None,
        policy_revision: str = "content-safety-v1",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._redactor = redactor or DefaultRedactor()
        self._policy_revision = policy_revision
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._revision = ComponentRevision(
            "security.content-safety",
            "1",
            policy_revision,
            DigestString("builtin"),
        )

    async def evaluate(
        self,
        request: ContentSafetyRequest,
        *,
        call: PortCallContext,
    ) -> ContentSafetyDecision:
        now = self._clock()
        if call.cancellation.is_cancelled or call.deadline <= now:
            raise error(
                "content_safety_call_cancelled_or_expired",
                ErrorCategory.VALIDATION,
                "security.content_rejected",
            )
        if content_safety_request_digest(request) != request.request_digest:
            raise error(
                "content_safety_request_digest_mismatch",
                ErrorCategory.VALIDATION,
                "security.content_rejected",
            )
        expected_content = canonical_digest(
            request.content,
            domain="security:content:v1",
        )
        if expected_content != request.content_digest:
            raise error(
                "content_digest_mismatch",
                ErrorCategory.VALIDATION,
                "security.content_rejected",
            )
        redaction = self._redactor.redact(
            RedactionRequest(
                1, request.content, Sensitivity.SENSITIVE, "content_safety"
            )
        )
        allowed = not redaction.changed
        return ContentSafetyDecision(
            schema_version=1,
            request_id=request.request_id,
            stage=request.stage,
            request_digest=request.request_digest,
            content_digest=request.content_digest,
            actor_digest=request.actor_digest,
            scope_digest=request.scope_digest,
            allowed=allowed,
            required_constraints=ResponseConstraints(),
            reason_codes=() if allowed else ("credential_like_content",),
            policy_revision=self._policy_revision,
            producer=self._revision,
            decided_at=now,
        )
