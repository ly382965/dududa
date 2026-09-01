from __future__ import annotations

import argparse
import atexit
import json
import logging
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from .client import NotifAIClient
from .config import AppConfig
from .errors import NotifAIError

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1
MAX_TITLE_LENGTH = 500
MAX_SUMMARY_LENGTH = 1600
MAX_CONTENT_LENGTH = 12000
MAX_LIST_ITEMS = 500
MAX_PAYLOAD_CHARS = 120000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, limit: int) -> tuple[str, bool]:
    if not isinstance(value, str):
        return "", False
    value = value.replace("\x00", "")
    if len(value) <= limit:
        return value, False
    return value[: max(0, limit - 1)] + "…", True


def _safe_url(value: Any) -> tuple[str, bool]:
    if not isinstance(value, str) or not value:
        return "", False
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
        return "", True
    cleaned, truncated = _safe_text(value, limit=2048)
    return cleaned, truncated


def _notice(value: Any, *, include_content: bool = True) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(value, dict):
        return {}, ["invalid_notice_item"]
    warnings: list[str] = []

    def text_field(key: str, limit: int) -> str:
        result, truncated = _safe_text(value.get(key), limit=limit)
        if truncated:
            warnings.append(f"truncated_{key}")
        return result

    origin_url, invalid_url = _safe_url(value.get("originUrl"))
    if invalid_url:
        warnings.append("invalid_origin_url")

    attachments: list[dict[str, str]] = []
    raw_attachments = value.get("attachments")
    if isinstance(raw_attachments, list):
        for raw in raw_attachments[:20]:
            if not isinstance(raw, dict):
                continue
            name, name_truncated = _safe_text(raw.get("name"), limit=300)
            url, url_invalid_or_truncated = _safe_url(raw.get("url"))
            if name_truncated:
                warnings.append("truncated_attachment_name")
            if url_invalid_or_truncated:
                warnings.append("invalid_attachment_url")
            if name and url:
                attachments.append({"name": name, "url": url})

    categories = value.get("categories")
    if not isinstance(categories, list):
        categories = []
    categories = [item for item in categories if isinstance(item, str)][:20]
    content = text_field("cleanContent", MAX_CONTENT_LENGTH) if include_content else ""
    if not include_content and value.get("cleanContent"):
        warnings.append("content_omitted_in_light_mode")

    return {
        "id": text_field("id", 200),
        "title": text_field("title", MAX_TITLE_LENGTH),
        "source": text_field("source", 200),
        "categories": categories,
        "publishDate": text_field("publishDate", 10),
        "aiSummary": text_field("aiSummary", MAX_SUMMARY_LENGTH),
        "deadline": text_field("deadline", 10) or None,
        "targetAudience": text_field("targetAudience", 800),
        "coreAction": text_field("coreAction", 1200),
        "originUrl": origin_url,
        "cleanContent": content,
        "firstSeen": text_field("firstSeen", 80) or None,
        "lastCrawl": text_field("lastCrawl", 80) or None,
        "attachments": attachments,
    }, warnings


