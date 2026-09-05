from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from astrbot_plugin_dududa_core.adapters.agent_policy import (
    FileScopeAgentPolicyResolver,
)
from astrbot_plugin_dududa_core.adapters.proactive_talk import ProactiveTalkController

from tests.contracts.test_proactive_talk import (
    _Bridge,
    _Clock,
    _Event,
    _History,
    _ProactiveEvent,
)


class AdaptivePluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "policy.json"
        fixture = (
            Path(__file__).parents[1]
            / "fixtures/recording/math-analysis-discussion.json"
        )
        self.messages = json.loads(fixture.read_text())["messages"]
        self.lines = tuple(f"{row['sender']}：{row['text']}" for row in self.messages)
        self.policy = {
            "scope": {
                "accountId": "qq-bot-1",
                "conversationId": "qq-bot-1:group:group-1",
            },
            "enabled": True,
            "updatedAt": "2026-09-06T00:00:00Z",
            "plugins": {"social.proactive_talk": "on", "icourse.read": "off"},
            "adaptivePlugins": ["icourse.read"],
            "contextLength": {"preferred": "standard"},
            "proactiveTalk": {
                "probabilityPercent": 100,
                "cooldownSeconds": 5,
                "maximumPerHour": 20,
                "minimumMessages": 20,
            },
        }
        self.save()
        self.resolver = FileScopeAgentPolicyResolver(self.path)

    def save(self):
        self.path.write_text(json.dumps({"policies": {"group": self.policy}}))

    async def test_twenty_messages_enable_icourse_then_enter_proactive_runtime(self):
        bridge, clock = _Bridge(), _Clock()
        history = _History()
        controller = ProactiveTalkController(
            bridge,
            self.resolver,
            history=history,
            monotonic=clock,
            random_value=lambda: 0.0,
            event_factory=_ProactiveEvent,
        )
        self.assertEqual(len(self.lines), 20)
        self.assertEqual(len({row["sender"] for row in self.messages}), 4)
        self.assertEqual(self.resolver.adaptive_status(), [])
        for index in range(20):
            history.lines = self.lines[: index + 1]
            clock.value += 6
            event = _Event()
            event.message_str = self.messages[index]["text"]
            delivered = await controller.maybe_handle(event)
            self.assertEqual(delivered, index == 19, index + 1)
            if index < 19:
                self.assertEqual(self.resolver.adaptive_status(), [])
        self.assertEqual(len(bridge.calls), 1)
        event, proactive = bridge.calls[0]
        self.assertTrue(proactive)
        self.assertEqual(event.message_str, self.messages[-1]["text"])
        self.assertEqual(len(event.dududa_preview_history["messages"]), 19)
        self.assertIn("数学分析", event.message_str)
        state = self.resolver.adaptive_status()[0]
        self.assertEqual(state["pluginId"], "icourse.read")
        self.assertEqual(state["messagesRead"], 20)
        # The administrator's starting policy stays off; activation is scoped runtime state.
        self.assertEqual(
            json.loads(self.path.read_text())["policies"]["group"]["plugins"][
                "icourse.read"
            ],
            "off",
        )

    def test_off_without_adaptive_permission_stays_off(self):
        self.policy["adaptivePlugins"] = []
        self.save()
        self.assertIsNone(
            self.resolver.activate_for_context(
                bot_id="bot-1", group_id="group-1", lines=self.lines
            )
        )
        self.assertEqual(self.resolver.adaptive_status(), [])

    def test_other_group_and_new_policy_do_not_inherit_activation(self):
        self.assertIsNone(
            self.resolver.activate_for_context(
                bot_id="bot-1", group_id="other", lines=self.lines
            )
        )
        self.resolver.activate_for_context(
            bot_id="bot-1", group_id="group-1", lines=self.lines
        )
        self.assertEqual(len(self.resolver.adaptive_status()), 1)
        self.policy["updatedAt"] = "2026-09-06T01:00:00Z"
        self.save()
        self.assertEqual(self.resolver.adaptive_status(), [])

    def test_conversation_without_current_question_does_not_activate(self):
        for count in range(1, 20):
            self.assertIsNone(
                self.resolver.activate_for_context(
                    bot_id="bot-1", group_id="group-1", lines=self.lines[:count]
                )
            )

    async def test_zero_probability_does_not_activate(self):
        self.policy["proactiveTalk"]["probabilityPercent"] = 0
        self.save()
        bridge = _Bridge()
        controller = ProactiveTalkController(
            bridge, self.resolver, history=_History(self.lines)
        )
        self.assertFalse(await controller.maybe_handle(_Event()))
        self.assertEqual(bridge.calls, [])
        self.assertEqual(self.resolver.adaptive_status(), [])

    async def test_adaptive_query_reaches_mcp_through_production_runtime(self):
        from dataclasses import replace
        from datetime import timedelta
        from unittest.mock import patch

        from astrbot_plugin_dududa_core.adapters.adaptive_plugins import (
            adaptive_history,
        )

        from ops.cli.run_dududa_100_message_benchmark import (
            FIXED_NOW,
            FixtureUnifiedMcpClient,
            Native100Event,
            Scripted100Provider,
            _checkpoint_summary,
            _ICourseFacade,
            composition,
            load_capability_catalog_snapshot,
        )
        from tests.contracts.test_production_composition import (
            ProductionCompositionContractTests,
        )

        harness = ProductionCompositionContractTests("runTest")
        harness.setUp()
        self.addCleanup(harness.tearDown)
        root = Path(__file__).parents[2]
        cases = json.loads(
            (
                root / "tests/fixtures/mcp/dududa-100-native-message-cases.json"
            ).read_text()
        )["cases"]
        case = next(
            row
            for row in cases
            if row.get("capability_id") == "icourse.public-query.v2"
        )
        case = {
            **case,
            "question": self.messages[-1]["text"],
            "entity_terms": ["数学分析"],
            "answer": "数学分析可以结合授课风格、评价数量和各自基础选择。",
            "scene": {"mention": False},
        }
        provider = Scripted100Provider((case,))
        provider._active_case = case
        catalog = load_capability_catalog_snapshot(
            root / "configs/capabilities/definitions",
            root / "configs/capabilities/mappings",
            snapshot_id="recording-adaptive",
            acquired_at=FIXED_NOW,
        )
        mcp = FixtureUnifiedMcpClient(catalog=catalog)
        mcp.set_case(case)
        plugin = harness._production_plugin(provider)
        plugin.unified_mcp_client, plugin.icourse = mcp, _ICourseFacade(mcp)
        values = harness._runtime_config(rollout_mode="canary")
        values.update(
            rollout_allowlisted_groups=["2000000001"],
            rollout_delivery_enabled=True,
            rollout_kill_switch=False,
            rollout_tools_enabled=True,
            proactive_talk_enabled=True,
        )
        self.policy["scope"] = {
            "accountId": "qq-1000000001",
            "conversationId": "qq-1000000001:group:2000000001",
        }
        self.save()
        assembly = composition.build_production_runtime(
            plugin, values, clock=lambda: FIXED_NOW
        )
        self.addAsyncCleanup(assembly.close)
        with patch.dict("os.environ", {"DUDUDA_AGENT_POLICY_PATH": str(self.path)}):
            harness._initialize(plugin, values, "adaptive", runtime_assembly=assembly)
        await assembly.publish_model_health(
            (harness._healthy_evidence(assembly, FIXED_NOW, ttl=timedelta(hours=1)),),
            call=replace(harness.call, deadline=FIXED_NOW + timedelta(hours=1)),
        )
        request = plugin.scope_policy_resolver.activate_for_context(
            bot_id="1000000001", group_id="2000000001", lines=self.lines
        )
        self.assertIsNotNone(request)
        event = Native100Event(case)
        event.dududa_preview_history = adaptive_history(
            self.lines, bot_id="1000000001", group_id="2000000001"
        )
        preview = await plugin.rollout_bridge.preview(
            event, proactive_group_participation=True
        )
        checkpoint = await assembly.state_store.load(
            preview.runtime_result.run_id,
            call=replace(
                harness.call,
                run_id=preview.runtime_result.run_id,
                deadline=FIXED_NOW + timedelta(hours=1),
            ),
        )
        self.assertEqual(preview.tool_calls, 1, _checkpoint_summary(checkpoint))
        self.assertEqual(
            preview.capability_ids,
            ("icourse.public-query.v2",),
            {
                "model_calls": len(provider.calls),
                "perception": checkpoint.state.perception_execution.result.reason_codes,
                "perception_failure": checkpoint.state.perception_execution.failure_code,
            },
        )
        self.assertIsNotNone(preview.runtime_result.final_response)
        self.assertEqual(mcp.tool_calls[0]["server_id"], "icourse")
        self.assertIn("数学分析", str(mcp.tool_calls[0]["arguments"]))
        self.assertEqual(event.send_calls, 0)
