"""Prepare Emoji Kitchen and Arc assets for the recording desk."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/astrbot-plugins"))
from astrbot_plugin_emoji_kitchen.emoji_kitchen import EmojiKitchenService


async def main():
    state = ROOT.parent / "dududa-recording-state"
    artifacts = state / "data/recording-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    emoji = await EmojiKitchenService(artifacts / "emoji-cache").compose("😀 😭")
    (artifacts / "emoji.png").write_bytes(emoji.image_bytes)
    # Actual local game assets; no account bindings or player records are read.
    script = """import sys,asyncio
from pathlib import Path
sys.path.insert(0,"/AstrBot/data/plugins")
from astrbot_plugin_arc_proxy.catalog import SongStore,format_song_info
from astrbot_plugin_arc_proxy.chart_renderer import ChartRenderer
async def run():
 root=Path("/AstrBot/data/recording-artifacts");arc=Path("/AstrBot/data/plugin_data/astrbot_plugin_arc_proxy")
 store=SongStore(root/"songs.sqlite3",arc/"import",arc/"catalog")
 song=store.search("Testify")[0]
 (root/"arc-info.txt").write_text(format_song_info(song));(root/"arc-cover.jpg").write_bytes(song.cover_path.read_bytes())
 song=store.search("Sayonara Hatsukoi")[0]
 await ChartRenderer(arc/"import",arc/"renderer-assets",root/"charts").render(song,next(x for x in song.charts if x.rating_class==2))
asyncio.run(run())
"""
    await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "dududa-recording-astrbot", "python", "-"],
        input=script.encode(),
        check=True,
    )
    result = {
        "emoji": {
            "command": "/emoji 😀 😭",
            "file": "emoji.png",
            "bytes": len(emoji.image_bytes),
        },
        "arcInfo": {
            "command": "/arc info Testify",
            "file": "arc-cover.jpg",
            "text": (artifacts / "arc-info.txt").read_text(),
        },
        "arcChart": {
            "command": "/arc chart Sayonara Hatsukoi ftr",
            "file": "charts/sayonarahatsukoi_2.jpg",
        },
    }
    (state / "reports/plugin-assets.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {"passed": True, "artifactDirectory": str(artifacts)}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
