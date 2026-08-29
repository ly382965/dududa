from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import AppConfig
from .fetcher import CatalogFetcher
from .storage import CatalogStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sync public USTC course-catalog lessons into local SQLite.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")
    parser.add_argument("--semester", type=int, default=None, help="Semester id to sync. Default: latest.")
    parser.add_argument("--base-url", default=None)
    args = parser.parse_args(argv)

    config = AppConfig.from_args(db_path=args.db_path, base_url=args.base_url)
    fetcher = CatalogFetcher(config)
    store = CatalogStore(config.db_path)
    try:
        semesters = fetcher.semesters()
        store.upsert_semesters(semesters)
        if args.semester:
            target = next((s for s in semesters if s.get("id") == args.semester), None)
            if not target:
                print(f"semester id {args.semester} not found; available ids: {[s.get('id') for s in semesters[:8]]}")
                return 1
        else:
            target = semesters[0]
        lessons = fetcher.lesson_list_for_teach(target["id"])
        count = store.replace_semester_lessons(target["id"], lessons)
        print(f"synced semester {target['id']} ({target.get('nameZh')}): {count} lessons cached at {config.db_path}")
    finally:
        fetcher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
