"""Exercise OneBot JSON through AstrBot's in-memory WebSocket ingress.

Run this inside the pinned AstrBot image. The OneBot API boundary is replaced
with a strict read-only stub, so the contract cannot send a QQ message.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import tempfile

from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot_plugin_dududa_core.adapters.message import AstrBotInputConnector
from astrbot_plugin_dududa_core.rollout_bridge import AstrBotRuntimeRequestFactory
from dududa.adapters.attachments import InMemoryAttachmentRepository
from dududa.domain.primitives import RuntimeBudget


_CASE_RE = re.compile(r"^### Case (\d+)(?:[：:]\s*(.*))?$", re.MULTILINE)
_OUTBOUND_ACTIONS = frozenset(
    {
        "send_group_msg",
        "send_private_msg",
        "send_group_forward_msg",
        "send_private_forward_msg",
        ".handle_quick_operation_async",
    }
)


def parse_questions(path: Path) -> tuple[tuple[int, str], ...]:
    source = path.read_text(encoding="utf-8")
    headings = list(_CASE_RE.finditer(source))
    questions: list[tuple[int, str]] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        block = source[heading.end() : end]
        match = re.search(
            r"\*\*Q：\*\*\s*(.*?)(?=\n\*\*(?:预期|考察)：\*\*)",
            block,
            re.DOTALL,
        )
        if match is None:
            raise ValueError(f"case {heading.group(1)} is missing Q")
        question = " ".join(
            line.strip() for line in match.group(1).splitlines() if line.strip()
        )
        questions.append((int(heading.group(1)), question))
    if [case_id for case_id, _ in questions] != list(range(1, 76)):
        raise ValueError("benchmark cases must be continuous from 1 through 75")
    return tuple(questions)


def onebot_payload(case_id: int, question: str) -> dict[str, object]:
    timestamp = 1_787_680_800 + case_id
    bot_id = 1_000_000_001
    user_id = 3_000_000_001
    return {
        "time": timestamp,
        "self_id": bot_id,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 900_000_000 + case_id,
        "group_id": 2_000_000_001,
        "user_id": user_id,
        "message": [
            {"type": "at", "data": {"qq": str(bot_id)}},
            {"type": "text", "data": {"text": f" {question}"}},
        ],
        "raw_message": f"[CQ:at,qq={bot_id}] {question}",
        "font": 0,
        "sender": {
            "user_id": user_id,
            "nickname": "benchmark-user",
            "card": "",
            "role": "member",
        },
    }


class StrictOneBotStub:
    def __init__(self, *, delay_first_lookup: bool = False) -> None:
        self.actions: Counter[str] = Counter()
        self._delay_first_lookup = delay_first_lookup
        self._lookup_count = 0

    async def __call__(self, *args: object, **kwargs: object) -> dict[str, object]:
        action = str(kwargs.get("action") or (args[0] if args else ""))
        self.actions[action] += 1
        if action in _OUTBOUND_ACTIONS or action.startswith("send_"):
            raise AssertionError(f"outbound OneBot action is forbidden: {action}")
        if action == "get_group_member_info":
            self._lookup_count += 1
            if self._delay_first_lookup and self._lookup_count == 1:
                await asyncio.sleep(0.05)
            return {"card": "嘟嘟哒", "nickname": "嘟嘟哒"}
        if action == "get_stranger_info":
            return {"nickname": "嘟嘟哒"}
        raise AssertionError(f"unexpected OneBot action: {action}")

    @property
    def outbound_count(self) -> int:
        return sum(
            count
            for action, count in self.actions.items()
            if action in _OUTBOUND_ACTIONS or action.startswith("send_")
        )


def build_adapter(
    queue: asyncio.Queue[object],
    stub: StrictOneBotStub,
) -> AiocqhttpAdapter:
    adapter = AiocqhttpAdapter(
        {
            "id": "qq-adapter-benchmark",
            "ws_reverse_host": "127.0.0.1",
            "ws_reverse_port": 0,
            "ws_reverse_token": "host-ingress-contract",
        },
        {},
        queue,
    )
    adapter.bot.call_action = stub  # type: ignore[method-assign]
    adapter.bot.logger.setLevel("WARNING")
    return adapter


async def websocket_events(
    adapter: AiocqhttpAdapter,
    payloads: tuple[dict[str, object], ...],
) -> tuple[AiocqhttpMessageEvent, ...]:
    headers = {
        "Authorization": "Bearer host-ingress-contract",
        "X-Client-Role": "event",
        "X-Self-ID": "1000000001",
    }
    queue = adapter._event_queue  # noqa: SLF001 - this is the host contract boundary
    async with adapter.bot.server_app.test_client().websocket(
        "/ws",
        headers=headers,
    ) as websocket:
        for payload in payloads:
            await websocket.send(json.dumps(payload, ensure_ascii=False))
        collected: list[object] = []
        for _ in payloads:
            collected.append(await asyncio.wait_for(queue.get(), timeout=10))
        events = tuple(collected)
    if not all(isinstance(event, AiocqhttpMessageEvent) for event in events):
        raise AssertionError("AstrBot did not produce AiocqhttpMessageEvent")
    return events


async def run_contract(fixture: Path) -> dict[str, object]:
    questions = parse_questions(fixture)
    queue: asyncio.Queue[object] = asyncio.Queue()
    stub = StrictOneBotStub()
    adapter = build_adapter(queue, stub)
    payloads = tuple(onebot_payload(case_id, question) for case_id, question in questions)
    events = await websocket_events(adapter, payloads)

    connector = AstrBotInputConnector(InMemoryAttachmentRepository())
    factory = AstrBotRuntimeRequestFactory(
        connector,
        RuntimeBudget(2, 1, 2, 16_000, 2_000, Decimal("20")),
        "host-ingress-contract-v1",
        response_profiles_enabled=True,
    )
    prepared: list[dict[str, object]] = []
    for event in events:
        request, _ = await factory.prepare(
            event,
            control_revision="host-ingress-contract-v1",
            timeout_seconds=10,
            tools_enabled=True,
            memory_enabled=False,
        )
        prepared.append(
            {
                "message_id": int(request.connector_result.message.message_id),
                "text": request.connector_result.message.text,
                "event_type": type(event).__name__,
            }
        )

    observed_case_ids = tuple(item["message_id"] - 900_000_000 for item in prepared)
    expected_case_ids = tuple(case_id for case_id, _ in questions)
    if {item["text"] for item in prepared} != {question for _, question in questions}:
        raise AssertionError("Connector text differs from the source questions")

    probe_queue: asyncio.Queue[object] = asyncio.Queue()
    probe_stub = StrictOneBotStub(delay_first_lookup=True)
    probe_adapter = build_adapter(probe_queue, probe_stub)
    probe_payloads = tuple(onebot_payload(case_id, f"顺序探测 {case_id}") for case_id in (1, 2, 3))
    probe_events = await websocket_events(probe_adapter, probe_payloads)
    probe_order = tuple(int(event.message_obj.message_id) - 900_000_000 for event in probe_events)

    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "astrbot_version": version("AstrBot"),
        "aiocqhttp_version": version("aiocqhttp"),
        "input_count": len(questions),
        "native_event_count": len(events),
        "request_factory_count": len(prepared),
        "expected_case_ids": list(expected_case_ids),
        "observed_case_ids": list(observed_case_ids),
        "sequential_order_observed": observed_case_ids == expected_case_ids,
        "onebot_actions": dict(stub.actions),
        "outbound_onebot_actions": stub.outbound_count,
        "order_probe": {
            "input": [1, 2, 3],
            "observed": list(probe_order),
            "reordered": probe_order != (1, 2, 3),
            "delay_first_lookup_ms": 50,
            "onebot_actions": dict(probe_stub.actions),
            "outbound_onebot_actions": probe_stub.outbound_count,
        },
    }


def write_private_json(path: Path, value: dict[str, object]) -> None:
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


async def async_main(args: argparse.Namespace) -> int:
    result = await run_contract(args.fixture)
    write_private_json(args.result, result)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the 75-case AstrBot/OneBot host-ingress contract."
    )
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return asyncio.run(async_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
