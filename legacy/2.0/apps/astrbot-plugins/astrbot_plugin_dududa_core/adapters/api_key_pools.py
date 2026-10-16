"""Read-only bridge from the Web API-key pool store to AstrBot Sources.

The Web gateway owns writes to the API-key pool file.  This module is a small
deployment adapter for the other side of that boundary: it validates a
versioned, private snapshot and produces the ``provider_sources``/``provider``
fragments AstrBot understands.  It deliberately is not imported by the core
model/domain packages and it never serializes a snapshot back to disk.

Raw credentials are retained only in the in-memory adapter object long enough
to build an AstrBot source.  The public dataclasses hide them from ``repr`` and
the projection has an explicit ``for_astrbot`` method to make the sensitive
boundary visible at call sites.  Callers must hand that result directly to
AstrBot's Provider Manager and must not put it in Runtime descriptors, traces,
or ordinary logs.

The canonical file is written by the Web gateway outside the repository.  For
backwards-compatible deployments both ``DUDUDA_API_KEY_STORE_PATH`` and
``DUDUDA_API_KEYS_FILE`` are accepted; the former wins when both are set.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

API_KEY_POOL_SCHEMA_VERSION = 1
API_KEY_POOL_TIERS: tuple[str, str, str] = ("haiku", "sonnet", "opus")
API_KEY_STORE_PATH_ENV = "DUDUDA_API_KEY_STORE_PATH"
API_KEY_STORE_PATH_COMPAT_ENV = "DUDUDA_API_KEYS_FILE"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
_SENSITIVE_HEADER_RE = re.compile(
    r"(?:authorization|api[-_]?key|token|secret|password|cookie|credential)",
    re.IGNORECASE,
)
_PROTOCOL_ALIASES = {
    "openai_chat_completion": "openai_chat_completion",
    "openai_chat_completions": "openai_chat_completion",
    "chat_completion": "openai_chat_completion",
    "openai": "openai_chat_completion",
    "anthropic": "anthropic_chat_completion",
    "anthropic_message": "anthropic_chat_completion",
    "anthropic_messages": "anthropic_chat_completion",
}

_DEFAULT_PROVIDER_IDS = {
    "haiku": "astrbot-luna",
    "sonnet": "astrbot-terra",
    "opus": "astrbot-sol",
}


class ApiKeyPoolConfigError(ValueError):
    """Raised when the external API-key pool snapshot is not usable."""


@dataclass(frozen=True, slots=True)
class ApiKeyCredential:
    """One key from the private store.

    ``secret`` is intentionally ``repr=False`` and excluded from comparisons.
    A projection is the only supported way for a deployment adapter to consume
    it.  The field is still present in memory because AstrBot's Source API
    expects a concrete key list; no Domain object receives this class.
    """

    id: str
    name: str
    secret_ref: str
    priority: int = 0
    weight: int = 1
    enabled: bool = True
    status: str = "active"
    secret: str = field(default="", repr=False, compare=False)

    @property
    def usable(self) -> bool:
        return bool(
            self.enabled
            and self.status.lower()
            not in {"disabled", "unavailable", "cooldown", "error"}
        )


@dataclass(frozen=True, slots=True)
class ApiKeyPool:
    """Validated metadata and credentials for one logical Dududa tier."""

    tier: str
    display_name: str
    provider: str
    provider_type: str
    provider_id: str
    source_id: str
    base_url: str
    model: str
    protocol: str
    reasoning_effort: str
    timeout_ms: int
    max_output_tokens: int
    enabled: bool
    scheduling_mode: str
    custom_headers: tuple[tuple[str, str], ...] = field(repr=False)
    revision: int | str
    keys: tuple[ApiKeyCredential, ...]

    def ordered_usable_keys(self) -> tuple[ApiKeyCredential, ...]:
        """Return a stable order suitable for AstrBot's source key list.

        AstrBot rotates the list after provider failures.  Priority is sorted
        ascending so a smaller value wins (the same convention used by the Web
        probe); ties prefer a larger weight and then use the stable key ID. The
        ``weight`` value remains metadata for schedulers that understand it and
        is not expanded into duplicate credentials here.
        """

        return tuple(
            sorted(
                (key for key in self.keys if key.usable),
                key=lambda key: (key.priority, -key.weight, key.id),
            )
        )


@dataclass(frozen=True, slots=True)
class ApiKeyPoolSnapshot:
    schema_version: int
    revision: int | str
    pools: tuple[ApiKeyPool, ...]

    def pool(self, tier: str) -> ApiKeyPool | None:
        normalized = str(tier).strip().lower()
        return next((item for item in self.pools if item.tier == normalized), None)


@dataclass(frozen=True, slots=True)
class AstrBotProviderProjection:
    """An explicit, one-way projection into AstrBot configuration.

    ``for_astrbot`` is intentionally the only method that materializes raw
    keys.  The mapping returned by that method must stay within the AstrBot
    Provider Manager boundary and must never be logged or included in Runtime
    descriptors.
    """

    tier: str
    source_id: str
    provider_id: str
    model: str
    source_type: str
    provider_type: str
    api_base: str
    timeout_seconds: int
    keys: tuple[str, ...] = field(repr=False, compare=False)
    custom_headers: Mapping[str, str] = field(
        default_factory=dict, repr=False, compare=False
    )
    enabled: bool = True

    def for_astrbot(self) -> dict[str, Any]:
        """Materialize a Provider Source/Provider fragment for AstrBot.

        The result contains raw keys by design.  Keep it in the local
        Provider Manager call and discard it after AstrBot has accepted the
        source.  This method does not write ``cmd_config.json``.
        """

        source = {
            "id": self.source_id,
            "type": self.source_type,
            "provider_type": self.provider_type,
            "api_base": self.api_base,
            "key": list(self.keys),
            "custom_headers": dict(self.custom_headers),
            "timeout": self.timeout_seconds,
        }
        provider = {
            "id": self.provider_id,
            "provider_source_id": self.source_id,
            "model": self.model,
            "modalities": ["text"],
            "enable": self.enabled,
        }
        if self.source_type == "openai_chat_completion":
            provider["custom_extra_body"] = {"store": False}
        return {"provider_source": source, "provider": provider}


def configured_api_key_store_path(
    *,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the external store path without reading the file."""

    source = os.environ if environment is None else environment
    value = str(source.get(API_KEY_STORE_PATH_ENV) or "").strip()
    if not value:
        value = str(source.get(API_KEY_STORE_PATH_COMPAT_ENV) or "").strip()
    if not value:
        raise ApiKeyPoolConfigError(
            f"{API_KEY_STORE_PATH_ENV} 未配置（兼容变量 {API_KEY_STORE_PATH_COMPAT_ENV}）"
        )
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ApiKeyPoolConfigError("API Key store path must be absolute")
    return path


