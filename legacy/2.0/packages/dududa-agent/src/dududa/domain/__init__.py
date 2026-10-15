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
    from .capability import (
        CapabilityDefinition,
        CostHint,
        Idempotency,
        LatencyHint,
        ProviderRef,
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
    from .task import (
        ContextPressure,
        TaskAmbiguity,
        TaskComplexityAssessment,
        TaskComplexityLevel,
        TaskReasoningDepth,
    )

__all__ = [
    "Actor",
    "ActorRef",
    "AttachmentAccessRequest",
    "AttachmentDescriptor",
    "AttachmentIngestRequest",
    "AttachmentPurpose",
    "AttachmentRef",
    "CapabilityDefinition",
    "ComponentRevision",
    "ContextPressure",
    "ConversationScope",
    "ConversationType",
    "CostHint",
    "DigestString",
    "JsonValue",
    "Idempotency",
    "LatencyHint",
    "Mention",
    "MessageEnvelope",
    "MessageReference",
    "Outcome",
    "PrivacyLevel",
    "ProviderRef",
    "ResourceRef",
    "RiskLevel",
    "SchemaRef",
    "Sensitivity",
    "StoredContentRef",
    "TaskAmbiguity",
    "TaskComplexityAssessment",
    "TaskComplexityLevel",
    "TaskReasoningDepth",
]

_EXPORT_MODULES = {
    "Actor": ".identity",
    "ActorRef": ".identity",
    "AttachmentAccessRequest": ".attachments",
    "AttachmentDescriptor": ".attachments",
    "AttachmentIngestRequest": ".attachments",
    "AttachmentPurpose": ".attachments",
    "AttachmentRef": ".message",
    "CapabilityDefinition": ".capability",
    "ComponentRevision": ".primitives",
    "ConversationScope": ".identity",
    "ConversationType": ".primitives",
    "CostHint": ".capability",
    "DigestString": ".primitives",
    "JsonValue": ".primitives",
    "Idempotency": ".capability",
    "LatencyHint": ".capability",
    "Mention": ".message",
    "MessageEnvelope": ".message",
    "MessageReference": ".message",
    "Outcome": ".primitives",
    "PrivacyLevel": ".primitives",
    "ProviderRef": ".capability",
    "ResourceRef": ".primitives",
    "RiskLevel": ".primitives",
    "SchemaRef": ".primitives",
    "Sensitivity": ".primitives",
    "StoredContentRef": ".attachments",
    "ContextPressure": ".task",
    "TaskAmbiguity": ".task",
    "TaskComplexityAssessment": ".task",
    "TaskComplexityLevel": ".task",
    "TaskReasoningDepth": ".task",
}


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
