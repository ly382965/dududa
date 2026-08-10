from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.dududa_ops import (
    BackupManager,
    HealthCheck,
    HealthReport,
    OperationFailed,
    OperationsCoordinator,
    OperationsError,
    ReleaseManifest,
    ReleaseStore,
    validate_compose_contract,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)
ZERO_DIGEST = "sha256:" + "0" * 64
ONE_DIGEST = "sha256:" + "1" * 64


class RecordingDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.health_by_release: dict[str, str] = {}

    def prepare(self, manifest: ReleaseManifest) -> object:
        return self._record("prepare", manifest)

    def start(self, manifest: ReleaseManifest) -> object:
        return self._record("start", manifest)

    def health(self, manifest: ReleaseManifest) -> HealthReport:
        self.calls.append(("health", manifest.release_id))
        deployment_status = self.health_by_release.get(manifest.release_id, "healthy")
        return HealthReport.create(
            release_id=manifest.release_id,
            observed_at=NOW,
            checks=(
                HealthCheck(
                    "release-store",
                    "healthy",
                    "release-manifest-verified",
                    manifest.manifest_digest,
                ),
                HealthCheck(
                    "deployment",
                    deployment_status,
                    f"deployment-{deployment_status}",
                    ZERO_DIGEST,
                ),
            ),
        )

    def rollback(self, manifest: ReleaseManifest) -> object:
        return self._record("rollback", manifest)

    def _record(self, stage: str, manifest: ReleaseManifest) -> object:
        self.calls.append((stage, manifest.release_id))
        return {"stage": stage, "release_id": manifest.release_id}


class OperationsHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="dududa-s16-")
        self.workspace = Path(self.temporary.name)
        self.data_root = self.workspace / "data"
        self.clock = lambda: NOW
        self.store = ReleaseStore(self.data_root, clock=self.clock)
        self.backups = BackupManager(self.store, clock=self.clock)
        self.driver = RecordingDriver()
        self.coordinator = OperationsCoordinator(
            self.store,
            self.backups,
            self.driver,
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_disposable_release_lifecycle(self) -> None:
        initial = self.store.bootstrap()
        state_bytes = self.store.state_path.read_bytes()
        self.assertEqual(self.store.bootstrap(), initial)
        self.assertEqual(self.store.state_path.read_bytes(), state_bytes)
        self.assertFalse((self.data_root / ".env").exists())
        for path in (
            self.data_root,
            self.store.metadata_root,
            self.store.releases_root,
            self.store.receipts_root,
            self.store.staging_root,
            self.store.backups_root,
        ):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

        config, database = self._seed_runtime_files()
        release_v1 = self._manifest("release-v1")
        started = self.coordinator.start_release(
            release_v1,
            operation_id="start-release-v1",
        )
        self.assertEqual(started.status, "succeeded")
        self.assertEqual(
            self._receipt_stages("start-release-v1"),
            [
                ("start", "started"),
                ("start", "succeeded"),
                ("health", "started"),
                ("health", "succeeded"),
                ("promote", "succeeded"),
            ],
        )

        before_health = self._file_snapshot(self.data_root)
        self.assertEqual(self.coordinator.health().status, "healthy")
        self.assertEqual(self._file_snapshot(self.data_root), before_health)

        baseline = self.backups.create(
            backup_id="baseline-v1",
            release_id="release-v1",
            includes=("astrbot/cmd_config.json", "astrbot/data.db"),
        )
        self.assertEqual(
            {entry.relative_path: entry.kind for entry in baseline.entries},
            {
                "astrbot/cmd_config.json": "file",
                "astrbot/data.db": "sqlite",
            },
        )

        release_v2 = self._manifest("release-v2", previous="release-v1")
        upgraded = self.coordinator.upgrade(
            release_v2,
            operation_id="upgrade-release-v2",
            backup_id="upgrade-release-v1",
            includes=("astrbot/cmd_config.json", "astrbot/data.db"),
        )
        self.assertEqual(upgraded.status, "succeeded")
        self.assertEqual(upgraded.backup_id, "upgrade-release-v1")
        self.assertEqual(
            self._receipt_stages("upgrade-release-v2"),
            [
                ("backup", "started"),
                ("backup", "succeeded"),
                ("prepare", "started"),
                ("prepare", "succeeded"),
                ("start", "started"),
                ("start", "succeeded"),
                ("health", "started"),
                ("health", "succeeded"),
                ("promote", "succeeded"),
            ],
        )
        state = self.store.state()
        self.assertEqual(state.current_release_id, "release-v2")
        self.assertEqual(state.previous_release_id, "release-v1")

        config.write_text('{"release":"v2"}\n', encoding="utf-8")
        destination = self.workspace / "restored-v1"
        first_plan = self.backups.plan_restore(
            backup_id="baseline-v1",
            destination=destination,
        )
        second_plan = self.backups.plan_restore(
            backup_id="baseline-v1",
            destination=destination,
        )
        self.assertEqual(first_plan.to_dict(), second_plan.to_dict())
        self.assertEqual(self.backups.restore(first_plan), destination)
        self.assertEqual(
            (destination / "astrbot" / "cmd_config.json").read_text(encoding="utf-8"),
            '{"release":"v1"}\n',
        )
        with sqlite3.connect(destination / "astrbot" / database.name) as restored:
            self.assertEqual(
                restored.execute("SELECT value FROM sample").fetchall(), [(1,)]
            )
            self.assertEqual(restored.execute("PRAGMA quick_check").fetchone(), ("ok",))

        rolled_back = self.coordinator.rollback(operation_id="rollback-release-v2")
        self.assertEqual(rolled_back.status, "succeeded")
        state = self.store.state()
        self.assertEqual(state.current_release_id, "release-v1")
        self.assertEqual(state.previous_release_id, "release-v2")
        self.assertEqual(
            self._receipt_stages("rollback-release-v2"),
            [
                ("rollback", "started"),
                ("rollback", "succeeded"),
                ("health", "started"),
                ("health", "succeeded"),
                ("promote", "succeeded"),
            ],
        )
        self.assertEqual(
            self.driver.calls,
            [
                ("start", "release-v1"),
                ("health", "release-v1"),
                ("health", "release-v1"),
                ("prepare", "release-v2"),
                ("start", "release-v2"),
                ("health", "release-v2"),
                ("rollback", "release-v1"),
                ("health", "release-v1"),
            ],
        )
        self.store.load_manifest("release-v2")
        self.backups.verify("baseline-v1")
        self.backups.verify("upgrade-release-v1")

    def test_manifest_backup_and_restore_boundaries(self) -> None:
        self.store.bootstrap()
        config, database = self._seed_runtime_files()
        release = self._manifest("release-v1")
        self.coordinator.start_release(release, operation_id="boundary-start")

        self.driver.health_by_release["release-v1"] = "degraded"
        before_health = self._file_snapshot(self.data_root)
        report = self.coordinator.health()
        self.assertEqual(report.status, "degraded")
        self.assertEqual(self._file_snapshot(self.data_root), before_health)

        backup = self.backups.create(
            backup_id="guarded-v1",
            release_id="release-v1",
            includes=("astrbot/cmd_config.json", "astrbot/data.db"),
        )
        entries = {entry.relative_path: entry for entry in backup.entries}
        self.assertEqual(entries["astrbot/data.db"].kind, "sqlite")
        self.assertEqual(entries["astrbot/cmd_config.json"].mode, 0o600)
        backup_database = (
            self.store.backups_root
            / "guarded-v1"
            / "payload"
            / "astrbot"
            / database.name
        )
        with sqlite3.connect(backup_database) as copied:
            self.assertEqual(
                copied.execute("SELECT value FROM sample").fetchall(), [(1,)]
            )
            self.assertEqual(copied.execute("PRAGMA quick_check").fetchone(), ("ok",))

        destination = self.workspace / "non-empty"
        destination.mkdir()
        sentinel = destination / "sentinel.txt"
        sentinel.write_text("preserve\n", encoding="utf-8")
        plan = self.backups.plan_restore(
            backup_id="guarded-v1",
            destination=destination,
        )
        with self.assertRaises(OperationsError) as nonempty:
            self.backups.restore(plan)
        self.assertEqual(nonempty.exception.code, "restore_destination_not_empty")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve\n")

        symlink = self.data_root / "astrbot" / "config-link.json"
        symlink.symlink_to(config)
        with self.assertRaises(OperationsError) as unsafe:
            self.backups.create(
                backup_id="unsafe-v1",
                release_id="release-v1",
                includes=("astrbot/config-link.json",),
            )
        self.assertEqual(unsafe.exception.code, "backup_symlink_rejected")
        self.assertFalse((self.store.backups_root / "unsafe-v1").exists())

        backup_config = (
            self.store.backups_root / "guarded-v1" / "payload" / "astrbot" / config.name
        )
        backup_config.write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(OperationsError) as tampered_backup:
            self.backups.verify("guarded-v1")
        self.assertEqual(tampered_backup.exception.code, "backup_digest_mismatch")

        manifest_path = self.store.manifest_path("release-v1")
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_manifest["source_revision"] = "tampered-revision"
        manifest_path.write_text(json.dumps(raw_manifest), encoding="utf-8")
        with self.assertRaises(OperationsError) as tampered_manifest:
            self.store.load_manifest("release-v1")
        self.assertEqual(
            tampered_manifest.exception.code,
            "release_manifest_digest_mismatch",
        )

    def test_failed_health_rolls_back_once_and_preserves_evidence(self) -> None:
        self.store.bootstrap()
        self._seed_runtime_files()
        release_v1 = self._manifest("release-v1")
        self.coordinator.start_release(release_v1, operation_id="failure-start")
        self.driver.calls.clear()

        release_v2 = self._manifest("release-v2", previous="release-v1")
        self.driver.health_by_release["release-v2"] = "unhealthy"
        with self.assertRaises(OperationFailed) as failure:
            self.coordinator.upgrade(
                release_v2,
                operation_id="upgrade-health-failure",
                backup_id="failure-backup-v1",
                includes=("astrbot/cmd_config.json", "astrbot/data.db"),
            )

        self.assertEqual(failure.exception.code, "upgrade_rolled_back")
        self.assertEqual(failure.exception.summary.status, "rolled_back")
        self.assertEqual(failure.exception.summary.backup_id, "failure-backup-v1")
        self.assertEqual(
            self.driver.calls,
            [
                ("prepare", "release-v2"),
                ("start", "release-v2"),
                ("health", "release-v2"),
                ("rollback", "release-v1"),
                ("health", "release-v1"),
            ],
        )
        self.assertEqual(self.driver.calls.count(("rollback", "release-v1")), 1)
        receipts = self._receipt_values("upgrade-health-failure")
        self.assertEqual(
            [(item["stage"], item["status"]) for item in receipts],
            [
                ("backup", "started"),
                ("backup", "succeeded"),
                ("prepare", "started"),
                ("prepare", "succeeded"),
                ("start", "started"),
                ("start", "succeeded"),
                ("health", "started"),
                ("health", "failed"),
                ("rollback", "started"),
                ("rollback", "succeeded"),
                ("rollback-health", "started"),
                ("rollback-health", "succeeded"),
            ],
        )
        self.assertEqual(receipts[7]["reason_code"], "release_health_not_healthy")
        self.assertNotIn("promote", {item["stage"] for item in receipts})
        state = self.store.state()
        self.assertEqual(state.current_release_id, "release-v1")
        self.assertIsNone(state.previous_release_id)
        self.store.load_manifest("release-v2")
        self.backups.verify("failure-backup-v1")
        self.assertTrue(
            (
                self.store.receipt_directory("upgrade-health-failure") / "summary.json"
            ).is_file()
        )

    def test_root_wrapper_and_compose_surface(self) -> None:
        rendered = {
            "services": {
                "web": {
                    "ports": [{"host_ip": "127.0.0.1"}],
                    "volumes": [],
                    "networks": {"bot_net": {}, "edge": {}},
                },
                "astrbot": {
                    "ports": [{"host_ip": "127.0.0.1"}],
                    "volumes": [
                        {
                            "target": "/AstrBot/data",
                            "read_only": False,
                        },
                        {
                            "target": "/opt/dududa/config",
                            "read_only": True,
                        },
                        {
                            "target": "/opt/dududa/scripts",
                            "read_only": True,
                        },
                        {
                            "target": "/AstrBot/data/icourse-mcp",
                            "read_only": True,
                        },
                    ],
                    "networks": {"bot_net": {}, "edge": {}},
                },
                "napcat": {
                    "ports": [{"host_ip": "127.0.0.1"}],
                    "volumes": [
                        {"target": "/AstrBot/data", "read_only": False},
                        {"target": "/app/napcat/config", "read_only": False},
                        {"target": "/app/.config/QQ", "read_only": False},
                    ],
                    "networks": {"bot_net": {}, "edge": {}},
                },
            }
        }
        result = validate_compose_contract(rendered)
        self.assertEqual(result["services"], ["astrbot", "napcat", "web"])
        self.assertTrue(result["loopback_ports"])
        public = deepcopy(rendered)
        public["services"]["web"]["ports"][0]["host_ip"] = "0.0.0.0"
        with self.assertRaises(OperationsError) as unsafe_port:
            validate_compose_contract(public)
        self.assertEqual(unsafe_port.exception.code, "compose_port_not_loopback")

        compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        for value in (
            "${DUDUDA_WEB_HOST:-127.0.0.1}",
            "${ASTRBOT_WEBUI_HOST:-127.0.0.1}",
            "${NAPCAT_WEBUI_HOST:-127.0.0.1}",
            "./config:/opt/dududa/config:ro",
            "./scripts:/opt/dududa/scripts:ro",
            "./services/mcp/icourse:/AstrBot/data/icourse-mcp:ro",
        ):
            self.assertIn(value, compose)
        self.assertNotIn(
            "${STACK_DATA_ROOT:-./data}/astrbot:/AstrBot/data:ro",
            compose,
        )
        self.assertGreaterEqual(compose.count("      bot_net:"), 3)
        self.assertGreaterEqual(compose.count("      edge:"), 3)

        fake_python = self.workspace / "fake-python"
        arguments = self.workspace / "operations-arguments.txt"
        fake_python.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$@" > "$OPS_ARGUMENTS"\nexit 37\n',
            encoding="utf-8",
        )
        os.chmod(fake_python, 0o700)
        managed_root = self.workspace / "managed-data"
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHON": str(fake_python),
                "STACK_DATA_ROOT": str(managed_root),
                "OPS_ARGUMENTS": str(arguments),
            }
        )
        completed = subprocess.run(
            [str(ROOT / "manage.sh"), "health", "--release-id", "release-v1"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 37)
        self.assertEqual(
            arguments.read_text(encoding="utf-8").splitlines(),
            [
                "scripts/dududa_ops.py",
                "health",
                "--data-root",
                str(managed_root),
                "--release-id",
                "release-v1",
            ],
        )
        self.assertFalse(managed_root.exists())

        manage = (ROOT / "manage.sh").read_text(encoding="utf-8")
        for command in (
            "bootstrap",
            "health",
            "backup",
            "restore",
            "rollback",
            "init",
            "seed",
            "up",
            "down",
            "restart",
            "logs",
            "ps",
        ):
            self.assertIn(f"  {command})", manage)
        self.assertIn('if [[ "$#" -gt 0 ]]', manage)
        self.assertIn('"$0" plugins', manage)
        self.assertIn('"$0" sync', manage)

    def _manifest(
        self,
        release_id: str,
        *,
        previous: str | None = None,
    ) -> ReleaseManifest:
        suffix = release_id.rsplit("-", 1)[-1]
        return ReleaseManifest.create(
            release_id=release_id,
            source_revision=f"revision-{suffix}",
            source_dirty=False,
            created_at=NOW,
            previous_release_id=previous,
            data_schema_version=f"schema-{suffix}",
            image_references={"astrbot": f"example.invalid/astrbot@{ONE_DIGEST}"},
            component_digests={"agent": ZERO_DIGEST},
            deployment_contract_digest=ONE_DIGEST,
        )

    def _seed_runtime_files(self) -> tuple[Path, Path]:
        astrbot = self.data_root / "astrbot"
        astrbot.mkdir(parents=True, exist_ok=True)
        config = astrbot / "cmd_config.json"
        config.write_text('{"release":"v1"}\n', encoding="utf-8")
        os.chmod(config, 0o600)
        database = astrbot / "data.db"
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("CREATE TABLE sample (value INTEGER NOT NULL)")
            connection.execute("INSERT INTO sample VALUES (1)")
            connection.commit()
        return config, database

    def _receipt_values(self, operation_id: str) -> list[dict[str, object]]:
        directory = self.store.receipt_directory(operation_id)
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]-*.json"))
        ]

    def _receipt_stages(self, operation_id: str) -> list[tuple[object, object]]:
        return [
            (value["stage"], value["status"])
            for value in self._receipt_values(operation_id)
        ]

    @staticmethod
    def _file_snapshot(root: Path) -> tuple[tuple[str, int, bytes], ...]:
        return tuple(
            (
                path.relative_to(root).as_posix(),
                stat.S_IMODE(path.stat().st_mode),
                path.read_bytes(),
            )
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
            if path.is_file() and not path.is_symlink()
        )


if __name__ == "__main__":
    unittest.main()
