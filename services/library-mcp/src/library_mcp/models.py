from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HoursRow:
    campus: str
    location: str
    service: str
    weekday: str | None = None
    weekend: str | None = None
    phone: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "campus": self.campus,
            "location": self.location,
            "service": self.service,
            "weekday": self.weekday,
            "weekend": self.weekend,
            "phone": self.phone,
        }