from __future__ import annotations

import json
from collections.abc import Mapping

from dududa.capabilities.contracts import CapabilitySchemaDocument
from dududa.contracts.canonical import canonical_json_bytes
from dududa.domain.primitives import JsonValue, freeze_json
from dududa.errors import validation_error
from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for


class JsonSchemaMcpValidator:
    """Local-only JSON Schema validation for the MCP infrastructure edge."""

    def check_schema(
        self,
        schema: Mapping[str, JsonValue],
        *,
        schema_id: str,
    ) -> None:
        document = _plain_mapping(schema, "mcp_schema")
        _reject_recursive_reference_graph(document)
        validator = validator_for(document)
        try:
            validator.check_schema(document)
        except SchemaError as exc:
            raise validation_error(
                "invalid_mcp_json_schema",
                "schema_document_rejected",
            ) from exc

    def validate(
        self,
        value: JsonValue,
        schema: Mapping[str, JsonValue],
        *,
        schema_id: str,
    ) -> JsonValue:
        document = _plain_mapping(schema, "mcp_schema")
        self.check_schema(schema, schema_id=schema_id)
        instance = json.loads(canonical_json_bytes(value))
        first = next(validator_for(document)(document).iter_errors(instance), None)
        if first is not None:
            raise validation_error(
                "mcp_json_schema_validation_failed",
                f"instance_depth_{len(first.absolute_path)}",
                str(first.validator or "schema"),
            )
        return freeze_json(instance)


class JsonSchemaCapabilityValidator:
    """Local-only JSON Schema validation for the Capability infrastructure edge."""

    def check_schema(self, document: CapabilitySchemaDocument) -> None:
        if not isinstance(document, CapabilitySchemaDocument):
            raise TypeError("document must be a CapabilitySchemaDocument")
        schema = _plain_mapping(document.document, "capability_schema")
        _reject_recursive_reference_graph(schema)
        validator = validator_for(schema)
        try:
            validator.check_schema(schema)
        except SchemaError as exc:
            raise validation_error(
                "invalid_capability_json_schema",
                "schema_document_rejected",
            ) from exc

    def validate(
        self,
        value: JsonValue,
        document: CapabilitySchemaDocument,
    ) -> JsonValue:
        self.check_schema(document)
        schema = _plain_mapping(document.document, "capability_schema")
        instance = json.loads(canonical_json_bytes(value))
        first = next(validator_for(schema)(schema).iter_errors(instance), None)
        if first is not None:
            raise validation_error(
                "capability_json_schema_validation_failed",
                f"instance_depth_{len(first.absolute_path)}",
                str(first.validator or "schema"),
            )
        return freeze_json(instance)


__all__ = ["JsonSchemaCapabilityValidator", "JsonSchemaMcpValidator"]


def _plain_mapping(value: Mapping[str, JsonValue], field: str) -> dict[str, object]:
    try:
        decoded = json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError, RecursionError) as exc:
        raise validation_error("invalid_mcp_json_schema", field) from exc
    if not isinstance(decoded, dict):
        raise validation_error("invalid_mcp_json_schema", field)
    return decoded


def _reject_recursive_reference_graph(document: dict[str, object]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()
    nodes = 0

    def scan(value: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 10_000:
            raise validation_error(
                "invalid_mcp_json_schema",
                "reference_graph_too_complex",
            )
        if isinstance(value, dict):
            if "$dynamicRef" in value or "$recursiveRef" in value:
                raise validation_error(
                    "invalid_mcp_json_schema",
                    "dynamic_reference_forbidden",
                )
            reference = value.get("$ref")
            if reference is not None:
                if not isinstance(reference, str) or not reference.startswith("#"):
                    raise validation_error(
                        "invalid_mcp_json_schema",
                        "remote_reference_forbidden",
                    )
                if reference in visiting:
                    raise validation_error(
                        "invalid_mcp_json_schema",
                        "recursive_reference_forbidden",
                    )
                if reference not in visited:
                    visiting.add(reference)
                    try:
                        scan(_resolve_pointer(document, reference), depth + 1)
                    finally:
                        visiting.discard(reference)
                    visited.add(reference)
            for key, item in value.items():
                if key != "$ref":
                    scan(item, depth)
        elif isinstance(value, list):
            for item in value:
                scan(item, depth)

    scan(document, 0)


def _resolve_pointer(document: dict[str, object], reference: str) -> object:
    if reference == "#":
        return document
    if not reference.startswith("#/"):
        raise validation_error(
            "invalid_mcp_json_schema",
            "unsupported_local_reference",
        )
    current: object = document
    for encoded in reference[2:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
            continue
        if isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
            continue
        raise validation_error(
            "invalid_mcp_json_schema",
            "local_reference_not_found",
        )
    return current
