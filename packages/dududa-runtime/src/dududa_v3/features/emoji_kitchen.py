"""Emoji Kitchen: combine two Unicode emoji into Google's official mashup sticker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path

from .base import Command, Ctx, FeatureError, Registry, Reply, Task

FEATURE = "emoji_kitchen"
TASK = "emoji_kitchen"
METADATA_URL = "https://raw.githubusercontent.com/xsalazar/emoji-kitchen-backend/main/app/metadata.json"
URL_PREFIX = "https://www.gstatic.com/android/keyboard/emojikitchen/"
DEFAULT_TTL = 7 * 24 * 3600
# Upstream metadata is ~9 MB gzipped / ~99 MB plain; allow either transfer form to grow modestly.
MAX_METADATA_BYTES = 160 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
USAGE = "用法：嘟嘟哒 表情合成 😀 😭（也可以写 😀+😭）"
SEPARATORS = re.compile(r"[\s+＋,，、和&]+")
# Every combination object in the metadata is flat; the outer objects contain nested braces.
COMBINATION = re.compile(r'\{[^{}]*"gStaticUrl"[^{}]*\}')
CODEPOINTS = re.compile(r"^[0-9a-f]+(?:-[0-9a-f]+)*$")
VARIATIONS = "\ufe0e\ufe0f"
ZWJ = "\u200d"


def _is_modifier(char: str) -> bool:
    code = ord(char)
    return (char in VARIATIONS or code == 0x20E3 or 0x1F3FB <= code <= 0x1F3FF
            or 0xE0020 <= code <= 0xE007F)


def split_emoji(text: str) -> list[str]:
    """Split ``😀😭``, ``😀 😭`` or ``😀+😭`` into emoji clusters (ZWJ sequences, modifiers kept)."""
    clusters: list[str] = []
    for chunk in SEPARATORS.split(text.strip()):
        current = ""
        for char in chunk:
            if current and (current.endswith(ZWJ) or char == ZWJ or _is_modifier(char)):
                current += char
            else:
                if current:
                    clusters.append(current)
                current = char
        if current:
            clusters.append(current)
    return clusters


def parse_pair(text: str) -> tuple[str, str]:
    clusters = split_emoji(text)
    if len(clusters) != 2:
        raise FeatureError(USAGE)
    return clusters[0], clusters[1]


def codepoint_to_emoji(codepoint: str) -> str:
    return "".join(chr(int(part, 16)) for part in codepoint.split("-"))


def strip_variations(value: str) -> str:
    return value.translate({ord(char): None for char in VARIATIONS})


def pair_key(left: str, right: str) -> str:
    return "|".join(sorted((left, right)))


def build_index(raw: str) -> dict:
    """Reduce the upstream metadata to ``{supported: [codepoint], pairs: {"a|b": url suffix}}``."""
    head = raw[:200_000]
    match = re.search(r'"knownSupportedEmoji"\s*:\s*(\[[^\]]*\])', head) or \
        re.search(r'"knownSupportedEmoji"\s*:\s*(\[[^\]]*\])', raw)
    if not match:
        raise ValueError("metadata lacks knownSupportedEmoji")
    supported = [item.lower() for item in json.loads(match.group(1))
                 if isinstance(item, str) and CODEPOINTS.match(item.lower())]
    pairs: dict[str, str] = {}
    for found in COMBINATION.finditer(raw):
        try:
            item = json.loads(found.group())
        except ValueError:
            continue
        url = item.get("gStaticUrl")
        left, right = item.get("leftEmojiCodepoint"), item.get("rightEmojiCodepoint")
        if item.get("isLatest") is not True or not isinstance(url, str) or not url.startswith(URL_PREFIX) \
                or not isinstance(left, str) or not isinstance(right, str):
            continue
        pairs[pair_key(left.lower(), right.lower())] = url[len(URL_PREFIX):]
    if not supported or not pairs:
        raise ValueError("metadata contains no combinations")
    return {"supported": supported, "pairs": pairs}


class Kitchen:
    """Loaded index plus the token → codepoint map for one state directory."""

    def __init__(self, index: dict, loaded_at: float):
        self.pairs: dict[str, str] = index["pairs"]
        self.loaded_at = loaded_at
        self.tokens: dict[str, str] = {}
        for codepoint in index["supported"]:
            printable = codepoint_to_emoji(codepoint)
            self.tokens.setdefault(printable, codepoint)
            self.tokens.setdefault(strip_variations(printable), codepoint)

    def codepoint(self, emoji: str) -> str | None:
        return self.tokens.get(emoji) or self.tokens.get(strip_variations(emoji))

    def url(self, left: str, right: str) -> str | None:
        suffix = self.pairs.get(pair_key(left, right))
        return URL_PREFIX + suffix if suffix else None


_kitchens: dict[Path, Kitchen] = {}
_lock = asyncio.Lock()


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _read_index(path: Path) -> tuple[Kitchen, float] | None:
    try:
        modified = path.stat().st_mtime
        return Kitchen(json.loads(path.read_text(encoding="utf-8")), modified), modified
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _store_index(path: Path, raw: bytes) -> Kitchen:
    index = build_index(raw.decode("utf-8-sig"))
    _write_atomic(path, json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode())
    return Kitchen(index, time.time())


async def load_kitchen(ctx: Ctx) -> Kitchen:
    try:
        ttl = max(60, int(ctx.config(FEATURE).get("metadata_ttl_seconds", DEFAULT_TTL)))
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL
    path = ctx.state_dir(FEATURE) / "index.json"
    async with _lock:
        now = time.time()
        kitchen = _kitchens.get(path)
        if kitchen and now - kitchen.loaded_at < ttl:
            return kitchen
        cached = await asyncio.to_thread(_read_index, path)
        if cached and now - cached[1] < ttl:
            _kitchens[path] = cached[0]
            return cached[0]
        try:
            raw, _, _ = await ctx.fetch(METADATA_URL, timeout=180, max_bytes=MAX_METADATA_BYTES)
            kitchen = await asyncio.to_thread(_store_index, path, raw)
        except (FeatureError, ValueError, UnicodeError, OSError):
            if cached is None:
                raise FeatureError("表情合成数据暂时不可用，请稍后重试。") from None
            kitchen = cached[0]  # Serve the stale index until the next successful refresh.
            kitchen.loaded_at = now
        _kitchens[path] = kitchen
        return kitchen


async def load_image(ctx: Ctx, url: str) -> bytes:
    path = ctx.state_dir(FEATURE) / "images" / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".png")
    try:
        cached = path.read_bytes()
        if cached.startswith(PNG_SIGNATURE):
            return cached
    except OSError:
        pass
    body, _, _ = await ctx.fetch(url, timeout=30, max_bytes=MAX_IMAGE_BYTES)
    if not body.startswith(PNG_SIGNATURE):
        raise FeatureError("表情合成图片暂时无法获取，请稍后重试。")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, body)
    return body


async def emoji_command(ctx: Ctx) -> Reply | str:
    try:
        left, right = parse_pair(ctx.args)
    except FeatureError as error:
        return str(error)
    try:
        kitchen = await load_kitchen(ctx)
        left_code, right_code = kitchen.codepoint(left), kitchen.codepoint(right)
        unknown = [emoji for emoji, code in ((left, left_code), (right, right_code)) if code is None]
        if unknown:
            return f"{'、'.join(unknown)} 不在 Emoji Kitchen 支持的表情里哦。"
        url = kitchen.url(left_code, right_code)
        if url is None:
            return f"暂时没有 {left} + {right} 的官方合成表情。"
        return Reply().image(await load_image(ctx, url), mime="image/png")
    except FeatureError as error:
        return str(error)


def register(registry: Registry) -> None:
    registry.task(Task(TASK, "表情合成", "Emoji Kitchen 官方表情合成（表情合成 😀 😭）", aliases=("emoji",)))
    registry.command(Command(("表情合成", "emoji"), emoji_command,
                             "表情合成 / emoji <表情1> <表情2>：合成 Google Emoji Kitchen 表情", task=TASK))
