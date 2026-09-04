from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

EMOJI_KITCHEN_METADATA_URL = (
    "https://raw.githubusercontent.com/xsalazar/emoji-kitchen-backend/main/app/metadata.json"
)
DEFAULT_METADATA_TTL_SECONDS = 7 * 24 * 60 * 60
# The upstream metadata is about 99 MB after decompression.  Keep the bound
# finite while leaving room for the published dataset to grow modestly.
MAX_METADATA_BYTES = 128 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CODEPOINT_RE = re.compile(r"^[0-9a-f]+(?:-[0-9a-f]+)*$", re.IGNORECASE)
_METADATA_HOSTS = frozenset({"raw.githubusercontent.com"})
_IMAGE_HOSTS = frozenset({"gstatic.com", "www.gstatic.com"})


class EmojiKitchenError(RuntimeError):
    """Base error for user-facing Emoji Kitchen failures."""


class EmojiKitchenUsageError(EmojiKitchenError):
    """The command did not contain exactly two Emoji arguments."""


class EmojiKitchenUnsupportedError(EmojiKitchenError):
    """The requested Emoji or pair has no supported Kitchen result."""

    def __init__(self, message: str, *, left: str = "", right: str = "") -> None:
        super().__init__(message)
        self.left = left
        self.right = right


class EmojiKitchenUnavailableError(EmojiKitchenError):
    """Metadata or image data could not be loaded."""


@dataclass(frozen=True, slots=True)
class EmojiKitchenCombination:
    left_codepoint: str
    right_codepoint: str
    alt: str
    image_url: str


@dataclass(frozen=True, slots=True)
class EmojiKitchenMetadata:
    supported_codepoints: tuple[str, ...]
    token_to_codepoint: Mapping[str, str]
    combinations: Mapping[str, Mapping[str, tuple[EmojiKitchenCombination, ...]]]


@dataclass(frozen=True, slots=True)
class EmojiKitchenResult:
    left: str
    right: str
    left_codepoint: str
    right_codepoint: str
    alt: str
    image_bytes: bytes


def parse_emoji_arguments(arguments: str) -> tuple[str, str]:
    """Parse the explicit ``/emoji A B`` command arguments."""

    tokens = str(arguments or "").split()
    if len(tokens) != 2:
        raise EmojiKitchenUsageError(
            "用法：/emoji <Emoji1> <Emoji2>，例如 /emoji 😀 😭"
        )
    return tokens[0], tokens[1]


def normalize_codepoint_id(value: str) -> str:
    """Return the lowercase hyphenated codepoint form used by the metadata."""

    candidate = str(value or "").strip()
    if not _CODEPOINT_RE.fullmatch(candidate):
        raise ValueError("invalid emoji codepoint id")
    parts = []
    for raw_part in candidate.split("-"):
        codepoint = int(raw_part, 16)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError("invalid Unicode codepoint")
        parts.append(f"{codepoint:x}")
    return "-".join(parts)


def codepoint_id_to_emoji(value: str) -> str:
    """Convert a metadata codepoint id into its printable Unicode Emoji."""

    normalized = normalize_codepoint_id(value)
    return "".join(chr(int(part, 16)) for part in normalized.split("-"))


def _token_without_variation_selectors(value: str) -> str:
    return value.replace("\ufe0e", "").replace("\ufe0f", "")


def parse_metadata(payload: Any) -> EmojiKitchenMetadata:
    """Validate the reference metadata and retain only latest usable results."""

    if not isinstance(payload, dict):
        raise TypeError("Emoji Kitchen metadata must be an object")
    raw_supported = payload.get("knownSupportedEmoji")
    raw_data = payload.get("data")
    if not isinstance(raw_supported, list) or not isinstance(raw_data, dict):
        raise TypeError("Emoji Kitchen metadata has an invalid shape")
    if not raw_supported or len(raw_supported) > 10_000:
        raise ValueError("Emoji Kitchen supported list is invalid")

    supported: list[str] = []
    seen_supported: set[str] = set()
    token_map: dict[str, str] = {}
    for raw_codepoint in raw_supported:
        if not isinstance(raw_codepoint, str):
            raise TypeError("Emoji Kitchen supported entries must be strings")
        codepoint = normalize_codepoint_id(raw_codepoint)
        if codepoint in seen_supported:
            continue
        seen_supported.add(codepoint)
        supported.append(codepoint)
        printable = codepoint_id_to_emoji(codepoint)
        token_map.setdefault(printable, codepoint)
        without_variation = _token_without_variation_selectors(printable)
        if without_variation:
            token_map.setdefault(without_variation, codepoint)

    combinations: dict[str, dict[str, tuple[EmojiKitchenCombination, ...]]] = {}
    for raw_left, raw_entry in raw_data.items():
        if not isinstance(raw_left, str) or not isinstance(raw_entry, dict):
            continue
        left_codepoint = normalize_codepoint_id(raw_left)
        raw_combinations = raw_entry.get("combinations")
        if not isinstance(raw_combinations, dict):
            continue
        left_combinations = combinations.setdefault(left_codepoint, {})
        for raw_right, raw_items in raw_combinations.items():
            if not isinstance(raw_right, str) or not isinstance(raw_items, list):
                continue
            right_codepoint = normalize_codepoint_id(raw_right)
            latest: list[EmojiKitchenCombination] = []
            for raw_item in raw_items:
                if not isinstance(raw_item, dict) or raw_item.get("isLatest") is not True:
                    continue
                image_url = raw_item.get("gStaticUrl")
                if not isinstance(image_url, str) or not image_url.strip():
                    continue
                alt = raw_item.get("alt")
                latest.append(
                    EmojiKitchenCombination(
                        left_codepoint=left_codepoint,
                        right_codepoint=right_codepoint,
                        alt=str(alt).strip() if isinstance(alt, str) else "",
                        image_url=image_url.strip(),
                    )
                )
            if latest:
                left_combinations[right_codepoint] = tuple(latest)

    if not combinations:
        raise ValueError("Emoji Kitchen metadata contains no combinations")
    return EmojiKitchenMetadata(
        supported_codepoints=tuple(supported),
        token_to_codepoint=token_map,
        combinations=combinations,
    )


