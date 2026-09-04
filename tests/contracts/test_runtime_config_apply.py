from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot_plugin_dududa_core.runtime_admission import tracked_runtime_call
from astrbot_plugin_dududa_core.runtime_config_apply import (
    RuntimeApplyError,
    RuntimeConfigApplyService,
    _write_private,
)

from tests.test_apply_deepseek_runtime import DeepSeekRuntimeMigrationTests


class Bridge:
    def __init__(self):
        self._active_configuration_calls = 0
        self._shadow = SimpleNamespace(active_count=0)
        self.paused = False
        self.close = AsyncMock()

    def pause_configuration(self):
        if self._active_configuration_calls or self._shadow.active_count:
            return False
        self.paused = True
        return True

    def resume_configuration(self):
        self.paused = False


class RuntimeConfigurationApplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixture = DeepSeekRuntimeMigrationTests()
        fixture.setUp()
        self.snapshot = fixture.snapshot
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.command_path, self.core_path = root / "cmd_config.json", root / "core.json"
        self.evidence_path = root / "evidence.json"
        core = {
            **fixture.core,
            "runtime_provider_evidence_path": str(self.evidence_path),
            "runtime_allow_provider_retention": True,
        }
        for path, value in (
            (self.command_path, fixture.command),
            (self.core_path, core),
            (self.evidence_path, {"providers": []}),
        ):
            _write_private(path, value)
        self.old_bridge = Bridge()
        self.old_assembly = SimpleNamespace(ready=True, close=AsyncMock())
        self.global_provider = SimpleNamespace(
            client=SimpleNamespace(close=AsyncMock())
        )
        self.proactive = SimpleNamespace(
            _bridge=self.old_bridge,
            _in_flight=set(),
            _last_attempt={"group": 123},
            _sent_at={"group": [123]},
        )
        self.plugin = SimpleNamespace(
            config=core,
            rollout_bridge=self.old_bridge,
            runtime_assembly=self.old_assembly,
            proactive_talk=self.proactive,
            context=SimpleNamespace(get_provider_by_id=lambda _: self.global_provider),
        )
        self.candidates = []

        async def prepare(plugin, command, config, snapshot, evidence):
            candidate = SimpleNamespace(
                plugin=SimpleNamespace(
                    config=config,
                    rollout_bridge=Bridge(),
                    runtime_assembly=SimpleNamespace(ready=True, close=AsyncMock()),
                    proactive_talk=None,
                ),
                providers={
                    "owned": SimpleNamespace(client=SimpleNamespace(close=AsyncMock()))
                },
                evidence=evidence,
            )
            self.candidates.append(candidate)
            return candidate

        self.prepare = AsyncMock(side_effect=prepare)
        self.service = RuntimeConfigApplyService(
            self.plugin,
            snapshot_loader=lambda: self.snapshot,
            prepare=self.prepare,
            command_path=self.command_path,
            core_path=self.core_path,
        )
        self.patch_health = patch(
            "astrbot_plugin_dududa_core.composition._start_model_health_refresh"
        )
        self.patch_publish = patch(
            "astrbot_plugin_dududa_core.composition._publish_runtime_status"
        )
        self.patch_host = patch(
            "astrbot_plugin_dududa_core.runtime_config_apply._sync_host_configuration"
        )
        self.patch_health.start()
        self.patch_publish.start()
        self.patch_host.start()
        self.addCleanup(self.patch_health.stop)
        self.addCleanup(self.patch_publish.stop)
        self.addCleanup(self.patch_host.stop)

    async def test_applies_real_generation_preserves_global_and_proactive_limits(self):
        result = await self.service.apply(self.snapshot.revision)
        self.assertEqual(result["status"], "applied")
        self.assertIs(self.plugin.proactive_talk, self.proactive)
        self.assertIs(self.proactive._bridge, self.plugin.rollout_bridge)
        self.assertEqual(self.proactive._sent_at, {"group": [123]})
        self.global_provider.client.close.assert_not_called()
        self.old_assembly.close.assert_awaited_once()
        self.assertEqual(self.command_path.stat().st_mode & 0o777, 0o600)
        first = self.candidates[0].providers["owned"]
        await self.service.apply(self.snapshot.revision)
        first.client.close.assert_awaited_once()
        self.global_provider.client.close.assert_not_called()
        self.assertEqual(len(self.service.providers), 1)

    async def test_revision_and_active_calls_refused_without_probe(self):
        with self.assertRaisesRegex(RuntimeApplyError, "pool_revision_changed"):
            await self.service.apply(-1)
        for target, field, value in (
            (self.old_bridge, "_active_configuration_calls", 1),
            (self.old_bridge._shadow, "active_count", 1),
            (self.proactive, "_in_flight", {"group"}),
        ):
            previous = getattr(target, field)
            setattr(target, field, value)
            with self.assertRaisesRegex(RuntimeApplyError, "runtime_requests_active"):
                await self.service.apply(self.snapshot.revision)
            setattr(target, field, previous)
        self.prepare.assert_not_called()

    async def test_concurrent_apply_and_late_revision_change(self):
        started, release = asyncio.Event(), asyncio.Event()
        original = self.prepare.side_effect

        async def prepare(*args):
            started.set()
            await release.wait()
            return await original(*args)

        self.prepare.side_effect = prepare
        first = asyncio.create_task(self.service.apply(self.snapshot.revision))
        await started.wait()
        self.assertEqual(self.service.status()["status"], "applying")
        with self.assertRaisesRegex(RuntimeApplyError, "runtime_apply_in_progress"):
            await self.service.apply(self.snapshot.revision)
        self.snapshot = replace(self.snapshot, revision=999)
        release.set()
        with self.assertRaisesRegex(RuntimeApplyError, "pool_revision_changed"):
            await first
        self.assertIs(self.plugin.rollout_bridge, self.old_bridge)
        self.old_assembly.close.assert_not_called()
        self.candidates[0].providers["owned"].client.close.assert_awaited_once()

    async def test_failed_write_rolls_back_and_keeps_old_runtime(self):
        before = {
            path: path.read_text()
            for path in (self.command_path, self.core_path, self.evidence_path)
        }
        failed = False

        def writer(path, value):
            nonlocal failed
            if path == self.core_path and not failed:
                failed = True
                raise OSError("synthetic-credential-must-not-leak")
            _write_private(path, value)

        self.service.writer = writer
        with self.assertRaisesRegex(RuntimeApplyError, "runtime_apply_failed"):
            await self.service.apply(self.snapshot.revision)
        self.assertEqual(before, {path: path.read_text() for path in before})
        self.assertIs(self.plugin.rollout_bridge, self.old_bridge)
        self.assertFalse(self.old_bridge.paused)
        self.assertNotIn("synthetic-credential", json.dumps(self.service.status()))

    async def test_health_only_revision_is_current_but_key_rotation_is_pending(self):
        await self.service.apply(self.snapshot.revision)
        self.snapshot = replace(self.snapshot, revision=999)
        self.assertEqual(self.service.status()["status"], "applied")
        pool = self.snapshot.pools[0]
        keys = tuple(
            replace(key, secret="synthetic-rotated") if key.enabled else key
            for key in pool.keys
        )
        self.snapshot = replace(
            self.snapshot, pools=(replace(pool, keys=keys), *self.snapshot.pools[1:])
        )
        self.assertEqual(self.service.status()["status"], "pending")
        self.assertNotIn("synthetic-rotated", json.dumps(self.service.status()))

    async def test_late_activity_abandons_candidate_without_closing_old_clients(self):
        original = self.prepare.side_effect

        async def prepare(*args):
            candidate = await original(*args)
            self.old_bridge._active_configuration_calls = 1
            return candidate

        self.prepare.side_effect = prepare
        with self.assertRaisesRegex(RuntimeApplyError, "runtime_requests_active"):
            await self.service.apply(self.snapshot.revision)
        self.old_assembly.close.assert_not_called()
        self.assertIs(self.plugin.rollout_bridge, self.old_bridge)

    async def test_tracking_spans_wait_and_cancellation(self):
        entered = asyncio.Event()

        class Tracked:
            @tracked_runtime_call
            async def preview(self):
                entered.set()
                await asyncio.Event().wait()

        target = Tracked()
        task = asyncio.create_task(target.preview())
        await entered.wait()
        self.assertEqual(target._active_configuration_calls, 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(target._active_configuration_calls, 0)

    async def test_private_last_good_and_cleanup_warning(self):
        before = json.loads(self.command_path.read_text())
        self.old_assembly.close.side_effect = RuntimeError("synthetic-cleanup-failure")
        result = await self.service.apply(self.snapshot.revision)
        self.assertEqual(result["status"], "applied")
        self.assertTrue(result["cleanupPending"])
        backup = self.command_path.parent / "private" / "dududa-runtime-last-good"
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual((backup / "command.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((backup / "command.json").read_text()), before)
        self.old_assembly.close.side_effect = None
        await self.service.close()
        self.assertFalse(self.service.pending_cleanup)

    async def test_shutdown_prevents_late_candidate_resurrection(self):
        started, release = asyncio.Event(), asyncio.Event()
        original = self.prepare.side_effect

        async def prepare(*args):
            started.set()
            await release.wait()
            return await original(*args)

        self.prepare.side_effect = prepare
        apply_task = asyncio.create_task(self.service.apply(self.snapshot.revision))
        await started.wait()
        shutdown = asyncio.create_task(self.service.begin_shutdown())
        await asyncio.sleep(0)
        release.set()
        with self.assertRaisesRegex(RuntimeApplyError, "runtime_shutting_down"):
            await apply_task
        await shutdown
        self.assertIs(self.plugin.runtime_assembly, self.old_assembly)
        self.candidates[0].providers["owned"].client.close.assert_awaited_once()
        with self.assertRaisesRegex(RuntimeApplyError, "runtime_shutting_down"):
            await self.service.apply(self.snapshot.revision)
