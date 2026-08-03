from __future__ import annotations

import json
from types import MappingProxyType
from typing import Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from dududa.contracts.canonical import (
    canonical_json_bytes,
    canonical_schema_digest,
)
from dududa.domain.primitives import (
    ComponentRevision,
    JsonValue,
    SchemaRef,
    freeze_json,
)
from dududa.errors import validation_error


class JsonSchemaDocumentRegistry:
    """Immutable local-only JSON Schema documents keyed by exact SchemaRef."""

    def __init__(
        self,
        documents: Mapping[SchemaRef, Mapping[str, object]],
    ) -> None:
        encoded: dict[SchemaRef, bytes] = {}
        identities: set[tuple[str, int]] = set()
        for reference, document in documents.items():
            if not isinstance(reference, SchemaRef):
                raise ValueError("schema registry key must be a SchemaRef")
            identity = (reference.schema_id, reference.schema_version)
            if identity in identities:
                raise ValueError("duplicate schema identity")
            identities.add(identity)
            expected = canonical_schema_digest(
                document,
                schema_id=reference.schema_id,
                schema_version=reference.schema_version,
            )
            if expected != reference.digest:
                raise validation_error("json_schema_digest_mismatch")
            plain = json.loads(canonical_json_bytes(document))
            schema_error = False
            try:
                Draft202012Validator.check_schema(plain)
            except SchemaError:
                schema_error = True
            if schema_error:
                raise validation_error("invalid_json_schema_document")
            encoded[reference] = canonical_json_bytes(document)
        self._documents = MappingProxyType(encoded)

    def document(self, reference: SchemaRef) -> dict[str, object]:
        if not isinstance(reference, SchemaRef):
            raise validation_error("invalid_schema_reference")
        encoded = self._documents.get(reference)
        if encoded is None:
            raise validation_error("json_schema_not_registered")
        value = json.loads(encoded)
        if not isinstance(value, dict):
            raise validation_error("json_schema_root_not_object")
        return value

    def token_upper_bound(self, reference: SchemaRef) -> int:
        encoded = self._documents.get(reference)
        if encoded is None:
            raise validation_error("json_schema_not_registered")
        return len(encoded)


class JsonSchemaOutputCodec:
    def __init__(
        self,
        registry: JsonSchemaDocumentRegistry,
        *,
        revision: ComponentRevision,
    ) -> None:
        if not isinstance(registry, JsonSchemaDocumentRegistry):
            raise ValueError("registry must be JsonSchemaDocumentRegistry")
        if not isinstance(revision, ComponentRevision):
            raise ValueError("revision must be ComponentRevision")
        self._registry = registry
        self._revision = revision

    @property
    def revision(self) -> ComponentRevision:
        return self._revision

    @property
    def registry(self) -> JsonSchemaDocumentRegistry:
        return self._registry

    def validate(
        self,
        output: JsonValue,
        schema: SchemaRef,
    ) -> JsonValue:
        document = self._registry.document(schema)
        instance = _plain_json(output)
        errors = sorted(
            Draft202012Validator(document).iter_errors(instance),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            first = errors[0]
            path = f"instance_depth_{len(first.absolute_path)}"
            validator = str(first.validator or "schema")
            raise validation_error(
                "model_output_schema_invalid",
                path,
                validator,
            )
        return freeze_json(instance)


def _plain_json(output: JsonValue) -> object:
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, RecursionError):
            pass
        else:
            return parsed
        raise validation_error("model_output_json_invalid")
    try:
        parsed = json.loads(canonical_json_bytes(output))
    except (TypeError, ValueError, RecursionError):
        pass
    else:
        return parsed
    raise validation_error("model_output_json_invalid")
