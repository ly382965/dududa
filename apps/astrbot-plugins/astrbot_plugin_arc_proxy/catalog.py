from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SIDE_NAMES = {
    0: "Light",
    1: "Conflict",
    2: "Colorless",
    3: "Lephon",
    4: "DarkLephon",
}


@dataclass(frozen=True, slots=True)
class ChartInfo:
    rating_class: int
    constant: float
    note_count: int
    chart_designer: str


@dataclass(frozen=True, slots=True)
class SongInfo:
    song_id: str
    idx: int
    title: str
    artist: str
    bpm: str
    side: str
    version: str
    release_date: str
    pack: str
    cover_path: Path
    charts: tuple[ChartInfo, ...]


def normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def title_initialism(value: str) -> str:
    initials = []
    for word in value.split():
        initial = next((character for character in word if character.isalnum()), "")
        if initial:
            initials.append(initial)
    if len(initials) < 2:
        return ""
    return normalize_alias("".join(initials))


def format_song_info(song: SongInfo) -> str:
    constants = " / ".join(f"{chart.constant:.1f}" for chart in song.charts)
    notes = " / ".join(str(chart.note_count) for chart in song.charts)
    designers = [chart.chart_designer for chart in song.charts]
    designer_text = designers[0] if len(set(designers)) == 1 else " / ".join(designers)
    return "\n".join(
        (
            f"曲目：{song.title}",
            f"曲目ID：{song.song_id} [IDX:{song.idx}]",
            f"难度：{constants}",
            f"物量：{notes}",
            f"谱面设计：{designer_text}",
            f"曲侧：{song.side}",
            f"艺术家：{song.artist}",
            f"BPM：{song.bpm}",
            f"版本：{song.version}",
            f"上线日期：{song.release_date}",
            f"曲包：{song.pack}",
        )
    )


