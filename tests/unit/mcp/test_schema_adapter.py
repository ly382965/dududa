from __future__ import annotations

import unittest

from dududa.errors import DududaError

from plugins.astrbot_plugin_dududa_core.adapters.mcp_schema import (
    JsonSchemaMcpValidator,
)


class JsonSchemaMcpValidatorTests(unittest.TestCase):
    def test_valid_schema_and_instance_are_accepted_without_transformation(
        self,
    ) -> None:
        validator = JsonSchemaMcpValidator()
        schema = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        }
        validator.check_schema(schema, schema_id="mcp.fake.echo.input")
        value = validator.validate(
            {"value": "ok"},
            schema,
            schema_id="mcp.fake.echo.input",
        )
        self.assertEqual(value, {"value": "ok"})

    def test_invalid_instance_and_recursive_schema_fail_closed(self) -> None:
        validator = JsonSchemaMcpValidator()
        schema = {"type": "string"}
        with self.assertRaises(DududaError):
            validator.validate(1, schema, schema_id="mcp.fake.echo.input")

        recursive = {
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"next": {"$ref": "#/$defs/node"}},
                }
            },
            "$ref": "#/$defs/node",
        }
        with self.assertRaises(DududaError):
            validator.check_schema(recursive, schema_id="mcp.fake.recursive.input")


if __name__ == "__main__":
    unittest.main()
