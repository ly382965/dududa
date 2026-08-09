from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(64)
    journal = Path(sys.argv[1])
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=False,
    )
    journal.write_text(
        json.dumps(
            {
                "server_pid": os.getpid(),
                "server_pgid": os.getpgrp(),
                "child_pid": child.pid,
                "child_pgid": os.getpgid(child.pid),
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
