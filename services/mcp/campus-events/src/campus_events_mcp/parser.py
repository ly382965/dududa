from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .models import EventDetail, EventItem

EVENT_ID_RE = re.compile(r"/info/(\d+)/(\d+)\.htm")
LIST_DATE_RE = re.compile(r"(?:20\d{2}|)(\d{1,2})[-/](\d{1,2})")
PUBLISHED_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TITLE_SUFFIX_RE = re.compile(r"\s*[|｜\-–]\s*中国科学技术大学\s*$")
ATTACHMENT_EXT_RE = re.compile(r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|txt)$", re.IGNORECASE)


def event_id_from_url(url: str) -> str | None:
    match = EVENT_ID_RE.search(url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def is_allowed_source_url(url: str, base_url: str) -> bool:
    """Allow only HTTPS URLs on the configured campus source origin."""

    try:
        parsed = urlsplit(url)
        base = urlsplit(base_url)
        port = parsed.port
        base_port = base.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == base.hostname
        and parsed.username is None
        and parsed.password is None
        and port == base_port
    )


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"<[^>]+>", "", title).strip()
    title = TITLE_SUFFIX_RE.sub("", title).strip()
    return title


def _resolve_date(mm_dd: str | None, today: date | None = None) -> str | None:
    if not mm_dd:
        return None
    match = LIST_DATE_RE.search(mm_dd)
    if not match:
        return None
    today = today or datetime.now(timezone.utc).date()
    month, day = int(match.group(1)), int(match.group(2))
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if candidate > today:
        try:
            candidate = date(candidate.year - 1, month, day)
        except ValueError:
            return None
    return candidate.isoformat()


def parse_event_list(html: str, base_url: str, category: str | None = None) -> list[EventItem]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, EventItem] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        if "info/" not in href or ".htm" not in href:
            continue
        full_url = urljoin(base_url.rstrip("/") + "/", href.lstrip("/"))
        if not is_allowed_source_url(full_url, base_url):
            continue
        event_id = event_id_from_url(full_url)
        if event_id is None:
            continue
        title = _clean_title(anchor.get_text(" ", strip=True))
        if not title:
            continue

        published_at: str | None = None
        container: Any = anchor
        for _ in range(4):
            if container is None or container.parent is None:
                break
            container = container.parent
            text = container.get_text(" ", strip=True)
            found_date = _resolve_date(text)
            if found_date:
                published_at = found_date
                break

        item_category = category or _category_from_url(full_url) or "综合"

        found.setdefault(
            event_id,
            EventItem(
                event_id=event_id,
                category=item_category,
                title=title,
                url=full_url,
                published_at=published_at,
            ),
        )
    return list(found.values())


def _category_from_url(url: str) -> str | None:
    url = url.lower()
    if "/1360/" in url or "/1361/" in url:
        return "教学"
    if "/1362/" in url or "/1363/" in url:
        return "科研"
    if "/1364/" in url or "/1365/" in url:
        return "管理"
    return None


def parse_event_detail(
    html: str, base_url: str, event_id: str, url: str, source_hash: str | None = None
) -> EventDetail:
    soup = BeautifulSoup(html, "html.parser")
    title = _clean_title(soup.title.get_text(" ", strip=True) if soup.title else "")

    published_at: str | None = None
    for pattern in (".article-meta", ".news_meta", ".source", ".arts_src"):
        meta = soup.select_one(pattern)
        if meta:
            match = PUBLISHED_DATE_RE.search(meta.get_text(" ", strip=True))
            if match:
                published_at = match.group(0)
                break

    content_text = ""
    node = soup.select_one("#vsb_content, .v_news_content, .wp_articlecontent, article")
    if node is not None:
        for unused in node.select("script,style,.arti-update,.arti-metas"):
            unused.decompose()
        content_text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()

    attachments: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        if not ATTACHMENT_EXT_RE.search(href):
            continue
        full_url = urljoin(base_url.rstrip("/") + "/", href.lstrip("/"))
        if not is_allowed_source_url(full_url, base_url):
            continue
        name = _clean_title(anchor.get_text(" ", strip=True)) or href.rsplit("/", 1)[-1]
        attachments.append(
            {
                "name": name,
                "url": full_url,
            }
        )

    return EventDetail(
        event_id=event_id,
        category=_category_from_url(url) or "综合",
        title=title,
        url=url,
        published_at=published_at,
        content_text=content_text,
        source_hash=source_hash,
        attachments=attachments,
    )
