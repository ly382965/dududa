from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RENDERER_PATH = ROOT / "apps" / "b50-renderer" / "b50_renderer.py"
SPEC = importlib.util.spec_from_file_location("dududa_b50_renderer", RENDERER_PATH)
assert SPEC is not None and SPEC.loader is not None
RENDERER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RENDERER
SPEC.loader.exec_module(RENDERER)


class B50RendererTests(unittest.TestCase):
    def test_synthetic_input_renders_png_without_network_or_jackets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "assets"
            assets.mkdir()
            (assets / "songlist").write_text(
                json.dumps(
                    {
                        "songs": [
                            {
                                "id": "synthetic",
                                "title_localized": {"en": "Synthetic Song"},
                                "difficulties": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source = root / "scores.txt"
            source.write_text(
                "Synthetic Song [FTR] 10.0: 9900000 (11.000) FAR 1 LOST 0\n",
                encoding="utf-8",
            )
            output = root / "b50.png"
            catalog = RENDERER.SongCatalog(assets)
            records, player = RENDERER.load_input(source, catalog)

            result = RENDERER.render(
                records,
                player,
                catalog,
                ROOT / "apps" / "b50-renderer" / "background.png",
                ROOT / "apps" / "b50-renderer" / "fonts",
                output,
            )

            self.assertEqual(result, (11.2, 11.2, 11.2, 0))
            with Image.open(output) as image:
                self.assertEqual(image.size, (1920, 1750))


if __name__ == "__main__":
    unittest.main()
