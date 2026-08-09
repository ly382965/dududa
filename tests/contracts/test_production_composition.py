from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from dududa.rollout import InMemoryRolloutMetrics, RolloutMode, SQLiteJournalMode
from plugins.astrbot_plugin_dududa_core import audit, composition, config
from plugins.astrbot_plugin_dududa_core.composition import (
    ProductionRuntimeAssembly,
    install_production_runtime,
    unavailable_runtime_assembly,
)
from plugins.astrbot_plugin_dududa_core.lifecycle import CoreLifecycleMixin
from plugins.astrbot_plugin_dududa_core.rollout_bridge import AstrBotBridgeAction

from tests.unit.rollout.helpers import control, ledger
from tests.unit.rollout.test_controlled_execution import (
    _MutableControls,
    _RuntimeProxy,
)
from tests.unit.runtime.test_orchestrator import OrchestratorFixture


class _Plugin(CoreLifecycleMixin):
    pass


class _Event:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop_event(self) -> None:
        self.stop_calls += 1


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


class ProductionCompositionContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "rollout.sqlite3"
        self.fixture = OrchestratorFixture()
        _, self.call = self.fixture.start()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _plugin(self, mode: RolloutMode = RolloutMode.OFF) -> _Plugin:
        plugin = _Plugin()
        plugin.rollout_ledger = ledger(self.path)
        plugin.rollout_controls = _MutableControls(control(mode))
        plugin.rollout_metrics = InMemoryRolloutMetrics()
        plugin.rollout_bridge = None
        plugin.runtime_assembly = None
        plugin._dududa_runtime_cleanup_assemblies = []
        return plugin

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
            patch.object(audit, "PLUGIN_DATA_DIR", root),
        ):
            composition.initialize_plugin(plugin, {})

        self.assertIsNotNone(plugin.rollout_bridge)
        self.assertIsNotNone(plugin.runtime_assembly)
        self.assertFalse(plugin.runtime_assembly.ready)
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

    async def test_repeated_plugin_initialization_preserves_the_first_owner(self) -> None:
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

    async def test_termination_retries_only_resources_that_failed_to_close(self) -> None:
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
