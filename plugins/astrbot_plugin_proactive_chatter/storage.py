from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any


class ChatterStore:
    """Persist group chat messages and derive per-user style statistics."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    nick TEXT,
                    text TEXT NOT NULL,
                    ts REAL NOT NULL
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_group_user ON messages(group_id, user_id, ts)")

    def add(self, group_id: str, user_id: str, nick: str | None, text: str, ts: float | None = None) -> None:
        text = (text or "").strip()
        if not text:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages(group_id, user_id, nick, text, ts) VALUES(?,?,?,?,?)",
                (group_id, user_id, nick, text, ts if ts is not None else time.time()),
            )
            # keep history bounded per group (avoid unbounded growth): keep last 3000
            conn.execute(
                """DELETE FROM messages WHERE id NOT IN (
                    SELECT id FROM messages WHERE group_id=? ORDER BY id DESC LIMIT 3000
                )""",
                (group_id,),
            )

    def prune_old(self, max_age_seconds: int = 86400 * 90) -> None:
        cutoff = time.time() - max_age_seconds
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))

    def recent_by_group(self, group_id: str, window_seconds: float, limit: int = 200) -> list[dict[str, Any]]:
        since = time.time() - window_seconds
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE group_id=? AND ts>=? ORDER BY id DESC LIMIT ?",
                (group_id, since, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_activity_count(self, group_id: str, window_seconds: float) -> int:
        since = time.time() - window_seconds
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE group_id=? AND ts>=?",
                (group_id, since),
            ).fetchone()
        return int(row["n"]) if row else 0

    def most_active_users(self, group_id: str, window_seconds: float, limit: int = 5) -> list[dict[str, Any]]:
        since = time.time() - window_seconds
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT user_id, nick, COUNT(*) AS cnt, MAX(ts) AS last_ts
                   FROM messages WHERE group_id=? AND ts>=?
                   GROUP BY user_id ORDER BY cnt DESC LIMIT ?""",
                (group_id, since, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def user_recent(self, group_id: str, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE group_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
                (group_id, user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def user_history_count(self, group_id: str, user_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            ).fetchone()
        return int(row["n"]) if row else 0

    @staticmethod
    def _tokens(text: str) -> list[str]:
        toks = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text.lower())
        stop = {
            "这个", "那个", "什么", "怎么", "就是", "一个", "我们", "你们", "他们",
            "真的", "觉得", "还是", "可以", "一下", "这些", "那些", "然后", "所以",
            "没有", "不是", "但是", "而且", "因为", "如果", "已经", "知道", "现在",
            "哈哈", "hhhh", "emm", "嗯", "的", "了", "吗", "吧", "呀", "呢", "啊",
        }
        return [t for t in toks if t not in stop and len(t) >= 2]

    def style_stats(self, group_id: str, user_id: str, sample_limit: int = 300) -> dict[str, Any]:
        """Summarize a user's recent chat style from up to ~300 messages."""
        rows = self.user_recent(group_id, user_id, sample_limit)
        if not rows:
            return {}
        texts = [r["text"] for r in rows]
        joined = "\n".join(texts)
        tokens = Counter()
        for t in texts:
            tokens.update(self._tokens(t))
        top_words = [w for w, _ in tokens.most_common(12)]
        length = sum(len(t) for t in texts) / max(1, len(texts))
        emoji_count = sum(t.count("😂") + t.count("😅") + t.count("😭") + t.count("🤣")
                          + t.count("👍") + t.count("❤️") + t.count("🥰") for t in texts)
        has_emoji = emoji_count / max(1, len(texts)) > 0.05
        # detect common sentence-final particles /口头禅 candidates
        particle_counts: Counter[str] = Counter()
        for t in texts:
            for p in ["吧", "呀", "呢", "啊", "哈", "嗯嗯", "对呀", "真的", "笑了"]:
                if p in t:
                    particle_counts[p] += 1
        catchphrases = [p for p, c in particle_counts.most_common(5) if c >= max(2, len(texts) * 0.08)]
        return {
            "nick": rows[0].get("nick") or "",
            "sample_count": len(rows),
            "style": {
                "length_hint": "简短" if length < 20 else ("中等" if length < 60 else "较长"),
                "uses_emoji": has_emoji,
                "top_words": top_words,
                "catchphrases": catchphrases,
            },
            "recent_sample": texts[:30],
        }
