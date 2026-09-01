from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import College, CollegeNoticeDetail, CollegeNoticeItem

DETAIL_URL_RE = re.compile(r"/(\d{4}/\d{2}\d{2}?/c\d+a\d+)/page\.htm")
PUBLISHED_DATE_RE = re.compile(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})日?")
TITLE_SUFFIX_RE = re.compile(r"\s*[|｜]\s*[^|｜]*$")
ATTACHMENT_EXT_RE = re.compile(r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|txt)$", re.IGNORECASE)
CONTENT_ID_RE = re.compile(r"^(vsb_content|v_news_content|article-content|wp_articlecontent|content)$")
CONTENT_CLASS_RE = re.compile(
    r"(vsb_content|v_news_content|article[-_]?content|wp[-_]?article|entry-content|detail-content|textbody)"
)


def notice_id_from_url(url: str) -> str | None:
    match = DETAIL_URL_RE.search(url)
    return match.group(1) if match else None


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"<[^>]+>", "", title).strip()
    title = TITLE_SUFFIX_RE.sub("", title).strip()
    return title


def _extract_date(html: str) -> str | None:
    matches = PUBLISHED_DATE_RE.findall(html)
    if not matches:
        return None
    return "{:04d}-{:02d}-{:02d}".format(*(int(part) for part in matches[-1]))


def parse_notice_list(html: str, college: College) -> list[CollegeNoticeItem]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, CollegeNoticeItem] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        if "page.htm" not in href:
            continue
        full_url = urljoin(college.base_url.rstrip("/") + "/", href.lstrip("/"))
        notice_id = notice_id_from_url(full_url)
        if notice_id is None:
            continue
        title = _clean_title(anchor.get_text(" ", strip=True))
        if not title:
            continue
        container: Any = anchor
        published_at: str | None = None
        for _ in range(4):
            if container is None or container.parent is None:
                break
            container = container.parent
            text = container.get_text(" ", strip=True)
            published_at = _extract_date(text)
            if published_at:
                break
        found.setdefault(
            notice_id,
            CollegeNoticeItem(
                notice_id=notice_id,
                college_key=college.key,
                title=title,
                url=full_url,
                published_at=published_at,
            ),
        )
    # 无发布日期的多为导航/栏目链接，剔除
    return [item for item in found.values() if item.published_at]


def parse_notice_detail(
    html: str, college: College, notice_id: str, url: str, source_hash: str | None = None
) -> CollegeNoticeDetail:
    soup = BeautifulSoup(html, "html.parser")
    title = _clean_title(soup.title.get_text(" ", strip=True) if soup.title else "")
    published_at = _extract_date(html)

    content_nodes = soup.select("#vsb_content, .v_news_content, .vsbcontent_main, article, .wp_articlecontent")
    content_text = ""
    if content_nodes:
        node = content_nodes[0]
        for unused in node.select("script,style,.wp_articleinfo,.news_title,.arti-title,.title"):
            unused.decompose()
        content_text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()

    attachments: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        if not ATTACHMENT_EXT_RE.search(href):
            continue
        name = _clean_title(anchor.get_text(" ", strip=True)) or href.rsplit("/", 1)[-1]
        attachments.append(
            {
                "name": name,
                "url": urljoin(college.base_url.rstrip("/") + "/", href.lstrip("/")),
            }
        )

    return CollegeNoticeDetail(
        notice_id=notice_id,
        college_key=college.key,
        title=title,
        url=url,
        published_at=published_at,
        content_text=content_text,
        source_hash=source_hash,
        attachments=attachments,
    )
