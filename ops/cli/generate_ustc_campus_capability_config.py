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
SERVICE_SRC = ROOT / "services" / "mcp" / "ustc-campus" / "src"
CONFIG_ROOT = Path("configs/capabilities")
sys.path.insert(0, str(SERVICE_SRC))

from ustc_campus_mcp.server import create_mcp


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    service: str
    tool_name: str
    name: str
    description: str
    category: str
    permission: str
    tags: frozenset[str]
    privacy: PrivacyLevel = PrivacyLevel.PUBLIC
    private_only: bool = False
    cost: int = 1
    expected_ms: int = 800
    maximum_ms: int = 90_000


SPECS = (
    CapabilitySpec("ustc.academic.semesters.list.v1", "academic", "catalog_list_semesters", "List USTC semesters", "List official teaching semesters and stable integer semester IDs.", "campus.academic", "capability.ustc.academic.read", frozenset({"academic", "semester", "ustc"})),
    CapabilitySpec("ustc.academic.programs.search.v1", "academic", "catalog_search_programs", "Search USTC training programs", "Search official undergraduate training programs by major, grade and type.", "campus.academic", "capability.ustc.academic.read", frozenset({"academic", "program", "search", "ustc"}), cost=2),
    CapabilitySpec("ustc.academic.program.get.v1", "academic", "catalog_get_program", "Read USTC training program", "Read one official training program with optional shared-module expansion.", "campus.academic", "capability.ustc.academic.read", frozenset({"academic", "program", "ustc"}), cost=3),
    CapabilitySpec("ustc.academic.lessons.search.v1", "academic", "catalog_search_lessons", "Search USTC lessons", "Search the official semester lesson list with local filters and pagination.", "campus.academic", "capability.ustc.academic.read", frozenset({"academic", "course", "lesson", "search", "ustc"}), cost=3),
    CapabilitySpec("ustc.academic.exams.search.v1", "academic", "catalog_search_exams", "Search USTC exams", "Search normalized official scheduled and general exam records.", "campus.academic", "capability.ustc.academic.read", frozenset({"academic", "exam", "search", "ustc"}), cost=3),
    CapabilitySpec("ustc.academic.calendar.get.v1", "academic", "teaching_calendar_get", "Read USTC teaching calendar", "Read the current official teaching-calendar article and its dated events.", "campus.academic", "capability.ustc.academic.read", frozenset({"academic", "calendar", "ustc"})),
    CapabilitySpec("ustc.shuttle.schedule.get.v1", "shuttle", "shuttle_current_schedule", "Read USTC shuttle schedule", "Read the current official shuttle notice, timetable image and revision-bound structured schedule.", "campus.shuttle", "capability.ustc.shuttle.read", frozenset({"bus", "schedule", "shuttle", "ustc"})),
    CapabilitySpec("ustc.shuttle.trips.search.v1", "shuttle", "shuttle_search_trips", "Search USTC shuttle trips", "Search current trips between east, west, research and high-tech campuses.", "campus.shuttle", "capability.ustc.shuttle.read", frozenset({"bus", "search", "shuttle", "ustc"})),
    CapabilitySpec("ustc.young.connection.status.v1", "young", "young_connection_status", "Read second-class connection status", "Report whether the second-class CAS SecretRefs are configured without exposing credentials.", "campus.second-class", "capability.ustc.young.read", frozenset({"authentication", "second-class", "status", "ustc"}), privacy=PrivacyLevel.PERSONAL),
    CapabilitySpec("ustc.young.activities.search.v1", "young", "young_search_activities", "Search USTC second-class activities", "Search authenticated second-class activities through the pinned pyustc adapter.", "campus.second-class", "capability.ustc.young.read", frozenset({"activity", "search", "second-class", "ustc"}), privacy=PrivacyLevel.PERSONAL, cost=3),
    CapabilitySpec("ustc.young.activity.get.v1", "young", "young_get_activity", "Read USTC second-class activity", "Read one second-class activity and optional series children.", "campus.second-class", "capability.ustc.young.read", frozenset({"activity", "detail", "second-class", "ustc"}), privacy=PrivacyLevel.PERSONAL, cost=2),
    CapabilitySpec("ustc.young.facets.list.v1", "young", "young_list_facets", "List USTC second-class filters", "List available module, department or label filters.", "campus.second-class", "capability.ustc.young.read", frozenset({"filter", "second-class", "ustc"}), privacy=PrivacyLevel.PERSONAL, cost=2),
    CapabilitySpec("ustc.young.activities.mine.list.v1", "young", "young_list_my_activities", "List my USTC second-class activities", "List activities associated with the configured CAS service account.", "campus.second-class", "capability.ustc.young.self.read", frozenset({"activity", "personal", "second-class", "ustc"}), privacy=PrivacyLevel.PERSONAL, private_only=True, cost=3),
)


