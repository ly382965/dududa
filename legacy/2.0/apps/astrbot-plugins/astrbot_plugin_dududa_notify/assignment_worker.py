from __future__ import annotations

import asyncio
import base64
import json
import sys

from assignment_client import HomeworkClient, HomeworkError
from campus_auth import CampusAuthError, graduate_session
from portal_diagnostics import PortalResponseError
from weekly_client import WeeklyError
from worker import load_credentials


async def execute(request: dict) -> dict:
    if request["operation"] == "render_course_report":
        from course_report import render_report

        return {
            "content": base64.b64encode(render_report(request["report"])).decode(
                "ascii"
            )
        }
    if request["operation"] == "render_pdf":
        from homework_pdf import render_pdf

        return {
            "content": base64.b64encode(render_pdf(request["content"])).decode("ascii")
        }
    credentials = load_credentials(request.get("credentials_file", ""))
    if request["operation"] in {"weekly_list", "weekly_submit"}:
        from weekly_client import execute_weekly

        return await execute_weekly(request, credentials)
    if request["operation"] == "courses":
        from course_sources import fetch_courses

        return await fetch_courses(request, credentials)
    async with graduate_session(
        credentials, timeout=request.get("timeout", 45)
    ) as session:
        client = HomeworkClient(session)
        await client.initialize()
        operation = request["operation"]
        if operation == "list":
            return await client.snapshot()
        if operation == "detail":
            return await client.detail(request["assignment_id"], attachments=False)
        if operation == "submit":
            return await client.submit(
                request["expected"],
                request["filename"],
                base64.b64decode(request["content"], validate=True),
                request["token"],
            )
        raise HomeworkError("unknown_homework_operation")


def main() -> int:
    request = json.load(sys.stdin)
    try:
        result = asyncio.run(execute(request))
    except (HomeworkError, CampusAuthError, WeeklyError, PortalResponseError) as exc:
        result = {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - never expose CAS tickets or request bodies
        result = {"error": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
