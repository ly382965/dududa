from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .catalog import ChartInfo, SongInfo

DIFFICULTY_NAMES = ("Past", "Present", "Future", "Beyond", "Eternal")
DIFFICULTY_ALIASES = {
    "pst": 0,
    "prs": 1,
    "ftr": 2,
    "byd": 3,
    "etr": 4,
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
}


class UnsupportedChartError(Exception):
    pass


def parse_chart_query(value: str) -> tuple[str, int | None] | None:
    value = value.strip()
    if not value:
        return None
    parts = value.rsplit(maxsplit=1)
    if len(parts) == 2:
        query, difficulty = parts
        if difficulty.casefold() in DIFFICULTY_ALIASES:
            return query, DIFFICULTY_ALIASES[difficulty.casefold()]
    return value, None


def resolve_rating_class(charts: Iterable[ChartInfo], requested: int | None) -> int:
    if requested is not None:
        return requested
    return max(chart.rating_class for chart in charts)


class ChartRenderer:
    def __init__(
        self,
        assets_root: Path,
        renderer_assets_root: Path,
        cache_root: Path,
    ) -> None:
        self.assets_root = assets_root
        self.renderer_assets_root = renderer_assets_root
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        songlist = json.loads((assets_root / "songlist").read_text(encoding="utf-8"))
        self._songs = {song["id"]: song for song in songlist["songs"]}
        self._render_lock = asyncio.Lock()

    async def render(self, song: SongInfo, chart: ChartInfo) -> Path:
        output_path = self.cache_root / f"{song.song_id}_{chart.rating_class}.jpg"
        if output_path.is_file():
            return output_path

        async with self._render_lock:
            if output_path.is_file():
                return output_path
            await asyncio.to_thread(self._render_sync, song, chart, output_path)
        return output_path

    def _render_sync(
        self,
        song: SongInfo,
        chart: ChartInfo,
        output_path: Path,
    ) -> None:
        song_data = dict(self._songs[song.song_id])
        difficulty = next(
            item
            for item in song_data["difficulties"]
            if int(item["ratingClass"]) == chart.rating_class
        )
        if difficulty.get("bg"):
            song_data["bg"] = difficulty["bg"]

        song_root = self.assets_root / song.song_id
        aff_path = song_root / f"{chart.rating_class}.aff"
        if not aff_path.is_file() and aff_path.with_suffix(".aff.pre").is_file():
            raise UnsupportedChartError(song.song_id)

        cover_path = self._cover_path(song_root, chart.rating_class, difficulty)
        Render, configure_assets, RenderSong = self._load_backend()
        configure_assets(self.renderer_assets_root)
        rendered = Render(
            aff_path=str(aff_path),
            cover_path=str(cover_path),
            song=RenderSong(**song_data),
            difficulty=chart.rating_class,
            constant=chart.constant,
        )
        rendered.im.convert("RGB").save(output_path, format="JPEG", quality=75)

    @staticmethod
    def _cover_path(
        song_root: Path,
        rating_class: int,
        difficulty: dict[str, Any],
    ) -> Path:
        stem = str(rating_class) if difficulty.get("jacketOverride") else "base"
        for name in (f"1080_{stem}.jpg", f"{stem}.jpg"):
            path = song_root / name
            if path.is_file():
                return path
        raise FileNotFoundError(f"missing cover for {song_root.name} [{rating_class}]")

    @staticmethod
    def _load_backend():
        prefix = f"{__package__}." if __package__ else ""
        package = importlib.import_module(f"{prefix}vendor.render.ArcaeaChartRender")
        model = importlib.import_module(
            f"{prefix}vendor.render.ArcaeaChartRender.model"
        )
        return package.Render, package.configure_assets, model.Song
