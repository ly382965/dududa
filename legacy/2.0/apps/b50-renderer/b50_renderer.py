#!/usr/bin/env python3
"""Render an Arcaea Best 50 score sheet from TXT, CSV, or JSON input."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH = 1920
HEIGHT = 1750
DIFFICULTY_NAMES = {0: "PST", 1: "PRS", 2: "FTR", 3: "BYD", 4: "ETR"}
DIFFICULTY_INDEX = {name: index for index, name in DIFFICULTY_NAMES.items()}
DIFFICULTY_COLORS = {
    "PST": "#4F86B8",
    "PRS": "#4F956A",
    "FTR": "#B34F61",
    "BYD": "#7C315F",
    "ETR": "#6656A3",
}
CLEAR_TYPES = {0: "TL", 1: "NC", 2: "FR", 3: "PM", 4: "EC", 5: "HC"}
TXT_DETAIL_TOKEN = r"(?:FAR|LOST|SMALL[_ ]?P|小P)\s*[:=]?\s*\d+"
TXT_ENTRY = re.compile(
    r"(?P<title>.+?)\s+"
    r"\[(?P<difficulty>PST|PRS|FTR|BYD|ETR)\]\s+"
    r"(?P<constant>\d+(?:\.\d+)?)\s*:\s*"
    r"(?P<score>[\d',]+)\s*"
    r"\((?P<potential>\d+(?:\.\d+)?)\)"
    rf"(?P<details>(?:\s+{TXT_DETAIL_TOKEN})*)",
    re.IGNORECASE | re.DOTALL,
)
TXT_DETAIL = re.compile(
    r"(?P<key>FAR|LOST|SMALL[_ ]?P|小P)\s*[:=]?\s*(?P<value>\d+)",
    re.IGNORECASE,
)


@dataclass
class Song:
    song_id: str
    title: str
    jacket_overrides: set[str]


@dataclass
class ScoreRecord:
    title: str
    song_id: str
    difficulty: str
    constant: float
    score: int
    potential: float
    pure: int | None = None
    max_pure: int | None = None
    far: int | None = None
    lost: int | None = None
    small_pure: int | None = None
    clear_type: str = ""
    played_at: str = ""


@dataclass
class Player:
    name: str = "PLAYER"
    user_id: str = "-"


class SongCatalog:
    def __init__(self, assets_root: Path) -> None:
        self.assets_root = assets_root
        with (assets_root / "songlist").open("r", encoding="utf-8") as file:
            payload = json.load(file)

        self.by_id: dict[str, Song] = {}
        self.by_title: dict[str, Song] = {}
        self.by_relaxed_title: dict[str, Song] = {}

        for item in payload["songs"]:
            localized = item.get("title_localized", {})
            canonical = localized.get("en") or next(iter(localized.values()), item["id"])
            overrides = {
                difficulty_name(chart.get("ratingClass"))
                for chart in item.get("difficulties", [])
                if chart.get("jacketOverride")
            }
            song = Song(item["id"], canonical, overrides)
            self.by_id[song.song_id] = song

            aliases: list[str] = list(localized.values())
            for values in item.get("search_title", {}).values():
                aliases.extend(values)
            for alias in aliases:
                self.by_title.setdefault(normalize_title(alias), song)
                self.by_relaxed_title.setdefault(relaxed_title(alias), song)

    def find(self, title: str = "", song_id: str = "") -> Song | None:
        if song_id and song_id in self.by_id:
            return self.by_id[song_id]
        return self.by_title.get(normalize_title(title)) or self.by_relaxed_title.get(
            relaxed_title(title)
        )

    def jacket_path(self, song: Song | None, difficulty: str) -> Path | None:
        if song is None:
            return None

        folder = self.assets_root / song.song_id
        index = DIFFICULTY_INDEX[difficulty]
        if difficulty in song.jacket_overrides:
            names = [
                f"1080_{index}_256.jpg",
                f"{index}_256.jpg",
                f"1080_{index}.jpg",
                f"{index}.jpg",
            ]
        else:
            names = ["1080_base_256.jpg", "base_256.jpg", "1080_base.jpg", "base.jpg"]

        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return candidate

        return None


class FontBook:
    def __init__(self, font_dir: Path) -> None:
        cjk_font = font_dir / "NotoSansCJKsc-Regular.otf"
        if not cjk_font.is_file():
            candidates = [
                Path(value)
                for value in (
                    os.environ.get("DUDUDA_B50_CJK_FONT", ""),
                    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
                    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                )
                if value
            ]
            cjk_font = next(
                (candidate for candidate in candidates if candidate.is_file()),
                font_dir / "NotoSans-Regular.ttf",
            )
        self.paths = {
            "regular": font_dir / "Exo-Regular.ttf",
            "semibold": font_dir / "Exo-SemiBold.ttf",
            "latin_text": font_dir / "NotoSans-Regular.ttf",
            "text": cjk_font,
        }
        self.cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def get(self, family: str, size: int) -> ImageFont.FreeTypeFont:
        key = (family, size)
        if key not in self.cache:
            self.cache[key] = ImageFont.truetype(str(self.paths[family]), size)
        return self.cache[key]

    def title(self, value: str, size: int) -> ImageFont.FreeTypeFont:
        family = "latin_text" if contains_subscript(value) else "text"
        return self.get(family, size)


def resource_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / name


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def relaxed_title(value: str) -> str:
    return "".join(character for character in normalize_title(value) if character.isalnum())


def contains_subscript(value: str) -> bool:
    return any("\u2080" <= character <= "\u209f" for character in value)


def difficulty_name(value: Any) -> str:
    if isinstance(value, str) and value.upper() in DIFFICULTY_INDEX:
        return value.upper()
    return DIFFICULTY_NAMES[int(value)]


def integer(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def small_pure_count(pure: int | None, max_pure: int | None) -> int | None:
    if pure is None or max_pure is None:
        return None
    return pure - max_pure


def parse_txt(path: Path, catalog: SongCatalog) -> tuple[list[ScoreRecord], Player]:
    text = path.read_text(encoding="utf-8-sig").strip()
    records: list[ScoreRecord] = []
    for match in TXT_ENTRY.finditer(text):
        title = " ".join(match.group("title").split())
        song = catalog.find(title=title)
        details = {
            detail.group("key").upper().replace("_", "").replace(" ", ""): int(
                detail.group("value")
            )
            for detail in TXT_DETAIL.finditer(match.group("details"))
        }
        records.append(
            ScoreRecord(
                title=song.title if song else title,
                song_id=song.song_id if song else "",
                difficulty=match.group("difficulty").upper(),
                constant=float(match.group("constant")),
                score=int(re.sub(r"\D", "", match.group("score"))),
                potential=float(match.group("potential")) + 0.2,
                far=details.get("FAR"),
                lost=details.get("LOST"),
                small_pure=details.get("小P", details.get("SMALLP")),
            )
        )
    if not records:
        raise ValueError("No B50 entries were found in the TXT input")
    return records[:50], Player()


def parse_csv(path: Path, catalog: SongCatalog) -> tuple[list[ScoreRecord], Player]:
    records: list[ScoreRecord] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            song_id = row["SongId"]
            song = catalog.find(song_id=song_id)
            pure = integer(row.get("Pure"))
            max_pure = integer(row.get("MaxPure"))
            supplied_small_pure = integer(row.get("SmallPure"))
            records.append(
                ScoreRecord(
                    title=song.title if song else song_id,
                    song_id=song_id,
                    difficulty=difficulty_name(row["Difficulty"]),
                    constant=float(row["Constant"]),
                    score=int(row["Score"]),
                    potential=float(row["Potential"]),
                    pure=pure,
                    max_pure=max_pure,
                    far=integer(row.get("Far")),
                    lost=integer(row.get("Lost")),
                    small_pure=supplied_small_pure
                    if supplied_small_pure is not None
                    else small_pure_count(pure, max_pure),
                    clear_type=CLEAR_TYPES.get(integer(row.get("ClearType")) or 0, ""),
                    played_at=row.get("DateTime", "").split(" ", 1)[0],
                )
            )
    records.sort(key=lambda item: item.potential, reverse=True)
    return records[:50], Player()


def first_value(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if item.get(name) is not None:
            return item[name]
    return None


def parse_json(path: Path, catalog: SongCatalog) -> tuple[list[ScoreRecord], Player]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        rows = payload
        player_data: dict[str, Any] = {}
    else:
        rows = payload.get("scores") or payload.get("records") or payload.get("b50") or []
        player_data = payload.get("player") or payload.get("user") or {}

    records: list[ScoreRecord] = []
    for row in rows:
        song_id = str(first_value(row, "song_id", "SongId") or "")
        supplied_title = str(first_value(row, "song_name", "title", "Title") or "")
        song = catalog.find(title=supplied_title, song_id=song_id)
        raw_potential = first_value(row, "raw_potential")
        potential = (
            float(raw_potential) + 0.2
            if raw_potential is not None
            else float(first_value(row, "potential", "Potential"))
        )
        raw_clear_type = first_value(row, "clear_type", "ClearType")
        clear_type = (
            CLEAR_TYPES.get(int(raw_clear_type), "")
            if isinstance(raw_clear_type, (int, float))
            else str(raw_clear_type or "")
        )
        pure = integer(first_value(row, "pure", "perfect_count", "Pure"))
        max_pure = integer(
            first_value(row, "max_pure", "shiny_perfect_count", "MaxPure")
        )
        supplied_small_pure = integer(first_value(row, "small_pure", "small_p", "SmallPure"))
        records.append(
            ScoreRecord(
                title=song.title if song else supplied_title or song_id,
                song_id=song.song_id if song else song_id,
                difficulty=difficulty_name(first_value(row, "difficulty", "Difficulty")),
                constant=float(first_value(row, "constant", "Constant")),
                score=int(first_value(row, "score", "Score")),
                potential=potential,
                pure=pure,
                max_pure=max_pure,
                far=integer(first_value(row, "far", "near_count", "Far")),
                lost=integer(first_value(row, "lost", "miss_count", "Lost")),
                small_pure=supplied_small_pure
                if supplied_small_pure is not None
                else small_pure_count(pure, max_pure),
                clear_type=clear_type,
                played_at=str(first_value(row, "played_at", "DateTime") or "").split(" ", 1)[0],
            )
        )
    records.sort(key=lambda item: item.potential, reverse=True)
    player = Player(
        name=str(first_value(player_data, "name", "display_name") or "PLAYER"),
        user_id=str(first_value(player_data, "user_id", "user_code", "code") or "-"),
    )
    return records[:50], player


def load_input(path: Path, catalog: SongCatalog) -> tuple[list[ScoreRecord], Player]:
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        return parse_csv(path, catalog)
    if suffix == ".json":
        return parse_json(path, catalog)
    return parse_txt(path, catalog)


def formatted_score(score: int) -> str:
    digits = f"{score:08d}"
    return f"{digits[:2]}'{digits[2:5]}'{digits[5:]}"


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(text, font=font)


def ellipsize(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> str:
    if text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "..."
    while text and text_width(draw, text + ellipsis, font) > max_width:
        text = text[:-1]
    return text.rstrip() + ellipsis


def paste_rounded(canvas: Image.Image, image: Image.Image, xy: tuple[int, int], radius: int) -> None:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width, image.height), radius, fill=255)
    canvas.paste(image, xy, mask)


def placeholder_cover(size: int, title: str, fonts: FontBook) -> Image.Image:
    cover = Image.new("RGB", (size, size), "#30343A")
    draw = ImageDraw.Draw(cover)
    draw.line((0, size, size, 0), fill="#555C65", width=3)
    initial = (title.strip()[:1] or "?").upper()
    draw.text(
        (size // 2, size // 2),
        initial,
        font=fonts.title(initial, 30),
        fill="#ECEAE5",
        anchor="mm",
    )
    return cover


def detail_line(record: ScoreRecord) -> str:
    parts: list[str] = []
    if record.pure is not None:
        pure = f"P{record.pure}"
        if record.max_pure is not None:
            pure += f"(+{record.max_pure})"
        parts.append(pure)
    if record.far is not None:
        parts.append(f"F{record.far}")
    if record.lost is not None:
        parts.append(f"L{record.lost}")
    if record.clear_type:
        parts.append(record.clear_type)
    return " ".join(parts)


def draw_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    fonts: FontBook,
    catalog: SongCatalog,
    record: ScoreRecord,
    rank: int,
    x: int,
    y: int,
) -> bool:
    width, height = 340, 100
    draw.rounded_rectangle(
        (x, y, x + width, y + height),
        radius=6,
        fill="#F0EFEB",
        outline="#FFFFFF",
        width=1,
    )

    song = catalog.find(record.title, record.song_id)
    jacket_path = catalog.jacket_path(song, record.difficulty)
    if jacket_path:
        with Image.open(jacket_path) as source:
            cover = ImageOps.fit(source.convert("RGB"), (92, 92), Image.Resampling.LANCZOS)
    else:
        cover = placeholder_cover(92, record.title, fonts)
    paste_rounded(canvas, cover, (x + 4, y + 4), 4)

    body_x = x + 106
    accent = DIFFICULTY_COLORS[record.difficulty]
    draw.rounded_rectangle((body_x, y + 8, body_x + 5, y + 27), radius=2, fill=accent)

    title_font = fonts.title(record.title, 16)
    rank_font = fonts.get("regular", 15)
    title = ellipsize(draw, record.title, title_font, 177)
    draw.text((body_x + 10, y + 5), title, font=title_font, fill="#22252A")
    draw.text((x + width - 8, y + 7), f"#{rank}", font=rank_font, fill="#3B3E43", anchor="ra")

    draw.text(
        (body_x + 8, y + 27),
        formatted_score(record.score),
        font=fonts.get("regular", 29),
        fill="#111317",
    )
    draw.text(
        (body_x + 8, y + 66),
        f"{record.difficulty}  {record.constant:.1f}",
        font=fonts.get("semibold", 14),
        fill=accent,
    )
    draw.text(
        (x + width - 8, y + 64),
        f"PT {record.potential:.4f}",
        font=fonts.get("semibold", 15),
        fill="#282B31",
        anchor="ra",
    )

    details = detail_line(record)
    if details:
        detail_width = 166 if record.played_at else 220
        details = ellipsize(draw, details, fonts.get("regular", 11), detail_width)
        draw.text((body_x + 8, y + 84), details, font=fonts.get("regular", 11), fill="#676B70")
        if record.played_at:
            draw.text(
                (x + width - 8, y + 84),
                record.played_at[5:],
                font=fonts.get("regular", 11),
                fill="#7A7E83",
                anchor="ra",
            )

    return jacket_path is not None


def render(
    records: list[ScoreRecord],
    player: Player,
    catalog: SongCatalog,
    background_path: Path,
    font_dir: Path,
    output_path: Path,
) -> tuple[float, float, float, int]:
    with Image.open(background_path) as background:
        canvas = ImageOps.fit(background.convert("RGB"), (WIDTH, HEIGHT), Image.Resampling.LANCZOS)

    veil = Image.new("RGBA", (WIDTH, HEIGHT), (8, 10, 13, 150))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), veil).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    fonts = FontBook(font_dir)

    top10 = records[:10]
    top50 = records[:50]
    top10_avg = sum(item.potential for item in top10) / len(top10)
    top50_avg = sum(item.potential for item in top50) / len(top50)
    max_potential = (sum(item.potential for item in top10) + sum(item.potential for item in top50)) / (
        len(top10) + len(top50)
    )

    draw.text((48, 38), "ARCAEA", font=fonts.get("semibold", 46), fill="#F7F5F0")
    draw.line((240, 48, 240, 87), fill="#B6BABD", width=2)
    draw.text((267, 44), "PLAYER BESTS", font=fonts.get("regular", 34), fill="#F7F5F0")
    draw.line((48, 103, 710, 103), fill="#90969D", width=1)

    player_font = fonts.title(player.name, 34)
    player_name = ellipsize(draw, player.name, player_font, 650)
    draw.text((48, 125), player_name, font=player_font, fill="#FFFFFF")
    draw.text((50, 174), f"ID: {player.user_id}", font=fonts.get("regular", 18), fill="#C9CDD0")

    stats = [
        ("BEST TOP10 AVG.", top10_avg),
        ("BEST TOP50 AVG.", top50_avg),
        ("MAX POTENTIAL", max_potential),
    ]
    for index, (label, value) in enumerate(stats):
        stat_x = 48 + index * 260
        draw.text((stat_x, 240), label, font=fonts.get("semibold", 16), fill="#C9CDD0")
        draw.text((stat_x, 269), f"{value:.5f}", font=fonts.get("regular", 28), fill="#FFFFFF")

    draw.text((48, 370), "BEST 50", font=fonts.get("semibold", 20), fill="#F2F0EB")
    draw.text(
        (1876, 371),
        f"{len(top50)} RECORDS",
        font=fonts.get("regular", 16),
        fill="#C9CDD0",
        anchor="ra",
    )
    draw.line((48, 405, 1876, 405), fill="#6A7077", width=1)

    jackets_found = 0
    for index, record in enumerate(top50):
        column = index % 5
        row = index // 5
        x = 36 + column * 375
        y = 430 + row * 122
        jackets_found += draw_card(canvas, draw, fonts, catalog, record, index + 1, x, y)

    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    draw.text((36, 1687), generated_at, font=fonts.get("regular", 18), fill="#D9DCDE")
    draw.text(
        (1884, 1687),
        "Generated by dududa B50 renderer",
        font=fonts.get("regular", 18),
        fill="#D9DCDE",
        anchor="ra",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)
    return top10_avg, top50_avg, max_potential, jackets_found


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="B50 TXT, CSV, or JSON file")
    parser.add_argument(
        "--assets-root",
        type=Path,
        required=True,
        help="Arcaea asset directory containing songlist and song ID folders",
    )
    parser.add_argument("--output", type=Path, default=Path("b50.png"))
    parser.add_argument("--background", type=Path, default=resource_path("background.png"))
    parser.add_argument("--font-dir", type=Path, default=resource_path("fonts"))
    parser.add_argument("--player-name")
    parser.add_argument("--player-id")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = SongCatalog(args.assets_root)
    records, player = load_input(args.input, catalog)
    if args.player_name is not None:
        player.name = args.player_name
    if args.player_id is not None:
        player.user_id = args.player_id

    top10, top50, maximum, jacket_count = render(
        records,
        player,
        catalog,
        args.background,
        args.font_dir,
        args.output,
    )
    print(f"Rendered {len(records[:50])} records to {args.output}")
    print(f"Top10 {top10:.5f} | Top50 {top50:.5f} | Max {maximum:.5f}")
    print(f"Resolved jackets: {jacket_count}/{len(records[:50])}")


if __name__ == "__main__":
    main()
