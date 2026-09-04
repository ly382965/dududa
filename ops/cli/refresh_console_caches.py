"""Operator-only bounded refresh of public MCP caches; never exposed as a tool."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = {
    "campus-events": ("events.sqlite3", "events", ["lists", "--refresh"]),
    "college-notice": ("notices.sqlite3", "notices", ["lists", "--refresh"]),
    "library": ("library.sqlite3", "hours", ["refresh"]),
    "training-plan": ("plans.sqlite3", "program_rows", ["refresh"]),
    "local-recs": ("local-recs.sqlite3", "recs", []),
}


def refresh(service: str, cache_root: Path) -> dict:
    filename, table, commands = SERVICES[service]
    service_root = ROOT / "services/mcp" / service
    db = cache_root / service / filename
    db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = dict(os.environ)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["PYTHONPATH"] = str(service_root / "src")
    module = service.replace("-", "_") + "_mcp"
    if service == "local-recs":
        env["PYTHONPATH"] += os.pathsep + str(service_root)
        command = [sys.executable, "-c", "from run_local_recs_mcp import auto_seed_if_empty; import sys; auto_seed_if_empty(sys.argv[1])", str(db)]
    else:
        command = [sys.executable, "-m", module + ".cli", "--db-path", str(db), "--timeout", "20", *commands]
    try:
        completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=150, check=False)
        if completed.returncode:
            return {"service": service, "ok": False, "error": "refresh_process_failed"}
        if commands and json.loads(completed.stdout).get("ok") is not True:
            return {"service": service, "ok": False, "error": "refresh_parse_failed"}
        with sqlite3.connect(db) as connection:
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return {"service": service, "ok": count > 0, "records": count, "sourceKind": "historical-curated" if service == "local-recs" else "official-public-cache"}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError, sqlite3.Error):
        return {"service": service, "ok": False, "error": "refresh_failed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--service", choices=SERVICES)
    args = parser.parse_args()
    if not args.cache_root.is_absolute():
        parser.error("cache-root must be absolute")
    results = [refresh(service, args.cache_root) for service in ([args.service] if args.service else SERVICES)]
    print(json.dumps({"results": results}), flush=True)
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
