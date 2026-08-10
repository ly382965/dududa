# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "mcp==2.0.0",
# ]
# ///

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

import anyio
from mcp import Client, StdioServerParameters, stdio_client, types
from mcp.server import Server
from mcp.server.stdio import stdio_server


SPIKE_ID = "s12a-mcp-v2-spike-v1"
NATIVE_PROTOCOL = "2026-07-28"
LEGACY_PROTOCOL = "2025-11-25"
DEADLINE_SECONDS = 0.15
DEADLINE_RETURN_BOUND_SECONDS = 3.0
CLOSE_TIMEOUT_SECONDS = 2.0
_ERRLOG = sys.stderr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the isolated Dududa MCP v2 Spike."
    )
    parser.add_argument("--legacy-python")
    parser.add_argument("--write-report")
    parser.add_argument("--check-report")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--journal")
    parser.add_argument("--effect-journal")
    parser.add_argument(
        "--schema-revision",
        choices=("v1", "compatible", "incompatible"),
        default="v1",
    )
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--startup-delay-ms", type=int, default=0)
    parser.add_argument("--discovery-delay-ms", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.serve:
        if not args.journal or not args.effect_journal:
            raise SystemExit("--serve requires --journal and --effect-journal")
        anyio.run(serve_fake, args)
        return
    if not args.legacy_python:
        raise SystemExit("--legacy-python is required")
    report = anyio.run(run_spike, args)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.write_report:
        Path(args.write_report).write_text(rendered, encoding="utf-8")
    if args.check_report:
        expected = Path(args.check_report).read_text(encoding="utf-8")
        if expected != rendered:
            raise SystemExit("committed MCP v2 Spike report is stale")
    if not args.write_report and not args.check_report:
        sys.stdout.write(rendered)


async def serve_fake(args: argparse.Namespace) -> None:
    journal = Path(args.journal)
    effect_journal = Path(args.effect_journal)
    _append_event(
        journal,
        {
            "event": "process_started",
            "pid": os.getpid(),
            "generation": args.generation,
            "schema_revision": args.schema_revision,
        },
    )
    if args.startup_delay_ms:
        await anyio.sleep(args.startup_delay_ms / 1000)

    active = 0

    async def list_tools(
        _context: object,
        _params: object,
    ) -> types.ListToolsResult:
        _append_event(
            journal,
            {
                "event": "tools_listed",
                "generation": args.generation,
                "schema_revision": args.schema_revision,
            },
        )
        if args.discovery_delay_ms:
            await anyio.sleep(args.discovery_delay_ms / 1000)
        tools = [_probe_tool(args.schema_revision)]
        if args.schema_revision != "v1":
            tools.append(
                types.Tool(
                    name="newly_discovered",
                    description="Unmapped discovery fact used by the Spike.",
                    inputSchema={"type": "object", "additionalProperties": False},
                )
            )
        return types.ListToolsResult(tools=tools)

    async def call_tool(
        _context: object,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        nonlocal active
        if params.name != "probe":
            return _tool_result({"ok": False, "error": "unknown_tool"}, is_error=True)
        arguments = params.arguments or {}
        operation = arguments.get("operation", "read")
        phase = arguments.get("phase", "contract")
        request_id = arguments.get("request_id", "unspecified")
        delay_ms = arguments.get("delay_ms", 0)
        if type(delay_ms) is not int or delay_ms < 0 or delay_ms > 10_000:
            return _tool_result({"ok": False, "error": "invalid_delay"}, is_error=True)

        active += 1
        _append_event(
            journal,
            {
                "event": "call_started",
                "generation": args.generation,
                "operation": operation,
                "phase": phase,
                "request_id": request_id,
                "active": active,
            },
        )
        if operation == "crash_before_effect":
            _append_event(journal, {"event": "crash_before_effect"})
            os._exit(71)
        if operation == "crash_after_effect":
            _append_event(effect_journal, {"event": "effect_committed"})
            _append_event(journal, {"event": "crash_after_effect"})
            os._exit(72)

        try:
            if delay_ms:
                await anyio.sleep(delay_ms / 1000)
            return _tool_result(
                {
                    "ok": True,
                    "generation": args.generation,
                    "schema_revision": args.schema_revision,
                    "value": arguments.get("value"),
                    "request_id": request_id,
                }
            )
        finally:
            active -= 1
            _append_event(
                journal,
                {
                    "event": "call_finished",
                    "generation": args.generation,
                    "operation": operation,
                    "phase": phase,
                    "request_id": request_id,
                    "active": active,
                },
            )

    server: Server[Any] = Server(
        "dududa-mcp-v2-spike",
        version="1.0.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def _probe_tool(schema_revision: str) -> types.Tool:
    value_schema: dict[str, object]
    if schema_revision != "incompatible":
        value_schema = {"type": "string"}
    else:
        value_schema = {"type": "integer"}
    return types.Tool(
        name="probe",
        description="Deterministic local lifecycle probe.",
        inputSchema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "value": value_schema,
                "delay_ms": {"type": "integer", "minimum": 0, "maximum": 10_000},
                "operation": {
                    "enum": ["read", "crash_before_effect", "crash_after_effect"]
                },
                "phase": {"type": "string"},
                "request_id": {"type": "string"},
            },
        },
        outputSchema={
            "type": "object",
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
        },
    )


def _tool_result(
    value: dict[str, object], *, is_error: bool = False
) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(text=json.dumps(value, sort_keys=True))],
        structuredContent=value,
        isError=is_error,
    )


