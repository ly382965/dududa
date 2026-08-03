from __future__ import annotations

from dataclasses import dataclass

from dududa.errors import validation_error

from .primitives import (
    ConversationType,
    DenyFlag,
    DigestString,
    RoleId,
    require_non_empty,
)


@dataclass(frozen=True, slots=True)
class Actor:
    platform: str
    bot_id: str
    user_id: str
    roles: frozenset[RoleId]
    deny_flags: frozenset[DenyFlag] = frozenset()

    def __post_init__(self) -> None:
        require_non_empty(self.platform, "platform")
        require_non_empty(self.bot_id, "bot_id")
        require_non_empty(self.user_id, "user_id")
        roles = frozenset(self.roles)
        deny_flags = frozenset(self.deny_flags)
        if any(not isinstance(role, str) or not role.strip() for role in roles):
            raise validation_error("invalid_actor_role")
        if any(not isinstance(flag, str) or not flag.strip() for flag in deny_flags):
            raise validation_error("invalid_actor_deny_flag")
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "deny_flags", deny_flags)


@dataclass(frozen=True, slots=True)
class ActorRef:
    platform: str
    bot_id: str
    opaque_actor_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.platform, "platform")
        require_non_empty(self.bot_id, "bot_id")
        require_non_empty(self.opaque_actor_id, "opaque_actor_id")


@dataclass(frozen=True, slots=True)
class ResolvedIdentityRef:
    identity_ref: str
    actor_ref: ActorRef
    evidence_message_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.identity_ref, "identity_ref")


@dataclass(frozen=True, slots=True)
class ConversationScope:
    platform: str
    bot_id: str
    conversation_type: ConversationType
    conversation_id: str
    group_id: str | None
    persona_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.platform, "platform")
        require_non_empty(self.bot_id, "bot_id")
        require_non_empty(self.conversation_id, "conversation_id")
        require_non_empty(self.persona_id, "persona_id")
        if not isinstance(self.conversation_type, ConversationType):
            raise validation_error("invalid_conversation_type")
        if (
            self.conversation_type is ConversationType.PRIVATE
            and self.conversation_id.strip().lower() == "private"
        ):
            raise validation_error("ambiguous_private_conversation_id")
        if self.conversation_type is ConversationType.GROUP:
            if not self.group_id:
                raise validation_error("group_scope_requires_group_id")
            if self.group_id != self.conversation_id:
                raise validation_error("group_scope_identity_mismatch")
        elif self.group_id is not None:
            raise validation_error("non_group_scope_forbids_group_id")


@dataclass(frozen=True, slots=True)
class ScopeRef:
    scope_digest: DigestString
