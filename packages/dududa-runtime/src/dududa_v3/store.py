from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import RUNTIME


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                  id INTEGER PRIMARY KEY, scope TEXT UNIQUE NOT NULL, thread_id TEXT);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, session_id INTEGER NOT NULL, message_id TEXT NOT NULL,
                  request TEXT NOT NULL, result TEXT NOT NULL,
                  UNIQUE(session_id, message_id));
                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, sender TEXT NOT NULL,
                  text TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS memories (
                  id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, owner TEXT NOT NULL,
                  text TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tool_calls (
                  id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deliveries (
                  run_id TEXT PRIMARY KEY, state TEXT NOT NULL, message_id TEXT);
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def session(self, scope: str) -> dict:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO sessions(scope) VALUES (?)", (scope,))
            return dict(db.execute("SELECT * FROM sessions WHERE scope=?", (scope,)).fetchone())

    def thread(self, session_id: int, thread_id: str | None) -> None:
        with self.connect() as db:
            db.execute("UPDATE sessions SET thread_id=? WHERE id=?", (thread_id, session_id))

    def create_run(self, session_id: int, request: dict) -> tuple[dict, bool]:
        run_id = str(uuid.uuid4())
        result = {"runtime": RUNTIME, "run_id": run_id, "status": "queued", "route": "ignore", "text": "",
                      "thread_id": None, "turn_id": None, "model": "", "tool_calls": 0, "events": [],
                      "created_at": datetime.now(timezone.utc).isoformat(), "latency_ms": 0}
        with self.connect() as db:
            inserted = db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?)",
                                  (run_id, session_id, request["message_id"], json.dumps(request), json.dumps(result))).rowcount
            row = db.execute("SELECT result FROM runs WHERE session_id=? AND message_id=?",
                             (session_id, request["message_id"])).fetchone()
        return json.loads(row[0]), bool(inserted)

    def get(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT result FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        return json.loads(row[0])

    def update(self, run_id: str, **changes) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT result FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            result = json.loads(row[0])
            result.update(changes)
            db.execute("UPDATE runs SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), run_id))
        return result

    def event(self, run_id: str, event: dict) -> None:
        current = self.get(run_id)
        self.update(run_id, events=(current["events"] + [event])[-200:])

    def recover(self) -> None:
        with self.connect() as db:
            rows = db.execute("SELECT id,result FROM runs").fetchall()
            # A process restart cannot establish whether an in-flight external
            # send succeeded. Keep its claim and expose the uncertain outcome.
            db.execute("UPDATE deliveries SET state='unknown' WHERE state='sending'")
        for row in rows:
            result = json.loads(row["result"])
            if result["status"] in ("queued", "running"):
                self.update(row["id"], status="failed", error="runtime_restarted: task was not replayed")

    def observe(self, session_id: int, sender: str, text: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO messages(session_id,sender,text,created_at) VALUES (?,?,?,?)",
                       (session_id, sender, text[:12000], time.time()))
            db.execute("DELETE FROM messages WHERE session_id=? AND id NOT IN "
                       "(SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 200)",
                       (session_id, session_id))

    def recent(self, session_id: int, limit: int = 12) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT sender,text,created_at FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                              (session_id, max(1, min(limit, 30)))).fetchall()
        return [dict(row) for row in reversed(rows)]

    def remember(self, session_id: int, owner: str, text: str) -> int:
        if not text.strip() or len(text) > 2000:
            raise ValueError("记忆内容必须为 1–2000 字符")
        with self.connect() as db:
            return db.execute("INSERT INTO memories(session_id,owner,text,created_at) VALUES (?,?,?,?)",
                              (session_id, owner, text, time.time())).lastrowid

    def memories(self, session_id: int, query: str = "") -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id,owner,text FROM memories WHERE session_id=? AND instr(text,?)>0 ORDER BY id DESC LIMIT 30",
                              (session_id, query)).fetchall()
        return [dict(row) for row in rows]

    def forget(self, session_id: int, owner: str, memory_id: int) -> bool:
        with self.connect() as db:
            return bool(db.execute("DELETE FROM memories WHERE session_id=? AND owner=? AND id=?",
                                   (session_id, owner, memory_id)).rowcount)

    def record_tool(self, run_id: str, name: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO tool_calls(run_id,name) VALUES (?,?)", (run_id, name))

    def tools(self, run_id: str) -> list[str]:
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT name FROM tool_calls WHERE run_id=? ORDER BY id", (run_id,))]

    def delivery(self, run_id: str, state: str, message_id: str | None = None) -> dict:
        if state not in ("sending", "sent", "unknown"):
            raise ValueError("Invalid delivery state")
        result = self.get(run_id)
        with self.connect() as db:
            request = json.loads(db.execute("SELECT request FROM runs WHERE id=?", (run_id,)).fetchone()[0])
            if request.get("preview") or result["status"] != "completed" or not result["text"]:
                raise ValueError("This run cannot be delivered")
            if state == "sending":
                claimed = bool(db.execute("INSERT OR IGNORE INTO deliveries VALUES (?,?,?)",
                                          (run_id, state, message_id)).rowcount)
            else:
                claimed = bool(db.execute("UPDATE deliveries SET state=?,message_id=? WHERE run_id=? AND state='sending'",
                                          (state, message_id, run_id)).rowcount)
            row = db.execute("SELECT state FROM deliveries WHERE run_id=?", (run_id,)).fetchone()
        return {"runtime": RUNTIME, "claimed": claimed, "state": row[0] if row else None}
