"""Framework-neutral domain contracts."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .attachments import (
        AttachmentAccessRequest,
        AttachmentDescriptor,
        AttachmentIngestRequest,
        AttachmentPurpose,
        StoredContentRef,
    )
    from .identity import Actor, ActorRef, ConversationScope
    from .message import AttachmentRef, Mention, MessageEnvelope, MessageReference
    from .primitives import (
        ComponentRevision,
        ConversationType,
        DigestString,
        JsonValue,
        Outcome,
        PrivacyLevel,
        ResourceRef,
        RiskLevel,
        SchemaRef,
        Sensitivity,
    )

__all__ = [
    "Actor",
    "ActorRef",
    "AttachmentAccessRequest",
    "AttachmentDescriptor",
    "AttachmentIngestRequest",
    "AttachmentPurpose",
    "AttachmentRef",
    "ComponentRevision",
    "ConversationScope",
    "ConversationType",
    "DigestString",
    "JsonValue",
    "Mention",
    "MessageEnvelope",
    "MessageReference",
    "Outcome",
    "PrivacyLevel",
    "ResourceRef",
    "RiskLevel",
    "SchemaRef",
    "Sensitivity",
    "StoredContentRef",
]

_EXPORT_MODULES = {
    "Actor": ".identity",
    "ActorRef": ".identity",
    "AttachmentAccessRequest": ".attachments",
    "AttachmentDescriptor": ".attachments",
    "AttachmentIngestRequest": ".attachments",
    "AttachmentPurpose": ".attachments",
    "AttachmentRef": ".message",
    "ComponentRevision": ".primitives",
    "ConversationScope": ".identity",
    "ConversationType": ".primitives",
    "DigestString": ".primitives",
    "JsonValue": ".primitives",
    "Mention": ".message",
    "MessageEnvelope": ".message",
    "MessageReference": ".message",
    "Outcome": ".primitives",
    "PrivacyLevel": ".primitives",
    "ResourceRef": ".primitives",
    "RiskLevel": ".primitives",
    "SchemaRef": ".primitives",
    "Sensitivity": ".primitives",
    "StoredContentRef": ".attachments",
}


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
