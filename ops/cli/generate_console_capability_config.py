"""Generate the five cache-only workbench capabilities, without Runtime grants."""
from __future__ import annotations

import argparse
import copy
import importlib
import json
import sys
import tempfile
from pathlib import Path

from generate_ustc_campus_capability_config import (
    _array, _boolean, _definition_config, _integer, _mapping_config,
    _number, _object, _provider, _schema_document, _string,
)
from dududa.capabilities import McpCapabilityMapping, capability_definition_digest, mcp_capability_mapping_digest
from dududa.contracts.canonical import canonical_schema_digest
from dududa.domain.capability import CapabilityDefinition, CostHint, Idempotency, LatencyHint
from dududa.domain.primitives import ConversationType, PrivacyLevel, RiskLevel, SideEffect
from dududa.mcp import McpOperationSemantics

ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = Path("configs/console-capabilities")
SPECS = (
    ("campus-events", "campus_events_public_query", "校园公告", 200, 20),
    ("college-notice", "college_notices_public_query", "学院通知", 200, 20),
    ("library", "library_hours_public_query", "图书馆开放时间", 120, 30),
    ("local-recs", "local_recommendations_public_query", "校园生活参考（非实时）", 120, 10),
    ("training-plan", "training_programs_public_query", "本科专业设置", 160, 30),
)


def obj(properties):
    return _object(properties, required=tuple(properties))


def output_schema(server_id, query_limit, result_limit):
    string = _string
    nullable = lambda size: string(size, nullable=True)
    extra = {}
    if server_id in {"campus-events", "college-notice"}:
        item = {"title": string(500), "published_at": string(64), "summary": string(1600),
                "source_url": string(2048), "observed_at": string(64),
                "attachments": _array(obj({"name": string(240), "url": string(2048)}), 10)}
        if server_id == "campus-events":
            item.update(event_id=string(160), category=string(32))
            extra["category"] = nullable(32)
        else:
            item.update(notice_id=string(200), college_key=string(64))
            extra["college_key"] = nullable(64)
    elif server_id == "library":
        item = {"campus": string(32), "location": string(240), "service": string(500),
                "weekday": nullable(160), "weekend": nullable(160), "phone": nullable(80)}
        extra["campus"] = nullable(32)
    elif server_id == "training-plan":
        item = {"year": _integer(), "college": string(200), "department": nullable(200),
                "major": string(200), "code": nullable(32), "degree": nullable(32), "discontinued": _boolean()}
        extra.update(year=_integer(nullable=True), college=nullable(200))
    else:
        item = {"id": _integer(), "kind": string(24), "name": string(240), "detail": string(800),
                "location": string(240), "score": _number(), "proximity": string(160),
                "tags": _array(string(80), 12), "source": string(120), "campus": string(32),
                "meal_time": _array(string(16), 8), "price_level": string(32),
                "opening_hours": {"type": "object", "maxProperties": 16,
                                  "propertyNames": {"maxLength": 24}, "additionalProperties": string(80)}}
        extra.update(kind=nullable(24), campus=nullable(32), meal_time=nullable(16), price_level=nullable(32))
    return obj({"schema_version": {"type": "integer", "const": 1}, "ok": _boolean(),
                "query": string(query_limit), "items": _array(obj(item), result_limit),
                "returned": {"type": "integer", "minimum": 0, "maximum": result_limit},
                "source": string(120), "source_url": nullable(2048), "fetched_at": nullable(64),
                "freshness_note": string(500), **extra})


def rendered_documents():
    documents = {}
    with tempfile.TemporaryDirectory(prefix="dududa-console-schema-") as temporary:
        for server_id, tool_name, name, query_limit, result_limit in SPECS:
            sys.path.insert(0, str(ROOT / "services/mcp" / server_id / "src"))
            module = server_id.replace("-", "_") + "_mcp"
            config = importlib.import_module(f"{module}.config").AppConfig(db_path=Path(temporary) / f"{server_id}.db")
            mcp = importlib.import_module(f"{module}.server").create_mcp(config)
            tool = next(tool for tool in mcp._tool_manager.list_tools() if tool.name == tool_name)
            cid = f"console.{server_id}.query.v1"
            input_value = copy.deepcopy(tool.parameters)
            input_value["additionalProperties"] = False
            input_value["properties"]["query"]["maxLength"] = query_limit
            input_value["properties"]["query"]["default"] = ""
            input_value["properties"]["limit"].update(minimum=1, maximum=result_limit)
            for key, prop in input_value["properties"].items():
                if key != "query" and prop.get("type") == "string":
                    prop["maxLength"] = 200
            input_doc = _schema_document(f"capability.{cid}.input", input_value)
            output_doc = _schema_document(f"capability.{cid}.output", output_schema(server_id, query_limit, result_limit))
            values = dict(schema_version=1, capability_id=cid, name=name,
                          description=f"{name}：只读缓存查询；query 留空可浏览。结果附数据来源和时效说明，不自动授权群聊。",
                          category=f"console.{server_id}", provider=_provider(server_id),
                          input_schema=input_doc.schema_ref, output_schema=output_doc.schema_ref,
                          risk_level=RiskLevel.LOW, privacy_level=PrivacyLevel.CONVERSATION,
                          allowed_contexts=frozenset({ConversationType.PRIVATE}),
                          required_permissions=frozenset({f"console.{server_id}.read"}),
                          cost_hint=CostHint(1), latency_hint=LatencyHint(300, 30000),
                          tags=frozenset({"console-only", "cache-only", "read-only"}),
                          idempotency=Idempotency.READ_ONLY, side_effects=frozenset({SideEffect.NONE}), enabled=True)
            definition = CapabilityDefinition(definition_digest=capability_definition_digest(values), **values)
            mapping_values = dict(schema_version=1, capability_id=cid, capability_definition_digest=definition.definition_digest,
                                  server_id=server_id, tool_name=tool_name, semantics=McpOperationSemantics.READ_ONLY,
                                  expected_input_schema_digest=canonical_schema_digest(tool.parameters, schema_id=f"mcp.{server_id}.{tool_name}.input", schema_version=1),
                                  expected_output_schema_digest=canonical_schema_digest(tool.fn_metadata.output_schema, schema_id=f"mcp.{server_id}.{tool_name}.output", schema_version=1),
                                  fixed_arguments={}, argument_mapping_revision="identity-v1", result_mapping_revision="schema-project-v1", enabled=True)
            mapping = McpCapabilityMapping(mapping_digest=mcp_capability_mapping_digest(mapping_values), **mapping_values)
            for folder, document in (("definitions", _definition_config(definition, input_doc, output_doc)), ("mappings", _mapping_config(mapping))):
                documents[CONFIG_ROOT / folder / f"{cid}.json"] = json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    return documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches = []
    for relative, expected in rendered_documents().items():
        target = ROOT / relative
        if args.write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(expected, encoding="utf-8")
        elif not target.exists() or target.read_text(encoding="utf-8") != expected:
            mismatches.append(str(relative))
    if mismatches:
        print("Outdated console capability documents: " + ", ".join(mismatches))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
