"""Repeater: echo a message once enough group members have sent the same thing in a row."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

from .base import Ctx, Inbound, Observer, Registry, Reply, Task

FEATURE = "repeater"
TASK = "repeater"
DEFAULT_THRESHOLDS = {"text": 2, "image": 2, "face": 2}
DEFAULT_PROBABILITY = 0.8
MAX_TEXT = 200
COMMAND_PREFIXES = ("/", "／", "#", "!", "！", ".")
SKIPPED_SEGMENTS = {"reply", "mention", "forward", "light_app", "unknown"}


@dataclass
class Chain:
    fingerprint: str | None = None
    senders: list[str] = field(default_factory=list)
    repeated: str | None = None


_chains: dict[str, Chain] = {}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def message_content(inbound: Inbound, bot_names: tuple[str, ...] = ()) -> tuple[str, str, dict] | None:
    """Return ``(kind, fingerprint, action)`` for a single text/image/face message, else ``None``."""
    segments = [s for s in inbound.segments if not (s.get("type") == "text" and not str(s.get("text", "")).strip())]
    if not segments:
        if inbound.text.strip() and not inbound.images:
            segments = [{"type": "text", "text": inbound.text}]
        elif not inbound.text.strip():
            segments = [{"type": "image", **image} for image in inbound.images]
    if len(segments) != 1 or segments[0].get("type") in SKIPPED_SEGMENTS:
        return None
    segment = segments[0]
    kind = segment.get("type")
    if kind == "text":
        text = str(segment.get("text", "")).strip()
        lowered = text.lower()
        if not text or len(text) > MAX_TEXT or text.startswith(COMMAND_PREFIXES) \
                or any(lowered.startswith(name.lower()) for name in bot_names):
            return None
        return "text", "text:" + text, {"type": "text", "text": text}
    if kind == "image":
        url = str(segment.get("url") or "")
        resource = str(segment.get("resource_id") or "")
        if not url:
            return None
        return "image", "image:" + _digest(resource or url), {"type": "image", "url": url}
    if kind == "face":
        face_id = str(segment.get("id") or "").strip()
        if not face_id:
            return None
        return "face", "face:" + face_id, {"type": "face", "id": face_id}
    return None


def thresholds(config: dict) -> dict[str, int]:
    merged = dict(DEFAULT_THRESHOLDS)
    raw = config.get("thresholds")
    if isinstance(raw, dict):
        for kind, value in raw.items():
            try:
                merged[kind] = max(2, int(value))
            except (TypeError, ValueError):
                continue
    return merged


def observe(chain: Chain, sender: str, fingerprint: str, threshold: int, need_different: bool,
            probability: float, roll: float) -> bool:
    """Advance one conversation's chain; True when the bot should repeat now."""
    if fingerprint != chain.fingerprint:
        chain.fingerprint, chain.senders = fingerprint, [sender]
    elif not (need_different and sender in chain.senders):
        chain.senders.append(sender)
    if len(chain.senders) < threshold or chain.repeated == fingerprint or roll >= probability:
        return False
    chain.repeated = fingerprint
    chain.senders = []
    return True


async def repeater_observer(ctx: Ctx) -> Reply | None:
    inbound = ctx.inbound
    if not inbound.is_group:
        return None
    chain = _chains.setdefault(inbound.scope, Chain())
    content = message_content(inbound, ctx.settings.bot_names)
    if content is None:
        # Any other message interrupts the chain.
        chain.fingerprint, chain.senders = None, []
        return None
    kind, fingerprint, action = content
    config = ctx.config(FEATURE)
    try:
        probability = float(config.get("probability", DEFAULT_PROBABILITY))
    except (TypeError, ValueError):
        probability = DEFAULT_PROBABILITY
    if observe(chain, inbound.sender.id, fingerprint, thresholds(config).get(kind, 2),
               bool(config.get("need_different", True)), probability, random.random()):
        return Reply(action)
    return None


def register(registry: Registry) -> None:
    registry.task(Task(TASK, "复读机", "群友连续发送相同的文字/图片/表情时跟着复读一次", aliases=("reread", "复读")))
    registry.observer(Observer(TASK, repeater_observer, order=60))
