"""Official seminar selection protocol; never infer success from a write alone."""

from __future__ import annotations

import hashlib
import json
import re

APP_BASE = "https://yjs1.ustc.edu.cn/gsapp/sys/xsbgglappustc"
SELECT_URL = APP_BASE + "/xsbgxkController/selectBg.do"
STUDENT_URL = APP_BASE + "/modules/xsbgxk/xsjcxxcx.do"


class SeminarBookingError(RuntimeError):
    """Only stable, non-identifying reason codes may cross the worker boundary."""


def canonical_account(username: str) -> str:
    if not isinstance(username, str) or not username.strip():
        raise SeminarBookingError("seminar_identity_missing")
    return username.strip().casefold()


def account_key(username: str) -> str:
    return hashlib.sha256(canonical_account(username).encode("utf-8")).hexdigest()


def report_identifier(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SeminarBookingError("seminar_report_id_invalid")
    identifier = str(value).strip()
    if not identifier or len(identifier) > 128 or any(c.isspace() for c in identifier):
        raise SeminarBookingError("seminar_report_id_invalid")
    return identifier


def page_integer(value) -> int:
    if isinstance(value, bool) or not str(value).isdigit():
        raise SeminarBookingError("seminar_selected_pagination_invalid")
    return int(value)


def withdrawal_fields(row) -> dict:
    flag = str(row.get("SFKTK", "")).strip()
    return {
        "cancellable": True if flag == "1" else False if flag == "0" else None,
        # The official selected table exposes no withdrawal deadline. JZSJ is
        # the enrollment deadline, not evidence of when withdrawal closes.
        "withdrawal_deadline": None,
    }


def create_seminar_client(session):
    from seminar_radar.client import SeminarClient

    class StableSeminarClient(SeminarClient):
        async def verify_identity(self):
            from seminar_radar.client import APP_URL

            response = await self.session.get(APP_URL, follow_redirects=False)
            if response.status_code != 200:
                raise SeminarBookingError("seminar_identity_unavailable")
            match = re.search(r"\bvar\s+pageMeta\s*=\s*(\{.*?\})\s*;", response.text, re.DOTALL)
            try:
                metadata = json.loads(match.group(1)) if match else {}
                identity = metadata["params"]["USERID"]
            except (ValueError, KeyError, TypeError):
                raise SeminarBookingError("seminar_identity_unavailable") from None
            if canonical_account(identity) != self.username:
                raise SeminarBookingError("seminar_account_mismatch")

        async def initialize_account(self, username):
            self.username = canonical_account(username)
            await self.initialize()
            await self.verify_identity()
            # The official selected tab switches action for combined MSc/PhD students.
            table = await self._query(
                STUDENT_URL, "xsjcxxcx", {"pageSize": "1", "pageNumber": "1"}
            )
            if len(table["rows"]) != 1 or page_integer(table.get("totalSize")) != 1:
                raise SeminarBookingError("seminar_identity_unavailable")
            student = table["rows"][0]
            if canonical_account(student.get("XH")) != self.username:
                raise SeminarBookingError("seminar_account_mismatch")
            if not isinstance(student.get("RXFSDM"), str) or not student["RXFSDM"]:
                raise SeminarBookingError("seminar_selected_action_unknown")
            self.selected_action = (
                "szbyxbgbgdz" if student["RXFSDM"] == "23" else "yxbgbgdz"
            )
            self.account_key = account_key(self.username)
            return self.account_key

        async def fetch_selected(self, *, max_pages=1000):
            reports = {}
            expected_total = None
            action = self.selected_action
            for number in range(1, max_pages + 1):
                table = await self._query(
                    APP_BASE + "/modules/xsbgxk/" + action + ".do",
                    action,
                    {
                        "*order": "-BGBM",
                        "querySetting": "[]",
                        "pageSize": str(self.page_size),
                        "pageNumber": str(number),
                    },
                )
                if page_integer(table.get("pageNumber")) != number:
                    raise SeminarBookingError("seminar_selected_page_mismatch")
                total = page_integer(table.get("totalSize"))
                if expected_total is not None and total != expected_total:
                    raise SeminarBookingError("seminar_selected_list_changed")
                expected_total = total
                for row in table["rows"]:
                    identifier = report_identifier(row.get("BGBM"))
                    if identifier in reports:
                        raise SeminarBookingError("seminar_selected_duplicate")
                    # The combined-program tab may include the former MSc student ID.
                    if (action == "yxbgbgdz" and row.get("XH") is not None
                            and canonical_account(row["XH"]) != self.username):
                        raise SeminarBookingError("seminar_account_mismatch")
                    reports[identifier] = row
                if len(reports) > total or (not table["rows"] and len(reports) != total):
                    raise SeminarBookingError("seminar_selected_list_incomplete")
                if len(reports) == total:
                    return list(reports.values())
            raise SeminarBookingError("seminar_selected_page_limit")

        async def book(self, identifier, expected_account_key, *, preferred_only=True):
            from seminar_radar.reports import normalize_report

            identifier = report_identifier(identifier)
            if expected_account_key != self.account_key:
                raise SeminarBookingError("seminar_account_mismatch")
            if not isinstance(preferred_only, bool):
                raise SeminarBookingError("seminar_preference_invalid")
            selected = await self.fetch_selected()
            for row in selected:
                if report_identifier(row["BGBM"]) == identifier:
                    return {
                        "status": "already_selected",
                        "reason": "seminar_already_selected",
                        "report": {
                            **normalize_report({**row, "BGBM": identifier}),
                            **withdrawal_fields(row),
                        },
                    }
            rows = await self.fetch_unselected()
            row = next(
                (row for row in rows if report_identifier(row["BGBM"]) == identifier),
                None,
            )
            if row is None:
                return {"status": "unavailable", "reason": "seminar_not_unselected"}
            report = normalize_report({**row, "BGBM": identifier})
            result = {"report": report}
            if not report["available"]:
                return {**result, "status": "unavailable", "reason": "seminar_not_available"}
            if preferred_only and not report["preferred"]:
                return {**result, "status": "unavailable", "reason": "seminar_not_preferred"}

            # xsbgxkBS.js + wxbg.js identify the endpoint and BGBM payload.
            # xgjsutil.js convertParam wraps it in one URL-encoded JSON `data` field.
            # Never retry this request, including exceptions raised by response hooks.
            try:
                response = await self.session.post(
                    SELECT_URL,
                    data={"data": json.dumps({"BGBM": identifier}, separators=(",", ":"))},
                    headers=self.headers,
                    follow_redirects=False,
                )
                if response.status_code != 200:
                    return {**result, "status": "uncertain", "reason": "seminar_write_http_unknown"}
                payload = response.json()
                code = payload.get("code") if isinstance(payload, dict) else None
                if isinstance(code, bool) or not isinstance(code, (str, int)):
                    return {**result, "status": "uncertain", "reason": "seminar_write_response_unknown"}
                if str(code) != "0":
                    if not str(code).lstrip("-").isdigit():
                        return {**result, "status": "uncertain", "reason": "seminar_write_response_unknown"}
                    return {**result, "status": "rejected", "reason": "seminar_portal_rejected"}
                if payload.get("success") is False:
                    return {**result, "status": "uncertain", "reason": "seminar_write_response_unknown"}
            except Exception:  # noqa: BLE001 - any post-submission failure leaves the write uncertain
                return {**result, "status": "uncertain", "reason": "seminar_write_outcome_unknown"}

            try:
                await self.verify_identity()
                selected = await self.fetch_selected()
            except Exception:  # noqa: BLE001 - never call an unconfirmed selection successful
                return {**result, "status": "uncertain", "reason": "seminar_confirmation_failed"}
            for row in selected:
                if report_identifier(row["BGBM"]) == identifier:
                    return {
                        "report": {**report, **withdrawal_fields(row)},
                        "status": "booked",
                        "reason": "seminar_selection_confirmed",
                    }
            return {**result, "status": "uncertain", "reason": "seminar_selection_not_confirmed"}

        async def _query(self, url, action, data):
            if action == "wxbgbgdz":
                # Several reports share BGSJ; date-only ordering can repeat page boundaries.
                data = {**data, "*order": "-BGBM"}
            return await super()._query(url, action, data)

    return StableSeminarClient(session)
