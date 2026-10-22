"""Run SeminarRadar in its own Python environment, returning JSON only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import tomllib

if __package__:
    from .campus_auth import CampusAuthError, graduate_session
    from .portal_diagnostics import PortalResponseError
    from .seminar_client import create_seminar_client
else:
    from campus_auth import CampusAuthError, graduate_session
    from portal_diagnostics import PortalResponseError
    from seminar_client import create_seminar_client


def load_credentials(path: str, *, expected_username=None):
    from seminar_radar.config import Credentials

    username = os.getenv("USTC_CAS_USR", "")
    password = os.getenv("USTC_CAS_PWD", "")
    # An explicit account file must never inherit another account's environment.
    if path or not (username and password):
        configured = path or os.getenv("USTC_CAS_CREDENTIALS_FILE", "")
        if not configured:
            raise ValueError("cas_credentials_missing")
        with Path(configured).open("rb") as handle:
            document = tomllib.load(handle)
        username = document.get("username")
        password = document.get("password")
    if not isinstance(username, str) or not username.strip():
        raise ValueError("cas_username_missing")
    if not isinstance(password, str) or not password.strip():
        raise ValueError("cas_password_missing")
    if expected_username is not None and username != expected_username:
        raise ValueError("cas_account_mismatch")
    return Credentials(username=username, password=password)


async def fetch(credentials_file: str, timeout: float) -> dict:
    from seminar_radar.reports import CHINA_TIME, normalize_report

    credentials = load_credentials(credentials_file)
    async with graduate_session(credentials, timeout=timeout) as session:
        client = create_seminar_client(session)
        await client.initialize()
        rows = await client.fetch_unselected()
    now = datetime.now(CHINA_TIME)
    reports = [normalize_report(row, now=now) for row in rows]
    available = sorted(
        (report for report in reports if report["available"]),
        key=lambda report: (not report["preferred"], report["time"], report["id"]),
    )
    return {
        "fetched_at": now.isoformat(timespec="seconds"),
        "total": len(reports),
        "available_count": len(available),
        "recommended_count": sum(report["preferred"] for report in available),
        "reports": available,
    }


def main() -> int:
    from seminar_radar.client import QueryError as SeminarQueryError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-file", default="")
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("timeout must be in (0, 300]")
    try:
        result = asyncio.run(fetch(args.credentials_file, args.timeout))
    except (CampusAuthError, PortalResponseError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except SeminarQueryError as exc:
        code = {
            "报告列表与总数不一致，请重新运行。": "seminar_list_incomplete",
            "查询期间报告总数发生变化，请重新运行获取完整列表。": "seminar_list_changed",
            "报告接口重复返回同一页，无法获取完整列表。": "seminar_repeated_page",
        }.get(str(exc), "seminar_query_failed")
        print(json.dumps({"error": code}))
        return 1
    except Exception as exc:  # noqa: BLE001 - sanitize the subprocess output boundary
        # Library exceptions can contain login URLs or cookies; expose only their type.
        print(json.dumps({"error": type(exc).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
