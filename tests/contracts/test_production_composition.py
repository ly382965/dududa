from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot_plugin_dududa_core import audit, composition, config
from astrbot_plugin_dududa_core.adapters.model import (
    AstrBotProviderBindingEvidence,
)
from astrbot_plugin_dududa_core.composition import (
    ProductionRuntimeAssembly,
    install_production_runtime,
    unavailable_runtime_assembly,
)
from astrbot_plugin_dududa_core.lifecycle import CoreLifecycleMixin
from astrbot_plugin_dududa_core.rollout_bridge import AstrBotBridgeAction
from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.models.contracts import (
    EndpointHealthStatus,
    ModelEndpointHealth,
    ModelProviderDescriptor,
    ModelProviderHealth,
)
from dududa.models.health import ModelHealthEvidence
from dududa.rollout import InMemoryRolloutMetrics, RolloutMode, SQLiteJournalMode

from tests.unit.rollout.helpers import control, ledger
from tests.unit.rollout.test_controlled_execution import (
    _MutableControls,
    _RuntimeProxy,
)
from tests.unit.runtime.test_orchestrator import OrchestratorFixture


class _Plugin(CoreLifecycleMixin):
    pass


class _ProviderContext:
    def __init__(
        self,
        providers: dict[str, object],
        *,
        evidence_enabled: bool = True,
    ) -> None:
        self.providers = dict(providers)
        self.evidence_enabled = evidence_enabled

    def get_provider_by_id(self, provider_id: str) -> object | None:
        return self.providers.get(provider_id)

    def resolve_dududa_model_provider_evidence(
        self,
        astrbot_provider_id: str,
        descriptor: ModelProviderDescriptor,
    ) -> AstrBotProviderBindingEvidence | None:
        if not self.evidence_enabled:
            return None
        endpoint = descriptor.endpoints[0]
        return AstrBotProviderBindingEvidence(
            schema_version=1,
            astrbot_provider_id=astrbot_provider_id,
            host_version="astrbot-test",
            conformance_revision=ComponentRevision(
                "astrbot-provider-conformance",
                "1.0.0",
                "test-v1",
                DigestString("builtin:astrbot-provider-conformance"),
            ),
            verified_model_id=endpoint.model_id,
            verified_max_output_tokens=endpoint.capabilities.max_output_tokens,
            verified_data_residencies=endpoint.available_data_residencies,
            verified_retention_modes=endpoint.supported_retention_modes,
            single_request_verified=True,
            model_binding_verified=True,
            output_limit_verified=True,
            residency_verified=True,
            retention_verified=True,
            sanitized_logging_verified=True,
            deadline_enforcement_verified=True,
            cancellation_enforcement_verified=True,
        )


class _ProviderRegistryContext:
    def __init__(self, providers: dict[str, object]) -> None:
        self.providers = dict(providers)

    def get_provider_by_id(self, provider_id: str) -> object | None:
        return self.providers.get(provider_id)


class _AstrBotProvider:
    def __init__(self, provider_id: str = "astrbot-luna") -> None:
        self.provider_id = provider_id
        self.calls: list[dict[str, object]] = []

    def meta(self) -> object:
        return SimpleNamespace(id=self.provider_id)

    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            completion_text="这是来自生产 Runtime 的影子回答。",
            usage=SimpleNamespace(input_other=12, input_cached=0, output=8),
        )


