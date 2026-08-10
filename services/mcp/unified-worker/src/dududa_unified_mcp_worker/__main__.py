from __future__ import annotations

import asyncio

from .worker import Worker


def main() -> None:
    raise SystemExit(asyncio.run(Worker().run()))


if __name__ == "__main__":
    main()
