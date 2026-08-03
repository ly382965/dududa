#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from dududa.memory.migration import (
    load_classifications,
    migrate_legacy_json,
    rollback_memory_migration,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dududa Memory v2 可逆离线迁移")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--classifications", type=Path)
    parser.add_argument("--backup-directory", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        result = rollback_memory_migration(args.receipt)
    else:
        required = (
            args.source,
            args.destination,
            args.classifications,
            args.backup_directory,
        )
        if any(item is None for item in required):
            parser.error("迁移需要 --source/--destination/--classifications/--backup-directory")
        result = migrate_legacy_json(
            args.source,
            args.destination,
            classifications=load_classifications(args.classifications),
            backup_directory=args.backup_directory,
            receipt_path=args.receipt,
            dry_run=args.dry_run,
        )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
