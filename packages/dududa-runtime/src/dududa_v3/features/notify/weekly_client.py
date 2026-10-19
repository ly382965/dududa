"""USTC teaching-assistant weekly reports, using the site's empty-submit flow."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

if __package__:
    from .campus_auth import graduate_ticket
    from .weekly import is_due
else:
    from campus_auth import graduate_ticket
    from weekly import is_due

ORIGIN = "https://tam.cmet.ustc.edu.cn"
API = ORIGIN + "/ustcta-server"
PORTAL = ORIGIN + "/ustcta-pc/"
WEEKLY_PAGE = PORTAL + "#/stu-week-report-student/index"
REPORT_API = "/api/v1/for-student/stu-week-report"


class WeeklyError(ValueError):
    pass


def normalize_report(row, username):
    if (
        str((row.get("assistStu") or {}).get("code", "")).casefold()
        != username.casefold()
    ):
        raise WeeklyError("weekly_owner_mismatch")
    required = (
        "id",
        "semesterId",
        "lessonId",
        "assistStuId",
        "fulWeekRangeStart",
        "fulWeekRangeEnd",
    )
    if any(not isinstance(row.get(k), str) or not row[k] for k in required):
        raise WeeklyError("weekly_response_invalid")
    try:
        start = date.fromisoformat(row["fulWeekRangeStart"]).isoformat()
        end = date.fromisoformat(row["fulWeekRangeEnd"]).isoformat()
        dates = sorted(
            {
                date.fromisoformat(value.strip()).isoformat()
                for value in (row.get("reportRangeStr") or "").split(",")
                if value.strip()
            }
        )
    except (ValueError, TypeError):
        raise WeeklyError("weekly_schedule_invalid") from None
    if row.get("submitStatus") not in {"SUBMITTED", "NOT_SUBMITTED", "CANCELLED"}:
        raise WeeklyError("weekly_response_invalid")
    # The site replaces its provisional row ID after submission; this period key stays stable.
    key = ":".join((row["semesterId"], row["lessonId"], row["assistStuId"], start, end))
    return {
        "key": key,
        "id": row["id"],
        "semester_id": row["semesterId"],
        "course": row.get("courseCodeAndName") or "助教课程",
        "week_start": start,
        "week_end": end,
        "report_dates": dates,
        "open_week": row.get("openWeek") is True,
        "status": row["submitStatus"],
        "submitted_at": row.get("submitTime"),
    }


class WeeklyClient:
    def __init__(self, client, username):
        self.client, self.username = client, username
        self.semester_id = None
        self.can_submit = False
        self.write_started = False

    async def request(self, method, path, **kwargs):
        response = await self.client.request(method, API + path, **kwargs)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise WeeklyError("weekly_api_rejected")
        return result

    async def initialize(self, token):
        result = await self.request(
            "GET",
            "/api/v1/poa/sys-auth/account/get-by-login-name",
            params={"token": token},
        )
        account = result["data"]
        if (
            str(account.get("loginName", "")).casefold() != self.username.casefold()
            or account.get("currentIdentity") != "STUDENT"
        ):
            raise WeeklyError("weekly_owner_mismatch")
        self.semester_id = str(account["currentSemesterId"])
        self.can_submit = any(
            p.get("permCode") == "stu-week-report-stu:submit"
            for p in account.get("permissions", [])
            if isinstance(p, dict)
        )

    async def reports(self, semester_id):
        items, seen, page = [], set(), 1
        while True:
            result = await self.request(
                "GET",
                REPORT_API + "/search",
                params={"semesterId": semester_id, "queryPage__": f"{page},100"},
            )
            rows, info = result.get("data"), result.get("pageInfo", {})
            if not isinstance(rows, list) or info.get("currentPage") != page:
                raise WeeklyError("weekly_pagination_invalid")
            for row in rows:
                item = normalize_report(row, self.username)
                if item["semester_id"] != str(semester_id) or item["key"] in seen:
                    raise WeeklyError("weekly_pagination_invalid")
                seen.add(item["key"])
                items.append(item)
            if page >= info.get("totalPages", 0):
                if len(items) != info.get("totalRows"):
                    raise WeeklyError("weekly_pagination_invalid")
                return items
            page += 1
            if page > 100:
                raise WeeklyError("weekly_pagination_invalid")

    async def snapshot(self, semesters=()):
        reports = []
        for semester in dict.fromkeys([self.semester_id, *semesters]):
            reports.extend(await self.reports(semester))
        return {
            "semester_id": self.semester_id,
            "reports": reports,
            "can_submit": self.can_submit,
        }

    async def submit(self, expected, *, hour=20, policy="first"):
        reports = await self.reports(expected["semester_id"])
        item = next((r for r in reports if r["key"] == expected["key"]), None)
        if item is None:
            return {"outcome": "blocked", "reason": "weekly_report_missing"}
        if item["status"] == "SUBMITTED":
            return {"outcome": "already_submitted", "report": item}
        if item["report_dates"] != expected["report_dates"]:
            return {"outcome": "blocked", "reason": "weekly_schedule_changed"}
        if not self.can_submit:
            return {"outcome": "blocked", "reason": "weekly_permission_missing"}
        if not is_due(item, hour, policy):
            return {"outcome": "not_due"}
        payload = {"id": item["id"], "semesterId": item["semester_id"]}
        check = await self.request("POST", REPORT_API + "/check-submit", json=payload)
        if check.get("data"):
            return {"outcome": "blocked", "reason": "weekly_submission_closed"}
        studies = await self.request(
            "GET", REPORT_API + "/check-week-range-studies", params=payload
        )
        if studies.get("data") is not False:
            return {"outcome": "blocked", "reason": "weekly_report_not_empty"}
        if not is_due(item, hour, policy):
            return {"outcome": "not_due"}
        self.write_started = True
        await self.request("POST", REPORT_API + "/submit", json=payload)
        verified = next(
            (
                r
                for r in await self.reports(item["semester_id"])
                if r["key"] == item["key"]
            ),
            None,
        )
        if verified and verified["status"] == "SUBMITTED" and verified["submitted_at"]:
            return {"outcome": "submitted", "report": verified}
        return {"outcome": "uncertain", "reason": "weekly_receipt_unconfirmed"}


@asynccontextmanager
async def weekly_session(credentials, timeout=45):
    from pyustc.cas import CASClient

    async with httpx.AsyncClient(
        trust_env=False, timeout=timeout, follow_redirects=False
    ) as http:
        response = await http.get(API + "/ucas-sso/login")
        login = response.headers.get("location", "")
        target = urlsplit(login)
        if (target.scheme, target.hostname, target.path, target.port) != (
            "https",
            "passport.ustc.edu.cn",
            "/login",
            None,
        ) or target.username:
            raise WeeklyError("weekly_login_redirect_invalid")
        response = await http.get(login)
        target = urlsplit(response.headers.get("location", ""))
        if (target.scheme, target.hostname, target.path, target.port) != (
            "https",
            "id.ustc.edu.cn",
            "/cas/login",
            None,
        ) or target.username:
            raise WeeklyError("weekly_login_redirect_invalid")
        service = parse_qs(target.query).get("service", [""])[0]
        target = urlsplit(service)
        if (
            (target.scheme, target.hostname, target.path, target.port)
            != ("https", "tam.cmet.ustc.edu.cn", "/ustcta-server/ucas-sso/login", None)
            or target.username
            or target.fragment
            or parse_qs(target.query) != {"redirect_uri": [PORTAL]}
        ):
            raise WeeklyError("weekly_login_redirect_invalid")
        cas = CASClient.login_by_pwd(credentials.username, credentials.password)
        cas._client.timeout = httpx.Timeout(timeout)
        async with cas:
            ticket = await graduate_ticket(cas, service)
        response = await http.get(service + "&" + urlencode({"ticket": ticket}))
        target = urlsplit(response.headers.get("location", ""))
        fragment = urlsplit(target.fragment)
        tokens = parse_qs(fragment.query).get("idToken", [])
        if (
            (target.scheme, target.hostname, target.path, target.port)
            != ("https", "tam.cmet.ustc.edu.cn", "/ustcta-pc/", None)
            or target.username
            or fragment.path != "/cas-login"
            or len(tokens) != 1
            or not tokens[0]
        ):
            raise WeeklyError("weekly_login_redirect_invalid")
        http.headers["Authorization"] = tokens[0]
        client = WeeklyClient(http, credentials.username)
        await client.initialize(tokens[0])
        yield client


async def execute_weekly(request, credentials):
    client = None
    try:
        async with weekly_session(credentials, request.get("timeout", 45)) as client:
            if request["operation"] == "weekly_list":
                return await client.snapshot(request.get("semesters", []))
            return await client.submit(
                request["expected"],
                hour=request.get("hour", 20),
                policy=request.get("policy", "first"),
            )
    except Exception as exc:
        if request["operation"] != "weekly_submit":
            raise
        return {
            "outcome": "uncertain" if client and client.write_started else "not_sent",
            "reason": str(exc) if isinstance(exc, WeeklyError) else type(exc).__name__,
        }
