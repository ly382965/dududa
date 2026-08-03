"""Offline, reproducible evaluation utilities."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .s09 import generate_s09_bundle, run_s09_eval

__all__ = ["generate_s09_bundle", "run_s09_eval"]


def __getattr__(name: str) -> object:
    if name in __all__:
        return getattr(import_module(".s09", __name__), name)
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
