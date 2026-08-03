from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import uuid

from dududa.contracts.canonical import canonical_digest, canonical_json_bytes
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import DigestString

from dududa.security.digests import actor_digest, scope_digest

from .models import MemoryType, ScopeSelector, SelectorMode


class HmacScopeSelectorAuthority:
    def __init__(
        self,
        secret: bytes,
        *,
        policy_revision: str,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        maximum_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if len(secret) < 16:
            raise ValueError("selector authority secret must be at least 16 bytes")
        self._secret = bytes(secret)
        self._policy_revision = policy_revision
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._maximum_ttl = maximum_ttl

    def issue_current_conversation(
        self,
        *,
        request_digest: DigestString,
        actor: Actor,
        scope: ConversationScope,
        memory_types: frozenset[MemoryType],
        purpose: str,
        ttl: timedelta = timedelta(minutes=1),
    ) -> ScopeSelector:
        return self._issue(
            request_digest=request_digest,
            actor=actor,
            scope=scope,
            mode=SelectorMode.CURRENT_CONVERSATION,
            memory_types=memory_types,
            purpose=purpose,
            conversation_id=scope.conversation_id,
            group_id=scope.group_id,
            user_id=actor.user_id,
            ttl=ttl,
        )

    def issue_current_group(
        self,
        *,
        request_digest: DigestString,
        actor: Actor,
        scope: ConversationScope,
        memory_types: frozenset[MemoryType],
        purpose: str,
        ttl: timedelta = timedelta(minutes=1),
    ) -> ScopeSelector:
        if scope.group_id is None:
            raise ValueError("current group selector requires group scope")
        return self._issue(
            request_digest=request_digest,
            actor=actor,
            scope=scope,
            mode=SelectorMode.CURRENT_GROUP,
            memory_types=memory_types,
            purpose=purpose,
            conversation_id=scope.conversation_id,
            group_id=scope.group_id,
            user_id=actor.user_id,
            ttl=ttl,
        )

    def issue_safe_user_profile(
        self,
        *,
        request_digest: DigestString,
        actor: Actor,
        scope: ConversationScope,
        purpose: str,
        ttl: timedelta = timedelta(minutes=1),
    ) -> ScopeSelector:
        return self._issue(
            request_digest=request_digest,
            actor=actor,
            scope=scope,
            mode=SelectorMode.SAFE_USER_PROFILE,
            memory_types=frozenset({MemoryType.USER_PROFILE}),
            purpose=purpose,
            conversation_id=None,
            group_id=None,
            user_id=actor.user_id,
            ttl=ttl,
        )

    def verify(
        self,
        selector: ScopeSelector,
        *,
        expected_request_digest: DigestString,
        now: datetime | None = None,
    ) -> bool:
        current = now or self._clock()
        if (
            selector.policy_revision != self._policy_revision
            or selector.request_digest != expected_request_digest
            or selector.expires_at <= current
            or selector.issued_at > current
        ):
            return False
        expected = self._proof(selector)
        return hmac.compare_digest(selector.integrity_proof, expected)

    @staticmethod
    def digest(selector: ScopeSelector) -> DigestString:
        return canonical_digest(selector, domain="memory:scope-selector:v1")

    def _issue(
        self,
        *,
        request_digest: DigestString,
        actor: Actor,
        scope: ConversationScope,
        mode: SelectorMode,
        memory_types: frozenset[MemoryType],
        purpose: str,
        conversation_id: str | None,
        group_id: str | None,
        user_id: str | None,
        ttl: timedelta,
    ) -> ScopeSelector:
        if ttl <= timedelta(0) or ttl > self._maximum_ttl:
            raise ValueError("invalid selector ttl")
        if actor.platform != scope.platform or actor.bot_id != scope.bot_id:
            raise ValueError("actor and scope do not match")
        now = self._clock()
        unsigned = ScopeSelector(
            1,
            self._id_factory(),
            request_digest,
            mode,
            self._policy_revision,
            purpose,
            str(actor_digest(actor)),
            scope_digest(scope),
            scope.platform,
            scope.bot_id,
            scope.persona_id,
            conversation_id,
            group_id,
            user_id,
            memory_types,
            now,
            now + ttl,
            "pending",
        )
        return replace(unsigned, integrity_proof=self._proof(unsigned))

    def _proof(self, selector: ScopeSelector) -> str:
        values = {
            name: getattr(selector, name)
            for name in selector.__dataclass_fields__
            if name != "integrity_proof"
        }
        material = b"dududa-memory-selector-v1\x00" + canonical_json_bytes(values)
        return (
            "hmac-sha256:"
            + hmac.new(self._secret, material, hashlib.sha256).hexdigest()
        )
