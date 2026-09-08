from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from dududa.domain.attachments import AttachmentIngestRequest, AttachmentOrigin
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import (
    AttachmentKind,
    AttachmentRef,
    Mention,
    MessageEnvelope,
    MessageReference,
)
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    RoleId,
    Sensitivity,
)
from dududa.errors import ErrorCategory, error
from dududa.ports.attachments import AttachmentRepository
from dududa.ports.context import ServiceCallContext
from dududa.runtime.state import ConnectorResult
from dududa.security.digests import scope_digest


class AttachmentSource(Protocol):
    def iter_bytes(
        self,
        component: object,
        *,
        maximum_size_bytes: int,
    ) -> AsyncIterator[bytes]: ...


class RejectingAttachmentSource:
    async def iter_bytes(
        self,
        component: object,
        *,
        maximum_size_bytes: int,
    ) -> AsyncIterator[bytes]:
        raise _connector_error("attachment_source_unavailable")
        yield b""  # pragma: no cover


class AstrBotInputConnector:
    def __init__(
        self,
        attachment_repository: AttachmentRepository,
        *,
        attachment_source: AttachmentSource | None = None,
        actor_resolver: Callable[[object, str, str, str], Actor] | None = None,
        persona_id: str = "dududa",
        maximum_attachment_bytes: int = 10 * 1024 * 1024,
        attachment_ttl: timedelta = timedelta(hours=1),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = attachment_repository
        self._source = attachment_source or RejectingAttachmentSource()
        self._actor_resolver = actor_resolver or _default_actor
        self._persona_id = persona_id
        self._maximum_attachment_bytes = maximum_attachment_bytes
        self._attachment_ttl = attachment_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._revision = ComponentRevision(
            "connector.astrbot",
            "0.1.0",
            "s04-v1",
            DigestString("builtin"),
        )
        self._history_provider = None

    async def convert(
        self,
        event: object,
        *,
        operation: ServiceCallContext,
    ) -> ConnectorResult:
        now = self._clock()
        if operation.cancellation.is_cancelled or operation.deadline <= now:
            raise _connector_error("connector_cancelled_or_expired")
        platform = _safe_call(event, "get_platform_id")
        bot_id = _safe_call(event, "get_self_id")
        user_id = _safe_call(event, "get_sender_id")
        group_id = _safe_call(event, "get_group_id")
        message_obj = getattr(event, "message_obj", None)
        message_id = str(getattr(message_obj, "message_id", "") or "").strip()
        if not all((platform, bot_id, user_id, message_id)):
            raise _connector_error("connector_identity_or_message_id_missing")
        if group_id:
            conversation_type = ConversationType.GROUP
            conversation_id = group_id
            normalized_group_id: str | None = group_id
        else:
            conversation_type = ConversationType.PRIVATE
            conversation_id = f"private:{user_id}"
            normalized_group_id = None
        scope = ConversationScope(
            platform,
            bot_id,
            conversation_type,
            conversation_id,
            normalized_group_id,
            self._persona_id,
        )
        actor = self._actor_resolver(event, platform, bot_id, user_id)
        components = tuple(_components(event, message_obj))
        _assert_no_dropped_attachments(message_obj, components)
        reply_to = _reply_reference(components, platform, bot_id, conversation_id)
        mentions = _mentions(components, platform)
        attachments: list[AttachmentRef] = []
        for index, component in enumerate(components):
            kind = _attachment_kind(component)
            if kind is None:
                continue
            declared_media_type = _media_type(component, kind)
            declared_size = _optional_nonnegative_int(
                getattr(component, "size", None)
                or getattr(component, "file_size", None)
            )
            content_id = f"{message_id}:{index}"
            ingest = AttachmentIngestRequest(
                schema_version=1,
                content_id=content_id,
                origin=AttachmentOrigin.PLATFORM_INPUT,
                scope_digest=scope_digest(scope),
                declared_media_type=declared_media_type,
                declared_size_bytes=declared_size,
                maximum_size_bytes=self._maximum_attachment_bytes,
                sensitivity=Sensitivity.PERSONAL,
                expires_at=now + self._attachment_ttl,
                idempotency_key=f"{platform}:{bot_id}:{conversation_id}:{content_id}",
            )
            try:
                stored = await self._repository.ingest_input(
                    ingest,
                    self._source.iter_bytes(
                        component,
                        maximum_size_bytes=self._maximum_attachment_bytes,
                    ),
                    operation=operation,
                )
            except Exception as exc:
                if getattr(exc, "info", None) is not None:
                    raise
                raise _connector_error("attachment_ingest_failed") from None
            attachments.append(
                AttachmentRef(
                    attachment_id=content_id,
                    kind=kind,
                    media_type=stored.media_type,
                    size_bytes=stored.size_bytes,
                    content_ref=stored.content_ref,
                    content_digest=stored.content_digest,
                )
            )
        envelope = MessageEnvelope(
            schema_version=1,
            message_id=message_id,
            platform=platform,
            bot_id=bot_id,
            conversation_type=conversation_type,
            conversation_id=conversation_id,
            group_id=normalized_group_id,
            user_id=user_id,
            reply_to=reply_to,
            timestamp=_message_timestamp(event, message_obj),
            text=str(getattr(event, "message_str", "") or ""),
            attachments=tuple(attachments),
            mentions=mentions,
            metadata={
                "adapter_type": _safe_call(event, "get_platform_name"),
                "message_type": str(_safe_call(event, "get_message_type")),
                "recent_context": await self._recent_group_context(event, operation),
                "reply_guidance": await self._reply_guidance(event),
            },
        )
        return ConnectorResult(1, envelope, actor, now, self._revision)

    async def _reply_guidance(self, event: object) -> str:
        try:
            get_extra = getattr(event, "get_extra", None)
            if not callable(get_extra):
                return ""
            value = get_extra("reply_guidance")
            return str(value or "")[:600]
        except Exception:  # noqa: BLE001 - guidance never blocks intake
            return ""

    async def _recent_group_context(
        self,
        event: object,
        operation: ServiceCallContext,
    ) -> str:
        """Fetch a compact recent group-chat window for conversational grounding."""
        try:
            group_id = _safe_call(event, "get_group_id")
            if not group_id:
                return ""
            if self._history_provider is None:
                from .proactive_talk import AstrBotGroupHistoryProvider

                self._history_provider = AstrBotGroupHistoryProvider()
            lines = await self._history_provider.recent_lines(
                event,
                message_limit=10,
                byte_limit=2000,
            )
            if not lines:
                return ""
            return "\n".join(lines[-10:])
        except Exception:  # noqa: BLE001 - context grounding never blocks intake
            return ""


def _default_actor(event: object, platform: str, bot_id: str, user_id: str) -> Actor:
    try:
        is_admin = bool(getattr(event, "is_admin")())
    except Exception:
        is_admin = False
    role = RoleId("admin" if is_admin else "normal_user")
    return Actor(platform, bot_id, user_id, frozenset({role}), frozenset())


def _safe_call(value: object, name: str) -> str:
    try:
        result = getattr(value, name)()
    except Exception:
        return ""
    return str(result or "").strip()


def _components(event: object, message_obj: object) -> list[object]:
    try:
        values = getattr(event, "get_messages")()
    except Exception:
        values = getattr(message_obj, "message", ())
    if not isinstance(values, (list, tuple)):
        raise _connector_error("invalid_message_chain")
    return list(values)


def _reply_reference(
    components: tuple[object, ...],
    platform: str,
    bot_id: str,
    conversation_id: str,
) -> MessageReference | None:
    for component in components:
        if type(component).__name__ != "Reply":
            continue
        message_id = str(
            getattr(component, "id", None)
            or getattr(component, "message_id", None)
            or ""
        ).strip()
        if not message_id:
            raise _connector_error("reply_message_id_missing")
        # AstrBot's Reply component does not always carry source metadata.  In
        # that common case preserve the existing same-scope behaviour.  When a
        # component does expose a group, however, never turn a cross-group
        # reference into a handle in the current conversation: the downstream
        # Context Builder cannot safely dereference it.
        source_group = getattr(component, "group_id", None)
        if source_group is None:
            source_group = getattr(component, "group", None)
        if source_group is not None:
            normalized_group = str(source_group).strip()
            if normalized_group and normalized_group != conversation_id:
                raise _connector_error("reply_scope_mismatch")
        return MessageReference(platform, bot_id, conversation_id, message_id)
    return None


def _mentions(components: tuple[object, ...], platform: str) -> tuple[Mention, ...]:
    result: list[Mention] = []
    for component in components:
        name = type(component).__name__
        if name == "At":
            user_id = str(getattr(component, "qq", "") or "").strip()
            if not user_id:
                raise _connector_error("mention_user_id_missing")
            result.append(Mention(platform, user_id, getattr(component, "name", None)))
        elif name == "AtAll":
            result.append(Mention(platform, "all", "@all"))
    return tuple(result)


def _attachment_kind(component: object) -> AttachmentKind | None:
    return {
        "Image": AttachmentKind.IMAGE,
        "Record": AttachmentKind.AUDIO,
        "Video": AttachmentKind.VIDEO,
        "File": AttachmentKind.FILE,
    }.get(type(component).__name__)


def _media_type(component: object, kind: AttachmentKind) -> str:
    declared = getattr(component, "media_type", None) or getattr(component, "mime_type", None)
    if isinstance(declared, str) and declared.strip():
        return declared.strip().lower()
    return {
        AttachmentKind.IMAGE: "image/jpeg",
        AttachmentKind.AUDIO: "audio/mpeg",
        AttachmentKind.VIDEO: "video/mp4",
        AttachmentKind.FILE: "application/octet-stream",
    }[kind]


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if type(value) is not int or value < 0:
        raise _connector_error("invalid_declared_attachment_size")
    return value


def _message_timestamp(event: object, message_obj: object) -> datetime:
    raw = getattr(message_obj, "raw_message", None)
    candidate = raw.get("time") if isinstance(raw, dict) else None
    if candidate is None:
        candidate = getattr(message_obj, "timestamp", None)
    if candidate is None:
        candidate = getattr(event, "created_at", None)
    if isinstance(candidate, datetime):
        if candidate.tzinfo is None or candidate.utcoffset() is None:
            raise _connector_error("naive_platform_timestamp")
        return candidate
    if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
        try:
            return datetime.fromtimestamp(candidate, timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    raise _connector_error("invalid_platform_timestamp")


def _assert_no_dropped_attachments(message_obj: object, components: tuple[object, ...]) -> None:
    raw = getattr(message_obj, "raw_message", None)
    raw_segments = raw.get("message") if isinstance(raw, dict) else None
    if not isinstance(raw_segments, list):
        return
    raw_count = sum(
        1
        for segment in raw_segments
        if isinstance(segment, dict)
        and str(segment.get("type", "")).lower() in {"image", "record", "video", "file"}
    )
    converted_count = sum(_attachment_kind(item) is not None for item in components)
    if raw_count > converted_count:
        raise _connector_error("attachment_component_missing")


def _connector_error(code: str):
    return error(code, ErrorCategory.VALIDATION, "connector.message_rejected")
