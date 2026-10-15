from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from .config import AppConfig
from .errors import NotifAIError, NotifAIValidationError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
_HTTP_URL_RE = re.compile(r"(?i)https?://[^\s\"'<>]+")


class _HttpxQueryRedactionFilter(logging.Filter):
    """Keep HTTPX diagnostics useful without copying request query data to logs."""

    _notifai_query_redaction_filter = True

    def filter(self, record: Any) -> bool:
        try:
            rendered = record.getMessage()
        except (AttributeError, TypeError, ValueError):  # pragma: no cover
            return True
        redacted = _HTTP_URL_RE.sub(_redact_logged_url, rendered)
        if redacted != rendered:
            # The message has already been rendered, so clear args to avoid a
            # second %-format pass by handlers.
            record.msg = redacted
            record.args = ()
        return True


def _redact_logged_url(match: re.Match[str]) -> str:
    value = match.group(0)
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[URL]"
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "[URL]"
    # Query strings contain free-form user input (for example `keyword`) and
    # must not be copied into the MCP process logs.
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _install_httpx_query_redaction() -> None:
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        if not any(
            getattr(item, "_notifai_query_redaction_filter", False)
            for item in logger.filters
        ):
            logger.addFilter(_HttpxQueryRedactionFilter())


def _text(value: str | None, name: str, *, max_length: int, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise NotifAIValidationError(f"{name} is required")
        return None
    if not isinstance(value, str):
        raise NotifAIValidationError(f"{name} must be a string")
    value = value.strip()
    if required and not value:
        raise NotifAIValidationError(f"{name} must not be empty")
    if len(value) > max_length:
        raise NotifAIValidationError(f"{name} is too long")
    if any(ord(char) < 32 and char not in {"\t"} for char in value):
        raise NotifAIValidationError(f"{name} contains control characters")
    return value or None


def _text_list(
    values: Iterable[str] | None,
    name: str,
    *,
    max_items: int,
    max_length: int,
) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise NotifAIValidationError(f"{name} must be an array")
    values = list(values)
    if len(values) > max_items:
        raise NotifAIValidationError(f"{name} contains too many items")
    result: list[str] = []
    for value in values:
        cleaned = _text(value, name, max_length=max_length, required=True)
        if cleaned not in result:
            result.append(cleaned)
    return result


def _integer(value: int, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NotifAIValidationError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise NotifAIValidationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(value: bool | None, name: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise NotifAIValidationError(f"{name} must be a boolean")
    return value


def _date(value: str | None, name: str) -> str | None:
    value = _text(value, name, max_length=10)
    if value is None:
        return None
    if not _DATE_RE.fullmatch(value):
        raise NotifAIValidationError(f"{name} must use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise NotifAIValidationError(f"{name} must be a valid date") from exc
    return value


def _iso_datetime(value: str | None, name: str) -> str | None:
    value = _text(value, name, max_length=80)
    if value is None:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NotifAIValidationError(f"{name} must be a valid ISO 8601 timestamp") from exc
    return value


def _month(value: str | None) -> str | None:
    value = _text(value, "month", max_length=7)
    if value is None:
        return None
    if not _MONTH_RE.fullmatch(value):
        raise NotifAIValidationError("month must use YYYY-MM")
    try:
        date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise NotifAIValidationError("month must be valid") from exc
    return value


def _week(value: str | None) -> str | None:
    value = _text(value, "week", max_length=8)
    if value is None:
        return None
    if not _WEEK_RE.fullmatch(value):
        raise NotifAIValidationError("week must use YYYY-Www")
    year = int(value[:4])
    week = int(value[-2:])
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise NotifAIValidationError("week must be a valid ISO week") from exc
    return value


def _params_add(params: list[tuple[str, str]], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        params.append((key, "true" if value else "false"))
    else:
        params.append((key, str(value)))


def _params_add_many(params: list[tuple[str, str]], key: str, values: Iterable[str] | None) -> None:
    if values:
        for value in values:
            params.append((key, value))


class NotifAIClient:
    """Small, bounded client for the public NotifAI HTTP contract."""

    def __init__(
        self,
        config: AppConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        _install_httpx_query_redaction()
        self._http = http_client or httpx.Client(
            timeout=config.timeout,
            transport=transport,
            headers={"Accept": "application/json"},
            trust_env=False,
        )
        self._owns_http = http_client is None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _request(
        self,
        path: str,
        params: list[tuple[str, str]] | None = None,
        *,
        not_found_code: str | None = None,
    ) -> Any:
        url = f"{self.config.base_url}/{path.lstrip('/')}"
        try:
            response = self._http.get(url, params=params or [])
        except httpx.TimeoutException as exc:
            raise NotifAIError("upstream_timeout", "NotifAI API timed out.", retryable=True) from exc
        except httpx.RequestError as exc:
            raise NotifAIError("upstream_unavailable", "NotifAI API is unavailable.", retryable=True) from exc

        if not 200 <= response.status_code < 300:
            if response.status_code == 404 and not_found_code:
                code = not_found_code
                message = "The requested notice was not found."
            elif response.status_code in {400, 422}:
                code = "invalid_upstream_request"
                message = "NotifAI rejected the request parameters."
            elif response.status_code >= 500:
                code = "upstream_unavailable"
                message = "NotifAI API is temporarily unavailable."
            else:
                code = "upstream_http_error"
                message = "NotifAI API returned an unexpected status."
            raise NotifAIError(
                code,
                message,
                retryable=response.status_code >= 500,
                status=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise NotifAIError("invalid_upstream_response", "NotifAI returned invalid JSON.") from exc

    def search_notices(
        self,
        *,
        keyword: str | None = None,
        source: str | None = None,
        sources: Iterable[str] | None = None,
        categories: Iterable[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        range_from: str | None = None,
        range_to: str | None = None,
        has_deadline: bool | None = None,
        since: str | None = None,
        exclude_ids: Iterable[str] | None = None,
        light: bool = True,
        cursor: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Any:
        keyword = _text(keyword, "keyword", max_length=200)
        source = _text(source, "source", max_length=120)
        sources = _text_list(sources, "sources", max_items=20, max_length=120)
        categories = _text_list(categories, "categories", max_items=20, max_length=80)
        date_from = _date(date_from, "date_from")
        date_to = _date(date_to, "date_to")
        range_from = _date(range_from, "range_from")
        range_to = _date(range_to, "range_to")
        has_deadline = _boolean(has_deadline, "has_deadline")
        since = _iso_datetime(since, "since")
        exclude_ids = _text_list(exclude_ids, "exclude_ids", max_items=500, max_length=200)
        cursor = _text(cursor, "cursor", max_length=2000)
        page = _integer(page, "page", minimum=1, maximum=10000)
        page_size = _integer(page_size, "page_size", minimum=1, maximum=min(1000, self.config.max_items))
        light = _boolean(light, "light")
        assert light is not None

        params: list[tuple[str, str]] = []
        _params_add(params, "keyword", keyword)
        _params_add(params, "source", source)
        _params_add_many(params, "sources[]", sources)
        _params_add_many(params, "categories[]", categories)
        _params_add(params, "dateFrom", date_from)
        _params_add(params, "dateTo", date_to)
        _params_add(params, "rangeFrom", range_from)
        _params_add(params, "rangeTo", range_to)
        _params_add(params, "hasDeadline", has_deadline)
        _params_add(params, "since", since)
        _params_add_many(params, "excludeIds[]", exclude_ids)
        _params_add(params, "light", light)
        _params_add(params, "cursor", cursor)
        _params_add(params, "page", page)
        _params_add(params, "pageSize", page_size)
        return self._request("notices", params)

    def get_notice(self, notice_id: str) -> Any:
        notice_id = _text(notice_id, "notice_id", max_length=200, required=True)
        assert notice_id is not None
        return self._request(
            f"notices/{quote(notice_id, safe='')}",
            not_found_code="notice_not_found",
        )

    def get_notice_calendar(self, *, month: str | None = None, week: str | None = None) -> Any:
        month = _month(month)
        week = _week(week)
        if (month is None) == (week is None):
            raise NotifAIValidationError("provide exactly one of month or week")
        params: list[tuple[str, str]] = []
        _params_add(params, "month", month)
        _params_add(params, "week", week)
        return self._request("notices/calendar", params)

    def get_notice_deadlines(
        self,
        *,
        days: int = 7,
        sources: Iterable[str] | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Any:
        days = _integer(days, "days", minimum=1, maximum=365)
        sources = _text_list(sources, "sources", max_items=20, max_length=120)
        page = _integer(page, "page", minimum=1, maximum=10000)
        page_size = _integer(page_size, "page_size", minimum=1, maximum=min(500, self.config.max_items))
        params: list[tuple[str, str]] = []
        _params_add(params, "days", days)
        _params_add_many(params, "sources[]", sources)
        _params_add(params, "page", page)
        _params_add(params, "pageSize", page_size)
        return self._request("notices/deadlines", params)

    def list_notice_sources(self) -> Any:
        return self._request("sources")

    def list_notice_categories(self) -> Any:
        return self._request("categories")

    def get_notice_stats(self) -> Any:
        return self._request("stats")
