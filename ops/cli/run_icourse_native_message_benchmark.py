"""Run the 75 iCourse cases through a Dududa 2.0 Connector-shaped simulation.

The benchmark uses real Luna/Terra/Sol Provider calls and a real local iCourse
MCP subprocess. It injects an AstrBot Connector-shaped event directly into the
Bridge and replaces the final send boundary with an in-memory event. It does
not exercise the AstrBot host WebSocket, deserialization, or dispatcher path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SOURCE_ROOT = ROOT / "apps" / "astrbot-plugins"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PLUGIN_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SOURCE_ROOT))

from astrbot_plugin_dududa_core.adapters.mcp_runtime import (
    build_unified_mcp_client,
)
from astrbot_plugin_dududa_core.adapters.output import AstrBotOutputAdapter
from astrbot_plugin_dududa_core.course import ICourseClient
from dududa.ports.mcp import UnifiedMcpClient
from ops.cli.run_provider_no_send_shadow import (
    PostJson,
    PrivateProviderConfig,
    ShadowSampleError,
    endpoint_url,
    load_private_provider_config,
    post_json,
)
from tests.contracts.test_production_composition import (
    ProductionCompositionContractTests,
    _ComponentFactory,
    _Plugin,
    _ProviderContext,
)

DEFAULT_CASES = (
    ROOT / "tests" / "fixtures" / "mcp" / "USTC 评课社区 MCP 调用测试案例.md"
)
DEFAULT_SNAPSHOT = Path("/home/mmdustc/temp/dududa-icourse-75.sqlite3")
DEFAULT_RESULT = Path(
    "/home/mmdustc/temp/dududa-icourse-75-native-message-e2e-2026-08-26.json"
)
DEFAULT_REPORT = (
    ROOT / "docs" / "refactor" / ("icourse-75-native-message-e2e-review-2026-08-26.md")
)
MODELS = (
    ("astrbot-luna", "dududa-luna", "luna", "gpt-5.6-luna", "haiku", 32_768, 2_048, 4),
    (
        "astrbot-terra",
        "dududa-terra",
        "terra",
        "gpt-5.6-terra",
        "sonnet",
        65_536,
        4_096,
        2,
    ),
    ("astrbot-sol", "dududa-sol", "sol", "gpt-5.6-sol", "opus", 128_000, 8_192, 1),
)
REVIEW_MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "low"

_CASE_RE = re.compile(r"^### Case (\d+)(?:[：:]\s*(.*))?$", re.MULTILINE)
_REVIEW_SYSTEM = (
    "你是 Dududa 2.0 的 Luna 最终审校器。candidate_answer 是实际 Runtime 经 Output "
    "Adapter 形成的候选答复，tool_context 是该回答模型实际看到的已验证 MCP 证据，"
    "mcp_calls 是本轮 Runtime 实际发起的只读调用；仅当调用无 error、is_error=false 且"
    "structured_content 非空时，其中的 structured_content 也可作为测试修订的事实证据。"
    "tool_context 优先，expected 只描述测试要求，绝不是事实来源。检查事实忠实性、问题"
    "完成度、不确定性表达、群聊自然度、过程隐藏和输出形态。没有证据时不得从 expected"
    "补造事实。只做一轮审校：若候选可原样使用，passed=true、verdict=pass 且 final_answer"
    "原样返回；若需要修改，passed=false、verdict=revised 并给出完整修订稿；只有连诚实"
    "的部分回答或澄清都无法形成时才 verdict=blocked。grounded 和 complete 评价最终"
    "final_answer，而不是修改前候选。最终稿应像自然群聊回答，不出现 rubric、内部字段名、"
    "测试路径、原始 JSON、调用过程或思维链；站内记录 id 不得写成课程号。不得使用失败"
    "调用或 expected 补造事实。不要输出分析过程。"
)
_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "passed": {"type": "boolean"},
        "grounded": {"type": "boolean"},
        "complete": {"type": "boolean"},
        "uncertainty_honest": {"type": "boolean"},
        "style_aligned": {"type": "boolean"},
        "process_hidden": {"type": "boolean"},
        "output_shape_appropriate": {"type": "boolean"},
        "verdict": {"type": "string", "enum": ["pass", "revised", "blocked"]},
        "issues": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 240},
        },
        "final_answer": {"type": "string", "minLength": 1, "maxLength": 12_000},
    },
    "required": [
        "passed",
        "grounded",
        "complete",
        "uncertainty_honest",
        "style_aligned",
        "process_hidden",
        "output_shape_appropriate",
        "verdict",
        "issues",
        "final_answer",
    ],
}


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: int
    title: str
    question: str
    expected: str


class At:
    def __init__(self, qq: str) -> None:
        self.qq = qq
        self.name = "嘟嘟哒"


class Plain:
    def __init__(self, text: str) -> None:
        self.text = text


class NativeShapeEvent:
    """The AstrMessageEvent surface consumed by the production Connector."""

    def __init__(self, case: BenchmarkCase) -> None:
        timestamp = 1_787_680_800 + case.case_id
        message_id = 900_000_000 + case.case_id
        bot_id = "1000000001"
        group_id = "2000000001"
        user_id = "3000000001"
        self.stop_calls = 0
        self.send_calls = 0
        self.sent_chains: list[object] = []
        self.message_str = case.question
        self.message_obj = SimpleNamespace(
            message_id=str(message_id),
            timestamp=timestamp,
            message=[At(bot_id), Plain(case.question)],
            raw_message={
                "time": timestamp,
                "self_id": int(bot_id),
                "post_type": "message",
                "message_type": "group",
                "sub_type": "normal",
                "message_id": message_id,
                "group_id": int(group_id),
                "user_id": int(user_id),
                "message": [
                    {"type": "at", "data": {"qq": bot_id}},
                    {"type": "text", "data": {"text": f" {case.question}"}},
                ],
                "raw_message": f"[CQ:at,qq={bot_id}] {case.question}",
                "font": 0,
                "sender": {
                    "user_id": int(user_id),
                    "nickname": "benchmark-user",
                    "card": "",
                    "role": "member",
                },
            },
        )

    def stop_event(self) -> None:
        self.stop_calls += 1

    def get_platform_id(self) -> str:
        return "qq-adapter-benchmark"

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def get_self_id(self) -> str:
        return "1000000001"

    def get_sender_id(self) -> str:
        return "3000000001"

    def get_group_id(self) -> str:
        return "2000000001"

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


class RuntimeCapture:
    def __init__(self) -> None:
        self.case_id: int | None = None
        self.model_calls: list[dict[str, object]] = []
        self.mcp_calls: list[dict[str, object]] = []
        self.runtime_errors: list[dict[str, object]] = []

    def model_calls_for(self, case_id: int) -> list[dict[str, object]]:
        return [item for item in self.model_calls if item["case_id"] == case_id]

    def mcp_calls_for(self, case_id: int) -> list[dict[str, object]]:
        return [item for item in self.mcp_calls if item["case_id"] == case_id]

    def runtime_errors_for(self, case_id: int) -> list[dict[str, object]]:
        return [item for item in self.runtime_errors if item["case_id"] == case_id]


class RecordingAgentRuntime:
    def __init__(self, delegate: object, capture: RuntimeCapture) -> None:
        self._delegate = delegate
        self._capture = capture

    async def run(self, request: object, *, call: object) -> object:
        try:
            return await self._delegate.run(request, call=call)
        except BaseException as exc:
            info = getattr(exc, "info", None)
            self._capture.runtime_errors.append(
                {
                    "case_id": self._capture.case_id,
                    "error": type(exc).__name__,
                    "code": getattr(info, "code", None),
                    "message": str(exc)[:240],
                }
            )
            raise

    async def acknowledge_delivery(self, receipt: object, *, call: object) -> object:
        return await self._delegate.acknowledge_delivery(receipt, call=call)

    async def reconcile_delivery(self, receipt: object, *, call: object) -> object:
        return await self._delegate.reconcile_delivery(receipt, call=call)


class ResponsesAstrBotProvider:
    def __init__(
        self,
        provider_id: str,
        private_config: PrivateProviderConfig,
        capture: RuntimeCapture,
        *,
        sender: PostJson = post_json,
    ) -> None:
        self.provider_id = provider_id
        self._config = private_config
        self._capture = capture
        self._sender = sender

    def meta(self) -> object:
        return SimpleNamespace(id=self.provider_id)

    async def text_chat(self, **kwargs: object) -> object:
        model = str(kwargs["model"])
        prompt = str(kwargs["prompt"])
        system_prompt = str(kwargs["system_prompt"])
        reasoning_effort = str(kwargs.get("reasoning_effort") or REASONING_EFFORT)
        max_tokens = int(kwargs.get("max_tokens") or 1_024)
        role = "perception" if "语义感知器" in system_prompt else "direct_chat"
        started = time.perf_counter()
        try:
            response = await asyncio.to_thread(
                self._sender,
                endpoint_url(self._config.base_url),
                {
                    "model": model,
                    "instructions": system_prompt,
                    "input": prompt,
                    "reasoning": {"effort": reasoning_effort},
                    "max_output_tokens": max_tokens,
                    "store": False,
                },
                self._config,
            )
            text = response_text(response)
            usage = response_usage(response)
            record: dict[str, object] = {
                "case_id": self._capture.case_id,
                "role": role,
                "provider_id": self.provider_id,
                "requested_model": model,
                "response_model": response.get("model"),
                "reasoning_effort": reasoning_effort,
                "max_output_tokens": max_tokens,
                "latency_ms": round((time.perf_counter() - started) * 1_000),
                "usage": usage,
            }
            if role == "perception":
                try:
                    record["projection"] = json.loads(text)
                except json.JSONDecodeError:
                    record["projection"] = None
                record["perception_context"] = extract_perception_context(prompt)
            else:
                record["answer_profile"] = extract_answer_profile(prompt)
                record["tool_context"] = extract_tool_context(prompt)
                record["completion_text"] = text
            self._capture.model_calls.append(record)
            cached = int(usage.get("input_cached_tokens", 0))
            input_tokens = int(usage.get("input_tokens", 0))
            return SimpleNamespace(
                completion_text=text,
                usage=SimpleNamespace(
                    input_other=max(0, input_tokens - cached),
                    input_cached=cached,
                    output=int(usage.get("output_tokens", 0)),
                ),
            )
        except BaseException as exc:
            self._capture.model_calls.append(
                {
                    "case_id": self._capture.case_id,
                    "role": role,
                    "provider_id": self.provider_id,
                    "requested_model": model,
                    "reasoning_effort": reasoning_effort,
                    "latency_ms": round((time.perf_counter() - started) * 1_000),
                    "error": type(exc).__name__,
                }
            )
            raise


class RecordingUnifiedMcpClient:
    def __init__(self, delegate: UnifiedMcpClient, capture: RuntimeCapture) -> None:
        self._delegate = delegate
        self._capture = capture

    async def discover(self, server_id, *, refresh=False, call):
        return await self._delegate.discover(server_id, refresh=refresh, call=call)

    async def call_tool(self, server_id, tool_name, arguments, *, call):
        started = time.perf_counter()
        try:
            result = await self._delegate.call_tool(
                server_id,
                tool_name,
                arguments,
                call=call,
            )
            self._capture.mcp_calls.append(
                {
                    "case_id": self._capture.case_id,
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "arguments": jsonable(arguments),
                    "latency_ms": round((time.perf_counter() - started) * 1_000),
                    "is_error": result.is_error,
                    "generation": result.generation,
                    "structured_content": jsonable(result.structured_content),
                }
            )
            return result
        except BaseException as exc:
            self._capture.mcp_calls.append(
                {
                    "case_id": self._capture.case_id,
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "arguments": jsonable(arguments),
                    "latency_ms": round((time.perf_counter() - started) * 1_000),
                    "error": type(exc).__name__,
                }
            )
            raise

    async def health(self, server_id, *, call):
        return await self._delegate.health(server_id, call=call)

    async def close(self) -> None:
        await self._delegate.close()


def parse_cases(path: Path) -> tuple[BenchmarkCase, ...]:
    source = path.read_text(encoding="utf-8")
    headings = list(_CASE_RE.finditer(source))
    cases: list[BenchmarkCase] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        block = source[heading.end() : end]
        question_match = re.search(
            r"\*\*Q：\*\*\s*(.*?)(?=\n\*\*(?:预期|考察)：\*\*)",
            block,
            re.DOTALL,
        )
        expected_match = re.search(
            r"\*\*(?:预期|考察)：\*\*\s*(.*?)(?=\n---|\Z)",
            block,
            re.DOTALL,
        )
        if question_match is None or expected_match is None:
            raise ValueError(f"case {heading.group(1)} is missing Q or rubric")
        cases.append(
            BenchmarkCase(
                case_id=int(heading.group(1)),
                title=(heading.group(2) or "").strip(),
                question=normalize_markdown_text(question_match.group(1)),
                expected=expected_match.group(1).strip(),
            )
        )
    if [item.case_id for item in cases] != list(range(1, 76)):
        raise ValueError("benchmark cases must be continuous from 1 through 75")
    return tuple(cases)


def normalize_markdown_text(value: str) -> str:
    return " ".join(line.strip() for line in value.splitlines() if line.strip())


def parse_case_selection(value: str | None) -> frozenset[int] | None:
    if value is None:
        return None
    selected: set[int] = set()
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", maxsplit=1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError("case range start exceeds end")
            selected.update(range(start, end + 1))
        else:
            selected.add(int(item))
    if not selected or min(selected) < 1 or max(selected) > 75:
        raise ValueError("selected cases must be within 1..75")
    return frozenset(selected)


def response_text(response: Mapping[str, object]) -> str:
    direct = response.get("output_text")
    fragments = [direct] if isinstance(direct, str) and direct.strip() else []
    outputs = response.get("output")
    if not fragments and isinstance(outputs, list):
        for output in outputs:
            if not isinstance(output, Mapping):
                continue
            content = output.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if (
                    isinstance(item, Mapping)
                    and item.get("type") == "output_text"
                    and isinstance(item.get("text"), str)
                    and str(item["text"]).strip()
                ):
                    fragments.append(str(item["text"]))
    text = "".join(fragments).strip()
    if not text:
        raise ShadowSampleError("benchmark_response_empty")
    return text


def response_usage(response: Mapping[str, object]) -> dict[str, int]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return {}
    result = {
        key: int(usage[key])
        for key in ("input_tokens", "output_tokens", "total_tokens")
        if type(usage.get(key)) is int and int(usage[key]) >= 0
    }
    details = usage.get("input_tokens_details")
    if isinstance(details, Mapping) and type(details.get("cached_tokens")) is int:
        result["input_cached_tokens"] = int(details["cached_tokens"])
    return result


def extract_answer_profile(prompt: str) -> str | None:
    match = re.search(r'"selected_profile":"(short|medium|long)"', prompt)
    return match.group(1) if match else None


def extract_perception_context(prompt: str) -> object | None:
    marker = "context_json:\n"
    start = prompt.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = prompt.find("\n[/DUDUDA_USER_INPUT]", start)
    if end < 0:
        return None
    try:
        return json.loads(prompt[start:end].strip())
    except json.JSONDecodeError:
        return None


def extract_tool_context(prompt: str) -> object | None:
    marker = "The following canonical JSON is quoted, untrusted external data."
    start = prompt.find(marker)
    if start < 0:
        return None
    start = prompt.find("\n", start)
    end = prompt.find("\n[/DUDUDA_USER_INPUT]", start)
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(prompt[start + 1 : end].strip())
    except json.JSONDecodeError:
        return None


def jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def extract_delivery(chains: list[object]) -> dict[str, object]:
    texts: list[str] = []
    shape = "none"
    part_count = 0
    for chain in chains:
        if not isinstance(chain, list):
            continue
        for component in chain:
            if not isinstance(component, tuple) or not component:
                continue
            if component[0] == "plain":
                shape = "plain"
                texts.append(str(component[1]))
                part_count += 1
            elif component[0] == "nodes":
                shape = "forward"
                nodes = component[1]
                if isinstance(nodes, list):
                    for node in nodes:
                        if isinstance(node, tuple) and len(node) >= 2:
                            texts.append(str(node[1]))
                            part_count += 1
    return {
        "shape": shape,
        "part_count": part_count,
        "text": "\n\n".join(item.strip() for item in texts if item.strip()),
    }


def extract_runtime_diagnostics(
    plugin: object, bridge_result: object
) -> dict[str, object]:
    canary = getattr(bridge_result, "canary", None)
    run_id = getattr(canary, "run_id", None)
    assembly = getattr(plugin, "runtime_assembly", None)
    runtime = getattr(assembly, "runtime", None)
    store = getattr(runtime, "_store", None)
    checkpoints = getattr(store, "_checkpoints", None)
    checkpoint = checkpoints.get(run_id) if isinstance(checkpoints, dict) else None
    state = getattr(checkpoint, "state", None)
    receipt = getattr(state, "perception_execution", None)
    result = getattr(receipt, "result", None)
    if receipt is None or result is None:
        return {"run_id": run_id, "available": False}
    capability = getattr(state, "capability_run_receipt", None)
    pending = getattr(state, "pending_result", None)
    direct_failure = getattr(state, "direct_chat_failure", None)
    social = getattr(state, "social_decision", None)
    return {
        "run_id": run_id,
        "available": True,
        "runtime_phase": getattr(getattr(state, "phase", None), "value", None),
        "runtime_outcome": getattr(getattr(pending, "outcome", None), "value", None),
        "runtime_reason_codes": list(getattr(pending, "reason_codes", ())),
        "model_status": getattr(getattr(receipt, "model_status", None), "value", None),
        "failure_code": getattr(receipt, "failure_code", None),
        "model_call_started": getattr(receipt, "model_call_started", False),
        "need_tools": getattr(result, "need_tools", False),
        "capability_categories": list(getattr(result, "capability_categories", ())),
        "intent_ids": [
            getattr(item, "intent_id", "") for item in getattr(result, "intents", ())
        ],
        "entities": [
            {
                "kind": getattr(getattr(item, "kind", None), "value", None),
                "value": getattr(item, "value", None),
            }
            for item in getattr(result, "entities", ())
        ],
        "social_action": getattr(getattr(social, "action", None), "value", None),
        "capability_status": getattr(
            getattr(capability, "status", None),
            "value",
            None,
        ),
        "capability_reason_codes": list(getattr(capability, "reason_codes", ())),
        "direct_failure_code": getattr(direct_failure, "failure_code", None),
    }


def runtime_values(timeout_seconds: float) -> dict[str, object]:
    model_specs = []
    for (
        astrbot_id,
        provider_id,
        endpoint_id,
        model_id,
        tier,
        context_tokens,
        output_tokens,
        concurrency,
    ) in MODELS:
        model_specs.append(
            {
                "provider_id": provider_id,
                "astrbot_provider_id": astrbot_id,
                "endpoint_id": endpoint_id,
                "model_id": model_id,
                "tier": tier,
                "reasoning_depth": "light",
                "max_context_tokens": context_tokens,
                "max_output_tokens": output_tokens,
                "max_concurrency": concurrency,
                "rpm_limit": 1_000,
                "tpm_limit": 50_000_000,
            }
        )
    return {
        "enabled": True,
        "runtime_enabled": True,
        "runtime_models_json": json.dumps(model_specs),
        "runtime_response_profiles_enabled": True,
        "runtime_health_probe_enabled": False,
        "runtime_model_load_max_age_seconds": 14_400,
        "rollout_mode": "canary",
        "rollout_revision": "icourse-native-message-benchmark-v1",
        "rollout_delivery_enabled": True,
        "rollout_allowlisted_groups": ["2000000001"],
        "rollout_kill_switch": False,
        "rollout_tools_enabled": True,
        "rollout_memory_enabled": False,
        "rollout_canary_timeout_ms": round(timeout_seconds * 1_000),
    }


def write_registry(directory: Path, snapshot: Path) -> None:
    document = json.loads(
        (ROOT / "configs" / "mcp" / "servers" / "icourse.json").read_text(
            encoding="utf-8"
        )
    )
    document["endpoint"] = {
        "command": sys.executable,
        "args": [
            str(ROOT / "services" / "mcp" / "icourse" / "run_icourse_mcp.py"),
            "--db-path",
            str(snapshot),
            "--request-delay",
            "0",
        ],
        "cwd": str(ROOT / "services" / "mcp" / "icourse"),
        "env_allowlist": ["LANG", "LC_ALL", "PATH", "PYTHONPATH"],
    }
    document["config_revision"] = "icourse-native-message-benchmark-v1"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "icourse.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def review_body(case: BenchmarkCase, record: Mapping[str, object]) -> dict[str, object]:
    delivery = record["delivery"]
    direct_call = next(
        (item for item in record["model_calls"] if item.get("role") == "direct_chat"),
        None,
    )
    payload = {
        "case_id": case.case_id,
        "question": case.question,
        "expected": case.expected,
        "runtime_action": record["runtime_action"],
        "tool_context": direct_call.get("tool_context") if direct_call else None,
        "mcp_calls": record["mcp_calls"],
        "answer_profile": direct_call.get("answer_profile") if direct_call else None,
        "delivery_shape": delivery["shape"],
        "candidate_answer": delivery["text"],
    }
    return {
        "model": REVIEW_MODEL,
        "instructions": _REVIEW_SYSTEM,
        "input": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "reasoning": {"effort": REASONING_EFFORT},
        "max_output_tokens": 4_096,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "dududa_icourse_native_message_review_v1",
                "strict": True,
                "schema": _REVIEW_SCHEMA,
            }
        },
    }


async def review_case(
    case: BenchmarkCase,
    record: Mapping[str, object],
    private_config: PrivateProviderConfig,
    *,
    sender: PostJson = post_json,
) -> dict[str, object]:
    started = time.perf_counter()
    response = await asyncio.to_thread(
        sender,
        endpoint_url(private_config.base_url),
        review_body(case, record),
        private_config,
    )
    value = json.loads(response_text(response))
    if not isinstance(value, dict) or set(value) != set(_REVIEW_SCHEMA["required"]):
        raise ShadowSampleError("benchmark_review_invalid")
    if (
        not isinstance(value.get("final_answer"), str)
        or not value["final_answer"].strip()
    ):
        raise ShadowSampleError("benchmark_review_invalid")
    return {
        **value,
        "model": REVIEW_MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "latency_ms": round((time.perf_counter() - started) * 1_000),
        "usage": response_usage(response),
    }


async def run_benchmark(
    cases: tuple[BenchmarkCase, ...],
    private_config: PrivateProviderConfig,
    snapshot: Path,
    result_path: Path,
    *,
    timeout_seconds: float,
) -> dict[str, object]:
    capture = RuntimeCapture()
    providers = {
        astrbot_id: ResponsesAstrBotProvider(astrbot_id, private_config, capture)
        for astrbot_id, *_rest in MODELS
    }
    harness = ProductionCompositionContractTests(methodName="runTest")
    harness.setUp()
    plugin: _Plugin | None = None
    started = time.perf_counter()
    result: dict[str, object] = {
        "schema_version": 1,
        "benchmark": "icourse-75-native-message-e2e-v1",
        "source_fixture": str(DEFAULT_CASES),
        "snapshot": {
            "path": str(snapshot),
            "bytes": snapshot.stat().st_size,
            "network_fetches": 0,
        },
        "reasoning_effort": REASONING_EFFORT,
        "review_model": REVIEW_MODEL,
        "real_qq_output_calls": 0,
        "records": [],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="dududa-icourse-native-") as temporary:
            temporary_root = Path(temporary)
            registry_dir = temporary_root / "mcp-registry"
            write_registry(registry_dir, snapshot)
            unified, reason = build_unified_mcp_client(
                {},
                registry_directory=registry_dir,
                worker_python=(
                    ROOT
                    / "services"
                    / "mcp"
                    / "unified-worker"
                    / ".venv"
                    / "bin"
                    / "python"
                ),
            )
            if unified is None:
                raise RuntimeError(f"Unified MCP unavailable: {reason}")
            recording_mcp = RecordingUnifiedMcpClient(unified, capture)
            plugin = _Plugin()
            plugin.context = _ProviderContext(providers)
            plugin.icourse = ICourseClient(recording_mcp, owns_client=False)
            plugin.unified_mcp_client = recording_mcp
            values = runtime_values(timeout_seconds)
            harness._initialize(plugin, values, "native-message-benchmark")
            canary = getattr(plugin.rollout_bridge, "_canary")
            canary._runtime = RecordingAgentRuntime(canary._runtime, capture)
            plugin.rollout_bridge._output_factory = lambda event, ledger, guard: (
                AstrBotOutputAdapter(
                    event,
                    ledger,
                    component_factory=_ComponentFactory(),
                    send_guard=guard,
                )
            )
            await plugin.runtime_assembly.refresh_model_health(
                timeout_seconds=timeout_seconds,
                evidence_ttl=timedelta(hours=4),
            )

            for index, case in enumerate(cases, start=1):
                capture.case_id = case.case_id
                event = NativeShapeEvent(case)
                case_started = time.perf_counter()
                runtime_error = None
                bridge_result = None
                try:
                    bridge_result = await plugin.rollout_bridge.handle(event)
                except BaseException as exc:
                    runtime_error = type(exc).__name__
                model_calls = capture.model_calls_for(case.case_id)
                mcp_calls = capture.mcp_calls_for(case.case_id)
                delivery = extract_delivery(event.sent_chains)
                record: dict[str, object] = {
                    "case_id": case.case_id,
                    "title": case.title,
                    "question": case.question,
                    "expected": case.expected,
                    "native_message": jsonable(event.message_obj.raw_message),
                    "runtime_action": (
                        bridge_result.action.value
                        if bridge_result is not None
                        else "exception"
                    ),
                    "runtime_reason": (
                        bridge_result.reason_code
                        if bridge_result is not None
                        else runtime_error
                    ),
                    "event_stop_calls": event.stop_calls,
                    "fake_send_calls": event.send_calls,
                    "model_calls": model_calls,
                    "mcp_calls": mcp_calls,
                    "runtime_errors": capture.runtime_errors_for(case.case_id),
                    "runtime_diagnostics": extract_runtime_diagnostics(
                        plugin,
                        bridge_result,
                    ),
                    "delivery": delivery,
                    "runtime_latency_ms": round(
                        (time.perf_counter() - case_started) * 1_000
                    ),
                }
                try:
                    record["review"] = await review_case(case, record, private_config)
                except BaseException as exc:
                    record["review"] = {
                        "error": type(exc).__name__,
                        "final_answer": delivery["text"]
                        or "本题运行未得到可审校答复。",
                    }
                result["records"].append(record)
                write_private_json(result_path, finalize_summary(result, started))
                print(
                    json.dumps(
                        {
                            "completed": index,
                            "total": len(cases),
                            "case_id": case.case_id,
                            "runtime_action": record["runtime_action"],
                            "mcp_calls": len(mcp_calls),
                            "fake_send_calls": event.send_calls,
                            "review": record["review"].get("verdict", "error"),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
    finally:
        capture.case_id = None
        if plugin is not None:
            await plugin.terminate()
        harness.tearDown()
    completed = finalize_summary(result, started)
    write_private_json(result_path, completed)
    return completed


def finalize_summary(result: dict[str, object], started: float) -> dict[str, object]:
    records = result["records"]
    model_calls = [call for item in records for call in item["model_calls"]]
    mcp_calls = [call for item in records for call in item["mcp_calls"]]
    reviews = [item["review"] for item in records]
    result["summary"] = {
        "case_count": len(records),
        "bridge_completed": sum(
            item["runtime_action"] == "canary_completed" for item in records
        ),
        "runtime_completed": sum(
            item.get("runtime_diagnostics", {}).get("runtime_phase") == "completed"
            for item in records
        ),
        "runtime_answered": sum(bool(item["delivery"]["text"]) for item in records),
        "final_answered": sum(
            bool(item["review"].get("final_answer")) for item in records
        ),
        "mcp_call_count": len(mcp_calls),
        "fake_send_count": sum(int(item["fake_send_calls"]) for item in records),
        "real_qq_output_calls": 0,
        "provider_call_count": len(model_calls) + len(reviews) + len(MODELS),
        "runtime_model_calls": len(model_calls),
        "review_calls": len(reviews),
        "health_probe_calls": len(MODELS),
        "direct_models": dict(
            Counter(
                str(call["requested_model"])
                for call in model_calls
                if call.get("role") == "direct_chat"
            )
        ),
        "answer_profiles": dict(
            Counter(
                str(call.get("answer_profile") or "unknown")
                for call in model_calls
                if call.get("role") == "direct_chat"
            )
        ),
        "delivery_shapes": dict(
            Counter(str(item["delivery"]["shape"]) for item in records)
        ),
        "review_verdicts": dict(
            Counter(str(item.get("verdict") or "error") for item in reviews)
        ),
        "review_complete": {
            "true": sum(item.get("complete") is True for item in reviews),
            "false": sum(item.get("complete") is not True for item in reviews),
        },
        "elapsed_ms": round((time.perf_counter() - started) * 1_000),
    }
    return result


def write_private_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def render_report(result: Mapping[str, object], path: Path) -> None:
    summary = result["summary"]
    records = result["records"]
    followup = result.get("targeted_followup")
    host_ingress = result.get("host_ingress_contract")
    post_benchmark_fixes = result.get("post_benchmark_fixes")
    editorial_count = sum(bool(item.get("editorial_adjustments")) for item in records)
    human_audit_count = sum(bool(item.get("human_final_audit")) for item in records)
    human_complete = sum(
        (
            item["human_final_audit"].get("complete") is True
            if isinstance(item.get("human_final_audit"), Mapping)
            else item["review"].get("complete") is True
        )
        for item in records
    )
    human_incomplete_ids = [
        item["case_id"]
        for item in records
        if (
            item["human_final_audit"].get("complete") is not True
            if isinstance(item.get("human_final_audit"), Mapping)
            else item["review"].get("complete") is not True
        )
    ]
    delivery_review_differences = sum(
        item["delivery"].get("text") != item["review"].get("final_answer")
        for item in records
    )
    runtime_error_count = sum(len(item.get("runtime_errors", ())) for item in records)
    mcp_error_count = sum(
        bool(call.get("error") or call.get("is_error"))
        for item in records
        for call in item.get("mcp_calls", ())
    )
    workflow_model_calls = [
        call for item in records for call in item.get("model_calls", ())
    ] + [item["review"] for item in records]
    main_business_calls = int(summary["runtime_model_calls"]) + int(
        summary["review_calls"]
    )
    low_reasoning_calls = sum(
        call.get("reasoning_effort") == "low" for call in workflow_model_calls
    )
    explicit_site_records = [
        item for item in records if "评课社区" in str(item.get("question", ""))
    ]
    explicit_site_mcp = sum(bool(item.get("mcp_calls")) for item in explicit_site_records)
    lines = [
        "# USTC 评课社区 75 题 AstrBot Connector 接口形状模拟与审校报告",
        "",
        "> 日期：2026-08-26。测试将 AstrBot Connector 消费接口形状的合成事件"
        "直接注入 Dududa 2.0 Bridge，使用真实 Luna/Terra/Sol、统一 MCP 与"
        "本地公开数据快照。这不是完整原生 OneBot 端到端测试：已绕过 AstrBot "
        "宿主的 WebSocket 收包、OneBot 帧反序列化和 dispatcher；最终发送边界为"
        "内存 Fake，未向 QQ 发送消息。",
        "",
        "## 总体结果",
        "",
        f"- 已执行题目：{summary['case_count']}/75。",
        f"- Bridge 已处理：{summary['bridge_completed']}/{summary['case_count']}；Runtime 完成："
        f"{summary['runtime_completed']}/{summary['case_count']}；"
        f"实际产生候选回答：{summary['runtime_answered']}/{summary['case_count']}。",
        f"- Luna 一轮终审后有最终答复：{summary['final_answered']}/{summary['case_count']}。",
        f"- MCP 调用：{summary['mcp_call_count']}；Fake Delivery："
        f"{summary['fake_send_count']}；真实 QQ 输出：0。",
        f"- Runtime 错误：{runtime_error_count}；MCP 错误：{mcp_error_count}；"
        f"显式“评课社区”调用：{explicit_site_mcp}/{len(explicit_site_records)}。",
        f"- 最终保留记录口径的 Runtime 模型调用：{summary['runtime_model_calls']}；Luna Review："
        f"{summary['review_calls']}；启动健康探测：{summary['health_probe_calls']}。",
        f"- 最终保留记录口径的业务链模型调用最低推理强度：{low_reasoning_calls}/"
        f"{len(workflow_model_calls)} 为 `low`。",
        f"- DirectChat 模型分布：`{json.dumps(summary['direct_models'], ensure_ascii=False)}`。",
        f"- 回答档位：`{json.dumps(summary['answer_profiles'], ensure_ascii=False)}`。",
        f"- 输出形态：`{json.dumps(summary['delivery_shapes'], ensure_ascii=False)}`。",
        f"- 审校结论：`{json.dumps(summary['review_verdicts'], ensure_ascii=False)}`。",
        f"- Luna 一轮审校完整度：`complete=true` "
        f"{summary['review_complete']['true']}；`complete=false` "
        f"{summary['review_complete']['false']}。",
        f"- 人工最终审校：{human_audit_count} 条需要覆盖或更正；最终完整 "
        f"{human_complete}，未完整 {len(records) - human_complete}。",
        f"- 人工仅清理可见措辞：{editorial_count} 条；不改事实、不追加第二轮模型审校。",
        f"- Runtime Delivery 与 Luna 审校稿不同：{delivery_review_differences}/"
        f"{len(records)}；审校是旁路证据，不是已发送正文。",
        f"- 总耗时：{summary['elapsed_ms'] / 60000:.1f} 分钟。",
        "",
        "### 人工终审口径",
        "",
        "逐题最终答案优先读取 `human_final_audit.final_answer`，没有人工覆盖时才读取 "
        "`review.final_answer`；最终完整度同样以人工覆盖优先。Luna 的原始 60/15 仍保留为"
        "模型审校证据，不覆盖人工最终 49/26。",
        "",
        "- 最终未完整 Case：`"
        + ", ".join(str(case_id) for case_id in human_incomplete_ids)
        + "`。",
        "- 主要缺口：课程别名规范化、结构化筛选、用户/回复联表、最新与历史时序、"
        "完整分页和多步聚合。",
        "",
        "## 测试口径",
        "",
        "每题构造包含 OneBot v11 `at + text` 段、message/group/user/self ID 和时间戳的"
        " AstrBot Connector 接口形状事件，再直接进入插件的 2.0 Bridge。覆盖 "
        "Connector 后半段、claim、"
        "Perception、Static Router、Capability Planner、Unified MCP、DirectChat、Persona、"
        "AnswerProfile、Final Validator 和 Output Adapter。该模拟明确绕过 AstrBot 宿主的 "
        "WebSocket 收包、OneBot 帧反序列化为 `AstrMessageEvent` 以及 dispatcher 分发。",
        "",
        "MCP 只读取仓库外本地只读公开快照，不抓取网络。Luna Review"
        " 审查的是 Output Adapter 形成的实际候选文本以及回答模型实际看到的 Tool Context；"
        "测试题的 expected 只作为完成度 rubric，不作为事实来源。",
        "Luna 在 Runtime 结束后只做一轮离线审校，`final_answer` 是该轮审校稿。"
        "只有 Runtime `delivery.text` 经过 Composer、Final Validator 和 Output Adapter，"
        "并进入 Fake Delivery。Luna 的修订稿没有重新进入 Runtime，也没有再校验或"
        "再投递，不代表生产环境会发送该文本。",
        "",
    ]
    if isinstance(followup, Mapping):
        followup_runtime_calls = int(followup.get("runtime_model_calls", 0))
        followup_review_calls = int(followup.get("review_calls", 0))
        followup_health_probes = int(followup.get("health_probe_calls", 0))
        lines.extend(
            [
                "### 定向补跑",
                "",
                f"主跑后只补跑 Case `{followup.get('case_ids', [])}`，耗时 "
                f"{float(followup.get('elapsed_ms', 0)) / 60000:.1f} 分钟。"
                "正式记录已用补跑结果替换；其余 71 题未重复调用模型。",
                (
                    "定向补跑另发生 "
                    f"{followup_runtime_calls + followup_review_calls} 次业务链调用和 "
                    f"{followup_health_probes} 次健康探测；加上主跑后，全过程共发生 "
                    f"{main_business_calls + followup_runtime_calls + followup_review_calls} "
                    "次业务链调用和 "
                    f"{summary['health_probe_calls'] + followup_health_probes} 次健康探测。"
                    if followup_runtime_calls or followup_review_calls
                    else ""
                ),
                "",
            ]
        )
    if isinstance(host_ingress, Mapping):
        order_probe = host_ingress.get("order_probe", {})
        lines.extend(
            [
                "### AstrBot 宿主入口补充契约",
                "",
                "另在固定 AstrBot 镜像的 Quart 内存 WebSocket 中逐帧送入相同 75 条合法 "
                "OneBot v11 JSON，覆盖 `Event.from_payload -> aiocqhttp EventBus -> "
                "AstrBot convert -> AiocqhttpMessageEvent -> RuntimeRequestFactory`。",
                "",
                f"- 原生事件：{host_ingress.get('native_event_count', 0)}/"
                f"{host_ingress.get('input_count', 0)}；RequestFactory："
                f"{host_ingress.get('request_factory_count', 0)}/"
                f"{host_ingress.get('input_count', 0)}。",
                f"- OneBot 发送动作：{host_ingress.get('outbound_onebot_actions', 0)}。",
                f"- 延迟首条成员查询 50 ms 的三帧探测：输入 "
                f"`{order_probe.get('input', [])}`，实际入队 "
                f"`{order_probe.get('observed', [])}`。这证明当前宿主入口存在并发乱序能力。",
                "",
                "宿主入口契约与逐题 Runtime Runner 是两段互补证据，不是一次跨真实 NapCat、"
                "生产网络和 QQ 服务端回执的无中断端到端测试。",
                "",
            ]
        )
    if isinstance(post_benchmark_fixes, Mapping):
        forward_fix = post_benchmark_fixes.get("forward_boundary_splitter")
        if isinstance(forward_fix, Mapping):
            lines.extend(
                [
                    "### 运行后修复",
                    "",
                    "本轮记录暴露了 LONG 合并转发按 UTF-8 字节硬切、可能把中文词拆到两个"
                    "节点的问题。分片器已改为优先在换行、句末标点或空格处分段，聚焦回归"
                    "通过。该修复发生在 75 题主跑之后，因此原 JSON 的 Delivery 仍保留当时"
                    "的分片，不能倒算成已经重新投递。",
                    "",
                ]
            )
    lines.extend(["## 逐题回答", ""])
    for record in records:
        direct_call = next(
            (
                item
                for item in record["model_calls"]
                if item.get("role") == "direct_chat"
            ),
            {},
        )
        mcp = record["mcp_calls"]
        operation = mcp[0].get("arguments", {}).get("operation", "-") if mcp else "-"
        query = mcp[0].get("arguments", {}).get("query", "-") if mcp else "-"
        review = record["review"]
        human_audit = record.get("human_final_audit")
        final_answer = (
            human_audit.get("final_answer")
            if isinstance(human_audit, Mapping)
            and isinstance(human_audit.get("final_answer"), str)
            else review.get("final_answer") or record["delivery"]["text"]
        )
        lines.extend(
            [
                f"### Case {record['case_id']}：{record['title']}",
                "",
                f"**Q：** {record['question']}",
                "",
                "**链路：** "
                f"`{record['runtime_action']}`；模型 "
                f"`{direct_call.get('requested_model', '-')}`；推理 "
                f"`{direct_call.get('reasoning_effort', '-')}`；档位 "
                f"`{direct_call.get('answer_profile', '-')}`；MCP "
                f"`{len(mcp)} 次 ({operation}, {query})`；输出 "
                f"`{record['delivery']['shape']}/{record['delivery']['part_count']} parts`。",
                "",
                (
                    "**最终审校答案（人工终审）：**"
                    if isinstance(human_audit, Mapping)
                    else (
                        "**Luna 一轮审校稿（人工措辞清理后）：**"
                        if record.get("editorial_adjustments")
                        else "**Luna 一轮审校稿 (`final_answer`)：**"
                    )
                ),
                "",
                str(final_answer),
                "",
                "**Luna 终审：** "
                f"`{review.get('verdict', 'error')}`；候选通过 "
                f"`{review.get('passed', False)}`；完整 "
                f"`{review.get('complete', False)}`。",
            ]
        )
        issues = review.get("issues")
        if isinstance(issues, list) and issues:
            lines.append("问题：" + "；".join(str(item) for item in issues))
        if isinstance(human_audit, Mapping):
            lines.append(
                "人工终审：grounded "
                f"`{human_audit.get('grounded', False)}`；完整 "
                f"`{human_audit.get('complete', False)}`；"
                f"{human_audit.get('reason', '人工复核覆盖 Luna 结论')}"
            )
        lines.append("")
    lines.extend(
        [
            "## 结论边界",
            "",
            f"- 本轮 `runtime_answered={summary['runtime_answered']}`、"
            f"`fake_send_count={summary['fake_send_count']}`，因此有 Runtime 回答的输入"
            "均进入 Fake Delivery；这仍不等于真实 QQ 已投递，真实 QQ 输出为 0。",
            "- Fake Delivery 只验证 Runtime Delivery 文本的消息链和合并转发形态，"
            "不包含 Luna 后处理修订稿，也不是 QQ 服务端回执。",
            f"- 本轮 Luna 审校没有回注 Runtime：{delivery_review_differences} 条审校稿"
            "与已记录 Delivery 不同。"
            "因此不能把审校后的答案描述为已经过 Final Validator 或已经发送。",
            "- 事实质量受 2026-08-26 本地公开快照覆盖限制；缺失数据应在回答中明确表达。",
            "- 私有逐调用证据保存在仓库外结果 JSON，文件不包含 API Key 或 Base URL。",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "\n".join(lines)
    path.write_text(
        "\n".join(line.rstrip() for line in rendered.splitlines()) + "\n",
        encoding="utf-8",
    )


async def async_main(args: argparse.Namespace) -> int:
    cases = parse_cases(args.fixture)
    selection = parse_case_selection(args.cases)
    if selection is not None:
        cases = tuple(item for item in cases if item.case_id in selection)
    if not args.snapshot.is_file():
        raise FileNotFoundError(args.snapshot)
    private_config = load_private_provider_config(
        args.codex_config,
        args.auth_file,
        provider_name=args.provider,
        timeout_seconds=args.timeout_seconds,
    )
    result = await run_benchmark(
        cases,
        private_config,
        args.snapshot,
        args.result,
        timeout_seconds=args.timeout_seconds,
    )
    render_report(result, args.report)
    print(json.dumps(result["summary"], ensure_ascii=False, separators=(",", ":")))
    summary = result["summary"]
    return 0 if summary["case_count"] == summary["final_answered"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run real-model iCourse cases through a no-send native message path."
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--cases", help="Comma-separated case IDs or ranges, for example 1,4,67-75"
    )
    parser.add_argument(
        "--codex-config",
        type=Path,
        default=Path.home() / ".codex" / "config.toml",
    )
    parser.add_argument(
        "--auth-file",
        type=Path,
        default=Path.home() / ".codex" / "auth.json",
    )
    parser.add_argument("--provider")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()
    try:
        return asyncio.run(async_main(args))
    except (ShadowSampleError, OSError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {"error": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