async def run_spike(args: argparse.Namespace) -> dict[str, object]:
    root = Path(__file__).resolve().parents[2]
    # Preserve a virtualenv launcher symlink: resolving it selects the base uv
    # interpreter and drops the legacy environment's installed MCP v1 SDK.
    legacy_python = Path(args.legacy_python).expanduser().absolute()
    if not legacy_python.is_file():
        raise RuntimeError("legacy Python does not exist")

    suite_fds_before = _fd_count()
    suite_tasks_before = _owned_task_count()
    with tempfile.TemporaryDirectory(prefix="dududa-mcp-v2-spike-") as temporary:
        work = Path(temporary)
        native = await probe_native_lifecycle(work)
        legacy = await probe_legacy_icourse(root, legacy_python, work)
        deadlines = await probe_deadlines(work)
        cancellation = await probe_cancellation(work)
        crash = await probe_crash_and_recovery(work)
        schema = await probe_schema_drift(work)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        suite_resource_cleanup = (
            _owned_task_count() <= suite_tasks_before
            and _fd_count() <= suite_fds_before + 2
        )

    hard_gates = {
        "native_v2_contract": native["contract_passed"],
        "legacy_v1_contract": legacy["contract_passed"],
        "legacy_fixture_isolated": legacy["network_attempts"] == 0
        and legacy["off_policy_database_opens"] == 0
        and legacy["allowed_database_opens"] > 0,
        "single_long_lived_session": native["process_starts"] == 1
        and native["tools_listed"] == 1
        and native["sequential_started"] == 100
        and native["sequential_finished"] == 100
        and native["sequential_unique"] == 100,
        "bounded_concurrency": 1 < native["max_active_calls"] <= 4
        and native["concurrent_started"] == 20
        and native["concurrent_finished"] == 20
        and native["concurrent_unique"] == 20
        and native["active_returned_to_zero"],
        "bounded_deadlines": all(evidence["passed"] for evidence in deadlines.values()),
        "cancellation_cleanup": cancellation["passed"],
        "crash_phases_classified": crash["before_error_observed"]
        and crash["before_call_attempts"] == 1
        and crash["before_crash_events"] == 1
        and crash["before_effect_count"] == 0
        and crash["after_error_observed"]
        and crash["after_call_attempts"] == 1
        and crash["after_crash_events"] == 1
        and crash["after_effect_count"] == 1,
        "crash_generation_recovery": crash["before_recovered"]
        and crash["after_recovered"]
        and crash["before_generation_count"] == 2
        and crash["after_generation_count"] == 2,
        "unknown_outcome_not_retried": crash["after_effect_count"] == 1
        and crash["after_call_attempts"] == 1,
        "schema_drift_not_published": schema["drift_rejected"]
        and schema["expired_rejected"]
        and schema["compatible_published"]
        and schema["last_known_good_unchanged"],
        "discovery_grants_no_capability": schema["new_tool_observed"]
        and schema["capability_grants_before"] == 0
        and schema["capability_grants_after"] == 0,
        "resource_close": suite_resource_cleanup
        and native["resource_closed"]
        and legacy["resource_closed"]
        and all(evidence["resource_closed"] for evidence in deadlines.values())
        and cancellation["resource_closed"]
        and crash["resource_closed"]
        and schema["resource_closed"],
    }
    payload: dict[str, object] = {
        "schema_version": 1,
        "spike_id": SPIKE_ID,
        "decision": "adopt" if all(hard_gates.values()) else "reject",
        "sdk": {
            "client": f"mcp=={version('mcp')}",
            "types": f"mcp-types=={version('mcp-types')}",
            "native_protocol": native["protocol"],
            "legacy_protocol": legacy["protocol"],
        },
        "fixtures": {
            "native": "local_v2_fake",
            "legacy": "current_icourse_v1_empty_db",
            "network_attempts": legacy["network_attempts"],
            "off_policy_database_opens": legacy["off_policy_database_opens"],
            "capability_grants": schema["capability_grants_after"],
        },
        "metrics": {
            "native_process_starts": native["process_starts"],
            "native_tools_listed": native["tools_listed"],
            "sequential_calls": native["sequential_finished"],
            "concurrent_calls": native["concurrent_finished"],
            "max_active_calls": native["max_active_calls"],
            "legacy_process_starts": legacy["process_starts"],
            "legacy_tool_count": legacy["tool_count"],
            "before_effect_call_attempts": crash["before_call_attempts"],
            "before_effect_count": crash["before_effect_count"],
            "unknown_call_attempts": crash["after_call_attempts"],
            "unknown_effect_count": crash["after_effect_count"],
            "generation_count": crash["after_generation_count"],
        },
        "classifications": {
            "deadlines": sorted(
                str(evidence["reason_code"]) for evidence in deadlines.values()
            ),
            "crash_before_effect": "safe_retry_eligible",
            "crash_after_effect": "outcome_unknown",
            "schema_drift": schema["drift_reason_code"],
            "schema_expiry": schema["expiry_reason_code"],
        },
        "deadline_evidence": {
            name: {
                "timed_out": evidence["timed_out"],
                "elapsed_bounded": evidence["elapsed_bounded"],
                "close_bounded": evidence["close_bounded"],
                "child_closed": evidence["child_closed"],
            }
            for name, evidence in sorted(deadlines.items())
        },
        "hard_gates": hard_gates,
        "schema": schema,
        "external_gates": [
            "production_unified_client_and_registry",
            "icourse_v2_server_migration",
            "real_provider_credentials",
            "live_mcp_sources",
            "authorized_qq_validation",
        ],
    }
    payload["report_digest"] = _digest(payload)
    return payload


