from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeSyncTests(unittest.TestCase):
    def test_sync_merges_mcp_without_overwriting_other_servers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            config_path = data_root / "astrbot" / "mcp_server.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps({"mcpServers": {"existing": {"command": "example"}}}),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "sync_runtime.py"),
                    "--data-root",
                    str(data_root),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            merged = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(set(merged["mcpServers"]), {"existing", "icourse"})
            self.assertTrue(merged["mcpServers"]["icourse"]["disabled"])
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