def _tool_catalog() -> dict[tuple[str, str], object]:
    return {
        (service, tool.name): tool
        for service in ("academic", "shuttle", "young")
        for tool in create_mcp(service)._tool_manager.list_tools()
    }


def _string(maximum: int = 4_096, *, nullable: bool = False) -> dict[str, object]:
    return {"type": ["string", "null"] if nullable else "string", "maxLength": maximum}


def _integer(*, nullable: bool = False) -> dict[str, object]:
    return {"type": ["integer", "null"] if nullable else "integer"}


def _number(*, nullable: bool = False) -> dict[str, object]:
    return {"type": ["number", "null"] if nullable else "number"}


def _boolean(*, nullable: bool = False) -> dict[str, object]:
    return {"type": ["boolean", "null"] if nullable else "boolean"}


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


def _array(items: dict[str, object], maximum: int = 100) -> dict[str, object]:
    return {"type": "array", "items": items, "maxItems": maximum}


def _named_schema(*, nullable: bool = True) -> dict[str, object]:
    return _object(
        {
            "id": _integer(nullable=True),
            "code": _string(64, nullable=True),
            "name": _string(300, nullable=True),
        },
        nullable=nullable,
    )


def _source_properties() -> dict[str, object]:
    return {
        "source_url": _string(2_048),
        "fetched_at": _string(64),
    }


def _activity_schema() -> dict[str, object]:
    return _object(
        {
            "activity_id": _string(128),
            "name": _string(500, nullable=True),
            "status": _object({"code": _integer(nullable=True), "text": _string(100)}),
            "kind": _string(32),
            "apply_window": _object({"start": _string(64, nullable=True), "end": _string(64, nullable=True)}),
            "event_window": _object({"start": _string(64, nullable=True), "end": _string(64, nullable=True)}),
            "valid_hours": _number(nullable=True),
            "capacity": _object({"registered": _integer(nullable=True), "limit": _integer(nullable=True)}),
            "is_registered": _boolean(),
            "can_apply": _boolean(),
            "module": _object({"id": _string(128, nullable=True), "name": _string(300, nullable=True)}),
            "department": _object({"id": _string(128, nullable=True), "name": _string(300, nullable=True)}),
            "labels": _array(_object({"id": _string(128, nullable=True), "name": _string(300, nullable=True)}), 100),
            "description": _string(20_000, nullable=True),
            "contact": _string(300, nullable=True),
        },
        required=("activity_id", "status", "kind", "apply_window", "event_window", "capacity", "is_registered", "can_apply", "module", "department", "labels"),
    )


def _young_result_properties(item_schema: dict[str, object]) -> dict[str, object]:
    return {
        "ok": _boolean(),
        "available": _boolean(),
        "authentication": _string(64),
        "error": _string(200, nullable=True),
        "items": _array(item_schema, 100),
        "total": _integer(),
        **_source_properties(),
    }