async def probe_native_lifecycle(work: Path) -> dict[str, object]:
    journal = work / "native.jsonl"
    effects = work / "native-effects.jsonl"
    client = _native_client(journal, effects, generation=1)

    async def exercise(entered_client: Client) -> bool:
        contract = await entered_client.call_tool(
            "probe",
            {
                "value": "contract",
                "phase": "contract",
                "request_id": "native-contract",
            },
        )
        if (
            contract.is_error
            or contract.structured_content.get("value") != "contract"
            or contract.structured_content.get("request_id") != "native-contract"
        ):
            return False
        for index in range(100):
            request_id = f"sequential-{index}"
            result = await entered_client.call_tool(
                "probe",
                {
                    "value": str(index),
                    "phase": "sequential",
                    "request_id": request_id,
                },
            )
            if (
                result.is_error
                or result.structured_content.get("value") != str(index)
                or result.structured_content.get("request_id") != request_id
            ):
                raise RuntimeError("native sequential call contract failed")

        semaphore = asyncio.Semaphore(4)

        async def invoke(index: int) -> None:
            async with semaphore:
                request_id = f"concurrent-{index}"
                result = await entered_client.call_tool(
                    "probe",
                    {
                        "value": str(index),
                        "delay_ms": 25,
                        "phase": "concurrent",
                        "request_id": request_id,
                    },
                )
                if (
                    result.is_error
                    or result.structured_content.get("value") != str(index)
                    or result.structured_content.get("request_id") != request_id
                ):
                    raise RuntimeError("native concurrent call failed")

        await asyncio.gather(*(invoke(index) for index in range(20)))
        return True

    contract = await _run_shared_contract(
        client,
        journal=journal,
        expected_protocol=NATIVE_PROTOCOL,
        expected_tools=frozenset({"probe"}),
        exercise=exercise,
    )
    events = _events(journal)
    sequential_started = _phase_request_ids(events, "call_started", "sequential")
    sequential_finished = _phase_request_ids(events, "call_finished", "sequential")
    concurrent_started = _phase_request_ids(events, "call_started", "concurrent")
    concurrent_finished = _phase_request_ids(events, "call_finished", "concurrent")
    finished = [event for event in events if event.get("event") == "call_finished"]
    return {
        "contract_passed": contract["passed"],
        "protocol": contract["protocol"],
        "process_starts": contract["process_starts"],
        "tools_listed": _event_count(events, "tools_listed"),
        "sequential_started": len(sequential_started),
        "sequential_finished": len(sequential_finished),
        "sequential_unique": len(set(sequential_started) & set(sequential_finished)),
        "concurrent_started": len(concurrent_started),
        "concurrent_finished": len(concurrent_finished),
        "concurrent_unique": len(set(concurrent_started) & set(concurrent_finished)),
        "max_active_calls": max(
            int(event["active"])
            for event in events
            if event.get("event") == "call_started"
        ),
        "active_returned_to_zero": bool(finished) and int(finished[-1]["active"]) == 0,
        "resource_closed": contract["resource_closed"],
    }


