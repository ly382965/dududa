"""Run the fixed four-member recording scene against the prepared Runtime."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from prepare_recording_environment import BOT_ID, GROUP_ID, ROOT, initial_policy


def reset_policy(state: Path) -> None:
    policy = initial_policy()
    policy["updatedAt"] = datetime.now(timezone.utc).isoformat()
    scope = policy["scope"]
    key = f"{quote(scope['accountId'], safe='')}::{quote(scope['conversationId'], safe='')}"
    path = state / "agent/agent-policies.json"
    path.write_text(
        json.dumps(
            {"schemaVersion": 1, "policies": {key: policy}},
            ensure_ascii=False,
            indent=2,
        )
    )
    path.chmod(0o600)


def adaptive_payload() -> dict:
    fixture = json.loads(
        (ROOT / "tests/fixtures/recording/math-analysis-discussion.json").read_text()
    )
    now = datetime.now(timezone.utc)
    scope = {
        "accountId": f"qq-{BOT_ID}",
        "conversationId": f"qq-{BOT_ID}:group:{GROUP_ID}",
    }
    messages = [
        {
            "id": f"recording-{index + 1}",
            "senderId": str(3_000_000_001 + fixture["members"].index(row["sender"])),
            "senderName": row["sender"],
            "content": row["text"],
            "timestamp": (now - timedelta(seconds=(20 - index) * 6)).isoformat(),
        }
        for index, row in enumerate(fixture["messages"])
    ]
    return {
        **scope,
        "prompt": messages[-1]["content"],
        "history": {
            **scope,
            "source": "synthetic",
            "truncated": False,
            "messages": messages,
        },
    }


def check_adaptive(result: dict) -> list[str]:
    issues = []
    data = result.get("data") or {}
    if data.get("messages") != 20 or data.get("participants") != 4:
        issues.append("需要完整的四人20条讨论")
    transitions = data.get("transitions", [])
    if any(row.get("activated") or row.get("replied") for row in transitions[:-1]):
        issues.append("第20条之前已启用或回复")
    if not transitions or "icourse.read" not in transitions[-1].get("activated", []):
        issues.append("第20条未自主启用评课社区")
    responses = data.get("responses", [])
    if len(responses) != 1 or responses[0].get("outcome") != "response":
        issues.append("未生成一次完整答复")
    else:
        reply = responses[0]
        if reply.get("toolCalls", 0) < 1 or not any(
            cap.startswith("icourse.") for cap in reply.get("capabilityIds", [])
        ):
            issues.append("没有实际调用评课社区")
        answer = reply.get("candidate", "")
        if "数学分析" not in answer or not re.search(
            r"(?:https?://)?icourse\.club/course/\d+(?:/|\b)", answer
        ):
            issues.append("回答缺少课程名称或来源")
        for name in ("小林", "小周", "小陈", "小许"):
            if name not in answer:
                issues.append(f"回答未明确回应{name}的需求")
    if data.get("outputCalls") != 0 or data.get("memoryWrites") != 0:
        issues.append("模拟出现了外部发送或记忆写入")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state", type=Path, default=ROOT.parent / "dududa-recording-state"
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:6186/api/v1")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.reset:
        reset_policy(args.state)
    key = (args.state / "secrets/astrbot_plugin_api_key").read_text().strip()
    response = httpx.post(
        args.api_url.rstrip("/")
        + "/plugins/extensions/astrbot_plugin_dududa_core/runtime/rehearsal",
        headers={"X-API-Key": key},
        json=adaptive_payload(),
        trust_env=False,
        timeout=240,
    )
    result = response.json()
    issues = check_adaptive(result)
    report = args.state / "reports/adaptive.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "httpStatus": response.status_code,
                "passed": not issues,
                "issues": issues,
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "httpStatus": response.status_code,
                "passed": not issues,
                "issues": issues,
                "report": str(report),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
