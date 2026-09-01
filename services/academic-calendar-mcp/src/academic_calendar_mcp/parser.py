from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import CalendarDay, TermCalendar, TermListing


CHINESE_MONTHS: dict[str, int] = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}

TERM_DETAIL_ID_RE = re.compile(r"/calendar/(\d+)\.html")
TERM_NAME_YEAR_RE = re.compile(r"(\d{4})\s*年")
WEEK_LABEL_RE = re.compile(r"[春秋夏]\d+")
PUBLISHED_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
HOLIDAY_MARKER_RE = re.compile(r"\s*\*?休\s*")

HEADER_ROW_MARKER = "教学周"


def parse_chinese_month(text: str) -> int | None:
    value = text.strip()
    if not value or value in {" ", "\u00a0"}:
        return None
    return CHINESE_MONTHS.get(value)


def parse_listing(html: str, base_url: str) -> list[TermListing]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[int, TermListing] = {}
    for anchor in soup.select('a[href*="/calendar/"]'):
        href = anchor.get("href") or ""
        match = TERM_DETAIL_ID_RE.search(href)
        if not match:
            continue
        term_id = int(match.group(1))
        name = anchor.get_text(" ", strip=True)
        if not name:
            continue
        url = urljoin(base_url.rstrip("/") + "/", href.lstrip("/"))
        published_at: str | None = None
        container: Any = anchor
        for _ in range(3):
            if container is None or container.parent is None:
                break
            container = container.parent
            text = container.get_text(" ", strip=True)
            date_match = PUBLISHED_DATE_RE.search(text)
            if date_match:
                published_at = date_match.group(0)
                break
        found.setdefault(
            term_id,
            TermListing(term_id=term_id, name=name, url=url, published_at=published_at),
        )
    return list(found.values())


def parse_term_detail(html: str, base_url: str, source_hash: str | None = None) -> TermCalendar:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    name = re.split(r"\s*[:：]\s*", title)[0].strip() if title else ""
    name = name or "教学日历"

    year_match = TERM_NAME_YEAR_RE.search(name)
    base_year = int(year_match.group(1)) if year_match else date.today().year

    canonical = soup.find("link", rel="canonical")
    canonical_href = canonical.get("href") or "" if canonical else ""
    id_match = TERM_DETAIL_ID_RE.search(canonical_href)
    term_id = int(id_match.group(1)) if id_match else 0

    article = soup.find("article") or soup.body or soup
    notes: list[str] = []
    for li in article.find_all("li"):
        text = li.get_text(" ", strip=True)
        if text:
            notes.append(text)

    calendar_table = None
    for table in soup.find_all("table"):
        if any((th.get_text(" ", strip=True) == HEADER_ROW_MARKER for th in table.find_all("th", recursive=False))):
            calendar_table = table
            break
        for th in table.find_all("th"):
            if HEADER_ROW_MARKER in th.get_text(" ", strip=True):
                calendar_table = table
                break
        if calendar_table:
            break

    days: list[CalendarDay] = []
    if calendar_table is not None:
        current_month: int | None = None
        previous_day: int | None = None
        for tr in calendar_table.find_all("tr"):
            cells = tr.find_all("td", recursive=False)
            if not cells:
                continue
            if tr.find_all("th", recursive=False):
                continue
            if any(cell.has_attr("colspan") for cell in cells):
                continue
            if cells[0].has_attr("rowspan"):
                month = parse_chinese_month(cells[0].get_text(" ", strip=True))
                if month is not None and current_month is None:
                    current_month = month
                cells = cells[1:]
            if not cells:
                continue
            week_match = WEEK_LABEL_RE.search(cells[0].get_text(" ", strip=True))
            week_label = week_match.group(0) if week_match else None
            pairs = _pair_day_cells(cells[1:])
            for day_text, event_cell in pairs:
                if not day_text.isdigit():
                    continue
                day_number = int(day_text)
                if current_month is not None and previous_day is not None and day_number < previous_day:
                    current_month += 1
                    if current_month > 12:
                        current_month = 1
                previous_day = day_number
                if current_month is None:
                    continue
                year = base_year if current_month >= 3 else base_year + 1
                try:
                    as_date = date(year, current_month, day_number)
                except ValueError:
                    continue
                event_name, is_off_day = _extract_event(event_cell)
                if not event_name and not is_off_day:
                    continue
                days.append(
                    CalendarDay(
                        date=as_date.isoformat(),
                        year=as_date.year,
                        month=as_date.month,
                        day_of_month=as_date.day,
                        weekday_iso=as_date.isoweekday(),
                        week_label=week_label,
                        event_name=event_name,
                        is_off_day=is_off_day,
                    )
                )

    days.sort(key=lambda item: item.date)
    url = urljoin(base_url.rstrip("/") + "/", f"calendar/{term_id}.html")
    return TermCalendar(
        term_id=term_id,
        name=name,
        url=url,
        base_year=base_year,
        published_at=None,
        notes=notes,
        days=days,
        source_hash=source_hash,
    )


def _pair_day_cells(cells: list[Any]) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    for index in range(0, len(cells) - 1, 2):
        pairs.append((cells[index].get_text(" ", strip=True), cells[index + 1]))
    return pairs


def _extract_event(cell: Any) -> tuple[str | None, bool]:
    is_off_day = bool(cell.find("i"))
    raw = " ".join(cell.stripped_strings)
    if not raw:
        return (None, is_off_day)
    cleaned = HOLIDAY_MARKER_RE.sub("", raw).strip()
    if not cleaned:
        return (None, is_off_day)
    return (cleaned, is_off_day)