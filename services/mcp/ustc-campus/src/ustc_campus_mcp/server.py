from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from .academic import AcademicClient
from .calendar import TeachingCalendarClient
from .shuttle import ShuttleClient
from .young import YoungClient

SERVICES = ("academic", "shuttle", "young")


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
        elif service == "shuttle":
            clients["shuttle"] = ShuttleClient(
                os.getenv("USTC_SHUTTLE_URL", "https://www.ustc.edu.cn/info/1029/25471.htm")
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
        async def catalog_search_programs(
            query: str = "",
            department_code: str = "",
            major_code: str = "",
            grade: str = "",
            train_type: str = "",
            offset: int = 0,
            limit: int = 20,
        ) -> dict[str, Any]:
            """Search official USTC undergraduate training programs."""
            return await academic().search_programs(query, department_code, major_code, grade, train_type, offset, limit)

        @mcp.tool()
        async def catalog_get_program(
            program_id: int,
            term: str = "",
            expand_shared_modules: bool = False,
            include_introduction: bool = False,
        ) -> dict[str, Any]:
            """Read one official training program; large course introductions are off by default."""
            return await academic().get_program(program_id, term, expand_shared_modules, include_introduction)

        @mcp.tool()
        async def catalog_search_lessons(
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
            """Search a semester's official lesson list with local filters and pagination."""
            return await academic().search_lessons(
                semester_id, query, department_code, teacher, campus, location,
                education, class_type, course_classify, time_span, offset, limit,
            )

        @mcp.tool()
        async def catalog_search_exams(
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
            """Search normalized scheduled and general USTC exam records."""
            return await academic().search_exams(
                semester_id, query, department_code, teacher, grade, admin_class,
                location, exam_date, exam_type, education, offset, limit,
            )

        @mcp.tool()
        async def teaching_calendar_get(start_date: str = "", end_date: str = "") -> dict[str, Any]:
            """Read the current official teaching-calendar article and optionally filter dates."""
            return await clients["calendar"].get(start_date, end_date)

    elif service == "shuttle":
        @mcp.tool()
        async def shuttle_current_schedule() -> dict[str, Any]:
            """Return the current official shuttle notice, image and revision-bound structured timetable."""
            return await clients["shuttle"].current_schedule()

        @mcp.tool()
        async def shuttle_search_trips(from_station: str, to_station: str, after: str = "") -> dict[str, Any]:
            """Search trips between east, west, research and hightech campuses."""
            return await clients["shuttle"].search_trips(from_station, to_station, after)

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
