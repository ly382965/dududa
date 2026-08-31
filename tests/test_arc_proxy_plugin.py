from __future__ import annotations

import ast
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from astrbot_plugin_arc_proxy import LocalB50Renderer, LocalB50RendererError

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "apps" / "astrbot-plugins" / "astrbot_plugin_arc_proxy"
NOW = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)


class ArcB50AssetTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_request_produces_local_artifact_and_provenance(
        self,
    ) -> None:
        calls: list[tuple[Path, ...]] = []
        input_payloads: list[dict[str, object]] = []

        def fake_engine(
            renderer_script: Path,
            input_path: Path,
            assets_root: Path,
            output_path: Path,
            background_path: Path,
            font_directory: Path,
        ) -> dict[str, object]:
            calls.append(
                (
                    renderer_script,
                    input_path,
                    assets_root,
                    output_path,
                    background_path,
                    font_directory,
                )
            )
            input_payloads.append(json.loads(input_path.read_text(encoding="utf-8")))
            output_path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            return {
                "record_count": 1,
                "top10_average": 13.1,
                "top50_average": 13.1,
                "maximum_potential": 13.1,
                "resolved_jacket_count": 0,
            }

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            renderer = root / "b50_renderer.py"
            renderer.write_text("# fixture", encoding="utf-8")
            assets = root / "assets"
            assets.mkdir()
            artifacts = root / "artifacts"
            adapter = LocalB50Renderer(
                renderer_script=renderer,
                assets_root=assets,
                artifact_root=artifacts,
                asset_dataset_id="fixture-assets-v1",
                engine=fake_engine,
                clock=lambda: NOW,
                id_factory=lambda: "fixture-001",
            )

            result = await adapter.render(
                {
                    "player": {"name": "PLAYER", "user_id": "123456789"},
                    "scores": (
                        {
                            "title": "Testify",
                            "song_id": "testify",
                            "difficulty": "BYD",
                            "constant": 12.0,
                            "score": 10_000_123,
                            "potential": 13.1,
                        },
                    ),
                }
            )

            artifact_path = Path(result["artifact"]["path"])
            self.assertEqual(artifact_path, artifacts / "b50-fixture-001.png")
            self.assertTrue(artifact_path.is_file())
            self.assertEqual(result["artifact"]["media_type"], "image/png")
            self.assertEqual(result["statistics"]["record_count"], 1)
            self.assertEqual(result["generated_at"], "2026-08-31T00:00:00+00:00")
            self.assertEqual(
                result["provenance"],
                {
                    "renderer": "dududa-b50-renderer",
                    "renderer_revision": "repository-v1",
                    "asset_dataset_id": "fixture-assets-v1",
                    "input_record_count": 1,
                    "execution": "local_in_process",
                },
            )
            self.assertEqual(input_payloads[0]["player"]["name"], "PLAYER")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], renderer)
            self.assertEqual(calls[0][2], assets)

            await adapter.close()
            with self.assertRaises(LocalB50RendererError):
                await adapter.render({"player": {}, "scores": ({},)})

    async def test_empty_scores_fail_before_renderer_execution(self) -> None:
        calls = 0

        def fake_engine(*paths):
            nonlocal calls
            calls += 1
            raise AssertionError(paths)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            adapter = LocalB50Renderer(
                renderer_script=root / "renderer.py",
                assets_root=root / "assets",
                artifact_root=root / "artifacts",
                engine=fake_engine,
            )
            with self.assertRaises(ValueError):
                await adapter.render({"player": {}, "scores": ()})
            await adapter.close()
        self.assertEqual(calls, 0)

    def test_plugin_python_has_no_proxy_handler_identity_store_or_send(self) -> None:
        identifiers: set[str] = set()
        string_literals: set[str] = set()
        decorators: list[str] = []
        for path in PLUGIN_ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            identifiers.update(
                node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
            )
            identifiers.update(
                node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            )
            string_literals.update(
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            )
            decorators.extend(
                ast.unparse(decorator)
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                for decorator in node.decorator_list
            )

        self.assertTrue(
            identifiers.isdisjoint(
                {
                    "AiocqhttpMessageEvent",
                    "AstrMessageEvent",
                    "BindingStore",
                    "MessageChain",
                    "send",
                    "send_group_msg",
                    "send_message",
                    "sqlite3",
                }
            )
        )
        self.assertFalse(any("filter." in decorator for decorator in decorators))
        self.assertFalse(any("3889054356" in value for value in string_literals))
        self.assertFalse(any("mmdustc.top" in value for value in string_literals))

    def test_plugin_is_default_off_and_describes_only_local_capability(self) -> None:
        schema = json.loads(
            (PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8")
        )
        metadata = (PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")

        self.assertIs(schema["enabled"]["default"], False)
        self.assertIn("version: v2.0.0", metadata)
        self.assertIn("不代理第三方 Bot 或自行发送消息", metadata)

    def test_repository_factory_points_at_in_tree_renderer(self) -> None:
        adapter = LocalB50Renderer.from_repository(
            assets_root=Path("/tmp/fixture-assets"),
            artifact_root=Path("/tmp/fixture-artifacts"),
        )
        self.assertEqual(
            adapter._renderer_script,
            ROOT / "apps" / "b50-renderer" / "b50_renderer.py",
        )


if __name__ == "__main__":
    unittest.main()
