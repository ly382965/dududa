from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dududa.capabilities import (
    CapabilityProviderKind,
    CapabilitySchemaDocument,
    McpCapabilityMapping,
    capability_definition_digest,
    mcp_capability_mapping_digest,
)
from dududa.contracts.canonical import canonical_digest, canonical_schema_digest
from dududa.domain.capability import (
    CapabilityDefinition,
    CostHint,
    Idempotency,
    LatencyHint,
    ProviderRef,
)
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    PrivacyLevel,
    RiskLevel,
    SchemaRef,
    SideEffect,
)
from dududa.mcp import McpOperationSemantics

ROOT = Path(__file__).resolve().parents[2]
SERVICE_SRC = ROOT / "services" / "mcp" / "notifai" / "src"
CONFIG_ROOT = Path("configs/capabilities")
sys.path.insert(0, str(SERVICE_SRC))

from notifai_mcp.config import AppConfig
from notifai_mcp.server import create_mcp


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    tool_name: str
    name: str
    description: str
    tags: frozenset[str]
    cost: int = 1


SPECS = (
    CapabilitySpec(
        "notifai.notices.search.v1",
        "search_notices",
        "Search campus notices",
        "Search public campus notices by keyword, source, category, date, or deadline.",
        frozenset({"campus", "notice", "search", "announcement", "notifai"}),
        cost=3,
    ),
    CapabilitySpec(
        "notifai.notices.get.v1",
        "get_notice",
        "Read a campus notice",
        "Read one public campus notice and its cleaned content by stable notice ID.",
        frozenset({"campus", "notice", "detail", "notifai"}),
        cost=2,
    ),
    CapabilitySpec(
        "notifai.notices.calendar.v1",
        "get_notice_calendar",
        "Read notice calendar",
        "Read public campus notices occurring in one requested month or ISO week.",
        frozenset({"campus", "notice", "calendar", "notifai"}),
    ),
    CapabilitySpec(
        "notifai.notices.deadlines.v1",
        "get_notice_deadlines",
        "Read notice deadlines",
        "Read public campus notices with deadlines in a bounded future date window.",
        frozenset({"campus", "notice", "deadline", "notifai"}),
        cost=2,
    ),
    CapabilitySpec(
        "notifai.sources.list.v1",
        "list_notice_sources",
        "List notice sources",
        "List public campus-notice sources and their current counts.",
        frozenset({"campus", "notice", "source", "filter", "notifai"}),
    ),
    CapabilitySpec(
        "notifai.categories.list.v1",
        "list_notice_categories",
        "List notice categories",
        "List the public campus-notice category dictionary and current counts.",
        frozenset({"campus", "notice", "category", "filter", "notifai"}),
    ),
    CapabilitySpec(
        "notifai.stats.read.v1",
        "get_notice_stats",
        "Read notice statistics",
        "Read aggregate counts and the latest synchronization time for public campus notices.",
        frozenset({"campus", "notice", "statistics", "notifai"}),
    ),
)


def _tool_catalog() -> dict[str, object]:
    return {tool.name: tool for tool in create_mcp(AppConfig())._tool_manager.list_tools()}


def _string(maximum: int = 4096, *, nullable: bool = False) -> dict[str, object]:
    return {"type": ["string", "null"] if nullable else "string", "maxLength": maximum}


def _integer(*, nullable: bool = False) -> dict[str, object]:
    return {"type": ["integer", "null"] if nullable else "integer"}


def _array(items: dict[str, object], maximum: int = 100) -> dict[str, object]:
    return {"type": "array", "items": items, "maxItems": maximum}


