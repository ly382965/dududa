from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import dududa.memory.migration as migration_module
from dududa.domain.primitives import ConversationType
from dududa.errors import DududaError
from dududa.memory.migration import (
    LegacyClassification,
    migrate_legacy_json,
    rollback_memory_migration,
)


class MemoryMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.classifications = {
            "u-1": LegacyClassification(
                "qq", "bot-1", ConversationType.PRIVATE, "private:u-1", None, "dududa"
            )
        }

    def test_dry_run_apply_receipt_counts_and_rollback(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "user_state.json"
            destination = root / "memory-v2.json"
            backups = root / "backups"
            receipt_path = root / "migration-receipt.json"
            legacy = {
                "u-1": {"memories": [{"text": "保留", "time": 1700000000}]},
                "u-2": {"memories": [{"text": "缺分类", "time": 1700000001}]},
            }
            original = json.dumps(legacy, ensure_ascii=False)
            source.write_text(original, encoding="utf-8")

            dry = migrate_legacy_json(
                source,
                destination,
                classifications=self.classifications,
                backup_directory=backups,
                receipt_path=receipt_path,
                dry_run=True,
                now=self.now,
            )
            self.assertTrue(dry.dry_run)
            self.assertEqual((dry.migrated_count, dry.quarantined_count), (1, 1))
            self.assertFalse(destination.exists())
            self.assertFalse(receipt_path.exists())

            applied = migrate_legacy_json(
                source,
                destination,
                classifications=self.classifications,
                backup_directory=backups,
                receipt_path=receipt_path,
                dry_run=False,
                now=self.now,
            )
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertTrue(Path(applied.source_backup_path).is_file())  # type: ignore[arg-type]
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["records"]), 1)
            self.assertEqual(payload["records"][0]["scope"]["user_id"], "u-1")
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

            rollback = rollback_memory_migration(receipt_path, now=self.now)
            self.assertTrue(rollback.destination_restored)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(applied.quarantine_path).exists())  # type: ignore[arg-type]
            self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_rollback_refuses_tampered_destination(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "user_state.json"
            destination = root / "memory-v2.json"
            receipt = root / "receipt.json"
            source.write_text(
                json.dumps({"u-1": {"memories": [{"text": "x", "time": 1}]}}),
                encoding="utf-8",
            )
            migrate_legacy_json(
                source,
                destination,
                classifications=self.classifications,
                backup_directory=root / "backups",
                receipt_path=receipt,
                dry_run=False,
                now=self.now,
            )
            destination.write_text("tampered", encoding="utf-8")
            with self.assertRaises(DududaError):
                rollback_memory_migration(receipt, now=self.now)

    def test_path_collision_and_existing_receipt_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "user_state.json"
            destination = root / "memory-v2.json"
            source.write_text(json.dumps({"u-1": {"memories": []}}), encoding="utf-8")
            with self.assertRaises(DududaError):
                migrate_legacy_json(
                    source,
                    destination,
                    classifications=self.classifications,
                    backup_directory=root / "backups",
                    receipt_path=source,
                    dry_run=False,
                    now=self.now,
                )
            receipt = root / "receipt.json"
            receipt.write_text("existing", encoding="utf-8")
            with self.assertRaises(DududaError):
                migrate_legacy_json(
                    source,
                    destination,
                    classifications=self.classifications,
                    backup_directory=root / "backups",
                    receipt_path=receipt,
                    dry_run=False,
                    now=self.now,
                )

    def test_partial_apply_restores_existing_destination_and_quarantine(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "user_state.json"
            destination = root / "memory-v2.json"
            quarantine = destination.with_suffix(
                destination.suffix + ".quarantine.json"
            )
            receipt = root / "receipt.json"
            source.write_text(
                json.dumps({"u-1": {"memories": [{"text": "x", "time": 1}]}}),
                encoding="utf-8",
            )
            destination.write_text("original-destination", encoding="utf-8")
            quarantine.write_text("original-quarantine", encoding="utf-8")
            original_atomic_json = migration_module._atomic_json

            def fail_quarantine(path: Path, value: object) -> None:
                if path == quarantine.resolve():
                    raise OSError("injected failure")
                original_atomic_json(path, value)

            with patch.object(
                migration_module, "_atomic_json", side_effect=fail_quarantine
            ):
                with self.assertRaises(DududaError):
                    migrate_legacy_json(
                        source,
                        destination,
                        classifications=self.classifications,
                        backup_directory=root / "backups",
                        receipt_path=receipt,
                        dry_run=False,
                        now=self.now,
                    )
            self.assertEqual(
                destination.read_text(encoding="utf-8"), "original-destination"
            )
            self.assertEqual(
                quarantine.read_text(encoding="utf-8"), "original-quarantine"
            )
            self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
