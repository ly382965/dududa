from __future__ import annotations

import re
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .common import fetched_at

CALENDAR_URL = "https://www.teach.ustc.edu.cn/calendar/20135.html"
_MONTHS = {
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


class TeachingCalendarClient:
    def __init__(self, url: str = CALENDAR_URL, timeout: float = 20.0) -> None:
        self.url = url
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": "Dududa-Campus-MCP/0.1 (+read-only)"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, start_date: str = "", end_date: str = "") -> dict[str, Any]:
        start = self._parse_filter(start_date, "start_date")
        end = self._parse_filter(end_date, "end_date")
        if start and end and start > end:
            raise ValueError("start_date must not be after end_date")
        try:
            response = await self._client.get(self.url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError("teaching_calendar_unavailable") from exc
        parsed = self.parse(response.text)
        if start or end:
            parsed["days"] = [
                item
                for item in parsed["days"]
                if (not start or date.fromisoformat(item["date"]) >= start)
                and (not end or date.fromisoformat(item["date"]) <= end)
            ]
            parsed["events"] = [item for item in parsed["days"] if item["event"]]
        return {
            "ok": True,
            **parsed,
            "source_url": self.url,
            "fetched_at": fetched_at(),
            "source_note": "Parsed from the current article table; the stale 2019 teachCalendarData widget is ignored.",
        }

    @staticmethod
    def _parse_filter(value: str, label: str) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{label} must use YYYY-MM-DD") from exc

    @staticmethod
    def parse(html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one("article table.calendar") or soup.select_one("table.calendar")
        if table is None:
            raise RuntimeError("teaching_calendar_table_missing")
        title_node = soup.select_one(".single-title h1") or soup.select_one("h1")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        year_match = re.search(r"(20\d{2})", title)
        if year_match is None:
            raise RuntimeError("teaching_calendar_year_missing")
        year = int(year_match.group(1))
        current_month: int | None = None
        previous_month: int | None = None
        week_label = ""
        days: list[dict[str, Any]] = []
        for row in table.select("tbody tr"):
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells:
                continue
            texts = [cell.get_text(" ", strip=True) for cell in cells]
            first_month = _MONTHS.get(texts[0])
            index = 0
            if first_month is not None:
                if previous_month is not None and first_month < previous_month:
                    year += 1
                current_month = first_month
                previous_month = first_month
                index = 1
            if current_month is None or index >= len(texts):
                continue
            week_label = texts[index] or week_label
            index += 1
            remaining = texts[index:]
            for position in range(0, len(remaining), 2):
                day_text = remaining[position]
                event = remaining[position + 1] if position + 1 < len(remaining) else ""
                if not day_text.isdigit():
                    continue
                try:
                    current = date(year, current_month, int(day_text))
                except ValueError:
                    continue
                days.append(
                    {
                        "date": current.isoformat(),
                        "week": week_label,
                        "event": event,
                    }
                )
        modified = soup.select_one(".meta-last-modified")
        notes: list[str] = []
        for heading in soup.find_all(["h2", "h3"]):
            if "说明" not in heading.get_text(" ", strip=True):
                continue
            next_list = heading.find_next_sibling(["ol", "ul"])
            if next_list:
                notes = [item.get_text(" ", strip=True) for item in next_list.find_all("li", recursive=False)]
            break
        return {
            "semester": title,
            "last_modified": modified.get_text(" ", strip=True) if modified else None,
            "days": days,
            "events": [item for item in days if item["event"]],
            "notes": notes,
        }
