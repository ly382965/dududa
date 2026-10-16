from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from dududa._compat import StrEnum
from dududa.errors import validation_error

from .primitives import (
    ConversationType,
    DigestString,
    JsonValue,
    freeze_json,
    require_aware,
    require_non_empty,
)


class AttachmentKind(StrEnum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"


@dataclass(frozen=True, slots=True)
class MessageReference:
    platform: str
    bot_id: str
    conversation_id: str
    message_id: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("platform", self.platform),
            ("bot_id", self.bot_id),
            ("conversation_id", self.conversation_id),
            ("message_id", self.message_id),
        ):
            require_non_empty(value, field_name)


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    attachment_id: str
    kind: AttachmentKind
    media_type: str
    size_bytes: int | None
    content_ref: str | None
    content_digest: DigestString | None
    summary: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.attachment_id, "attachment_id")
        if not isinstance(self.kind, AttachmentKind):
            raise validation_error("invalid_attachment_kind")
        require_non_empty(self.media_type, "media_type")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise validation_error("negative_attachment_size")
        if (self.content_ref is None) != (self.content_digest is None):
            raise validation_error("incomplete_attachment_content_ref")


@dataclass(frozen=True, slots=True)
class Mention:
    platform: str
    user_id: str
    display_text: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.platform, "platform")
        require_non_empty(self.user_id, "user_id")


@dataclass(frozen=True, slots=True)
class MessageDedupKey:
    platform: str
    bot_id: str
    conversation_id: str
    message_id: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("platform", self.platform),
            ("bot_id", self.bot_id),
            ("conversation_id", self.conversation_id),
            ("message_id", self.message_id),
        ):
            require_non_empty(value, field_name)


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    schema_version: int
    message_id: str
    platform: str
    bot_id: str
    conversation_type: ConversationType
    conversation_id: str
    group_id: str | None
    user_id: str
    reply_to: MessageReference | None
    timestamp: datetime
    text: str
    attachments: tuple[AttachmentRef, ...] = ()
    mentions: tuple[Mention, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        for field_name, value in (
            ("message_id", self.message_id),
            ("platform", self.platform),
            ("bot_id", self.bot_id),
            ("conversation_id", self.conversation_id),
            ("user_id", self.user_id),
        ):
            require_non_empty(value, field_name)
        require_aware(self.timestamp, "timestamp")
        if not isinstance(self.conversation_type, ConversationType):
            raise validation_error("invalid_conversation_type")
        if (
            self.conversation_type is ConversationType.PRIVATE
            and self.conversation_id.strip().lower() == "private"
        ):
            raise validation_error("ambiguous_private_conversation_id")
        if self.conversation_type is ConversationType.GROUP:
            if not self.group_id or self.group_id != self.conversation_id:
                raise validation_error("invalid_group_envelope")
        elif self.group_id is not None:
            raise validation_error("non_group_envelope_forbids_group_id")
        if self.reply_to is not None:
            if (
                self.reply_to.platform != self.platform
                or self.reply_to.bot_id != self.bot_id
                or self.reply_to.conversation_id != self.conversation_id
            ):
                raise validation_error("cross_scope_reply_reference")
        attachments = tuple(self.attachments)
        mentions = tuple(self.mentions)
        if len({item.attachment_id for item in attachments}) != len(attachments):
            raise validation_error("duplicate_attachment_id")
        if any(item.platform != self.platform for item in mentions):
            raise validation_error("cross_platform_mention")
        object.__setattr__(self, "attachments", attachments)
        object.__setattr__(self, "mentions", mentions)
        object.__setattr__(self, "metadata", freeze_json(dict(self.metadata)))

    @property
    def dedup_key(self) -> MessageDedupKey:
        return MessageDedupKey(
            platform=self.platform,
            bot_id=self.bot_id,
            conversation_id=self.conversation_id,
            message_id=self.message_id,
        )
