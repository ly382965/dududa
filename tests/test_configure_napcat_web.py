from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "cli" / "configure_napcat_web.py"
SPEC = importlib.util.spec_from_file_location("configure_napcat_web", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ConfigureNapCatWebTests(unittest.TestCase):
    def test_apply_preserves_existing_client_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            token_file = root / "token"
            token_file.write_text("a" * 64, encoding="utf-8")
            os.chmod(token_file, 0o600)
            config_path = config_dir / "onebot11_123456789.json"
            original_client = {"name": "astrbot", "enable": True, "url": "ws://astrbot:6199/ws"}
            config_path.write_text(
                json.dumps({"network": {"websocketClients": [original_client]}}),
                encoding="utf-8",
            )

            changed = MODULE.configure(config_dir, token_file, "ws://dududa-web-api:8000/onebot/v11/ws", True)
            self.assertEqual(changed, 1)
            document = json.loads(config_path.read_text(encoding="utf-8"))
            clients = document["network"]["websocketClients"]
            self.assertEqual(clients[0], original_client)
            self.assertEqual(clients[1]["name"], "dududa-web")
            self.assertTrue(clients[1]["reportSelfMessage"])
            self.assertEqual(clients[1]["token"], "a" * 64)
            self.assertEqual(len(list(config_dir.glob("*.bak.*"))), 1)

            changed_again = MODULE.configure(config_dir, token_file, "ws://dududa-web-api:8000/onebot/v11/ws", True)
            self.assertEqual(changed_again, 0)
            self.assertEqual(len(list(config_dir.glob("*.bak.*"))), 1)

    def test_rejects_a_world_readable_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            token_file = Path(temporary) / "token"
            token_file.write_text("b" * 64, encoding="utf-8")
            os.chmod(token_file, 0o644)

            with self.assertRaisesRegex(ValueError, "must not be readable"):
                MODULE.load_token(token_file)


if __name__ == "__main__":
    unittest.main()
