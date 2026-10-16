from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from astrbot_plugin_dududa_core.adapters.agent_policy import (
    FileScopeAgentPolicyResolver,
)
from astrbot_plugin_dududa_core.adapters.output import InMemoryDeliveryLedger
from astrbot_plugin_dududa_core.rollout_bridge import (
    AstrBotBridgeAction,
    AstrBotRolloutBridge,
    AstrBotRuntimeRequestFactory,
)
from dududa.rollout import (
    BoundedShadowSupervisor,
    CanaryCoordinator,
    InMemoryRolloutMetrics,
    RolloutMode,
)
from dududa.runtime.shadow import ShadowRunner

from tests.unit.models.helpers import NOW
from tests.unit.rollout.helpers import control, ledger
from tests.unit.rollout.test_controlled_execution import (
    _MutableControls,
    _OutputFactory,
    _RuntimeProxy,
    _ShadowSink,
)
from tests.unit.runtime.test_orchestrator import OrchestratorFixture


class _PreparedRequests:
    def __init__(self, request, call) -> None:
        self.request = request
        self.call = call
        self.calls = 0

    async def prepare(
        self,
        event,
        *,
        control_revision,
        timeout_seconds,
        tools_enabled=False,
        memory_enabled=False,
        proactive_group_participation=False,
    ):
        self.calls += 1
        return self.request, self.call


class _Connector:
    def __init__(self, result) -> None:
        self.result = result

    async def convert(self, event, *, operation):
        return self.result


class _Event:
    def __init__(self) -> None:
        self.stopped = False
        self.stop_calls = 0

    def stop_event(self) -> None:
        self.stop_calls += 1
        self.stopped = True


class AstrBotRolloutBridgeContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "rollout.sqlite3"
        self.fixture = OrchestratorFixture()
        self.request, self.call = self.fixture.start()
        self.group_id = self.request.connector_result.message.group_id

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _bridge(self, config):
        controls = _MutableControls(config)
        runtime = _RuntimeProxy(self.fixture.runtime)
        metrics = InMemoryRolloutMetrics()
        shadow = BoundedShadowSupervisor(
            ShadowRunner(runtime, _ShadowSink(), clock=lambda: NOW),
            config,
            metrics,
            clock=lambda: NOW,
        )
        canary = CanaryCoordinator(
            runtime,
            controls,
            ledger(self.path, clock=lambda: NOW),
            metrics,
            clock=lambda: NOW,
        )
        requests = _PreparedRequests(self.request, self.call)
        output = _OutputFactory()
        bridge = AstrBotRolloutBridge(
            controls,
            requests,
            shadow,
            canary,
            InMemoryDeliveryLedger(),
            runtime=runtime,
            output_factory=lambda event, output_ledger, guard: output(guard),
            clock=self.fixture.clock,
        )
        return bridge, runtime, requests, output

    async def test_request_factory_advertises_response_profiles_only_when_enabled(
        self,
    ) -> None:
        connector = _Connector(self.request.connector_result)
        default_factory = AstrBotRuntimeRequestFactory(
            connector,
            self.call.budget,
            "policy-v1",
            clock=lambda: NOW,
        )
        enabled_factory = AstrBotRuntimeRequestFactory(
            connector,
            self.call.budget,
            "policy-v1",
            response_profiles_enabled=True,
            clock=lambda: NOW,
        )

        default_request, _ = await default_factory.prepare(
            object(), control_revision="rollout-v1", timeout_seconds=10
        )
        enabled_request, _ = await enabled_factory.prepare(
            object(), control_revision="rollout-v1", timeout_seconds=10
        )
        tools_request, _ = await default_factory.prepare(
            object(),
            control_revision="rollout-v1",
            timeout_seconds=10,
            tools_enabled=True,
        )
        proactive_request, _ = await enabled_factory.prepare(
            object(),
            control_revision="rollout-v1",
            timeout_seconds=10,
            tools_enabled=True,
            memory_enabled=True,
            proactive_group_participation=True,
        )

        self.assertEqual(
            dict(default_request.options.feature_flags),
            {"tools": False, "memory": False},
        )
        self.assertEqual(
            dict(enabled_request.options.feature_flags),
            {"tools": False, "memory": False, "response_profiles": True},
        )
        self.assertEqual(
            dict(tools_request.options.feature_flags),
            {"tools": True, "memory": False},
        )
        self.assertEqual(
            proactive_request.options.entrypoint_id, "astrbot_proactive_talk"
        )
        self.assertFalse(proactive_request.options.feature_flags["tools"])
        self.assertFalse(proactive_request.options.feature_flags["memory"])
        self.assertTrue(
            proactive_request.options.feature_flags["proactive_group_participation"]
        )
        self.assertTrue(
            proactive_request.options.feature_flags["response_profile.force_short"]
        )

    async def test_request_factory_projects_exact_scope_capability_policy(self) -> None:
        message = self.request.connector_result.message
        account_id = f"qq-{message.bot_id}"
        conversation_id = f"{account_id}:group:{message.group_id}"
        policy_path = Path(self.temp.name) / "agent-policies.json"
        policy_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "policies": {
                        "target": {
                            "scope": {
                                "accountId": account_id,
                                "conversationId": conversation_id,
                            },
                            "enabled": True,
                            "plugins": {
                                "icourse.read": "on",
                                "ustc.academic.read": "off",
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        factory = AstrBotRuntimeRequestFactory(
            _Connector(self.request.connector_result),
            self.call.budget,
            "policy-v1",
            scope_policy_resolver=FileScopeAgentPolicyResolver(policy_path),
            clock=lambda: NOW,
        )

        request, _ = await factory.prepare(
            object(),
            control_revision="rollout-v1",
            timeout_seconds=10,
            tools_enabled=True,
        )

        self.assertTrue(request.options.feature_flags["scope_agent_enabled"])
        self.assertTrue(
            request.options.feature_flags["capability.category.campus.course-review"]
        )
        self.assertFalse(
            request.options.feature_flags["capability.category.campus.academic"]
        )
        self.assertTrue(request.options.feature_flags["tools"])

    async def test_scope_disabled_never_claims_or_stops_event(self) -> None:
        self.request, self.call = self.fixture.start(
            feature_flags={"scope_agent_enabled": False}
        )
        config = control(allowlisted_group_ids=frozenset({self.group_id}))
        bridge, runtime, requests, output = self._bridge(config)
        event = _Event()

        result = await bridge.handle(event)

        self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
        self.assertEqual(result.reason_code, "scope_agent_disabled")
        self.assertFalse(event.stopped)
        self.assertEqual(requests.calls, 1)
        self.assertEqual(runtime.run_calls, 0)
        self.assertEqual(output.send_calls, 0)
        await bridge.close()

    async def test_preview_runs_runtime_without_claim_or_output(self) -> None:
        config = control(allowlisted_group_ids=frozenset({self.group_id}))
        bridge, runtime, requests, output = self._bridge(config)
        event = _Event()
        self.fixture.clock.now += timedelta(seconds=1)

        result = await bridge.preview(event)

        self.assertEqual(result.runtime_result.run_id, self.call.run_id)
        self.assertEqual(result.completion.run_id, self.call.run_id)
        self.assertEqual(result.tool_calls, 0)
        self.assertEqual(requests.calls, 1)
        self.assertEqual(runtime.run_calls, 1)
        self.assertEqual(runtime.ack_calls, 1)
        self.assertEqual(output.send_calls, 0)
        self.assertFalse(event.stopped)
        await bridge.close()

    async def test_off_and_shadow_leave_legacy_and_event_ownership_untouched(
        self,
    ) -> None:
        off_bridge, off_runtime, off_requests, _ = self._bridge(
            control(RolloutMode.OFF)
        )
        off_event = _Event()
        off = await off_bridge.handle(off_event)
        self.assertIs(off.action, AstrBotBridgeAction.LEGACY)
        self.assertTrue(off.legacy_owner)
        self.assertFalse(off_event.stopped)
        self.assertEqual(off_requests.calls, 0)
        self.assertEqual(off_runtime.run_calls, 0)

        shadow_config = control(
            RolloutMode.SHADOW,
            delivery_enabled=False,
            allowlisted_group_ids=frozenset({self.group_id}),
        )
        shadow_bridge, shadow_runtime, shadow_requests, _ = self._bridge(shadow_config)
        shadow_event = _Event()
        shadow = await shadow_bridge.handle(shadow_event)
        await shadow_bridge.close()
        self.assertIs(shadow.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        self.assertTrue(shadow.legacy_owner)
        self.assertFalse(shadow_event.stopped)
        self.assertEqual(shadow_requests.calls, 1)
        self.assertEqual(shadow_runtime.run_calls, 1)
        await off_bridge.close()

    async def test_canary_stops_before_legacy_target_talk_and_replay_never_sends(
        self,
    ) -> None:
        config = control(allowlisted_group_ids=frozenset({self.group_id}))
        bridge, runtime, _, output = self._bridge(config)
        first_event = _Event()

        first = await bridge.handle(first_event)
        target_talk_calls = 0
        if not first_event.stopped:
            target_talk_calls += 1

        second_event = _Event()
        second = await bridge.handle(second_event)
        if not second_event.stopped:
            target_talk_calls += 1

        self.assertIs(first.action, AstrBotBridgeAction.CANARY_COMPLETED)
        self.assertIs(second.action, AstrBotBridgeAction.CANARY_REPLAY)
        self.assertTrue(first.runtime_owner)
        self.assertFalse(first.legacy_owner)
        self.assertEqual(first_event.stop_calls, 1)
        self.assertEqual(second_event.stop_calls, 1)
        self.assertEqual(target_talk_calls, 0)
        self.assertEqual(runtime.run_calls, 1)
        self.assertEqual(output.send_calls, 1)
        await bridge.close()

    async def test_non_allowlisted_group_never_claims_or_stops(self) -> None:
        config = control(allowlisted_group_ids=frozenset({"other-group"}))
        bridge, runtime, requests, output = self._bridge(config)
        event = _Event()

        result = await bridge.handle(event)

        self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
        self.assertFalse(event.stopped)
        self.assertEqual(requests.calls, 1)
        self.assertEqual(runtime.run_calls, 0)
        self.assertEqual(output.send_calls, 0)
        await bridge.close()

    async def test_all_groups_scope_claims_without_enumerating_group_ids(self) -> None:
        config = control(allowlisted_group_ids=frozenset({"*"}))
        bridge, runtime, _, output = self._bridge(config)
        event = _Event()

        result = await bridge.handle(event)

        self.assertIs(result.action, AstrBotBridgeAction.CANARY_COMPLETED)
        self.assertTrue(event.stopped)
        self.assertEqual(runtime.run_calls, 1)
        self.assertEqual(output.send_calls, 1)
        await bridge.close()

    async def test_uncertain_claim_suppresses_legacy_without_running_or_sending(
        self,
    ) -> None:
        config = control(allowlisted_group_ids=frozenset({self.group_id}))
        bridge, runtime, _, output = self._bridge(config)
        event = _Event()

        def fail_claim(*args, **kwargs):
            raise RuntimeError("injected commit outcome loss")

        bridge._canary.claim = fail_claim
        result = await bridge.handle(event)

        self.assertIs(result.action, AstrBotBridgeAction.CANARY_FAILED)
        self.assertTrue(result.runtime_owner)
        self.assertFalse(result.legacy_owner)
        self.assertTrue(event.stopped)
        self.assertEqual(runtime.run_calls, 0)
        self.assertEqual(output.send_calls, 0)
        await bridge.close()


if __name__ == "__main__":
    unittest.main()
