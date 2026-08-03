from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import hmac
import json
import math
import re
import unicodedata
from typing import Mapping

from dududa.domain.primitives import DigestString
from dududa.errors import validation_error


CODEC_ID = "dududa-c14n-v1"
_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9._:/-]*:v[1-9][0-9]*$")
_DIGEST_RE = re.compile(
    r"^dududa-c14n-v1:(?P<domain>[a-z0-9][a-z0-9._:/-]*:v[1-9][0-9]*):"
    r"sha-256:(?P<digest>[0-9a-f]{64})$"
)


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a supported value to deterministic UTF-8 JSON bytes."""

    return _encode(value, path="$", active=set())


def canonical_digest(value: object, *, domain: str) -> DigestString:
    """Hash canonical bytes with an explicit, versioned domain separator."""

    _validate_domain(domain)
    material = (
        CODEC_ID.encode("ascii")
        + b"\x00"
        + domain.encode("ascii")
        + b"\x00"
        + canonical_json_bytes(value)
    )
    payload_digest = hashlib.sha256(material).hexdigest()
    return DigestString(f"{CODEC_ID}:{domain}:sha-256:{payload_digest}")


def verify_canonical_digest(
    value: object,
    digest: DigestString | str,
    *,
    domain: str,
) -> bool:
    _validate_domain(domain)
    encoded = str(digest)
    match = _DIGEST_RE.fullmatch(encoded)
    if match is None or match.group("domain") != domain:
        return False
    expected = str(canonical_digest(value, domain=domain))
    return hmac.compare_digest(encoded, expected)


def canonical_schema_digest(
    bundle: Mapping[str, object],
    *,
    schema_id: str,
    schema_version: int,
) -> DigestString:
    """Digest a complete offline schema bundle without resolving remote refs."""

    if not schema_id or schema_version < 1:
        raise validation_error("invalid_schema_identity")
    _reject_remote_refs(bundle, path="$", active=set())
    return canonical_digest(
        bundle,
        domain=f"schema:{schema_id}:v{schema_version}",
    )


def _encode(value: object, *, path: str, active: set[int]) -> bytes:
    if value is None:
        return b"null"
    if isinstance(value, bool):
        return b"true" if value else b"false"
    if isinstance(value, Enum):
        return _encode(value.value, path=path, active=active)
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, Decimal):
        return _canonical_decimal(value, path=path).encode("ascii")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise validation_error("non_finite_number", path)
        return _canonical_decimal(Decimal(repr(value)), path=path).encode("ascii")
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise validation_error("naive_datetime", path)
        utc = value.astimezone(timezone.utc)
        normalized = (
            f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}T"
            f"{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}."
            f"{utc.microsecond:06d}Z"
        )
        return _encode(normalized, path=path, active=active)
    if isinstance(value, timedelta):
        total_microseconds = (
            value.days * 86400 + value.seconds
        ) * 1_000_000 + value.microseconds
        sign = "-" if total_microseconds < 0 else ""
        absolute = abs(total_microseconds)
        seconds, microseconds = divmod(absolute, 1_000_000)
        normalized = f"{sign}PT{seconds}.{microseconds:06d}S"
        return _encode(normalized, path=path, active=active)
    if is_dataclass(value) and not isinstance(value, type):
        return _with_cycle_guard(
            value,
            path=path,
            active=active,
            encode=lambda: _encode_mapping(
                {item.name: getattr(value, item.name) for item in fields(value)},
                path=path,
                active=active,
            ),
        )
    if isinstance(value, Mapping):
        return _with_cycle_guard(
            value,
            path=path,
            active=active,
            encode=lambda: _encode_mapping(value, path=path, active=active),
        )
    if isinstance(value, (list, tuple)):
        return _with_cycle_guard(
            value,
            path=path,
            active=active,
            encode=lambda: b"["
            + b",".join(
                _encode(item, path=f"{path}[{index}]", active=active)
                for index, item in enumerate(value)
            )
            + b"]",
        )
    if isinstance(value, (set, frozenset)):
        return _with_cycle_guard(
            value,
            path=path,
            active=active,
            encode=lambda: _encode_set(value, path=path, active=active),
        )
    raise validation_error("unsupported_canonical_value", path, type(value).__name__)


def _encode_mapping(
    value: Mapping[object, object],
    *,
    path: str,
    active: set[int],
) -> bytes:
    entries: list[tuple[bytes, bytes]] = []
    normalized_keys: set[str] = set()
    for key, item in value.items():
        if not isinstance(key, str):
            raise validation_error("non_string_mapping_key", path)
        normalized_key = unicodedata.normalize("NFC", key)
        if normalized_key in normalized_keys:
            raise validation_error("duplicate_canonical_key", path, normalized_key)
        normalized_keys.add(normalized_key)
        encoded_key = _encode(normalized_key, path=f"{path}.<key>", active=active)
        encoded_value = _encode(item, path=f"{path}.{normalized_key}", active=active)
        entries.append((encoded_key, encoded_value))
    entries.sort(key=lambda entry: entry[0])
    return b"{" + b",".join(key + b":" + item for key, item in entries) + b"}"


def _encode_set(
    value: set[object] | frozenset[object], *, path: str, active: set[int]
) -> bytes:
    encoded = sorted(_encode(item, path=f"{path}[]", active=active) for item in value)
    if len(encoded) != len(set(encoded)):
        raise validation_error("duplicate_canonical_set_item", path)
    return b"[" + b",".join(encoded) + b"]"


def _canonical_decimal(value: Decimal, *, path: str) -> str:
    if not value.is_finite():
        raise validation_error("non_finite_number", path)
    if value.is_zero():
        return "0"
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result


def _with_cycle_guard(
    value: object,
    *,
    path: str,
    active: set[int],
    encode: object,
) -> bytes:
    identity = id(value)
    if identity in active:
        raise validation_error("cyclic_canonical_value", path)
    active.add(identity)
    try:
        return encode()  # type: ignore[operator]
    finally:
        active.remove(identity)


def _validate_domain(domain: str) -> None:
    if _DOMAIN_RE.fullmatch(domain) is None:
        raise validation_error("invalid_digest_domain", domain)


def _reject_remote_refs(value: object, *, path: str, active: set[int]) -> None:
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise validation_error("cyclic_schema_bundle", path)
        active.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise validation_error("non_string_mapping_key", path)
                if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (
                    not isinstance(item, str) or not item.startswith("#")
                ):
                    raise validation_error("remote_schema_ref_forbidden", path)
                _reject_remote_refs(item, path=f"{path}.{key}", active=active)
        finally:
            active.remove(identity)
    elif isinstance(value, (list, tuple, set, frozenset)):
        identity = id(value)
        if identity in active:
            raise validation_error("cyclic_schema_bundle", path)
        active.add(identity)
        try:
            for index, item in enumerate(value):
                _reject_remote_refs(item, path=f"{path}[{index}]", active=active)
        finally:
            active.remove(identity)
