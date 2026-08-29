from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .academic import AcademicClient
from .calendar import TeachingCalendarClient
from .curriculum import CurriculumClient
from .young import YoungClient

SERVICES = ("academic", "curriculum", "young")


def create_mcp(service: str) -> FastMCP:
    service = service.casefold()
    if service not in SERVICES:
        raise ValueError(f"unknown service: {service}")
    clients: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        if service == "academic":
            clients["academic"] = AcademicClient(os.getenv("USTC_CATALOG_BASE_URL", "https://catalog.ustc.edu.cn"))
            clients["calendar"] = TeachingCalendarClient(
                os.getenv("USTC_TEACHING_CALENDAR_URL", "https://www.teach.ustc.edu.cn/calendar/20135.html")
            )
        elif service == "curriculum":
            clients["curriculum"] = CurriculumClient(
                os.getenv(
                    "USTC_CURRICULUM_DATA_BASE_URL",
                    "https://docs.mmdustc.top/curriculum/data",
                )
            )
        else:
            clients["young"] = YoungClient()
        try:
            yield clients
        finally:
            for client in clients.values():
                close = getattr(client, "close", None)
                if close is not None:
                    await close()
            clients.clear()

    mcp = FastMCP(f"ustc-{service}-mcp", lifespan=lifespan)

    if service == "academic":
        def academic() -> AcademicClient:
            return clients["academic"]

        @mcp.tool()
        async def catalog_list_semesters(include_future: bool = True, limit: int = 20) -> dict[str, Any]:
            """List official USTC teaching semesters and their integer API IDs."""
            return await academic().list_semesters(include_future, limit)

        @mcp.tool()
        async def catalog_search_lessons(
            semester_id: int = 0,
            semester: str = "",
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
            """Search an official lesson list, resolving a semester label when needed."""
            resolved_semester_id = (
                semester_id
                if semester_id > 0
                else await academic().resolve_semester_id(semester)
            )
            return await academic().search_lessons(
                resolved_semester_id, query, department_code, teacher, campus, location,
                education, class_type, course_classify, time_span, offset, limit,
            )

        @mcp.tool()
        async def catalog_search_exams(
            semester_id: int = 0,
            semester: str = "",
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
            """Search official exams, resolving a semester label when needed."""
            resolved_semester_id = (
                semester_id
                if semester_id > 0
                else await academic().resolve_semester_id(semester)
            )
            return await academic().search_exams(
                resolved_semester_id, query, department_code, teacher, grade, admin_class,
                location, exam_date, exam_type, education, offset, limit,
            )

        @mcp.tool()
        async def teaching_calendar_get(start_date: str = "", end_date: str = "") -> dict[str, Any]:
            """Read the current official teaching-calendar article and optionally filter dates."""
            return await clients["calendar"].get(start_date, end_date)

    elif service == "curriculum":
        @mcp.tool()
        async def curriculum_public_query(
            query: str,
            goal: str = "",
            operation: Literal[
                "overview",
                "program",
                "course",
                "change",
                "comparison",
                "substitution",
                "shared",
                "history",
            ] = "program",
            limit: int = 6,
        ) -> dict[str, Any]:
            """Query the bounded public curriculum research snapshot, not live SIS data."""
            return await clients["curriculum"].public_query(
                query,
                goal,
                operation,
                limit,
            )

    else:
        def young() -> YoungClient:
            return clients["young"]

        @mcp.tool()
        def young_connection_status() -> dict[str, Any]:
            """Report whether USTC CAS SecretRefs are configured without returning credential data."""
            return young().status()

        @mcp.tool()
        async def young_search_activities(
            query: str = "",
            state: str = "applying",
            module_id: str = "",
            department_id: str = "",
            label_ids: list[str] | None = None,
            start_time: str = "",
            end_time: str = "",
            limit: int = 20,
        ) -> dict[str, Any]:
            """Search authenticated USTC second-class activities through pyustc."""
            return await young().search_activities(
                query, state, module_id, department_id, label_ids, start_time, end_time, limit,
            )

        @mcp.tool()
        async def young_get_activity(activity_id: str, include_children: bool = False) -> dict[str, Any]:
            """Read one second-class activity and optionally its series children."""
            return await young().get_activity(activity_id, include_children)

        @mcp.tool()
        async def young_list_facets(facet: str) -> dict[str, Any]:
            """List second-class module, department or label filters."""
            return await young().list_facets(facet)

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one USTC campus MCP server over stdio.")
    parser.add_argument("--service", choices=SERVICES, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    create_mcp(args.service).run()


if __name__ == "__main__":
    main(sys.argv[1:])
