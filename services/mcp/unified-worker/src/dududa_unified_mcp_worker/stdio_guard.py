from __future__ import annotations

import ctypes
import json
import os
import re
import signal
import sys
from pathlib import Path

_NONCE = re.compile(r"^[a-f0-9]{32}$")


def _install_parent_death_signal(parent_pid: int) -> None:
    if not sys.platform.startswith("linux"):
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL) != 0:
        raise OSError(ctypes.get_errno(), "prctl failed")
    if os.getppid() != parent_pid:
        raise RuntimeError("worker exited before stdio guard initialization")


def _write_record(path: Path, nonce: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    payload = json.dumps(
        {
            "v": 1,
            "nonce": nonce,
            "pid": os.getpid(),
            "pgid": os.getpgrp(),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short process-control write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 3:
        raise SystemExit(64)
    record = Path(arguments[0])
    nonce = arguments[1]
    command = arguments[2]
    command_arguments = arguments[3:]
    if not record.is_absolute() or not os.path.isabs(command):
        raise SystemExit(64)
    if _NONCE.fullmatch(nonce) is None:
        raise SystemExit(64)
    parent_pid = os.getppid()
    _install_parent_death_signal(parent_pid)
    if os.getpid() != os.getpgrp():
        raise SystemExit(70)
    _write_record(record, nonce)
    os.execve(command, [command, *command_arguments], dict(os.environ))


if __name__ == "__main__":
    main()