def _object(
    properties: dict[str, object],
    *,
    required: tuple[str, ...] = (),
    nullable: bool = False,
) -> dict[str, object]:
    return {
        "type": ["object", "null"] if nullable else "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _notice_schema() -> dict[str, object]:
    attachment = _object(
        {"name": _string(300), "url": _string(2048)},
        required=("name", "url"),
    )
    properties = {
        "id": _string(200),
        "title": _string(500),
        "source": _string(200),
        "categories": _array(_string(100), 20),
        "publishDate": _string(10),
        "aiSummary": _string(1600),
        "deadline": _string(10, nullable=True),
        "targetAudience": _string(800),
        "coreAction": _string(1200),
        "originUrl": _string(2048),
        "cleanContent": _string(12000),
        "firstSeen": _string(80, nullable=True),
        "lastCrawl": _string(80, nullable=True),
        "attachments": _array(attachment, 20),
    }
    return _object(properties, required=tuple(properties))


def _calendar_item_schema() -> dict[str, object]:
    return _object(
        {
            "id": _string(200),
            "title": _string(500),
            "source": _string(200),
            "publishDate": _string(10),
            "deadline": _string(10, nullable=True),
        },
        required=("id", "title", "source", "publishDate", "deadline"),
    )


def _deadline_item_schema() -> dict[str, object]:
    return _object(
        {
            "id": _string(200),
            "title": _string(500),
            "source": _string(200),
            "publishDate": _string(10),
            "deadline": _string(10, nullable=True),
            "aiSummary": _string(1600),
            "targetAudience": _string(800),
        },
        required=(
            "id",
            "title",
            "source",
            "publishDate",
            "deadline",
            "aiSummary",
            "targetAudience",
        ),
    )


def _error_schema() -> dict[str, object]:
    return _object(
        {
            "code": _string(100),
            "message": _string(500),
            "retryable": {"type": "boolean"},
            "status": _integer(nullable=True),
        },
        required=("code", "message", "retryable"),
        nullable=True,
    )


def _envelope(data: dict[str, object]) -> dict[str, object]:
    nullable_data = copy.deepcopy(data)
    data_type = nullable_data.get("type")
    if isinstance(data_type, str):
        nullable_data["type"] = [data_type, "null"]
    elif isinstance(data_type, list) and "null" not in data_type:
        nullable_data["type"] = [*data_type, "null"]
    return _object(
        {
            "schema_version": {"type": "integer", "const": 1},
            "ok": {"type": "boolean"},
            "data": nullable_data,
            "error": _error_schema(),
            "source": {"type": "string", "const": "notifai", "maxLength": 32},
            "observed_at": _string(64),
            "warnings": _array(_string(200), 32),
        },
        required=("schema_version", "ok", "data", "error", "source", "observed_at", "warnings"),
    )


def _output_schema(capability_id: str) -> dict[str, object]:
    notice = _notice_schema()
    if capability_id == "notifai.notices.search.v1":
        return _envelope(
            _object(
                {
                    "items": _array(notice),
                    "total": _integer(),
                    "nextCursor": _string(2000, nullable=True),
                },
                required=("items", "total", "nextCursor"),
            )
        )
    if capability_id == "notifai.notices.get.v1":
        return _envelope(notice)
    if capability_id == "notifai.notices.calendar.v1":
        return _envelope(
            _object({"items": _array(_calendar_item_schema())}, required=("items",))
        )
    if capability_id == "notifai.notices.deadlines.v1":
        return _envelope(
            _object(
                {"items": _array(_deadline_item_schema()), "total": _integer()},
                required=("items", "total"),
            )
        )
    if capability_id == "notifai.sources.list.v1":
        source = _object(
            {"name": _string(200), "group": _string(80), "noticeCount": _integer()},
            required=("name", "group", "noticeCount"),
        )
        return _envelope(_object({"items": _array(source)}, required=("items",)))
    if capability_id == "notifai.categories.list.v1":
        category = _object(
            {
                "key": _string(100),
                "name": _string(200),
                "description": _string(800),
                "noticeCount": _integer(),
            },
            required=("key", "name", "description", "noticeCount"),
        )
        return _envelope(_object({"items": _array(category)}, required=("items",)))
    if capability_id == "notifai.stats.read.v1":
        return _envelope(
            _object(
                {
                    "total": _integer(),
                    "sourceCount": _integer(),
                    "last7DaysDdl": _integer(),
                    "last24hNew": _integer(),
                    "lastCrawlAt": _string(80, nullable=True),
                },
                required=("total", "sourceCount", "last7DaysDdl", "last24hNew", "lastCrawlAt"),
            )
        )
    raise KeyError(capability_id)


def _plain(value: object) -> object:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _schema_document(schema_id: str, value: dict[str, object]) -> CapabilitySchemaDocument:
    reference = SchemaRef(schema_id, 1, canonical_schema_digest(value, schema_id=schema_id, schema_version=1))
    return CapabilitySchemaDocument(1, reference, value)


def _provider() -> ProviderRef:
    artifact = canonical_digest(
        {
            "adapter": "dududa.capabilities.McpCapabilityProvider",
            "server_id": "notifai",
            "argument_mapping": "identity-v1",
            "result_mapping": "schema-project-v1",
        },
        domain="capability.provider-artifact:v1",
    )
    return ProviderRef(
        "mcp.notifai",
        ComponentRevision(
            "capability-provider.mcp",
            "1.0.0",
            "notifai-read-v1",
            DigestString(str(artifact)),
        ),
    )


def _definition(
    spec: CapabilitySpec,
    input_schema: CapabilitySchemaDocument,
    output_schema: CapabilitySchemaDocument,
) -> CapabilityDefinition:
    values = {
        "schema_version": 1,
        "capability_id": spec.capability_id,
        "name": spec.name,
        "description": spec.description,
        "category": "campus.notifications",
        "provider": _provider(),
        "input_schema": input_schema.schema_ref,
        "output_schema": output_schema.schema_ref,
        "risk_level": RiskLevel.LOW,
        # The source data is public, while the query itself is formed from one
        # conversation. This matches the remote academic capability semantics.
        "privacy_level": PrivacyLevel.CONVERSATION,
        "allowed_contexts": frozenset({ConversationType.PRIVATE, ConversationType.GROUP}),
        "required_permissions": frozenset({"capability.notifai.read"}),
        "cost_hint": CostHint(spec.cost),
        "latency_hint": LatencyHint(800, 90_000),
        "tags": spec.tags,
        "idempotency": Idempotency.READ_ONLY,
        "side_effects": frozenset({SideEffect.NETWORK_READ}),
        "enabled": True,
    }
    return CapabilityDefinition(definition_digest=capability_definition_digest(values), **values)


def _mapping(
    spec: CapabilitySpec,
    definition: CapabilityDefinition,
    tool: object,
) -> McpCapabilityMapping:
    input_digest = canonical_schema_digest(
        tool.parameters,
        schema_id=f"mcp.notifai.{spec.tool_name}.input",
        schema_version=1,
    )
    output_digest = canonical_schema_digest(
        tool.fn_metadata.output_schema,
        schema_id=f"mcp.notifai.{spec.tool_name}.output",
        schema_version=1,
    )
    values = {
        "schema_version": 1,
        "capability_id": spec.capability_id,
        "capability_definition_digest": definition.definition_digest,
        "server_id": "notifai",
        "tool_name": spec.tool_name,
        "expected_input_schema_digest": input_digest,
        "expected_output_schema_digest": output_digest,
        "semantics": McpOperationSemantics.READ_ONLY,
        "fixed_arguments": {},
        "argument_mapping_revision": "identity-v1",
        "result_mapping_revision": "schema-project-v1",
        "enabled": True,
    }
    return McpCapabilityMapping(mapping_digest=mcp_capability_mapping_digest(values), **values)


def _schema_config(document: CapabilitySchemaDocument) -> dict[str, object]:
    reference = document.schema_ref
    return {
        "schema_id": reference.schema_id,
        "schema_version": reference.schema_version,
        "digest": str(reference.digest),
        "document": _plain(document.document),
    }


def _definition_config(
    definition: CapabilityDefinition,
    input_schema: CapabilitySchemaDocument,
    output_schema: CapabilitySchemaDocument,
) -> dict[str, object]:
    revision = definition.provider.revision
    return {
        "schema_version": definition.schema_version,
        "capability_id": definition.capability_id,
        "definition_digest": str(definition.definition_digest),
        "name": definition.name,
        "description": definition.description,
        "category": definition.category,
        "provider": {
            "provider_id": definition.provider.provider_id,
            "revision": {
                "component_id": revision.component_id,
                "implementation_version": revision.implementation_version,
                "config_revision": revision.config_revision,
                "artifact_digest": str(revision.artifact_digest),
            },
        },
        "provider_kind": CapabilityProviderKind.MCP.value,
        "input_schema": _schema_config(input_schema),
        "output_schema": _schema_config(output_schema),
        "risk_level": definition.risk_level.value,
        "privacy_level": definition.privacy_level.value,
        "allowed_contexts": sorted(item.value for item in definition.allowed_contexts),
        "required_permissions": sorted(definition.required_permissions),
        "cost_hint_units": definition.cost_hint.units,
        "latency_hint": {
            "expected_ms": definition.latency_hint.expected_ms,
            "maximum_ms": definition.latency_hint.maximum_ms,
        },
        "tags": sorted(definition.tags),
        "idempotency": definition.idempotency.value,
        "side_effects": sorted(item.value for item in definition.side_effects),
        "enabled": definition.enabled,
    }


def _mapping_config(mapping: McpCapabilityMapping) -> dict[str, object]:
    return {
        "schema_version": mapping.schema_version,
        "capability_id": mapping.capability_id,
        "capability_definition_digest": str(mapping.capability_definition_digest),
        "server_id": mapping.server_id,
        "tool_name": mapping.tool_name,
        "expected_input_schema_digest": str(mapping.expected_input_schema_digest),
        "expected_output_schema_digest": str(mapping.expected_output_schema_digest),
        "semantics": mapping.semantics.value,
        "fixed_arguments": _plain(mapping.fixed_arguments),
        "argument_mapping_revision": mapping.argument_mapping_revision,
        "result_mapping_revision": mapping.result_mapping_revision,
        "enabled": mapping.enabled,
        "mapping_digest": str(mapping.mapping_digest),
    }


def rendered_documents() -> dict[Path, str]:
    tools = _tool_catalog()
    documents: dict[Path, str] = {}
    for spec in SPECS:
        tool = tools[spec.tool_name]
        input_value = copy.deepcopy(tool.parameters)
        input_value["additionalProperties"] = False
        input_schema = _schema_document(
            f"capability.{spec.capability_id}.input",
            input_value,
        )
        output_schema = _schema_document(
            f"capability.{spec.capability_id}.output",
            _output_schema(spec.capability_id),
        )
        definition = _definition(spec, input_schema, output_schema)
        mapping = _mapping(spec, definition, tool)
        documents[
            CONFIG_ROOT / "definitions" / f"{spec.capability_id}.json"
        ] = json.dumps(
            _definition_config(definition, input_schema, output_schema),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        ) + "\n"
        documents[
            CONFIG_ROOT / "mappings" / f"{spec.capability_id}.json"
        ] = json.dumps(
            _mapping_config(mapping),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        ) + "\n"
    return documents


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    mismatches: list[str] = []
    for relative, expected in rendered_documents().items():
        target = args.root / relative
        if args.write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(expected, encoding="utf-8")
        elif not target.exists() or target.read_text(encoding="utf-8") != expected:
            mismatches.append(str(relative))
    if mismatches:
        print("outdated NotifAI Capability configuration:")
        for item in mismatches:
            print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
