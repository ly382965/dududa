from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dududa_mcp_console.server import EnvironmentSecretResolver, _project_to_schema


class CapabilityProjectionTests(unittest.TestCase):
    def test_unknown_mcp_fields_do_not_escape_capability_schema(self) -> None:
        value = {"courses": 0, "db_path": "/private/cache.sqlite3"}
        schema = {
            "type": "object",
            "properties": {"courses": {"type": "integer"}},
            "required": ["courses"],
            "additionalProperties": False,
        }
        self.assertEqual(_project_to_schema(value, schema), {"courses": 0})

    def test_cas_secret_refs_can_reuse_the_existing_toml_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.toml"
            path.write_text('username = "student"\npassword = "local-secret"\n', encoding="utf-8")
            resolver = EnvironmentSecretResolver(path)
            username = SimpleNamespace(secret_id="ustc-cas-username", target_name="USTC_CAS_USR")
            password = SimpleNamespace(secret_id="ustc-cas-password", target_name="USTC_CAS_PWD")
            with patch.dict(os.environ, {"USTC_CAS_USR": "", "USTC_CAS_PWD": ""}):
                self.assertTrue(resolver.is_configured(username))
                self.assertTrue(resolver.is_configured(password))
                self.assertEqual(asyncio.run(resolver.resolve(username, call=None)), "student")


if __name__ == "__main__":
    unittest.main()
