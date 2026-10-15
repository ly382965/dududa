from __future__ import annotations

import hashlib
import re
from typing import Mapping
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dududa.domain.primitives import JsonValue, freeze_json

from .models import RedactionRequest, RedactionResult


_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|cookie|authorization|credential)(?:$|[_-])",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_API_KEY = re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
)
_ABSOLUTE_PATH = re.compile(r"^(?:/[^\s]+|[A-Za-z]:[\\/][^\s]+)$")
_EMBEDDED_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9:/])/(?:[A-Za-z0-9._~-]+/)+[^\s/]+")
_EMBEDDED_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s]+")
_FILE_URI = re.compile(r"(?i)\bfile://[^\s\"'<>]+")
_HTTP_URL = re.compile(r"(?i)\bhttps?://[^\s\"'<>]+")
_SECRET_CANDIDATE = re.compile(r"[A-Za-z0-9._~+/=-]{8,}")
_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "auth",
    "authorization",
    "credential",
    "key",
    "password",
    "refresh_token",
    "secret",
    "signature",
    "token",
}


class DefaultRedactor:
    def __init__(
        self,
        *,
        revision: str = "redactor-v1",
        secret_fingerprints: frozenset[str] = frozenset(),
        maximum_string_characters: int = 2048,
    ) -> None:
        if not revision.strip() or maximum_string_characters < 1:
            raise ValueError("invalid redactor configuration")
        self._revision = revision
        self._secret_fingerprints = frozenset(secret_fingerprints)
        self._maximum = maximum_string_characters

    @staticmethod
    def fingerprint(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    def redact(self, request: RedactionRequest) -> RedactionResult:
        reasons: set[str] = set()
        value = self._redact_value(request.value, reasons, key=None)
        frozen = freeze_json(value)
        return RedactionResult(
            schema_version=1,
            value=frozen,
            changed=frozen != request.value,
            reason_codes=tuple(sorted(reasons)),
            redactor_revision=self._revision,
        )

    def _redact_value(
        self,
        value: JsonValue,
        reasons: set[str],
        *,
        key: str | None,
    ) -> JsonValue:
        if key is not None and _is_sensitive_key(key):
            if value in (None, "", False):
                return value
            reasons.add("sensitive_field")
            return "[REDACTED]"
        if isinstance(value, Mapping):
            return {
                str(item_key): self._redact_value(item, reasons, key=str(item_key))
                for item_key, item in value.items()
            }
        if isinstance(value, tuple):
            return tuple(self._redact_value(item, reasons, key=None) for item in value)
        if isinstance(value, str):
            return self._redact_string(value, reasons)
        return value

    def _redact_string(self, value: str, reasons: set[str]) -> str:
        if value in {"[REDACTED]", "[PATH]"}:
            return value
        if self.fingerprint(value) in self._secret_fingerprints:
            reasons.add("secret_fingerprint")
            return "[REDACTED]"
        result = value
        for candidate in _SECRET_CANDIDATE.findall(result):
            if self.fingerprint(candidate) in self._secret_fingerprints:
                reasons.add("secret_fingerprint")
                result = result.replace(candidate, "[REDACTED]")
        if _ABSOLUTE_PATH.fullmatch(value) or value.lower().startswith("file://"):
            reasons.add("absolute_path")
            return "[PATH]"
        result = _PRIVATE_KEY.sub("[REDACTED]", result)
        result = _BEARER.sub("Bearer [REDACTED]", result)
        result = _JWT.sub("[REDACTED]", result)
        result = _API_KEY.sub("[REDACTED]", result)
        if result != value and "secret_fingerprint" not in reasons:
            reasons.add("credential_pattern")
        result = self._redact_urls(result, reasons)
        result = _FILE_URI.sub("[PATH]", result)
        path_redacted = _EMBEDDED_WINDOWS_PATH.sub("[PATH]", result)
        path_redacted = _EMBEDDED_POSIX_PATH.sub("[PATH]", path_redacted)
        if path_redacted != result:
            reasons.add("absolute_path")
            result = path_redacted
        if len(result) > self._maximum:
            result = result[: self._maximum] + "[TRUNCATED]"
            reasons.add("string_truncated")
        return result

    def _redact_urls(self, value: str, reasons: set[str]) -> str:
        return _HTTP_URL.sub(
            lambda match: self._redact_url(match.group(0), reasons),
            value,
        )

    def _redact_url(self, value: str, reasons: set[str]) -> str:
        try:
            parsed = urlsplit(value)
        except ValueError:
            reasons.add("invalid_url")
            return "[URL]"
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            reasons.add("invalid_url")
            return "[URL]"
        changed = False
        try:
            hostname = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port is not None else ""
        except ValueError:
            reasons.add("invalid_url")
            return "[URL]"
        netloc = hostname + port
        if parsed.username is not None or parsed.password is not None:
            changed = True
        query = []
        try:
            parsed_query = parse_qsl(parsed.query, keep_blank_values=True)
        except ValueError:
            reasons.add("invalid_url")
            return "[URL]"
        for key, item in parsed_query:
            if key.lower() in _SENSITIVE_QUERY_KEYS or _is_sensitive_key(key):
                query.append((key, "[REDACTED]"))
                changed = True
            else:
                query.append((key, item))
        if not changed:
            return value
        reasons.add("sensitive_url")
        return urlunsplit(
            (parsed.scheme, netloc, parsed.path, urlencode(query), parsed.fragment)
        )


def _is_sensitive_key(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized.casefold()).strip("_")
    return _SENSITIVE_KEY.search(normalized) is not None
