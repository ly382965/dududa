from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

CATALOG_BASE_URL = "https://catalog.ustc.edu.cn"


def fetched_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("cn") or value.get("en") or "")
    return str(value)


class CatalogClient:
    """Read-only client for the public catalog.ustc.edu.cn JSON APIs."""

    def __init__(
        self,
        base_url: str = CATALOG_BASE_URL,
        *,
        timeout: float = 30.0,
        cache_dir: Path | None = None,
        cache_ttl_seconds: float = 12 * 3600,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": "Dududa-Classroom-Plugin/0.1 (+read-only)"},
        )
        self._cache_dir = cache_dir
        self._cache_ttl = cache_ttl_seconds
        self._lock = asyncio.Lock()
        self._semester_id: int | None = None
        self._semester_name: str = ""

    async def close(self) -> None:
        await self._client.aclose()

    async def _json(self, path: str) -> Any:
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise RuntimeError("catalog_network_unavailable") from exc
        try:
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"catalog_upstream_error_{response.status_code}") from exc

    async def current_semester(self) -> tuple[int, str]:
        async with self._lock:
            if self._semester_id is not None:
                return self._semester_id, self._semester_name
            semesters = await self._json("/api/teach/semester/list")
            if not isinstance(semesters, list) or not semesters:
                raise RuntimeError("catalog_semester_list_unavailable")
            selected = next(
                (item for item in semesters if item.get("isLast")),
                semesters[-1],
            )
            self._semester_id = int(selected["id"])
            self._semester_name = text(selected.get("nameZh"))
            return self._semester_id, self._semester_name

    async def lessons(self) -> list[dict[str, Any]]:
        semester_id, _ = await self.current_semester()
        cached = self._read_cache(f"lessons_{semester_id}.json")
        if cached is not None:
            return cached
        values = await self._json(f"/api/teach/lesson/list-for-teach/{semester_id}")
        if not isinstance(values, list):
            raise RuntimeError("catalog_lesson_shape_changed")
        self._write_cache(f"lessons_{semester_id}.json", values)
        return values

    async def exams(self) -> list[dict[str, Any]]:
        semester_id, _ = await self.current_semester()
        cached = self._read_cache(f"exams_{semester_id}.json")
        if cached is not None:
            return cached
        normal, general = await asyncio.gather(
            self._json(f"/api/teach/exam/list/{semester_id}"),
            self._json(f"/api/teach/general-exam/list/{semester_id}"),
        )
        values = [
            *(normal if isinstance(normal, list) else []),
            *(general if isinstance(general, list) else []),
        ]
        self._write_cache(f"exams_{semester_id}.json", values)
        return values

    def _cache_path(self, name: str) -> Path | None:
        if self._cache_dir is None:
            return None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        return self._cache_dir / name

    def _read_cache(self, name: str) -> list[dict[str, Any]] | None:
        path = self._cache_path(name)
        if path is None or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        stored_at = payload.get("stored_at")
        if not isinstance(stored_at, (int, float)):
            return None
        if time.time() - stored_at > self._cache_ttl:
            return None
        values = payload.get("values")
        return values if isinstance(values, list) else None

    def _write_cache(self, name: str, values: list[dict[str, Any]]) -> None:
        path = self._cache_path(name)
        if path is None:
            return
        try:
            path.write_text(
                json.dumps(
                    {"stored_at": time.time(), "values": values},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass


__all__ = ["CatalogClient", "fetched_at", "text"]
