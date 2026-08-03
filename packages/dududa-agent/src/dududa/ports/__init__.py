"""Framework-neutral Protocol ports owned by Dududa core."""

from typing import TYPE_CHECKING

from .context import (
    CancellationToken,
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
    ServiceCallContext,
    ServicePrincipal,
)

if TYPE_CHECKING:
    from .attachments import AttachmentRepository, BoundedAttachmentStream
    from .memory import MemoryRepository, ScopeSelectorVerifier
    from .output import OutputAdapter
    from .runtime import AgentRuntime, InputConnector

__all__ = [
    "AgentRuntime",
    "AttachmentRepository",
    "BoundedAttachmentStream",
    "CancellationToken",
    "InputConnector",
    "ManualCancellationToken",
    "MemoryRepository",
    "NeverCancelled",
    "OutputAdapter",
    "PortCallContext",
    "ServiceCallContext",
    "ServicePrincipal",
    "ScopeSelectorVerifier",
]


def __getattr__(name: str) -> object:
    if name in {"MemoryRepository", "ScopeSelectorVerifier"}:
        from .memory import MemoryRepository, ScopeSelectorVerifier

        return {
            "MemoryRepository": MemoryRepository,
            "ScopeSelectorVerifier": ScopeSelectorVerifier,
        }[name]
    if name in {"AttachmentRepository", "BoundedAttachmentStream"}:
        from .attachments import AttachmentRepository, BoundedAttachmentStream

        return {
            "AttachmentRepository": AttachmentRepository,
            "BoundedAttachmentStream": BoundedAttachmentStream,
        }[name]
    if name == "OutputAdapter":
        from .output import OutputAdapter

        return OutputAdapter
    if name in {"AgentRuntime", "InputConnector"}:
        from .runtime import AgentRuntime, InputConnector

        return {"AgentRuntime": AgentRuntime, "InputConnector": InputConnector}[name]
    raise AttributeError(name)
