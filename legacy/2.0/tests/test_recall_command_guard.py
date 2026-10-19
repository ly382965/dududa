from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "apps/astrbot-plugins/astrbot_plugin_dududa_core"
spec = importlib.util.spec_from_file_location("recall_guard", PLUGIN / "recall_command_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def event(text="/开启防撤回", *, user="300001", mention="100001", kind="group", extra=None):
    segments = [{"type": "at", "data": {"qq": mention}}, {"type": "text", "data": {"text": " " + text}}]
    if extra:
        segments.append(extra)
    return SimpleNamespace(
        message_obj=SimpleNamespace(raw_message={"message_type": kind, "user_id": user, "message": segments}),
        get_self_id=lambda: "100001", stop_event=Mock(),
    )


class RecallCommandGuardTests(unittest.TestCase):
    def test_exact_commands_are_consumed_without_any_reply(self):
        for text in ("/开启防撤回", "/关闭防撤回"):
            for user in ("300001", "123456789"):
                with self.subTest(text=text, user=user):
                    e = event(text, user=user)
                    self.assertTrue(guard.consume_gateway_recall_command(e))
                    e.stop_event.assert_called_once_with()

    def test_similar_commands_and_conversation_still_reach_chat(self):
        for text in ("/开启防撤回啊", "/开启防撤", "开启防撤回", "/开启 防撤回", "/关闭防撤回\n解释一下", "你好", "解释/开启防撤回"):
            with self.subTest(text=text):
                e = event(text)
                self.assertFalse(guard.consume_gateway_recall_command(e))
                e.stop_event.assert_not_called()

    def test_requires_real_single_self_mention_and_group(self):
        cases = [event(mention="all"), event(mention="123456789"), event(kind="private"),
                 event(extra={"type":"image","data":{"file":"x"}}),
                 event(extra={"type":"at","data":{"qq":"100001"}})]
        e = event(); e.message_obj.raw_message["message"] = [{"type":"text","data":{"text":"@100001 /开启防撤回"}}]; cases.append(e)
        e = event(); e.message_obj.raw_message["message"] = "[CQ:at,qq=100001] /开启防撤回"; cases.append(e)
        e = event(); e.message_obj.raw_message = None; cases.append(e)
        for e in cases:
            self.assertFalse(guard.consume_gateway_recall_command(e))
            e.stop_event.assert_not_called()

    def test_real_handler_stops_before_runtime_and_preserves_normal_chat(self):
        # Execute the actual registered handler body without booting providers.
        tree = ast.parse((PLUGIN / "main.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DududaCorePlugin")
        fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "controlled_rollout")
        self.assertIn("priority=100", ast.unparse(fn.decorator_list[0]))
        fn.decorator_list = []
        namespace = {"AstrMessageEvent": object, "consume_gateway_recall_command": guard.consume_gateway_recall_command}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "handler", "exec"), namespace)
        plugin = SimpleNamespace(_handle_controlled_rollout=AsyncMock())
        for command in ("/开启防撤回", "/关闭防撤回"):
            e = event(command)
            asyncio.run(namespace["controlled_rollout"](plugin, e))
            e.stop_event.assert_called_once()
            plugin._handle_controlled_rollout.assert_not_awaited()
        e = event("你好")
        asyncio.run(namespace["controlled_rollout"](plugin, e))
        plugin._handle_controlled_rollout.assert_awaited_once_with(e)
        e.stop_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