async def probe_legacy_icourse(
    root: Path,
    legacy_python: Path,
    work: Path,
) -> dict[str, object]:
    journal = work / "legacy.jsonl"
    audit_journal = work / "legacy-audit.jsonl"
    database = work / "icourse.sqlite3"
    wrapper = root / "spikes" / "mcp-v2" / "process_wrapper.py"
    server = root / "services" / "mcp" / "icourse" / "run_icourse_mcp.py"
    params = StdioServerParameters(
        command=str(legacy_python),
        args=[
            str(wrapper),
            "--journal",
            str(journal),
            "--",
            str(legacy_python),
            str(server),
            "--db-path",
            str(database),
            "--request-delay",
            "0",
        ],
        cwd=str(root / "services" / "mcp" / "icourse"),
        env={
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(root / "spikes" / "mcp-v2" / "guard"),
            "DUDUDA_SPIKE_AUDIT_JOURNAL": str(audit_journal),
            "DUDUDA_SPIKE_ALLOWED_DB": str(database),
        },
    )
    client = Client(
        stdio_client(params, errlog=_ERRLOG),
        mode="legacy",
        read_timeout_seconds=5,
        cache=None,
    )
    expected = {
        "icourse_stats",
        "search_courses",
        "get_course",
        "get_reviews",
        "crawl_course",
        "crawl_courses",
        "search_site_courses",
        "crawl_latest_reviews",
        "check_robots",
        "export_dataset",
    }

    async def exercise(entered_client: Client) -> bool:
        stats = await entered_client.call_tool("icourse_stats", {})
        search = await entered_client.call_tool("search_courses", {"query": "fixture"})
        return (
            not stats.is_error
            and stats.structured_content.get("courses") == 0
            and not search.is_error
            and search.structured_content.get("items") == []
        )

    contract = await _run_shared_contract(
        client,
        journal=journal,
        expected_protocol=LEGACY_PROTOCOL,
        expected_tools=frozenset(expected),
        exercise=exercise,
    )
    audit_events = _events(audit_journal)
    return {
        "contract_passed": contract["passed"],
        "protocol": contract["protocol"],
        "process_starts": contract["process_starts"],
        "tool_count": contract["tool_count"],
        "network_attempts": _event_count(audit_events, "network_attempt"),
        "allowed_database_opens": _event_count(audit_events, "database_open"),
        "off_policy_database_opens": _event_count(audit_events, "database_denied"),
        "resource_closed": contract["resource_closed"],
    }


async def _run_shared_contract(
    client: Client,
    *,
    journal: Path,
    expected_protocol: str,
    expected_tools: frozenset[str],
    exercise: Callable[[Client], Awaitable[bool]],
) -> dict[str, object]:
    entered = False
    protocol = ""
    tool_names: frozenset[str] = frozenset()
    call_passed = False
    try:
        await asyncio.wait_for(client.__aenter__(), timeout=5)
        entered = True
        protocol = client.protocol_version
        tools = await asyncio.wait_for(
            client.list_tools(cache_mode="bypass"), timeout=5
        )
        tool_names = frozenset(tool.name for tool in tools.tools)
        call_passed = await exercise(client)
    finally:
        close_bounded = await _close_bounded(client) if entered else False
    events = _events(journal)
    pids = _event_values(events, "process_started", "pid")
    child_closed = len(pids) == 1 and await _all_dead(pids)
    return {
        "passed": protocol == expected_protocol
        and tool_names == expected_tools
        and call_passed
        and close_bounded
        and child_closed,
        "protocol": protocol,
        "tool_count": len(tool_names),
        "process_starts": len(pids),
        "resource_closed": close_bounded and child_closed,
    }


