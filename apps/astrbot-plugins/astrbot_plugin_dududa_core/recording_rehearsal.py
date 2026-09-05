"""Replay synthetic group messages through proactive participation and Runtime."""

from __future__ import annotations

from types import SimpleNamespace

from dududa.rollout import CanaryExecutionDisposition

from .adapters.proactive_talk import ProactiveTalkController
from .rollout_bridge import AstrBotBridgeAction
from .web_runtime import WebRuntimePreviewEvent, preview_event


class Plain:
    def __init__(self, text: str):
        self.text = text


class _GroupEvent(WebRuntimePreviewEvent):
    def __init__(self, *, bot_id: str, group_id: str, member: dict):
        super().__init__(bot_id=bot_id, group_id=group_id, prompt=member["content"])
        self.message_str = member["content"]
        self.message_obj.message = [Plain(self.message_str)]
        self.message_obj.message_str = self.message_str
        self._sender_id = member["senderId"]
        self.is_at_or_wake_command = False

    def get_sender_id(self):
        return self._sender_id

    def stop_event(self):
        pass

    async def send(self, *args, **kwargs):
        raise RuntimeError("recording_uses_preview_output_only")


class _History:
    def __init__(self):
        self.lines: tuple[str, ...] = ()

    async def recent_lines(self, event, *, message_limit, byte_limit):
        result: list[str] = []
        size = 0
        for line in reversed(self.lines[-message_limit:]):
            size += len(line.encode("utf-8"))
            if size > byte_limit:
                break
            result.insert(0, line)
        return tuple(result)


class _PreviewBridge:
    def __init__(self, bridge):
        self.bridge = bridge
        self.results = []

    async def handle(self, event, *, proactive_group_participation=False):
        result = await self.bridge.preview(
            event, proactive_group_participation=proactive_group_participation
        )
        self.results.append(result)
        delivered = (
            result.runtime_result.outcome.value == "response"
            and result.runtime_result.final_response is not None
        )
        return SimpleNamespace(
            action=AstrBotBridgeAction.CANARY_COMPLETED
            if delivered
            else AstrBotBridgeAction.CANARY_FAILED,
            canary=SimpleNamespace(disposition=CanaryExecutionDisposition.DELIVERED)
            if delivered
            else None,
            reason_code=",".join(result.runtime_result.reason_codes),
        )


async def run_recording_rehearsal(plugin, payload: dict) -> dict:
    source, _ = preview_event(payload)
    history_input = source.dududa_preview_history
    if not history_input or history_input.get("source") != "synthetic":
        raise ValueError("recording_requires_synthetic_history")
    resolver = getattr(plugin, "scope_policy_resolver", None)
    bridge = getattr(plugin, "rollout_bridge", None)
    if resolver is None or bridge is None:
        raise ValueError("recording_runtime_not_ready")
    rows = history_input["messages"]
    history, relay = _History(), _PreviewBridge(bridge)
    clock = [1000.0]
    # The fixed six-second message timeline is accelerated; model/tool calls remain real.
    controller = ProactiveTalkController(
        relay, resolver, history=history, monotonic=lambda: clock[0]
    )
    transitions = []
    for index, member in enumerate(rows):
        clock[0] += 6
        history.lines += (
            f"{member.get('senderName', member['senderId'])}：{member['content']}",
        )
        event = _GroupEvent(
            bot_id=source.get_self_id(), group_id=source.get_group_id(), member=member
        )
        before = resolver.adaptive_status()
        replied = await controller.maybe_handle(event)
        after = resolver.adaptive_status()
        transitions.append(
            {
                "message": index + 1,
                "replied": replied,
                "activated": [item["pluginId"] for item in after if item not in before],
            }
        )
    responses = []
    for preview in relay.results:
        result = preview.runtime_result
        response = result.final_response
        text = (
            "\n\n".join(
                block.content.text
                for block in response.response.blocks
                if block.content.text
            )
            if response
            else ""
        )
        responses.append(
            {
                "runId": result.run_id,
                "candidate": text,
                "outcome": result.outcome.value,
                "reasonCodes": list(result.reason_codes),
                "toolCalls": preview.tool_calls,
                "capabilityIds": list(preview.capability_ids),
                "contextUsage": preview.context_usage,
                "diagnostics": preview.diagnostics,
            }
        )
    return {
        "mode": "synthetic_group_rehearsal",
        "messageIntervalSeconds": 6,
        "messages": len(rows),
        "participants": len({row["senderId"] for row in rows}),
        "transitions": transitions,
        "responses": responses,
        "adaptiveActivations": resolver.adaptive_status(),
        "outputCalls": 0,
        "memoryWrites": 0,
    }


async def runtime_rehearsal_response(plugin):
    from astrbot.api.web import error_response, json_response, request

    try:
        result = await run_recording_rehearsal(plugin, await request.json(default={}))
    except ValueError as exc:
        return error_response(str(exc), status_code=400)
    return json_response({"status": "ok", "data": result})
