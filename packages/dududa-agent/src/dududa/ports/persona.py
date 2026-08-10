from __future__ import annotations

from typing import Protocol, runtime_checkable

from dududa.domain.primitives import DigestString
from dududa.persona.contracts import (
    PersonaCatalogSnapshot,
    PersonaCatalogUpdate,
    PersonaResolution,
)

from .context import PortCallContext, ServiceCallContext

PersonaCatalogCallContext = PortCallContext | ServiceCallContext


@runtime_checkable
class PersonaRegistry(Protocol):
    def acquire_snapshot(self) -> PersonaCatalogSnapshot: ...

    def snapshot_by_id(
        self,
        snapshot_id: str,
        *,
        expected_digest: DigestString | None = None,
    ) -> PersonaCatalogSnapshot: ...

    def resolve(
        self,
        snapshot: PersonaCatalogSnapshot,
        persona_id: str,
        version: str | None = None,
    ) -> PersonaResolution: ...

    def list_versions(
        self,
        snapshot: PersonaCatalogSnapshot,
        persona_id: str,
    ) -> tuple[str, ...]: ...


@runtime_checkable
class PersonaCatalogPublisher(Protocol):
    async def publish(
        self,
        update: PersonaCatalogUpdate,
        *,
        call: PersonaCatalogCallContext,
    ) -> PersonaCatalogSnapshot: ...


__all__ = ["PersonaCatalogPublisher", "PersonaRegistry"]
