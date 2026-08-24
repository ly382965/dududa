from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .common import fetched_at

SHUTTLE_URL = "https://www.ustc.edu.cn/info/1029/25471.htm"
KNOWN_IMAGE_PATH = "/__local/8/AD/92/D4B66E1E6F1978E6D6F7CDEC4DA_183B220D_4D9B90.jpg"
VALID_FROM = "2026-08-01"
VALID_TO = "2026-08-29"

_ROUTES = [
    {
        "direction": "east_to_hightech",
        "stops": ["east", "west", "research", "hightech"],
        "trips": [
            {"east": "07:30", "west": "07:40", "research": None, "hightech": "08:20"},
            {"east": "12:30", "west": "12:40", "research": None, "hightech": "13:20"},
            {"east": "18:00", "west": "18:10", "research": None, "hightech": "18:50"},
            {"east": "20:00", "west": "20:10", "research": None, "hightech": "20:50"},
        ],
    },
    {
        "direction": "hightech_to_east",
        "stops": ["hightech", "research", "west", "east"],
        "trips": [
            {"hightech": "08:45", "research": "08:50", "west": None, "east": "09:35"},
            {"hightech": "13:30", "research": "13:35", "west": None, "east": "14:20"},
            {"hightech": "19:00", "research": "19:05", "west": None, "east": "19:50"},
            {"hightech": "21:00", "research": "21:05", "west": None, "east": "21:50"},
        ],
    },
]

_ALIASES = {
    "east": "east",
    "east campus": "east",
    "东区": "east",
    "west": "west",
    "west campus": "west",
    "西区": "west",
    "research": "research",
    "先研院": "research",
    "先进技术研究院": "research",
    "hightech": "hightech",
    "high-tech": "hightech",
    "高新": "hightech",
    "高新校区": "hightech",
}


class ShuttleClient:
    def __init__(self, url: str = SHUTTLE_URL, timeout: float = 20.0) -> None:
        self.url = url
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": "Dududa-Campus-MCP/0.1 (+read-only)"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def current_schedule(self) -> dict[str, Any]:
        page = await self._page()
        today = datetime.now(timezone.utc).date().isoformat()
        structured = (
            urlsplit(page["image_url"]).path == KNOWN_IMAGE_PATH
            and VALID_FROM <= today <= VALID_TO
        )
        return {
            "ok": True,
            **page,
            "structured": structured,
            "valid_from": VALID_FROM if structured else None,
            "valid_to": VALID_TO if structured else None,
            "routes": _ROUTES if structured else [],
            "notice": (
                "Stops marked with a bus icon are pass-through stops; the bus departs immediately on arrival."
                if structured
                else "The official image changed or its stated validity ended. Use the returned image until the timetable is re-structured."
            ),
            "fetched_at": fetched_at(),
        }

    async def search_trips(self, from_station: str, to_station: str, after: str = "") -> dict[str, Any]:
        source = self._station(from_station)
        target = self._station(to_station)
        if source == target:
            raise ValueError("from_station and to_station must differ")
        if after and (len(after) != 5 or after[2] != ":" or not after.replace(":", "").isdigit()):
            raise ValueError("after must use HH:MM")
        schedule = await self.current_schedule()
        if not schedule["structured"]:
            return {**schedule, "from_station": source, "to_station": target, "items": []}
        items: list[dict[str, Any]] = []
        for route in _ROUTES:
            stops = route["stops"]
            if source not in stops or target not in stops or stops.index(source) >= stops.index(target):
                continue
            for trip in route["trips"]:
                departure = trip[source]
                if after and departure is not None and departure < after:
                    continue
                items.append(
                    {
                        "direction": route["direction"],
                        "from": source,
                        "to": target,
                        "departure": departure,
                        "arrival": trip[target],
                        "stop_times": trip,
                        "time_notice": "null means the official image marks this as a pass-through stop without a published time.",
                    }
                )
        return {
            "ok": True,
            "from_station": source,
            "to_station": target,
            "items": items,
            "total": len(items),
            "structured": True,
            "valid_from": VALID_FROM,
            "valid_to": VALID_TO,
            "source_url": schedule["source_url"],
            "image_url": schedule["image_url"],
            "fetched_at": schedule["fetched_at"],
        }

    async def _page(self) -> dict[str, str]:
        try:
            response = await self._client.get(self.url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError("shuttle_notice_unavailable") from exc
        soup = BeautifulSoup(response.text, "html.parser")
        title_node = soup.select_one("td.title") or soup.select_one("title")
        image = soup.select_one(".v_news_content img")
        if image is None or not image.get("src"):
            raise RuntimeError("shuttle_timetable_image_missing")
        return {
            "title": title_node.get_text(" ", strip=True) if title_node else "USTC shuttle timetable",
            "source_url": self.url,
            "image_url": urljoin(self.url, str(image["src"])),
        }

    @staticmethod
    def _station(value: str) -> str:
        station = _ALIASES.get(value.strip().casefold()) or _ALIASES.get(value.strip())
        if station is None:
            raise ValueError("unknown station; use east, west, research or hightech")
        return station
