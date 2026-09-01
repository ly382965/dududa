from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TermListing:
    term_id: int
    name: str
    url: str
    published_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "term_id": self.term_id,
            "name": self.name,
            "url": self.url,
            "published_at": self.published_at,
        }


@dataclass
class CalendarDay:
    date: str
    year: int
    month: int
    day_of_month: int
    weekday_iso: int
    week_label: str | None
    event_name: str | None
    is_off_day: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "year": self.year,
            "month": self.month,
            "day_of_month": self.day_of_month,
            "weekday_iso": self.weekday_iso,
            "week_label": self.week_label,
            "event_name": self.event_name,
            "is_off_day": self.is_off_day,
        }


@dataclass
class TermCalendar:
    term_id: int
    name: str
    url: str
    base_year: int
    published_at: str | None = None
    notes: list[str] = field(default_factory=list)
    days: list[CalendarDay] = field(default_factory=list)
    source_hash: str | None = None

    def to_dict(self, include_days: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "term_id": self.term_id,
            "name": self.name,
            "url": self.url,
            "base_year": self.base_year,
            "published_at": self.published_at,
            "notes": self.notes,
        }
        if include_days:
            data["days"] = [day.to_dict() for day in self.days]
        data["event_count"] = sum(1 for day in self.days if day.event_name)
        data["off_day_count"] = sum(1 for day in self.days if day.is_off_day)
        return data