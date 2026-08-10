from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path

from dududa.domain.primitives import ConversationType
from dududa.errors import validation_error

from .contracts import (
    PersonaChannelStyle,
    PersonaDefinition,
    PersonaRendererMode,
    PersonaSentenceLength,
    PersonaVoiceRules,
    build_persona_definition,
)

_MAX_ASSET_BYTES = 65_536
_SECRET_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9]{12,}|api[_-]?key\s*[:=]|cookie\s*[:=]|token\s*[:=])"
)
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "persona_id",
        "version",
        "display_name",
        "default_locale",
        "voice",
        "channel_rules",
        "renderer_mode",
        "safety_note_ids",
    }
)
_VOICE_FIELDS = frozenset(
    {
        "schema_version",
        "tone_tags",
        "sentence_length",
        "preferred_language",
        "emoji_budget",
        "avoid_patterns",
        "technical_style",
        "uncertainty_style",
        "instructions",
    }
)
_CHANNEL_FIELDS = frozenset(
    {"schema_version", "tone_tags", "emoji_budget", "prefer_short_sentences"}
)


def load_persona_directory(root: Path) -> tuple[PersonaDefinition, ...]:
    resolved_root = _resolve_root(root)
    try:
        paths = tuple(sorted(resolved_root.glob("*.json")))
    except OSError:
        raise validation_error("invalid_persona_asset_root")
    if not paths:
        raise validation_error("empty_persona_asset_directory")
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise validation_error("invalid_persona_asset_file")
    return tuple(load_persona_asset(resolved_root, path) for path in paths)


def load_persona_asset(root: Path, path: Path) -> PersonaDefinition:
    resolved_root = _resolve_root(root)
    if not isinstance(path, Path):
        raise validation_error("invalid_persona_asset_path")
    try:
        resolved_path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise validation_error("invalid_persona_asset_path") from None
    if path.is_symlink() or resolved_path.parent != resolved_root:
        raise validation_error("persona_asset_outside_root")
    payload = _read_bounded_regular_file(resolved_path)
    if not payload or len(payload) > _MAX_ASSET_BYTES:
        raise validation_error("invalid_persona_asset_size")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise validation_error("invalid_persona_asset_encoding") from None
    if _SECRET_RE.search(text) is not None:
        raise validation_error("persona_asset_secret_pattern")
    try:
        document = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeError, ValueError):
        raise validation_error("invalid_persona_asset_json") from None
    root_values = _mapping(document, "persona_asset")
    _exact_fields(root_values, _ROOT_FIELDS, "persona_asset")
    if (
        type(root_values["schema_version"]) is not int
        or root_values["schema_version"] != 1
    ):
        raise validation_error("unsupported_schema_version")
    voice_values = _mapping(root_values["voice"], "persona_voice")
    _exact_fields(voice_values, _VOICE_FIELDS, "persona_voice")
    try:
        sentence_length = PersonaSentenceLength(voice_values["sentence_length"])
    except (TypeError, ValueError):
        raise validation_error("invalid_persona_sentence_length") from None
    voice = PersonaVoiceRules(
        schema_version=voice_values["schema_version"],
        tone_tags=_strings(voice_values["tone_tags"], "tone_tags"),
        sentence_length=sentence_length,
        preferred_language=_string(
            voice_values["preferred_language"],
            "preferred_language",
        ),
        emoji_budget=voice_values["emoji_budget"],
        avoid_patterns=_strings(
            voice_values["avoid_patterns"],
            "avoid_patterns",
        ),
        technical_style=_string(
            voice_values["technical_style"],
            "technical_style",
        ),
        uncertainty_style=_string(
            voice_values["uncertainty_style"],
            "uncertainty_style",
        ),
        instructions=_strings(
            voice_values["instructions"],
            "instructions",
        ),
    )
    channels = _mapping(root_values["channel_rules"], "channel_rules")
    if set(channels) != {value.value for value in ConversationType}:
        raise validation_error("invalid_persona_channel_rules")
    channel_rules = {}
    for kind in ConversationType:
        values = _mapping(channels[kind.value], f"channel_rules.{kind.value}")
        _exact_fields(values, _CHANNEL_FIELDS, f"channel_rules.{kind.value}")
        channel_rules[kind] = PersonaChannelStyle(
            schema_version=values["schema_version"],
            tone_tags=_strings(values["tone_tags"], "tone_tags"),
            emoji_budget=values["emoji_budget"],
            prefer_short_sentences=values["prefer_short_sentences"],
        )
    try:
        renderer_mode = PersonaRendererMode(root_values["renderer_mode"])
    except (TypeError, ValueError):
        raise validation_error("invalid_persona_renderer_mode") from None
    return build_persona_definition(
        persona_id=_string(root_values["persona_id"], "persona_id"),
        version=_string(root_values["version"], "version"),
        display_name=_string(root_values["display_name"], "display_name"),
        default_locale=_string(root_values["default_locale"], "default_locale"),
        voice=voice,
        channel_rules=channel_rules,
        renderer_mode=renderer_mode,
        safety_note_ids=_strings(
            root_values["safety_note_ids"],
            "safety_note_ids",
        ),
    )


def _resolve_root(root: Path) -> Path:
    if not isinstance(root, Path) or root.is_symlink():
        raise validation_error("invalid_persona_asset_root")
    try:
        resolved = root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise validation_error("invalid_persona_asset_root") from None
    if not resolved.is_dir():
        raise validation_error("invalid_persona_asset_root")
    return resolved


def _read_bounded_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        metadata = path.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= _MAX_ASSET_BYTES
        ):
            raise validation_error("invalid_persona_asset_size")
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size != metadata.st_size
                or not 0 < opened.st_size <= _MAX_ASSET_BYTES
            ):
                raise validation_error("invalid_persona_asset_file")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                payload = handle.read(_MAX_ASSET_BYTES + 1)
        finally:
            os.close(descriptor)
    except OSError:
        raise validation_error("invalid_persona_asset_file") from None
    if not payload or len(payload) > _MAX_ASSET_BYTES:
        raise validation_error("invalid_persona_asset_size")
    return payload


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(value)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise validation_error("invalid_persona_asset_mapping", field)
    return value


def _exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise validation_error("invalid_persona_asset_fields", field)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_persona_asset_string", field)
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise validation_error("invalid_persona_asset_strings", field)
    return tuple(value)


__all__ = ["load_persona_asset", "load_persona_directory"]
