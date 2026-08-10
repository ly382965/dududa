"""Versioned Persona expression assets and catalog."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .assets import load_persona_asset, load_persona_directory
    from .contracts import (
        PersonaCatalogSnapshot,
        PersonaCatalogUpdate,
        PersonaChannelStyle,
        PersonaDefinition,
        PersonaRendererMode,
        PersonaResolution,
        PersonaSentenceLength,
        PersonaVoiceRules,
        build_persona_definition,
        persona_catalog_digest,
        persona_definition_source_digest,
        validate_persona_resolution,
    )
    from .registry import InMemoryPersonaRegistry

__all__ = [
    "InMemoryPersonaRegistry",
    "PersonaCatalogSnapshot",
    "PersonaCatalogUpdate",
    "PersonaChannelStyle",
    "PersonaDefinition",
    "PersonaRendererMode",
    "PersonaResolution",
    "PersonaSentenceLength",
    "PersonaVoiceRules",
    "build_persona_definition",
    "load_persona_asset",
    "load_persona_directory",
    "persona_catalog_digest",
    "persona_definition_source_digest",
    "validate_persona_resolution",
]

_EXPORT_MODULES = {
    "InMemoryPersonaRegistry": ".registry",
    "PersonaCatalogSnapshot": ".contracts",
    "PersonaCatalogUpdate": ".contracts",
    "PersonaChannelStyle": ".contracts",
    "PersonaDefinition": ".contracts",
    "PersonaRendererMode": ".contracts",
    "PersonaResolution": ".contracts",
    "PersonaSentenceLength": ".contracts",
    "PersonaVoiceRules": ".contracts",
    "build_persona_definition": ".contracts",
    "persona_catalog_digest": ".contracts",
    "persona_definition_source_digest": ".contracts",
    "validate_persona_resolution": ".contracts",
    "load_persona_asset": ".assets",
    "load_persona_directory": ".assets",
}


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
