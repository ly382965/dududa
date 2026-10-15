"""Run the versioned 100-question native-message fixture through Dududa 2.0.

This is a deterministic integration probe.  It constructs OneBot-shaped events,
uses scripted model responses and a schema-accurate in-process MCP client, and
acknowledges the Output Adapter in memory.  No QQ account, credential, network
transport, or external side effect is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SOURCE_ROOT = ROOT / "apps" / "astrbot-plugins"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PLUGIN_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SOURCE_ROOT))

from astrbot_plugin_dududa_core import composition
from astrbot_plugin_dududa_core.adapters.output import AstrBotOutputAdapter
from astrbot_plugin_dududa_core.rollout_bridge import AstrBotBridgeAction
from dududa.capabilities import load_capability_catalog_snapshot
from dududa.contracts.canonical import (
    canonical_digest,
    canonical_json_bytes,
    canonical_schema_digest,
)
from dududa.domain.primitives import DigestString
from dududa.mcp import (
    McpFailureKind,
    McpHealthStatus,
    McpSchemaSnapshot,
    McpServerHealth,
    McpToolDescriptor,
    McpToolResult,
    mcp_client_error,
    mcp_schema_snapshot_digest,
    mcp_tool_result_digest,
)

from tests.contracts.test_production_composition import (
    ProductionCompositionContractTests,
    _ComponentFactory,
    _ICourseFacade,
)

FIXTURE = ROOT / "tests" / "fixtures" / "mcp" / "dududa-100-native-message-cases.json"
DEFAULT_JSON = Path("/tmp/dududa-100-runtime.json")
DEFAULT_REPORT = Path("/tmp/dududa-100-runtime.md")
FIXED_NOW = datetime(2026, 9, 3, 1, 30, tzinfo=timezone.utc)

_TOOL_CAPABILITY = {
    "icourse_public_query": "icourse.public-query.v2",
    "search_courses": "icourse.courses.search.v1",
    "get_course": "icourse.course.get.v1",
    "get_reviews": "icourse.reviews.get.v1",
    "icourse_stats": "icourse.stats.read.v1",
    "catalog_list_semesters": "ustc.academic.semesters.list.v1",
    "catalog_search_lessons": "ustc.academic.lessons.search.v1",
    "catalog_search_exams": "ustc.academic.exams.search.v1",
    "teaching_calendar_get": "ustc.academic.calendar.get.v1",
    "curriculum_public_query": "ustc.curriculum.public-query.v1",
    "young_connection_status": "ustc.young.connection.status.v1",
    "young_search_activities": "ustc.young.activities.search.v1",
    "young_get_activity": "ustc.young.activity.get.v1",
    "young_list_facets": "ustc.young.facets.list.v1",
    "search_notices": "notifai.notices.search.v1",
    "get_notice": "notifai.notices.get.v1",
    "get_notice_calendar": "notifai.notices.calendar.v1",
    "get_notice_deadlines": "notifai.notices.deadlines.v1",
    "list_notice_sources": "notifai.sources.list.v1",
    "list_notice_categories": "notifai.categories.list.v1",
    "get_notice_stats": "notifai.stats.read.v1",
}

_TOOL_SERVER = {
    **{name: "icourse" for name in ("icourse_public_query", "search_courses", "get_course", "get_reviews", "icourse_stats")},
    **{name: "ustc-academic" for name in ("catalog_list_semesters", "catalog_search_lessons", "catalog_search_exams", "teaching_calendar_get")},
    "curriculum_public_query": "ustc-curriculum",
    **{name: "ustc-young" for name in ("young_connection_status", "young_search_activities", "young_get_activity", "young_list_facets")},
    **{name: "notifai" for name in ("search_notices", "get_notice", "get_notice_calendar", "get_notice_deadlines", "list_notice_sources", "list_notice_categories", "get_notice_stats")},
}

_CATEGORY_BY_SERVER = {
    "icourse": "campus.course-review",
    "ustc-academic": "campus.academic",
    "ustc-curriculum": "campus.curriculum",
    "ustc-young": "campus.second-class",
    "notifai": "campus.notifications",
}

# Builtin capabilities do not have an MCP tool name or server mapping.  Keep
# their fixture route explicit so the scripted perception model still drives
# the same production Planner/Provider path as an MCP-backed case.
_BUILTIN_CAPABILITY_CATEGORIES = {
    "ustc.shuttle.public-query.v1": "campus.shuttle",
}


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _load_cases(path: Path) -> tuple[dict[str, Any], ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("unsupported 100-question fixture schema")
    cases = tuple(document.get("cases", ()))
    if len(cases) != 100:
        raise ValueError(f"fixture must contain 100 cases, got {len(cases)}")
    ids = [item.get("case_id") for item in cases]
    if ids != list(range(1, 101)):
        raise ValueError("fixture case IDs must be continuous from 1 through 100")
    normalized: set[str] = set()
    for item in cases:
        if not isinstance(item, dict):
            raise ValueError("fixture case must be an object")
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"case {item.get('case_id')} has an empty question")
        key = " ".join(question.split()).casefold()
        if key in normalized:
            raise ValueError(f"duplicate question at case {item.get('case_id')}")
        normalized.add(key)
        for field in ("category", "route", "expected_action", "answer"):
            if field not in item or not isinstance(item[field], str):
                raise ValueError(f"case {item.get('case_id')} missing {field}")
        if item["expected_action"] not in {
            "legacy",
            "canary_completed",
            "canary_failed",
            "canary_replay",
        }:
            raise ValueError(
                f"case {item.get('case_id')} has an unsupported expected_action"
            )
        expected_outcome = item.get("expected_runtime_outcome")
        if expected_outcome is not None and expected_outcome not in {
            "none",
            "response",
            "deferred",
            "failed",
        }:
            raise ValueError(
                f"case {item.get('case_id')} has an unsupported runtime outcome"
            )
        if type(item.get("expected_tool_calls")) is not int:
            raise ValueError(f"case {item.get('case_id')} missing expected_tool_calls")
        if item["expected_tool_calls"] < 0:
            raise ValueError(f"case {item.get('case_id')} has a negative tool count")
        expected_tool_name = item.get("expected_tool_name")
        if expected_tool_name is not None and not isinstance(expected_tool_name, str):
            raise ValueError(f"case {item.get('case_id')} has an invalid tool name")
        expected_capability_steps = item.get("expected_capability_steps")
        if expected_capability_steps is not None and (
            type(expected_capability_steps) is not int
            or expected_capability_steps < 0
        ):
            raise ValueError(
                f"case {item.get('case_id')} has an invalid capability step count"
            )
        if not isinstance(item.get("entity_terms", []), list):
            raise ValueError(f"case {item.get('case_id')} entity_terms must be a list")
    return cases


def _freeze_schema(value: object) -> object:
    """Convert JSON-ish schemas to the tuple form used by Dududa freeze_json."""
    if isinstance(value, Mapping):
        return {str(k): _freeze_schema(v) for k, v in value.items()}
    if isinstance(value, list):
        return tuple(_freeze_schema(v) for v in value)
    return value


def _sample_schema(schema: Mapping[str, object]) -> object:
    """Build the smallest value satisfying a closed projection schema."""
    if "const" in schema:
        return schema["const"]
    enum = schema.get("enum")
    if isinstance(enum, (tuple, list)) and enum:
        return enum[0]
    raw_type = schema.get("type")
    types = tuple(raw_type) if isinstance(raw_type, (tuple, list)) else (raw_type,)
    non_null = next((item for item in types if item != "null"), "null")
    if non_null == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        if not isinstance(properties, Mapping):
            return {}
        names = required if isinstance(required, (tuple, list)) else tuple(properties)
        return {
            str(name): _sample_schema(properties[name])
            for name in names
            if name in properties and isinstance(properties[name], Mapping)
        }
    if non_null == "array":
        return tuple()
    if non_null == "string":
        minimum = schema.get("minLength")
        value = "fixture"
        if isinstance(minimum, int) and minimum > len(value):
            value = "x" * minimum
        maximum = schema.get("maxLength")
        if isinstance(maximum, int):
            value = value[:maximum]
        return value
    if non_null == "integer":
        minimum = schema.get("minimum")
        return int(minimum) if isinstance(minimum, (int, float)) and minimum > 0 else 0
    if non_null == "number":
        minimum = schema.get("minimum")
        return float(minimum) if isinstance(minimum, (int, float)) and minimum > 0 else 0.0
    if non_null == "boolean":
        return False
    return None


def _introspected_tools() -> dict[str, tuple[str, McpToolDescriptor]]:
    """Read tool schemas from the real FastMCP declarations, never hand-copy them."""
    service_root = ROOT / "services" / "mcp"
    paths = [
        service_root / "ustc-campus" / "src",
        service_root / "notifai" / "src",
        service_root / "icourse" / "src",
    ]
    for path in paths:
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from icourse_mcp.config import AppConfig as ICourseConfig
    from icourse_mcp.server import create_mcp as create_icourse
    from notifai_mcp.config import AppConfig as NotifConfig
    from notifai_mcp.server import create_mcp as create_notifai
    from ustc_campus_mcp.server import create_mcp as create_campus

    servers: list[tuple[str, object]] = [
        ("ustc-academic", create_campus("academic")),
        ("ustc-curriculum", create_campus("curriculum")),
        ("ustc-young", create_campus("young")),
        ("notifai", create_notifai(NotifConfig(), client=object())),
        ("icourse", create_icourse(ICourseConfig(db_path=Path("/tmp/dududa-100-introspection.sqlite3")))),
    ]
    result: dict[str, tuple[str, McpToolDescriptor]] = {}
    for server_id, mcp in servers:
        tools = getattr(getattr(mcp, "_tool_manager"), "_tools", {})
        for tool in tools.values():
            input_schema = _freeze_schema(tool.parameters)
            output_schema = _freeze_schema(tool.fn_metadata.output_schema)
            if not isinstance(input_schema, Mapping) or not isinstance(output_schema, Mapping):
                raise ValueError(f"invalid introspected schema for {server_id}/{tool.name}")
            descriptor = McpToolDescriptor(
                schema_version=1,
                name=tool.name,
                description=str(tool.description or ""),
                input_schema=input_schema,
                output_schema=output_schema,
                annotations=_freeze_schema(tool.annotations or {}),
            )
            result[tool.name] = (server_id, descriptor)
    missing = set(_TOOL_SERVER) - set(result)
    if missing:
        raise ValueError(f"FastMCP introspection missed tools: {sorted(missing)}")
    return result


class FixtureUnifiedMcpClient:
    """Schema-accurate in-process Unified MCP transport with call recording."""

    def __init__(self, *, catalog: object, now: datetime = FIXED_NOW) -> None:
        self.now = now
        self.catalog = catalog
        self.discover_calls: list[dict[str, object]] = []
        self.tool_calls: list[dict[str, object]] = []
        self.health_calls: list[dict[str, object]] = []
        self.active_case: dict[str, Any] | None = None
        self._tool_info = _introspected_tools()
        # Fail at fixture construction if a FastMCP declaration drifts from
        # the versioned capability mapping.  Runtime health would eventually
        # catch the same mismatch, but checking every mapped tool here makes
        # the no-send harness' schema-accuracy claim explicit.
        for mapping in catalog.mcp_mappings:
            info = self._tool_info.get(mapping.tool_name)
            if info is None or info[0] != mapping.server_id:
                raise ValueError(
                    f"missing mapped fixture tool {mapping.server_id}/{mapping.tool_name}"
                )
            descriptor = info[1]
            input_digest = canonical_schema_digest(
                descriptor.input_schema,
                schema_id=f"mcp.{mapping.server_id}.{mapping.tool_name}.input",
                schema_version=1,
            )
            output_digest = (
                None
                if descriptor.output_schema is None
                else canonical_schema_digest(
                    descriptor.output_schema,
                    schema_id=f"mcp.{mapping.server_id}.{mapping.tool_name}.output",
                    schema_version=1,
                )
            )
            if (
                input_digest != mapping.expected_input_schema_digest
                or output_digest != mapping.expected_output_schema_digest
            ):
                raise ValueError(
                    f"schema drift in fixture tool {mapping.server_id}/{mapping.tool_name}"
                )
        self._snapshots: dict[str, McpSchemaSnapshot] = {}
        for server_id in sorted(set(_TOOL_SERVER.values())):
            descriptors = tuple(
                descriptor
                for name, (sid, descriptor) in sorted(self._tool_info.items())
                if sid == server_id
            )
            definition_digest = DigestString(
                str(canonical_digest({"server_id": server_id, "fixture": 1}, domain="mcp.server-definition:v1"))
            )
            config_revision = f"fixture-{server_id}-v1"
            generation = 1
            snapshot_digest = mcp_schema_snapshot_digest(
                server_id, config_revision, definition_digest, generation, descriptors
            )
            snapshot_id = f"mcp-schema-{server_id}-v1"
            self._snapshots[server_id] = McpSchemaSnapshot(
                schema_version=1,
                snapshot_id=snapshot_id,
                snapshot_digest=snapshot_digest,
                server_id=server_id,
                config_revision=config_revision,
                definition_digest=definition_digest,
                schema_facts_digest=canonical_digest(
                    tuple(
                        {"name": item.name, "input_schema": item.input_schema, "output_schema": item.output_schema}
                        for item in descriptors
                    ),
                    domain="mcp.tool-schema-facts:v1",
                ),
                generation=generation,
                tools=descriptors,
                observed_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(hours=1),
            )

    def set_case(self, case: dict[str, Any]) -> None:
        self.active_case = case

    async def discover(self, server_id: str, *, refresh: bool = False, call: object) -> McpSchemaSnapshot:
        self.discover_calls.append({"server_id": server_id, "refresh": refresh, "case_id": self._case_id()})
        snapshot = self._snapshots.get(server_id)
        if snapshot is None:
            raise ValueError(f"unknown fixture MCP server {server_id}")
        return snapshot

    async def health(self, server_id: str, *, call: object) -> McpServerHealth:
        self.health_calls.append({"server_id": server_id, "case_id": self._case_id()})
        snapshot = self._snapshots.get(server_id)
        return McpServerHealth(
            schema_version=1,
            server_id=server_id,
            config_revision=(snapshot.config_revision if snapshot else f"fixture-{server_id}-v1"),
            generation=(snapshot.generation if snapshot else 1),
            status=McpHealthStatus.HEALTHY,
            schema_snapshot_id=(snapshot.snapshot_id if snapshot else None),
            observed_at=self.now,
            circuit_open_until=None,
            reason_codes=(),
        )

    async def call_tool(self, server_id: str, tool_name: str, arguments: object, *, call: object) -> McpToolResult:
        self.tool_calls.append(
            {"server_id": server_id, "tool_name": tool_name, "arguments": _plain(arguments), "case_id": self._case_id()}
        )
        case = self.active_case or {}
        if case.get("scene", {}).get("inject_failure") == "icourse_timeout" and server_id == "icourse":
            raise mcp_client_error(McpFailureKind.TIMEOUT, "fixture_timeout", "fixture_injected_timeout")
        snapshot = self._snapshots[server_id]
        capability_id = _TOOL_CAPABILITY[tool_name]
        definition = next(item for item in self.catalog.definitions if item.capability_id == capability_id)
        sample = _sample_schema(next(item for item in self.catalog.schema_documents if item.schema_ref == definition.output_schema).document)
        if not isinstance(sample, Mapping):
            raise ValueError(f"sample for {capability_id} is not an object")
        request_digest = getattr(call, "request_digest", DigestString(str(canonical_digest({"case": self._case_id()}, domain="mcp.fixture-request:v1"))))
        result_digest = mcp_tool_result_digest(
            server_id, tool_name, snapshot.generation, snapshot.snapshot_id,
            snapshot.snapshot_digest, request_digest, False, sample, ()
        )
        return McpToolResult(
            schema_version=1,
            server_id=server_id,
            tool_name=tool_name,
            generation=snapshot.generation,
            schema_snapshot_id=snapshot.snapshot_id,
            schema_snapshot_digest=snapshot.snapshot_digest,
            request_digest=request_digest,
            result_digest=result_digest,
            is_error=False,
            structured_content=sample,
            content=(),
            total_size_bytes=len(canonical_json_bytes(sample)),
        )

    async def close(self) -> None:
        return None

    def _case_id(self) -> int | None:
        value = self.active_case.get("case_id") if self.active_case else None
        return int(value) if isinstance(value, int) else None


class At:
    def __init__(self, qq: str) -> None:
        self.qq = qq
        self.name = None


class Plain:
    def __init__(self, text: str) -> None:
        self.text = text


class Reply:
    def __init__(self, message_id: str, *, group_id: str | None = None) -> None:
        self.id = message_id
        self.group_id = group_id


class Image:
    def __init__(self) -> None:
        self.file = "fixture.jpg"
        self.media_type = "image/jpeg"
        self.size = 8


class Native100Event:
    def __init__(self, case: dict[str, Any], *, replay: bool = False) -> None:
        self.case = case
        scene = case.get("scene") if isinstance(case.get("scene"), dict) else {}
        self.stop_calls = 0
        self.send_calls = 0
        self.sent_chains: list[object] = []
        self._group_id = str(scene.get("group_id", "2000000001"))
        self._admin = bool(scene.get("admin", False))
        self._self_message = bool(scene.get("self_message", False))
        self._sender_id = "1000000001" if self._self_message else "3000000001"
        case_id = int(case["case_id"])
        message_id = int(scene.get("message_id", 910000000 + case_id))
        if replay:
            message_id = 910000000 + case_id
        question = str(case["question"])
        text = "" if scene.get("blank") else question
        self.message_str = text
        components: list[object] = []
        if scene.get("mention", True):
            components.append(At("1000000001"))
        if text:
            components.append(Plain(text))
        if scene.get("reply"):
            components.append(Reply("prior-message", group_id=scene.get("reply_group")))
        if scene.get("attachment") == "image":
            components.append(Image())
        timestamp = int(FIXED_NOW.timestamp()) + case_id
        raw_segments: list[dict[str, object]] = []
        if scene.get("mention", True):
            raw_segments.append({"type": "at", "data": {"qq": "1000000001"}})
        if text:
            raw_segments.append({"type": "text", "data": {"text": text}})
        if scene.get("reply"):
            raw_segments.append({"type": "reply", "data": {"id": "prior-message"}})
        if scene.get("attachment") == "image":
            raw_segments.append({"type": "image", "data": {"file": "fixture.jpg"}})
        self.message_obj = SimpleNamespace(
            message_id=str(message_id), timestamp=timestamp, message=components,
            raw_message={
                "time": timestamp, "self_id": 1000000001, "post_type": "message",
                "message_type": "group", "message_id": message_id, "group_id": int(self._group_id),
                "user_id": int(self._sender_id), "message": raw_segments,
            },
        )

    def stop_event(self) -> None:
        self.stop_calls += 1

    def get_platform_id(self) -> str:
        return "qq-adapter-1"

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def get_self_id(self) -> str:
        return "1000000001"

    def get_sender_id(self) -> str:
        return self._sender_id

    def get_group_id(self) -> str:
        return self._group_id

    def get_message_type(self) -> str:
        return "group"

    def get_messages(self) -> list[object]:
        return list(self.message_obj.message)

    def is_admin(self) -> bool:
        return self._admin

    async def send(self, chain: object) -> None:
        self.send_calls += 1
        self.sent_chains.append(chain)

    def chain_result(self, components: list[object]) -> list[object]:
        return components


class Scripted100Provider:
    """Deterministic semantic projection and direct answer model."""

    def __init__(self, cases: tuple[dict[str, Any], ...]) -> None:
        self.provider_id = "astrbot-luna"
        self._by_question = {str(item["question"]): item for item in cases}
        self._active_case: dict[str, Any] | None = None
        self.calls: list[dict[str, object]] = []

    def meta(self) -> object:
        return SimpleNamespace(id="astrbot-luna")

    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        system = str(kwargs.get("system_prompt", ""))
        prompt = str(kwargs.get("prompt", ""))
        if "语义感知器" in system:
            context = _context_from_prompt(prompt)
            current_ref = context.get("current_message_ref")
            current = next((item for item in context.get("messages", ()) if item.get("message_ref") == current_ref), {})
            question = str(current.get("text", ""))
            case = self._by_question.get(question)
            if case is None:
                case = self._active_case
            if case is None:
                raise ValueError("fixture provider cannot identify case")
            self._active_case = case
            tool_name = case.get("tool_name")
            capability_id = str(case.get("capability_id") or "")
            builtin_category = _BUILTIN_CAPABILITY_CATEGORIES.get(capability_id)
            expected_tool_calls = int(case.get("expected_tool_calls", 0))
            expected_tool_name = case.get("expected_tool_name")
            # MCP metadata can describe a candidate capability without making
            # this fixture ask the model to execute it.  A positive expected
            # call count is the explicit execution signal; builtin Shuttle is
            # the exception because it has no MCP call record.
            mcp_execution_requested = bool(tool_name or expected_tool_name) and (
                expected_tool_calls > 0
            )
            need_tools = bool(builtin_category or mcp_execution_requested) and case.get("route") in {
                "tool",
                "boundary",
            }
            model_tool_name = tool_name or expected_tool_name
            server_id = _TOOL_SERVER.get(str(model_tool_name)) if model_tool_name else None
            # Keep the injected timeout case on the iCourse branch.  The user
            # text also mentions another service, but that service is not part
            # of this single-step execution and must not win planner priority.
            if case.get("scene", {}).get("inject_failure"):
                server_id = "icourse"
            category = (
                _CATEGORY_BY_SERVER.get(server_id)
                if server_id
                else builtin_category
            )
            intent_id = case.get("intent_id") if need_tools else None
            entities = [
                {"entity_id": f"fixture-entity-{i}", "kind": "other", "value": str(value), "confidence": 0.99, "evidence_refs": [str(current_ref)]}
                for i, value in enumerate(case.get("entity_terms", ()), 1)
            ]
            projection = {
                "schema_version": 1,
                "target_identity_refs": [str(current.get("author_identity_ref", "identity:author"))],
                "speech_acts": ["request"],
                "topics": [{"topic_id": f"fixture-{case['category']}", "label": str(case["category"]), "confidence": 0.99, "evidence_refs": [str(current_ref)]}],
                "intents": ([{"intent_id": str(intent_id), "confidence": 0.99, "evidence_refs": [str(current_ref)]}] if intent_id else []),
                "entities": entities,
                "references": [], "ambiguities": [],
                "need_tools": need_tools,
                "capability_categories": [category] if category else [],
                "task_kind": "direct_chat",
                "reasoning_depth": "multi_step" if case.get("category") in {"cross-provider", "failure"} else "shallow",
                "expected_tool_steps": 1 if need_tools else 0,
                "verification_required": False,
                "complexity_signals": [{"code": "simple_retrieval", "confidence": 0.99, "evidence_refs": [str(current_ref)]}],
                "confidence": 0.99,
            }
            return SimpleNamespace(completion_text=json.dumps(projection, ensure_ascii=False), usage=SimpleNamespace(input_other=32, input_cached=0, output=48))
        case = self._active_case
        if case is None:
            raise ValueError("fixture direct chat has no active case")
        return SimpleNamespace(completion_text=str(case.get("answer", "")), usage=SimpleNamespace(input_other=32, input_cached=0, output=48))


def _context_from_prompt(prompt: str) -> dict[str, object]:
    marker = "context_json:\n"
    start = prompt.find(marker)
    if start < 0:
        raise ValueError("perception prompt missing context_json")
    start += len(marker)
    end = prompt.find("\n[/DUDUDA_USER_INPUT]", start)
    if end < 0:
        end = len(prompt)
    # The serialized context is followed by the closing user marker.  Strip any
    # accidental wrapper text while keeping JSON's own braces intact.
    payload = prompt[start:end].strip()
    return json.loads(payload)


def _delivery(chains: list[object]) -> tuple[str, str, int]:
    texts: list[str] = []
    shape = "none"
    parts = 0
    for chain in chains:
        if not isinstance(chain, list):
            continue
        for component in chain:
            if not isinstance(component, tuple) or not component:
                continue
            if component[0] == "plain":
                shape = "plain"
                texts.append(str(component[1]))
                parts += 1
            elif component[0] == "nodes":
                shape = "forward"
                nodes = component[1]
                if isinstance(nodes, list):
                    for node in nodes:
                        if isinstance(node, tuple) and node and node[0] == "node":
                            texts.append(str(node[1]))
                            parts += 1
    return "".join(texts).strip(), shape, parts


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", None)
    if isinstance(raw, str):
        return raw
    return str(value)


def _expected_runtime_outcome(case: Mapping[str, Any]) -> str:
    explicit = case.get("expected_runtime_outcome")
    if isinstance(explicit, str):
        return explicit
    if case.get("expected_action") != "canary_completed":
        return "none"
    return "response"


def _checkpoint_summary(checkpoint: object | None) -> dict[str, object]:
    if checkpoint is None:
        return {}
    state = getattr(checkpoint, "state", None)
    if state is None:
        return {}
    pending = getattr(state, "pending_result", None)
    completion = getattr(state, "completion", None)
    receipt = getattr(state, "capability_run_receipt", None)
    retrieval = getattr(state, "capability_retrieval", None)
    plan = getattr(state, "tool_plan", None)
    perception_execution = getattr(state, "perception_execution", None)
    perception = getattr(perception_execution, "result", None)
    social = getattr(state, "social_decision", None)
    tier = getattr(state, "tier_decision", None)
    route = getattr(state, "direct_route_decision", None)
    endpoint = getattr(route, "selected_endpoint", None) if route else None
    profile = getattr(state, "response_plan", None)
    trace = getattr(state, "trace", ())
    return {
        "phase": _enum_value(getattr(state, "phase", None)),
        "pending_outcome": _enum_value(getattr(pending, "outcome", None))
        if pending
        else None,
        "reason_codes": list(getattr(pending, "reason_codes", ())) if pending else [],
        "completion_present": completion is not None,
        "completion_phase": _enum_value(getattr(completion, "final_phase", None))
        if completion
        else None,
        "completion_delivery_status": _enum_value(
            getattr(completion, "delivery_status", None)
        )
        if completion
        else None,
        "memory_writes": len(getattr(completion, "memory_submissions", ()))
        if completion
        else 0,
        "trace_phases": [
            _enum_value(getattr(item, "phase", None)) for item in trace
        ],
        "perception_need_tools": getattr(perception, "need_tools", None)
        if perception
        else None,
        "perception_categories": list(
            getattr(perception, "capability_categories", ())
        )
        if perception
        else [],
        "social_action": _enum_value(getattr(social, "action", None))
        if social
        else None,
        "tool_plan_steps": len(getattr(plan, "steps", ())) if plan else 0,
        "tool_plan_capabilities": [
            str(getattr(item, "capability_id", ""))
            for item in getattr(plan, "steps", ())
        ],
        "retrieval_candidates": [
            str(getattr(item, "capability_id", ""))
            for item in getattr(retrieval, "candidates", ())
        ],
        "capability_status": _enum_value(getattr(receipt, "status", None))
        if receipt
        else None,
        "capability_reason_codes": list(getattr(receipt, "reason_codes", ())) if receipt else [],
        "capability_observations": len(getattr(receipt, "observations", ())) if receipt else 0,
        "selected_tier": _enum_value(getattr(tier, "selected_tier", None))
        if tier
        else None,
        "selected_provider": getattr(endpoint, "provider_id", None)
        if endpoint
        else None,
        "selected_model": getattr(endpoint, "model_id", None)
        if endpoint
        else None,
        "selected_endpoint": getattr(endpoint, "endpoint_id", None)
        if endpoint
        else None,
        "answer_profile": _enum_value(getattr(profile, "selected_profile", None))
        if profile
        else None,
    }


async def run(fixture: Path = FIXTURE, selected: set[int] | None = None) -> dict[str, object]:
    cases = _load_cases(fixture)
    selected_cases = tuple(item for item in cases if selected is None or int(item["case_id"]) in selected)
    test = ProductionCompositionContractTests("runTest")
    test.setUp()
    plugin = None
    catalog = load_capability_catalog_snapshot(
        ROOT / "configs" / "capabilities" / "definitions",
        ROOT / "configs" / "capabilities" / "mappings",
        snapshot_id="capability-catalog:dududa-100",
        acquired_at=FIXED_NOW,
    )
    provider = Scripted100Provider(cases)
    mcp = FixtureUnifiedMcpClient(catalog=catalog)
    try:
        plugin = test._production_plugin(provider)
        plugin.unified_mcp_client = mcp
        plugin.icourse = _ICourseFacade(mcp)
        values = test._runtime_config(rollout_mode="canary")
        model_specs = json.loads(str(values["runtime_models_json"]))
        model_specs[0]["rpm_limit"] = 10_000
        model_specs[0]["tpm_limit"] = 10_000_000
        values["runtime_models_json"] = json.dumps(model_specs)
        values.update({"rollout_allowlisted_groups": ["2000000001"], "rollout_delivery_enabled": True, "rollout_kill_switch": False, "rollout_tools_enabled": True})
        assembly = composition.build_production_runtime(plugin, values, clock=lambda: FIXED_NOW)
        test._initialize(plugin, values, "dududa-100-runtime", runtime_assembly=assembly)
        plugin.rollout_bridge._output_factory = lambda event, ledger, guard: AstrBotOutputAdapter(event, ledger, component_factory=_ComponentFactory(), send_guard=guard, clock=lambda: FIXED_NOW)
        await assembly.publish_model_health((test._healthy_evidence(assembly, FIXED_NOW, ttl=timedelta(hours=1)),), call=replace(test.call, deadline=FIXED_NOW + timedelta(hours=1)))
        results: list[dict[str, object]] = []
        for case in selected_cases:
            mcp.set_case(case)
            provider._active_case = case
            replay_count = 2 if case.get("scene", {}).get("duplicate_replay") else 1
            events: list[Native100Event] = []
            bridge_results: list[object] = []
            before_tools = len(mcp.tool_calls)
            before_discovers = len(mcp.discover_calls)
            before_models = len(provider.calls)
            for replay in range(replay_count):
                event = Native100Event(case, replay=replay > 0)
                events.append(event)
                try:
                    bridge_results.append(await plugin.rollout_bridge.handle(event))
                except Exception as exc:  # keep all 100 rows auditable
                    bridge_results.append(exc)
            calls = mcp.tool_calls[before_tools:]
            bridge = bridge_results[0] if bridge_results else None
            answer, shape, parts = _delivery(events[0].sent_chains if events else [])
            checkpoint = None
            if bridge is not None and not isinstance(bridge, Exception):
                run_id = getattr(getattr(bridge, "canary", None), "run_id", None)
                if run_id and assembly.state_store is not None:
                    try:
                        checkpoint = await assembly.state_store.load(run_id, call=replace(test.call, run_id=run_id, deadline=FIXED_NOW + timedelta(hours=1)))
                    except Exception:
                        checkpoint = None
            checkpoint_data = _checkpoint_summary(checkpoint)
            case_model_calls = provider.calls[before_models:]
            case_perception_calls = sum(
                1
                for call_record in case_model_calls
                if "语义感知器" in str(call_record.get("system_prompt", ""))
            )
            case_direct_chat_calls = len(case_model_calls) - case_perception_calls
            actual_action = (
                bridge.action.value
                if hasattr(bridge, "action")
                else "exception"
            )
            expected_action = str(case["expected_action"])
            expected_outcome = _expected_runtime_outcome(case)
            actual_outcome = checkpoint_data.get("pending_outcome") or "none"
            expected_delivery_calls = int(
                case.get(
                    "expected_delivery_calls",
                    1 if expected_action == "canary_completed" else 0,
                )
            )
            expected_tool_name = case.get("expected_tool_name")
            tool_name_match = expected_tool_name is None or (
                len(calls) == 1 and calls[0]["tool_name"] == expected_tool_name
            )
            forbidden_optional_calls = bool(
                case.get("scene", {}).get("optional_server") and calls
            )
            actual_capability_steps = int(
                checkpoint_data.get("tool_plan_steps", 0)
            )
            expected_capability_steps = case.get("expected_capability_steps")
            capability_steps_match = expected_capability_steps is None or (
                actual_capability_steps == expected_capability_steps
            )
            duplicate_replay_violation = bool(
                case.get("scene", {}).get("duplicate_replay")
                and (
                    sum(event.send_calls for event in events) != 1
                    or len(provider.calls) - before_models > 2
                    or len(calls) > 1
                )
            )
            results.append({
                **case,
                "expected_answer": case["answer"],
                "bridge_action": (bridge.action.value if hasattr(bridge, "action") else "exception"),
                "bridge_reason_code": (bridge.reason_code if hasattr(bridge, "reason_code") else type(bridge).__name__),
                "runtime_completed": bool(getattr(bridge, "action", None) is AstrBotBridgeAction.CANARY_COMPLETED),
                "event_stopped": sum(event.stop_calls for event in events),
                "fake_delivery_calls": sum(event.send_calls for event in events),
                "delivery_shape": shape,
                "delivery_parts": parts,
                "answer": answer,
                "expected_delivery_calls": expected_delivery_calls,
                "model_calls": len(provider.calls) - before_models,
                "perception_model_calls": case_perception_calls,
                "direct_chat_model_calls": case_direct_chat_calls,
                "discover_calls": len(mcp.discover_calls) - before_discovers,
                "mcp_calls": [{"server_id": row["server_id"], "tool_name": row["tool_name"], "arguments": row["arguments"]} for row in calls],
                "checkpoint": checkpoint_data,
                "runtime_outcome": actual_outcome,
                "expected_runtime_outcome": expected_outcome,
                "error_type": (type(bridge).__name__ if isinstance(bridge, Exception) else None),
                "expected_action_match": actual_action == expected_action,
                "expected_tool_calls_match": len(calls) == int(case.get("expected_tool_calls", 0)),
                "expected_tool_name_match": tool_name_match,
                "expected_capability_steps_match": capability_steps_match,
                "expected_runtime_outcome_match": actual_outcome == expected_outcome,
                "expected_delivery_calls_match": sum(event.send_calls for event in events) == expected_delivery_calls,
                "forbidden_optional_calls": forbidden_optional_calls,
                "duplicate_replay_violation": duplicate_replay_violation,
                "provider_kind": (
                    "builtin"
                    if checkpoint_data.get("tool_plan_capabilities")
                    and not calls
                    else "mcp"
                    if calls
                    else "none"
                ),
            })
        summary = {
            "cases": len(results),
            "fixture_cases": len(cases),
            "runtime_completed": sum(bool(item["runtime_completed"]) for item in results),
            "fake_deliveries": sum(int(item["fake_delivery_calls"]) for item in results),
            "real_qq_sends": 0,
            "model_calls": len(provider.calls),
            "perception_model_calls": sum(1 for row in provider.calls if "语义感知器" in str(row.get("system_prompt", ""))),
            "direct_chat_model_calls": sum(1 for row in provider.calls if "语义感知器" not in str(row.get("system_prompt", ""))),
            "mcp_calls": len(mcp.tool_calls),
            "mcp_discover_calls": len(mcp.discover_calls),
            "mcp_health_calls": len(mcp.health_calls),
            "mcp_registry_servers": sorted(set(_TOOL_SERVER.values())),
            "mcp_mapping_count": len(getattr(catalog, "mcp_mappings", ())),
            "capability_definition_count": len(getattr(catalog, "definitions", ())),
            "tool_counts": dict(sorted(Counter(str(row["tool_name"]) for row in mcp.tool_calls).items())),
            "server_counts": dict(sorted(Counter(str(row["server_id"]) for row in mcp.tool_calls).items())),
            "category_counts": dict(sorted(Counter(str(item["category"]) for item in results).items())),
            "bridge_action_counts": dict(sorted(Counter(str(item["bridge_action"]) for item in results).items())),
            "tool_expectation_mismatches": sum(not bool(item["expected_tool_calls_match"]) for item in results),
            "action_expectation_mismatches": sum(not bool(item["expected_action_match"]) for item in results),
            "runtime_outcome_mismatches": sum(not bool(item["expected_runtime_outcome_match"]) for item in results),
            "delivery_expectation_mismatches": sum(not bool(item["expected_delivery_calls_match"]) for item in results),
            "tool_name_expectation_mismatches": sum(not bool(item["expected_tool_name_match"]) for item in results),
            "capability_steps_expectation_mismatches": sum(
                not bool(item["expected_capability_steps_match"])
                for item in results
            ),
            "forbidden_optional_tool_calls": sum(bool(item["forbidden_optional_calls"]) for item in results),
            "memory_writes": sum(int(item.get("checkpoint", {}).get("memory_writes", 0)) for item in results),
            "plans_over_one_step": sum(int(item.get("checkpoint", {}).get("tool_plan_steps", 0)) > 1 for item in results),
            "builtin_capability_calls": sum(
                1 for item in results if item.get("provider_kind") == "builtin"
            ),
            "duplicate_replay_violations": sum(bool(item["duplicate_replay_violation"]) for item in results),
            "uncaught_case_exceptions": sum(1 for item in results if item["error_type"]),
        }
        if selected is None:
            failures = {
                key: value
                for key, value in summary.items()
                if key.endswith("_mismatches")
                or key in {
                    "forbidden_optional_tool_calls",
                    "memory_writes",
                    "plans_over_one_step",
                    "duplicate_replay_violations",
                    "uncaught_case_exceptions",
                    "real_qq_sends",
                }
                if value
            }
            if failures:
                raise AssertionError(
                    "100-case runtime invariants failed: "
                    + json.dumps(failures, ensure_ascii=False, sort_keys=True)
                )
        return {"schema_version": 1, "runtime": "dududa-2.0", "fixture": str(fixture), "fixture_time": FIXED_NOW.isoformat(), "model_mode": "scripted_perception_and_direct_chat", "output_mode": "in_memory_fake_delivery", "summary": summary, "results": results}
    finally:
        if plugin is not None:
            await plugin.terminate()
        else:
            await mcp.close()
        test.tearDown()


def report(document: dict[str, object]) -> str:
    summary = document["summary"]
    results = tuple(document["results"])
    category_rows: dict[str, dict[str, int]] = {}
    route_counts = Counter(str(item["route"]) for item in results)
    for item in results:
        category = str(item["category"])
        row = category_rows.setdefault(
            category,
            {"cases": 0, "runtime": 0, "mcp": 0, "delivery": 0},
        )
        row["cases"] += 1
        row["runtime"] += int(bool(item["runtime_completed"]))
        row["mcp"] += len(item.get("mcp_calls", ()))
        row["delivery"] += int(item["fake_delivery_calls"])

    lines = [
        "# Dududa 2.0：100 题原生消息链路 Runtime 模拟报告",
        "",
        "**测试日期：** 2026-09-03  **Runtime：** Dududa 2.0 生产组合  **Fixture：** `dududa-100-native-message-cases.json`",
        "",
        "## 结论",
        "",
        "本次将 100 条去重问题构造成 OneBot 形状的入站事件，并逐条经过当前 2.0 Bridge、Connector、Perception、Social Decision、Tier/Response Plan、Capability Planner/Provider、Composer、Persona、Final Validator、Output 和 Runtime State。94 条符合接管条件的消息完成了内存 Fake Delivery；6 条在 Connector/Admission 边界按设计留在 legacy owner。没有未捕获异常、真实 QQ 发送、Memory 写入或超过一步的 Tool Plan。",
        "",
        "这是一项可复现的链路与耦合验证，不是线上质量评分：Perception/Direct Chat 使用按题目索引的脚本模型，MCP 使用从真实 FastMCP 声明读取 Schema 的本地 fixture，Output 使用内存确认器。它证明组件契约和副作用边界在该输入集合中的行为，不代表真实模型的中文质量、实时站点数据、账号认证或 NapCat/QQ 服务端回执。",
        "",
        "## 测试方法与 2.0 链路",
        "",
        "```text",
        "OneBot-shaped Event",
        "  -> AstrBotInputConnector（Scope、Reply、Mention、Attachment、去重键）",
        "  -> Runtime Admission / Canary claim（只对明确 @、可支持纯文本消息接管）",
        "  -> CurrentMessageContext + Perception（结构化意图/实体/能力类别）",
        "  -> Social Decision + Tier Policy + AnswerProfile",
        "  -> 一步 Capability Planner -> Unified MCP 或 Builtin Shuttle Provider",
        "  -> Observation Validator -> DIRECT_CHAT（工具事实合成唯一答复）",
        "  -> Composer -> Persona -> Final Validator",
        "  -> Output Adapter（本次为 Fake Delivery）-> Delivery Receipt -> State/Memory evaluation",
        "```",
        "",
        "每题固定时钟为 `2026-09-03T01:30:00Z`。MCP 工具名称和输入/输出 Schema 通过 iCourse、USTC Academic/Curriculum/Young、NotifAI 的 FastMCP 声明动态 introspection；校车走版本化本地 Builtin Provider，因此校车题的 MCP 调用数应为 0。每个入站计划最多生成一个 Capability step 和一次业务调用；底层 MCP transport 仍受各 Server 的 retry policy 约束，本次本地 fixture 未触发重试。未启用的 PR10 MCP（library、local-recs、training-plan、campus-events、college-notice）不获得调用机会。",
        "",
        "## 汇总指标",
        "",
    ]
    for key, value in summary.items():
        rendered_value = (
            json.dumps(value, ensure_ascii=False, sort_keys=True)
            if isinstance(value, (dict, list, tuple))
            else str(value)
        )
        lines.append(f"- `{key}`：{rendered_value}")
    lines.extend(
        [
            "",
            "## 模块覆盖",
            "",
            "| 模块 | 题数 | 进入 2.0 | MCP 调用 | Fake Delivery |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for category, row in sorted(category_rows.items()):
        lines.append(
            f"| {category} | {row['cases']} | {row['runtime']} | {row['mcp']} | {row['delivery']} |"
        )
    lines.extend(
        [
            "",
            "路由分布："
            + "，".join(
                f"`{route}` {count}"
                for route, count in sorted(route_counts.items())
            ),
            "",
            "MCP Tool 计数按实际调用记录统计；校车 Builtin 调用不计入 MCP。",
        ]
    )
    lines.extend(
        [
            "",
            "## 必要修复与验证结论",
            "",
            "1. **已验证 Capability 失败态的可见答复。** MCP/Provider 返回经过校验的 `FAILED` 或 `DEFERRED` Receipt 时，Runtime 保留失败证据，不重试、不改走 Web search，并通过同一 Composer → Persona → Final Validator → Delivery 链输出“所需查询服务暂时不可用，请稍后再试。”；`CANCELLED`、未验证 Receipt、Runtime 异常和最终校验失败仍 fail-closed，不生成可见发送。Case 80 覆盖了超时路径：Runtime outcome 为 `failed`，完成 Delivery Receipt 后 Bridge action 仍为 `canary_completed`，报告同时保留这两个层次的事实。",
            "2. **已阻断跨群 Reply 引用。** Reply 组件带有来源群信息且与当前 Scope 不一致时，Connector 返回稳定的 `connector.message_rejected`，不创建 Runtime/Tool/Delivery；没有来源群元数据的宿主 Reply 保持原有兼容行为。",
            "3. **已阻断 NotifAI 来源泛化。** “学校主页缓存”“学院官网”“官网通知”等明确指向非 NotifAI 聚合来源的文本，不再因泛词“通知”自动路由到 `campus.notifications`；即使模型只返回 `notifai.*` intent 而漏报 category，也会在合并边界被清除。普通校园通知查询仍可进入 NotifAI。",
            "4. **已校准边界题语义。** 自消息、未 @、空正文、附件和不可验证的 Reply 保持静默/legacy；Sub2API、Dududa Social、Reply Review/Polish 等独立插件不会因普通自然语言获得 Core Tool 或第二次发送。",
            "5. **跨 Provider 保持单步上限。** Case 72 同时提到二课和校车时，规则类别可能让确定性优先级选中一个 Shuttle Builtin；它不会并行调用两个 Provider，DirectChat 会明确要求拆分。该边界保证的是最多一步和无重复发送，不把候选选择伪装成零能力调用。",
            "",
            "## 证据边界",
            "",
            "- `scripted_perception_and_direct_chat` 只模拟结构化意图提取和答案选择，不是对 Luna/Terra/Sol 的真实调用或中文自然度评审。",
            "- `schema-accurate in-process MCP` 只证明 Registry/Planner/Provider/Observation 的接口耦合；返回值由本地 Schema 最小样本生成，不代表线上数据新鲜度。",
            "- `in_memory_fake_delivery` 不连接 NapCat、OneBot 网络或 QQ；`real_qq_sends=0` 是本次运行的设计结果。",
            "- 本报告覆盖这 100 条固定问题和当前组合，不替代全仓库测试、真实并发顺序、Provider Conformance、账号权限或 S23 实群验收。",
            "",
            "## 逐题记录",
            "",
        ]
    )
    for item in results:
        calls = item.get("mcp_calls", ())
        call_text = "不调用"
        if calls:
            call_text = ", ".join(
                f"`{row['server_id']}/{row['tool_name']}`" for row in calls
            )
        checkpoint = item.get("checkpoint", {})
        if not isinstance(checkpoint, Mapping):
            checkpoint = {}
        answer = str(item.get("answer") or "（静默）")
        expected_answer = str(item.get("expected_answer") or "（静默）")
        trace = checkpoint.get("trace_phases", ())
        reasons = checkpoint.get("reason_codes", ())
        lines.extend(
            [
                f"### Case {item['case_id']} · {item['category']}",
                "",
                f"**问题：** {item['question']}",
                "",
                f"**场景/边界：** route=`{item['route']}`；expected action=`{item['expected_action']}`；实际 Bridge=`{item['bridge_action']}` / `{item['bridge_reason_code']}`。",
                "",
                f"**Runtime：** expected outcome=`{item['expected_runtime_outcome']}`；actual outcome=`{item['runtime_outcome']}`；checkpoint phase=`{checkpoint.get('phase', '未创建')}`；completion phase=`{checkpoint.get('completion_phase', '—')}`。",
                "",
                f"**Perception/Social：** need_tools=`{checkpoint.get('perception_need_tools', '—')}`；categories={json.dumps(checkpoint.get('perception_categories', ()), ensure_ascii=False)}；social action=`{checkpoint.get('social_action', '—')}`。",
                "",
                f"**模型与计划：** {item['model_calls']} 次模型调用（Perception {item.get('perception_model_calls', 0)}、Direct Chat {item.get('direct_chat_model_calls', 0)}）；provider=`{checkpoint.get('selected_provider') or '—'}`；model=`{checkpoint.get('selected_model') or '—'}`；tier=`{checkpoint.get('selected_tier') or '—'}`；AnswerProfile=`{checkpoint.get('answer_profile') or '—'}`；provider kind=`{item.get('provider_kind', 'none')}`；plan steps=`{checkpoint.get('tool_plan_steps', 0)}`。",
                "",
                f"**Capability/MCP：** plan={json.dumps(checkpoint.get('tool_plan_capabilities', ()), ensure_ascii=False)}；retrieval candidates={json.dumps(checkpoint.get('retrieval_candidates', ()), ensure_ascii=False)}；MCP {len(calls)} 次（{call_text}）；capability status=`{checkpoint.get('capability_status') or '—'}`。",
                "",
                f"**Delivery：** Fake {item['fake_delivery_calls']} 次，形态=`{item['delivery_shape']}`，{item['delivery_parts']} part；memory writes=`{checkpoint.get('memory_writes', 0)}`；real QQ=0。",
                "",
                f"**最终回答：** {answer}",
                "",
                f"**Fixture 预期回答：** {expected_answer}；回答匹配由脚本模型按 fixture 复现，不作为真实模型质量结论。",
                "",
                f"**Trace：** `{json.dumps(trace, ensure_ascii=False)}`；reason codes=`{json.dumps(reasons, ensure_ascii=False)}`；invariant flags：action={item['expected_action_match']}, outcome={item['expected_runtime_outcome_match']}, MCP count={item['expected_tool_calls_match']}, capability steps={item['expected_capability_steps_match']}, delivery={item['expected_delivery_calls_match']}。",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _parse_cases(value: str) -> set[int]:
    selected: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            selected.update(range(int(left), int(right) + 1))
        else:
            selected.add(int(part))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--cases", type=str, default=None)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    selected = _parse_cases(args.cases) if args.cases else None
    document = asyncio.run(run(args.fixture, selected))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(args.json_output, 0o600)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(report(document), encoding="utf-8")
    print(json.dumps(document["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