async def probe_deadlines(work: Path) -> dict[str, dict[str, object]]:
    return {
        "handshake_timeout": await _handshake_timeout(work),
        "discovery_timeout": await _discovery_timeout(work),
        "call_timeout": await _call_timeout(work),
    }


async def _handshake_timeout(work: Path) -> dict[str, object]:
    journal = work / "timeout-handshake.jsonl"
    effects = work / "timeout-handshake-effects.jsonl"
    client = _native_client(journal, effects, startup_delay_ms=800)
    timed_out = False
    started = time.monotonic()
    try:
        await asyncio.wait_for(client.__aenter__(), timeout=DEADLINE_SECONDS)
    except asyncio.TimeoutError:
        timed_out = True
    finally:
        close_bounded = await _close_bounded(client)
    elapsed_bounded = time.monotonic() - started < DEADLINE_RETURN_BOUND_SECONDS
    pids = _event_values(_events(journal), "process_started", "pid")
    child_closed = len(pids) == 1 and await _all_dead(pids)
    passed = timed_out and elapsed_bounded and close_bounded and child_closed
    return {
        "passed": passed,
        "reason_code": "connect_timeout" if passed else "deadline_gate_failed",
        "resource_closed": close_bounded and child_closed,
        "timed_out": timed_out,
        "elapsed_bounded": elapsed_bounded,
        "close_bounded": close_bounded,
        "child_closed": child_closed,
    }


async def _discovery_timeout(work: Path) -> dict[str, object]:
    journal = work / "timeout-discovery.jsonl"
    effects = work / "timeout-discovery-effects.jsonl"
    client = _native_client(journal, effects, discovery_delay_ms=800)
    timed_out = False
    await asyncio.wait_for(client.__aenter__(), timeout=5)
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            client.list_tools(cache_mode="bypass"), timeout=DEADLINE_SECONDS
        )
    except asyncio.TimeoutError:
        timed_out = True
    finally:
        close_bounded = await _close_bounded(client)
    elapsed_bounded = time.monotonic() - started < DEADLINE_RETURN_BOUND_SECONDS
    pids = _event_values(_events(journal), "process_started", "pid")
    child_closed = len(pids) == 1 and await _all_dead(pids)
    passed = timed_out and elapsed_bounded and close_bounded and child_closed
    return {
        "passed": passed,
        "reason_code": "discovery_timeout" if passed else "deadline_gate_failed",
        "resource_closed": close_bounded and child_closed,
        "timed_out": timed_out,
        "elapsed_bounded": elapsed_bounded,
        "close_bounded": close_bounded,
        "child_closed": child_closed,
    }


async def _call_timeout(work: Path) -> dict[str, object]:
    journal = work / "timeout-call.jsonl"
    effects = work / "timeout-call-effects.jsonl"
    client = _native_client(journal, effects)
    timed_out = False
    await asyncio.wait_for(client.__aenter__(), timeout=5)
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            client.call_tool("probe", {"value": "slow", "delay_ms": 800}),
            timeout=DEADLINE_SECONDS,
        )
    except asyncio.TimeoutError:
        timed_out = True
    finally:
        close_bounded = await _close_bounded(client)
    elapsed_bounded = time.monotonic() - started < DEADLINE_RETURN_BOUND_SECONDS
    pids = _event_values(_events(journal), "process_started", "pid")
    child_closed = len(pids) == 1 and await _all_dead(pids)
    passed = timed_out and elapsed_bounded and close_bounded and child_closed
    return {
        "passed": passed,
        "reason_code": "tool_call_timeout" if passed else "deadline_gate_failed",
        "resource_closed": close_bounded and child_closed,
        "timed_out": timed_out,
        "elapsed_bounded": elapsed_bounded,
        "close_bounded": close_bounded,
        "child_closed": child_closed,
    }