def _output_schema(capability_id: str) -> dict[str, object]:
    if capability_id == "ustc.academic.semesters.list.v1":
        item = _object({"id": _integer(), "code": _string(32, nullable=True), "name": _string(200, nullable=True), "start": _string(32, nullable=True), "end": _string(32, nullable=True), "is_last": _boolean()})
        return _object({"ok": _boolean(), "items": _array(item), "total": _integer(), "offset": _integer(), "limit": _integer(), **_source_properties()}, required=("ok", "items", "total", "offset", "limit", "source_url", "fetched_at"))
    if capability_id == "ustc.academic.programs.search.v1":
        item = _object({"program_id": _integer(), "name": _string(500, nullable=True), "grade": _string(16, nullable=True), "train_type": _string(100, nullable=True), "department": _object({"code": _string(64, nullable=True), "name": _string(300, nullable=True)}), "major": _object({"code": _string(64, nullable=True), "name": _string(300, nullable=True)})})
        return _object({"ok": _boolean(), "items": _array(item), "total": _integer(), "offset": _integer(), "limit": _integer(), **_source_properties()}, required=("ok", "items", "total", "offset", "limit", "source_url", "fetched_at"))
    if capability_id == "ustc.academic.program.get.v1":
        course = _object({"course_id": _integer(nullable=True), "code": _string(64, nullable=True), "name": _string(500, nullable=True), "name_en": _string(500, nullable=True), "credits": _number(nullable=True), "compulsory": _boolean(), "terms": _array(_string(32), 32), "exam_mode": _string(200, nullable=True), "department": _named_schema(), "introduction": _string(20_000, nullable=True)})
        module = _object({"module_id": _integer(nullable=True), "parent_id": _integer(nullable=True), "level": _integer(), "name": _string(300, nullable=True), "name_en": _string(300, nullable=True), "remark": _string(2_000, nullable=True), "required_credits": _number(nullable=True), "required_course_count": _integer(nullable=True), "shared_module_id": _integer(nullable=True), "expanded_shared": _boolean(), "courses": _array(course, 500)})
        program = _object({"train_type": _string(100, nullable=True), "grade": _string(16, nullable=True), "education": _string(100), "student_type": _string(100), "department": _named_schema(), "major": _named_schema(), "major_direction": _named_schema(), "required_credits": _number(nullable=True), "award_degree": _boolean(), "begin_semester": _string(100, nullable=True), "modules": _array(module, 2_000)})
        return _object({"ok": _boolean(), "program_id": _integer(), "requested_term": _string(32, nullable=True), "program": program, "shared_modules": _array(module, 2_000), "source_url": _string(2_048), "api_source": _string(2_048), "fetched_at": _string(64)}, required=("ok", "program_id", "requested_term", "program", "shared_modules", "source_url", "api_source", "fetched_at"))
    if capability_id == "ustc.academic.lessons.search.v1":
        item = _object({"lesson_id": _integer(nullable=True), "lesson_code": _string(64, nullable=True), "course_code": _string(64, nullable=True), "course_name": _string(500, nullable=True), "course_name_en": _string(500, nullable=True), "credits": _number(nullable=True), "period": _integer(nullable=True), "teachers": _array(_string(200), 32), "department": _object({"code": _string(64, nullable=True), "name": _string(300, nullable=True)}), "campus": _string(100), "education": _string(100), "class_type": _string(200), "course_type": _string(200), "course_classify": _string(200), "schedule": _string(4_000), "student_count": _integer(nullable=True), "limit_count": _integer(nullable=True), "exam_mode": _string(200)})
        return _object({"ok": _boolean(), "items": _array(item), "total": _integer(), "offset": _integer(), "limit": _integer(), "semester_id": _integer(), "freshness_notice": _string(500), **_source_properties()}, required=("ok", "items", "total", "offset", "limit", "semester_id", "freshness_notice", "source_url", "fetched_at"))
    if capability_id == "ustc.academic.exams.search.v1":
        room = _object({"room": _string(200, nullable=True), "count": _integer(nullable=True)})
        item = _object({"exam_id": _integer(nullable=True), "course_code": _string(64, nullable=True), "course_name": _string(500, nullable=True), "course_name_en": _string(500, nullable=True), "date": _string(64, nullable=True), "start_time": _integer(nullable=True), "end_time": _integer(nullable=True), "type": _string(200), "rooms": _array(room, 32), "teachers": _array(_string(200), 32), "department": _object({"code": _string(64, nullable=True), "name": _string(300, nullable=True)}), "education": _string(100), "grades": _string(500, nullable=True), "admin_classes": _string(2_000, nullable=True), "exam_mode": _string(200, nullable=True), "source_kind": _string(32)})
        return _object({"ok": _boolean(), "items": _array(item), "total": _integer(), "offset": _integer(), "limit": _integer(), "semester_id": _integer(), **_source_properties()}, required=("ok", "items", "total", "offset", "limit", "semester_id", "source_url", "fetched_at"))
    if capability_id == "ustc.academic.calendar.get.v1":
        day = _object({"date": _string(16), "week": _string(32), "event": _string(2_000)})
        return _object({"ok": _boolean(), "semester": _string(200), "last_modified": _string(100, nullable=True), "days": _array(day, 400), "events": _array(day, 400), "notes": _array(_string(2_000), 32), "source_note": _string(500), **_source_properties()}, required=("ok", "semester", "days", "events", "notes", "source_note", "source_url", "fetched_at"))
    stop_times = _object({"east": _string(8, nullable=True), "west": _string(8, nullable=True), "research": _string(8, nullable=True), "hightech": _string(8, nullable=True)})
    if capability_id == "ustc.shuttle.schedule.get.v1":
        route = _object({"direction": _string(64), "stops": _array(_string(32), 8), "trips": _array(stop_times, 32)})
        return _object({"ok": _boolean(), "title": _string(300), "structured": _boolean(), "valid_from": _string(16, nullable=True), "valid_to": _string(16, nullable=True), "routes": _array(route, 8), "notice": _string(1_000), "image_url": _string(2_048), **_source_properties()}, required=("ok", "title", "structured", "routes", "notice", "image_url", "source_url", "fetched_at"))
    if capability_id == "ustc.shuttle.trips.search.v1":
        item = _object({"direction": _string(64), "from": _string(32), "to": _string(32), "departure": _string(8, nullable=True), "arrival": _string(8, nullable=True), "stop_times": stop_times, "time_notice": _string(500)})
        return _object({"ok": _boolean(), "from_station": _string(32), "to_station": _string(32), "items": _array(item, 32), "total": _integer(), "structured": _boolean(), "valid_from": _string(16, nullable=True), "valid_to": _string(16, nullable=True), "image_url": _string(2_048), **_source_properties()}, required=("ok", "from_station", "to_station", "items", "total", "structured", "image_url", "source_url", "fetched_at"))
    if capability_id == "ustc.young.connection.status.v1":
        return _object({"ok": _boolean(), "available": _boolean(), "authentication": _string(64), "reason": _string(500, nullable=True), "provider": _string(100), "provider_revision": _string(128), "fetched_at": _string(64)}, required=("ok", "available", "authentication", "provider", "provider_revision", "fetched_at"))
    activity = _activity_schema()
    if capability_id in {"ustc.young.activities.search.v1", "ustc.young.activities.mine.list.v1"}:
        properties = _young_result_properties(activity)
        properties["account_scoped"] = _boolean()
        return _object(properties, required=("ok", "available", "authentication", "items", "total", "source_url", "fetched_at"))
    if capability_id == "ustc.young.activity.get.v1":
        properties = _young_result_properties(activity)
        properties.update({"activity": _object(activity["properties"], required=tuple(activity["required"]), nullable=True), "children": _array(activity, 100)})
        return _object(properties, required=("ok", "available", "authentication", "items", "total", "source_url", "fetched_at"))
    if capability_id == "ustc.young.facets.list.v1":
        facet = _object({"id": _string(128, nullable=True), "name": _string(300, nullable=True), "level": _integer(nullable=True)})
        return _object(_young_result_properties(facet), required=("ok", "available", "authentication", "items", "total", "source_url", "fetched_at"))
    raise KeyError(capability_id)


