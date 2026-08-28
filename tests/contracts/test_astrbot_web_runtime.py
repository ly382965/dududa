from __future__ import annotations

import unittest

from astrbot_plugin_dududa_core.web_runtime import preview_event


class AstrBotWebRuntimeContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
