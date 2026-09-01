from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from .models import HoursRow

# 8 列网格: 0 校区, 1 楼层, 2 业务内容, 3-4 周一至周五, 5-6 周六至周日, 7 电话
GRID_COLS = 8
EMPTY_MARKERS = {"——", "-", "--", "—", ""}


def parse_opening_hours(html: str, base_url: str) -> list[HoursRow]:
    soup = BeautifulSoup(html, "html.parser")
    table = _find_hours_table(soup)
    if table is None:
        return []

    rows: list[HoursRow] = []
    current_campus: str | None = None
    seen_keys: set[tuple[str, str, str]] = set()

    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        if cells[0].name == "th":
            header_text = re.sub(r"\s+", "", table.get_text(" ", strip=True))
            if "周一" in header_text and "业务地点" in header_text:
                continue
        grid = _expand_grid(cells)
        if not grid:
            continue

        campus = _col(grid, 0)
        if _is_campus_text(campus):
            current_campus = re.sub(r"\s+", "", campus)
        elif current_campus is None:
            continue

        location = _col(grid, 1)
        service = _col(grid, 2)
        if not location and not service:
            continue
        if (
            "业务地点" in service
            or "业务内容" in service
            or "联系电话" in _col(grid, 7)
            or (service and "业务" in service and "周一" in _col(grid, 3))
        ):
            continue

        weekday = _merge_cols(_col(grid, 3), _col(grid, 4))
        weekend = _merge_cols(_col(grid, 5), _col(grid, 6))
        phone = _col(grid, 7)

        key = (current_campus, location, service)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(
            HoursRow(
                campus=current_campus,
                location=location,
                service=service,
                weekday=weekday or None,
                weekend=weekend or None,
                phone=phone or None,
            )
        )
    return rows


def _find_hours_table(soup: BeautifulSoup) -> Any | None:
    best: Any = None
    best_score = 0
    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True)
        score = 0
        if "业务地点" in text:
            score += 2
        if "周一" in text:
            score += 1
        if "联系电话" in text:
            score += 1
        if score > best_score:
            best_score = score
            best = table
    return best if best_score >= 2 else None


def _expand_grid(cells: list[Any]) -> list[str]:
    grid: list[str] = [""] * GRID_COLS
    col = 0
    pending: dict[int, tuple[int, str]] = {}
    for cell in cells:
        while col < GRID_COLS and col in pending:
            remaining, text = pending[col]
            grid[col] = text
            if remaining <= 1:
                del pending[col]
            else:
                pending[col] = (remaining - 1, text)
            col += 1
        if col >= GRID_COLS:
            break
        rowspan = int(cell.get("rowspan") or 1)
        colspan = int(cell.get("colspan") or 1)
        text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
        for _ in range(min(colspan, GRID_COLS - col)):
            grid[col] = text
            col += 1
        if rowspan > 1:
            for j in range(max(1, colspan)):
                target = col - (colspan or 1) + (0 if colspan == 0 else j)
                if 0 <= target < GRID_COLS:
                    pending[target] = (rowspan - 1, text)
    for index in sorted(pending):
        if index < GRID_COLS and not grid[index]:
            grid[index] = pending[index][1]
    return grid


def _col(grid: list[str], index: int) -> str:
    return grid[index] if index < len(grid) else ""


def _merge_cols(a: str, b: str) -> str | None:
    candidate = a or b
    if not candidate:
        return None
    if candidate in EMPTY_MARKERS:
        return None
    return candidate


def _is_campus_text(text: str) -> bool:
    text = re.sub(r"\s+", "", text)
    return bool(
        ("东" in text and "区" in text)
        or ("西" in text and "区" in text)
        or "高新" in text
        or "南区" in text
        or "北区" in text
    )