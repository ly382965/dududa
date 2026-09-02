from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from .models import HoursRow

# 8 列网格: 0 校区, 1 楼层, 2 业务内容, 3-4 周一至周五, 5-6 周六至周日, 7 电话
GRID_COLS = 8
EMPTY_MARKERS = {"——", "-", "--", "—", ""}


def parse_opening_hours(html: str, base_url: str) -> list[HoursRow]:
    del base_url
    soup = BeautifulSoup(html, "html.parser")
    table = _find_hours_table(soup)
    if table is None:
        return []

    rows: list[HoursRow] = []
    current_campus: str | None = None
    seen_keys: set[tuple[str, str, str]] = set()
    active_rowspans: dict[int, tuple[int, str]] = {}

    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        if cells[0].name == "th":
            header_text = re.sub(r"\s+", "", table.get_text(" ", strip=True))
            if "周一" in header_text and "业务地点" in header_text:
                continue
        grid = _expand_grid(cells, active_rowspans)
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


def _expand_grid(
    cells: list[Any], active: dict[int, tuple[int, str]]
) -> list[str]:
    grid: list[str] = [""] * GRID_COLS
    next_active: dict[int, tuple[int, str]] = {}
    for column, (remaining, text) in active.items():
        if 0 <= column < GRID_COLS:
            grid[column] = text
            if remaining > 1:
                next_active[column] = (remaining - 1, text)
    active.clear()
    active.update(next_active)

    col = 0
    for cell in cells:
        while col < GRID_COLS and grid[col]:
            col += 1
        if col >= GRID_COLS:
            break
        rowspan = int(cell.get("rowspan") or 1)
        colspan = int(cell.get("colspan") or 1)
        text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
        populated: list[int] = []
        for _ in range(colspan):
            while col < GRID_COLS and grid[col]:
                col += 1
            if col >= GRID_COLS:
                break
            grid[col] = text
            populated.append(col)
            col += 1
        if rowspan > 1:
            for target in populated:
                active[target] = (rowspan - 1, text)
    return grid


def _col(grid: list[str], index: int) -> str:
    return grid[index] if index < len(grid) else ""


def _merge_cols(a: str, b: str) -> str | None:
    values = [value for value in (a, b) if value not in EMPTY_MARKERS]
    if not values:
        return None
    if len(values) == 1 or values[0] == values[1]:
        return values[0]
    return f"{values[0]}-{values[1]}"


def _is_campus_text(text: str) -> bool:
    text = re.sub(r"\s+", "", text)
    return bool(
        ("东" in text and "区" in text)
        or ("西" in text and "区" in text)
        or "高新" in text
        or "南区" in text
        or "北区" in text
    )
