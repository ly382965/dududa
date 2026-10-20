"""Feature modules; each non-``base`` module exposes ``register(registry)``."""

from __future__ import annotations

import importlib
import pkgutil

from .base import Registry


def load_registry() -> Registry:
    registry = Registry()
    for module in sorted(pkgutil.iter_modules(__path__), key=lambda item: item.name):
        if module.name == "base" or module.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{module.name}").register(registry)
    return registry
