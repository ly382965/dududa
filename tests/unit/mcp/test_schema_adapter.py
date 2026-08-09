from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dududa.capabilities import CapabilitySchemaDocument
from dududa.contracts.canonical import canonical_schema_digest
from dududa.domain.primitives import SchemaRef
from dududa.errors import DududaError

from plugins.astrbot_plugin_dududa_core.adapters import mcp_schema
from plugins.astrbot_plugin_dududa_core.adapters.mcp_schema import (
    JsonSchemaCapabilityValidator,
    JsonSchemaMcpValidator,
)


def capability_schema(schema_id: str, document) -> CapabilitySchemaDocument:
    reference = SchemaRef(
        schema_id,
        1,
        canonical_schema_digest(document, schema_id=schema_id, schema_version=1),
    )
    return CapabilitySchemaDocument(1, reference, document)


class JsonSchemaCapabilityValidatorTests(unittest.TestCase):
    def test_capability_document_and_instance_are_digest_bound(self) -> None:
        validator = JsonSchemaCapabilityValidator()
        document = capability_schema(
            "capability.fixture.output",
            {
                "type": "object",
                "properties": {"value": {"type": "string", "maxLength": 8}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )

        validator.check_schema(document)
        self.assertEqual(validator.validate({"value": "ok"}, document), {"value": "ok"})
        with self.assertRaises(DududaError):
            validator.validate({"value": "too-long-value"}, document)

    def test_capability_recursive_schema_fails_closed(self) -> None:
        validator = JsonSchemaCapabilityValidator()
        document = capability_schema(
            "capability.fixture.recursive",
            {
                "$defs": {
                    "node": {
                        "type": "object",
                        "properties": {"next": {"$ref": "#/$defs/node"}},
                    }
                },
                "$ref": "#/$defs/node",
            },
        )
        with self.assertRaises(DududaError):
            validator.check_schema(document)

    def test_validation_stops_after_first_instance_error(self) -> None:
        class OneErrorValidator:
            @staticmethod
            def check_schema(schema) -> None:
                return None

            def __init__(self, schema) -> None:
                self.schema = schema

            def iter_errors(self, instance):
                yield SimpleNamespace(absolute_path=(), validator="type")
                raise AssertionError("validator consumed more than one error")

        document = capability_schema(
            "capability.fixture.first-error",
            {"type": "integer"},
        )
        with (
            patch.object(mcp_schema, "validator_for", return_value=OneErrorValidator),
            self.assertRaises(DududaError),
        ):
            JsonSchemaCapabilityValidator().validate("wrong", document)

    def test_reference_graph_is_memoized_and_depth_bounded(self) -> None:
        definitions = {"level0": {"type": "string"}}
        for level in range(1, 19):
            previous = f"#/$defs/level{level - 1}"
            definitions[f"level{level}"] = {
                "anyOf": [{"$ref": previous}, {"$ref": previous}]
            }
        document = capability_schema(
            "capability.fixture.reference-dag",
            {"$defs": definitions, "$ref": "#/$defs/level18"},
        )
        original = mcp_schema._resolve_pointer
        with patch.object(
            mcp_schema,
            "_resolve_pointer",
            wraps=original,
        ) as resolve:
            JsonSchemaCapabilityValidator().check_schema(document)
        self.assertLessEqual(resolve.call_count, 19)

        too_deep_definitions = {"level0": {"type": "string"}}
        for level in range(1, 35):
            too_deep_definitions[f"level{level}"] = {
                "$ref": f"#/$defs/level{level - 1}"
            }
        with self.assertRaises(DududaError):
            JsonSchemaCapabilityValidator().check_schema(
                capability_schema(
                    "capability.fixture.too-deep",
                    {
                        "$defs": too_deep_definitions,
                        "$ref": "#/$defs/level34",
                    },
                )
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
