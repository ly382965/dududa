"""Exercise the operator's 100-question table without sending any QQ messages.

The host's authenticated preview API accepts explicitly synthetic history. This
runner never fetches group history or changes policy. It records observations,
not a fabricated automatic semantic pass rate. Fault/proactive cases are covered
separately by isolated tests, never by interrupting production services.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "docs/operations/group-chat-100-questions.md"
ISOLATED = {
    93: "MCP timeout: isolated failure fixture only",
    94: "Model unavailable: isolated failure fixture only",
    95: "Duplicate native message: isolated replay fixture only",
    96: "Unmentioned message: isolated proactive policy fixture only",
    97: "Unmentioned incomplete context: isolated proactive fixture only",
    98: "Probability/cooldown/hourly limits: isolated clock and RNG fixture only",
    99: "After-delivery cooldown: isolated clock fixture only",
}


def questions(path: Path = TABLE) -> list[dict[str, object]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\| (\d+) \| (.*?) \| (.*?) \|", line)
        if match:
            rows.append({"id": int(match[1]), "question": match[2], "criterion": match[3]})
    if [row["id"] for row in rows] != list(range(1, 101)):
        raise ValueError("question_table_must_contain_ids_1_to_100")
    return rows


def synthetic_context(case_id: int, previous: dict[int, str], day: datetime):
    lines: list[tuple[str, str]] = [
        ("小林", "会议周五晚上七点开始。"),
        ("小林", "更正，会议改成周六晚上八点，原时间作废。"),
        ("小李", "我负责场地，周五下午五点前确认。"),
        ("小王", "我负责海报，周五中午十二点交初稿。"),
        ("小周", "复习方案 A 是线下自习，方案 B 是线上讨论。我赞成 B，不用通勤。"),
        ("小李", "我倾向方案 A，面对面更专注。还没决定选哪个。"),
        ("小王", "数学复习定在周六 14:00—15:30，英语讨论也暂定周六 15:00—16:00。"),
        ("小林", "报告还没交。聚餐可能周日晚，还没定。"),
        ("小周", "讨论室可以借投影仪吗？"),
        ("小王", "今天午饭吃了面条。"),
    ]
    prompt = None
    reply = None
    if case_id == 31:
        lines, prompt = lines[:1], "会议几点开始？"
    elif case_id == 32:
        lines, prompt = lines[:2], "最终几点开会？"
    elif case_id == 33:
        lines, prompt = [("小林", "小李负责场地，小王负责海报。")], "谁负责海报？"
    elif case_id == 34:
        lines, prompt = lines[4:6], "你觉得后一个更适合吗？"
    elif case_id == 35:
        lines = [("小林", "周六晚上开会。"), ("小王", "周日下午聚餐。")]
        prompt = "那个安排取消了吗？"
    elif case_id == 36:
        lines = [("小林", "方案是先各自复习数学一小时，再线上讨论错题半小时。")]
        prompt, reply = "把我引用的这条方案压缩成一句话。", "synthetic-1"
    elif case_id == 37:
        lines, prompt, reply = lines[:2], "我引用的这个信息现在还有效吗？", "synthetic-1"
    elif case_id == 38:
        lines, prompt = [("小林", "报告还没交。")], "所以报告已经交了吗？"
    elif case_id == 39:
        lines, prompt = [("小林", "可能周日晚聚餐，还没定。")], "聚餐确定在什么时候？"
    elif case_id == 54:
        lines = [("小林", "想查一场二课活动，但还没有选定活动。")]
    elif case_id == 58:
        lines = [("小林", "想了解计算机专业培养方案，但还没有确定年级和版本。")]
    elif case_id == 80:
        lines = [("嘟嘟哒", previous[79][:2000])] if previous.get(79) else []
    elif case_id == 90:
        lines = [("嘟嘟哒", previous[89][:2000])] if previous.get(89) else []
    elif not (21 <= case_id <= 40 or case_id == 100):
        lines = []
    messages = [
        {
            "id": f"synthetic-{i + 1}", "senderId": f"synthetic-user-{name}",
            "senderName": name, "content": content,
            "timestamp": (day + timedelta(minutes=i)).isoformat(),
        }
        for i, (name, content) in enumerate(lines)
    ]
    # An explicit quoted fixture, not a fabricated native QQ reply or lookup.
    if reply:
        prompt += f" 引用原文：『{lines[0][1]}』"
    return messages, prompt


def selected_ids(value: str) -> set[int]:
    result: set[int] = set()
    for part in value.split(","):
        if "-" in part:
            first, last = map(int, part.split("-", 1))
            result.update(range(first, last + 1))
        else:
            result.add(int(part))
    if not result or not result <= set(range(1, 101)):
        raise ValueError("invalid_case_selection")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=TABLE)
    parser.add_argument("--cases", default="1-100")
    parser.add_argument("--base-url", default="http://127.0.0.1:6185/api/v1")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--account-id")
    parser.add_argument("--conversation-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    chosen = selected_ids(args.cases)
    rows = [row for row in questions(args.questions) if row["id"] in chosen]
    if not args.execute:
        print(json.dumps({"mode": "plan_only", "cases": rows, "isolated": ISOLATED}, ensure_ascii=False))
        return 0
    parsed = urlparse(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("The credential-bearing runner only accepts the local private host API")
    if not all((args.api_key_file, args.account_id, args.conversation_id, args.output)):
        parser.error("execution requires credential file, explicit scope and output path")
    if args.output.exists():
        parser.error("output already exists; choose a new batch path")
    api_key = args.api_key_file.read_text(encoding="utf-8").strip()
    if not api_key:
        parser.error("credential file is empty")
    day = datetime.now(timezone(timedelta(hours=8))).replace(hour=10, minute=0, second=0, microsecond=0)
    previous: dict[int, str] = {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Each completed row is durable. Never record credentials, headers, group IDs,
    # real history, raw exception text or a whole HTTP error response.
    with args.output.open("x", encoding="utf-8") as output, httpx.Client(timeout=125, trust_env=False) as client:
        args.output.chmod(0o600)
        for row in rows:
            case_id = int(row["id"])
            record = {**row, "mode": "synthetic_host_preview", "review": "needs_semantic_review"}
            if case_id in ISOLATED:
                record.update(mode="isolated_test_required", note=ISOLATED[case_id])
            else:
                messages, prompt = synthetic_context(case_id, previous, day)
                payload = {
                    "accountId": args.account_id, "conversationId": args.conversation_id,
                    "prompt": prompt or row["question"],
                    "history": {"accountId": args.account_id, "conversationId": args.conversation_id,
                                "source": "synthetic", "truncated": True, "messages": messages},
                }
                started = time.monotonic()
                try:
                    response = client.post(
                        args.base_url.rstrip("/") + "/plugins/extensions/astrbot_plugin_dududa_core/runtime/preview",
                        headers={"X-API-Key": api_key}, json=payload,
                    )
                    record["http"] = response.status_code
                    envelope = response.json()
                    data = envelope.get("data")
                    if response.is_success and envelope.get("status") != "error" and isinstance(data, dict):
                        record.update({key: data.get(key) for key in (
                            "candidate", "tier", "model", "reasoning", "reasonCodes", "outcome",
                            "runtimeState", "generationObserved", "coverage", "messagesRead",
                            "toolCalls", "capabilityIds", "outputCalls", "memoryWrites",
                        )})
                        if data.get("outputCalls") != 0 or data.get("memoryWrites") != 0:
                            raise RuntimeError("no_send_contract_violated")
                        previous[case_id] = str(data.get("candidate") or "")
                    else:
                        record["review"] = "request_failed"
                except (httpx.HTTPError, ValueError) as exc:
                    record.update(review="request_failed", errorType=type(exc).__name__)
                record["latencyMs"] = round((time.monotonic() - started) * 1000)
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            print(json.dumps({"case": case_id, "mode": record["mode"], "http": record.get("http"),
                              "outcome": record.get("outcome"), "latencyMs": record.get("latencyMs")}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
