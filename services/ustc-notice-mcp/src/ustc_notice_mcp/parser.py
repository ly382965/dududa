from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import NoticeDetail, NoticeItem

NOTICE_ID_RE = re.compile(r"/(?:notice/)?notice-info/(\d+)\.html")
PUBLISHED_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?")
TITLE_SUFFIX_RE = re.compile(r"\s*:\s*中国科学技术大学教务处\s*$")
ATTACHMENT_EXT_RE = re.compile(r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|txt)$", re.IGNORECASE)


def parse_notice_id(href: str) -> int | None:
    match = NOTICE_ID_RE.search(href)
    return int(match.group(1)) if match else None


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return TITLE_SUFFIX_RE.sub("", title).strip()


def parse_notice_list(html: str, base_url: str) -> list[NoticeItem]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[int, NoticeItem] = {}
    for li in soup.select("ul.article-list li"):
        anchor = li.select_one("span.post a[href]") or li.find("a", href=True)
        if not anchor:
            continue
        notice_id = parse_notice_id(anchor.get("href") or "")
        if notice_id is None:
            continue
        title = _clean_title(anchor.get_text(" ", strip=True))
        if not title:
            continue
        url = urljoin(base_url.rstrip("/") + "/", (anchor.get("href") or "").lstrip("/"))

        published_at: str | None = None
        category: str | None = None
        date_span = li.select_one("span.date")
        if date_span:
            match = PUBLISHED_DATE_RE.search(date_span.get_text(" ", strip=True))
            if match:
                published_at = match.group(0)
        cat_tags = li.select("a.cat-tag")
        if cat_tags:
            category = cat_tags[0].get_text(" ", strip=True).strip() or None

        found.setdefault(
            notice_id,
            NoticeItem(
                notice_id=notice_id,
                title=title,
                url=url,
                published_at=published_at,
                category=category,
            ),
        )
    return list(found.values())


def parse_notice_detail(html: str, base_url: str, source_hash: str | None = None) -> NoticeDetail | None:
    soup = BeautifulSoup(html, "html.parser")

    raw_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    title = _clean_title(raw_title)
    notice_id: int | None = None

    body = soup.body
    if body is not None:
        match = re.search(r"postid-(\d+)", " ".join(body.get("class", [])))
        if match:
            notice_id = int(match.group(1))
    if notice_id is None:
        article_tag = soup.find("article")
        if article_tag is not None and article_tag.get("id"):
            match = re.match(r"post-(\d+)", article_tag.get("id", ""))
            if match:
                notice_id = int(match.group(1))
    if notice_id is None:
        for tag in soup.select("a[href*='notice-info/']"):
            parsed = parse_notice_id(tag.get("href") or "")
            if parsed:
                notice_id = parsed
                break

    if notice_id is None:
        return None

    url = urljoin(base_url.rstrip("/") + "/", f"notice/notice-info/{notice_id}.html")

    published_at: str | None = None
    last_modified: str | None = None
    category: str | None = None
    for li in soup.select(".post-meta-side li"):
        title_attr = (li.get("title") or "").strip()
        text = li.get_text(" ", strip=True).strip()
        if title_attr == "发布时间":
            published_at = text or None
        elif title_attr == "上次修改时间":
            last_modified = text or None
        elif title_attr == "所属栏目":
            category = text or None

    content_text = ""
    content_html = ""
    main_article = soup.find("article")
    if main_article is not None:
        for unused in main_article.select("script,style,nav,.post-meta-side,.popular-article,.related-post"):
            unused.decompose()
        content_html = str(main_article)
        content_text = re.sub(r"\s+", " ", main_article.get_text(" ", strip=True)).strip()

    attachments: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        if not ATTACHMENT_EXT_RE.search(href):
            continue
        name = _clean_title(anchor.get_text(" ", strip=True)) or href.rsplit("/", 1)[-1]
        attachments.append(
            {
                "name": name,
                "url": urljoin(base_url.rstrip("/") + "/", href.lstrip("/")),
            }
        )

    return NoticeDetail(
        notice_id=notice_id,
        title=title,
        url=url,
        published_at=published_at,
        last_modified=last_modified,
        category=category,
        content_text=content_text,
        content_html=content_html,
        attachments=attachments,
        source_hash=source_hash,
    )