from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PlanRow:
    year: int
    college: str
    dept: str | None
    major: str
    code: str | None
    degree: str | None
    discontinued: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "college": self.college,
            "dept": self.dept,
            "major": self.major,
            "code": self.code,
            "degree": self.degree,
            "discontinued": self.discontinued,
        }


@dataclass
class PlanYear:
    year: int
    title: str
    discontinued_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "title": self.title,
            "discontinued_count": self.discontinued_count,
        }