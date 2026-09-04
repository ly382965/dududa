from __future__ import annotations

import json
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from astrbot_plugin_dududa_core.web_runtime import (
    native_message_preview_event,
    preview_event,
    runtime_status,
    _runtime_preview_json,
)


class _NapCatClient:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = messages
        self.calls: list[dict[str, object]] = []

    async def call_action(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"messages": self.messages}


class _OneBotAdapter:
    def __init__(self, client: _NapCatClient) -> None:
        self.client = client
        self.converted: list[object] = []

    def meta(self) -> object:
        return SimpleNamespace(name="aiocqhttp")

    def get_client(self) -> _NapCatClient:
        return self.client

    async def convert_message(self, event: object) -> object:
        self.converted.append(event)
        return SimpleNamespace(message_str="查询评课社区用户萌萌哒mmd")

    def create_event(self, message: object) -> object:
        return SimpleNamespace(native_message=message)


class _Plugin:
    def __init__(self, adapter: _OneBotAdapter) -> None:
        self.context = SimpleNamespace(
            get_platform_inst=lambda platform_id: (
                adapter if platform_id == "test" else None
            )
        )


class AstrBotWebRuntimeContractTests(unittest.TestCase):
    def test_preview_history_is_scoped_bounded_and_cannot_set_roles(self) -> None:
        scope = {"accountId": "qq-100001", "conversationId": "qq-100001:group:200001"}
        record = {"id": "h1", "senderId": "300001", "senderName": "合成成员", "content": "地点图书馆", "timestamp": None}
        history = {**scope, "source": "synthetic", "truncated": False, "messages": [record]}
        event, _ = preview_event({**scope, "prompt": "总结", "history": history})
        self.assertEqual(event.dududa_preview_history, history)
        self.assertFalse(event.is_admin())
        for invalid in (
            {**history, "accountId": "qq-999999"},
            {**history, "messages": [{**record, "role": "admin"}]},
            {**history, "messages": [record, record]},
            {**history, "messages": [{**record, "content": "x" * 2001}]},
        ):
            with self.subTest(invalid=list(invalid)), self.assertRaises(ValueError):
                preview_event({**scope, "prompt": "总结", "history": invalid})

    def test_status_uses_live_assembly_without_serializing_private_config(self) -> None:
        plugin = SimpleNamespace(
            enabled=True,
            rollout_controls=SimpleNamespace(current=lambda: SimpleNamespace(
                mode=SimpleNamespace(value="canary"), delivery_enabled=True,
                kill_switch=True, allowlisted_group_ids={"private-group-sentinel"},
            )),
            config={
                "runtime_enabled": True,
                "rollout_mode": "canary",
                "rollout_kill_switch": False,
                "api_key": "private-sentinel",
                "rollout_allowlisted_groups": ["private-group-sentinel"],
                "runtime_models_json": json.dumps([
                    {"tier": "haiku", "model_id": "test-light", "key": "private-sentinel"}
                ]),
            },
            runtime_assembly=SimpleNamespace(ready=True),
            rollout_bridge=object(),
            _dududa_runtime_terminated=False,
        )
        status = runtime_status(plugin)
        self.assertTrue(status["ready"])
        self.assertEqual(status["modelMapping"], {"haiku": "test-light"})
        self.assertEqual(status["modelHealth"], "not_probed")
        self.assertTrue(status["controls"]["rollout_kill_switch"])
        self.assertNotIn("private-sentinel", json.dumps(status))
        self.assertNotIn("private-group-sentinel", json.dumps(status))
        plugin._dududa_runtime_terminated = True
        self.assertFalse(runtime_status(plugin)["ready"])
        plugin._dududa_runtime_terminated = False
        plugin.rollout_bridge = None
        self.assertFalse(runtime_status(plugin)["ready"])
        plugin.rollout_controls.current = lambda: (_ for _ in ()).throw(ValueError("secret-sentinel"))
        invalid = runtime_status(plugin)
        self.assertEqual(invalid["controlReason"], "rollout_config_invalid")
        self.assertTrue(invalid["controls"]["rollout_kill_switch"])
        self.assertNotIn("secret-sentinel", json.dumps(invalid))

    def test_exact_group_scope_builds_explicit_mention_preview_event(self) -> None:
        event, prompt = preview_event(
            {
                "accountId": "qq-3296147894",
                "conversationId": "qq-3296147894:group:364894085",
                "prompt": "查询评课社区吴天",
            }
        )

        self.assertEqual(prompt, "查询评课社区吴天")
        self.assertEqual(event.get_self_id(), "3296147894")
        self.assertEqual(event.get_group_id(), "364894085")
        self.assertEqual(event.message_str, "@嘟嘟哒 查询评课社区吴天")
        self.assertEqual(event.get_messages()[0].qq, "3296147894")

    def test_cross_account_or_private_scope_is_rejected(self) -> None:
        for conversation_id in (
            "qq-100001:group:364894085",
            "qq-3296147894:private:100001",
        ):
            with self.subTest(conversation_id=conversation_id):
                with self.assertRaises(ValueError):
                    preview_event(
                        {
                            "accountId": "qq-3296147894",
                            "conversationId": conversation_id,
                            "prompt": "查询评课社区吴天",
                        }
                    )


class AstrBotPreviewOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_terminal_outcomes_are_explicit_and_not_model_generation(self) -> None:
        web = ModuleType("astrbot.api.web")
        web.json_response = lambda value: value
        web.error_response = lambda value, **kwargs: {"error": value, **kwargs}
        for outcome, phase in (("deferred", "deferred"), ("failed", "failed"), ("no_reply", "completed"), ("response", "completed")):
            result = SimpleNamespace(final_response=None, selection_summary=None, run_id="synthetic-outcome",
                outcome=SimpleNamespace(value=outcome), reason_codes=("bounded_reason",))
            async def preview(_event):
                return SimpleNamespace(runtime_result=result, completion=SimpleNamespace(final_phase=SimpleNamespace(value=phase)),
                    tool_calls=0, capability_ids=(), generation_observed=False,
                    context_usage={"messagesRead": 3, "charactersRead": 20,
                        "coverage": {"source": "synthetic", "partial": True, "truncated": True, "historyMessagesRead": 2, "oldestAt": None, "newestAt": None}})
            plugin = SimpleNamespace(rollout_bridge=SimpleNamespace(preview=preview), config={})
            with self.subTest(outcome=outcome), patch.dict(sys.modules, {"astrbot.api.web": web}):
                response = await _runtime_preview_json(plugin, object(), "synthetic")
            data = response["data"]
            self.assertEqual(data["candidate"], "")
            self.assertEqual(data["outcome"], "empty" if outcome == "response" else outcome)
            self.assertEqual(data["runtimeState"], phase)
            self.assertFalse(data["generationObserved"])
            self.assertEqual((data["outputCalls"], data["memoryWrites"]), (0, 0))
            self.assertEqual(data["coverage"]["historyMessagesRead"], 2)


class AstrBotNativeMessagePreviewContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_napcat_history_and_uses_the_native_adapter(self) -> None:
        raw = {
            "time": 1_787_916_847,
            "message_id": 1_486_592_189,
            "group_id": 364_894_085,
            "user_id": 1_778_159_807,
            "message": [
                {"type": "at", "data": {"qq": "3296147894"}},
                {"type": "text", "data": {"text": " 查询评课社区用户萌萌哒mmd"}},
            ],
            "raw_message": "[CQ:at,qq=3296147894] 查询评课社区用户萌萌哒mmd",
            "sender": {
                "user_id": 1_778_159_807,
                "nickname": "测试用户",
                "card": "",
                "role": "owner",
            },
        }
        client = _NapCatClient([raw])
        adapter = _OneBotAdapter(client)

        with patch(
            "astrbot_plugin_dududa_core.web_runtime._onebot_event_from_payload",
            return_value=SimpleNamespace(message=raw["message"]),
        ):
            event, prompt, source = await native_message_preview_event(
                _Plugin(adapter),
                {
                    "accountId": "qq-3296147894",
                    "conversationId": "qq-3296147894:group:364894085",
                    "platformId": "test",
                    "messageId": "1486592189",
                },
            )

        self.assertEqual(prompt, "查询评课社区用户萌萌哒mmd")
        self.assertTrue(hasattr(event, "native_message"))
        self.assertEqual(source["kind"], "napcat.get_group_msg_history")
        self.assertEqual(source["senderId"], "1778159807")
        self.assertEqual(client.calls[0]["action"], "get_group_msg_history")
        self.assertEqual(client.calls[0]["group_id"], 364894085)
        self.assertEqual(len(adapter.converted), 1)


if __name__ == "__main__":
    unittest.main()