async def probe_cancellation(work: Path) -> dict[str, object]:
    journal = work / "cancel.jsonl"
    effects = work / "cancel-effects.jsonl"
    before_fds = _fd_count()
    before_tasks = _owned_task_count()
    client = _native_client(journal, effects)
    await asyncio.wait_for(client.__aenter__(), timeout=5)
    task = asyncio.create_task(
        client.call_tool(
            "probe",
            {
                "value": "cancel",
                "delay_ms": 5_000,
                "phase": "cancellation",
                "request_id": "cancel-0",
            },
        )
    )
    await _wait_for_event(journal, "call_started")
    started = time.monotonic()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    cancel_seconds = time.monotonic() - started
    close_bounded = await _close_bounded(client)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    events = _events(journal)
    pids = _event_values(events, "process_started", "pid")
    after_fds = _fd_count()
    after_tasks = _owned_task_count()
    child_closed = len(pids) == 1 and await _all_dead(pids)
    return {
        "passed": cancel_seconds < 1.0
        and after_tasks <= before_tasks
        and after_fds <= before_fds + 2
        and close_bounded
        and child_closed,
        "resource_closed": close_bounded and child_closed,
    }


async def probe_crash_and_recovery(work: Path) -> dict[str, object]:
    before_journal = work / "crash-before.jsonl"
    before_effects = work / "crash-before-effects.jsonl"
    before = await _invoke_crash(
        before_journal,
        before_effects,
        "crash_before_effect",
    )
    before_recovered = await _recover_generation(
        before_journal,
        before_effects,
        generation=2,
    )

    after_journal = work / "crash-after.jsonl"
    after_effects = work / "crash-after-effects.jsonl"
    after = await _invoke_crash(
        after_journal,
        after_effects,
        "crash_after_effect",
        generation=1,
    )
    after_recovered = await _recover_generation(
        after_journal,
        after_effects,
        generation=2,
    )

    before_events = _events(before_journal)
    after_events = _events(after_journal)
    before_pids = _event_values(before_events, "process_started", "pid")
    after_pids = _event_values(after_events, "process_started", "pid")
    return {
        "before_error_observed": before["error_observed"],
        "before_effect_count": _event_count(
            _events(before_effects), "effect_committed"
        ),
        "before_call_attempts": sum(
            1
            for event in before_events
            if event.get("event") == "call_started"
            and event.get("operation") == "crash_before_effect"
        ),
        "before_crash_events": _event_count(before_events, "crash_before_effect"),
        "before_generation_count": len(
            {
                event.get("generation")
                for event in before_events
                if event.get("event") == "process_started"
            }
        ),
        "before_recovered": before_recovered["recovered"],
        "after_error_observed": after["error_observed"],
        "after_effect_count": _event_count(_events(after_effects), "effect_committed"),
        "after_call_attempts": sum(
            1
            for event in after_events
            if event.get("event") == "call_started"
            and event.get("operation") == "crash_after_effect"
        ),
        "after_crash_events": _event_count(after_events, "crash_after_effect"),
        "after_generation_count": len(
            {
                event.get("generation")
                for event in after_events
                if event.get("event") == "process_started"
            }
        ),
        "after_recovered": after_recovered["recovered"],
        "resource_closed": before["resource_closed"]
        and before_recovered["resource_closed"]
        and after["resource_closed"]
        and after_recovered["resource_closed"]
        and len(before_pids) == 2
        and len(after_pids) == 2
        and await _all_dead(before_pids)
        and await _all_dead(after_pids),
    }


async def _invoke_crash(
    journal: Path,
    effects: Path,
    operation: str,
    *,
    generation: int = 1,
) -> dict[str, bool]:
    client = _native_client(journal, effects, generation=generation)
    await asyncio.wait_for(client.__aenter__(), timeout=5)
    error_observed = False
    try:
        await asyncio.wait_for(
            client.call_tool(
                "probe",
                {
                    "operation": operation,
                    "phase": "crash",
                    "request_id": f"{operation}-{generation}",
                },
            ),
            timeout=2,
        )
    except Exception:
        error_observed = True
    finally:
        close_bounded = await _close_bounded(client)
    pids = _event_values(_events(journal), "process_started", "pid")
    child_closed = len(pids) == 1 and await _all_dead(pids)
    return {
        "error_observed": error_observed,
        "resource_closed": close_bounded and child_closed,
    }


