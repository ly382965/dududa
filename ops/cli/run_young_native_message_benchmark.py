"""Run 75 Young cases through the Dududa 2.0 native-message path.

The runner uses a fixed local MCP fixture, scripted model semantics and an
in-memory Output Adapter. It never reads a real account or sends a QQ message.
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

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SOURCE_ROOT = ROOT / "apps" / "astrbot-plugins"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PLUGIN_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SOURCE_ROOT))

from astrbot_plugin_dududa_core import composition
from astrbot_plugin_dududa_core.adapters.mcp_schema import JsonSchemaMcpValidator
from astrbot_plugin_dududa_core.adapters.output import AstrBotOutputAdapter
from astrbot_plugin_dududa_core.rollout_bridge import AstrBotBridgeAction
from dududa.mcp import ManagedUnifiedMcpClient

from tests.contracts.test_mcp_capability_provider import RecordingUnifiedClient
from tests.contracts.test_production_composition import (
    ProductionCompositionContractTests,
    _assert_young_answer_semantics,
    _ComponentFactory,
    _ICourseFacade,
    _young_native_cases,
    _YoungBenchmarkAstrBotProvider,
    _YoungNativeEvent,
)
from tests.contracts.test_unified_mcp_worker import (
    _StaticRegistry,
    factory,
    young_fixture_definition,
)

DEFAULT_JSON = Path(
    "/home/mmdustc/temp/dududa-young-75-native-message-2026-08-29.json"
)
DEFAULT_REPORT = ROOT / "docs" / "refactor" / (
    "young-75-native-message-validation-2026-08-29.md"
)
FIXED_NOW = datetime(2026, 8, 29, 1, 30, tzinfo=timezone.utc)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


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
                for node in component[1]:
                    if isinstance(node, tuple) and node and node[0] == "node":
                        texts.append(str(node[1]))
                        parts += 1
    return "".join(texts).strip(), shape, parts


async def run() -> dict[str, object]:
    test = ProductionCompositionContractTests(
        "test_all_young_native_messages_use_only_the_2_0_runtime"
    )
    test.setUp()
    plugin = None
    cases = _young_native_cases()
    provider = _YoungBenchmarkAstrBotProvider(cases)
    recording_mcp = RecordingUnifiedClient(
        ManagedUnifiedMcpClient(
            _StaticRegistry(young_fixture_definition()),
            factory(),
            JsonSchemaMcpValidator(),
            wall_clock=lambda: FIXED_NOW,
        )
    )
    try:
        plugin = test._production_plugin(provider)
        plugin.icourse = _ICourseFacade(recording_mcp)
        plugin.unified_mcp_client = recording_mcp
        values = test._runtime_config(rollout_mode="canary")
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
            clock=lambda: FIXED_NOW,
        )
        test._initialize(
            plugin,
            values,
            "young-native-report",
            runtime_assembly=assembly,
        )
        plugin.rollout_bridge._output_factory = (
            lambda event, ledger, guard: AstrBotOutputAdapter(
                event,
                ledger,
                component_factory=_ComponentFactory(),
                send_guard=guard,
                clock=lambda: FIXED_NOW,
            )
        )
        await assembly.publish_model_health(
            (
                test._healthy_evidence(
                    assembly,
                    FIXED_NOW,
                    ttl=timedelta(minutes=10),
                ),
            ),
            call=replace(
                test.call,
                deadline=FIXED_NOW + timedelta(minutes=1),
            ),
        )
        results: list[dict[str, object]] = []
        for case in cases:
            before = len(recording_mcp.tool_calls)
            event = _YoungNativeEvent(case)
            bridge = await plugin.rollout_bridge.handle(event)
            calls = recording_mcp.tool_calls[before:]
            answer, shape, parts = _delivery(event.sent_chains)
            _assert_young_answer_semantics(int(case["case_id"]), answer)
            results.append(
                {
                    **case,
                    "bridge_action": bridge.action.value,
                    "runtime_completed": (
                        bridge.action is AstrBotBridgeAction.CANARY_COMPLETED
                    ),
                    "event_stopped": event.stop_calls,
                    "fake_delivery_calls": event.send_calls,
                    "delivery_shape": shape,
                    "delivery_parts": parts,
                    "answer": answer,
                    "mcp_calls": [
                        {
                            "server_id": server_id,
                            "tool_name": tool_name,
                            "arguments": _plain(arguments),
                        }
                        for server_id, tool_name, arguments, _call in calls
                    ],
                }
            )
        summary = {
            "cases": len(results),
            "runtime_completed": sum(
                bool(item["runtime_completed"]) for item in results
            ),
            "fake_deliveries": sum(
                int(item["fake_delivery_calls"]) for item in results
            ),
            "mcp_calls": len(recording_mcp.tool_calls),
            "model_calls": len(provider.calls),
            "real_qq_sends": 0,
            "tool_counts": dict(
                sorted(
                    Counter(
                        tool_name
                        for _server_id, tool_name, _arguments, _call in (
                            recording_mcp.tool_calls
                        )
                    ).items()
                )
            ),
            "category_counts": dict(
                sorted(Counter(str(item["category"]) for item in results).items())
            ),
            "semantic_status_counts": dict(
                sorted(
                    Counter(
                        str(item["semantic_status"]) for item in results
                    ).items()
                )
            ),
        }
        if summary != {
            **summary,
            "cases": 75,
            "runtime_completed": 75,
            "fake_deliveries": 75,
            "mcp_calls": 62,
            "model_calls": 150,
            "real_qq_sends": 0,
        }:
            raise RuntimeError(f"Young benchmark incomplete: {summary}")
        return {
            "schema_version": 1,
            "runtime": "dududa-2.0",
            "fixture_time": FIXED_NOW.isoformat(),
            "model_mode": "scripted_perception_and_summary",
            "source_mode": "fixed_local_young_mcp_fixture",
            "output_mode": "in_memory_fake_delivery",
            "summary": summary,
            "results": results,
        }
    finally:
        if plugin is not None:
            await plugin.terminate()
        else:
            await recording_mcp.close()
        test.tearDown()


def report(document: dict[str, object]) -> str:
    summary = document["summary"]
    results = document["results"]
    lines = [
        "# USTC 第二课堂 75 题 Dududa 2.0 原生消息模拟报告",
        "",
        "> 记录日期：2026-08-29。该报告使用固定本地 Young MCP fixture、脚本化模型语义和",
        "> 内存 Fake Delivery；事件由测试代码手工构造为 OneBot-shaped Event，不经过 NapCat、",
        "> AstrBot Filter 调度或真实 QQ 回执，不访问真实二课账号，也不经过 Dududa 1.0。",
        "",
        "## 结论",
        "",
        f"- OneBot-shaped 原生消息：{summary['cases']}/75。",
        f"- 2.0 Runtime 完成：{summary['runtime_completed']}/75。",
        f"- Fake Delivery：{summary['fake_deliveries']}/75；真实 QQ 发送：0。",
        f"- Unified MCP 调用：{summary['mcp_calls']}；不调用边界：13。",
        f"- 模型调用：{summary['model_calls']}（75 次 Perception + 75 次 Direct Chat，均为脚本 Fake）。",
        "- 唯一链路：手工 OneBot-shaped Event -> Dududa 2.0 Rollout Bridge -> Connector -> Hybrid Perception -> Planner -> Capability Runtime -> Unified MCP -> Young MCP -> Observation -> DirectChat -> Composer -> Persona/Final Validator -> Fake Delivery。",
        "- 禁止面：`young_list_my_activities`、报名、取消、申请人、Web search、ReplyPolish 和旧命令路由均未执行。",
        "- 个人请求负例：Case 70 中脚本模型故意提出 Young 公共搜索，确定性资格过滤将其移除，最终 MCP 调用为 0。",
        "",
        "## 证据边界",
        "",
        "这份结果证明路由、参数投影、MCP 契约、结构化 Observation、最终输出和正确不调用。",
        "聚焦语义断言覆盖日期、报名窗口、余位阈值、填充率排序、容量、学时效率、五育覆盖和",
        "规模比较，不只检查有无回复。脚本 Fake 不能证明真实 Luna/Terra/Sol 的中文理解和总结质量；",
        "另行执行的 Luna Review 只是旁路审校证据，不是 Runtime 已发送的回复。上下文追问也准确暴露了",
        "当前 Production Context 只含本轮消息的限制，没有伪造前序对话。",
        "",
        "## 逐题结果",
        "",
    ]
    for item in results:
        calls = item["mcp_calls"]
        call_text = "不调用"
        if calls:
            call = calls[0]
            call_text = (
                f"`{call['server_id']}/{call['tool_name']}` "
                f"`{json.dumps(call['arguments'], ensure_ascii=False, sort_keys=True)}`"
            )
        lines.extend(
            [
                f"### Case {item['case_id']}：{item['category']}",
                "",
                f"**Q：** {item['question']}",
                "",
                f"**2.0 调用：** {call_text}",
                "",
                f"**完成类型：** `{item['semantic_status']}`；输出 `{item['delivery_shape']}` / {item['delivery_parts']} part。",
                "",
                f"**实际 Fake Delivery：** {item['answer']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    document = asyncio.run(run())
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(args.json_output, 0o600)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(report(document), encoding="utf-8")
    print(json.dumps(document["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
