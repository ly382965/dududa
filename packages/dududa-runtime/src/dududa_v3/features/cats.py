"""Cat hearts: react with a heart to group photos of cats, judged by the vision model."""

from __future__ import annotations

import base64
import hashlib
import struct
import time
from collections import OrderedDict, deque

from .base import Ctx, FeatureError, Observer, Registry, Reply, Task, sniff_mime

FEATURE = "cats"
TASK = "cat_hearts"
HEART = "66"
MIN_SIDE = 200
DEFAULT_MAX_PER_HOUR = 30
CACHE_SIZE = 2048
MAX_IMAGE_BYTES = 8 * 1024 * 1024
SYSTEM = ("你是图片分类器。判断图片里是否有真实的猫或明显以猫为主角的画面（照片、绘画、表情包都算）。"
          "只输出一个词：有猫输出 CAT，没有输出 NO。不要输出其他任何内容。")
PROMPT = "这张图里有猫吗？只回答 CAT 或 NO。"

_verdicts: OrderedDict[str, bool] = OrderedDict()
_budgets: dict[str, deque[float]] = {}


def image_key(image: dict) -> str | None:
    source = str(image.get("resource_id") or "") or str(image.get("url") or "")
    return hashlib.sha256(source.encode()).hexdigest()[:32] if source else None


def too_small(width: object, height: object) -> bool:
    return isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0 \
        and min(width, height) < MIN_SIDE


def image_size(body: bytes) -> tuple[int, int] | None:
    """Pixel size from PNG/GIF/JPEG/WebP headers, without decoding the image."""
    try:
        if body.startswith(b"\x89PNG") and body[12:16] == b"IHDR":
            return struct.unpack(">II", body[16:24])
        if body[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", body[6:10])
        if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
            chunk = body[12:16]
            if chunk == b"VP8X":
                return int.from_bytes(body[24:27], "little") + 1, int.from_bytes(body[27:30], "little") + 1
            if chunk == b"VP8 ":
                width, height = struct.unpack("<HH", body[26:30])
                return width & 0x3FFF, height & 0x3FFF
            if chunk == b"VP8L":
                bits = int.from_bytes(body[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if body.startswith(b"\xff\xd8"):
            index = 2
            while index + 9 < len(body):
                if body[index] != 0xFF:
                    index += 1
                    continue
                marker = body[index + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    height, width = struct.unpack(">HH", body[index + 5:index + 9])
                    return width, height
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    index += 2
                    continue
                index += 2 + struct.unpack(">H", body[index + 2:index + 4])[0]
    except (struct.error, IndexError):
        return None
    return None


def remember(key: str, verdict: bool) -> None:
    _verdicts[key] = verdict
    _verdicts.move_to_end(key)
    while len(_verdicts) > CACHE_SIZE:
        _verdicts.popitem(last=False)


def take_budget(scope: str, limit: int, now: float) -> bool:
    window = _budgets.setdefault(scope, deque())
    while window and now - window[0] >= 3600:
        window.popleft()
    if len(window) >= limit:
        return False
    window.append(now)
    return True


async def classify(ctx: Ctx, body: bytes, mime: str) -> bool:
    result = await ctx.agent_once(PROMPT, service="vision", system=SYSTEM, timeout=90,
                                  images=[{"data": base64.b64encode(body).decode(), "mimeType": mime}])
    return result.text.strip().upper().lstrip("*`'\" ").startswith("CAT")


async def cat_observer(ctx: Ctx) -> Reply | None:
    inbound = ctx.inbound
    if not inbound.is_group:
        return None
    candidates = []
    for image in inbound.images:
        key = image_key(image)
        if key is None or not image.get("url") or image.get("sticker") \
                or too_small(image.get("width"), image.get("height")):
            continue
        if _verdicts.get(key):
            return Reply().reaction(inbound.message_id, HEART)
        if key not in _verdicts:
            candidates.append((key, image))
    if not candidates:
        return None
    # At most one classification per message: the first image not judged before.
    key, image = candidates[0]
    try:
        limit = max(0, int(ctx.config(FEATURE).get("max_per_hour", DEFAULT_MAX_PER_HOUR)))
    except (TypeError, ValueError):
        limit = DEFAULT_MAX_PER_HOUR
    if not take_budget(inbound.scope, limit, time.monotonic()):
        return None
    try:
        body, info, _ = await ctx.fetch(image["url"], timeout=20, max_bytes=MAX_IMAGE_BYTES)
    except FeatureError:
        return None
    mime = sniff_mime(body) or info.get("content-type", "").split(";")[0]
    size = image_size(body)
    if not mime.startswith("image/") or (size and too_small(*size)):
        remember(key, False)
        return None
    verdict = await classify(ctx, body, mime)
    remember(key, verdict)
    return Reply().reaction(inbound.message_id, HEART) if verdict else None


def register(registry: Registry) -> None:
    registry.task(Task(TASK, "猫图点爱心", "群里有人发猫图时自动给这条消息点个爱心", aliases=("cats", "猫图")))
    registry.observer(Observer(TASK, cat_observer, order=80))
