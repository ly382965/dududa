from __future__ import annotations

import json
from typing import Mapping

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
        errors = sorted(
            validator_for(document)(document).iter_errors(instance),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            first = errors[0]
            raise validation_error(
                "mcp_json_schema_validation_failed",
                f"instance_depth_{len(first.absolute_path)}",
                str(first.validator or "schema"),
            )
        return freeze_json(instance)


def _plain_mapping(value: Mapping[str, JsonValue], field: str) -> dict[str, object]:
    try:
        decoded = json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError, RecursionError) as exc:
        raise validation_error("invalid_mcp_json_schema", field) from exc
    if not isinstance(decoded, dict):
        raise validation_error("invalid_mcp_json_schema", field)
    return decoded


def _reject_recursive_reference_graph(document: dict[str, object]) -> None:
    def scan(value: object, chain: frozenset[str]) -> None:
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
                if reference in chain:
                    raise validation_error(
                        "invalid_mcp_json_schema",
                        "recursive_reference_forbidden",
                    )
                scan(_resolve_pointer(document, reference), chain | {reference})
            for key, item in value.items():
                if key != "$ref":
                    scan(item, chain)
        elif isinstance(value, list):
            for item in value:
                scan(item, chain)

    scan(document, frozenset())


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
