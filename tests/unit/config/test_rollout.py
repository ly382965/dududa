from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dududa.errors import DududaError
from dududa.rollout import RolloutMode
from plugins.astrbot_plugin_dududa_core.config import AstrBotRolloutControlProvider


class AstrBotRolloutControlProviderTests(unittest.TestCase):
    def test_missing_file_uses_fail_safe_typed_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            provider = AstrBotRolloutControlProvider(
                {}, path=Path(directory) / "missing.json"
            )
            config = provider.current()
        self.assertIs(config.mode, RolloutMode.OFF)
        self.assertTrue(config.kill_switch)
        self.assertFalse(config.delivery_enabled)
        self.assertEqual(config.allowlisted_group_ids, frozenset())

    def test_each_current_read_observes_disk_and_invalid_json_fails_closed(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "plugin.json"
            path.write_text(
                json.dumps(
                    {
                        "rollout_mode": "shadow",
                        "rollout_revision": "rollout-v1",
                        "rollout_kill_switch": False,
                        "rollout_allowlisted_groups": ["g-1"],
                    }
                ),
                encoding="utf-8",
            )
            provider = AstrBotRolloutControlProvider({}, path=path)
            self.assertIs(provider.current().mode, RolloutMode.SHADOW)
            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises((ValueError, DududaError, json.JSONDecodeError)):
                provider.current()


if __name__ == "__main__":
    unittest.main()