def _calendar_item(value: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(value, dict):
        return {}, ["invalid_calendar_item"]
    item = {
        "id": _safe_text(value.get("id"), limit=200)[0],
        "title": _safe_text(value.get("title"), limit=MAX_TITLE_LENGTH)[0],
        "source": _safe_text(value.get("source"), limit=200)[0],
        "publishDate": _safe_text(value.get("publishDate"), limit=10)[0],
        "deadline": _safe_text(value.get("deadline"), limit=10)[0] or None,
    }
    warnings: list[str] = []
    for key, limit in (("id", 200), ("title", MAX_TITLE_LENGTH), ("source", 200), ("publishDate", 10), ("deadline", 10)):
        if _safe_text(value.get(key), limit=limit)[1]:
            warnings.append("truncated_calendar_item")
            break
    return item, warnings


def _deadline_item(value: Any) -> tuple[dict[str, Any], list[str]]:
    item, warnings = _calendar_item(value)
    if not isinstance(value, dict):
        return item, warnings
    summary, summary_truncated = _safe_text(value.get("aiSummary"), limit=MAX_SUMMARY_LENGTH)
    audience, audience_truncated = _safe_text(value.get("targetAudience"), limit=800)
    item.update({"aiSummary": summary, "targetAudience": audience})
    if summary_truncated or audience_truncated:
        warnings.append("truncated_deadline_item")
    return item, warnings


def _list_items(
    values: Any,
    normalizer: Callable[[Any], tuple[dict[str, Any], list[str]]],
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(values, list):
        raise NotifAIError("invalid_upstream_response", "NotifAI returned an invalid list.")
    warnings: list[str] = []
    if len(values) > max_items:
        warnings.append("items_truncated")
    items = []
    for value in values[:max_items]:
        item, item_warnings = normalizer(value)
        if item:
            items.append(item)
        warnings.extend(item_warnings)
    return items, sorted(set(warnings))


def _dict_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NotifAIError("invalid_upstream_response", "NotifAI returned an invalid object.")
    return value


def _success(data: Any, warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "data": data,
        "error": None,
        "source": "notifai",
        "observed_at": _now(),
        "warnings": sorted(set(warnings or [])),
    }


def _failure(error: NotifAIError) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "data": None,
        "error": {
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
        },
        "source": "notifai",
        "observed_at": _now(),
        "warnings": [],
    }
    if error.status is not None:
        result["error"]["status"] = error.status
    return result


def _run(fetch: Callable[[], Any], transform: Callable[[Any], tuple[Any, list[str]]]) -> dict[str, Any]:
    try:
        payload = fetch()
        data, warnings = transform(payload)
        if len(json.dumps(data, ensure_ascii=False, separators=(",", ":"))) > MAX_PAYLOAD_CHARS:
            raise NotifAIError("result_too_large", "NotifAI returned more data than this MCP tool allows.")
        return _success(data, warnings)
    except NotifAIError as exc:
        return _failure(exc)
    except Exception:
        LOGGER.exception("Unexpected NotifAI MCP operation failure")
        return _failure(NotifAIError("internal_error", "NotifAI MCP operation failed."))


def _transform_search(payload: Any, *, max_items: int) -> tuple[dict[str, Any], list[str]]:
    payload = _dict_payload(payload)
    items, warnings = _list_items(
        payload.get("items", []),
        lambda value: _notice(value, include_content=False),
        max_items=max_items,
    )
    total = payload.get("total", len(items))
    if not isinstance(total, int) or total < 0:
        raise NotifAIError("invalid_upstream_response", "NotifAI returned an invalid total.")
    next_cursor, truncated = _safe_text(payload.get("nextCursor"), limit=2000)
    if truncated:
        warnings.append("truncated_next_cursor")
    return {"items": items, "total": total, "nextCursor": next_cursor or None}, warnings


def _transform_notice(payload: Any) -> tuple[dict[str, Any], list[str]]:
    item, warnings = _notice(payload, include_content=True)
    if not item.get("id"):
        raise NotifAIError("invalid_upstream_response", "NotifAI returned a notice without an ID.")
    return item, warnings


def _transform_calendar(payload: Any, *, max_items: int) -> tuple[dict[str, Any], list[str]]:
    payload = _dict_payload(payload)
    items, warnings = _list_items(
        payload.get("items", []),
        _calendar_item,
        max_items=min(max_items, MAX_LIST_ITEMS),
    )
    return {"items": items}, warnings


def _transform_deadlines(payload: Any, *, max_items: int) -> tuple[dict[str, Any], list[str]]:
    payload = _dict_payload(payload)
    items, warnings = _list_items(payload.get("items", []), _deadline_item, max_items=max_items)
    total = payload.get("total", len(items))
    if not isinstance(total, int) or total < 0:
        raise NotifAIError("invalid_upstream_response", "NotifAI returned an invalid total.")
    return {"items": items, "total": total}, warnings


def _source_item(value: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(value, dict):
        return {}, ["invalid_source_item"]
    name, name_truncated = _safe_text(value.get("name"), limit=200)
    group, group_truncated = _safe_text(value.get("group"), limit=80)
    count = value.get("noticeCount", 0)
    if not isinstance(count, int) or count < 0:
        count = 0
    warnings = ["truncated_source_item"] if name_truncated or group_truncated else []
    return {"name": name, "group": group, "noticeCount": count}, warnings


def _transform_sources(payload: Any, *, max_items: int) -> tuple[dict[str, Any], list[str]]:
    items, warnings = _list_items(payload, _source_item, max_items=min(max_items, MAX_LIST_ITEMS))
    return {"items": items}, warnings


def _category_item(value: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(value, dict):
        return {}, ["invalid_category_item"]
    key, key_truncated = _safe_text(value.get("key"), limit=100)
    name, name_truncated = _safe_text(value.get("name"), limit=200)
    description, description_truncated = _safe_text(value.get("description"), limit=800)
    count = value.get("noticeCount", 0)
    if not isinstance(count, int) or count < 0:
        count = 0
    warnings = ["truncated_category_item"] if key_truncated or name_truncated or description_truncated else []
    return {"key": key, "name": name, "description": description, "noticeCount": count}, warnings


def _transform_categories(payload: Any, *, max_items: int) -> tuple[dict[str, Any], list[str]]:
    items, warnings = _list_items(payload, _category_item, max_items=min(max_items, MAX_LIST_ITEMS))
    return {"items": items}, warnings


def _transform_stats(payload: Any) -> tuple[dict[str, Any], list[str]]:
    payload = _dict_payload(payload)
    result: dict[str, Any] = {}
    for key in ("total", "sourceCount", "last7DaysDdl", "last24hNew"):
        value = payload.get(key, 0)
        if not isinstance(value, int) or value < 0:
            raise NotifAIError("invalid_upstream_response", "NotifAI returned invalid statistics.")
        result[key] = value
    last_crawl, truncated = _safe_text(payload.get("lastCrawlAt"), limit=80)
    if truncated:
        return {**result, "lastCrawlAt": last_crawl or None}, ["truncated_last_crawl_at"]
    return {**result, "lastCrawlAt": last_crawl or None}, []


def create_mcp(config: AppConfig, *, client: NotifAIClient | None = None) -> FastMCP:
    mcp = FastMCP("notifai-mcp")
    api = client or NotifAIClient(config)
    if client is None:
        atexit.register(api.close)

    @mcp.tool()
    def search_notices(
        keyword: str | None = None,
        source: str | None = None,
        sources: list[str] | None = None,
        categories: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        range_from: str | None = None,
        range_to: str | None = None,
        has_deadline: bool | None = None,
        since: str | None = None,
        exclude_ids: list[str] | None = None,
        light: bool = True,
        cursor: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """Search public campus notices by keyword, source, category, date, or deadline."""
        return _run(
            lambda: api.search_notices(
                keyword=keyword,
                source=source,
                sources=sources,
                categories=categories,
                date_from=date_from,
                date_to=date_to,
                range_from=range_from,
                range_to=range_to,
                has_deadline=has_deadline,
                since=since,
                exclude_ids=exclude_ids,
                light=light,
                cursor=cursor,
                page=page,
                page_size=page_size,
            ),
            lambda payload: _transform_search(payload, max_items=config.max_items),
        )

    @mcp.tool()
    def get_notice(notice_id: str) -> dict[str, Any]:
        """Get one public campus notice, including its cleaned Markdown content."""
        return _run(lambda: api.get_notice(notice_id), _transform_notice)

    @mcp.tool()
    def get_notice_calendar(month: str | None = None, week: str | None = None) -> dict[str, Any]:
        """Get lightweight notice nodes for one calendar month or ISO week."""
        return _run(
            lambda: api.get_notice_calendar(month=month, week=week),
            lambda payload: _transform_calendar(payload, max_items=config.max_items),
        )

    @mcp.tool()
    def get_notice_deadlines(
        days: int = 7,
        sources: list[str] | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Get public notices with deadlines in the next number of days."""
        return _run(
            lambda: api.get_notice_deadlines(days=days, sources=sources, page=page, page_size=page_size),
            lambda payload: _transform_deadlines(payload, max_items=config.max_items),
        )

    @mcp.tool()
    def list_notice_sources() -> dict[str, Any]:
        """List campus notice sources and their current counts."""
        return _run(
            api.list_notice_sources,
            lambda payload: _transform_sources(payload, max_items=config.max_items),
        )

    @mcp.tool()
    def list_notice_categories() -> dict[str, Any]:
        """List the campus notice category dictionary and current counts."""
        return _run(
            api.list_notice_categories,
            lambda payload: _transform_categories(payload, max_items=config.max_items),
        )

    @mcp.tool()
    def get_notice_stats() -> dict[str, Any]:
        """Get aggregate counts and the latest NotifAI crawl time."""
        return _run(api.get_notice_stats, _transform_stats)

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the NotifAI campus-notice MCP server over stdio.")
    parser.add_argument("--base-url", default=None, help=f"NotifAI API base URL. Default: {AppConfig().base_url}")
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout in seconds. Default: 15")
    parser.add_argument("--max-items", type=int, default=None, help="Maximum items returned by one tool call. Default: 100")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = AppConfig.from_args(base_url=args.base_url, timeout=args.timeout, max_items=args.max_items)
    create_mcp(config).run()


if __name__ == "__main__":
    main(sys.argv[1:])