def load_api_key_pool_snapshot(
    path: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    require_private_mode: bool = True,
    max_bytes: int = 4 * 1024 * 1024,
) -> ApiKeyPoolSnapshot:
    """Load and validate one immutable API-key pool snapshot.

    The loader accepts the Web gateway's internal object form
    ``pools: {haiku: {...}}`` and the GET-compatible array form
    ``pools: [{tier: "haiku", ...}]``.  Missing tiers are represented as
    disabled empty pools so a partial rollout cannot change tier routing.
    """

    if type(max_bytes) is not int or max_bytes <= 0:
        raise ApiKeyPoolConfigError("API Key store size limit is invalid")
    source_path = (
        Path(path).expanduser()
        if path is not None
        else configured_api_key_store_path(environment=environment)
    )
    if not source_path.is_absolute():
        raise ApiKeyPoolConfigError("API Key store path must be absolute")
    try:
        info = source_path.lstat()
    except OSError as exc:
        raise ApiKeyPoolConfigError("API Key store is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ApiKeyPoolConfigError("API Key store must be a regular file")
    if require_private_mode and stat.S_IMODE(info.st_mode) & 0o077:
        raise ApiKeyPoolConfigError(
            "API Key store permissions must not expose group/other access"
        )
    if info.st_size > max_bytes:
        raise ApiKeyPoolConfigError("API Key store is too large")
    try:
        raw = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ApiKeyPoolConfigError("API Key store cannot be read") from exc
    try:
        document = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ApiKeyPoolConfigError("API Key store JSON is invalid") from exc
    return parse_api_key_pool_snapshot(document)


def parse_api_key_pool_snapshot(document: object) -> ApiKeyPoolSnapshot:
    """Parse a snapshot already held in memory (without exposing secrets)."""

    root = _mapping(document, "snapshot")
    schema_version = _positive_int(
        root.get("schemaVersion", root.get("schema_version", 1)), "schema_version"
    )
    if schema_version != API_KEY_POOL_SCHEMA_VERSION:
        raise ApiKeyPoolConfigError("unsupported API Key store schema version")
    revision = _revision(
        root.get("revision", root.get("configRevision", root.get("config_revision", 1)))
    )
    raw_pools = root.get("pools", {})
    if isinstance(raw_pools, Mapping):
        entries: list[object] = []
        for tier, value in raw_pools.items():
            if not isinstance(value, Mapping):
                raise ApiKeyPoolConfigError("API Key pool must be an object")
            item = dict(value)
            item.setdefault("tier", tier)
            entries.append(item)
    elif isinstance(raw_pools, list):
        entries = list(raw_pools)
    else:
        raise ApiKeyPoolConfigError("API Key store pools must be an object or array")

    parsed: dict[str, ApiKeyPool] = {}
    for value in entries:
        pool = _parse_pool(value)
        if pool.tier in parsed:
            raise ApiKeyPoolConfigError("duplicate API Key pool tier")
        parsed[pool.tier] = pool

    # Keep a deterministic three-tier projection even while a deployment is
    # being prepared.  Empty pools are inert and do not alter TierPolicy.
    pools = tuple(
        parsed.get(tier) or _empty_pool(tier, revision) for tier in API_KEY_POOL_TIERS
    )
    # AstrBot indexes Provider and Source records by ID. Check the completed
    # three-tier projection, not only explicitly supplied entries: a missing
    # tier contributes a generated default ID that can collide with another
    # pool's explicit binding.
    provider_ids = [pool.provider_id for pool in pools]
    source_ids = [pool.source_id for pool in pools]
    if len(set(provider_ids)) != len(provider_ids) or len(set(source_ids)) != len(
        source_ids
    ):
        raise ApiKeyPoolConfigError("API Key provider/source IDs must be unique")
    return ApiKeyPoolSnapshot(
        schema_version=schema_version, revision=revision, pools=pools
    )


def project_pool_to_astrbot(
    pool: ApiKeyPool,
    *,
    secret_resolver: Callable[[str], str] | None = None,
) -> AstrBotProviderProjection:
    """Create an AstrBot Source projection for one validated pool.

    A key may carry a concrete private-store ``secret`` or a ``secret_ref``.
    When the concrete value is absent, ``secret_resolver`` is consulted.  A
    resolver is deliberately explicit so deployments can use an environment
    or platform Secret Manager without making the Domain aware of it.
    """

    keys: list[str] = []
    if pool.enabled and pool.base_url and pool.model:
        for credential in pool.ordered_usable_keys():
            value = credential.secret
            if not value and secret_resolver is not None and credential.secret_ref:
                try:
                    value = str(secret_resolver(credential.secret_ref) or "").strip()
                # Resolver implementations are deployment-owned; normalize
                # every failure here so their exception text cannot disclose
                # a resolved credential through logs or API responses.
                except Exception:  # noqa: BLE001
                    raise ApiKeyPoolConfigError(
                        "API Key SecretRef cannot be resolved"
                    ) from None
            if value:
                keys.append(value)

    return AstrBotProviderProjection(
        tier=pool.tier,
        source_id=pool.source_id,
        provider_id=pool.provider_id,
        model=pool.model,
        source_type=pool.protocol,
        provider_type="chat_completion",
        api_base=pool.base_url,
        timeout_seconds=max(1, min(900, math.ceil(pool.timeout_ms / 1_000))),
        keys=tuple(keys),
        custom_headers=MappingProxyType(dict(pool.custom_headers)),
        enabled=bool(pool.enabled and pool.model and pool.base_url and keys),
    )


def _parse_pool(value: object) -> ApiKeyPool:
    item = _mapping(value, "pool")
    tier = _identifier(item.get("tier"), "tier").lower()
    if tier not in API_KEY_POOL_TIERS:
        raise ApiKeyPoolConfigError("API Key pool tier is invalid")
    display_name = _bounded_text(
        item.get("displayName", item.get("display_name", item.get("name", tier))),
        "display_name",
        required=False,
        default=tier,
    )
    provider = _bounded_text(
        item.get("provider", item.get("providerName", item.get("provider_name", ""))),
        "provider",
        required=False,
    )
    provider_type = _bounded_text(
        item.get("providerType", item.get("provider_type", "chat_completion")),
        "provider_type",
        required=False,
        default="chat_completion",
    )
    provider_id = _identifier(
        item.get("providerId", item.get("provider_id", _DEFAULT_PROVIDER_IDS[tier])),
        "provider_id",
    )
    source_id = _identifier(
        item.get("sourceId", item.get("source_id", f"dududa-{tier}-source")),
        "source_id",
    )
    base_url = _base_url(
        item.get(
            "baseUrl",
            item.get("base_url", item.get("apiBase", item.get("api_base", ""))),
        )
    )
    model = _bounded_text(
        item.get("model", item.get("modelId", item.get("model_id", ""))),
        "model",
        required=False,
    )
    protocol_raw = _bounded_text(
        item.get(
            "protocol",
            item.get(
                "protocolMode", item.get("protocol_mode", "openai_chat_completion")
            ),
        ),
        "protocol",
        required=False,
        default="openai_chat_completion",
    ).lower()
    protocol = _PROTOCOL_ALIASES.get(protocol_raw)
    if protocol is None:
        raise ApiKeyPoolConfigError("API Key pool protocol is unsupported")
    reasoning = _bounded_text(
        item.get(
            "reasoningEffort",
            item.get("reasoning_effort", item.get("reasoning", "low")),
        ),
        "reasoning_effort",
        required=False,
        default="low",
    )
    timeout_ms = _bounded_int(
        item.get("timeoutMs", item.get("timeout_ms", 120_000)),
        "timeout_ms",
        1_000,
        900_000,
    )
    max_output_tokens = _bounded_int(
        item.get("maxOutputTokens", item.get("max_output_tokens", 2_048)),
        "max_output_tokens",
        1,
        1_000_000,
    )
    enabled = _bool(item.get("enabled", False), "enabled")
    scheduling = _bounded_text(
        item.get(
            "schedulingMode",
            item.get("scheduling_mode", item.get("scheduler", "round_robin")),
        ),
        "scheduling_mode",
        required=False,
        default="round_robin",
    )
    headers = _headers(
        item.get("customHeaders", item.get("custom_headers", item.get("headers", {})))
    )
    revision = _revision(
        item.get("revision", item.get("configRevision", item.get("config_revision", 1)))
    )
    raw_keys = item.get(
        "keys", item.get("entries", item.get("keyEntries", item.get("key_entries", [])))
    )
    if not isinstance(raw_keys, list):
        raise ApiKeyPoolConfigError("API Key pool keys must be an array")
    keys = tuple(
        _parse_credential(value, index) for index, value in enumerate(raw_keys)
    )
    return ApiKeyPool(
        tier=tier,
        display_name=display_name,
        provider=provider,
        provider_type=provider_type,
        provider_id=provider_id,
        source_id=source_id,
        base_url=base_url,
        model=model,
        protocol=protocol,
        reasoning_effort=reasoning,
        timeout_ms=timeout_ms,
        max_output_tokens=max_output_tokens,
        enabled=enabled,
        scheduling_mode=scheduling,
        custom_headers=headers,
        revision=revision,
        keys=keys,
    )


def _parse_credential(value: object, index: int) -> ApiKeyCredential:
    item = _mapping(value, "key")
    key_id = _identifier(
        item.get("id", item.get("keyId", item.get("key_id"))), "key_id"
    )
    name = _bounded_text(
        item.get(
            "name",
            item.get("displayName", item.get("display_name", f"Key {index + 1}")),
        ),
        "key_name",
        required=False,
        default=f"Key {index + 1}",
    )
    secret_ref = _bounded_text(
        item.get(
            "secretRef",
            item.get("secret_ref", item.get("secretId", item.get("secret_id", ""))),
        ),
        "secret_ref",
        required=False,
    )
    # The Web store uses ``secret`` internally.  ``credentials.api_key`` is
    # accepted for migration from Sub2API-shaped stores, but no response/API
    # projection should ever use ``key`` or ``value`` as a fallback.
    secret = item.get("secret", "")
    credentials = item.get("credentials")
    if not secret and isinstance(credentials, Mapping):
        secret = credentials.get("api_key", credentials.get("apiKey", ""))
    if secret is None:
        secret = ""
    if not isinstance(secret, str):
        raise ApiKeyPoolConfigError("API Key secret must be text")
    if len(secret) > 16_384:
        raise ApiKeyPoolConfigError("API Key secret is too long")
    priority = _bounded_int(item.get("priority", 0), "priority", 0, 1_000_000)
    weight = _bounded_int(item.get("weight", 1), "weight", 1, 1_000)
    status = _bounded_text(
        item.get("status", item.get("state", "active")),
        "key_status",
        required=False,
        default="active",
    )
    enabled = _bool(item.get("enabled", status.lower() != "disabled"), "key_enabled")
    return ApiKeyCredential(
        id=key_id,
        name=name,
        secret_ref=secret_ref,
        priority=priority,
        weight=weight,
        enabled=enabled,
        status=status,
        secret=secret.strip(),
    )


def _empty_pool(tier: str, revision: int | str) -> ApiKeyPool:
    return ApiKeyPool(
        tier=tier,
        display_name=tier,
        provider="",
        provider_type="chat_completion",
        provider_id=_DEFAULT_PROVIDER_IDS[tier],
        source_id=f"dududa-{tier}-source",
        base_url="",
        model="",
        protocol="openai_chat_completion",
        reasoning_effort="low",
        timeout_ms=120_000,
        max_output_tokens=2_048,
        enabled=False,
        scheduling_mode="round_robin",
        custom_headers=(),
        revision=revision,
        keys=(),
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ApiKeyPoolConfigError(f"API Key {label} must be an object")
    return value


def _bounded_text(
    value: object, label: str, *, required: bool = True, default: str = ""
) -> str:
    if not isinstance(value, str):
        if not required and value is None:
            return default
        raise ApiKeyPoolConfigError(f"API Key {label} must be text")
    text = value.strip()
    if required and not text:
        raise ApiKeyPoolConfigError(f"API Key {label} is required")
    if len(text) > 512:
        raise ApiKeyPoolConfigError(f"API Key {label} is too long")
    return text or default


def _identifier(value: object, label: str) -> str:
    text = _bounded_text(value, label)
    if _IDENTIFIER_RE.fullmatch(text) is None:
        raise ApiKeyPoolConfigError(f"API Key {label} is invalid")
    return text


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApiKeyPoolConfigError(f"API Key {label} is invalid")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ApiKeyPoolConfigError(f"API Key {label} is invalid")
    return value


def _revision(value: object) -> int | str:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.strip() and len(value.strip()) <= 128:
        return value.strip()
    raise ApiKeyPoolConfigError("API Key revision is invalid")


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ApiKeyPoolConfigError(f"API Key {label} is invalid")
    return value


def _base_url(value: object) -> str:
    text = _bounded_text(value, "base_url", required=False)
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise ApiKeyPoolConfigError("API Key base_url is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ApiKeyPoolConfigError(
            "API Key base_url must be an HTTP(S) origin/path without credentials or query"
        )
    return text.rstrip("/")


def _headers(value: object) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        candidates: Sequence[tuple[object, object]] = tuple(value.items())
    elif isinstance(value, list):
        entries: list[tuple[object, object]] = []
        for candidate in value:
            item = _mapping(candidate, "custom_header")
            entries.append(
                (
                    item.get("name", item.get("headerName", item.get("header_name"))),
                    item.get(
                        "value", item.get("headerValue", item.get("header_value"))
                    ),
                )
            )
        candidates = tuple(entries)
    else:
        raise ApiKeyPoolConfigError("API Key custom_headers must be an object or array")
    for name, raw_value in candidates:
        header_name = _bounded_text(name, "custom_header_name")
        header_value = _bounded_text(raw_value, "custom_header_value")
        if _HEADER_NAME_RE.fullmatch(
            header_name
        ) is None or _SENSITIVE_HEADER_RE.search(header_name):
            raise ApiKeyPoolConfigError(
                "API Key custom header cannot carry credentials"
            )
        if any(
            ord(character) < 0x20 or ord(character) == 0x7F
            for character in header_value
        ):
            raise ApiKeyPoolConfigError(
                "API Key custom header value contains control characters"
            )
        pairs.append((header_name, header_value))
    if len(pairs) > 32:
        raise ApiKeyPoolConfigError("too many API Key custom headers")
    return tuple(pairs)


__all__ = [
    "API_KEY_POOL_SCHEMA_VERSION",
    "API_KEY_POOL_TIERS",
    "API_KEY_STORE_PATH_COMPAT_ENV",
    "API_KEY_STORE_PATH_ENV",
    "ApiKeyCredential",
    "ApiKeyPool",
    "ApiKeyPoolConfigError",
    "ApiKeyPoolSnapshot",
    "AstrBotProviderProjection",
    "configured_api_key_store_path",
    "load_api_key_pool_snapshot",
    "parse_api_key_pool_snapshot",
    "project_pool_to_astrbot",
]
