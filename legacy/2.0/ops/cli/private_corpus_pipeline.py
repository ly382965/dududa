"""Build Dududa's private, offline historical group-corpus demo.

Raw and derived chat text stays under the configured private output directory.
Nothing in this module connects to QQ, NapCat, MCP, Memory, or production routing.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import random
import re
import sys
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dududa.domain.primitives import (
    ConversationType,
    DigestString,
    PrivacyLevel,
)
from dududa.perception.contracts import (
    PerceptionContext,
    PerceptionIdentity,
    PerceptionLimits,
    PerceptionMessage,
)
from dududa.perception.digests import perception_context_digest
from dududa.runtime.perception import serialize_perception_context

DEFAULT_INPUT = Path("/home/mmdustc/temp")
DEFAULT_OUTPUT = Path(
    "/home/mmdustc/.local/share/dududa/private-datasets/"
    "external-chat-20260815"
)
SOURCE_RE = re.compile(
    r"^(?P<kind>group|friend)_(?P<body>.+?)_"
    r"(?P<date>\d{8})_(?P<time>\d{6})"
    r"(?P<suffix>_chunked_jsonl|_streaming|_[^.]+)?(?:\.[^.]+)?$"
)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
QQ_RE = re.compile(r"(?<!\d)\d{6,12}(?!\d)")
URL_QUERY_RE = re.compile(r"(https?://[^\s?#]+)(?:\?[^\s#]*)?(?:#[^\s]*)?")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
ATTACHMENT_MARKERS = {
    "IMAGE": "[图片]",
    "AUDIO": "[语音]",
    "VIDEO": "[视频]",
    "FILE": "[文件]",
}
JSON_ATTACHMENT_TYPES = {
    "image": "IMAGE",
    "audio": "AUDIO",
    "video": "VIDEO",
    "file": "FILE",
}
BUCKETS = (
    "short_chat",
    "ordinary_qa",
    "long_complex",
    "campus_retrieval",
    "programming",
    "tool_candidate",
    "multi_speaker",
    "ambiguous_reference",
    "media_emoji_boundary",
    "ordinary_group_negative",
)
TEACHER_PROMPT_REVISION = "s23-terra-silver-v2"
TEACHER_MODEL_DEFAULT = "gpt-5.6-terra"
TRANSIENT_HTTP_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
TASK_KINDS = (
    "conversation",
    "retrieval",
    "coding",
    "analysis",
    "creative",
    "coordination",
    "other",
)
TOOL_NEED_KINDS = ("none", "search", "campus", "course", "code", "other")


class CorpusError(RuntimeError):
    """A local private-corpus pipeline error."""


@dataclass(slots=True)
class OpaqueRegistry:
    values: dict[str, dict[str, str]] = field(default_factory=dict)
    reverse: dict[str, dict[str, str]] = field(default_factory=dict)

    def get(self, kind: str, raw: object, *, width: int = 0) -> str:
        raw_value = str(raw)
        mapping = self.values.setdefault(kind, {})
        existing = mapping.get(raw_value)
        if existing is not None:
            return existing
        number = len(mapping) + 1
        suffix = f"{number:0{width}d}" if width else str(number)
        value = f"{kind}-{suffix}"
        mapping[raw_value] = value
        self.reverse.setdefault(kind, {})[value] = raw_value
        return value

    def export(self) -> dict[str, dict[str, str]]:
        return {
            kind: dict(sorted(mapping.items(), key=lambda item: item[1]))
            for kind, mapping in sorted(self.reverse.items())
        }


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    path: Path
    relative_path: str
    source_kind: str
    conversation_kind: str
    conversation_key: str
    priority: int


@dataclass(slots=True)
class HtmlMessageParser(HTMLParser):
    _VOID_TAGS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    messages: list[dict[str, object]] = field(default_factory=list)
    _stack: list[tuple[str, frozenset[str], dict[str, str]]] = field(
        default_factory=list
    )
    _message_depth: int | None = None
    _current: dict[str, object] | None = None

    def __post_init__(self) -> None:
        HTMLParser.__init__(self, convert_charrefs=True)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        classes = frozenset(attr_map.get("class", "").split())
        is_message_root = (
            tag == "div"
            and "message" in classes
            and attr_map.get("id", "").startswith("msg-")
        )
        if is_message_root and self._current is not None:
            # Some QQ HTML exports contain unbalanced markup. A new root message
            # is an unambiguous boundary, so retain the prior message instead of
            # letting one malformed subtree swallow the rest of the file.
            self._finish_current()
        if tag not in self._VOID_TAGS:
            self._stack.append((tag, classes, attr_map))
        if is_message_root:
            self._message_depth = len(self._stack)
            self._current = {
                "id": attr_map["id"][4:],
                "sender_uid": (
                    attr_map.get("data-sender-uid")
                    or attr_map.get("data-uid")
                    or ""
                ),
                "self": "self" in classes,
                "system": "system" in classes,
                "date": attr_map.get("data-date", ""),
                "sender": [],
                "time": [],
                "text": [],
                "reply_to": None,
                "mentions": [],
                "attachments": set(),
            }
        if self._current is None:
            return
        if "reply-content" in classes:
            reply_to = attr_map.get("data-reply-to") or attr_map.get(
                "data-message-id"
            )
            if reply_to:
                self._current["reply_to"] = reply_to.removeprefix("msg-")
        if "at-mention" in classes:
            mention = (
                attr_map.get("data-uid")
                or attr_map.get("data-uin")
                or attr_map.get("data-target-uid")
            )
            if mention:
                cast_list(self._current["mentions"]).append(mention)
        class_text = " ".join(classes).lower()
        for marker, kind in (
            ("image", "IMAGE"),
            ("audio", "AUDIO"),
            ("voice", "AUDIO"),
            ("video", "VIDEO"),
            ("file", "FILE"),
        ):
            if marker in class_text:
                cast_set(self._current["attachments"]).add(kind)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._current is None or not data:
            return
        active_classes = set().union(*(item[1] for item in self._stack))
        if "text-content" in active_classes:
            cast_list(self._current["text"]).append(data)
        elif "sender" in active_classes:
            cast_list(self._current["sender"]).append(data)
        elif "time" in active_classes:
            cast_list(self._current["time"]).append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        match_index = next(
            (
                index
                for index in range(len(self._stack) - 1, -1, -1)
                if self._stack[index][0] == tag
            ),
            None,
        )
        if match_index is None:
            return
        if (
            self._current is not None
            and self._message_depth is not None
            and match_index + 1 <= self._message_depth
        ):
            self._finish_current()
        del self._stack[match_index:]

    def close(self) -> None:
        HTMLParser.close(self)
        if self._current is not None:
            self._finish_current()

    def _finish_current(self) -> None:
        current = self._current
        if current is None:
            return
        current["sender"] = "".join(cast_list(current["sender"])).strip()
        current["time"] = "".join(cast_list(current["time"])).strip()
        current["text"] = html.unescape(
            "".join(cast_list(current["text"])).strip()
        )
        current["mentions"] = sorted(set(cast_list(current["mentions"])))
        current["attachments"] = sorted(cast_set(current["attachments"]))
        self.messages.append(current)
        self._current = None
        self._message_depth = None


def cast_list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError("expected list")
    return value


def cast_set(value: object) -> set[Any]:
    if not isinstance(value, set):
        raise TypeError("expected set")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            )
            handle.write("\n")
            count += 1
    return count


def read_jsonl(path: Path) -> Iterator[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CorpusError(f"invalid_jsonl:{path.name}:{line_number}") from exc
            if not isinstance(value, dict):
                raise CorpusError(f"invalid_jsonl_object:{path.name}:{line_number}")
            yield value


def source_identity(path: Path, root: Path) -> tuple[str, str] | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    top = relative.parts[0]
    match = SOURCE_RE.match(top)
    if match is None:
        return None
    kind = match.group("kind")
    body = match.group("body")
    if kind == "group":
        peer = body.rsplit("_", maxsplit=1)[-1]
    else:
        peer = body
    return kind, peer


def discover_sources(root: Path) -> list[SourceDescriptor]:
    sources: list[SourceDescriptor] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        identity = source_identity(child, root)
        if identity is None:
            continue
        conversation_kind, conversation_key = identity
        relative = child.relative_to(root).as_posix()
        if child.is_dir() and child.name.endswith("_chunked_jsonl"):
            source_kind = "directory_jsonl"
            priority = 1
        elif child.is_file() and child.suffix.lower() == ".zip":
            source_kind = "streaming_zip"
            priority = 2
        elif child.is_file() and child.suffix.lower() in {".html", ".htm"}:
            source_kind = "html"
            priority = 3
        else:
            continue
        sources.append(
            SourceDescriptor(
                child,
                relative,
                source_kind,
                conversation_kind,
                conversation_key,
                priority,
            )
        )
    return sorted(sources, key=lambda item: (item.priority, item.relative_path))


def inventory(input_root: Path, output_root: Path) -> dict[str, object]:
    files = sorted(path for path in input_root.rglob("*") if path.is_file())
    by_extension: Counter[str] = Counter()
    total_bytes = 0
    for path in files:
        total_bytes += path.stat().st_size
        suffix = path.suffix.lower().lstrip(".") or "no_extension"
        if path.name == "manifest.json":
            suffix = "manifest_json"
        by_extension[suffix] += 1
    sources = discover_sources(input_root)
    source_counts = Counter(source.source_kind for source in sources)
    conversation_counts = Counter(
        source.conversation_kind
        for source in {
            (item.conversation_kind, item.conversation_key): item
            for item in sources
        }.values()
    )
    report = {
        "schema_version": 1,
        "dataset_kind": "private_historical_group_export",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files_by_kind": dict(sorted(by_extension.items())),
        "export_sources": dict(sorted(source_counts.items())),
        "conversations": dict(sorted(conversation_counts.items())),
        "private_chat_excluded": conversation_counts.get("friend", 0),
        "claims": {
            "current_dududa_bot_traffic": False,
            "qq_access_performed": False,
            "remote_content_fetched": False,
        },
    }
    write_json(output_root / "inventory.json", report)
    return report


def _manifest(source: SourceDescriptor) -> dict[str, object]:
    if source.source_kind != "directory_jsonl":
        return {}
    path = source.path / "manifest.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _iter_json_records(
    source: SourceDescriptor,
) -> Iterator[tuple[dict[str, object], int]]:
    ordinal = 0
    if source.source_kind == "directory_jsonl":
        paths = sorted(source.path.glob("chunks/*.jsonl"))
        for path in paths:
            with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
                for line in handle:
                    ordinal += 1
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if isinstance(value, dict):
                        yield value, ordinal
    elif source.source_kind == "streaming_zip":
        with zipfile.ZipFile(source.path) as archive:
            names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("message_batches/") and name.endswith(".jsonl")
            )
            for name in names:
                with archive.open(name) as raw:
                    for raw_line in raw:
                        ordinal += 1
                        line = raw_line.decode("utf-8-sig", errors="replace")
                        if not line.strip():
                            continue
                        value = json.loads(line)
                        if isinstance(value, dict):
                            yield value, ordinal


def _iter_html_records(
    source: SourceDescriptor,
) -> Iterator[tuple[dict[str, object], int]]:
    parser = HtmlMessageParser()
    parser.feed(source.path.read_text(encoding="utf-8", errors="replace"))
    parser.close()
    local_zone = ZoneInfo("Asia/Shanghai")
    for ordinal, item in enumerate(parser.messages, start=1):
        time_text = str(item.get("time") or "")
        timestamp = 0
        for format_string in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(time_text, format_string).replace(
                    tzinfo=local_zone
                )
                timestamp = int(parsed.timestamp() * 1000)
                break
            except ValueError:
                continue
        yield (
            {
                "id": item.get("id"),
                "seq": str(ordinal),
                "timestamp": timestamp,
                "sender": {
                    "uid": item.get("sender_uid"),
                    "name": item.get("sender"),
                },
                "type": "system" if item.get("system") else "html",
                "content": {
                    "text": item.get("text"),
                    "elements": [
                        {"type": str(kind).lower(), "data": {}}
                        for kind in item.get("attachments", [])
                    ],
                    "mentions": [
                        {"uid": value} for value in item.get("mentions", [])
                    ],
                },
                "recalled": False,
                "system": bool(item.get("system")),
                "reply_to": item.get("reply_to"),
                "html_self": bool(item.get("self")),
            },
            ordinal,
        )


def _raw_sender(record: Mapping[str, object], source_ref: str, ordinal: int) -> str:
    sender = record.get("sender")
    if isinstance(sender, Mapping):
        uid = str(sender.get("uid") or "").strip()
        uin = str(sender.get("uin") or "").strip()
        if uid and uid not in {"未知", "0"}:
            return f"uid:{uid}"
        if uin and uin != "0":
            return f"uin:{uin}"
    return f"unknown:{source_ref}:{ordinal}"


def _element_data(element: object) -> tuple[str, Mapping[str, object]]:
    if not isinstance(element, Mapping):
        return "", {}
    kind = str(element.get("type") or "").strip().lower()
    data = element.get("data")
    return kind, data if isinstance(data, Mapping) else {}


def _normalize_record(
    *,
    record: Mapping[str, object],
    source: SourceDescriptor,
    source_ref: str,
    conversation_ref: str,
    ordinal: int,
    registry: OpaqueRegistry,
    self_ids: frozenset[str],
) -> dict[str, object]:
    raw_message_id = str(record.get("id") or "").strip()
    if not raw_message_id:
        raw_message_id = f"missing:{source_ref}:{ordinal}"
    message_ref = registry.get(
        "message",
        f"{source.conversation_kind}:{source.conversation_key}:{raw_message_id}",
        width=8,
    )
    raw_sender = _raw_sender(record, source_ref, ordinal)
    sender_ref = registry.get("identity", raw_sender, width=6)
    sender = record.get("sender")
    sender_values: set[str] = set()
    if isinstance(sender, Mapping):
        for key in ("uid", "uin"):
            value = str(sender.get(key) or "").strip()
            if value:
                sender_values.add(value)
    content = record.get("content")
    if not isinstance(content, Mapping):
        content = {}
    recalled = bool(record.get("recalled"))
    text = "" if recalled else str(content.get("text") or "")
    elements = content.get("elements")
    if not isinstance(elements, Sequence) or isinstance(elements, (str, bytes)):
        elements = ()
    attachments: set[str] = set()
    raw_mentions: set[str] = set()
    mention_all = False
    reply_raw: str | None = None
    has_system_element = False
    for element in elements:
        kind, data = _element_data(element)
        attachment = JSON_ATTACHMENT_TYPES.get(kind)
        if attachment:
            attachments.add(attachment)
        if kind == "system":
            has_system_element = True
        if kind == "reply":
            reply_raw = str(
                data.get("referencedMessageId") or data.get("messageId") or ""
            ).strip() or reply_raw
        if kind == "at":
            if str(data.get("atType") or "").lower() in {"all", "everyone"}:
                mention_all = True
            else:
                raw_mention = str(data.get("uid") or data.get("uin") or "").strip()
                if raw_mention:
                    raw_mentions.add(raw_mention)
    content_mentions = content.get("mentions")
    if isinstance(content_mentions, Sequence) and not isinstance(
        content_mentions, (str, bytes)
    ):
        for mention in content_mentions:
            if not isinstance(mention, Mapping):
                continue
            if str(mention.get("atType") or "").lower() in {"all", "everyone"}:
                mention_all = True
                continue
            raw_mention = str(
                mention.get("uid") or mention.get("uin") or mention.get("target") or ""
            ).strip()
            if raw_mention:
                raw_mentions.add(raw_mention)
    reply_raw = str(record.get("reply_to") or reply_raw or "").strip() or None
    reply_to_ref = (
        registry.get(
            "message",
            f"{source.conversation_kind}:{source.conversation_key}:{reply_raw}",
            width=8,
        )
        if reply_raw
        else None
    )
    mention_refs = tuple(
        sorted(
            registry.get("identity", f"uid:{value}", width=6)
            for value in raw_mentions
        )
    )
    message_type = str(record.get("type") or "").lower()
    system = (
        bool(record.get("system"))
        or message_type == "system"
        or has_system_element
    )
    timestamp = record.get("timestamp")
    try:
        timestamp_ms = int(timestamp or 0)
    except (TypeError, ValueError):
        timestamp_ms = 0
    return {
        "schema_version": 1,
        "source_ref": source_ref,
        "conversation_ref": conversation_ref,
        "message_ref": message_ref,
        "normalized_message_id": raw_message_id,
        "sender_ref": sender_ref,
        "timestamp_ms": timestamp_ms,
        "seq": str(record.get("seq") or ordinal),
        "self_authored": bool(record.get("html_self"))
        or bool(sender_values.intersection(self_ids)),
        "text": text,
        "reply_to_ref": reply_to_ref,
        "reply_unresolved": False,
        "mention_refs": list(mention_refs),
        "mention_all": mention_all,
        "attachment_kinds": sorted(attachments),
        "source_format": source.source_kind,
        "source_ordinal": ordinal,
        "recalled": recalled,
        "system": system,
        "conflict_flags": [],
    }


def _comparison_fields(message: Mapping[str, object]) -> dict[str, object]:
    return {
        key: message.get(key)
        for key in (
            "timestamp_ms",
            "sender_ref",
            "text",
            "reply_to_ref",
            "mention_refs",
            "mention_all",
            "attachment_kinds",
            "recalled",
            "system",
        )
    }


def extract(input_root: Path, output_root: Path) -> dict[str, object]:
    sources = discover_sources(input_root)
    registry = OpaqueRegistry()
    selected: dict[tuple[str, str], dict[str, object]] = {}
    source_rows: list[dict[str, object]] = []
    excluded_rows: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    stats: Counter[str] = Counter()
    source_record_counts: Counter[str] = Counter()
    for source in sources:
        source_ref = registry.get("source", source.relative_path, width=4)
        conversation_ref = registry.get(
            "conversation",
            f"{source.conversation_kind}:{source.conversation_key}",
            width=4,
        )
        source_rows.append(
            {
                "schema_version": 1,
                "source_ref": source_ref,
                "source_format": source.source_kind,
                "conversation_ref": conversation_ref,
                "excluded": source.conversation_kind != "group",
            }
        )
        if source.conversation_kind != "group":
            stats["excluded_private_sources"] += 1
            excluded_rows.append(
                {
                    "schema_version": 1,
                    "source_ref": source_ref,
                    "conversation_ref": conversation_ref,
                    "reason": "private_chat",
                }
            )
            continue
        manifest = _manifest(source)
        chat_info = manifest.get("chatInfo") if isinstance(manifest, Mapping) else {}
        if not isinstance(chat_info, Mapping):
            chat_info = {}
        self_ids = frozenset(
            str(value).strip()
            for value in (chat_info.get("selfUid"), chat_info.get("selfUin"))
            if str(value or "").strip()
        )
        try:
            iterator = (
                _iter_html_records(source)
                if source.source_kind == "html"
                else _iter_json_records(source)
            )
            any_record = False
            for record, ordinal in iterator:
                any_record = True
                stats["records_seen"] += 1
                source_record_counts[source_ref] += 1
                try:
                    message = _normalize_record(
                        record=record,
                        source=source,
                        source_ref=source_ref,
                        conversation_ref=conversation_ref,
                        ordinal=ordinal,
                        registry=registry,
                        self_ids=self_ids,
                    )
                except (TypeError, ValueError, KeyError):
                    stats["malformed_records"] += 1
                    continue
                key = (
                    str(message["conversation_ref"]),
                    str(message["normalized_message_id"]),
                )
                prior = selected.get(key)
                if prior is None:
                    selected[key] = message
                    stats[f"selected_{source.source_kind}"] += 1
                    if source.priority > 1:
                        stats["supplement_records"] += 1
                    continue
                stats["duplicate_records"] += 1
                prior_fields = _comparison_fields(prior)
                message_fields = _comparison_fields(message)
                differing = sorted(
                    key for key in prior_fields if prior_fields[key] != message_fields[key]
                )
                if differing:
                    stats["conflict_records"] += 1
                    prior_flags = prior.get("conflict_flags")
                    if isinstance(prior_flags, list):
                        prior_flags.extend(
                            value for value in differing if value not in prior_flags
                        )
                    conflicts.append(
                        {
                            "schema_version": 1,
                            "conversation_ref": prior["conversation_ref"],
                            "message_ref": prior["message_ref"],
                            "selected_source_ref": prior["source_ref"],
                            "conflicting_source_ref": message["source_ref"],
                            "conflict_fields": differing,
                        }
                    )
            if not any_record:
                stats["empty_sources"] += 1
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
            stats["broken_sources"] += 1
    messages = sorted(
        selected.values(),
        key=lambda item: (
            str(item["conversation_ref"]),
            int(item["timestamp_ms"]),
            _sortable_seq(str(item["seq"])),
            int(item["source_ordinal"]),
        ),
    )
    known_refs = {str(item["message_ref"]) for item in messages}
    for message in messages:
        reply = message.get("reply_to_ref")
        if reply is not None and str(reply) not in known_refs:
            message["reply_unresolved"] = True
            stats["unresolved_replies"] += 1
        if message["system"]:
            stats["system_messages"] += 1
        if message["recalled"]:
            stats["recalled_messages"] += 1
        if message["self_authored"]:
            stats["self_authored_messages"] += 1
        if not message["text"] and message["attachment_kinds"]:
            stats["attachment_only_messages"] += 1
        # The raw exporter message ID was needed for deterministic deduplication
        # only. Keep it in the private identity map, not in normalized rows.
        message.pop("normalized_message_id", None)
    write_jsonl(output_root / "normalized/messages.jsonl", messages)
    write_jsonl(output_root / "normalized/conflicts.jsonl", conflicts)
    write_jsonl(output_root / "normalized/excluded.jsonl", excluded_rows)
    write_jsonl(output_root / "normalized/raw-sources.jsonl", source_rows)
    write_json(
        output_root / "identity-map.json",
        {
            "schema_version": 1,
            "private": True,
            "mappings": registry.export(),
        },
    )
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "unique_messages": len(messages),
        "group_conversations": len(
            {item["conversation_ref"] for item in messages}
        ),
        "sources_with_records": sum(value > 0 for value in source_record_counts.values()),
        "counts": dict(sorted(stats.items())),
        "source_formats": dict(
            sorted(Counter(item["source_format"] for item in messages).items())
        ),
        "time_range": _time_range(messages),
        "privacy": {
            "opaque_identifiers": True,
            "identity_map_private": True,
            "private_chat_excluded": True,
            "not_current_dududa_bot_traffic": True,
        },
    }
    write_json(output_root / "reports/intake-summary.json", report)
    return report


def _sortable_seq(value: str) -> tuple[int, str]:
    try:
        return int(value), ""
    except ValueError:
        return sys.maxsize, value


def _time_range(messages: Sequence[Mapping[str, object]]) -> dict[str, str | None]:
    values = [int(item["timestamp_ms"]) for item in messages if int(item["timestamp_ms"]) > 0]
    if not values:
        return {"start": None, "end": None}
    return {
        "start": datetime.fromtimestamp(min(values) / 1000, timezone.utc).isoformat(),
        "end": datetime.fromtimestamp(max(values) / 1000, timezone.utc).isoformat(),
    }


def _display_text(message: Mapping[str, object], *, limit: int = 2_000) -> str:
    text = str(message.get("text") or "").strip()
    if not text:
        markers = [
            ATTACHMENT_MARKERS.get(str(kind), f"[{kind}]")
            for kind in message.get("attachment_kinds", [])
        ]
        text = " ".join(markers)
    if not text and message.get("recalled"):
        text = "[已撤回]"
    if not text and message.get("system"):
        text = "[系统消息]"
    return text[:limit]


def _bucket_window(messages: Sequence[Mapping[str, object]]) -> list[str]:
    current = messages[-1]
    text = str(current.get("text") or "")
    joined = "\n".join(str(item.get("text") or "") for item in messages)
    buckets: list[str] = []
    if len(text.strip()) <= 18:
        buckets.append("short_chat")
    if re.search(r"[?？]|(?:吗|呢|怎么|如何|为什么|哪[个里]|多少|是否)", text):
        buckets.append("ordinary_qa")
    if len(text) >= 240 or len(joined) >= 1_800:
        buckets.append("long_complex")
    if re.search(r"课程|选课|评课|教务|学院|校园|考试|老师|宿舍|学分|成绩", joined):
        buckets.append("campus_retrieval")
    if re.search(
        r"代码|编程|python|java|rust|typescript|github|api|bug|模型|agent|llm",
        joined,
        re.IGNORECASE,
    ):
        buckets.append("programming")
    if re.search(
        r"最新|实时|搜索|查一下|天气|新闻|论文|arxiv|工具|网页",
        text,
        re.IGNORECASE,
    ):
        buckets.append("tool_candidate")
    if len({str(item["sender_ref"]) for item in messages}) >= 3:
        buckets.append("multi_speaker")
    if current.get("reply_unresolved") or re.search(
        r"^(这|那|它|他|她|这个|那个|上面|前面|所以呢|然后呢)", text.strip()
    ):
        buckets.append("ambiguous_reference")
    if any(item.get("attachment_kinds") for item in messages) or EMOJI_RE.search(joined):
        buckets.append("media_emoji_boundary")
    if not buckets:
        buckets.append("ordinary_group_negative")
    return [bucket for bucket in BUCKETS if bucket in buckets]


def _context_from_window(
    window_id: str, conversation_ref: str, messages: Sequence[Mapping[str, object]]
) -> PerceptionContext:
    bot_ref = "identity:bot-candidate"
    included_refs = {str(item["message_ref"]) for item in messages}
    identity_refs = sorted({str(item["sender_ref"]) for item in messages})
    identities = [PerceptionIdentity(1, bot_ref, True)]
    identities.extend(PerceptionIdentity(1, value, False) for value in identity_refs)
    perception_messages: list[PerceptionMessage] = []
    known_refs: set[str] = set()
    for item in messages:
        message_ref = str(item["message_ref"])
        reply_to = item.get("reply_to_ref")
        reply_ref = (
            str(reply_to)
            if reply_to is not None
            and str(reply_to) in included_refs
            and str(reply_to) in known_refs
            else None
        )
        mentions = tuple(
            sorted(
                str(value)
                for value in item.get("mention_refs", [])
                if str(value) in identity_refs
            )
        )
        perception_messages.append(
            PerceptionMessage(
                1,
                message_ref,
                str(item["sender_ref"]),
                _display_text(item),
                reply_ref,
                mentions,
                False,
            )
        )
        known_refs.add(message_ref)
    total_chars = sum(len(item.text) for item in perception_messages)
    return PerceptionContext(
        1,
        f"context:{window_id}",
        DigestString(f"scope:{conversation_ref}"),
        ConversationType.GROUP,
        tuple(identities),
        tuple(perception_messages),
        perception_messages[-1].message_ref,
        bot_ref,
        PerceptionLimits(1, 12, 32, 8_000, 64_000, 16, 8, 64, 16),
        (),
        (),
        max(1, (total_chars + 3) // 4),
        PrivacyLevel.CONVERSATION,
    )


def _window_row(
    number: int, conversation_ref: str, messages: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    window_id = f"window-{number:08d}"
    context = _context_from_window(window_id, conversation_ref, messages)
    serialized = json.loads(serialize_perception_context(context))
    compact_messages = [
        {
            "message_ref": str(item["message_ref"]),
            "sender_ref": str(item["sender_ref"]),
            "timestamp_ms": int(item["timestamp_ms"]),
            "text": _display_text(item),
            "reply_to_ref": item.get("reply_to_ref"),
            "mention_refs": item.get("mention_refs", []),
            "attachment_kinds": item.get("attachment_kinds", []),
            "self_authored": bool(item.get("self_authored")),
        }
        for item in messages
    ]
    buckets = _bucket_window(messages)
    return {
        "schema_version": 1,
        "window_id": window_id,
        "conversation_ref": conversation_ref,
        "current_message_ref": str(messages[-1]["message_ref"]),
        "timestamp_ms": int(messages[-1]["timestamp_ms"]),
        "message_count": len(messages),
        "speaker_count": len({str(item["sender_ref"]) for item in messages}),
        "buckets": buckets,
        "primary_bucket": buckets[0],
        "messages": compact_messages,
        "perception_context": serialized,
        "perception_context_digest": str(perception_context_digest(context)),
    }


def window(
    output_root: Path, *, session_gap_minutes: int = 30
) -> dict[str, object]:
    messages_path = output_root / "normalized/messages.jsonl"
    if not messages_path.exists():
        raise CorpusError("normalized_messages_missing")
    by_conversation: dict[str, list[dict[str, object]]] = defaultdict(list)
    for message in read_jsonl(messages_path):
        by_conversation[str(message["conversation_ref"])].append(message)
    windows_path = output_root / "windows/all.jsonl"
    windows_path.parent.mkdir(parents=True, exist_ok=True)
    gap_ms = int(timedelta(minutes=session_gap_minutes).total_seconds() * 1000)
    counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    number = 0
    with windows_path.open("w", encoding="utf-8") as handle:
        for conversation_ref, conversation_messages in sorted(by_conversation.items()):
            conversation_messages.sort(
                key=lambda item: (
                    int(item["timestamp_ms"]),
                    _sortable_seq(str(item["seq"])),
                    int(item["source_ordinal"]),
                )
            )
            session: list[dict[str, object]] = []
            prior_timestamp: int | None = None
            by_ref: dict[str, dict[str, object]] = {}
            for message in conversation_messages:
                timestamp_ms = int(message["timestamp_ms"])
                if (
                    prior_timestamp is not None
                    and timestamp_ms - prior_timestamp > gap_ms
                ):
                    session = []
                    by_ref = {}
                    counts["session_breaks"] += 1
                session.append(message)
                by_ref[str(message["message_ref"])] = message
                prior_timestamp = timestamp_ms
                if len(session) < 3:
                    continue
                if message.get("system"):
                    counts["excluded_current_system"] += 1
                    continue
                if message.get("recalled"):
                    counts["excluded_current_recalled"] += 1
                    continue
                if message.get("self_authored"):
                    counts["excluded_current_self_authored"] += 1
                    continue
                if not str(message.get("text") or "").strip() and not message.get(
                    "attachment_kinds"
                ):
                    counts["excluded_current_empty"] += 1
                    continue
                selected = list(session[-12:])
                reply = message.get("reply_to_ref")
                if reply and str(reply) in by_ref and all(
                    str(item["message_ref"]) != str(reply) for item in selected
                ):
                    # Preserve the older reply target plus the most recent 11
                    # messages (including current); never trim the target away.
                    selected = [by_ref[str(reply)], *session[-11:]]
                if len(selected) < 3:
                    continue
                number += 1
                row = _window_row(number, conversation_ref, selected)
                handle.write(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                )
                handle.write("\n")
                counts["eligible_windows"] += 1
                group_counts[conversation_ref] += 1
                for bucket in row["buckets"]:
                    bucket_counts[str(bucket)] += 1
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_gap_minutes": session_gap_minutes,
        "window_count": number,
        "group_count": len(group_counts),
        "counts": dict(sorted(counts.items())),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "largest_group_windows": group_counts.most_common(10),
        "past_only": True,
        "current_target_excludes": ["system", "recalled", "self_authored"],
    }
    write_json(output_root / "reports/window-summary.json", report)
    return report


def _stratified_sample(
    rows: Sequence[dict[str, object]],
    target: int,
    *,
    seed: int,
    per_group_fraction: float = 0.12,
) -> list[dict[str, object]]:
    rng = random.Random(seed)
    by_bucket: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_bucket[str(row["primary_bucket"])].append(row)
    for values in by_bucket.values():
        rng.shuffle(values)
    ordered_buckets = [bucket for bucket in BUCKETS if by_bucket.get(bucket)]
    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    group_counts: Counter[str] = Counter()
    group_cap = max(2, int(target * per_group_fraction))
    cursor = 0
    while len(selected) < target and ordered_buckets:
        bucket = ordered_buckets[cursor % len(ordered_buckets)]
        values = by_bucket[bucket]
        accepted = None
        while values:
            candidate = values.pop()
            window_id = str(candidate["window_id"])
            group = str(candidate["conversation_ref"])
            if window_id in selected_ids or group_counts[group] >= group_cap:
                continue
            accepted = candidate
            break
        if accepted is None:
            ordered_buckets.remove(bucket)
            if not ordered_buckets:
                break
            continue
        selected.append(accepted)
        selected_ids.add(str(accepted["window_id"]))
        group_counts[str(accepted["conversation_ref"])] += 1
        cursor += 1
    if len(selected) < target:
        remainder = [row for row in rows if str(row["window_id"]) not in selected_ids]
        rng.shuffle(remainder)
        selected.extend(remainder[: target - len(selected)])
    return selected[:target]


def sample(output_root: Path, *, seed: int = 230815) -> dict[str, object]:
    all_path = output_root / "windows/all.jsonl"
    if not all_path.exists():
        raise CorpusError("windows_missing")
    rows = list(read_jsonl(all_path))
    if len(rows) < 50:
        raise CorpusError("fewer_than_50_eligible_windows")
    smoke = _stratified_sample(rows, 50, seed=seed)
    write_jsonl(output_root / "windows/smoke-50.jsonl", smoke)
    candidate_counts: dict[str, int] = {}
    for target in (240, 360, 480, 600):
        selected = _stratified_sample(rows, min(target, len(rows)), seed=seed)
        path = output_root / f"windows/candidate-{target}.jsonl"
        candidate_counts[str(target)] = write_jsonl(path, selected)
    largest = min(600, len(rows))
    write_jsonl(
        output_root / "windows/teacher-target.jsonl",
        _stratified_sample(rows, largest, seed=seed),
    )
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "eligible_windows": len(rows),
        "smoke_windows": len(smoke),
        "candidate_counts": candidate_counts,
        "initial_teacher_target": largest,
        "final_target_selected_after_50_pilot": False,
        "per_group_fraction": 0.12,
        "coverage_before_count": True,
    }
    write_json(output_root / "reports/sample-summary.json", report)
    return report


def redact_for_teacher(value: str, known_labels: Iterable[str] = ()) -> str:
    redacted = PHONE_RE.sub("[PHONE]", value)
    redacted = EMAIL_RE.sub("[EMAIL]", redacted)
    redacted = URL_QUERY_RE.sub(r"\1", redacted)
    redacted = QQ_RE.sub("[ACCOUNT]", redacted)
    for label in sorted({item for item in known_labels if item}, key=len, reverse=True):
        redacted = redacted.replace(label, "[NAME]")
    return redacted


def _print_report(value: Mapping[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "inventory",
            "extract",
            "window",
            "sample",
            "label",
            "compile",
            "train",
            "evaluate",
            "predict",
            "demo",
            "serve",
            "all",
        ),
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--session-gap-minutes", type=int, default=30)
    parser.add_argument("--seed", type=int, default=230815)
    parser.add_argument("--target", type=int)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--total-budget-seconds", type=float, default=14_400)
    parser.add_argument("--reserve-seconds", type=float, default=4_500)
    parser.add_argument("--minimum-confidence", type=float, default=0.65)
    parser.add_argument("--sample-limit", type=int, default=300)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_root = args.input.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    if args.command in {"inventory", "extract", "all"} and not input_root.is_dir():
        raise CorpusError(f"input_directory_missing:{input_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    if args.command == "inventory":
        _print_report(inventory(input_root, output_root))
    elif args.command == "extract":
        _print_report(extract(input_root, output_root))
    elif args.command == "window":
        _print_report(
            window(output_root, session_gap_minutes=args.session_gap_minutes)
        )
    elif args.command == "sample":
        _print_report(sample(output_root, seed=args.seed))
    elif args.command == "label":
        from private_corpus_teacher import label_teacher_batch

        _print_report(
            asyncio.run(
                label_teacher_batch(
                    output_root,
                    target=args.target,
                    concurrency=args.concurrency,
                    total_budget_seconds=args.total_budget_seconds,
                    reserve_seconds=args.reserve_seconds,
                )
            )
        )
    elif args.command == "compile":
        from private_corpus_teacher import compile_teacher_batch

        _print_report(
            compile_teacher_batch(
                output_root,
                minimum_confidence=args.minimum_confidence,
            )
        )
    elif args.command == "train":
        from private_corpus_student import train_students

        _print_report(train_students(output_root, seed=args.seed))
    elif args.command == "evaluate":
        from private_corpus_student import evaluate_students

        _print_report(evaluate_students(output_root))
    elif args.command == "predict":
        from private_corpus_student import predict_all

        _print_report(predict_all(output_root))
    elif args.command == "demo":
        from private_corpus_demo import generate_demo

        _print_report(generate_demo(output_root, sample_limit=args.sample_limit))
    elif args.command == "serve":
        from private_corpus_demo import serve_demo

        serve_demo(output_root, host=args.host, port=args.port)
    elif args.command == "all":
        from private_corpus_demo import generate_demo
        from private_corpus_student import (
            evaluate_students,
            predict_all,
            train_students,
        )
        from private_corpus_teacher import (
            compile_teacher_batch,
            label_teacher_batch,
        )

        _print_report(inventory(input_root, output_root))
        _print_report(extract(input_root, output_root))
        _print_report(
            window(output_root, session_gap_minutes=args.session_gap_minutes)
        )
        _print_report(sample(output_root, seed=args.seed))
        _print_report(
            asyncio.run(
                label_teacher_batch(
                    output_root,
                    target=args.target,
                    concurrency=args.concurrency,
                    total_budget_seconds=args.total_budget_seconds,
                    reserve_seconds=args.reserve_seconds,
                )
            )
        )
        _print_report(
            compile_teacher_batch(
                output_root,
                minimum_confidence=args.minimum_confidence,
            )
        )
        _print_report(train_students(output_root, seed=args.seed))
        _print_report(evaluate_students(output_root))
        _print_report(predict_all(output_root))
        _print_report(generate_demo(output_root, sample_limit=args.sample_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
