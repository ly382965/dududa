"""Live v3 acceptance through the real local omp harness; never sends QQ messages."""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dududa_v3 import RUNTIME, VERSION
from dududa_v3.config import Settings
from dududa_v3.omp import OmpClient
from dududa_v3.runtime import Runtime

ACCOUNT = "qq-acceptance"
CONVERSATION = "qq-acceptance:private:owner"


async def verify(config: str | None) -> dict:
    settings = Settings.load(config)
    starts: list[Path | None] = []

    def observed_omp(**kwargs) -> OmpClient:
        starts.append(kwargs.get("session_dir"))
        return OmpClient(**kwargs)

    report = {"runtime": RUNTIME, "version": VERSION, "verified_at": datetime.now(timezone.utc).isoformat(),
              "mode": "real-local-omp", "qq_messages_sent": 0, "cases": []}
    version = await asyncio.to_thread(subprocess.run, [settings.omp_binary, "--version"], check=True,
                                      capture_output=True, text=True, timeout=30)
    report["omp_version"] = version.stdout.strip()
    with tempfile.TemporaryDirectory(prefix="dududa-v3-acceptance-") as directory:
        settings.state_dir = Path(directory)
        runtime = Runtime(settings, observed_omp)
        report["model"] = runtime.health()["model"]
        report["reasoning_effort"] = runtime.health()["reasoning_effort"]

        async def run(text: str) -> dict:
            request = {"account_id": ACCOUNT, "conversation_id": CONVERSATION, "user_id": "owner",
                       "message_id": str(uuid.uuid4()), "text": text, "source": "web", "mentioned": True,
                       "sender": {"nickname": "验收员", "role": "member"}}
            submitted = await runtime.submit(request)
            result = await runtime.wait(submitted["run_id"])
            assert result["runtime"] == RUNTIME and result["status"] == "completed", result
            return result

        def agent_case(name: str, result: dict) -> dict:
            return {"name": name, "passed": True, "run_id": result["run_id"], "thread_id": result["thread_id"],
                    "model": result["model"], "model_name": result.get("model_name"),
                    "reasoning_effort": result.get("reasoning_effort"), "tools": result.get("tools", []),
                    "usage": result.get("usage", {}), "latency_ms": result["latency_ms"], "text": result["text"]}

        try:
            ping = await run("/ping")
            clock = await run("时间")
            marker = "蓝莓星球" + uuid.uuid4().hex[:8]
            remembered = await run("/remember 本次验收标记是" + marker)
            assert all(item["route"] == "rule" and item["model"] == "rules" for item in (ping, clock, remembered))
            assert "上海" in clock["text"] and "已记住" in remembered["text"] and not starts, (clock, remembered)
            report["cases"].append({"name": "rules-without-llm", "passed": True,
                                    "replies": [ping["text"], clock["text"].splitlines()[0], remembered["text"]]})

            query = await run("请先调用 memory_search 查询本次验收标记，再调用 shuttle_query 查询工作日东区到西区最早一班。"
                              "必须实际调用这两个工具，最后简短报告验收标记和查询到的班次时间。")
            assert query["route"] == "agent" and marker in query["text"], query
            assert {"memory_search", "shuttle_query"} <= set(query["tools"]), query
            session_dir = starts[-1]
            assert session_dir is not None and any(session_dir.iterdir()), session_dir
            report["cases"].append(agent_case("agent-calls-two-host-tools", query))

            # A fresh Runtime proves continuity comes from the persisted omp session directory.
            await runtime.close()
            runtime = Runtime(settings, observed_omp)
            resumed = await run("继续上一轮对话：不要调用任何工具，只用一行复述你刚才报告的验收标记。")
            assert resumed["route"] == "agent" and resumed["thread_id"] == query["thread_id"], resumed
            assert starts[-1] == session_dir and len(starts) == 2, starts
            assert marker in resumed["text"], resumed
            report["cases"].append({**agent_case("same-session-continuity", resumed),
                                    "session_dir_reused": True})
            report["passed"] = True
            report["omp_runs"] = len(starts)
        except (AssertionError, RuntimeError, ValueError, OSError, LookupError, TypeError) as error:
            report["passed"] = False
            report["error"] = f"{type(error).__name__}: {str(error)[:2000]}"
        finally:
            await runtime.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--output", type=Path, default=Path("runtime/v3/verification.json"))
    args = parser.parse_args()
    report = asyncio.run(verify(args.config))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