class EmojiKitchenService:
    """Resolve and locally cache official Emoji Kitchen combinations."""

    def __init__(
        self,
        cache_root: Path,
        *,
        metadata_ttl_seconds: int = DEFAULT_METADATA_TTL_SECONDS,
        metadata_url: str = EMOJI_KITCHEN_METADATA_URL,
        timeout_seconds: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cache_root = Path(cache_root)
        self.metadata_path = self.cache_root / "metadata.json"
        self.images_root = self.cache_root / "images"
        self.metadata_ttl_seconds = max(60, min(30 * 24 * 60 * 60, int(metadata_ttl_seconds)))
        self.metadata_url = metadata_url
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self._clock = clock
        self._metadata: EmojiKitchenMetadata | None = None
        self._metadata_loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def compose(self, arguments: str) -> EmojiKitchenResult:
        left, right = parse_emoji_arguments(arguments)
        async with self._lock:
            metadata = await self._load_metadata()
            left_codepoint = metadata.token_to_codepoint.get(left)
            right_codepoint = metadata.token_to_codepoint.get(right)
            if not left_codepoint or not right_codepoint:
                raise EmojiKitchenUnsupportedError(
                    "输入的 Emoji 不在官方 Emoji Kitchen 支持范围内。",
                    left=left,
                    right=right,
                )

            combination = self._find_combination(
                metadata, left_codepoint, right_codepoint
            )
            if combination is None:
                raise EmojiKitchenUnsupportedError(
                    "这两个 Emoji 没有官方 Emoji Kitchen 合成结果。",
                    left=left,
                    right=right,
                )
            image_bytes = await self._load_image(combination)
            return EmojiKitchenResult(
                left=left,
                right=right,
                left_codepoint=left_codepoint,
                right_codepoint=right_codepoint,
                alt=combination.alt,
                image_bytes=image_bytes,
            )

    async def _load_metadata(self) -> EmojiKitchenMetadata:
        now = self._clock()
        if self._metadata is not None and now - self._metadata_loaded_at < self.metadata_ttl_seconds:
            return self._metadata

        cached = self._read_cached_metadata()
        if cached is not None:
            metadata, modified_at = cached
            if now - modified_at < self.metadata_ttl_seconds:
                self._metadata = metadata
                self._metadata_loaded_at = now
                return metadata

        try:
            raw = await self._fetch_bytes(
                self.metadata_url,
                max_bytes=MAX_METADATA_BYTES,
                allowed_hosts=_METADATA_HOSTS,
                read_compressed=True,
            )
            payload = json.loads(raw.decode("utf-8-sig"))
            metadata = parse_metadata(payload)
            self._write_json_atomic(self.metadata_path, self._compact_metadata(metadata))
            self._metadata = metadata
            self._metadata_loaded_at = self._clock()
            return metadata
        except (
            EmojiKitchenError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            if cached is not None:
                metadata = cached[0]
                self._metadata = metadata
                self._metadata_loaded_at = now
                return metadata
            raise EmojiKitchenUnavailableError(
                "Emoji Kitchen 数据暂时不可用。"
            ) from exc

    def _read_cached_metadata(self) -> tuple[EmojiKitchenMetadata, float] | None:
        try:
            if self.metadata_path.stat().st_size > MAX_METADATA_BYTES:
                return None
            payload = json.loads(
                self.metadata_path.read_text(encoding="utf-8-sig")
            )
            metadata = parse_metadata(payload)
            return metadata, self.metadata_path.stat().st_mtime
        except (OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
            return None

    async def _load_image(self, combination: EmojiKitchenCombination) -> bytes:
        path = self._image_path(combination)
        try:
            cached = path.read_bytes()
            if self._valid_png(cached):
                return cached
            path.unlink(missing_ok=True)
        except OSError:
            pass

        try:
            image = await self._fetch_bytes(
                combination.image_url,
                max_bytes=MAX_IMAGE_BYTES,
                allowed_hosts=_IMAGE_HOSTS,
            )
            if not self._valid_png(image):
                raise EmojiKitchenUnavailableError("Emoji Kitchen 图片格式无效。")
            self._write_bytes_atomic(path, image)
            return image
        except (EmojiKitchenError, OSError) as exc:
            raise EmojiKitchenUnavailableError(
                "Emoji Kitchen 图片暂时无法获取。"
            ) from exc

    def _image_path(self, combination: EmojiKitchenCombination) -> Path:
        pair_key = "|".join(
            sorted((combination.left_codepoint, combination.right_codepoint))
        )
        cache_key = f"{pair_key}|{combination.image_url}"
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return self.images_root / f"{digest}.png"

    async def _fetch_bytes(
        self,
        url: str,
        *,
        max_bytes: int,
        allowed_hosts: frozenset[str],
        read_compressed: bool = False,
    ) -> bytes:
        self._validate_url(url, allowed_hosts)
        try:
            proxy = self._http_proxy()
            async with httpx.AsyncClient(
                follow_redirects=True,
                proxy=proxy if self._transport is None else None,
                timeout=self.timeout_seconds,
                trust_env=False,
                transport=self._transport,
            ) as client, client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise EmojiKitchenUnavailableError(
                        f"Emoji Kitchen resource returned HTTP {response.status_code}"
                    )
                self._validate_url(str(response.url), allowed_hosts)
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    raise EmojiKitchenUnavailableError(
                        "Emoji Kitchen resource is too large"
                    )
                if read_compressed and response.is_stream_consumed:
                    body = response.content
                else:
                    chunks: list[bytes] = []
                    total = 0
                    stream = response.aiter_raw() if read_compressed else response.aiter_bytes()
                    async for chunk in stream:
                        total += len(chunk)
                        if total > max_bytes:
                            raise EmojiKitchenUnavailableError(
                                "Emoji Kitchen resource is too large"
                            )
                        chunks.append(chunk)
                    body = b"".join(chunks)
                if read_compressed and response.headers.get("content-encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)
                    if len(body) > max_bytes:
                        raise EmojiKitchenUnavailableError(
                            "Emoji Kitchen resource is too large"
                        )
                return body
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise EmojiKitchenUnavailableError(
                "Emoji Kitchen resource could not be downloaded"
            ) from exc

    @staticmethod
    def _validate_url(url: str, allowed_hosts: frozenset[str]) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in allowed_hosts:
            raise EmojiKitchenUnavailableError("Emoji Kitchen resource URL is not allowed")

    @staticmethod
    def _http_proxy() -> str | None:
        """Use an explicit HTTP(S) proxy without accidentally selecting SOCKS."""

        values = [os.environ.get("DUDUDA_EMOJI_KITCHEN_HTTP_PROXY", "")]
        values.extend(
            os.environ.get(name, "")
            for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
        )
        for value in values:
            value = value.strip()
            if not value:
                continue
            parsed = urlparse(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return value
        return None

    @staticmethod
    def _valid_png(value: bytes) -> bool:
        return len(value) <= MAX_IMAGE_BYTES and value.startswith(PNG_SIGNATURE)

    @staticmethod
    def _compact_metadata(metadata: EmojiKitchenMetadata) -> dict[str, Any]:
        return {
            "knownSupportedEmoji": list(metadata.supported_codepoints),
            "data": {
                left: {
                    "combinations": {
                        right: [
                            {
                                "gStaticUrl": combination.image_url,
                                "alt": combination.alt,
                                "isLatest": True,
                            }
                            for combination in candidates
                        ]
                        for right, candidates in right_combinations.items()
                    }
                }
                for left, right_combinations in metadata.combinations.items()
            },
        }

    @staticmethod
    def _find_combination(
        metadata: EmojiKitchenMetadata,
        left_codepoint: str,
        right_codepoint: str,
    ) -> EmojiKitchenCombination | None:
        direct = metadata.combinations.get(left_codepoint, {}).get(right_codepoint)
        if direct:
            return direct[0]
        reverse = metadata.combinations.get(right_codepoint, {}).get(left_codepoint)
        if reverse:
            return reverse[0]
        return None

    @staticmethod
    def _write_json_atomic(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @staticmethod
    def _write_bytes_atomic(path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
