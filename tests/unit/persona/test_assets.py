from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from dududa.errors import DududaError
from dududa.persona.assets import load_persona_asset, load_persona_directory
from dududa.persona.contracts import persona_definition_source_digest

from tests.unit.persona._fixtures import ASSET_ROOT


class PersonaAssetTests(unittest.TestCase):
    def test_repository_assets_load_strictly_and_have_computed_digests(self) -> None:
        definitions = load_persona_directory(ASSET_ROOT)

        self.assertEqual(
            tuple(item.persona_id for item in definitions),
            ("dududa", "neutral"),
        )
        self.assertTrue(
            all(
                item.source_digest == persona_definition_source_digest(item)
                for item in definitions
            )
        )

    def test_json_parser_rejects_duplicate_unknown_non_finite_and_bad_enum(
        self,
    ) -> None:
        source = (ASSET_ROOT / "neutral.json").read_text(encoding="utf-8")
        documents = (
            source.replace(
                '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1
            ),
            source.replace(
                '"display_name": "Neutral",',
                '"display_name": "Neutral", "unknown": true,',
            ),
            source.replace('"emoji_budget": 0,', '"emoji_budget": NaN,', 1),
            source.replace(
                '"sentence_length": "balanced"', '"sentence_length": "invalid"'
            ),
            source.replace('"schema_version": 1,', '"schema_version": true,', 1),
            source.replace('"schema_version": 1,', '"schema_version": 1.0,', 1),
        )
        expected_codes = (
            "invalid_persona_asset_json",
            "invalid_persona_asset_fields",
            "invalid_persona_asset_json",
            "invalid_persona_sentence_length",
            "unsupported_schema_version",
            "unsupported_schema_version",
        )
        with tempfile.TemporaryDirectory(prefix="dududa-persona-assets-") as temp:
            root = Path(temp)
            for index, (text, code) in enumerate(
                zip(documents, expected_codes, strict=True)
            ):
                path = root / f"case-{index}.json"
                path.write_text(text, encoding="utf-8")
                with self.subTest(code=code), self.assertRaises(DududaError) as caught:
                    load_persona_asset(root, path)
                self.assertEqual(caught.exception.info.code, code)

    def test_secret_pattern_and_paths_fail_closed(self) -> None:
        document = json.loads((ASSET_ROOT / "neutral.json").read_text(encoding="utf-8"))
        document["voice"]["instructions"].append("api_key=do-not-load")
        with tempfile.TemporaryDirectory(prefix="dududa-persona-paths-") as temp:
            parent = Path(temp)
            root = parent / "assets"
            root.mkdir()
            outside = parent / "outside.json"
            outside.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(DududaError) as caught:
                load_persona_asset(root, outside)
            self.assertEqual(caught.exception.info.code, "persona_asset_outside_root")

            inside = root / "persona.json"
            inside.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(DududaError) as caught:
                load_persona_asset(root, inside)
            self.assertEqual(caught.exception.info.code, "persona_asset_secret_pattern")

            link = parent / "asset-link"
            os.symlink(root, link)
            with self.assertRaises(DududaError) as caught:
                load_persona_directory(link)
            self.assertEqual(caught.exception.info.code, "invalid_persona_asset_root")

    def test_missing_and_empty_directories_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dududa-persona-empty-") as temp:
            empty = Path(temp)
            with self.assertRaises(DududaError) as caught:
                load_persona_directory(empty)
            self.assertEqual(
                caught.exception.info.code, "empty_persona_asset_directory"
            )

            with self.assertRaises(DududaError) as caught:
                load_persona_directory(empty / "missing")
            self.assertEqual(caught.exception.info.code, "invalid_persona_asset_root")

    def test_oversized_asset_is_rejected_before_json_decode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dududa-persona-large-") as temp:
            root = Path(temp)
            path = root / "large.json"
            path.write_bytes(b"{" + b"x" * 65_536)
            with self.assertRaises(DududaError) as caught:
                load_persona_asset(root, path)
            self.assertEqual(caught.exception.info.code, "invalid_persona_asset_size")


if __name__ == "__main__":
    unittest.main()
