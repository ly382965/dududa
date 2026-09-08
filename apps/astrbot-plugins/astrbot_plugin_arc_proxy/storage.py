from __future__ import annotations

import sqlite3
from pathlib import Path


class BindingStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bindings (
                    user_id TEXT PRIMARY KEY,
                    friend_code TEXT NOT NULL
                )
                """
            )

    def set(self, user_id: str, friend_code: str) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO bindings(user_id, friend_code) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET friend_code = excluded.friend_code
                """,
                (user_id, friend_code),
            )

    def get(self, user_id: str) -> str | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT friend_code FROM bindings WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return str(row[0]) if row else None
