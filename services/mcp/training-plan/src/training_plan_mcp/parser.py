from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from .models import PlanRow, PlanYear

TABLE_RE = re.compile(r"table2|plan[-_]?table")
YEAR_RE = re.compile(r"(\d{4})")
CODE_RE = re.compile(r"^\s*(\d{5,7}[A-Z]*)\s*(?:\((\S+?)\))?\s*$")
COLLEGE_CODE_RE = re.compile(r"^(.*?)\s*\((\d+)\)\s*$")
DISCONTINUED_FOOTNOTE_RE = re.compile(r"已停止招生本科专业[：:]\s*(\d+)")


def parse_overview(html: str, base_url: str, source_hash: str | None = None) -> tuple[list[PlanYear], list[PlanRow]]:
    soup = BeautifulSoup(html, "html.parser")
    years: list[PlanYear] = []
    rows: list[PlanRow] = []

    for table in soup.find_all("table"):
        if not _looks_like_overview_table(table):
            continue
        caption = table.find("caption")
        title = re.sub(r"\s+", " ", caption.get_text(" ", strip=True)) if caption else ""
        year_match = YEAR_RE.search(title)
        if not year_match:
            continue
        year = int(year_match.group(1))
        years.append(PlanYear(year=year, title=title or f"{year}级本科专业设置一览"))

        tfoot = table.find("tfoot")
        if tfoot is not None:
            match = DISCONTINUED_FOOTNOTE_RE.search(tfoot.get_text(" ", strip=True))
            if match:
                years[-1].discontinued_count = int(match.group(1))

        tbody = table.find("tbody")
        if tbody is None:
            continue
        rows.extend(_rows_from_grid(*_expand_grid(tbody), year))

    return years, rows


def _looks_like_overview_table(table: Any) -> bool:
    if table.get("class") and TABLE_RE.search(" ".join(table.get("class", []))):
        return True
    captions = table.select("caption")
    if captions and "专业设置一览" in captions[0].get_text(" ", strip=True):
        return True
    heads = {re.sub(r"\s+|（|）|/", "", th.get_text(" ", strip=True)) for th in table.find_all("th")}
    return bool(("学院" in heads) and ("系" in heads) and ("专业" in heads))


def _expand_grid(tbody: Any) -> tuple[list[list[str]], list[list[int]]]:
    """展开 rowspan，固定 4 列：学院/系/专业/专业代码。
    返回 (grid, spans)，spans[i][j] 为该单元格 rowspan（继承/空为 0，普通为 1，跨行为 >1）。"""
    grid: list[list[str]] = []
    spans: list[list[int]] = []
    active: dict[int, tuple[int, str]] = {}
    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td", recursive=False) or tr.find_all("td")
        if not cells:
            continue
        row: list[str] = []
        row_spans: list[int] = []
        col = 0
        for cell in cells:
            while col < 4 and col in active:
                remaining, text = active[col]
                row.append(text)
                row_spans.append(0)
                if remaining <= 1:
                    del active[col]
                else:
                    active[col] = (remaining - 1, text)
                col += 1
            if col >= 4:
                break
            text = "\n".join(line for line in cell.get_text("\n", strip=True).split("\n") if line.strip())
            row.append(text)
            row_spans.append(int(cell.get("rowspan") or 1))
            rowspan = int(cell.get("rowspan") or 1)
            if rowspan > 1:
                active[col] = (rowspan - 1, text)
            col += 1
        # 行尾继续消费残留 rowspan（如专业单元格 rowspan 的最后一行无实际 cell）
        while col < 4 and col in active:
            remaining, text = active[col]
            row.append(text)
            row_spans.append(0)
            if remaining <= 1:
                del active[col]
            else:
                active[col] = (remaining - 1, text)
            col += 1
        while col < 4:
            row.append("")
            row_spans.append(0)
            col += 1
        grid.append(row)
        spans.append(row_spans)
    return grid, spans


def _rows_from_grid(grid: list[list[str]], spans: list[list[int]], year: int) -> list[PlanRow]:
    result: list[PlanRow] = []
    current_college: str | None = None
    major_block: str | None = None
    major_queue: list[str] = []
    major_is_span: bool = False
    code_queue: list[str] = []

    for index, row in enumerate(grid):
        raw_college, raw_dept, raw_majors, raw_codes = row[0], row[1], row[2], row[3]
        if raw_college:
            current_college = _strip_code(raw_college) or current_college
        if not current_college:
            continue
        # tfoot 汇总行（如 “45个本科专业”）不是专业，跳过
        if _is_summary_row(raw_majors, raw_codes):
            continue
        dept = _strip_code(raw_dept) if raw_dept else None

        row_span = spans[index][2]
        if raw_majors and (major_block is None or raw_majors != major_block):
            major_block = raw_majors
            major_queue = _split_block(raw_majors)
            major_is_span = row_span > 1
            code_queue = _split_block(raw_codes) if raw_codes else []

        if major_is_span:
            if not major_queue:
                continue
            major = major_queue.pop(0)
            code_value = code_queue.pop(0) if code_queue else None
        else:
            if not major_queue:
                continue
            block_majors = major_queue
            block_codes = code_queue
            major_queue = []
            code_queue = []
            for idx, major in enumerate(block_majors):
                code_value = block_codes[idx] if idx < len(block_codes) else None
                code_match = CODE_RE.match(code_value) if code_value else None
                result.append(
                    PlanRow(
                        year=year,
                        college=current_college,
                        dept=dept,
                        major=major,
                        code=code_match.group(1) if code_match else None,
                        degree=code_match.group(2) if code_match and code_match.group(2) else None,
                        discontinued=False,
                    )
                )
            continue

        code_match = CODE_RE.match(code_value) if code_value else None
        result.append(
            PlanRow(
                year=year,
                college=current_college,
                dept=dept,
                major=major,
                code=code_match.group(1) if code_match else None,
                degree=code_match.group(2) if code_match and code_match.group(2) else None,
                discontinued=False,
            )
        )
    return result


def _split_block(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n") if p.strip()]


def _strip_code(text: str) -> str | None:
    text = re.sub(r"\s+", "", text or "").strip()
    if not text:
        return None
    match = COLLEGE_CODE_RE.match(text)
    return match.group(1).strip() if match else text


def _is_summary_row(raw_majors: str, raw_codes: str) -> bool:
    return bool(re.fullmatch(r"\d+个本科专业(?:\(.*\))?", raw_majors.strip()))