async def _recover_generation(
    journal: Path,
    effects: Path,
    *,
    generation: int,
) -> dict[str, bool]:
    client = _native_client(journal, effects, generation=generation)
    await asyncio.wait_for(client.__aenter__(), timeout=5)
    recovered = False
    try:
        await asyncio.wait_for(client.list_tools(cache_mode="bypass"), timeout=5)
        result = await asyncio.wait_for(
            client.call_tool(
                "probe",
                {
                    "value": "recovered",
                    "phase": "recovery",
                    "request_id": f"recovery-{generation}",
                },
            ),
            timeout=5,
        )
        recovered = (
            not result.is_error
            and result.structured_content.get("generation") == generation
        )
    finally:
        close_bounded = await _close_bounded(client)
    pids = _event_values(_events(journal), "process_started", "pid")
    child_closed = len(pids) == 2 and await _all_dead(pids)
    return {
        "recovered": recovered,
        "resource_closed": close_bounded and child_closed,
    }


async def probe_schema_drift(work: Path) -> dict[str, object]:
    first_tools, first_closed = await _discover_schema_revision(
        work,
        name="v1",
        schema_revision="v1",
        generation=1,
    )
    first_digest = _schema_digest(first_tools.tools)

    compatible_tools, compatible_closed = await _discover_schema_revision(
        work,
        name="compatible",
        schema_revision="compatible",
        generation=2,
    )
    compatible_digest = _schema_digest(compatible_tools.tools)

    incompatible_tools, incompatible_closed = await _discover_schema_revision(
        work,
        name="incompatible",
        schema_revision="incompatible",
        generation=3,
    )
    incompatible_digest = _schema_digest(incompatible_tools.tools)

    publisher = _SpikeSchemaPublisher(mapped_tools=frozenset({"probe"}))
    grants_before = publisher.capability_grant_count
    initial_reason = publisher.observe(
        first_tools.tools,
        now_tick=1,
        expires_at_tick=10,
    )
    compatible_reason = publisher.observe(
        compatible_tools.tools,
        now_tick=2,
        expires_at_tick=10,
    )
    published_compatible_digest = publisher.published_digest
    drift_reason = publisher.observe(
        incompatible_tools.tools,
        now_tick=3,
        expires_at_tick=10,
    )
    health_after_drift = publisher.health
    published_after_drift = publisher.published_digest
    expiry_reason = publisher.observe(
        compatible_tools.tools,
        now_tick=11,
        expires_at_tick=10,
    )
    health_after_expiry = publisher.health
    grants_after = publisher.capability_grant_count
    return {
        "first_digest": first_digest,
        "compatible_digest": compatible_digest,
        "observed_drift_digest": incompatible_digest,
        "published_digest": publisher.published_digest,
        "compatible_published": initial_reason == "published"
        and compatible_reason == "published"
        and published_compatible_digest == compatible_digest,
        "drift_rejected": drift_reason == "mapped_tool_schema_changed",
        "expired_rejected": expiry_reason == "schema_expired",
        "last_known_good_unchanged": published_after_drift
        == published_compatible_digest
        == publisher.published_digest,
        "drift_reason_code": drift_reason,
        "expiry_reason_code": expiry_reason,
        "health_after_drift": health_after_drift,
        "health_after_expiry": health_after_expiry,
        "new_tool_observed": any(
            tool.name == "newly_discovered" for tool in compatible_tools.tools
        ),
        "capability_grants_before": grants_before,
        "capability_grants_after": grants_after,
        "resource_closed": first_closed and compatible_closed and incompatible_closed,
    }


async def _discover_schema_revision(
    work: Path,
    *,
    name: str,
    schema_revision: str,
    generation: int,
) -> tuple[types.ListToolsResult, bool]:
    journal = work / f"schema-{name}.jsonl"
    effects = work / f"schema-{name}-effects.jsonl"
    client = _native_client(
        journal,
        effects,
        schema_revision=schema_revision,
        generation=generation,
    )
    await asyncio.wait_for(client.__aenter__(), timeout=5)
    try:
        tools = await asyncio.wait_for(
            client.list_tools(cache_mode="bypass"), timeout=5
        )
    finally:
        close_bounded = await _close_bounded(client)
    pids = _event_values(_events(journal), "process_started", "pid")
    child_closed = len(pids) == 1 and await _all_dead(pids)
    return tools, close_bounded and child_closed


