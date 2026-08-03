from __future__ import annotations

try:
    from enum import StrEnum as StrEnum
except ImportError:  # pragma: no cover - exercised by the Python 3.10 CI job
    from enum import Enum

    class StrEnum(str, Enum):
        def __new__(cls, value: str) -> "StrEnum":
            if not isinstance(value, str):
                raise TypeError(f"{value!r} is not a string")
            member = str.__new__(cls, value)
            member._value_ = value
            return member

        def __str__(self) -> str:
            return str.__str__(self.value)
