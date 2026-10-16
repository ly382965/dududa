from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sqlite3
from typing import Any


_AUDIT_JOURNAL = Path(os.environ["DUDUDA_SPIKE_AUDIT_JOURNAL"])
_ALLOWED_DB = Path(os.environ["DUDUDA_SPIKE_ALLOWED_DB"]).absolute()


def _record(event: str, operation: str) -> None:
    payload = (
        json.dumps(
            {"event": event, "operation": operation},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    descriptor = os.open(
        _AUDIT_JOURNAL,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)


class _NetworkDeniedSocket(socket.socket):
    def connect(self, address: object) -> None:
        _record("network_attempt", "connect")
        raise OSError("S12A fixture network access is disabled")

    def connect_ex(self, address: object) -> int:
        _record("network_attempt", "connect_ex")
        raise OSError("S12A fixture network access is disabled")


def _deny_create_connection(*args: object, **kwargs: object) -> socket.socket:
    _record("network_attempt", "create_connection")
    raise OSError("S12A fixture network access is disabled")


def _deny_getaddrinfo(*args: object, **kwargs: object) -> list[object]:
    _record("network_attempt", "getaddrinfo")
    raise OSError("S12A fixture network access is disabled")


_sqlite_connect = sqlite3.connect


def _guarded_sqlite_connect(database: object, *args: object, **kwargs: object) -> Any:
    candidate = Path(os.fspath(database)).absolute()
    if candidate != _ALLOWED_DB:
        _record("database_denied", "sqlite_connect")
        raise OSError("S12A fixture may only open its temporary SQLite database")
    _record("database_open", "sqlite_connect")
    return _sqlite_connect(database, *args, **kwargs)


socket.socket = _NetworkDeniedSocket
socket.create_connection = _deny_create_connection
socket.getaddrinfo = _deny_getaddrinfo
sqlite3.connect = _guarded_sqlite_connect