class _SpikeSchemaPublisher:
    def __init__(self, *, mapped_tools: frozenset[str]) -> None:
        self._mapped_tools = mapped_tools
        self._published_tools: tuple[types.Tool, ...] | None = None
        self._published_digest = ""
        self._capability_grants: set[str] = set()
        self.health = "unavailable"

    @property
    def capability_grant_count(self) -> int:
        return len(self._capability_grants)

    @property
    def published_digest(self) -> str:
        return self._published_digest

    def observe(
        self,
        tools: list[types.Tool],
        *,
        now_tick: int,
        expires_at_tick: int,
    ) -> str:
        if now_tick > expires_at_tick:
            self.health = "unavailable"
            return "schema_expired"
        if self._published_tools is not None:
            reason = _mapped_schema_incompatibility(
                self._published_tools,
                tools,
                mapped_tools=self._mapped_tools,
            )
            if reason is not None:
                self.health = "stale"
                return reason
        self._published_tools = tuple(tools)
        self._published_digest = _schema_digest(tools)
        self.health = "healthy"
        return "published"


def _mapped_schema_incompatibility(
    published: tuple[types.Tool, ...],
    observed: list[types.Tool],
    *,
    mapped_tools: frozenset[str],
) -> str | None:
    published_by_name = {tool.name: tool for tool in published}
    observed_by_name = {tool.name: tool for tool in observed}
    for tool_name in sorted(mapped_tools):
        if tool_name not in observed_by_name:
            return "mapped_tool_removed"
        if _tool_schema_contract(published_by_name[tool_name]) != _tool_schema_contract(
            observed_by_name[tool_name]
        ):
            return "mapped_tool_schema_changed"
    return None


def _tool_schema_contract(tool: types.Tool) -> dict[str, object]:
    encoded = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {
        "inputSchema": encoded.get("inputSchema"),
        "outputSchema": encoded.get("outputSchema"),
    }


def _native_client(
    journal: Path,
    effects: Path,
    *,
    schema_revision: str = "v1",
    generation: int = 1,
    startup_delay_ms: int = 0,
    discovery_delay_ms: int = 0,
) -> Client:
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(Path(__file__).resolve()),
            "--serve",
            "--journal",
            str(journal),
            "--effect-journal",
            str(effects),
            "--schema-revision",
            schema_revision,
            "--generation",
            str(generation),
            "--startup-delay-ms",
            str(startup_delay_ms),
            "--discovery-delay-ms",
            str(discovery_delay_ms),
        ],
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    transport = stdio_client(params, errlog=_ERRLOG)
    return Client(
        transport,
        mode="auto",
        read_timeout_seconds=5,
        cache=None,
    )


async def _close_bounded(client: Client) -> bool:
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            client.__aexit__(None, None, None), timeout=CLOSE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        return False
    except Exception:
        return time.monotonic() - started < DEADLINE_RETURN_BOUND_SECONDS
    return time.monotonic() - started < DEADLINE_RETURN_BOUND_SECONDS


def _append_event(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)


def _events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _event_count(events: list[dict[str, object]], event_name: str) -> int:
    return sum(1 for event in events if event.get("event") == event_name)


def _event_values(
    events: list[dict[str, object]],
    event_name: str,
    field: str,
) -> list[int]:
    return [
        int(event[field])
        for event in events
        if event.get("event") == event_name and field in event
    ]


def _phase_request_ids(
    events: list[dict[str, object]],
    event_name: str,
    phase: str,
) -> list[str]:
    return [
        str(event["request_id"])
        for event in events
        if event.get("event") == event_name
        and event.get("phase") == phase
        and "request_id" in event
    ]


async def _wait_for_event(path: Path, event_name: str) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if _event_count(_events(path), event_name):
            return
        await asyncio.sleep(0.01)
    raise RuntimeError(f"timed out waiting for fixture event: {event_name}")


async def _all_dead(pids: list[int]) -> bool:
    if not pids:
        return False
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if all(not _pid_alive(pid) for pid in pids):
            return True
        await asyncio.sleep(0.02)
    return all(not _pid_alive(pid) for pid in pids)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _fd_count() -> int:
    path = Path("/proc/self/fd")
    return len(tuple(path.iterdir())) if path.is_dir() else 0


def _owned_task_count() -> int:
    current = asyncio.current_task()
    return sum(
        1 for task in asyncio.all_tasks() if task is not current and not task.done()
    )


def _schema_digest(tools: list[types.Tool]) -> str:
    payload = [
        tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        for tool in sorted(tools, key=lambda item: item.name)
    ]
    return _digest(payload)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    material = SPIKE_ID.encode() + b"\x00" + encoded
    return f"sha-256:{hashlib.sha256(material).hexdigest()}"


if __name__ == "__main__":
    main()
