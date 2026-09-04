from __future__ import annotations

import asyncio
import json
import re
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot_plugin_dududa_core import audit, composition, config
from astrbot_plugin_dududa_core.adapters.capability_planner import (
    supports_production_query_schema,
)
from astrbot_plugin_dududa_core.adapters.mcp_schema import JsonSchemaMcpValidator
from astrbot_plugin_dududa_core.adapters.model import (
    AstrBotProviderBindingEvidence,
)
from astrbot_plugin_dududa_core.adapters.output import AstrBotOutputAdapter
from astrbot_plugin_dududa_core.adapters.proactive_talk import (
    PROACTIVE_GROUP_PROMPT_MARKER,
    ProactiveTalkEvent,
)
from astrbot_plugin_dududa_core.composition import (
    ProductionRuntimeAssembly,
    install_production_runtime,
    unavailable_runtime_assembly,
)
from astrbot_plugin_dududa_core.lifecycle import CoreLifecycleMixin
from astrbot_plugin_dududa_core.rollout_bridge import AstrBotBridgeAction
from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.mcp import ManagedUnifiedMcpClient, McpTimeoutPolicy
from dududa.models.contracts import (
    EndpointHealthStatus,
    ModelEndpointHealth,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRetentionMode,
)
from dududa.models.health import ModelHealthEvidence
from dududa.rollout import InMemoryRolloutMetrics, RolloutMode, SQLiteJournalMode

from tests.contracts.test_mcp_capability_provider import (
    RecordingUnifiedClient,
)
from tests.contracts.test_unified_mcp_worker import (
    _StaticRegistry,
    factory,
    icourse_definition,
    icourse_fixture_server,
    young_fixture_definition,
)
from tests.unit.mcp.helpers import replace_server_definition
from tests.unit.rollout.helpers import control, ledger
from tests.unit.rollout.test_controlled_execution import (
    _MutableControls,
    _RuntimeProxy,
)
from tests.unit.runtime.test_orchestrator import OrchestratorFixture

ROOT = Path(__file__).resolve().parents[2]
ICOURSE_BENCHMARK = (
    ROOT / "tests" / "fixtures" / "mcp" / "USTC 评课社区 MCP 调用测试案例.md"
)
ICOURSE_ROUTING_REGRESSIONS = (
    ROOT / "tests" / "fixtures" / "mcp" / "icourse-v2-routing-regressions.json"
)
YOUNG_NATIVE_CASES = (
    ROOT / "tests" / "fixtures" / "mcp" / "young-v2-native-message-cases.json"
)
SHUTTLE_NATIVE_CASES = (
    ROOT / "tests" / "fixtures" / "ustc_shuttle" / "questions.v1.json"
)
ICOURSE_CASE_HEADING_RE = re.compile(
    r"^### Case (\d+)(?:[：:].*)?$",
    re.MULTILINE,
)


class _Plugin(CoreLifecycleMixin):
    pass


class _NoopUnifiedMcpClient:
    def __init__(self) -> None:
        self.closed = False

    async def discover(self, server_id, *, refresh=False, call):
        raise AssertionError(f"unexpected MCP discovery: {server_id}")

    async def call_tool(self, server_id, tool_name, arguments, *, call):
        raise AssertionError(f"unexpected MCP call: {server_id}/{tool_name}")

    async def health(self, server_id, *, call):
        raise AssertionError(f"unexpected MCP health call: {server_id}")

    async def close(self) -> None:
        self.closed = True


class _ICourseFacade:
    def __init__(self, client=None) -> None:
        self.client = client or _NoopUnifiedMcpClient()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _ComponentFactory:
    def plain(self, text: str) -> tuple[str, str]:
        return ("plain", text)

    def at(self, user_id: str) -> tuple[str, str]:
        return ("at", user_id)

    def reply(self, message_id: str) -> tuple[str, str]:
        return ("reply", message_id)

    def node(self, text: str, *, name: str, uin: str) -> tuple[object, ...]:
        return ("node", text, name, uin)

    def nodes(self, nodes: list[object]) -> tuple[str, list[object]]:
        return ("nodes", nodes)

    def chain(self, components: list[object]) -> list[object]:
        return components


class _ProviderContext:
    def __init__(
        self,
        providers: dict[str, object],
        *,
        evidence_enabled: bool = True,
    ) -> None:
        self.providers = dict(providers)
        self.evidence_enabled = evidence_enabled

    def get_provider_by_id(self, provider_id: str) -> object | None:
        return self.providers.get(provider_id)

    def resolve_dududa_model_provider_evidence(
        self,
        astrbot_provider_id: str,
        descriptor: ModelProviderDescriptor,
    ) -> AstrBotProviderBindingEvidence | None:
        if not self.evidence_enabled:
            return None
        endpoint = descriptor.endpoints[0]
        return AstrBotProviderBindingEvidence(
            schema_version=1,
            astrbot_provider_id=astrbot_provider_id,
            host_version="astrbot-test",
            conformance_revision=ComponentRevision(
                "astrbot-provider-conformance",
                "1.0.0",
                "test-v1",
                DigestString("builtin:astrbot-provider-conformance"),
            ),
            verified_model_id=endpoint.model_id,
            verified_max_output_tokens=endpoint.capabilities.max_output_tokens,
            verified_data_residencies=endpoint.available_data_residencies,
            verified_retention_modes=endpoint.supported_retention_modes,
            single_request_verified=True,
            model_binding_verified=True,
            output_limit_verified=True,
            residency_verified=True,
            retention_verified=True,
            sanitized_logging_verified=True,
            deadline_enforcement_verified=True,
            cancellation_enforcement_verified=True,
        )


class _ProviderRegistryContext:
    def __init__(self, providers: dict[str, object]) -> None:
        self.providers = dict(providers)

    def get_provider_by_id(self, provider_id: str) -> object | None:
        return self.providers.get(provider_id)


class _AstrBotProvider:
    def __init__(self, provider_id: str = "astrbot-luna") -> None:
        self.provider_id = provider_id
        self.calls: list[dict[str, object]] = []

    def meta(self) -> object:
        return SimpleNamespace(id=self.provider_id)

    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            completion_text="这是来自生产 Runtime 的影子回答。",
            usage=SimpleNamespace(input_other=12, input_cached=0, output=8),
        )


