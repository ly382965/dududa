from __future__ import annotations

from collections.abc import Mapping

from dududa.contracts.canonical import canonical_json_bytes, canonical_schema_digest
from dududa.domain.capability import CapabilityDefinition
from dududa.domain.primitives import JsonValue, SchemaRef
from dududa.errors import validation_error
from dududa.ports.capabilities import CapabilitySchemaValidator

from .contracts import CapabilitySchemaDocument, McpCapabilityMapping

IDENTITY_ARGUMENT_MAPPING_REVISION = "identity-v1"
STRUCTURED_RESULT_MAPPING_REVISION = "structured-content-v1"
SCHEMA_PROJECT_RESULT_MAPPING_REVISION = "schema-project-v1"

RESULT_MAPPING_REVISIONS = frozenset(
    {
        STRUCTURED_RESULT_MAPPING_REVISION,
        SCHEMA_PROJECT_RESULT_MAPPING_REVISION,
    }
)
_UNSUPPORTED_PROJECTION_KEYWORDS = frozenset(
    {
        "$ref",
        "$dynamicRef",
        "allOf",
        "anyOf",
        "contains",
        "dependentSchemas",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "patternProperties",
        "prefixItems",
        "propertyNames",
        "unevaluatedProperties",
    }
)


def fixed_arguments_match(
    arguments: Mapping[str, JsonValue],
    fixed_arguments: Mapping[str, JsonValue],
) -> bool:
    try:
        return all(
            key in arguments
            and canonical_json_bytes(arguments[key]) == canonical_json_bytes(value)
            for key, value in fixed_arguments.items()
        )
    except Exception:  # noqa: BLE001 - malformed values fail closed.
        return False


def validate_mcp_mapping_policy(
    definition: CapabilityDefinition,
    mapping: McpCapabilityMapping,
    input_schema: CapabilitySchemaDocument,
    output_schema: CapabilitySchemaDocument,
    schema_validator: CapabilitySchemaValidator,
) -> None:
    if (
        mapping.capability_id != definition.capability_id
        or mapping.capability_definition_digest != definition.definition_digest
        or mapping.argument_mapping_revision != IDENTITY_ARGUMENT_MAPPING_REVISION
        or mapping.result_mapping_revision not in RESULT_MAPPING_REVISIONS
        or input_schema.schema_ref != definition.input_schema
        or output_schema.schema_ref != definition.output_schema
    ):
        raise validation_error("unsupported_mcp_capability_mapping_policy")
    root = input_schema.document
    properties = root.get("properties")
    if "object" not in _declared_types(root) or not isinstance(properties, Mapping):
        raise validation_error("mcp_fixed_argument_schema_not_object")
    definitions = root.get("$defs")
    for key, value in mapping.fixed_arguments.items():
        child = properties.get(key)
        if not isinstance(child, Mapping):
            raise validation_error("mcp_fixed_argument_not_in_input_schema")
        fragment = dict(child)
        if definitions is not None:
            fragment["$defs"] = definitions
        schema_id = f"{input_schema.schema_ref.schema_id}.fixed.{key}"
        reference = SchemaRef(
            schema_id,
            input_schema.schema_ref.schema_version,
            canonical_schema_digest(
                fragment,
                schema_id=schema_id,
                schema_version=input_schema.schema_ref.schema_version,
            ),
        )
        document = CapabilitySchemaDocument(1, reference, fragment)
        schema_validator.check_schema(document)
        validated = schema_validator.validate(value, document)
        if canonical_json_bytes(validated) != canonical_json_bytes(value):
            raise validation_error("mcp_fixed_argument_schema_transformed")
    if mapping.result_mapping_revision == SCHEMA_PROJECT_RESULT_MAPPING_REVISION:
        check_projection_schema(output_schema.document)


def check_projection_schema(
    schema: Mapping[str, JsonValue],
    *,
    depth: int = 0,
    nodes: list[int] | None = None,
) -> None:
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if depth > 32 or nodes[0] > 10_000:
        raise ValueError("Capability projection Schema is too complex")
    if any(keyword in schema for keyword in _UNSUPPORTED_PROJECTION_KEYWORDS):
        raise ValueError("unsupported Capability projection Schema")
    types = projection_schema_types(schema)
    if "object" in types:
        properties = schema.get("properties")
        if (
            not isinstance(properties, Mapping)
            or schema.get("additionalProperties") is not False
        ):
            raise ValueError("projected object Schema must declare closed properties")
        required = schema.get("required", ())
        if (
            not isinstance(required, tuple)
            or not all(isinstance(item, str) for item in required)
            or len(required) != len(set(required))
            or not set(required) <= set(properties)
        ):
            raise ValueError("projected object Schema has invalid required fields")
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                raise TypeError("invalid projected object property")
            check_projection_schema(child, depth=depth + 1, nodes=nodes)
    if "array" in types:
        items = schema.get("items")
        maximum_items = schema.get("maxItems")
        if (
            not isinstance(items, Mapping)
            or type(maximum_items) is not int
            or not 0 <= maximum_items <= 10_000
        ):
            raise ValueError("projected array Schema must declare item Schema")
        check_projection_schema(items, depth=depth + 1, nodes=nodes)
    if "string" in types:
        maximum_length = schema.get("maxLength")
        if type(maximum_length) is not int or not 0 <= maximum_length <= 1_048_576:
            raise ValueError("projected string Schema must declare maxLength")


def projection_schema_types(schema: Mapping[str, JsonValue]) -> frozenset[str]:
    values = _declared_types(schema)
    allowed = frozenset(
        {"null", "boolean", "integer", "number", "string", "object", "array"}
    )
    result = frozenset(values)
    non_null = result - {"null"}
    if (
        len(result) != len(values)
        or not result <= allowed
        or len(non_null) != 1
        or len(result) > 2
    ):
        raise ValueError("projected Schema declares invalid types")
    return result


def _declared_types(schema: Mapping[str, JsonValue]) -> tuple[str, ...]:
    value = schema.get("type")
    if isinstance(value, str):
        return (value,)
    if (
        isinstance(value, tuple)
        and value
        and all(isinstance(item, str) for item in value)
    ):
        return value
    raise ValueError("Schema must declare explicit types")


__all__ = [
    "IDENTITY_ARGUMENT_MAPPING_REVISION",
    "RESULT_MAPPING_REVISIONS",
    "SCHEMA_PROJECT_RESULT_MAPPING_REVISION",
    "STRUCTURED_RESULT_MAPPING_REVISION",
    "check_projection_schema",
    "fixed_arguments_match",
    "projection_schema_types",
    "validate_mcp_mapping_policy",
]