class SongStore:
    def __init__(self, path: Path, assets_root: Path, data_root: Path):
        self.path = path
        self.assets_root = assets_root
        self.data_root = data_root
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rebuild()

    def rebuild(self) -> None:
        songlist = self._read_json(self.assets_root / "songlist")
        packlist = self._read_json(self.assets_root / "packlist")
        base_stats = self._read_json(self.data_root / "chart_stats_base.json")
        overrides = self._read_json(self.data_root / "chart_overrides.json")
        base_aliases = self._read_json(self.data_root / "aliases_base.json")
        extra_aliases = self._read_json(self.data_root / "extra_aliases.json")

        stats = self._merge_stats(base_stats, overrides)
        aliases = {item["id"]: list(item.get("alias", [])) for item in base_aliases}
        for song_id, values in extra_aliases.items():
            aliases.setdefault(song_id, []).extend(values)

        packs = {item["id"]: item for item in packlist["packs"]}
        with sqlite3.connect(self.path) as connection:
            self._create_schema(connection)
            connection.execute("DELETE FROM initialisms")
            connection.execute("DELETE FROM aliases")
            connection.execute("DELETE FROM charts")
            connection.execute("DELETE FROM songs")

            for song in songlist["songs"]:
                difficulties = song.get("difficulties")
                if not difficulties:
                    continue
                song_id = song["id"]
                title = self._localized_text(song.get("title_localized", {}))
                cover_file = self._cover_file(song_id)
                connection.execute(
                    """
                    INSERT INTO songs(
                        song_id, idx, title, artist, bpm, side, version,
                        release_date, pack, cover_file
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        song_id,
                        int(song["idx"]),
                        title,
                        str(song.get("artist", "")),
                        self._format_bpm(song),
                        SIDE_NAMES[int(song.get("side", 0))],
                        str(song.get("version", "")),
                        datetime.fromtimestamp(
                            int(song["date"]), timezone.utc
                        ).strftime("%Y-%m-%d"),
                        self._pack_name(str(song.get("set", "")), packs),
                        cover_file,
                    ),
                )

                song_stats = stats[song_id]
                for difficulty in sorted(
                    difficulties,
                    key=lambda item: int(item["ratingClass"]),
                ):
                    rating_class = int(difficulty["ratingClass"])
                    chart_stats = song_stats.get(str(rating_class))
                    if chart_stats is None:
                        continue
                    connection.execute(
                        """
                        INSERT INTO charts(
                            song_id, rating_class, constant, note_count,
                            chart_designer
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            song_id,
                            rating_class,
                            float(chart_stats["constant"]),
                            int(chart_stats["notes"]),
                            str(difficulty.get("chartDesigner", "-")) or "-",
                        ),
                    )

                song_aliases = {
                    song_id,
                    str(song["idx"]),
                    *self._strings(song.get("title_localized", {})),
                    *self._strings(song.get("search_title", {})),
                    *aliases.get(song_id, []),
                }
                for alias in song_aliases:
                    alias_key = normalize_alias(alias)
                    if alias_key:
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO aliases(alias_key, alias, song_id)
                            VALUES (?, ?, ?)
                            """,
                            (alias_key, alias, song_id),
                        )
                if initialism := title_initialism(title):
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO initialisms(alias_key, song_id)
                        VALUES (?, ?)
                        """,
                        (initialism, song_id),
                    )

    def search(self, query: str, limit: int = 6) -> list[SongInfo]:
        alias_key = normalize_alias(query)
        if not alias_key:
            return []
        song_ids = self._search_ids("a.alias_key = ?", (alias_key,), limit)
        if not song_ids:
            song_ids = self._search_initialism_ids(alias_key, limit)
        if not song_ids:
            song_ids = self._search_ids(
                "a.alias_key LIKE ?",
                (f"{alias_key}%",),
                limit,
            )
        if not song_ids:
            song_ids = self._search_ids(
                "a.alias_key LIKE ?",
                (f"%{alias_key}%",),
                limit,
            )
        return [self.get(song_id) for song_id in song_ids]

    def get(self, song_id: str) -> SongInfo:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            song = connection.execute(
                "SELECT * FROM songs WHERE song_id = ?",
                (song_id,),
            ).fetchone()
            if song is None:
                raise KeyError(song_id)
            charts = connection.execute(
                """
                SELECT * FROM charts
                WHERE song_id = ?
                ORDER BY rating_class
                """,
                (song_id,),
            ).fetchall()
        return SongInfo(
            song_id=str(song["song_id"]),
            idx=int(song["idx"]),
            title=str(song["title"]),
            artist=str(song["artist"]),
            bpm=str(song["bpm"]),
            side=str(song["side"]),
            version=str(song["version"]),
            release_date=str(song["release_date"]),
            pack=str(song["pack"]),
            cover_path=self.assets_root / song_id / str(song["cover_file"]),
            charts=tuple(
                ChartInfo(
                    rating_class=int(chart["rating_class"]),
                    constant=float(chart["constant"]),
                    note_count=int(chart["note_count"]),
                    chart_designer=str(chart["chart_designer"]),
                )
                for chart in charts
            ),
        )

    def counts(self) -> tuple[int, int]:
        with sqlite3.connect(self.path) as connection:
            songs = connection.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
            charts = connection.execute("SELECT COUNT(*) FROM charts").fetchone()[0]
        return int(songs), int(charts)

    def _search_ids(
        self,
        predicate: str,
        parameters: tuple[str, ...],
        limit: int,
    ) -> list[str]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT s.song_id, s.idx
                FROM aliases AS a
                JOIN songs AS s ON s.song_id = a.song_id
                WHERE {predicate}
                ORDER BY s.idx
                LIMIT ?
                """,
                (*parameters, limit),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def _search_initialism_ids(self, alias_key: str, limit: int) -> list[str]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT s.song_id
                FROM initialisms AS i
                JOIN songs AS s ON s.song_id = i.song_id
                WHERE i.alias_key = ?
                ORDER BY s.idx
                LIMIT ?
                """,
                (alias_key, limit),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def _cover_file(self, song_id: str) -> str:
        song_root = self.assets_root / song_id
        for name in (
            "1080_base_256.jpg",
            "base_256.jpg",
            "1080_base.jpg",
            "base.jpg",
        ):
            if (song_root / name).is_file():
                return name
        raise FileNotFoundError(f"missing cover for {song_id}")

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS songs (
                song_id TEXT PRIMARY KEY,
                idx INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                bpm TEXT NOT NULL,
                side TEXT NOT NULL,
                version TEXT NOT NULL,
                release_date TEXT NOT NULL,
                pack TEXT NOT NULL,
                cover_file TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS charts (
                song_id TEXT NOT NULL,
                rating_class INTEGER NOT NULL,
                constant REAL NOT NULL,
                note_count INTEGER NOT NULL,
                chart_designer TEXT NOT NULL,
                PRIMARY KEY(song_id, rating_class),
                FOREIGN KEY(song_id) REFERENCES songs(song_id)
            );
            CREATE TABLE IF NOT EXISTS aliases (
                alias_key TEXT NOT NULL,
                alias TEXT NOT NULL,
                song_id TEXT NOT NULL,
                PRIMARY KEY(alias_key, song_id),
                FOREIGN KEY(song_id) REFERENCES songs(song_id)
            );
            CREATE TABLE IF NOT EXISTS initialisms (
                alias_key TEXT NOT NULL,
                song_id TEXT NOT NULL,
                PRIMARY KEY(alias_key, song_id),
                FOREIGN KEY(song_id) REFERENCES songs(song_id)
            );
            CREATE INDEX IF NOT EXISTS aliases_song_id_idx ON aliases(song_id);
            """
        )

    @staticmethod
    def _merge_stats(base_stats: list[dict], overrides: dict) -> dict:
        merged: dict[str, dict[str, dict[str, float | int]]] = {}
        for song in base_stats:
            charts = {
                str(index): dict(chart)
                for index, chart in enumerate(song["charts"])
                if chart is not None
            }
            merged[str(song["id"])] = charts
        for song_id, charts in overrides.items():
            target = merged.setdefault(song_id, {})
            for rating_class, values in charts.items():
                target[rating_class] = dict(values)
        return merged

    @staticmethod
    def _pack_name(set_id: str, packs: dict[str, dict]) -> str:
        if set_id == "single":
            return "Memory Archive"
        pack = packs[set_id]
        name = SongStore._localized_text(pack.get("name_localized", {}))
        parent_id = pack.get("pack_parent")
        if parent_id:
            parent = packs[str(parent_id)]
            parent_name = SongStore._localized_text(parent.get("name_localized", {}))
            return f"{name} ({parent_name})"
        return name

    @staticmethod
    def _format_bpm(song: dict) -> str:
        bpm = str(song.get("bpm", ""))
        if "-" not in bpm:
            return bpm
        base = float(song["bpm_base"])
        base_text = str(int(base)) if base.is_integer() else str(base)
        return f"{bpm} (Base {base_text})"

    @staticmethod
    def _localized_text(value: dict) -> str:
        if value.get("en"):
            return str(value["en"])
        if value.get("zh-Hans"):
            return str(value["zh-Hans"])
        return str(next(iter(value.values()), ""))

    @staticmethod
    def _strings(value: Any) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from SongStore._strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from SongStore._strings(item)

    @staticmethod
    def _read_json(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))
