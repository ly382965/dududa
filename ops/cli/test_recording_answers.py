"""Check the fixed manual questions with real model and tool responses."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from prepare_recording_environment import ROOT, initial_policy
from run_recording_rehearsal import reset_policy

STATE = ROOT.parent / "dududa-recording-state"
CASES = [
    (
        "ustc.young.read",
        "ustc.young.activities.search.v1",
        "二课里搜索英语角活动，列出活动名称和活动时间。",
    ),
    (
        "ustc.academic.read",
        "ustc.academic.lessons.search.v1",
        "查询2026秋季学期数学分析的开课记录，列出课程名和任课教师。",
    ),
    (
        "ustc.curriculum.read",
        "ustc.curriculum.",
        "查询2026级计算机科学与技术普通主修培养方案的总学分要求。",
    ),
    (
        "notifai.read",
        "notifai.notices.search.v1",
        "查询最近三条校园通知，带标题、日期和来源链接。",
    ),
    (
        "ustc.shuttle.read",
        "ustc.shuttle.",
        "列出工作日东校区到西校区上午的校车发车时刻。",
    ),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=[case[0] for case in CASES])
    args = parser.parse_args()
    report = STATE / "reports/manual-answers.json"
    rows = (
        [
            row
            for row in json.loads(report.read_text())["results"]
            if row["plugin"] != args.only
        ]
        if args.only and report.exists()
        else []
    )
    key = (STATE / "secrets/astrbot_plugin_api_key").read_text().strip()
    with httpx.Client(
        trust_env=False, timeout=240, headers={"X-API-Key": key}
    ) as client:
        for plugin, prefix, question in CASES:
            if args.only and plugin != args.only:
                continue
            policy = initial_policy()
            policy["plugins"] = {plugin: "on"}
            policy["adaptivePlugins"] = []
            policy["answerProfile"] = {
                "mode": "locked",
                "preferred": "long",
                "allowed": ["long"],
            }
            policy["updatedAt"] = datetime.now(timezone.utc).isoformat()
            scope = policy["scope"]
            key_id = f"{quote(scope['accountId'], safe='')}::{quote(scope['conversationId'], safe='')}"
            (STATE / "agent/agent-policies.json").write_text(
                json.dumps({"schemaVersion": 1, "policies": {key_id: policy}})
            )
            start = datetime.now(timezone.utc)
            try:
                r = client.post(
                    "http://127.0.0.1:6186/api/v1/plugins/extensions/astrbot_plugin_dududa_core/runtime/preview",
                    json={**scope, "prompt": question},
                )
                value = r.json()
                data = value.get("data") or {}
                candidate = data.get("candidate", "")
                row = {
                    "plugin": plugin,
                    "question": question,
                    "httpStatus": r.status_code,
                    "seconds": round(
                        (datetime.now(timezone.utc) - start).total_seconds(), 2
                    ),
                    "passed": r.status_code == 200
                    and bool(candidate)
                    and data.get("toolCalls", 0) > 0
                    and any(
                        x.startswith(prefix) for x in data.get("capabilityIds", [])
                    ),
                    "result": value,
                }
            except (httpx.HTTPError, ValueError) as e:
                row = {
                    "plugin": plugin,
                    "question": question,
                    "passed": False,
                    "error": str(e),
                }
            rows.append(row)
            (STATE / "reports/manual-answers.json").write_text(
                json.dumps(
                    {"passed": all(x["passed"] for x in rows), "results": rows},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            print(
                json.dumps(
                    {k: v for k, v in row.items() if k != "result"}, ensure_ascii=False
                ),
                flush=True,
            )
    reset_policy(STATE)
    return 0 if all(x["passed"] for x in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
