"""Live v3 acceptance: rules and real local Codex + native MCP, never v2."""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dududa_v3 import RUNTIME
from dududa_v3.codex import CodexClient
from dududa_v3.config import Settings
from dududa_v3.runtime import Runtime


async def verify(config: str | None) -> dict:
    settings = Settings.load(config)
    starts = []

    class ObservedCodex(CodexClient):
        def __init__(self, *args, **kwargs):
            starts.append(True)
            super().__init__(*args, **kwargs)

    report = {"runtime": RUNTIME, "verified_at": datetime.now(timezone.utc).isoformat(),
              "mode": "real-local-codex", "qq_messages_sent": 0, "cases": []}
    version = await asyncio.to_thread(subprocess.run, [settings.codex_binary, "--version"], check=True,
                                      capture_output=True, text=True, timeout=10)
    report["codex_version"] = version.stdout.strip()
    with tempfile.TemporaryDirectory(prefix="dududa-v3-acceptance-") as directory:
        settings.state_dir = Path(directory)
        runtime = Runtime(settings, ObservedCodex)
        async def run(text: str, **overrides) -> dict:
            request = {"account_id": "acceptance", "conversation_id": "qq:acceptance:private:owner",
                       "user_id": "owner", "message_id": str(uuid.uuid4()), "text": text,
                       "source": "web", "mentioned": True, **overrides}
            submitted = await runtime.submit(request)
            result = await runtime.wait(submitted["run_id"])
            assert result["runtime"] == RUNTIME and result["status"] == "completed", result
            return result
        try:
            ping = await run("/ping")
            assert ping["route"] == "rule" and not starts and not ping["thread_id"]
            report["cases"].append({"name": "rules-without-llm", "passed": True, "run_id": ping["run_id"]})
            shuttle = await run("/校车 工作日东区到西区最早一班")
            assert shuttle["route"] == "rule" and not starts and "dataset_id" in shuttle["text"]
            report["cases"].append({"name": "shared-shuttle-rule", "passed": True})
            marker = "蓝莓星球" + uuid.uuid4().hex[:8]
            await run("/remember 本次验收标记是" + marker)
            query = await run("请先调用 memory_search 查询本次验收标记，再调用 shuttle_query 查询工作日东区到西区最早一班。"
                              "必须实际调用这两个工具，最后简短报告验收标记和查询结果。")
            assert query["route"] == "agent" and marker in query["text"], query
            assert {"memory_search", "shuttle_query"} <= set(query["tools"]), query
            report["cases"].append({"name": "real-codex-multiple-mcp-tools", "passed": True,
                                    "thread_id": query["thread_id"], "turn_id": query["turn_id"],
                                    "model": query["model"], "tools": query["tools"], "latency_ms": query["latency_ms"]})
            await runtime.close()
            runtime = Runtime(settings, ObservedCodex)
            resumed = await run("继续上一次对话。仅用一行复述刚才的验收标记，不要重新查询。")
            assert resumed["thread_id"] == query["thread_id"] and marker in resumed["text"], resumed
            assert len(starts) == 2
            report["cases"].append({"name": "persisted-thread-resume", "passed": True,
                                    "thread_id": resumed["thread_id"], "turn_id": resumed["turn_id"],
                                    "latency_ms": resumed["latency_ms"]})
            isolated = await run("/memory", conversation_id="qq:acceptance:private:another")
            assert marker not in isolated["text"]
            preview = await run("/remember 不应该保存", preview=True)
            with runtime.store.connect() as db:
                assert db.execute("SELECT count(*) FROM memories WHERE text='不应该保存'").fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 0
            assert "不写入" in preview["text"] and len(starts) == 2
            report["cases"].append({"name": "scope-and-preview-isolation", "passed": True})
            report["passed"] = True
            report["actual_codex_runs"] = len(starts)
        except (AssertionError, RuntimeError, ValueError, OSError, LookupError, TypeError) as error:
            report["passed"] = False
            report["error"] = str(error)
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
