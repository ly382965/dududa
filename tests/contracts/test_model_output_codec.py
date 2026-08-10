from __future__ import annotations

from types import MappingProxyType
import unittest

from dududa.contracts.canonical import canonical_schema_digest
from dududa.domain.primitives import SchemaRef
from dududa.errors import DududaError
from astrbot_plugin_dududa_core.adapters.model_codec import (
    JsonSchemaDocumentRegistry,
    JsonSchemaOutputCodec,
)

from tests.unit.models.helpers import revision


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "answer"],
    "properties": {
        "schema_version": {"const": 1},
        "answer": {"type": "string", "minLength": 1},
    },
}


def _reference(document=SCHEMA) -> SchemaRef:
    return SchemaRef(
        schema_id="direct-chat-output",
        schema_version=1,
        digest=canonical_schema_digest(
            document,
            schema_id="direct-chat-output",
            schema_version=1,
        ),
    )


class JsonSchemaOutputCodecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = _reference()
        self.registry = JsonSchemaDocumentRegistry({self.reference: SCHEMA})
        self.codec = JsonSchemaOutputCodec(
            self.registry,
            revision=revision("json-schema-codec"),
        )

    def test_whole_json_document_is_validated_and_frozen(self) -> None:
        result = self.codec.validate(
            '{"schema_version":1,"answer":"ok"}',
            self.reference,
        )
        self.assertIsInstance(result, MappingProxyType)
        self.assertEqual(result["answer"], "ok")
        self.assertGreater(self.registry.token_upper_bound(self.reference), 0)

    def test_trailing_text_partial_and_unknown_fields_are_rejected(self) -> None:
        invalid_values = (
            '{"schema_version":1,"answer":"ok"} trailing',
            '{"schema_version":1}',
            '{"schema_version":1,"answer":"ok","extra":true}',
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(DududaError):
                self.codec.validate(value, self.reference)

    def test_invalid_output_is_not_exposed_by_error(self) -> None:
        secret = "Bearer synthetic-secret-value"
        with self.assertRaises(DududaError) as captured:
            self.codec.validate(
                {"schema_version": 1, "answer": "", "secret": secret},
                self.reference,
            )
        self.assertNotIn(secret, str(captured.exception))
        self.assertNotIn(secret, repr(captured.exception))

        invalid_json = f'{{"answer":"{secret}"}} trailing'
        with self.assertRaises(DududaError) as malformed:
            self.codec.validate(invalid_json, self.reference)
        self.assertIsNone(malformed.exception.__context__)
        self.assertIsNone(malformed.exception.__cause__)
        self.assertNotIn(secret, repr(malformed.exception.info))

    def test_instance_key_is_replaced_by_bounded_schema_path_metadata(self) -> None:
        secret_key = "provider-secret-object-key"
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": {"type": "integer"},
        }
        reference = _reference(schema)
        codec = JsonSchemaOutputCodec(
            JsonSchemaDocumentRegistry({reference: schema}),
            revision=revision("json-schema-codec"),
        )

        with self.assertRaises(DududaError) as captured:
            codec.validate({secret_key: "not-an-integer"}, reference)

        self.assertNotIn(secret_key, repr(captured.exception.info))
        self.assertEqual(
            captured.exception.info.reason_codes,
            ("instance_depth_1", "type"),
        )

    def test_registry_rejects_digest_drift_and_remote_refs(self) -> None:
        changed = dict(SCHEMA)
        changed["title"] = "changed"
        with self.assertRaises(DududaError):
            JsonSchemaDocumentRegistry({self.reference: changed})

        remote = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.invalid/schema.json",
        }
        with self.assertRaises(DududaError):
            _reference(remote)


if __name__ == "__main__":
    unittest.main()
