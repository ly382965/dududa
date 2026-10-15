"""Inject fixed OneBot inputs into the logged-in bot's proactive Runtime."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.ports.context import NeverCancelled, PortCallContext


class RehearsalHistoryClient:
    """Supply only the simulated history; normal QQ actions use the real client."""

    def __init__(self, client, bot_id: str, group_id: str):
        self.client, self.bot_id, self.group_id = client, bot_id, group_id
        self.messages = []

    async def call_action(self, action: str, **params):
        if (
            action == "get_group_msg_history"
            and str(params.get("group_id")) == self.group_id
        ):
            return {"messages": self.messages[-int(params.get("count", 100)) :]}
        return await self.client.call_action(action=action, **params)

    def __getattr__(self, name):
        return getattr(self.client, name)


class NativeRehearsalInput:
    def __init__(self, adapter, client, bot_id: str, group_id: str):
        self.adapter, self.client = adapter, client
        self.bot_id, self.group_id = bot_id, group_id

    async def event(self, member: dict, index: int):
        from .web_runtime import _onebot_event_from_payload

        raw = {
            "self_id": int(self.bot_id),
            "group_id": int(self.group_id),
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": int(member["id"]),
            "message_seq": index + 1,
            "user_id": int(member["senderId"]),
            "time": int(datetime.now(timezone.utc).timestamp()) + index * 6,
            "sender": {
                "user_id": int(member["senderId"]),
                "nickname": member["senderName"],
                "card": member["senderName"],
                "role": "member",
            },
            "message": [{"type": "text", "data": {"text": member["content"]}}],
            "raw_message": member["content"],
            "font": 0,
        }
        self.client.messages.append(raw)
        message = await self.adapter.convert_message(_onebot_event_from_payload(raw))
        if message is None:
            raise ValueError("native_rehearsal_message_ignored")
        event = self.adapter.create_event(message)
        event.bot = self.client
        event.is_at_or_wake_command = False
        return event


async def native_input(plugin, payload, source, rows):
    adapter = plugin.context.get_platform_inst(payload.get("platformId", ""))
    if adapter is None or adapter.meta().name != "aiocqhttp":
        raise ValueError("native_platform_not_onebot")
    bot_id, group_id = source.get_self_id(), source.get_group_id()
    client = adapter.get_client()
    login = await client.call_action(action="get_login_info", self_id=int(bot_id))
    if str(login.get("user_id")) != bot_id:
        raise ValueError("native_rehearsal_account_mismatch")
    members = await client.call_action(
        action="get_group_member_list", group_id=int(group_id), self_id=int(bot_id)
    )
    member_ids = {str(item["user_id"]) for item in members}
    if any(
        row["senderId"] not in member_ids or row["senderId"] == bot_id for row in rows
    ):
        raise ValueError("native_rehearsal_sender_not_group_member")
    if any(not str(row["id"]).isdigit() for row in rows):
        raise ValueError("native_rehearsal_requires_numeric_message_ids")
    return NativeRehearsalInput(
        adapter, RehearsalHistoryClient(client, bot_id, group_id), bot_id, group_id
    )


class NativeDeliveryBridge:
    """Use the normal canary output path and inspect its existing checkpoint."""

    def __init__(self, bridge):
        self.bridge, self.results = bridge, []
        self.deliveries = []

    async def handle(self, event, *, proactive_group_participation=False):
        result = await self.bridge.handle(
            event, proactive_group_participation=proactive_group_participation
        )
        self.deliveries.append(
            {
                "action": result.action.value,
                "reason": result.reason_code,
                "runtimeReasons": list(result.runtime_reason_codes),
            }
        )
        if result.canary is None:
            return result
        run_id = result.canary.run_id
        call = PortCallContext(
            run_id,
            TraceContext(run_id),
            datetime.now(timezone.utc) + timedelta(seconds=30),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, None),
            self.bridge._requests._policy_snapshot_id,
        )
        checkpoint = await self.bridge._state_store.load(run_id, call=call)
        if checkpoint and checkpoint.state.pending_result:
            state = checkpoint.state
            steps = state.tool_plan.steps if state.tool_plan else ()
            context = (
                state.current_context.perception if state.current_context else None
            )
            failure = state.direct_chat_failure
            route = failure.route_decision if failure else None
            self.results.append(
                SimpleNamespace(
                    runtime_result=state.pending_result,
                    tool_calls=len(steps),
                    capability_ids=tuple(step.capability_id for step in steps),
                    context_usage={"messagesRead": len(context.messages)}
                    if context
                    else {},
                    diagnostics={
                        "delivery": result.canary.disposition.value,
                        "directFailure": failure.failure_code if failure else None,
                        "directAttempts": [
                            {
                                "model": attempt.model_id,
                                "error": attempt.error.code if attempt.error else None,
                                "reasons": list(attempt.error.reason_codes)
                                if attempt.error
                                else [],
                            }
                            for attempt in route.attempts
                        ]
                        if route
                        else [],
                        "toolArguments": [
                            dict(step.arguments.literal_template) for step in steps
                        ],
                    },
                )
            )
        return result