class _BlockingAstrBotProvider(_AstrBotProvider):
    def __init__(self, provider_id: str = "astrbot-luna") -> None:
        super().__init__(provider_id)
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def text_chat(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.cancelled.set()


class At:
    def __init__(self, qq: str) -> None:
        self.qq = qq
        self.name = None


class _Event:
    def __init__(
        self,
        *,
        group_id: str = "group-1",
        message_id: str = "message-1",
    ) -> None:
        self.stop_calls = 0
        self.send_calls = 0
        self.message_str = "@嘟嘟哒 你好"
        self.message_obj = SimpleNamespace(
            message_id=message_id,
            timestamp=1_786_723_200,
            message=[At("bot-1")],
            raw_message={"time": 1_786_723_200, "message": []},
        )
        self._group_id = group_id

    def stop_event(self) -> None:
        self.stop_calls += 1

    def get_platform_id(self) -> str:
        return "qq-adapter-1"

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def get_self_id(self) -> str:
        return "bot-1"

    def get_sender_id(self) -> str:
        return "user-1"

    def get_group_id(self) -> str:
        return self._group_id

    def get_message_type(self) -> str:
        return "group"

    def get_messages(self) -> list[object]:
        return list(self.message_obj.message)

    def is_admin(self) -> bool:
        return False

    async def send(self, chain: object) -> None:
        self.send_calls += 1


class _Closeable:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class _FailOnceCloseable(_Closeable):
    async def close(self) -> None:
        self.close_calls += 1
        if self.close_calls == 1:
            raise RuntimeError("transient close failure")


class _MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class ProductionCompositionContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "rollout.sqlite3"
        self.fixture = OrchestratorFixture()
        _, self.call = self.fixture.start()

    def tearDown(self) -> None:
        self.temp.cleanup()

    async def _wait_until(self, predicate, *, timeout: float = 1.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate():
            if loop.time() >= deadline:
                self.fail("condition was not reached before timeout")
            await asyncio.sleep(0.002)

    def _plugin(self, mode: RolloutMode = RolloutMode.OFF) -> _Plugin:
        plugin = _Plugin()
        plugin.rollout_ledger = ledger(self.path)
        plugin.rollout_controls = _MutableControls(control(mode))
        plugin.rollout_metrics = InMemoryRolloutMetrics()
        plugin.rollout_bridge = None
        plugin.runtime_assembly = None
        plugin._dududa_runtime_cleanup_assemblies = []
        return plugin

    def _production_plugin(
        self,
        provider: _AstrBotProvider | None = None,
        *,
        evidence_enabled: bool = True,
    ) -> _Plugin:
        plugin = _Plugin()
        plugin.context = _ProviderContext(
            {provider.provider_id: provider} if provider is not None else {},
            evidence_enabled=evidence_enabled,
        )
        return plugin

    def _runtime_config(
        self,
        *,
        astrbot_provider_id: str = "astrbot-luna",
        rollout_mode: str = "off",
    ) -> dict[str, object]:
        return {
            "runtime_enabled": True,
            "runtime_models_json": json.dumps(
                [
                    {
                        "provider_id": "openai-luna",
                        "astrbot_provider_id": astrbot_provider_id,
                        "endpoint_id": "luna",
                        "model_id": "gpt-5.6-luna",
                        "tier": "haiku",
                        "reasoning_depth": "light",
                        "max_context_tokens": 128_000,
                        "max_output_tokens": 4_096,
                        "max_concurrency": 4,
                        "rpm_limit": 60,
                        "tpm_limit": 100_000,
                    }
                ]
            ),
            "runtime_response_profiles_enabled": True,
            "rollout_mode": rollout_mode,
            "rollout_revision": f"rollout-{rollout_mode}-test-v1",
            "rollout_delivery_enabled": False,
            "rollout_allowlisted_groups": ["group-1"],
            "rollout_kill_switch": rollout_mode != "shadow",
            "rollout_tools_enabled": False,
            "rollout_memory_enabled": False,
        }

    def _provider_evidence_path(
        self,
        *,
        model_id: str = "gpt-5.6-luna",
    ) -> Path:
        path = Path(self.temp.name) / f"provider-evidence-{model_id}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "providers": [
                        {
                            "schema_version": 1,
                            "astrbot_provider_id": "astrbot-luna",
                            "host_version": "astrbot-test",
                            "conformance_revision": {
                                "component_id": "astrbot-provider-conformance",
                                "implementation_version": "1.0.0",
                                "config_revision": "private-test-v1",
                                "artifact_digest": "private:astrbot-luna-v1",
                            },
                            "verified_model_id": model_id,
                            "verified_max_output_tokens": 4_096,
                            "verified_data_residencies": ["global"],
                            "verified_retention_modes": ["no_retention"],
                            "single_request_verified": True,
                            "model_binding_verified": True,
                            "output_limit_verified": True,
                            "residency_verified": True,
                            "retention_verified": True,
                            "sanitized_logging_verified": True,
                            "deadline_enforcement_verified": True,
                            "cancellation_enforcement_verified": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _healthy_evidence(
        assembly: ProductionRuntimeAssembly,
        observed_at: datetime,
        *,
        ttl: timedelta = timedelta(seconds=5),
    ) -> ModelHealthEvidence:
        registry = assembly.model_operational_registry
        if registry is None:
            raise AssertionError("model operational registry is unavailable")
        initial = registry.acquire_snapshot()
        provider = initial.provider_health[0]
        endpoint = provider.endpoints[0]
        health = ModelProviderHealth(
            schema_version=1,
            provider_id=provider.provider_id,
            status=EndpointHealthStatus.HEALTHY,
            endpoints=(
                ModelEndpointHealth(
                    schema_version=1,
                    endpoint_id=endpoint.endpoint_id,
                    endpoint_descriptor_digest=endpoint.endpoint_descriptor_digest,
                    status=EndpointHealthStatus.HEALTHY,
                    reason_codes=(),
                ),
            ),
            snapshot_revision="astrbot-preflight-test-v1",
            checked_at=observed_at,
            reason_codes=(),
        )
        return ModelHealthEvidence(
            schema_version=1,
            provider_revision=composition._revision(
                f"model-provider:{provider.provider_id}"
            ),
            health=health,
            expires_at=observed_at + ttl,
            evidence_revision="astrbot-preflight-test-v1",
        )

    def _initialize(
        self,
        plugin: _Plugin,
        values: dict[str, object],
        directory: str,
        *,
        runtime_assembly: ProductionRuntimeAssembly | None = None,
    ) -> None:
        root = Path(self.temp.name) / directory
        with (
            patch.object(config, "PLUGIN_DATA_DIR", root),
            patch.object(config, "PLUGIN_CONFIG_PATH", root / "config.json"),
            patch.object(config, "ASTRBOT_CONFIG_PATH", root / "astrbot.json"),
            patch.object(composition, "PLUGIN_DATA_DIR", root),
            patch.object(composition, "ROLLOUT_LEDGER_PATH", root / "rollout.sqlite3"),
            patch.object(composition, "MCP_REGISTRY_DIR", root / "missing-registry"),
            patch.object(composition, "MCP_WORKER_PYTHON", root / "missing-worker"),
            patch.object(audit, "PLUGIN_DATA_DIR", root),
        ):
            composition.initialize_plugin(
                plugin,
                values,
                runtime_assembly=runtime_assembly,
            )

    async def test_builder_accepts_private_provider_evidence_file(self) -> None:
        provider = _AstrBotProvider()
        plugin = _Plugin()
        plugin.context = _ProviderRegistryContext({provider.provider_id: provider})
        values = self._runtime_config()
        values["runtime_provider_evidence_path"] = str(self._provider_evidence_path())

        assembly = composition.build_production_runtime(
            plugin,
            values,
        )

        self.assertTrue(assembly.ready)
        self.assertIsNotNone(assembly.model_operational_registry)
        snapshot = assembly.model_operational_registry.acquire_snapshot()
        self.assertIs(
            snapshot.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertIs(
            snapshot.provider_health[0].endpoints[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertEqual(provider.calls, [])
        await assembly.close()

    async def test_builder_rejects_mismatched_private_provider_evidence(self) -> None:
        provider = _AstrBotProvider()
        plugin = _Plugin()
        plugin.context = _ProviderRegistryContext({provider.provider_id: provider})
        values = self._runtime_config()
        values["runtime_provider_evidence_path"] = str(
            self._provider_evidence_path(model_id="gpt-5.6-terra")
        )

        with self.assertRaisesRegex(
            ValueError,
            "provider conformance evidence is unavailable",
        ):
            composition.build_production_runtime(plugin, values)

    async def test_enabled_health_probe_publishes_and_periodically_refreshes(
        self,
    ) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        values = self._runtime_config()
        values.update(
            {
                "runtime_health_probe_enabled": True,
                "runtime_health_probe_interval_seconds": 0.01,
                "runtime_health_probe_timeout_seconds": 0.1,
                "runtime_health_evidence_ttl_seconds": 0.2,
            }
        )

        self._initialize(plugin, values, "production-health-refresh")
        await self._wait_until(lambda: len(provider.calls) >= 2)

        snapshot = plugin.runtime_assembly.model_operational_registry.acquire_snapshot()
        self.assertIs(
            snapshot.provider_health[0].status,
            EndpointHealthStatus.HEALTHY,
        )
        self.assertEqual(provider.calls[0]["model"], "gpt-5.6-luna")
        self.assertEqual(provider.calls[0]["max_tokens"], 8)
        self.assertEqual(provider.calls[0]["request_max_retries"], 0)
        self.assertNotIn("reasoning_effort", provider.calls[0])

        await plugin.terminate()
        calls_after_close = len(provider.calls)
        await asyncio.sleep(0.02)
        self.assertEqual(len(provider.calls), calls_after_close)
        self.assertIsNone(plugin._dududa_model_health_task)

    async def test_timed_out_health_probe_publishes_unknown(self) -> None:
        provider = _BlockingAstrBotProvider()
        plugin = self._production_plugin(provider)
        values = self._runtime_config()
        values.update(
            {
                "runtime_health_probe_enabled": True,
                "runtime_health_probe_interval_seconds": 60,
                "runtime_health_probe_timeout_seconds": 0.01,
                "runtime_health_evidence_ttl_seconds": 1,
            }
        )

        self._initialize(plugin, values, "production-health-timeout")
        await self._wait_until(provider.cancelled.is_set)
        await self._wait_until(
            lambda: (
                plugin.runtime_assembly.model_operational_registry.acquire_snapshot()
                .provider_health[0]
                .reason_codes
                == ("health_probe_failed",)
            )
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["request_max_retries"], 0)
        await plugin.terminate()

    async def test_health_probe_without_running_loop_stays_unknown(self) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        values = self._runtime_config()
        self._initialize(plugin, values, "production-health-no-loop")
        plugin.config["runtime_health_probe_enabled"] = True

        with patch.object(
            composition.asyncio,
            "get_running_loop",
            side_effect=RuntimeError,
        ):
            composition._start_model_health_refresh(plugin)

        snapshot = plugin.runtime_assembly.model_operational_registry.acquire_snapshot()
        self.assertIs(
            snapshot.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertEqual(provider.calls, [])
        self.assertIsNone(plugin._dududa_model_health_task)
        await plugin.terminate()

    async def test_auto_assembled_off_runtime_never_calls_provider(self) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        self._initialize(plugin, self._runtime_config(), "production-off")

        event = _Event()
        result = await plugin.rollout_bridge.handle(event)

        self.assertTrue(plugin.runtime_assembly.ready)
        self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
        self.assertEqual(result.reason_code, "rollout_not_active")
        self.assertEqual(provider.calls, [])
        self.assertEqual(event.stop_calls, 0)
        self.assertEqual(event.send_calls, 0)
        await plugin.terminate()

    async def test_auto_assembled_shadow_with_unknown_health_does_not_call_or_send(
        self,
    ) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        self._initialize(
            plugin,
            self._runtime_config(rollout_mode="shadow"),
            "production-shadow",
        )

        event = _Event()
        result = await plugin.rollout_bridge.handle(event)
        await plugin.rollout_bridge.close()

        self.assertTrue(plugin.runtime_assembly.ready)
        self.assertIs(result.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        self.assertTrue(result.legacy_owner)
        self.assertFalse(result.runtime_owner)
        self.assertEqual(provider.calls, [])
        self.assertEqual(event.stop_calls, 0)
        self.assertEqual(event.send_calls, 0)
        await plugin.terminate()

    async def test_shadow_uses_endpoint_fixed_reasoning_after_healthy_evidence(
        self,
    ) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        observed_at = datetime.now(timezone.utc)
        clock = _MutableClock(observed_at)
        assembly = composition.build_production_runtime(
            plugin,
            self._runtime_config(rollout_mode="shadow"),
            clock=clock,
        )
        await assembly.publish_model_health(
            (self._healthy_evidence(assembly, observed_at),),
            call=replace(
                self.call,
                deadline=observed_at + timedelta(minutes=1),
            ),
        )
        self._initialize(
            plugin,
            self._runtime_config(rollout_mode="shadow"),
            "production-shadow-healthy",
            runtime_assembly=assembly,
        )

        event = _Event()
        result = await plugin.rollout_bridge.handle(event)
        await plugin.rollout_bridge.close()

        self.assertIs(result.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["reasoning_effort"], "low")
        self.assertEqual(event.stop_calls, 0)
        self.assertEqual(event.send_calls, 0)
        await plugin.terminate()

    async def test_shadow_stops_calling_provider_after_health_ttl(self) -> None:
        provider = _AstrBotProvider()
        plugin = self._production_plugin(provider)
        observed_at = datetime.now(timezone.utc)
        clock = _MutableClock(observed_at)
        values = self._runtime_config(rollout_mode="shadow")
        assembly = composition.build_production_runtime(
            plugin,
            values,
            clock=clock,
        )
        await assembly.publish_model_health(
            (self._healthy_evidence(assembly, observed_at),),
            call=replace(
                self.call,
                deadline=observed_at + timedelta(minutes=1),
            ),
        )
        self._initialize(
            plugin,
            values,
            "production-shadow-health-ttl",
            runtime_assembly=assembly,
        )

        first = await plugin.rollout_bridge.handle(_Event(message_id="healthy"))
        await plugin.rollout_bridge._shadow.drain()
        self.assertIs(first.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        self.assertEqual(len(provider.calls), 1)

        clock.now = observed_at + timedelta(seconds=6)
        snapshot = assembly.model_operational_registry.acquire_snapshot()
        self.assertIs(
            snapshot.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        second = await plugin.rollout_bridge.handle(_Event(message_id="expired"))
        await plugin.rollout_bridge.close()

        self.assertIs(second.action, AstrBotBridgeAction.SHADOW_SCHEDULED)
        self.assertEqual(len(provider.calls), 1)
        await plugin.terminate()

    async def test_missing_or_unknown_provider_falls_back_to_legacy(self) -> None:
        cases = {
            "runtime-disabled": (None, True, {}),
            "unknown-provider": (
                None,
                True,
                self._runtime_config(astrbot_provider_id="missing-provider"),
            ),
            "missing-evidence": (
                _AstrBotProvider(),
                False,
                self._runtime_config(),
            ),
        }
        for name, (provider, evidence_enabled, values) in cases.items():
            with self.subTest(name=name):
                plugin = self._production_plugin(
                    provider,
                    evidence_enabled=evidence_enabled,
                )
                self._initialize(plugin, values, name)

                event = _Event()
                result = await plugin.rollout_bridge.handle(event)

                self.assertFalse(plugin.runtime_assembly.ready)
                self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
                self.assertEqual(event.stop_calls, 0)
                self.assertEqual(event.send_calls, 0)
                await plugin.terminate()

    async def test_unavailable_default_never_reads_or_claims_an_event(self) -> None:
        plugin = self._plugin(RolloutMode.CANARY)
        assembly = unavailable_runtime_assembly()
        bridge = install_production_runtime(
            plugin,
            assembly,
            self.call.budget,
            "policy-v1",
        )
        self.assertIsNotNone(bridge)

        event = _Event()
        result = await bridge.handle(event)

        self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
        self.assertEqual(result.reason_code, "rollout_runtime_unavailable")
        self.assertEqual(event.stop_calls, 0)
        self.assertEqual(plugin.rollout_ledger.recover_incomplete(), ())
        await plugin.terminate()

    async def test_plugin_initialization_installs_one_default_off_bridge(self) -> None:
        root = Path(self.temp.name) / "plugin-data"
        plugin = _Plugin()
        with (
            patch.object(config, "PLUGIN_DATA_DIR", root),
            patch.object(config, "PLUGIN_CONFIG_PATH", root / "config.json"),
            patch.object(config, "ASTRBOT_CONFIG_PATH", root / "astrbot.json"),
            patch.object(composition, "PLUGIN_DATA_DIR", root),
            patch.object(composition, "ROLLOUT_LEDGER_PATH", root / "rollout.sqlite3"),
            patch.object(composition, "MCP_REGISTRY_DIR", root / "missing-registry"),
            patch.object(composition, "MCP_WORKER_PYTHON", root / "missing-worker"),
            patch.object(audit, "PLUGIN_DATA_DIR", root),
        ):
            composition.initialize_plugin(plugin, {})

        self.assertIsNotNone(plugin.rollout_bridge)
        self.assertIsNotNone(plugin.runtime_assembly)
        self.assertFalse(plugin.runtime_assembly.ready)
        self.assertEqual(plugin.icourse_mode, "unavailable")
        self.assertEqual(
            plugin.icourse_reason,
            "unified_infrastructure_missing",
        )
        self.assertIs(
            plugin.rollout_ledger.config.journal_mode,
            SQLiteJournalMode.DELETE,
        )
        event = _Event()
        result = await plugin.rollout_bridge.handle(event)
        self.assertEqual(result.reason_code, "rollout_not_active")
        self.assertEqual(event.stop_calls, 0)
        await plugin.terminate()
        self.assertFalse(plugin._dududa_runtime_initialized)

    async def test_repeated_plugin_initialization_preserves_the_first_owner(
        self,
    ) -> None:
        root = Path(self.temp.name) / "plugin-repeat"
        plugin = _Plugin()
        resource = _Closeable()
        assembly = ProductionRuntimeAssembly(
            _RuntimeProxy(self.fixture.runtime),
            ready=True,
            closeables=(resource,),
        )
        with (
            patch.object(config, "PLUGIN_DATA_DIR", root),
            patch.object(config, "PLUGIN_CONFIG_PATH", root / "config.json"),
            patch.object(config, "ASTRBOT_CONFIG_PATH", root / "astrbot.json"),
            patch.object(composition, "PLUGIN_DATA_DIR", root),
            patch.object(composition, "ROLLOUT_LEDGER_PATH", root / "rollout.sqlite3"),
            patch.object(composition, "MCP_REGISTRY_DIR", root / "missing-registry"),
            patch.object(composition, "MCP_WORKER_PYTHON", root / "missing-worker"),
            patch.object(audit, "PLUGIN_DATA_DIR", root),
        ):
            composition.initialize_plugin(plugin, {}, runtime_assembly=assembly)
            original_bridge = plugin.rollout_bridge
            with self.assertRaisesRegex(RuntimeError, "already initialized"):
                composition.initialize_plugin(plugin, {})

        self.assertIs(plugin.rollout_bridge, original_bridge)
        self.assertIs(plugin.runtime_assembly, assembly)
        self.assertEqual(resource.close_calls, 0)
        await plugin.terminate()
        self.assertEqual(resource.close_calls, 1)

    async def test_disabled_plugin_never_enters_the_rollout_bridge(self) -> None:
        plugin = _Plugin()
        plugin.enabled = False
        plugin.rollout_bridge = AsyncMock()

        await plugin._handle_controlled_rollout(_Event())

        plugin.rollout_bridge.handle.assert_not_awaited()

    async def test_ready_off_composition_is_single_and_closes_once(self) -> None:
        plugin = self._plugin()
        runtime = _RuntimeProxy(self.fixture.runtime)
        resource = _Closeable()
        assembly = ProductionRuntimeAssembly(
            runtime,
            ready=True,
            closeables=(resource,),
        )
        bridge = install_production_runtime(
            plugin,
            assembly,
            self.call.budget,
            "policy-v1",
        )
        self.assertIsNotNone(bridge)

        event = _Event()
        result = await bridge.handle(event)
        self.assertIs(result.action, AstrBotBridgeAction.LEGACY)
        self.assertEqual(runtime.run_calls, 0)
        self.assertEqual(event.stop_calls, 0)
        self.assertIs(
            install_production_runtime(
                plugin,
                assembly,
                self.call.budget,
                "policy-v1",
            ),
            bridge,
        )
        self.assertFalse(assembly.aborted)

        aborted: list[str] = []
        duplicate_resource = _Closeable()
        duplicate = ProductionRuntimeAssembly(
            runtime,
            ready=True,
            closeables=(duplicate_resource,),
            abort_callbacks=(lambda: aborted.append("duplicate"),),
        )
        self.assertIs(
            install_production_runtime(
                plugin,
                duplicate,
                self.call.budget,
                "policy-v1",
            ),
            bridge,
        )
        self.assertEqual(aborted, ["duplicate"])

        await plugin.terminate()
        await plugin.terminate()
        self.assertEqual(resource.close_calls, 1)
        self.assertEqual(duplicate_resource.close_calls, 1)
        self.assertIsNone(plugin.rollout_bridge)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [])

    async def test_partial_install_aborts_and_preserves_legacy_owner(self) -> None:
        plugin = self._plugin()
        plugin.rollout_ledger = None
        aborted: list[str] = []
        assembly = ProductionRuntimeAssembly(
            _RuntimeProxy(self.fixture.runtime),
            ready=True,
            abort_callbacks=(lambda: aborted.append("partial"),),
        )

        result = install_production_runtime(
            plugin,
            assembly,
            self.call.budget,
            "policy-v1",
        )

        self.assertIsNone(result)
        self.assertEqual(aborted, ["partial"])
        self.assertTrue(assembly.aborted)
        self.assertIsNone(plugin.rollout_bridge)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [assembly])
        with self.assertRaisesRegex(RuntimeError, "not installable"):
            install_production_runtime(
                plugin,
                assembly,
                self.call.budget,
                "policy-v1",
            )
        await plugin.terminate()
        self.assertTrue(assembly.closed)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [])

    async def test_closed_assembly_cannot_be_installed(self) -> None:
        plugin = self._plugin()
        assembly = ProductionRuntimeAssembly(
            _RuntimeProxy(self.fixture.runtime),
            ready=True,
        )
        await assembly.close()

        with self.assertRaisesRegex(RuntimeError, "not installable"):
            install_production_runtime(
                plugin,
                assembly,
                self.call.budget,
                "policy-v1",
            )

    async def test_failed_abort_is_retried_during_lifecycle_cleanup(self) -> None:
        plugin = self._plugin()
        plugin.rollout_ledger = None
        calls = 0

        def abort() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transient abort failure")

        assembly = ProductionRuntimeAssembly(
            _RuntimeProxy(self.fixture.runtime),
            ready=True,
            abort_callbacks=(abort,),
        )

        self.assertIsNone(
            install_production_runtime(
                plugin,
                assembly,
                self.call.budget,
                "policy-v1",
            )
        )
        self.assertEqual(calls, 1)
        self.assertFalse(assembly.aborted)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [assembly])

        await plugin.terminate()
        self.assertEqual(calls, 2)
        self.assertTrue(assembly.aborted)
        self.assertTrue(assembly.closed)
        self.assertIsNone(plugin.runtime_assembly)
        self.assertEqual(plugin._dududa_runtime_cleanup_assemblies, [])

    async def test_termination_retries_only_resources_that_failed_to_close(
        self,
    ) -> None:
        plugin = self._plugin()
        runtime = _RuntimeProxy(self.fixture.runtime)
        closed = _Closeable()
        flaky = _FailOnceCloseable()
        assembly = ProductionRuntimeAssembly(
            runtime,
            ready=True,
            closeables=(flaky, closed),
        )
        install_production_runtime(
            plugin,
            assembly,
            self.call.budget,
            "policy-v1",
        )

        with self.assertRaisesRegex(RuntimeError, "transient close failure"):
            await plugin.terminate()
        self.assertIsNone(plugin.rollout_bridge)
        self.assertIs(plugin.runtime_assembly, assembly)
        self.assertEqual(closed.close_calls, 1)
        self.assertEqual(flaky.close_calls, 1)
        self.assertFalse(assembly.closed)

        await plugin.terminate()
        await plugin.terminate()
        self.assertEqual(closed.close_calls, 1)
        self.assertEqual(flaky.close_calls, 2)
        self.assertTrue(assembly.closed)
        self.assertIsNone(plugin.runtime_assembly)

    async def test_termination_retries_failed_icourse_close(self) -> None:
        plugin = self._plugin()
        plugin.icourse = _FailOnceCloseable()

        with self.assertRaisesRegex(RuntimeError, "transient close failure"):
            await plugin.terminate()
        self.assertIsNotNone(plugin.icourse)
        self.assertFalse(plugin._dududa_runtime_terminated)

        await plugin.terminate()
        self.assertIsNone(plugin.icourse)
        self.assertTrue(plugin._dududa_runtime_terminated)


if __name__ == "__main__":
    unittest.main()
