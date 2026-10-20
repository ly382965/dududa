from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
                CREATE TABLE IF NOT EXISTS switches (
                  task TEXT PRIMARY KEY, enabled INTEGER NOT NULL, updated_by TEXT, updated_at REAL);
                CREATE TABLE IF NOT EXISTS model_bindings (
                  target TEXT PRIMARY KEY, name TEXT NOT NULL, updated_by TEXT, updated_at REAL);
                CREATE TABLE IF NOT EXISTS kv (
                  feature TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, updated_at REAL NOT NULL,
                  PRIMARY KEY(feature, key));
                CREATE TABLE IF NOT EXISTS outbox (
                  id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                  actions TEXT NOT NULL, state TEXT NOT NULL, dedupe TEXT UNIQUE,
                  created_at REAL NOT NULL, updated_at REAL NOT NULL, message_id TEXT);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
            if "profile" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN profile TEXT")
            if "context_mark" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN context_mark TEXT")
            columns = {row[1] for row in db.execute("PRAGMA table_info(messages)")}
            for name in ("sender_name", "message_id"):
                if name not in columns:
                    db.execute(f"ALTER TABLE messages ADD COLUMN {name} TEXT")
            if "bot" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN bot INTEGER NOT NULL DEFAULT 0")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    # ------------------------------------------------------------ sessions and runs

    def session(self, scope: str) -> dict:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO sessions(scope) VALUES (?)", (scope,))
            return dict(db.execute("SELECT * FROM sessions WHERE scope=?", (scope,)).fetchone())

    def thread(self, session_id: int, thread_id: str | None, profile: str | None = None) -> None:
        """Bind the session's agent conversation; ``None`` starts a fresh one."""
        with self.connect() as db:
            db.execute("UPDATE sessions SET thread_id=?,profile=?,context_mark=NULL WHERE id=?",
                       (thread_id, profile, session_id))

    def context_mark(self, session_id: int, mark: str | None) -> None:
        with self.connect() as db:
            db.execute("UPDATE sessions SET context_mark=? WHERE id=?", (mark, session_id))

    def create_run(self, session_id: int, request: dict) -> tuple[dict, bool]:
        run_id = str(uuid.uuid4())
        result = {"runtime": RUNTIME, "run_id": run_id, "status": "queued", "route": "ignore", "text": "",
                  "actions": [], "thread_id": None, "turn_id": None, "model": "", "tool_calls": 0, "events": [],
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

    def request(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT request FROM runs WHERE id=?", (run_id,)).fetchone()
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
            rows = db.execute("SELECT id,result FROM runs WHERE result LIKE '%\"status\": \"queued\"%' "
                              "OR result LIKE '%\"status\": \"running\"%'").fetchall()
            # A process restart cannot establish whether an in-flight external
            # send succeeded. Keep its claim and expose the uncertain outcome.
            db.execute("UPDATE deliveries SET state='unknown' WHERE state='sending'")
            db.execute("UPDATE outbox SET state='unknown' WHERE state='sending'")
        for row in rows:
            result = json.loads(row["result"])
            if result["status"] in ("queued", "running"):
                self.update(row["id"], status="failed", error="runtime_restarted: task was not replayed")

    # ------------------------------------------------------------ local message log

    def observe(self, session_id: int, sender: str, text: str, *, sender_name: str = "",
                message_id: str | None = None, bot: bool = False) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO messages(session_id,sender,text,created_at,sender_name,message_id,bot) "
                       "VALUES (?,?,?,?,?,?,?)",
                       (session_id, sender, text[:12000], time.time(), sender_name[:120], message_id, int(bot)))
            db.execute("DELETE FROM messages WHERE session_id=? AND id NOT IN "
                       "(SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 200)",
                       (session_id, session_id))

    def recent(self, session_id: int, limit: int = 12) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT sender,sender_name,text,created_at,message_id,bot FROM messages "
                              "WHERE session_id=? ORDER BY id DESC LIMIT ?",
                              (session_id, max(1, min(limit, 30)))).fetchall()
        return [dict(row) for row in reversed(rows)]

    # ------------------------------------------------------------ memories and tools

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

    # ------------------------------------------------------------ deliveries

    def delivery(self, run_id: str, state: str, message_id: str | None = None) -> dict:
        if state not in ("sending", "sent", "unknown"):
            raise ValueError("Invalid delivery state")
        result = self.get(run_id)
        with self.connect() as db:
            row = db.execute("SELECT session_id,request FROM runs WHERE id=?", (run_id,)).fetchone()
            request = json.loads(row["request"])
            if request.get("preview") or result["status"] != "completed" or not result.get("actions"):
                raise ValueError("This run cannot be delivered")
            if state == "sending":
                claimed = bool(db.execute("INSERT OR IGNORE INTO deliveries VALUES (?,?,?)",
                                          (run_id, state, message_id)).rowcount)
            else:
                claimed = bool(db.execute("UPDATE deliveries SET state=?,message_id=? WHERE run_id=? AND state='sending'",
                                          (state, message_id, run_id)).rowcount)
            delivered = db.execute("SELECT state FROM deliveries WHERE run_id=?", (run_id,)).fetchone()
        if state == "sent" and claimed and result.get("text"):
            self.observe(row["session_id"], request["account_id"].removeprefix("qq-"), result["text"],
                         sender_name="(bot)", message_id=message_id, bot=True)
        return {"runtime": RUNTIME, "claimed": claimed, "state": delivered[0] if delivered else None}

    # ------------------------------------------------------------ switches, models, kv

    def switches(self) -> dict[str, bool]:
        with self.connect() as db:
            return {row[0]: bool(row[1]) for row in db.execute("SELECT task,enabled FROM switches")}

    def set_switch(self, task: str, enabled: bool | None, user: str) -> None:
        with self.connect() as db:
            if enabled is None:
                db.execute("DELETE FROM switches WHERE task=?", (task,))
            else:
                db.execute("INSERT OR REPLACE INTO switches VALUES (?,?,?,?)", (task, int(enabled), user, time.time()))

    def model_bindings(self) -> dict[str, str]:
        with self.connect() as db:
            return {row[0]: row[1] for row in db.execute("SELECT target,name FROM model_bindings")}

    def bind_model(self, target: str, name: str | None, user: str) -> None:
        with self.connect() as db:
            if name is None:
                db.execute("DELETE FROM model_bindings WHERE target=?", (target,))
            else:
                db.execute("INSERT OR REPLACE INTO model_bindings VALUES (?,?,?,?)", (target, name, user, time.time()))

    def kv_get(self, feature: str, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value FROM kv WHERE feature=? AND key=?", (feature, key)).fetchone()
        return json.loads(row[0]) if row else default

    def kv_set(self, feature: str, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?,?)",
                       (feature, key, json.dumps(value, ensure_ascii=False), time.time()))

    # ------------------------------------------------------------ outbox

    def outbox_push(self, account_id: str, conversation_id: str, actions: list[dict], dedupe: str | None = None) -> bool:
        if not actions:
            raise ValueError("Outbox messages need at least one action")
        now = time.time()
        with self.connect() as db:
            return bool(db.execute(
                "INSERT OR IGNORE INTO outbox(account_id,conversation_id,actions,state,dedupe,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (account_id, conversation_id, json.dumps(actions, ensure_ascii=False), "pending", dedupe, now, now)).rowcount)

    def outbox_claim(self, limit: int = 10) -> list[dict]:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,account_id,conversation_id,actions FROM outbox WHERE state='pending' "
                              "ORDER BY id LIMIT ?", (max(1, min(limit, 50)),)).fetchall()
            for row in rows:
                db.execute("UPDATE outbox SET state='sending',updated_at=? WHERE id=?", (now, row["id"]))
        return [{"id": row["id"], "account_id": row["account_id"], "conversation_id": row["conversation_id"],
                 "actions": json.loads(row["actions"])} for row in rows]

    def outbox_result(self, item_id: int, state: str, message_id: str | None = None) -> bool:
        if state not in ("sent", "unknown"):
            raise ValueError("Invalid outbox state")
        with self.connect() as db:
            return bool(db.execute("UPDATE outbox SET state=?,message_id=?,updated_at=? WHERE id=? AND state='sending'",
                                   (state, message_id, time.time(), item_id)).rowcount)
