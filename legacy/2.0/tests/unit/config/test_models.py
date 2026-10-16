from __future__ import annotations

import unittest

from dududa.config import ConfigError, parse_agent_config


class ConfigTests(unittest.TestCase):
    def test_parse_strict_config(self) -> None:
        config = parse_agent_config(
            {
                "schema_version": 1,
                "default_persona_id": "dududa",
                "policy_snapshot_id": "policy-1",
                "feature_flags": {"runtime_v2": False},
            }
        )
        self.assertFalse(config.feature_flags["runtime_v2"])
        with self.assertRaises(TypeError):
            config.feature_flags["runtime_v2"] = True

    def test_unknown_or_malformed_config_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            parse_agent_config({"schema_version": 1, "unexpected": True})


if __name__ == "__main__":
    unittest.main()
