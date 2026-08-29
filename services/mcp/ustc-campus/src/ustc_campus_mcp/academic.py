from __future__ import annotations

import asyncio
import copy
import re
from datetime import date, datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .common import contains, fetched_at, page, text

CATALOG_BASE_URL = "https://catalog.ustc.edu.cn"


class AcademicClient:
    def __init__(self, base_url: str = CATALOG_BASE_URL, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": "Dududa-Campus-MCP/0.1 (+read-only)"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _json(self, path: str) -> Any:
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise RuntimeError("catalog_network_unavailable") from exc
        if response.status_code == 401:
            raise RuntimeError("catalog_requires_campus_network_or_direct_connection")
        try:
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"catalog_upstream_error_{response.status_code}") from exc

    async def list_semesters(self, include_future: bool = True, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        values = await self._json("/api/teach/semester/list")
        if not isinstance(values, list):
            raise RuntimeError("catalog_semester_shape_changed")  # noqa: TRY004 - upstream failure
        today = datetime.now(timezone.utc).date().isoformat()
        items = [
            {
                "id": item.get("id"),
                "code": item.get("code"),
                "name": item.get("nameZh"),
                "start": item.get("start"),
                "end": item.get("end"),
                "is_last": bool(item.get("isLast")),
            }
            for item in values
            if isinstance(item, dict) and (include_future or str(item.get("start", "")) <= today)
        ]
        items.reverse()
        return self._result(items[:limit], len(items), "/api/teach/semester/list")

    async def resolve_semester_id(self, selector: str = "") -> int:
        result = await self.list_semesters(include_future=True, limit=100)
        selected = self.select_semester(
            result["items"],
            selector,
            today=datetime.now(timezone.utc).date(),
        )
        semester_id = selected.get("id")
        if not isinstance(semester_id, int) or semester_id <= 0:
            raise RuntimeError("catalog_semester_shape_changed")
        return semester_id

    @staticmethod
    def select_semester(
        items: list[dict[str, Any]],
        selector: str,
        *,
        today: date,
    ) -> dict[str, Any]:
        valid = [
            item
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("id"), int)
            and isinstance(item.get("start"), str)
            and isinstance(item.get("end"), str)
        ]
        if not valid:
            raise RuntimeError("catalog_semester_shape_changed")
        compact = "".join(str(selector or "").split()).casefold()

        code_match = re.search(r"(?<!\d)(20\d{3})(?!\d)", compact)
        if code_match is not None:
            match = next(
                (item for item in valid if str(item.get("code")) == code_match.group(1)),
                None,
            )
            if match is not None:
                return match

        term_match = re.search(r"(20\d{2})年?(春季?|夏季?|秋季?)", compact)
        if term_match is not None:
            year, season = term_match.groups()
            season = season[0]
            match = next(
                (
                    item
                    for item in valid
                    if year in str(item.get("name") or "")
                    and season in str(item.get("name") or "")
                ),
                None,
            )
            if match is None:
                raise ValueError("semester_not_found")
            return match

        dated = [
            (
                date.fromisoformat(str(item["start"])),
                date.fromisoformat(str(item["end"])),
                item,
            )
            for item in valid
        ]
        current = [item for start, end, item in dated if start <= today <= end]
        if current:
            return max(current, key=lambda item: str(item["start"]))
        upcoming = [(start, item) for start, _, item in dated if start > today]
        if upcoming:
            return min(upcoming, key=lambda value: value[0])[1]
        return max(dated, key=lambda value: value[1])[2]

    async def search_programs(
        self,
        query: str = "",
        department_code: str = "",
        major_code: str = "",
        grade: str = "",
        train_type: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        tree = await self._json("/api/teach/program/tree")
        if not isinstance(tree, dict):
            raise RuntimeError("catalog_program_tree_shape_changed")  # noqa: TRY004 - upstream failure
        items: list[dict[str, Any]] = []
        for department in tree.values():
            if not isinstance(department, dict):
                continue
            majors = department.get("majors", {})
            if not isinstance(majors, dict):
                continue
            for major in majors.values():
                if not isinstance(major, dict):
                    continue
                programs = major.get("programs", [])
                if not isinstance(programs, list):
                    continue
                for program in programs:
                    if not isinstance(program, dict):
                        continue
                    item = {
                        "program_id": program.get("id"),
                        "name": program.get("nameZh"),
                        "grade": program.get("grade"),
                        "train_type": program.get("trainType"),
                        "department": {
                            "code": department.get("code"),
                            "name": department.get("nameZh"),
                        },
                        "major": {"code": major.get("code"), "name": major.get("nameZh")},
                    }
                    searchable = " ".join(
                        str(value or "")
                        for value in (
                            item["name"],
                            item["grade"],
                            item["train_type"],
                            item["department"]["name"],
                            item["major"]["name"],
                            item["major"]["code"],
                        )
                    )
                    if query and query.casefold() not in searchable.casefold():
                        continue
                    if department_code and department_code != item["department"]["code"]:
                        continue
                    if major_code and major_code != item["major"]["code"]:
                        continue
                    if grade and grade != item["grade"]:
                        continue
                    if train_type and train_type != item["train_type"]:
                        continue
                    items.append(item)
        items.sort(key=lambda item: (str(item["grade"]), str(item["name"])), reverse=True)
        selected, actual_offset, actual_limit = page(items, offset, limit)
        return self._result(
            selected,
            len(items),
            "/api/teach/program/tree",
            offset=actual_offset,
            limit=actual_limit,
        )

    async def get_program(
        self,
        program_id: int,
        term: str = "",
        expand_shared_modules: bool = False,
        include_introduction: bool = False,
    ) -> dict[str, Any]:
        if program_id <= 0:
            raise ValueError("program_id must be positive")
        value = await self._json(f"/api/teach/program/info/{program_id}")
        if not isinstance(value, dict):
            raise RuntimeError("catalog_program_shape_changed")  # noqa: TRY004 - upstream failure
        document = copy.deepcopy(value)
        shared_ids: set[int] = set()

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                if not include_introduction:
                    node.pop("introduction", None)
                self_value = node.get("self")
                if isinstance(self_value, dict) and isinstance(self_value.get("public"), int):
                    shared_ids.add(self_value["public"])
                for child in node.values():
                    visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)

        visit(document)
        expanded: dict[str, Any] = {}
        if expand_shared_modules and shared_ids:
            details = await asyncio.gather(
                *(self._json(f"/api/teach/course-module/info/{module_id}") for module_id in sorted(shared_ids))
            )
            for module_id, detail in zip(sorted(shared_ids), details, strict=True):
                if not include_introduction:
                    visit(detail)
                expanded[str(module_id)] = detail
        modules = self._modules(document.get("moduleTree", []), term, include_introduction)
        shared_modules = [
            module
            for detail in expanded.values()
            for module in self._modules([detail], term, include_introduction, shared=True)
        ]
        program = {
            "train_type": document.get("trainType"),
            "grade": document.get("grade"),
            "education": text(document.get("education")),
            "student_type": text(document.get("studentType")),
            "department": self._named(document.get("department")),
            "major": self._named(document.get("major")),
            "major_direction": self._named(document.get("majorDirection")),
            "required_credits": document.get("requiredCredits"),
            "award_degree": bool(document.get("awardDegree")),
            "begin_semester": document.get("beginSemester"),
            "modules": modules,
        }
        return {
            "ok": True,
            "program_id": program_id,
            "requested_term": term or None,
            "program": program,
            "shared_modules": shared_modules,
            "source_url": f"{self.base_url}/plan",
            "api_source": f"{self.base_url}/api/teach/program/info/{program_id}",
            "fetched_at": fetched_at(),
        }

    @classmethod
    def _modules(
        cls,
        roots: Any,
        term: str,
        include_introduction: bool,
        *,
        shared: bool = False,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def visit(node: Any, level: int) -> None:
            if not isinstance(node, dict):
                return
            current = node.get("self") if isinstance(node.get("self"), dict) else node
            courses: list[dict[str, Any]] = []
            for raw in current.get("courses", []) if isinstance(current.get("courses"), list) else []:
                if not isinstance(raw, dict):
                    continue
                terms = [str(item) for item in raw.get("terms", []) if item is not None]
                if term and term not in terms:
                    continue
                course = raw.get("course") if isinstance(raw.get("course"), dict) else {}
                introduction = course.get("introduction")
                courses.append(
                    {
                        "course_id": course.get("id"),
                        "code": course.get("code"),
                        "name": course.get("nameZh"),
                        "name_en": course.get("nameEn"),
                        "credits": course.get("credits"),
                        "compulsory": bool(raw.get("compulsory")),
                        "terms": terms,
                        "exam_mode": raw.get("examMode"),
                        "department": cls._named(raw.get("department")),
                        "introduction": (
                            BeautifulSoup(str(introduction or ""), "html.parser").get_text(" ", strip=True)
                            if include_introduction
                            else None
                        ),
                    }
                )
            result.append(
                {
                    "module_id": current.get("id"),
                    "parent_id": current.get("parent"),
                    "level": level,
                    "name": current.get("type"),
                    "name_en": current.get("typeEn"),
                    "remark": current.get("remark"),
                    "required_credits": current.get("requiredCredits"),
                    "required_course_count": current.get("requiredCourseNum"),
                    "shared_module_id": current.get("public"),
                    "expanded_shared": shared,
                    "courses": courses,
                }
            )
            children = node.get("children", [])
            if isinstance(children, list):
                for child in children:
                    visit(child, level + 1)

        if isinstance(roots, list):
            for root in roots:
                visit(root, 0)
        return result

    @staticmethod
    def _named(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            "id": value.get("id"),
            "code": value.get("code"),
            "name": value.get("nameZh") or value.get("cn") or value.get("name"),
        }

    async def search_lessons(
        self,
        semester_id: int,
        query: str = "",
        department_code: str = "",
        teacher: str = "",
        campus: str = "",
        location: str = "",
        education: str = "",
        class_type: str = "",
        course_classify: str = "",
        time_span: str = "",
        offset: int = 0,
        limit: int = 25,
    ) -> dict[str, Any]:
        values = await self._json(f"/api/teach/lesson/list-for-teach/{semester_id}")
        if not isinstance(values, list):
            raise RuntimeError("catalog_lesson_shape_changed")  # noqa: TRY004 - upstream failure
        items: list[dict[str, Any]] = []
        for raw in values:
            if not isinstance(raw, dict):
                continue
            course = raw.get("course") if isinstance(raw.get("course"), dict) else {}
            department = raw.get("openDepartment") if isinstance(raw.get("openDepartment"), dict) else {}
            teachers = [text(item) for item in raw.get("teacherAssignmentList", []) if text(item)]
            schedule = text(raw.get("dateTimePlacePersonText")) or text(raw.get("dateTimePlaceText"))
            item = {
                "lesson_id": raw.get("id"),
                "lesson_code": raw.get("code"),
                "course_code": course.get("code"),
                "course_name": course.get("cn"),
                "course_name_en": course.get("en"),
                "credits": raw.get("credits"),
                "period": raw.get("period"),
                "teachers": teachers,
                "department": {"code": department.get("code"), "name": department.get("cn")},
                "campus": text(raw.get("campus")),
                "education": text(raw.get("education")),
                "class_type": text(raw.get("classType")),
                "course_type": text(raw.get("courseType")),
                "course_classify": text(raw.get("courseClassify")),
                "schedule": schedule,
                "student_count": raw.get("stdCount"),
                "limit_count": raw.get("limitCount"),
                "exam_mode": text(raw.get("examMode")),
            }
            searchable = " ".join(
                str(value or "")
                for value in (
                    item["lesson_code"],
                    item["course_code"],
                    item["course_name"],
                    item["course_name_en"],
                    item["department"]["name"],
                    *teachers,
                )
            )
            if query and query.casefold() not in searchable.casefold():
                continue
            if department_code and department_code != item["department"]["code"]:
                continue
            if teacher and not any(contains(name, teacher) for name in teachers):
                continue
            if campus and not contains(item["campus"], campus):
                continue
            if location and not contains(schedule, location):
                continue
            if education and not contains(item["education"], education):
                continue
            if class_type and not contains(item["class_type"], class_type):
                continue
            if course_classify and not contains(item["course_classify"], course_classify):
                continue
            if time_span and not contains(schedule, time_span):
                continue
            items.append(item)
        selected, actual_offset, actual_limit = page(items, offset, limit)
        return self._result(
            selected,
            len(items),
            f"/api/teach/lesson/list-for-teach/{semester_id}",
            offset=actual_offset,
            limit=actual_limit,
            extra={"semester_id": semester_id, "freshness_notice": "Official site data is updated on the following day."},
        )

    async def search_exams(
        self,
        semester_id: int,
        query: str = "",
        department_code: str = "",
        teacher: str = "",
        grade: str = "",
        admin_class: str = "",
        location: str = "",
        exam_date: str = "",
        exam_type: str = "",
        education: str = "",
        offset: int = 0,
        limit: int = 25,
    ) -> dict[str, Any]:
        normal, general = await asyncio.gather(
            self._json(f"/api/teach/exam/list/{semester_id}"),
            self._json(f"/api/teach/general-exam/list/{semester_id}"),
        )
        values = [
            *(normal if isinstance(normal, list) else []),
            *(general if isinstance(general, list) else []),
        ]
        items: list[dict[str, Any]] = []
        for raw in values:
            if not isinstance(raw, dict):
                continue
            item = self._exam(raw)
            searchable = " ".join(
                str(value or "")
                for value in (
                    item["course_code"], item["course_name"], item["course_name_en"],
                    item["department"]["name"], *item["teachers"], item["admin_classes"],
                )
            )
            if query and query.casefold() not in searchable.casefold():
                continue
            if department_code and department_code != item["department"]["code"]:
                continue
            if teacher and not any(contains(name, teacher) for name in item["teachers"]):
                continue
            if grade and not contains(item["grades"], grade):
                continue
            if admin_class and not contains(item["admin_classes"], admin_class):
                continue
            if location and not any(contains(room["room"], location) for room in item["rooms"]):
                continue
            if exam_date and not str(item["date"]).startswith(exam_date):
                continue
            if exam_type and not contains(item["type"], exam_type):
                continue
            if education and not contains(item["education"], education):
                continue
            items.append(item)
        items.sort(key=lambda item: (str(item["date"]), int(item["start_time"] or 0)))
        selected, actual_offset, actual_limit = page(items, offset, limit)
        return self._result(
            selected,
            len(items),
            f"/api/teach/exam/list/{semester_id}",
            offset=actual_offset,
            limit=actual_limit,
            extra={"semester_id": semester_id},
        )

    @staticmethod
    def _exam(raw: dict[str, Any]) -> dict[str, Any]:
        lesson = raw.get("lesson") if isinstance(raw.get("lesson"), dict) else {}
        course = lesson.get("course") if isinstance(lesson.get("course"), dict) else {}
        department = lesson.get("openDepartment") if isinstance(lesson.get("openDepartment"), dict) else {}
        general = not lesson and "courseName" in raw
        type_names = {1: "midterm", 2: "final", 21: "final", 3: "make-up", 4: "deferred"}
        rooms = raw.get("examRooms", []) if isinstance(raw.get("examRooms"), list) else []
        if general and raw.get("room"):
            rooms = [{"room": raw.get("room"), "count": None}]
        teachers = [text(item) for item in lesson.get("teacherAssignmentList", []) if text(item)]
        raw_type = raw.get("examType")
        batch = raw.get("batch") or text(raw.get("examBatch"))
        return {
            "exam_id": raw.get("id"),
            "course_code": raw.get("courseCode") if general else course.get("code"),
            "course_name": raw.get("courseName") if general else course.get("cn"),
            "course_name_en": raw.get("courseNameEn") if general else course.get("en"),
            "date": raw.get("examDate"),
            "start_time": raw.get("startTime"),
            "end_time": raw.get("endTime"),
            "type": batch or type_names.get(raw_type, f"unknown:{raw_type}"),
            "rooms": [{"room": room.get("room"), "count": room.get("count")} for room in rooms if isinstance(room, dict)],
            "teachers": teachers,
            "department": {
                "code": None if general else department.get("code"),
                "name": raw.get("dept") if general else department.get("cn"),
            },
            "education": text(raw.get("education") or lesson.get("education")),
            "grades": raw.get("grades"),
            "admin_classes": raw.get("adminclasseNames"),
            "exam_mode": raw.get("examMode"),
            "source_kind": "general" if general else "scheduled",
        }

    def _result(
        self,
        items: list[dict[str, Any]],
        total: int,
        api_path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "items": items,
            "total": total,
            "offset": offset,
            "limit": len(items) if limit is None else limit,
            "source_url": f"{self.base_url}{api_path}",
            "fetched_at": fetched_at(),
            **(extra or {}),
        }