class _ScriptedAstrBotProvider(_AstrBotProvider):
    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        system_prompt = str(kwargs["system_prompt"])
        prompt = str(kwargs["prompt"])
        if "语义感知器" in system_prompt:
            marker = "context_json:\n"
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\n[/DUDUDA_USER_INPUT]", start)
            context = json.loads(prompt[start:end])
            current_ref = context["current_message_ref"]
            current = next(
                item
                for item in context["messages"]
                if item["message_ref"] == current_ref
            )
            completion = json.dumps(
                {
                    "schema_version": 1,
                    "target_identity_refs": [current["author_identity_ref"]],
                    "speech_acts": ["request"],
                    "topics": [
                        {
                            "topic_id": "course-review",
                            "label": "评课社区课程查询",
                            "confidence": 0.98,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "intents": [
                        {
                            "intent_id": "icourse.teacher.search",
                            "confidence": 0.99,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "entities": [
                        {
                            "entity_id": "icourse-site",
                            "kind": "capability",
                            "value": "评课社区",
                            "confidence": 0.99,
                            "evidence_refs": [current_ref],
                        },
                        {
                            "entity_id": "teacher-wu-tian",
                            "kind": "person",
                            "value": "吴天",
                            "confidence": 0.99,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "references": [],
                    "ambiguities": [],
                    "need_tools": True,
                    "capability_categories": ["campus.course-review"],
                    "task_kind": "direct_chat",
                    "reasoning_depth": "shallow",
                    "expected_tool_steps": 1,
                    "verification_required": False,
                    "complexity_signals": [
                        {
                            "code": "simple_retrieval",
                            "confidence": 0.98,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "confidence": 0.98,
                },
                ensure_ascii=False,
            )
        else:
            if "icourse.public-query.v2" not in prompt or "吴天" not in prompt:
                raise AssertionError("Direct Chat did not receive iCourse Observation")
            completion = (
                "评课社区的公开数据命中了吴天老师的《数学分析(B1)》，当前固定测试"
                "数据中的课程评分是 9.6。下面只根据 MCP 返回的课程记录整理，不补入"
                "网页搜索结果。课程名称、教师、学期和评分都来自同一次只读查询；如果"
                "需要进一步比较不同教师或查看具体点评，应继续由对应的评课能力提供"
                "数据，而不是凭空扩写。这个长回复测试还会验证群聊输出被拆成多个"
                "文本分片后，只打包发送一条 QQ 合并转发消息。"
            )
        return SimpleNamespace(
            completion_text=completion,
            usage=SimpleNamespace(input_other=32, input_cached=0, output=24),
        )


class _ProactiveAstrBotProvider(_AstrBotProvider):
    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        system_prompt = str(kwargs["system_prompt"])
        prompt = str(kwargs["prompt"])
        if "语义感知器" in system_prompt:
            marker = "context_json:\n"
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\n[/DUDUDA_USER_INPUT]", start)
            context = json.loads(prompt[start:end])
            current_ref = context["current_message_ref"]
            current = next(
                item
                for item in context["messages"]
                if item["message_ref"] == current_ref
            )
            needs_tool = "校车" in str(current["text"])
            completion = json.dumps(
                {
                    "schema_version": 1,
                    "target_identity_refs": [current["author_identity_ref"]],
                    "speech_acts": ["statement"],
                    "topics": [],
                    "intents": [],
                    "entities": [],
                    "references": [],
                    "ambiguities": [],
                    "need_tools": needs_tool,
                    "capability_categories": (
                        ["campus.shuttle"] if needs_tool else []
                    ),
                    "task_kind": "shallow_conversation",
                    "reasoning_depth": "shallow",
                    "expected_tool_steps": 1 if needs_tool else 0,
                    "verification_required": False,
                    "complexity_signals": [
                        {
                            "code": "shallow_conversation",
                            "confidence": 0.98,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "confidence": 0.98,
                },
                ensure_ascii=False,
            )
        else:
            completion = "那就十二点五十一起回高新吧。"
        return SimpleNamespace(
            completion_text=completion,
            usage=SimpleNamespace(input_other=32, input_cached=0, output=24),
        )


class _ICourseBenchmarkAstrBotProvider(_AstrBotProvider):
    """Script only model semantics; exercise the real 2.0 Runtime around it."""

    def __init__(self, query_terms: dict[str, str]) -> None:
        super().__init__()
        self.query_terms = dict(query_terms)
        self.perception_decisions: list[tuple[str, bool]] = []

    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        system_prompt = str(kwargs["system_prompt"])
        prompt = str(kwargs["prompt"])
        if "语义感知器" in system_prompt:
            marker = "context_json:\n"
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\n[/DUDUDA_USER_INPUT]", start)
            context = json.loads(prompt[start:end])
            current_ref = context["current_message_ref"]
            current = next(
                item
                for item in context["messages"]
                if item["message_ref"] == current_ref
            )
            question = str(current["text"]).removeprefix("@嘟嘟哒").strip()
            query = self.query_terms.get(question, question)
            # The marker subset deliberately models a false negative. Production
            # rules must still supply the Capability category after the merge.
            model_requests_tools = "评课社区" not in question
            self.perception_decisions.append((question, model_requests_tools))
            completion = json.dumps(
                {
                    "schema_version": 1,
                    "target_identity_refs": [current["author_identity_ref"]],
                    "speech_acts": ["request"],
                    "topics": [
                        {
                            "topic_id": "course-review",
                            "label": "评课社区查询",
                            "confidence": 0.98,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "intents": [
                        {
                            "intent_id": "icourse.lookup",
                            "confidence": 0.98,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "entities": [
                        {
                            "entity_id": "icourse-query",
                            "kind": "other",
                            "value": query,
                            "confidence": 0.98,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "references": [],
                    "ambiguities": [],
                    "need_tools": model_requests_tools,
                    "capability_categories": (
                        ["campus.course-review"] if model_requests_tools else []
                    ),
                    "task_kind": "direct_chat",
                    "reasoning_depth": "shallow",
                    "expected_tool_steps": 1 if model_requests_tools else 0,
                    "verification_required": False,
                    "complexity_signals": [
                        {
                            "code": "simple_retrieval",
                            "confidence": 0.98,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "confidence": 0.98,
                },
                ensure_ascii=False,
            )
        else:
            completion = "评课社区 MCP 已返回结果；当前固定测试数据没有匹配记录。"
        return SimpleNamespace(
            completion_text=completion,
            usage=SimpleNamespace(input_other=32, input_cached=0, output=24),
        )


_YOUNG_TOOL_CAPABILITY_IDS = {
    "young_search_activities": "ustc.young.activities.search.v1",
    "young_get_activity": "ustc.young.activity.get.v1",
    "young_list_facets": "ustc.young.facets.list.v1",
    "young_connection_status": "ustc.young.connection.status.v1",
}


class _YoungBenchmarkAstrBotProvider(_AstrBotProvider):
    """Script model semantics while the production 2.0 path remains real."""

    def __init__(self, cases: tuple[dict[str, object], ...]) -> None:
        super().__init__()
        self._by_question = {str(item["question"]): item for item in cases}
        self._active_case: dict[str, object] | None = None
        self.perception_decisions: list[tuple[int, bool]] = []

    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        system_prompt = str(kwargs["system_prompt"])
        prompt = str(kwargs["prompt"])
        if "语义感知器" in system_prompt:
            marker = "context_json:\n"
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\n[/DUDUDA_USER_INPUT]", start)
            context = json.loads(prompt[start:end])
            current_ref = context["current_message_ref"]
            current = next(
                item
                for item in context["messages"]
                if item["message_ref"] == current_ref
            )
            question = str(current["text"]).removeprefix("@嘟嘟哒").strip()
            case = self._by_question[question]
            self._active_case = case
            tool_name = case.get("tool_name")
            model_tool_need = bool(
                case.get("simulate_model_tool_false_positive", False)
            ) or (
                tool_name is not None
                and not bool(case.get("simulate_model_tool_miss", False))
            )
            self.perception_decisions.append(
                (int(case["case_id"]), model_tool_need)
            )
            intents = (
                [
                    {
                        "intent_id": (
                            case["intent_id"] or "ustc.young.activity.search"
                        ),
                        "confidence": 0.99,
                        "evidence_refs": [current_ref],
                    }
                ]
                if model_tool_need
                else []
            )
            entities = [
                {
                    "entity_id": f"young-entity-{index}",
                    "kind": "other",
                    "value": value,
                    "confidence": 0.99,
                    "evidence_refs": [current_ref],
                }
                for index, value in enumerate(case["entity_terms"], start=1)
            ]
            completion = json.dumps(
                {
                    "schema_version": 1,
                    "target_identity_refs": (
                        []
                        if case.get("omit_model_target", False)
                        else [current["author_identity_ref"]]
                    ),
                    "speech_acts": ["request"],
                    "topics": [
                        {
                            "topic_id": "second-class",
                            "label": "第二课堂活动",
                            "confidence": 0.98,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "intents": intents,
                    "entities": entities,
                    "references": [],
                    "ambiguities": [],
                    "need_tools": model_tool_need,
                    "capability_categories": (
                        ["campus.second-class"] if model_tool_need else []
                    ),
                    "task_kind": "direct_chat",
                    "reasoning_depth": (
                        "multi_step"
                        if case["semantic_status"] == "bounded_aggregation"
                        else "shallow"
                    ),
                    "expected_tool_steps": 1 if model_tool_need else 0,
                    "verification_required": False,
                    "complexity_signals": [
                        {
                            "code": "simple_retrieval",
                            "confidence": 0.98,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "confidence": 0.98,
                },
                ensure_ascii=False,
            )
        else:
            if self._active_case is None:
                raise AssertionError("Young Direct Chat has no active case")
            completion = _young_scripted_answer(self._active_case, prompt)
        return SimpleNamespace(
            completion_text=completion,
            usage=SimpleNamespace(input_other=32, input_cached=0, output=48),
        )


class _ShuttleBenchmarkAstrBotProvider(_AstrBotProvider):
    def __init__(self, cases: tuple[dict[str, object], ...]) -> None:
        super().__init__()
        self._by_question = {str(item["question"]): item for item in cases}
        self._active_case: dict[str, object] | None = None

    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        system_prompt = str(kwargs["system_prompt"])
        prompt = str(kwargs["prompt"])
        if "语义感知器" in system_prompt:
            marker = "context_json:\n"
            start = prompt.index(marker) + len(marker)
            end = prompt.index("\n[/DUDUDA_USER_INPUT]", start)
            context = json.loads(prompt[start:end])
            current_ref = context["current_message_ref"]
            current = next(
                item
                for item in context["messages"]
                if item["message_ref"] == current_ref
            )
            question = str(current["text"]).removeprefix("@嘟嘟哒").strip()
            case = self._by_question[question]
            self._active_case = case
            model_requests_tools = int(case["case_id"]) != 6
            completion = json.dumps(
                {
                    "schema_version": 1,
                    "target_identity_refs": [current["author_identity_ref"]],
                    "speech_acts": ["request"],
                    "topics": [
                        {
                            "topic_id": "ustc-shuttle",
                            "label": "中国科大校车",
                            "confidence": 0.99,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "intents": (
                        [
                            {
                                "intent_id": "ustc.shuttle.next.read",
                                "confidence": 0.99,
                                "evidence_refs": [current_ref],
                            }
                        ]
                        if model_requests_tools
                        else []
                    ),
                    "entities": [],
                    "references": [],
                    "ambiguities": [],
                    "need_tools": model_requests_tools,
                    "capability_categories": (
                        ["campus.shuttle"] if model_requests_tools else []
                    ),
                    "task_kind": "direct_chat",
                    "reasoning_depth": "shallow",
                    "expected_tool_steps": 1 if model_requests_tools else 0,
                    "verification_required": False,
                    "complexity_signals": [
                        {
                            "code": "simple_retrieval",
                            "confidence": 0.99,
                            "evidence_refs": [current_ref],
                        }
                    ],
                    "confidence": 0.99,
                },
                ensure_ascii=False,
            )
        else:
            if self._active_case is None:
                raise AssertionError("Shuttle Direct Chat has no active case")
            case_id = int(self._active_case["case_id"])
            if "ustc.shuttle.public-query.v1" not in prompt:
                raise AssertionError("Direct Chat did not receive Shuttle Observation")
            expected = {
                6: ('"departure":"14:00"', "下一班是 14:00。"),
                11: ('"on_demand":true', "先研院是即停即走站，没有固定发车时间。"),
                20: ('"matched":false', "当前时刻表没有北区直达太湖路园区的班次。"),
            }[case_id]
            if expected[0] not in prompt:
                raise AssertionError(
                    f"Shuttle case {case_id} lost expected fact: {expected[0]}"
                )
            completion = expected[1]
        return SimpleNamespace(
            completion_text=completion,
            usage=SimpleNamespace(input_other=32, input_cached=0, output=24),
        )


def _young_scripted_answer(case: dict[str, object], prompt: str) -> str:
    tool_name = case.get("tool_name")
    if tool_name is None:
        return str(case["boundary_answer"])
    capability_id = _YOUNG_TOOL_CAPABILITY_IDS[str(tool_name)]
    if capability_id not in prompt:
        raise AssertionError(f"Direct Chat did not receive {capability_id}")
    data = _young_tool_data(prompt)
    if data.get("available") is False:
        return "第二课堂查询服务暂时不可用，请稍后再试。"
    if tool_name == "young_connection_status":
        return (
            "第二课堂查询服务当前可用，认证配置正常。"
            if data.get("available")
            else "第二课堂查询服务当前不可用。"
        )
    if tool_name == "young_list_facets":
        names = [
            str(item.get("name"))
            for item in data.get("items", [])
            if isinstance(item, dict) and item.get("name")
        ]
        return "当前公开筛选项包括：" + "、".join(names) + "。"
    if tool_name == "young_get_activity":
        return _young_activity_answer(case, data)
    items = [
        item for item in data.get("items", []) if isinstance(item, dict)
    ]
    if not items:
        return "按当前条件没有查到匹配的第二课堂活动。"
    answer = _young_search_answer(case, items)
    status = str(case["semantic_status"])
    if status == "evidence_boundary":
        answer += "这些记录不包含历史抢报、个人签到或实际考核结果，不能据此补猜。"
    elif status == "planner_boundary":
        answer += "当前单步查询只能给出这一层结果，不能继续自动展开下一层详情。"
    return answer


def _young_search_answer(
    case: dict[str, object],
    source_items: list[dict[str, object]],
) -> str:
    case_id = int(case["case_id"])
    question = str(case["question"])
    items = list(source_items)
    for module in ("德育", "智育", "体育", "美育", "劳育"):
        if f"{module}活动" in question and "德智体美劳各" not in question:
            items = [item for item in items if _young_module(item) == module]
            break

    if case_id in {1, 2, 3, 4, 5, 6, 7}:
        items = [item for item in items if item.get("kind") != "series"]
        if case_id == 2:
            items = [
                item
                for item in items
                if (_young_event_start(item) or datetime.min).hour >= 18
            ]
    if case_id == 19:
        selections = []
        for module in ("德育", "智育", "体育", "美育", "劳育"):
            match = next(
                (item for item in items if _young_module(item) == module),
                None,
            )
            selections.append(
                f"{module}：{_young_activity_line(match)}"
                if match is not None
                else f"{module}：当前没有匹配活动"
            )
        return "；".join(selections) + "。"
    if case_id == 21:
        return _young_lines(
            [item for item in items if _young_can_apply(item)],
            include_apply=True,
            include_capacity=True,
        )
    if case_id == 22:
        today = [
            item
            for item in items
            if _young_apply_end(item) is not None
            and _young_apply_end(item).date() == datetime(2026, 8, 29).date()
        ]
        return _young_lines(today, include_apply=True)
    if case_id in {23, 24}:
        return _young_lines(items, include_apply=True, include_capacity=True)
    if case_id in {25, 26, 27}:
        item = items[0]
        line = _young_activity_line(
            item,
            include_apply=True,
            include_capacity=True,
        )
        if _young_can_apply(item):
            return line + "；按当前公开状态、报名窗口和余位判断，可以报名。"
        reason = "活动已满" if _young_remaining(item) == 0 else "当前状态不在报名中"
        return line + f"；{reason}，按当前公开条件不能报名。"
    if case_id == 29:
        item = items[0]
        window = item.get("event_window")
        event_start = window.get("start") if isinstance(window, dict) else None
        event_end = window.get("end") if isinstance(window, dict) else None
        apply_end = _young_apply_end(item)
        return (
            f"{item.get('name')}：报名截止 "
            f"{apply_end.isoformat() if apply_end else '未知'}；"
            f"活动时间 {event_start} 至 {event_end}。"
        )
    if case_id == 35:
        return _young_lines([max(items, key=lambda item: _young_remaining(item) or -1)])
    if case_id == 36:
        available = [item for item in items if _young_can_apply(item)]
        return _young_lines(
            [min(available, key=lambda item: _young_remaining(item) or 0)]
        )
    if case_id == 37:
        return _young_lines(
            [item for item in items if (_young_remaining(item) or 0) >= 100]
        )
    if case_id == 38:
        ranked = sorted(items, key=_young_fill_ratio, reverse=True)[:3]
        return "；".join(_young_ratio_line(item) for item in ranked) + "。"
    if case_id == 40:
        return _young_lines(
            [item for item in items if _young_valid_hours(item) == 2]
        )
    if case_id == 41:
        return _young_lines([max(items, key=_young_valid_hours)])
    if case_id == 42:
        ranked = sorted(
            [item for item in items if item.get("kind") != "series"],
            key=_young_efficiency,
            reverse=True,
        )
        return "；".join(_young_efficiency_line(item) for item in ranked) + "。"
    if case_id == 43:
        lecture = next(item for item in items if "人工智能" in str(item.get("name")))
        volunteer = next(item for item in items if "志愿服务" in str(item.get("name")))
        return (
            f"{lecture.get('name')}和{volunteer.get('name')}都是 1 学时/小时，"
            "按当前记录学时效率相同。"
        )
    if case_id == 44:
        item = items[0]
        return (
            f"是。{item.get('name')}活动时长 {_young_duration(item):g} 小时，"
            f"有效学时 {_young_valid_hours(item):g}。"
        )
    if case_id == 45:
        return (
            "系列入口本身显示 0 学时，但当前搜索结果没有展开子活动，"
            "不能据此推断每个子活动也都是 0 学时。"
        )
    if case_id in {46, 47}:
        candidates = sorted(
            [
                item
                for item in items
                if _young_can_apply(item) and item.get("kind") != "series"
            ],
            key=_young_efficiency,
            reverse=True,
        )
        answer = "按当前公开条件可优先比较：" + "；".join(
            _young_efficiency_line(item, include_description=True)
            for item in candidates[:5]
        )
        return answer + "。这里只比较公开学时、时长、余位和明确要求，不保证实际获得学时。"
    if case_id == 48:
        return _young_capacity_line(max(items, key=_young_capacity_limit)) + "。"
    if case_id == 49:
        return _young_capacity_line(min(items, key=_young_capacity_limit)) + "。"
    if case_id == 50:
        return _young_capacity_line(max(items, key=_young_registered)) + "。"
    if case_id == 51:
        return _young_ratio_line(max(items, key=_young_fill_ratio)) + "。"
    if case_id == 52:
        available = [item for item in items if _young_can_apply(item)]
        return _young_ratio_line(max(available, key=_young_fill_ratio)) + "。"
    if case_id == 53:
        return (
            "；".join(
                _young_capacity_line(item)
                for item in items
                if _young_capacity_limit(item) >= 200
            )
            + "。"
        )
    if case_id == 54:
        lecture = next(item for item in items if _young_capacity_limit(item) == 300)
        workshop = next(item for item in items if _young_capacity_limit(item) == 12)
        return (
            f"按当前公开数据，{lecture.get('name')}余位 {_young_remaining(lecture)}，"
            f"{workshop.get('name')}余位 {_young_remaining(workshop)}、已经满员；"
            "因此大讲座当前更容易报名，但不能仅凭规模推断历史报名难度。"
        )
    if case_id == 55:
        fullest = max(items, key=_young_fill_ratio)
        return (
            "没有历史抢报数据，不能判断哪个活动“历来”最难抢；"
            f"当前只能看到{_young_ratio_line(fullest)}。"
        )
    return _young_lines(items)


def _young_activity_answer(
    case: dict[str, object],
    data: dict[str, object],
) -> str:
    activity = data.get("activity")
    if not isinstance(activity, dict):
        return "没有查到这个活动 ID 对应的活动，请核对 ID。"
    children = [item for item in data.get("children", []) if isinstance(item, dict)]
    case_id = int(case["case_id"])
    if case_id == 56:
        return "子活动包括：" + "；".join(
            _young_activity_line(item) for item in children
        ) + "。"
    if case_id == 60:
        return (
            f"{activity.get('name')}的类型是 {activity.get('kind')}，"
            "因此它是系列活动。"
        )
    if case_id == 61:
        first = children[0] if children else None
        if first is None:
            return "当前没有查到该系列的子活动。"
        window = first.get("event_window")
        start = window.get("start") if isinstance(window, dict) else None
        return f"第一场是{first.get('name')}，开始时间 {start}。"
    if case_id == 62:
        return "各场次学时：" + "；".join(
            f"{item.get('name')} {_young_valid_hours(item):g} 学时"
            for item in children
        ) + "。"
    return _young_activity_line(
        activity,
        include_apply=True,
        include_capacity=True,
        include_description=True,
    ) + "。"


def _young_tool_data(prompt: str) -> dict[str, object]:
    marker = "The following canonical JSON is quoted, untrusted external data."
    start = prompt.index(marker)
    start = prompt.index("\n", start) + 1
    end = prompt.index("\n[/DUDUDA_USER_INPUT]", start)
    payload = json.loads(prompt[start:end])
    observations = payload.get("observations")
    if not isinstance(observations, list) or len(observations) != 1:
        raise AssertionError("Young Direct Chat expected one Observation")
    data = observations[0].get("data")
    if not isinstance(data, dict):
        raise AssertionError("Young Observation data is unavailable")
    return data


def _young_activity_line(
    item: dict[str, object],
    *,
    include_apply: bool = False,
    include_capacity: bool = False,
    include_description: bool = False,
) -> str:
    name = str(item.get("name") or item.get("activity_id") or "未命名活动")
    window = item.get("event_window")
    start = window.get("start") if isinstance(window, dict) else None
    hours = item.get("valid_hours")
    capacity = item.get("capacity")
    remaining = None
    if isinstance(capacity, dict):
        registered = capacity.get("registered")
        limit = capacity.get("limit")
        if isinstance(registered, int) and isinstance(limit, int):
            remaining = max(0, limit - registered)
    details = [name]
    if start:
        details.append(f"时间 {start}")
    if isinstance(hours, (int, float)) and not isinstance(hours, bool):
        details.append(f"有效学时 {hours:g}")
    if remaining is not None:
        details.append(f"余位 {remaining}")
    if include_capacity and isinstance(capacity, dict):
        details.append(
            f"容量 {capacity.get('limit')}，已报名 {capacity.get('registered')}"
        )
    if include_apply:
        apply_window = item.get("apply_window")
        if isinstance(apply_window, dict):
            details.append(
                f"报名窗口 {apply_window.get('start')} 至 {apply_window.get('end')}"
            )
        status = item.get("status")
        if isinstance(status, dict) and status.get("text"):
            details.append(f"状态 {status.get('text')}")
    if include_description and item.get("description"):
        details.append(f"要求：{item.get('description')}")
    return "，".join(details)


def _young_lines(
    items: list[dict[str, object]],
    **line_options: bool,
) -> str:
    if not items:
        return "按当前条件没有查到匹配的第二课堂活动。"
    return "；".join(
        _young_activity_line(item, **line_options) for item in items
    ) + "。"


def _young_module(item: dict[str, object]) -> str:
    module = item.get("module")
    return str(module.get("name") or "") if isinstance(module, dict) else ""


def _young_event_start(item: dict[str, object]) -> datetime | None:
    window = item.get("event_window")
    value = window.get("start") if isinstance(window, dict) else None
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


def _young_apply_end(item: dict[str, object]) -> datetime | None:
    window = item.get("apply_window")
    value = window.get("end") if isinstance(window, dict) else None
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


def _young_remaining(item: dict[str, object]) -> int | None:
    capacity = item.get("capacity")
    if not isinstance(capacity, dict):
        return None
    registered = capacity.get("registered")
    limit = capacity.get("limit")
    if type(registered) is not int or type(limit) is not int:
        return None
    return max(0, limit - registered)


def _young_capacity_limit(item: dict[str, object]) -> int:
    capacity = item.get("capacity")
    value = capacity.get("limit") if isinstance(capacity, dict) else 0
    return value if type(value) is int else 0


def _young_registered(item: dict[str, object]) -> int:
    capacity = item.get("capacity")
    value = capacity.get("registered") if isinstance(capacity, dict) else 0
    return value if type(value) is int else 0


def _young_fill_ratio(item: dict[str, object]) -> float:
    limit = _young_capacity_limit(item)
    return _young_registered(item) / limit if limit else 0.0


def _young_valid_hours(item: dict[str, object]) -> float:
    value = item.get("valid_hours")
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else 0.0
    )


def _young_duration(item: dict[str, object]) -> float:
    window = item.get("event_window")
    if not isinstance(window, dict):
        return 0.0
    start = window.get("start")
    end = window.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return 0.0
    seconds = (
        datetime.fromisoformat(end) - datetime.fromisoformat(start)
    ).total_seconds()
    return max(0.0, seconds / 3600)


def _young_efficiency(item: dict[str, object]) -> float:
    duration = _young_duration(item)
    return _young_valid_hours(item) / duration if duration else 0.0


def _young_can_apply(item: dict[str, object]) -> bool:
    status = item.get("status")
    code = status.get("code") if isinstance(status, dict) else None
    end = _young_apply_end(item)
    return (
        code == 26
        and (_young_remaining(item) or 0) > 0
        and end is not None
        and datetime(2026, 8, 29, 9, 30) <= end
    )


def _young_ratio_line(item: dict[str, object]) -> str:
    return (
        f"{item.get('name')}，报名 {_young_registered(item)}/"
        f"{_young_capacity_limit(item)}，填充率 {_young_fill_ratio(item):.0%}"
    )


def _young_capacity_line(item: dict[str, object]) -> str:
    return (
        f"{item.get('name')}，容量 {_young_capacity_limit(item)}，"
        f"已报名 {_young_registered(item)}，余位 {_young_remaining(item)}"
    )


def _young_efficiency_line(
    item: dict[str, object],
    *,
    include_description: bool = False,
) -> str:
    answer = (
        f"{item.get('name')}，{_young_valid_hours(item):g} 学时/"
        f"{_young_duration(item):g} 小时={_young_efficiency(item):.2g} 学时/小时，"
        f"余位 {_young_remaining(item)}"
    )
    if include_description and item.get("description"):
        description = str(item.get("description")).rstrip("。；; ")
        answer += f"，要求：{description}"
    return answer


def _young_delivery_text(chains: list[object]) -> str:
    texts: list[str] = []
    for chain in chains:
        if not isinstance(chain, list):
            continue
        for component in chain:
            if not isinstance(component, tuple) or not component:
                continue
            if component[0] == "plain":
                texts.append(str(component[1]))
            elif component[0] == "nodes":
                texts.extend(
                    str(node[1])
                    for node in component[1]
                    if isinstance(node, tuple) and node and node[0] == "node"
                )
    return "".join(texts)


def _assert_young_answer_semantics(case_id: int, answer: str) -> None:
    required = {
        2: ("人工智能前沿公开讲座",),
        19: ("德育：", "智育：", "体育：", "美育：", "劳育："),
        21: ("报名窗口", "余位"),
        22: ("2026-08-29T18:00:00",),
        23: ("报名窗口", "2026-08-29T18:00:00"),
        24: ("2026-08-20T08:00:00", "2026-08-29T18:00:00"),
        25: ("活动已满", "不能报名"),
        26: ("结项", "不能报名"),
        27: ("余位 500", "可以报名"),
        29: ("报名截止", "活动时间"),
        35: ("生涯发展系列讲座", "余位 500"),
        36: ("校园劳动志愿服务", "余位 4"),
        37: ("人工智能前沿公开讲座", "科学精神与学术道德", "生涯发展系列讲座"),
        38: ("机器人社团小组工作坊", "100%", "校园劳动志愿服务", "90%", "新生体能训练体验", "75%"),
        40: ("人工智能前沿公开讲座", "有效学时 2"),
        41: ("校园劳动志愿服务", "有效学时 3"),
        43: ("1 学时/小时", "效率相同"),
        45: ("不能据此推断", "子活动"),
        46: ("学时/小时", "要求：", "不保证实际获得学时"),
        47: ("学时/小时", "不保证实际获得学时"),
        48: ("生涯发展系列讲座", "容量 500"),
        49: ("机器人社团小组工作坊", "容量 12"),
        50: ("人工智能前沿公开讲座", "已报名 180"),
        51: ("机器人社团小组工作坊", "填充率 100%"),
        52: ("校园劳动志愿服务", "填充率 90%"),
        53: ("人工智能前沿公开讲座", "科学精神与学术道德", "生涯发展系列讲座"),
        54: ("人工智能前沿公开讲座", "余位 120", "机器人社团小组工作坊", "余位 0", "当前更容易报名"),
        55: ("没有历史抢报数据", "不能判断"),
        60: ("是系列活动",),
        61: ("2026-08-29T09:00:00",),
        62: ("生涯发展系列讲座第一场", "1.5 学时"),
    }
    forbidden = {
        2: ("机器人社团小组工作坊", "生涯发展系列讲座"),
        21: ("机器人社团小组工作坊",),
        35: ("人工智能前沿公开讲座",),
        36: ("机器人社团小组工作坊",),
        37: ("校园美育艺术赏析", "校园劳动志愿服务"),
        38: ("人工智能前沿公开讲座",),
        40: ("机器人社团小组工作坊", "生涯发展系列讲座"),
        48: ("人工智能前沿公开讲座",),
        49: ("校园劳动志愿服务",),
    }
    missing = [value for value in required.get(case_id, ()) if value not in answer]
    unexpected = [value for value in forbidden.get(case_id, ()) if value in answer]
    if missing or unexpected:
        raise AssertionError(
            f"Young case {case_id} semantic mismatch: missing={missing}, "
            f"unexpected={unexpected}, answer={answer}"
        )


def _icourse_benchmark_questions() -> tuple[tuple[int, str], ...]:
    source = ICOURSE_BENCHMARK.read_text(encoding="utf-8")
    headings = list(ICOURSE_CASE_HEADING_RE.finditer(source))
    questions: list[tuple[int, str]] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        block = source[heading.end() : end]
        question = block.split("**Q：**", maxsplit=1)[1]
        question = re.split(r"\n\*\*(?:预期|考察)：\*\*", question, maxsplit=1)[0]
        normalized = " ".join(
            line.strip() for line in question.splitlines() if line.strip()
        )
        questions.append((int(heading.group(1)), normalized))
    return tuple(questions)


def _young_native_cases() -> tuple[dict[str, object], ...]:
    document = json.loads(YOUNG_NATIVE_CASES.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("unsupported Young native fixture schema")
    cases = tuple(document.get("cases", ()))
    if [item.get("case_id") for item in cases] != list(range(1, 76)):
        raise ValueError("Young native cases must be continuous from 1 through 75")
    return cases


class _BlockingAstrBotProvider(_AstrBotProvider):
    def __init__(self, provider_id: str = "astrbot-luna") -> None:
        super().__init__(provider_id)
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.cancelled.set()


class _SucceedsThenBlocksAstrBotProvider(_AstrBotProvider):
    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        if len(self.calls) == 1:
            return SimpleNamespace(
                completion_text="OK",
                usage=SimpleNamespace(input_other=2, input_cached=0, output=1),
            )
        await asyncio.Future()


class At:
    def __init__(self, qq: str) -> None:
        self.qq = qq
        self.name = None


class Plain:
    def __init__(self, text: str) -> None:
        self.text = text


class _Event:
    def __init__(
        self,
        *,
        group_id: str = "group-1",
        message_id: str = "message-1",
        message_str: str = "@嘟嘟哒 你好",
    ) -> None:
        self.stop_calls = 0
        self.send_calls = 0
        self.sent_chains: list[object] = []
        self.message_str = message_str
        self.message_obj = SimpleNamespace(
            message_id=message_id,
            timestamp=1_786_723_200,
            message=[At("bot-1")],
            raw_message={"time": 1_786_723_200, "message": []},
        )
        self._group_id = group_id

    def stop_event(self) -> None:
        self.stop_calls += 1

    def get_platform_id(self) -> str:
        return "qq-adapter-1"

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def get_self_id(self) -> str:
        return "bot-1"

    def get_sender_id(self) -> str:
        return "user-1"

    def get_group_id(self) -> str:
        return self._group_id

    def get_message_type(self) -> str:
        return "group"

    def get_messages(self) -> list[object]:
        return list(self.message_obj.message)

    def is_admin(self) -> bool:
        return False

    async def send(self, chain: object) -> None:
        self.send_calls += 1
        self.sent_chains.append(chain)

    def chain_result(self, components: list[object]) -> list[object]:
        return components


class _YoungNativeEvent(_Event):
    """OneBot-shaped group message consumed by the production Connector."""

    def __init__(self, case: dict[str, object]) -> None:
        case_id = int(case["case_id"])
        question = str(case["question"])
        timestamp = 1_787_968_200 + case_id
        message_id = 910_000_000 + case_id
        super().__init__(
            group_id="2000000001",
            message_id=str(message_id),
            message_str=question,
        )
        self.message_obj = SimpleNamespace(
            message_id=str(message_id),
            timestamp=timestamp,
            message=[At("1000000001"), Plain(question)],
            raw_message={
                "time": timestamp,
                "self_id": 1_000_000_001,
                "post_type": "message",
                "message_type": "group",
                "sub_type": "normal",
                "message_id": message_id,
                "group_id": 2_000_000_001,
                "user_id": 3_000_000_001,
                "message": [
                    {"type": "at", "data": {"qq": "1000000001"}},
                    {"type": "text", "data": {"text": f" {question}"}},
                ],
                "raw_message": f"[CQ:at,qq=1000000001] {question}",
                "font": 0,
                "sender": {
                    "user_id": 3_000_000_001,
                    "nickname": "young-benchmark-user",
                    "card": "",
                    "role": "member",
                },
            },
        )

    def get_self_id(self) -> str:
        return "1000000001"

    def get_sender_id(self) -> str:
        return "3000000001"


class _Closeable:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class _FailOnceCloseable(_Closeable):
    async def close(self) -> None:
        self.close_calls += 1
        if self.close_calls == 1:
            raise RuntimeError("transient close failure")


class _MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class ProductionCompositionContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_provider_retention_and_reasoning_budget_assemble(self) -> None:
        values = self._runtime_config()
        specs = json.loads(values["runtime_models_json"])
        specs[0].update(model_id="deepseek-v4-flash", retention_mode="provider_managed",
                        data_residency="CN", max_output_tokens=8192)
        values.update(runtime_models_json=json.dumps(specs), runtime_allow_provider_retention=True,
                      runtime_direct_output_tokens=8192, runtime_perception_output_tokens=4096,
                      runtime_reasoning_output_reserve_tokens=4096)
        assembly = composition.build_production_runtime(self._production_plugin(_AstrBotProvider()), values)
        try:
            self.assertTrue(assembly.ready)
            endpoint = assembly._model_health_probes[0].descriptor.endpoints[0]
            self.assertEqual(endpoint.available_data_residencies, frozenset({"CN"}))
            self.assertEqual(endpoint.supported_retention_modes, frozenset({ModelRetentionMode.PROVIDER_MANAGED}))
            self.assertEqual(composition._default_runtime_budget(values).output_tokens_remaining, 12288)
            self.assertEqual(composition._default_runtime_budget().output_tokens_remaining, 8000)
        finally:
            await assembly.close()

    def test_provider_managed_retention_requires_explicit_approval(self) -> None:
        values = self._runtime_config()
        specs = json.loads(values["runtime_models_json"])
        specs[0].update(retention_mode="provider_managed", data_residency="CN")
        values["runtime_models_json"] = json.dumps(specs)
        with self.assertRaisesRegex(ValueError, "explicit_operator_approval"):
            composition.build_production_runtime(_Plugin(), values)

    def test_all_academic_read_schemas_are_plannable(self) -> None:
        for path in sorted(
            (ROOT / "configs" / "capabilities" / "definitions").glob(
                "ustc.academic.*.v1.json"
            )
        ):
            definition = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(
                supports_production_query_schema(
                    definition["capability_id"],
                    definition["input_schema"]["document"],
                ),
                path.name,
            )

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "rollout.sqlite3"
        self.fixture = OrchestratorFixture()
        self.icourse_fixture_context = None
        self.icourse_fixture_base_url = None
        _, self.call = self.fixture.start()
        self.capability_patches = (
            patch.object(
                composition,
                "CAPABILITY_DEFINITIONS_DIR",
                ROOT / "configs" / "capabilities" / "definitions",
            ),
            patch.object(
                composition,
                "CAPABILITY_MAPPINGS_DIR",
                ROOT / "configs" / "capabilities" / "mappings",
            ),
            patch.object(
                composition,
                "RUNTIME_STATUS_PATH",
                Path(self.temp.name) / "runtime-status.json",
            ),
        )
        for active_patch in self.capability_patches:
            active_patch.start()

    def tearDown(self) -> None:
        if self.icourse_fixture_context is not None:
            self.icourse_fixture_context.__exit__(None, None, None)
        for active_patch in reversed(self.capability_patches):
            active_patch.stop()
        self.temp.cleanup()

    def _live_icourse_fixture(self) -> str:
        if self.icourse_fixture_base_url is None:
            self.icourse_fixture_context = icourse_fixture_server()
            self.icourse_fixture_base_url = self.icourse_fixture_context.__enter__()
        return self.icourse_fixture_base_url

    async def _wait_until(self, predicate, *, timeout: float = 1.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate():
            if loop.time() >= deadline:
                self.fail("condition was not reached before timeout")
            await asyncio.sleep(0.002)

    def _plugin(self, mode: RolloutMode = RolloutMode.OFF) -> _Plugin:
        plugin = _Plugin()
        plugin.rollout_ledger = ledger(self.path)
        plugin.rollout_controls = _MutableControls(control(mode))
        plugin.rollout_metrics = InMemoryRolloutMetrics()
        plugin.rollout_bridge = None
        plugin.runtime_assembly = None
        plugin._dududa_runtime_cleanup_assemblies = []
        return plugin

    def _production_plugin(
        self,
        provider: _AstrBotProvider | None = None,
        *,
        evidence_enabled: bool = True,
    ) -> _Plugin:
        plugin = _Plugin()
        plugin.context = _ProviderContext(
            {provider.provider_id: provider} if provider is not None else {},
            evidence_enabled=evidence_enabled,
        )
        plugin.icourse = _ICourseFacade()
        plugin.unified_mcp_client = plugin.icourse.client
        return plugin

    def _runtime_config(
        self,
        *,
        astrbot_provider_id: str = "astrbot-luna",
        rollout_mode: str = "off",
    ) -> dict[str, object]:
        return {
            "runtime_enabled": True,
            "runtime_models_json": json.dumps(
                [
                    {
                        "provider_id": "openai-luna",
                        "astrbot_provider_id": astrbot_provider_id,
                        "endpoint_id": "luna",
                        "model_id": "gpt-5.6-luna",
                        "tier": "haiku",
                        "reasoning_depth": "light",
                        "max_context_tokens": 128_000,
                        "max_output_tokens": 4_096,
                        "max_concurrency": 4,
                        "rpm_limit": 60,
                        "tpm_limit": 100_000,
                    }
                ]
            ),
            "runtime_response_profiles_enabled": True,
            "rollout_mode": rollout_mode,
            "rollout_revision": f"rollout-{rollout_mode}-test-v1",
            "rollout_delivery_enabled": False,
            "rollout_allowlisted_groups": ["group-1"],
            "rollout_kill_switch": rollout_mode != "shadow",
            "rollout_tools_enabled": False,
            "rollout_memory_enabled": False,
        }

    def _provider_evidence_path(
        self,
        *,
        model_id: str = "gpt-5.6-luna",
    ) -> Path:
        path = Path(self.temp.name) / f"provider-evidence-{model_id}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "providers": [
                        {
                            "schema_version": 1,
                            "astrbot_provider_id": "astrbot-luna",
                            "host_version": "astrbot-test",
                            "conformance_revision": {
                                "component_id": "astrbot-provider-conformance",
                                "implementation_version": "1.0.0",
                                "config_revision": "private-test-v1",
                                "artifact_digest": "private:astrbot-luna-v1",
                            },
                            "verified_model_id": model_id,
                            "verified_max_output_tokens": 4_096,
                            "verified_data_residencies": ["global"],
                            "verified_retention_modes": ["no_retention"],
                            "single_request_verified": True,
                            "model_binding_verified": True,
                            "output_limit_verified": True,
                            "residency_verified": True,
                            "retention_verified": True,
                            "sanitized_logging_verified": True,
                            "deadline_enforcement_verified": True,
                            "cancellation_enforcement_verified": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _healthy_evidence(
        assembly: ProductionRuntimeAssembly,
        observed_at: datetime,
        *,
        ttl: timedelta = timedelta(seconds=5),
    ) -> ModelHealthEvidence:
        registry = assembly.model_operational_registry
        if registry is None:
            raise AssertionError("model operational registry is unavailable")
        initial = registry.acquire_snapshot()
        provider = initial.provider_health[0]
        endpoint = provider.endpoints[0]
        health = ModelProviderHealth(
            schema_version=1,
            provider_id=provider.provider_id,
            status=EndpointHealthStatus.HEALTHY,
            endpoints=(
                ModelEndpointHealth(
                    schema_version=1,
                    endpoint_id=endpoint.endpoint_id,
                    endpoint_descriptor_digest=endpoint.endpoint_descriptor_digest,
                    status=EndpointHealthStatus.HEALTHY,
                    reason_codes=(),
                ),
            ),
            snapshot_revision="astrbot-preflight-test-v1",
            checked_at=observed_at,
            reason_codes=(),
        )
        return ModelHealthEvidence(
            schema_version=1,
            provider_revision=composition._revision(
                f"model-provider:{provider.provider_id}"
            ),
            health=health,
            expires_at=observed_at + ttl,
            evidence_revision="astrbot-preflight-test-v1",
        )

    def _initialize(
        self,
        plugin: _Plugin,
        values: dict[str, object],
        directory: str,
        *,
        runtime_assembly: ProductionRuntimeAssembly | None = None,
    ) -> None:
        root = Path(self.temp.name) / directory
        with (
            patch.object(config, "PLUGIN_DATA_DIR", root),
            patch.object(config, "PLUGIN_CONFIG_PATH", root / "config.json"),
            patch.object(config, "ASTRBOT_CONFIG_PATH", root / "astrbot.json"),
            patch.object(composition, "PLUGIN_DATA_DIR", root),
            patch.object(composition, "ROLLOUT_LEDGER_PATH", root / "rollout.sqlite3"),
            patch.object(composition, "MCP_REGISTRY_DIR", root / "missing-registry"),
            patch.object(composition, "MCP_WORKER_PYTHON", root / "missing-worker"),
            patch.object(
                composition,
                "build_icourse_client",
                return_value=(plugin.icourse, "unified", "unified_ready"),
            ),
            patch.object(
                composition,
                "build_unified_mcp_client",
                return_value=(plugin.unified_mcp_client, "unified_ready"),
            ),
            patch.object(audit, "PLUGIN_DATA_DIR", root),
        ):
            composition.initialize_plugin(
                plugin,
                values,
                runtime_assembly=runtime_assembly,
            )

    async def test_builder_accepts_private_provider_evidence_file(self) -> None:
        provider = _AstrBotProvider()
        plugin = _Plugin()
        plugin.context = _ProviderRegistryContext({provider.provider_id: provider})
        plugin.icourse = _ICourseFacade()
        plugin.unified_mcp_client = plugin.icourse.client
        values = self._runtime_config()
        values["runtime_provider_evidence_path"] = str(self._provider_evidence_path())

        assembly = composition.build_production_runtime(
            plugin,
            values,
        )

        self.assertTrue(assembly.ready)
        self.assertIsNotNone(assembly.model_operational_registry)
        snapshot = assembly.model_operational_registry.acquire_snapshot()
        self.assertIs(
            snapshot.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertIs(
            snapshot.provider_health[0].endpoints[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertEqual(provider.calls, [])
        await assembly.close()

    async def test_builder_rejects_mismatched_private_provider_evidence(self) -> None:
        provider = _AstrBotProvider()
        plugin = _Plugin()
        plugin.context = _ProviderRegistryContext({provider.provider_id: provider})
        plugin.icourse = _ICourseFacade()
        plugin.unified_mcp_client = plugin.icourse.client
        values = self._runtime_config()
        values["runtime_provider_evidence_path"] = str(
            self._provider_evidence_path(model_id="gpt-5.6-terra")
        )

        with self.assertRaisesRegex(
            ValueError,
            "provider conformance evidence is unavailable",
        ):
            composition.build_production_runtime(plugin, values)

    async def test_enabled_health_probe_publishes_and_periodically_refreshes(
        self,
    ) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        values = self._runtime_config()
        values.update(
            {
                "runtime_health_probe_enabled": True,
                "runtime_health_probe_interval_seconds": 0.01,
                "runtime_health_probe_timeout_seconds": 0.1,
                "runtime_health_evidence_ttl_seconds": 0.2,
            }
        )

        self._initialize(plugin, values, "production-health-refresh")
        await self._wait_until(lambda: len(provider.calls) >= 2)

        snapshot = plugin.runtime_assembly.model_operational_registry.acquire_snapshot()
        self.assertIs(
            snapshot.provider_health[0].status,
            EndpointHealthStatus.HEALTHY,
        )
        self.assertEqual(provider.calls[0]["model"], "gpt-5.6-luna")
        self.assertEqual(provider.calls[0]["max_tokens"], 8)
        self.assertEqual(provider.calls[0]["request_max_retries"], 1)
        self.assertNotIn("reasoning_effort", provider.calls[0])

        await plugin.terminate()
        calls_after_close = len(provider.calls)
        await asyncio.sleep(0.02)
        self.assertEqual(len(provider.calls), calls_after_close)
        self.assertIsNone(plugin._dududa_model_health_task)

    async def test_timed_out_health_probe_publishes_unknown(self) -> None:
        provider = _BlockingAstrBotProvider()
        plugin = self._production_plugin(provider)
        values = self._runtime_config()
        values.update(
            {
                "runtime_health_probe_enabled": True,
                "runtime_health_probe_interval_seconds": 60,
                "runtime_health_probe_timeout_seconds": 0.01,
                "runtime_health_evidence_ttl_seconds": 1,
            }
        )

        self._initialize(plugin, values, "production-health-timeout")
        await self._wait_until(provider.cancelled.is_set)
        await self._wait_until(
            lambda: (
                plugin.runtime_assembly.model_operational_registry.acquire_snapshot()
                .provider_health[0]
                .reason_codes
                == ("health_probe_failed",)
            )
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["request_max_retries"], 1)
        await plugin.terminate()

    async def test_transient_probe_timeout_keeps_unexpired_health_evidence(
        self,
    ) -> None:
        provider = _SucceedsThenBlocksAstrBotProvider()
        plugin = self._production_plugin(provider)
        observed_at = datetime.now(timezone.utc)
        clock = _MutableClock(observed_at)
        assembly = composition.build_production_runtime(
            plugin,
            self._runtime_config(),
            clock=clock,
        )

        healthy = await assembly.refresh_model_health(
            timeout_seconds=0.1,
            evidence_ttl=timedelta(seconds=30),
        )
        self.assertIs(
            healthy.provider_health[0].status,
            EndpointHealthStatus.HEALTHY,
        )

        clock.now = observed_at + timedelta(seconds=1)
        transient_timeout = await assembly.refresh_model_health(
            timeout_seconds=0.01,
            evidence_ttl=timedelta(seconds=30),
        )
        self.assertIs(
            transient_timeout.provider_health[0].status,
            EndpointHealthStatus.HEALTHY,
        )

        clock.now = observed_at + timedelta(seconds=31)
        expired = await assembly.refresh_model_health(
            timeout_seconds=0.01,
            evidence_ttl=timedelta(seconds=30),
        )
        self.assertIs(
            expired.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertEqual(len(provider.calls), 3)
        await assembly.close()

    async def test_health_refresh_keeps_long_lived_runtime_load_eligible(
        self,
    ) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        observed_at = datetime.now(timezone.utc)
        clock = _MutableClock(observed_at)
        values = self._runtime_config(rollout_mode="shadow")
        assembly = composition.build_production_runtime(
            plugin,
            values,
            clock=clock,
        )
        clock.now = observed_at + timedelta(minutes=31)

        snapshot = await assembly.refresh_model_health(
            timeout_seconds=1,
            evidence_ttl=timedelta(minutes=30),
        )

        self.assertEqual(snapshot.endpoint_load[0].checked_at, clock.now)
        self._initialize(
            plugin,
            values,
            "production-health-long-lived",
            runtime_assembly=assembly,
        )
        result = await plugin.rollout_bridge.handle(_Event(message_id="long-lived"))
        await plugin.rollout_bridge._shadow.drain()

        self.assertIs(result.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        self.assertGreater(len(provider.calls), 1)
        await plugin.terminate()

    async def test_health_probe_without_running_loop_stays_unknown(self) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        values = self._runtime_config()
        self._initialize(plugin, values, "production-health-no-loop")
        plugin.config["runtime_health_probe_enabled"] = True

        with patch.object(
            composition.asyncio,
            "get_running_loop",
            side_effect=RuntimeError,
        ):
            composition._start_model_health_refresh(plugin)

        snapshot = plugin.runtime_assembly.model_operational_registry.acquire_snapshot()
        self.assertIs(
            snapshot.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertEqual(provider.calls, [])
        self.assertIsNone(plugin._dududa_model_health_task)
        await plugin.terminate()

    async def test_auto_assembled_off_runtime_never_calls_provider(self) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        self._initialize(plugin, self._runtime_config(), "production-off")

        event = _Event()
        result = await plugin.rollout_bridge.handle(event)

        self.assertTrue(plugin.runtime_assembly.ready)
        self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
        self.assertEqual(result.reason_code, "rollout_not_active")
        self.assertEqual(provider.calls, [])
        self.assertEqual(event.stop_calls, 0)
        self.assertEqual(event.send_calls, 0)
        await plugin.terminate()

    async def test_auto_assembled_shadow_with_unknown_health_does_not_call_or_send(
        self,
    ) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        self._initialize(
            plugin,
            self._runtime_config(rollout_mode="shadow"),
            "production-shadow",
        )

        event = _Event()
        result = await plugin.rollout_bridge.handle(event)
        await plugin.rollout_bridge.close()

        self.assertTrue(plugin.runtime_assembly.ready)
        self.assertIs(result.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        self.assertTrue(result.legacy_owner)
        self.assertFalse(result.runtime_owner)
        self.assertEqual(provider.calls, [])
        self.assertEqual(event.stop_calls, 0)
        self.assertEqual(event.send_calls, 0)
        await plugin.terminate()

    async def test_production_preview_history_completes_without_sending(self) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        self._initialize(plugin, self._runtime_config(rollout_mode="shadow"),
                         "production-preview-history")
        try:
            await plugin.runtime_assembly.refresh_model_health(
                timeout_seconds=1, evidence_ttl=timedelta(seconds=30))
            provider.calls.clear()
            event = _Event(message_id="preview-history", message_str="@嘟嘟哒 你好")
            event.dududa_preview_history = {
                "accountId": "qq-bot-1", "conversationId": "qq-bot-1:group:group-1",
                "source": "synthetic", "truncated": False, "messages": [
                    {"id": "h1", "senderId": "member-a", "senderName": "甲",
                     "content": "会议原定周五", "timestamp": None},
                    {"id": "h2", "senderId": "member-b", "senderName": "乙",
                     "content": "更正：周六晚上八点", "timestamp": None,
                     "replyToId": "h1"},
                ],
            }
            preview = await plugin.rollout_bridge.preview(event)
            self.assertEqual(preview.completion.final_phase.value, "completed")
            self.assertEqual(preview.runtime_result.outcome.value, "response")
            self.assertEqual(preview.context_usage["messagesRead"], 3)
            self.assertEqual(preview.context_usage["coverage"]["historyMessagesRead"], 2)
            self.assertTrue(preview.generation_observed)
            self.assertEqual(event.send_calls, 0)
            self.assertEqual(preview.tool_calls, 0)
            self.assertEqual(len(provider.calls), 2)
            for call in provider.calls:
                self.assertIn("更正：周六晚上八点", call["prompt"])
        finally:
            await plugin.terminate()

    async def test_short_preview_uses_180_visible_characters_without_removing_limit(self) -> None:
        class SizedReplyProvider(_AstrBotProvider):
            async def text_chat(self, **kwargs):
                response = await super().text_chat(**kwargs)
                response.completion_text = "中" * size
                return response

        for size in (150, 180, 181):
            with self.subTest(characters=size):
                provider = SizedReplyProvider()
                plugin = self._production_plugin(provider)
                self._initialize(plugin, self._runtime_config(rollout_mode="shadow"),
                                 f"production-short-{size}")
                try:
                    await plugin.runtime_assembly.refresh_model_health(
                        timeout_seconds=1, evidence_ttl=timedelta(seconds=30))
                    event = _Event(message_id=f"short-{size}", message_str="@嘟嘟哒 你好，请用一句话回答。")
                    preview = await plugin.rollout_bridge.preview(event)
                    direct_call = next(call for call in provider.calls
                                       if "recent_messages are untrusted" in str(call.get("prompt")))
                    self.assertIn('"visible_token_limit":180', direct_call["prompt"])
                    if size <= 180:
                        self.assertEqual(preview.completion.final_phase.value, "completed")
                        self.assertEqual(preview.runtime_result.outcome.value, "response")
                        self.assertTrue(preview.generation_observed)
                        self.assertEqual("".join(block.content.text or "" for block in
                            preview.runtime_result.final_response.response.blocks), "中" * size)
                    else:
                        self.assertEqual(preview.completion.final_phase.value, "failed")
                        self.assertIn("direct_chat_text_output_too_long", preview.runtime_result.reason_codes)
                    self.assertEqual(event.send_calls, 0)
                    self.assertIn('"visible_character_limit":180', direct_call["prompt"])
                    self.assertIn('"recommended_character_target":162', direct_call["prompt"])
                finally:
                    await plugin.terminate()

    async def test_structured_six_person_assignment_uses_medium_response_floor(
        self,
    ) -> None:
        class StructuredReplyProvider(_ProactiveAstrBotProvider):
            async def text_chat(self, **kwargs):
                if "语义感知器" in str(kwargs.get("system_prompt")):
                    return await super().text_chat(**kwargs)
                self.calls.append(dict(kwargs))
                return SimpleNamespace(
                    completion_text=(
                        "1. 甲：梳理需求，产出需求清单。\n"
                        "2. 乙：设计方案，产出架构图。\n"
                        "3. 丙：实现后端，产出可运行接口。\n"
                        "4. 丁：实现前端，产出可交互页面。\n"
                        "5. 戊：设计测试，产出验收记录。\n"
                        "6. 己：整理发布，产出部署说明。"
                    ),
                    usage=SimpleNamespace(
                        input_other=32,
                        input_cached=0,
                        output=80,
                    ),
                )

        provider = StructuredReplyProvider()
        plugin = self._production_plugin(provider)
        self._initialize(
            plugin,
            self._runtime_config(rollout_mode="shadow"),
            "production-structured-six-person",
        )
        try:
            await plugin.runtime_assembly.refresh_model_health(
                timeout_seconds=1,
                evidence_ttl=timedelta(seconds=30),
            )
            provider.calls.clear()
            event = _Event(
                message_id="structured-six-person",
                message_str="@嘟嘟哒 给一个 6 人小组安排任务，要求每个人都有明确产出。",
            )

            preview = await plugin.rollout_bridge.preview(event)

            self.assertEqual(preview.completion.final_phase.value, "completed")
            self.assertEqual(preview.runtime_result.outcome.value, "response")
            response = preview.runtime_result.final_response
            self.assertIsNotNone(response)
            self.assertEqual(response.profile_validation.selected_profile, "medium")
            direct_prompt = next(
                str(call.get("prompt"))
                for call in provider.calls
                if "语义感知器" not in str(call.get("system_prompt"))
            )
            self.assertIn('"visible_character_limit":720', direct_prompt)
            self.assertEqual(event.send_calls, 0)
        finally:
            await plugin.terminate()

    async def test_production_preview_exact_literal_ignores_mention_and_provider_punctuation(
        self,
    ) -> None:
        from astrbot_plugin_dududa_core.web_runtime import WebRuntimePreviewEvent

        class PunctuatedReplyProvider(_ProactiveAstrBotProvider):
            async def text_chat(self, **kwargs):
                if "语义感知器" in str(kwargs.get("system_prompt")):
                    return await super().text_chat(**kwargs)
                self.calls.append(dict(kwargs))
                return SimpleNamespace(
                    completion_text="收到。",
                    usage=SimpleNamespace(input_other=8, input_cached=0, output=2),
                )

        provider = PunctuatedReplyProvider()
        plugin = self._production_plugin(provider)
        self._initialize(
            plugin,
            self._runtime_config(rollout_mode="shadow"),
            "production-exact-literal-mention",
        )
        try:
            await plugin.runtime_assembly.refresh_model_health(
                timeout_seconds=1,
                evidence_ttl=timedelta(seconds=30),
            )
            event = WebRuntimePreviewEvent(
                bot_id="bot-1",
                group_id="group-1",
                prompt="这条请只回复“收到”。",
            )

            preview = await plugin.rollout_bridge.preview(event)

            self.assertEqual(
                preview.completion.final_phase.value,
                "completed",
                preview.runtime_result.reason_codes,
            )
            self.assertEqual(preview.runtime_result.outcome.value, "response")
            response = preview.runtime_result.final_response
            self.assertIsNotNone(response)
            self.assertEqual(response.response.blocks[0].content.text, "收到")
            self.assertEqual(preview.tool_calls, 0)
        finally:
            await plugin.terminate()

    async def test_multi_message_summary_auto_profile_respects_explicit_and_locked_limits(self) -> None:
        class SummaryProvider(_ProactiveAstrBotProvider):
            async def text_chat(self, **kwargs):
                response = await super().text_chat(**kwargs)
                if "语义感知器" in str(kwargs.get("system_prompt")):
                    payload = json.loads(response.completion_text)
                    payload.update(task_kind="bounded_transformation", speech_acts=["request"])
                    payload["complexity_signals"][0]["code"] = "bounded_transformation"
                    response.completion_text = json.dumps(payload, ensure_ascii=False)
                elif '"selected_profile":"short"' in str(kwargs.get("prompt")):
                    response.completion_text = "只据最近窗口：会议更正为周六二十点，不代表全天。"
                else:
                    response.completion_text = "只据最近十条消息，会议更正为周六二十点。" + "这是合成历史中已确认的讨论事项，不代表全天记录。" * 7
                return response

        cases = (
            ("总结这个群今天的讨论。", 10, None, "medium"),
            ("Please summarize today's group discussion.", 10, None, "medium"),
            ("总结这个群今天的讨论，请用一句话概括。", 10, None, "short"),
            ("总结这个群今天的讨论。", 10, "short", "short"),
            ("总结这个群今天的讨论。", 10, "long", "long"),
            ("翻译这条消息成英文。", 10, None, "short"),
            ("请总结这段文字：“群里有人要求总结消息。”", 10, None, "short"),
            ("总结这个群今天的讨论。", 1, None, "short"),
        )
        for index, (prompt, count, forced, expected) in enumerate(cases):
            with self.subTest(prompt=prompt, history=count, forced=forced):
                provider = SummaryProvider()
                plugin = self._production_plugin(provider)
                self._initialize(plugin, self._runtime_config(rollout_mode="shadow"),
                                 f"production-history-profile-{index}")
                if forced:
                    plugin.rollout_bridge._requests._scope_policy_resolver = SimpleNamespace(
                        feature_flags=lambda connector: {f"response_profile.force_{forced}": True})
                try:
                    await plugin.runtime_assembly.refresh_model_health(
                        timeout_seconds=1, evidence_ttl=timedelta(seconds=30))
                    event = _Event(message_id=f"history-profile-{index}", message_str=f"@嘟嘟哒 {prompt}")
                    event.dududa_preview_history = {
                        "accountId": "qq-bot-1", "conversationId": "qq-bot-1:group:group-1",
                        "source": "synthetic", "truncated": False, "messages": [
                            {"id": f"h{number}", "senderId": "member-a", "senderName": "甲",
                             "content": f"第{number}项讨论已确认；会议更正为周六二十点。",
                             "timestamp": f"2026-09-04T02:{number:02d}:00+00:00"}
                            for number in range(count)
                        ],
                    }
                    preview = await plugin.rollout_bridge.preview(event)
                    self.assertEqual(preview.completion.final_phase.value, "completed", preview.runtime_result.reason_codes)
                    self.assertEqual(preview.runtime_result.outcome.value, "response")
                    self.assertEqual(preview.context_usage["coverage"]["historyMessagesRead"], count)
                    self.assertEqual(preview.runtime_result.final_response.profile_validation.selected_profile, expected)
                    self.assertEqual(preview.runtime_result.selection_summary.selected_tier.value, "haiku")
                    self.assertEqual(event.send_calls, 0)
                    self.assertEqual(preview.tool_calls, 0)
                    if expected == "medium":
                        self.assertGreater(preview.runtime_result.final_response.profile_validation.visible_characters, 180)
                finally:
                    await plugin.terminate()

    async def test_natural_language_icourse_uses_2_0_runtime_and_unified_mcp(
        self,
    ) -> None:
        database = Path(self.temp.name) / "icourse-runtime.sqlite3"
        server = replace_server_definition(
            icourse_definition(
                database,
                base_url=self._live_icourse_fixture(),
            ),
            timeouts=McpTimeoutPolicy(
                connect=timedelta(seconds=10),
                discovery=timedelta(seconds=10),
                call=timedelta(seconds=10),
                maximum_call=timedelta(seconds=30),
                close=timedelta(seconds=5),
            ),
        )
        managed = ManagedUnifiedMcpClient(
            _StaticRegistry(server),
            factory(),
            JsonSchemaMcpValidator(),
        )
        recording_mcp = RecordingUnifiedClient(managed)
        provider = _ScriptedAstrBotProvider()
        plugin = self._production_plugin(provider)
        plugin.icourse = _ICourseFacade(recording_mcp)
        plugin.unified_mcp_client = recording_mcp
        values = self._runtime_config(rollout_mode="canary")
        values.update(
            {
                "rollout_delivery_enabled": True,
                "rollout_kill_switch": False,
                "rollout_tools_enabled": True,
            }
        )
        self._initialize(plugin, values, "production-icourse-natural-language")
        plugin.rollout_bridge._output_factory = (
            lambda event, ledger, guard: AstrBotOutputAdapter(
                event,
                ledger,
                component_factory=_ComponentFactory(),
                send_guard=guard,
            )
        )
        observed_at = datetime.now(timezone.utc)
        await plugin.runtime_assembly.publish_model_health(
            (self._healthy_evidence(plugin.runtime_assembly, observed_at),),
            call=replace(
                self.call,
                deadline=observed_at + timedelta(minutes=1),
            ),
        )
        event = _Event(
            message_id="natural-language-icourse",
            message_str="@嘟嘟哒 查询评课社区吴天",
        )

        try:
            result = await plugin.rollout_bridge.handle(event)

            self.assertIs(result.action, AstrBotBridgeAction.CANARY_COMPLETED)
            self.assertEqual(event.stop_calls, 1)
            self.assertEqual(
                event.send_calls,
                1,
                (result.canary, provider.calls, recording_mcp.tool_calls),
            )
            self.assertEqual(len(event.sent_chains), 1)
            self.assertEqual(event.sent_chains[0][0][0], "nodes")
            self.assertEqual(len(provider.calls), 2)
            self.assertIn("语义感知器", provider.calls[0]["system_prompt"])
            self.assertIn("自然参与对话", provider.calls[1]["system_prompt"])
            self.assertIn("campus.course-review", provider.calls[0]["prompt"])
            self.assertIn(
                "synthesize its source content into a self-contained answer",
                provider.calls[1]["prompt"],
            )
            self.assertIn(
                "Do not substitute bare URLs, a link list, raw JSON",
                provider.calls[1]["prompt"],
            )
            self.assertIn("campus.academic", provider.calls[0]["prompt"])
            self.assertIn("campus.shuttle", provider.calls[0]["prompt"])
            self.assertIn("campus.second-class", provider.calls[0]["prompt"])
            self.assertEqual(
                [item["reasoning_effort"] for item in provider.calls],
                ["low", "low"],
            )
            self.assertEqual(
                [
                    (server_id, tool_name, arguments)
                    for server_id, tool_name, arguments, _call in (
                        recording_mcp.tool_calls
                    )
                ],
                [
                    (
                        "icourse",
                        "icourse_public_query",
                        {
                            "query": "吴天",
                            "goal": "@嘟嘟哒 查询评课社区吴天",
                            "operation": "teacher",
                            "limit": 10,
                        },
                    )
                ],
            )
            rendered = repr(
                (provider.calls, recording_mcp.tool_calls, event.sent_chains)
            )
            self.assertIn("数学分析(B1)", rendered)
            self.assertNotIn("https://", repr(event.sent_chains))
            for forbidden in (
                "web_search_baidu",
                "search_site_courses",
                "我先查找",
                "我再检索",
                "正在查询",
                "ToolPlan",
                "tool-plan:",
            ):
                self.assertNotIn(forbidden, rendered)
        finally:
            await plugin.terminate()
        self.assertTrue(recording_mcp.closed)

    async def test_proactive_event_normalizes_to_chat_only_runtime(
        self,
    ) -> None:
        provider = _ProactiveAstrBotProvider()
        plugin = self._production_plugin(provider)
        values = self._runtime_config(rollout_mode="canary")
        values.update(
            {
                "rollout_delivery_enabled": True,
                "rollout_kill_switch": False,
                "rollout_tools_enabled": True,
            }
        )
        self._initialize(plugin, values, "production-proactive-talk")
        plugin.rollout_bridge._output_factory = (
            lambda event, ledger, guard: AstrBotOutputAdapter(
                event,
                ledger,
                component_factory=_ComponentFactory(),
                send_guard=guard,
            )
        )
        observed_at = datetime.now(timezone.utc)
        await plugin.runtime_assembly.publish_model_health(
            (self._healthy_evidence(plugin.runtime_assembly, observed_at),),
            call=replace(self.call, deadline=observed_at + timedelta(minutes=1)),
        )
        try:
            tool_source = _Event(
                message_id="proactive-tool-source",
                message_str="普通消息",
            )
            chat_source = _Event(
                message_id="proactive-chat-source",
                message_str="普通消息",
            )
            astrbot_module = ModuleType("astrbot")
            api_module = ModuleType("astrbot.api")
            components_module = ModuleType("astrbot.api.message_components")
            components_module.Plain = Plain
            astrbot_module.api = api_module
            api_module.message_components = components_module
            with patch.dict(
                sys.modules,
                {
                    "astrbot": astrbot_module,
                    "astrbot.api": api_module,
                    "astrbot.api.message_components": components_module,
                },
            ):
                tool_event = ProactiveTalkEvent(
                    tool_source,
                    f"{PROACTIVE_GROUP_PROMPT_MARKER}\n"
                    "最近大家在问校车时间，接一句话。",
                )
                chat_event = ProactiveTalkEvent(
                    chat_source,
                    f"{PROACTIVE_GROUP_PROMPT_MARKER}\n"
                    "最近大家在说十二点五十回高新，接一句话。",
                )
            tool_chat = await plugin.rollout_bridge.handle(
                tool_event,
                proactive_group_participation=True,
            )
            delivered = await plugin.rollout_bridge.handle(
                chat_event,
                proactive_group_participation=True,
            )

            self.assertIs(tool_chat.action, AstrBotBridgeAction.CANARY_COMPLETED)
            self.assertEqual(
                tool_chat.runtime_reason_codes,
                ("delivery_ready", "proactive_group_direct_reply"),
            )
            self.assertEqual(tool_source.stop_calls, 0)
            self.assertEqual(tool_source.send_calls, 1)
            self.assertIs(delivered.action, AstrBotBridgeAction.CANARY_COMPLETED)
            self.assertEqual(delivered.canary.disposition.value, "delivered")
            self.assertEqual(
                delivered.runtime_reason_codes,
                ("delivery_ready", "proactive_group_direct_reply"),
            )
            self.assertEqual(chat_source.stop_calls, 0)
            self.assertEqual(chat_source.send_calls, 1)
            self.assertEqual(len(provider.calls), 4)
            self.assertTrue(
                all(call["reasoning_effort"] == "low" for call in provider.calls)
            )
        finally:
            await plugin.terminate()

    async def test_shuttle_questions_use_local_plugin_provider_in_2_0_runtime(
        self,
    ) -> None:
        document = json.loads(SHUTTLE_NATIVE_CASES.read_text(encoding="utf-8"))
        selected_ids = {6, 11, 20}
        cases = tuple(
            item for item in document["cases"] if int(item["case_id"]) in selected_ids
        )
        self.assertEqual([int(item["case_id"]) for item in cases], [6, 11, 20])
        fixed_now = datetime.fromisoformat(document["observed_at"]).astimezone(
            timezone.utc
        )
        provider = _ShuttleBenchmarkAstrBotProvider(cases)
        plugin = self._production_plugin(provider)
        unified_mcp_client = plugin.unified_mcp_client
        values = self._runtime_config(rollout_mode="canary")
        values.update(
            {
                "rollout_delivery_enabled": True,
                "rollout_kill_switch": False,
                "rollout_tools_enabled": True,
            }
        )
        assembly = composition.build_production_runtime(
            plugin,
            values,
            clock=lambda: fixed_now,
        )
        self._initialize(
            plugin,
            values,
            "production-shuttle-plugin",
            runtime_assembly=assembly,
        )
        plugin.rollout_bridge._output_factory = (
            lambda event, ledger, guard: AstrBotOutputAdapter(
                event,
                ledger,
                component_factory=_ComponentFactory(),
                send_guard=guard,
                clock=lambda: fixed_now,
            )
        )
        await plugin.runtime_assembly.publish_model_health(
            (
                self._healthy_evidence(
                    plugin.runtime_assembly,
                    fixed_now,
                    ttl=timedelta(minutes=10),
                ),
            ),
            call=replace(self.call, deadline=fixed_now + timedelta(minutes=1)),
        )

        try:
            for case in cases:
                event = _Event(
                    message_id=f"shuttle-{case['case_id']}",
                    message_str=f"@嘟嘟哒 {case['question']}",
                )
                result = await plugin.rollout_bridge.handle(event)
                with self.subTest(case_id=case["case_id"]):
                    self.assertIs(
                        result.action,
                        AstrBotBridgeAction.CANARY_COMPLETED,
                    )
                    self.assertEqual(event.stop_calls, 1)
                    self.assertEqual(event.send_calls, 1)
                    self.assertEqual(len(event.sent_chains), 1)
            self.assertEqual(len(provider.calls), 6)
            self.assertTrue(
                all(
                    "plugin://ustc-shuttle/ustc-shuttle-timetable-v1"
                    in str(call["prompt"])
                    for call in provider.calls[1::2]
                )
            )
        finally:
            await plugin.terminate()
        self.assertTrue(unified_mcp_client.closed)

    async def test_all_icourse_benchmark_messages_reach_2_0_mcp_dispatch(
        self,
    ) -> None:
        benchmark = _icourse_benchmark_questions()
        self.assertEqual([case_id for case_id, _ in benchmark], list(range(1, 76)))
        explicit_marker_ids = {
            case_id for case_id, question in benchmark if "评课社区" in question
        }
        self.assertEqual(
            explicit_marker_ids,
            {1, 7, 8, 16, 17, 20, 22, 28, 29, 30, 32, 33, 34, 35, 36, 37, 40, 72, 74},
        )
        regression_fixture = json.loads(
            ICOURSE_ROUTING_REGRESSIONS.read_text(encoding="utf-8")
        )
        self.assertEqual(regression_fixture["schema_version"], 1)
        regression_cases = regression_fixture["cases"]
        self.assertEqual(
            [item["strict_semantic_status"] for item in regression_cases],
            ["partial", "unsupported", "partial"],
        )
        regression_queries = {
            item["question"]: item["expected_query"] for item in regression_cases
        }
        provider = _ICourseBenchmarkAstrBotProvider(regression_queries)
        database = Path(self.temp.name) / "icourse-runtime-benchmark.sqlite3"
        server = replace_server_definition(
            icourse_definition(
                database,
                base_url=self._live_icourse_fixture(),
            ),
            timeouts=McpTimeoutPolicy(
                connect=timedelta(seconds=10),
                discovery=timedelta(seconds=10),
                call=timedelta(seconds=10),
                maximum_call=timedelta(seconds=30),
                close=timedelta(seconds=5),
            ),
        )
        managed = ManagedUnifiedMcpClient(
            _StaticRegistry(server),
            factory(),
            JsonSchemaMcpValidator(),
        )
        recording_mcp = RecordingUnifiedClient(managed)
        plugin = self._production_plugin(provider)
        plugin.icourse = _ICourseFacade(recording_mcp)
        plugin.unified_mcp_client = recording_mcp
        values = self._runtime_config(rollout_mode="canary")
        model_specs = json.loads(str(values["runtime_models_json"]))
        model_specs[0]["rpm_limit"] = 1_000
        model_specs[0]["tpm_limit"] = 10_000_000
        values["runtime_models_json"] = json.dumps(model_specs)
        values.update(
            {
                "rollout_delivery_enabled": True,
                "rollout_kill_switch": False,
                "rollout_tools_enabled": True,
            }
        )
        self._initialize(plugin, values, "production-icourse-benchmark")
        plugin.rollout_bridge._output_factory = (
            lambda event, ledger, guard: AstrBotOutputAdapter(
                event,
                ledger,
                component_factory=_ComponentFactory(),
                send_guard=guard,
            )
        )
        observed_at = datetime.now(timezone.utc)
        await plugin.runtime_assembly.publish_model_health(
            (
                self._healthy_evidence(
                    plugin.runtime_assembly,
                    observed_at,
                    ttl=timedelta(minutes=10),
                ),
            ),
            call=replace(
                self.call,
                deadline=observed_at + timedelta(minutes=1),
            ),
        )
        scenarios = [
            (f"benchmark-{case_id:02d}", question)
            for case_id, question in benchmark
        ] + [
            (str(item["case_id"]), str(item["question"]))
            for item in regression_cases
        ]
        events: list[_Event] = []

        try:
            for scenario_id, question in scenarios:
                event = _Event(
                    message_id=scenario_id,
                    message_str=f"@嘟嘟哒 {question}",
                )
                result = await plugin.rollout_bridge.handle(event)
                events.append(event)
                with self.subTest(scenario_id=scenario_id):
                    self.assertIs(result.action, AstrBotBridgeAction.CANARY_COMPLETED)
                    self.assertEqual(event.stop_calls, 1)
                    self.assertEqual(
                        event.send_calls,
                        1,
                        (scenario_id, result.canary, len(recording_mcp.tool_calls)),
                    )
                    self.assertEqual(len(event.sent_chains), 1)

            calls = [
                (server_id, tool_name, arguments)
                for server_id, tool_name, arguments, _call in recording_mcp.tool_calls
            ]
            self.assertEqual(len(calls), 78)
            self.assertTrue(
                all(
                    server_id == "icourse"
                    and tool_name == "icourse_public_query"
                    and arguments["operation"] == "course"
                    for server_id, tool_name, arguments in calls
                )
            )
            self.assertEqual(
                sum(
                    not model_requests_tools
                    for _question, model_requests_tools in provider.perception_decisions
                ),
                22,
            )
            self.assertEqual(
                [arguments["query"] for _server, _tool, arguments in calls[-3:]],
                ["人工智能", "萌萌哒mmd", "线性代数B1"],
            )
            self.assertEqual(len(provider.calls), 156)
            rendered = repr((provider.calls, recording_mcp.tool_calls, events))
            for forbidden in (
                "web_search_baidu",
                "search_site_courses",
                "我先查找",
                "我再检索",
                "正在查询",
                "ToolPlan",
                "tool-plan:",
            ):
                self.assertNotIn(forbidden, rendered)
        finally:
            await plugin.terminate()
        self.assertTrue(recording_mcp.closed)

    async def test_all_young_native_messages_use_only_the_2_0_runtime(
        self,
    ) -> None:
        cases = _young_native_cases()
        self.assertEqual(len(cases), 75)
        self.assertEqual(
            sum(item["tool_name"] is not None for item in cases),
            62,
        )
        provider = _YoungBenchmarkAstrBotProvider(cases)
        fixed_now = datetime(2026, 8, 29, 1, 30, tzinfo=timezone.utc)
        managed = ManagedUnifiedMcpClient(
            _StaticRegistry(young_fixture_definition()),
            factory(),
            JsonSchemaMcpValidator(),
            wall_clock=lambda: fixed_now,
        )
        recording_mcp = RecordingUnifiedClient(managed)
        plugin = self._production_plugin(provider)
        plugin.icourse = _ICourseFacade(recording_mcp)
        plugin.unified_mcp_client = recording_mcp
        values = self._runtime_config(rollout_mode="canary")
        model_specs = json.loads(str(values["runtime_models_json"]))
        model_specs[0]["rpm_limit"] = 1_000
        model_specs[0]["tpm_limit"] = 10_000_000
        values["runtime_models_json"] = json.dumps(model_specs)
        values.update(
            {
                "rollout_allowlisted_groups": ["2000000001"],
                "rollout_delivery_enabled": True,
                "rollout_kill_switch": False,
                "rollout_tools_enabled": True,
            }
        )
        assembly = composition.build_production_runtime(
            plugin,
            values,
            clock=lambda: fixed_now,
        )
        self._initialize(
            plugin,
            values,
            "production-young-native-benchmark",
            runtime_assembly=assembly,
        )
        plugin.rollout_bridge._output_factory = (
            lambda event, ledger, guard: AstrBotOutputAdapter(
                event,
                ledger,
                component_factory=_ComponentFactory(),
                send_guard=guard,
                clock=lambda: fixed_now,
            )
        )
        await plugin.runtime_assembly.publish_model_health(
            (
                self._healthy_evidence(
                    plugin.runtime_assembly,
                    fixed_now,
                    ttl=timedelta(minutes=10),
                ),
            ),
            call=replace(self.call, deadline=fixed_now + timedelta(minutes=1)),
        )
        events: list[_YoungNativeEvent] = []
        calls_by_case: dict[int, list[tuple[str, str, object, object]]] = {}

        try:
            for case in cases:
                case_id = int(case["case_id"])
                before = len(recording_mcp.tool_calls)
                event = _YoungNativeEvent(case)
                result = await plugin.rollout_bridge.handle(event)
                events.append(event)
                calls_by_case[case_id] = recording_mcp.tool_calls[before:]
                with self.subTest(case_id=case_id):
                    self.assertIs(
                        result.action,
                        AstrBotBridgeAction.CANARY_COMPLETED,
                    )
                    self.assertEqual(event.stop_calls, 1)
                    self.assertEqual(event.send_calls, 1)
                    self.assertEqual(len(event.sent_chains), 1)
                    _assert_young_answer_semantics(
                        case_id,
                        _young_delivery_text(event.sent_chains),
                    )
                    expected_count = 1 if case["tool_name"] is not None else 0
                    self.assertEqual(len(calls_by_case[case_id]), expected_count)

            self.assertEqual(len(provider.calls), 150)
            self.assertEqual(len(recording_mcp.tool_calls), 62)
            self.assertEqual(
                sum(not needed for _case_id, needed in provider.perception_decisions),
                13,
            )
            self.assertEqual(
                [
                    (server_id, tool_name)
                    for server_id, tool_name, _arguments, _call in (
                        recording_mcp.tool_calls
                    )
                ].count(("ustc-young", "young_search_activities")),
                51,
            )
            for case in cases:
                case_id = int(case["case_id"])
                calls = calls_by_case[case_id]
                if not calls:
                    continue
                server_id, tool_name, arguments, _call = calls[0]
                self.assertEqual(server_id, "ustc-young")
                self.assertEqual(tool_name, case["tool_name"])
                if tool_name == "young_search_activities":
                    self.assertEqual(arguments["query"], case["expected_query"])
                    self.assertEqual(
                        arguments["state"],
                        case.get("expected_state", "applying"),
                    )
                    self.assertEqual(arguments["limit"], 8)
                elif tool_name == "young_get_activity":
                    self.assertEqual(
                        arguments,
                        {
                            "activity_id": case["expected_activity_id"],
                            "include_children": case["expected_include_children"],
                        },
                    )
                elif tool_name == "young_list_facets":
                    self.assertEqual(
                        arguments,
                        {"facet": case["expected_facet"]},
                    )
                else:
                    self.assertEqual(arguments, {})

            self.assertEqual(len(calls_by_case[1]), 1)
            self.assertFalse(provider.perception_decisions[0][1])
            self.assertTrue(dict(provider.perception_decisions)[70])
            self.assertEqual(calls_by_case[70], [])
            for case_id in range(63, 76):
                self.assertEqual(calls_by_case[case_id], [])
            rendered_output = repr(
                [event.sent_chains for event in events]
            )
            for forbidden in (
                "web_search_baidu",
                "search_site_courses",
                "young_list_my_activities",
                "young_apply",
                "young_cancel_apply",
                "ReplyPolish",
                "我先查找",
                "我再检索",
                "正在查询",
                "ToolPlan",
                "tool-plan:",
            ):
                self.assertNotIn(forbidden, rendered_output)
            self.assertTrue(
                all(
                    event.message_obj.raw_message["post_type"] == "message"
                    and event.message_obj.raw_message["message_type"] == "group"
                    and event.send_calls == 1
                    for event in events
                )
            )
        finally:
            await plugin.terminate()
        self.assertTrue(recording_mcp.closed)

    async def test_shadow_uses_endpoint_fixed_reasoning_after_healthy_evidence(
        self,
    ) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        observed_at = datetime.now(timezone.utc)
        clock = _MutableClock(observed_at)
        assembly = composition.build_production_runtime(
            plugin,
            self._runtime_config(rollout_mode="shadow"),
            clock=clock,
        )
        await assembly.publish_model_health(
            (self._healthy_evidence(assembly, observed_at),),
            call=replace(
                self.call,
                deadline=observed_at + timedelta(minutes=1),
            ),
        )
        self._initialize(
            plugin,
            self._runtime_config(rollout_mode="shadow"),
            "production-shadow-healthy",
            runtime_assembly=assembly,
        )

        event = _Event()
        result = await plugin.rollout_bridge.handle(event)
        await plugin.rollout_bridge.close()

        self.assertIs(result.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        # Hybrid Perception + Direct Chat is the complete 2.0 shadow path;
        # both calls use the endpoint's fixed reasoning profile.
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(
            all(call["reasoning_effort"] == "low" for call in provider.calls)
        )
        self.assertEqual(event.stop_calls, 0)
        self.assertEqual(event.send_calls, 0)
        await plugin.terminate()

    async def test_shadow_stops_calling_provider_after_health_ttl(self) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        observed_at = datetime.now(timezone.utc)
        clock = _MutableClock(observed_at)
        values = self._runtime_config(rollout_mode="shadow")
        assembly = composition.build_production_runtime(
            plugin,
            values,
            clock=clock,
        )
        await assembly.publish_model_health(
            (self._healthy_evidence(assembly, observed_at),),
            call=replace(
                self.call,
                deadline=observed_at + timedelta(minutes=1),
            ),
        )
        self._initialize(
            plugin,
            values,
            "production-shadow-health-ttl",
            runtime_assembly=assembly,
        )

        first = await plugin.rollout_bridge.handle(_Event(message_id="healthy"))
        await plugin.rollout_bridge._shadow.drain()
        self.assertIs(first.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        self.assertEqual(len(provider.calls), 2)

        clock.now = observed_at + timedelta(seconds=6)
        snapshot = assembly.model_operational_registry.acquire_snapshot()
        self.assertIs(
            snapshot.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        second = await plugin.rollout_bridge.handle(_Event(message_id="expired"))
        await plugin.rollout_bridge.close()

        self.assertIs(second.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        self.assertEqual(len(provider.calls), 2)
        await plugin.terminate()

    async def test_missing_or_unknown_provider_falls_back_to_legacy(self) -> None:
        cases = {
            "runtime-disabled": (None, True, {}),
            "unknown-provider": (
                None,
                True,
                self._runtime_config(astrbot_provider_id="missing-provider"),
            ),
            "missing-evidence": (
                _AstrBotProvider(),
                False,
                self._runtime_config(),
            ),
        }
        for name, (provider, evidence_enabled, values) in cases.items():
            with self.subTest(name=name):
                plugin = self._production_plugin(
                    provider,
                    evidence_enabled=evidence_enabled,
                )
                self._initialize(plugin, values, name)

                event = _Event()
                result = await plugin.rollout_bridge.handle(event)

                self.assertFalse(plugin.runtime_assembly.ready)
                self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
                self.assertEqual(event.stop_calls, 0)
                self.assertEqual(event.send_calls, 0)
                await plugin.terminate()

    async def test_unavailable_default_never_reads_or_claims_an_event(self) -> None:
        plugin = self._plugin(RolloutMode.CANARY)
        assembly = unavailable_runtime_assembly()
        bridge = install_production_runtime(
            plugin,
            assembly,
            self.call.budget,
            "policy-v1",
        )
        self.assertIsNotNone(bridge)

        event = _Event()
        result = await bridge.handle(event)

        self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
        self.assertEqual(result.reason_code, "rollout_runtime_unavailable")
        self.assertEqual(event.stop_calls, 0)
        self.assertEqual(plugin.rollout_ledger.recover_incomplete(), ())
        await plugin.terminate()

    async def test_plugin_initialization_installs_one_default_off_bridge(self) -> None:
        root = Path(self.temp.name) / "plugin-data"
        plugin = _Plugin()
        with (
            patch.object(config, "PLUGIN_DATA_DIR", root),
            patch.object(config, "PLUGIN_CONFIG_PATH", root / "config.json"),
            patch.object(config, "ASTRBOT_CONFIG_PATH", root / "astrbot.json"),
            patch.object(composition, "PLUGIN_DATA_DIR", root),
            patch.object(composition, "ROLLOUT_LEDGER_PATH", root / "rollout.sqlite3"),
            patch.object(composition, "MCP_REGISTRY_DIR", root / "missing-registry"),
            patch.object(composition, "MCP_WORKER_PYTHON", root / "missing-worker"),
            patch.object(composition, "build_icourse_client") as build_compatibility,
            patch.object(audit, "PLUGIN_DATA_DIR", root),
        ):
            composition.initialize_plugin(plugin, {})

        build_compatibility.assert_not_called()
        self.assertIsNotNone(plugin.rollout_bridge)
        self.assertIsNotNone(plugin.runtime_assembly)
        self.assertFalse(plugin.runtime_assembly.ready)
        self.assertEqual(plugin.icourse_mode, "unavailable")
        self.assertEqual(
            plugin.icourse_reason,
            "unified_infrastructure_missing",
        )
        self.assertEqual(
            json.loads(composition.RUNTIME_STATUS_PATH.read_text(encoding="utf-8"))[
                "state"
            ],
            "disabled",
        )
        self.assertIs(
            plugin.rollout_ledger.config.journal_mode,
            SQLiteJournalMode.DELETE,
        )
        event = _Event()
        result = await plugin.rollout_bridge.handle(event)
        self.assertEqual(result.reason_code, "rollout_not_active")
        self.assertEqual(event.stop_calls, 0)
        await plugin.terminate()
        self.assertFalse(plugin._dududa_runtime_initialized)

    async def test_repeated_plugin_initialization_preserves_the_first_owner(
        self,
    ) -> None:
        root = Path(self.temp.name) / "plugin-repeat"
        plugin = _Plugin()
        resource = _Closeable()
        assembly = ProductionRuntimeAssembly(
            _RuntimeProxy(self.fixture.runtime),
            ready=True,
            closeables=(resource,),
        )
        with (
            patch.object(config, "PLUGIN_DATA_DIR", root),
            patch.object(config, "PLUGIN_CONFIG_PATH", root / "config.json"),
            patch.object(config, "ASTRBOT_CONFIG_PATH", root / "astrbot.json"),
            patch.object(composition, "PLUGIN_DATA_DIR", root),
            patch.object(composition, "ROLLOUT_LEDGER_PATH", root / "rollout.sqlite3"),
            patch.object(composition, "MCP_REGISTRY_DIR", root / "missing-registry"),
            patch.object(composition, "MCP_WORKER_PYTHON", root / "missing-worker"),
            patch.object(audit, "PLUGIN_DATA_DIR", root),
        ):
            composition.initialize_plugin(plugin, {}, runtime_assembly=assembly)
            original_bridge = plugin.rollout_bridge
            with self.assertRaisesRegex(RuntimeError, "already initialized"):
                composition.initialize_plugin(plugin, {})

        self.assertIs(plugin.rollout_bridge, original_bridge)
        self.assertIs(plugin.runtime_assembly, assembly)
        self.assertTrue(
            json.loads(composition.RUNTIME_STATUS_PATH.read_text(encoding="utf-8"))[
                "ready"
            ]
        )
        self.assertEqual(resource.close_calls, 0)
        await plugin.terminate()
        self.assertEqual(resource.close_calls, 1)

    async def test_disabled_plugin_never_enters_the_rollout_bridge(self) -> None:
        plugin = _Plugin()
        plugin.enabled = False
        plugin.rollout_bridge = AsyncMock()

        await plugin._handle_controlled_rollout(_Event())

        plugin.rollout_bridge.handle.assert_not_awaited()

    async def test_registered_command_never_enters_the_rollout_bridge(self) -> None:
        plugin = _Plugin()
        plugin.enabled = True
        plugin.rollout_bridge = AsyncMock()
        event = _Event(message_str="sub2api overview")
        event.get_extra = lambda key, default=None: {
            "handlers_parsed_params": {"sub2api.overview": {}}
        }.get(key, default)

        await plugin._handle_controlled_rollout(event)

        plugin.rollout_bridge.handle.assert_not_awaited()
        self.assertEqual(event.stop_calls, 0)

    async def test_non_command_message_still_enters_the_rollout_bridge(self) -> None:
        plugin = _Plugin()
        plugin.enabled = True
        plugin.rollout_bridge = AsyncMock()
        event = _Event(message_str="@嘟嘟哒 你好")
        event.get_extra = lambda key, default=None: {
            "handlers_parsed_params": {}
        }.get(key, default)

        await plugin._handle_controlled_rollout(event)

        plugin.rollout_bridge.handle.assert_awaited_once_with(event)

    async def test_ready_off_composition_is_single_and_closes_once(self) -> None:
        plugin = self._plugin()
        runtime = _RuntimeProxy(self.fixture.runtime)
        resource = _Closeable()
        assembly = ProductionRuntimeAssembly(
            runtime,
            ready=True,
            closeables=(resource,),
        )
        bridge = install_production_runtime(
            plugin,
            assembly,
            self.call.budget,
            "policy-v1",
        )
        self.assertIsNotNone(bridge)

        event = _Event()
        result = await bridge.handle(event)
        self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
        self.assertEqual(runtime.run_calls, 0)
        self.assertEqual(event.stop_calls, 0)
        self.assertIs(
            install_production_runtime(
                plugin,
                assembly,
                self.call.budget,
                "policy-v1",
            ),
            bridge,
        )
        self.assertFalse(assembly.aborted)

        aborted: list[str] = []
        duplicate_resource = _Closeable()
        duplicate = ProductionRuntimeAssembly(
            runtime,
            ready=True,
            closeables=(duplicate_resource,),
            abort_callbacks=(lambda: aborted.append("duplicate"),),
        )
        self.assertIs(
            install_production_runtime(
                plugin,
                duplicate,
                self.call.budget,
                "policy-v1",
            ),
            bridge,
        )
        self.assertEqual(aborted, ["duplicate"])

        await plugin.terminate()
        await plugin.terminate()
        self.assertEqual(resource.close_calls, 1)
        self.assertEqual(duplicate_resource.close_calls, 1)
        self.assertIsNone(plugin.rollout_bridge)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [])

    async def test_partial_install_aborts_and_preserves_legacy_owner(self) -> None:
        plugin = self._plugin()
        plugin.rollout_ledger = None
        aborted: list[str] = []
        assembly = ProductionRuntimeAssembly(
            _RuntimeProxy(self.fixture.runtime),
            ready=True,
            abort_callbacks=(lambda: aborted.append("partial"),),
        )

        result = install_production_runtime(
            plugin,
            assembly,
            self.call.budget,
            "policy-v1",
        )

        self.assertIsNone(result)
        self.assertEqual(aborted, ["partial"])
        self.assertTrue(assembly.aborted)
        self.assertIsNone(plugin.rollout_bridge)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [assembly])
        with self.assertRaisesRegex(RuntimeError, "not installable"):
            install_production_runtime(
                plugin,
                assembly,
                self.call.budget,
                "policy-v1",
            )
        await plugin.terminate()
        self.assertTrue(assembly.closed)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [])

    async def test_closed_assembly_cannot_be_installed(self) -> None:
        plugin = self._plugin()
        assembly = ProductionRuntimeAssembly(
            _RuntimeProxy(self.fixture.runtime),
            ready=True,
        )
        await assembly.close()

        with self.assertRaisesRegex(RuntimeError, "not installable"):
            install_production_runtime(
                plugin,
                assembly,
                self.call.budget,
                "policy-v1",
            )

    async def test_failed_abort_is_retried_during_lifecycle_cleanup(self) -> None:
        plugin = self._plugin()
        plugin.rollout_ledger = None
        calls = 0

        def abort() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transient abort failure")

        assembly = ProductionRuntimeAssembly(
            _RuntimeProxy(self.fixture.runtime),
            ready=True,
            abort_callbacks=(abort,),
        )

        self.assertIsNone(
            install_production_runtime(
                plugin,
                assembly,
                self.call.budget,
                "policy-v1",
            )
        )
        self.assertEqual(calls, 1)
        self.assertFalse(assembly.aborted)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [assembly])

        await plugin.terminate()
        self.assertEqual(calls, 2)
        self.assertTrue(assembly.aborted)
        self.assertTrue(assembly.closed)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [])

    async def test_termination_retries_only_resources_that_failed_to_close(
        self,
    ) -> None:
        plugin = self._plugin()
        runtime = _RuntimeProxy(self.fixture.runtime)
        closed = _Closeable()
        flaky = _FailOnceCloseable()
        assembly = ProductionRuntimeAssembly(
            runtime,
            ready=True,
            closeables=(flaky, closed),
        )
        install_production_runtime(
            plugin,
            assembly,
            self.call.budget,
            "policy-v1",
        )

        with self.assertRaisesRegex(RuntimeError, "transient close failure"):
            await plugin.terminate()
        self.assertIsNone(plugin.rollout_bridge)
        self.assertIs(plugin.runtime_assembly, assembly)
        self.assertEqual(closed.close_calls, 1)
        self.assertEqual(flaky.close_calls, 1)
        self.assertFalse(assembly.closed)

        await plugin.terminate()
        await plugin.terminate()
        self.assertEqual(closed.close_calls, 1)
        self.assertEqual(flaky.close_calls, 2)
        self.assertTrue(assembly.closed)
        self.assertIsNone(plugin.runtime_assembly)

    async def test_termination_retries_failed_icourse_close(self) -> None:
        plugin = self._plugin()
        plugin.icourse = _FailOnceCloseable()

        with self.assertRaisesRegex(RuntimeError, "transient close failure"):
            await plugin.terminate()
        self.assertIsNotNone(plugin.icourse)
        self.assertFalse(plugin._dududa_runtime_terminated)

        await plugin.terminate()
        self.assertIsNone(plugin.icourse)
        self.assertTrue(plugin._dududa_runtime_terminated)


if __name__ == "__main__":
    unittest.main()