def _schema_document(schema_id: str, value: dict[str, object]) -> CapabilitySchemaDocument:
    reference = SchemaRef(schema_id, 1, canonical_schema_digest(value, schema_id=schema_id, schema_version=1))
    return CapabilitySchemaDocument(1, reference, value)


def _provider(server_id: str) -> ProviderRef:
    artifact = canonical_digest(
        {"adapter": "dududa.capabilities.McpCapabilityProvider", "server_id": server_id, "argument_mapping": "identity-v1", "result_mapping": "schema-project-v1"},
        domain="capability.provider-artifact:v1",
    )
    return ProviderRef(
        f"mcp.{server_id}",
        ComponentRevision("capability-provider.mcp", "1.0.0", f"{server_id}-read-v1", DigestString(str(artifact))),
    )


def _plain(value):
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _definition(spec: CapabilitySpec, input_schema: CapabilitySchemaDocument, output_schema: CapabilitySchemaDocument) -> CapabilityDefinition:
    contexts = frozenset({ConversationType.PRIVATE}) if spec.private_only else frozenset({ConversationType.PRIVATE, ConversationType.GROUP})
    values = {
        "schema_version": 1,
        "capability_id": spec.capability_id,
        "name": spec.name,
        "description": spec.description,
        "category": spec.category,
        "provider": _provider(f"ustc-{spec.service}"),
        "input_schema": input_schema.schema_ref,
        "output_schema": output_schema.schema_ref,
        "risk_level": RiskLevel.LOW,
        "privacy_level": spec.privacy,
        "allowed_contexts": contexts,
        "required_permissions": frozenset({spec.permission}),
        "cost_hint": CostHint(spec.cost),
        "latency_hint": LatencyHint(spec.expected_ms, spec.maximum_ms),
        "tags": spec.tags,
        "idempotency": Idempotency.READ_ONLY,
        "side_effects": frozenset({SideEffect.NETWORK_READ}),
        "enabled": True,
    }
    return CapabilityDefinition(definition_digest=capability_definition_digest(values), **values)


