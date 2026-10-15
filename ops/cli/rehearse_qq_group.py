"""Replay the fixed discussion as native inputs for a logged-in QQ account."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--platform-id", default="test")
    parser.add_argument("--web-url", default="http://127.0.0.1:5173")
    parser.add_argument("--api-url", default="http://127.0.0.1:6185/api/v1")
    parser.add_argument(
        "--key-file",
        type=Path,
        default=ROOT / "runtime/web/secrets/astrbot_plugin_api_key",
    )
    parser.add_argument(
        "--deliver",
        action="store_true",
        help="Allow the normal Runtime to reply in this QQ group",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Set this group to iCourse off, adaptive on, and wait for 20 messages",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT.parent / "dududa-recording-state/reports/native-result.json",
    )
    args = parser.parse_args()
    scope = {
        "accountId": f"qq-{args.bot_id}",
        "conversationId": f"qq-{args.bot_id}:group:{args.group_id}",
    }
    fixture = json.loads(
        (ROOT / "tests/fixtures/recording/math-analysis-discussion.json").read_text()
    )
    with httpx.Client(trust_env=False, timeout=30) as web:
        response = web.get(
            args.web_url
            + "/api/accounts/"
            + scope["accountId"]
            + "/groups/"
            + args.group_id
            + "/members"
        )
        response.raise_for_status()
        members = response.json()["members"]
        ids = {}
        for name in fixture["members"]:
            matches = [
                m for m in members if (m.get("card") or m.get("nickname") or "") == name
            ]
            if not matches:
                matches = [
                    m
                    for m in members
                    if (m.get("card") or m.get("nickname") or "").startswith(name)
                ]
            if len(matches) != 1:
                raise ValueError(f"Cannot uniquely match group member: {name}")
            ids[name] = matches[0]["userId"]
        if args.reset:
            response = web.get(args.web_url + "/api/agent/config", params=scope)
            response.raise_for_status()
            policy = response.json()
            policy["plugins"].update(
                {"icourse.read": "auto", "social.proactive_talk": "on"}
            )
            policy["adaptivePlugins"] = ["icourse.read"]
            policy.pop("activePlugins", None)
            policy["proactiveTalk"] = {
                "probabilityPercent": 100,
                "cooldownSeconds": 5,
                "maximumPerHour": 3,
                "minimumMessages": 20,
            }
            response = web.put(
                args.web_url + "/api/agent/config",
                json={"scope": scope, "policy": policy},
                headers={"Origin": args.web_url},
            )
            response.raise_for_status()
    base = int(time.time() * 1000)
    messages = [
        {
            "id": str(base + i),
            "senderId": ids[row["sender"]],
            "senderName": row["sender"],
            "content": row["text"],
        }
        for i, row in enumerate(fixture["messages"])
    ]
    payload = {
        **scope,
        "platformId": args.platform_id,
        "inputMode": "onebot",
        "deliver": args.deliver,
        "prompt": messages[-1]["content"],
        "history": {
            **scope,
            "source": "synthetic",
            "truncated": False,
            "messages": messages,
        },
    }
    with httpx.Client(
        trust_env=False,
        timeout=600,
        headers={"X-API-Key": args.key_file.read_text().strip()},
    ) as client:
        response = client.post(
            args.api_url
            + "/plugins/extensions/astrbot_plugin_dududa_core/runtime/rehearsal",
            json=payload,
        )
        response.raise_for_status()
        result = response.json()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    data = result.get("data") or {}
    print(
        json.dumps(
            {
                "report": str(args.output),
                "mode": data.get("mode"),
                "messages": data.get("messages"),
                "activations": data.get("adaptiveActivations"),
                "outputCalls": data.get("outputCalls"),
                "deliveries": data.get("deliveries"),
            },
            ensure_ascii=False,
        )
    )
    return (
        0
        if data.get("responses") and data["responses"][0]["outcome"] == "response"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
