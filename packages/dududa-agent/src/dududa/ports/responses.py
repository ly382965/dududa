from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from dududa.domain.primitives import ComponentRevision
from dududa.responses.contracts import (
    ResponsePlan,
    ResponseProfileSelectionRequest,
)


@runtime_checkable
class ResponseProfilePolicy(Protocol):
    def select(
        self,
        request: ResponseProfileSelectionRequest,
        *,
        now: datetime,
    ) -> ResponsePlan: ...


@runtime_checkable
class VisibleTokenCounter(Protocol):
    @property
    def revision(self) -> ComponentRevision: ...

    def count(self, text: str) -> int: ...


__all__ = ["ResponseProfilePolicy", "VisibleTokenCounter"]
