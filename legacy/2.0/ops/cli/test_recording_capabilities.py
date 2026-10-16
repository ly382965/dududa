"""Exercise every configured recording MCP query with saved, inspectable results."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--state", type=Path, default=ROOT.parent / "dududa-recording-state"
    )
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    fixture = ROOT / "tests/fixtures/recording/manual-capability-cases.json"
    document = json.loads(fixture.read_text())
    cases = [
        x
        for x in document["cases"]
        if x["mode"] != "runtime" and (not args.only or args.only in x["capabilityId"])
    ]
    groups = {}
    for case in cases:
        groups.setdefault(
            case["capabilityId"].split(".")[0]
            if not case["capabilityId"].startswith("ustc.")
            else ".".join(case["capabilityId"].split(".")[:2]),
            [],
        ).append(case)
    results = []
    async with httpx.AsyncClient(trust_env=False, timeout=125) as client:

        async def invoke(case):
            start = datetime.now(timezone.utc)
            try:
                r = await client.post(
                    args.url.rstrip("/") + "/v1/invoke",
                    json={
                        "capabilityId": case["capabilityId"],
                        "arguments": case["arguments"],
                    },
                )
                data = r.json()
                result = {
                    "capabilityId": case["capabilityId"],
                    "question": case["question"],
                    "arguments": case["arguments"],
                    "httpStatus": r.status_code,
                    "passed": r.status_code == 200 and data.get("ok") is True,
                    "result": data,
                }
            except (httpx.HTTPError, ValueError) as exc:
                result = {
                    "capabilityId": case["capabilityId"],
                    "passed": False,
                    "error": str(exc),
                }
            result["seconds"] = round(
                (datetime.now(timezone.utc) - start).total_seconds(), 2
            )
            results.append(result)
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in result.items()
                        if k not in ("result", "arguments")
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return result.get("result", {}).get("data") or {}

        async def group_run(rows):
            # Resolve actual IDs from search before exercising detail tools.
            rows.sort(key=lambda x: (".get." in x["capabilityId"], x["capabilityId"]))
            notice_id = activity_id = None
            for row in rows:
                if "$latest_notice" in str(row["arguments"]):
                    if not notice_id:
                        continue
                    row["arguments"]["notice_id"] = str(notice_id)
                    row["question"] = row["question"].replace(
                        "$latest_notice", str(notice_id)
                    )
                if "$latest_activity" in str(row["arguments"]):
                    if not activity_id:
                        continue
                    row["arguments"]["activity_id"] = str(activity_id)
                    row["question"] = row["question"].replace(
                        "$latest_activity", str(activity_id)
                    )
                data = await invoke(row)
                if isinstance(data.get("data"), dict):
                    data = data["data"]
                if row["capabilityId"] == "notifai.notices.search.v1":
                    items = data.get("items", data.get("notices", []))
                    notice_id = items[0].get("id") if items else None
                if row["capabilityId"] == "ustc.young.activities.search.v1":
                    items = data.get("items", data.get("activities", []))
                    activity_id = (
                        items[0].get("activity_id", items[0].get("id"))
                        if items
                        else None
                    )

        await asyncio.gather(*(group_run(rows) for rows in groups.values()))
    missing = [
        x["capabilityId"]
        for x in cases
        if x["capabilityId"] not in {r["capabilityId"] for r in results}
    ]
    report = {
        "testedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "live_mcp",
        "passed": not missing and all(x["passed"] for x in results),
        "missing": missing,
        "results": results,
    }
    path = args.state / "reports/manual-mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    fixture.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "count": len(results),
                "missing": missing,
                "report": str(path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
