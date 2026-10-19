"""Decide whether a message is a command, an agent question, or passive chat."""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass

from .features.base import Command, Inbound

SEPARATORS = " \t\r\n,，:：、!！~～"
TRAILING = "?？!！。.~～ "
CJK = re.compile(r"[\u3400-\u9fff]")


@dataclass
class Route:
    kind: str  # command | agent | passive | ignore
    body: str
    command: Command | None = None
    args: str = ""
    addressed: bool = False


def strip_prefix(text: str, bot_names: tuple[str, ...]) -> tuple[str, bool, bool]:
    """Return (body, slash, named) after removing a leading ``/`` or bot name.

    A typed ``@嘟嘟哒`` (plain text, not a real mention) counts as the name, and a slash right after
    the name is dropped too, so ``@嘟嘟哒 /亲密度`` and ``嘟嘟哒 /help`` reach the command.
    """
    body = text.strip()
    if body[:1] in ("/", "／"):
        return body[1:].lstrip(), True, False
    unprefixed = body[1:] if body[:1] in ("@", "＠") else body
    lowered = unprefixed.lower()
    for name in sorted(bot_names, key=len, reverse=True):
        if lowered.startswith(name.lower()):
            rest = unprefixed[len(name):]
            if not rest or rest[0] in SEPARATORS:
                rest = rest.lstrip(SEPARATORS)
                if rest[:1] in ("/", "／"):
                    return rest[1:].lstrip(), True, True
                return rest, False, True
    return body, False, False


def match_command(body: str, commands: list[Command]) -> tuple[Command, str] | None:
    lowered = body.lower()
    candidates = sorted(((name.lower(), command) for command in commands for name in command.names),
                        key=lambda item: len(item[0]), reverse=True)
    for name, command in candidates:
        if command.exact:
            if lowered.rstrip(TRAILING) == name:
                return command, ""
            continue
        if lowered == name:
            return command, ""
        if lowered.startswith(name):
            rest = body[len(name):]
            if rest[0] in SEPARATORS or (CJK.match(name[-1]) and CJK.match(rest[0])):
                return command, rest.strip(SEPARATORS + " ")
    return None


def route(inbound: Inbound, commands: list[Command], bot_names: tuple[str, ...]) -> Route:
    body, slash, named = strip_prefix(inbound.text, bot_names)
    addressed = inbound.kind != "group" or inbound.mentioned or named
    matched = match_command(body, commands) if body else None
    if matched and (addressed or slash):
        return Route("command", body, matched[0], matched[1], addressed=True)
    if addressed:
        return Route("agent", body, addressed=True)
    if slash:
        # Unknown slash commands in groups belong to other bots.
        return Route("ignore", body)
    return Route("passive", body)


class RateLimiter:
    """Counts replies the bot actively produces per conversation in a sliding window."""

    def __init__(self, window_seconds: float, limits: dict[str, int]):
        self.window = window_seconds
        self.limits = limits
        self.events: dict[str, deque[float]] = {}
        self.warned: dict[str, float] = {}

    def admit(self, scope: str, kind: str) -> str:
        """Return ``ok`` (counted), ``tired`` (first refusal: say so once) or ``drop``."""
        now = time.monotonic()
        events = self.events.setdefault(scope, deque())
        while events and now - events[0] >= self.window:
            events.popleft()
        if len(events) < self.limits.get(kind, self.limits.get("group", 30)):
            events.append(now)
            return "ok"
        if now - self.warned.get(scope, -float("inf")) >= self.window:
            self.warned[scope] = now
            return "tired"
        return "drop"