def _mapping(spec: CapabilitySpec, definition: CapabilityDefinition, tool: object) -> McpCapabilityMapping:
    server_id = f"ustc-{spec.service}"
    input_digest = canonical_schema_digest(tool.parameters, schema_id=f"mcp.{server_id}.{spec.tool_name}.input", schema_version=1)
    output_digest = canonical_schema_digest(tool.fn_metadata.output_schema, schema_id=f"mcp.{server_id}.{spec.tool_name}.output", schema_version=1)
    values = {
        "schema_version": 1,
        "capability_id": spec.capability_id,
        "capability_definition_digest": definition.definition_digest,
        "server_id": server_id,
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
    return {"schema_id": reference.schema_id, "schema_version": reference.schema_version, "digest": str(reference.digest), "document": _plain(document.document)}


def _definition_config(definition: CapabilityDefinition, input_schema: CapabilitySchemaDocument, output_schema: CapabilitySchemaDocument) -> dict[str, object]:
    revision = definition.provider.revision
    return {
        "schema_version": definition.schema_version,
        "capability_id": definition.capability_id,
        "definition_digest": str(definition.definition_digest),
        "name": definition.name,
        "description": definition.description,
        "category": definition.category,
        "provider": {"provider_id": definition.provider.provider_id, "revision": {"component_id": revision.component_id, "implementation_version": revision.implementation_version, "config_revision": revision.config_revision, "artifact_digest": str(revision.artifact_digest)}},
        "provider_kind": CapabilityProviderKind.MCP.value,
        "input_schema": _schema_config(input_schema),
        "output_schema": _schema_config(output_schema),
        "risk_level": definition.risk_level.value,
        "privacy_level": definition.privacy_level.value,
        "allowed_contexts": sorted(item.value for item in definition.allowed_contexts),
        "required_permissions": sorted(definition.required_permissions),
        "cost_hint_units": definition.cost_hint.units,
        "latency_hint": {"expected_ms": definition.latency_hint.expected_ms, "maximum_ms": definition.latency_hint.maximum_ms},
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
        tool = tools[(spec.service, spec.tool_name)]
        input_value = copy.deepcopy(tool.parameters)
        input_value["additionalProperties"] = False
        output_value = _output_schema(spec.capability_id)
        input_schema = _schema_document(f"capability.{spec.capability_id}.input", input_value)
        output_schema = _schema_document(f"capability.{spec.capability_id}.output", output_value)
        definition = _definition(spec, input_schema, output_schema)
        mapping = _mapping(spec, definition, tool)
        documents[CONFIG_ROOT / "definitions" / f"{spec.capability_id}.json"] = json.dumps(_definition_config(definition, input_schema, output_schema), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        documents[CONFIG_ROOT / "mappings" / f"{spec.capability_id}.json"] = json.dumps(_mapping_config(mapping), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
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
        print("outdated USTC campus Capability configuration:")
        for item in mismatches:
            print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
