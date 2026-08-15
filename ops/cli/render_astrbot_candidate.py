#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

PLUGIN_CONFIG_NAME = "astrbot_plugin_dududa_core_config.json"


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object in {path}")
    return value


def merge_by_id(
    existing: object,
    additions: object,
    *,
    field: str,
) -> list[dict[str, Any]]:
    if not isinstance(existing, list) or not isinstance(additions, list):
        raise TypeError(f"{field} must be a JSON array")

    merged: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for item in existing:
        if not isinstance(item, dict):
            raise TypeError(f"{field} entries must be JSON objects")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(f"{field} entries require a non-empty id")
        if item_id in positions:
            raise ValueError(f"duplicate {field} id: {item_id}")
        positions[item_id] = len(merged)
        merged.append(dict(item))

    for item in additions:
        if not isinstance(item, dict):
            raise TypeError(f"{field} additions must be JSON objects")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(f"{field} additions require a non-empty id")
        if item_id in positions:
            current = dict(merged[positions[item_id]])
            current.update(item)
            merged[positions[item_id]] = current
        else:
            positions[item_id] = len(merged)
            merged.append(dict(item))
    return merged


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_api_key(*, key_file: Path | None, key_env: str) -> str | None:
    if key_file is not None:
        value = key_file.read_text(encoding="utf-8").strip()
    else:
        value = os.environ.get(key_env, "").strip()
    return value or None


def render_candidate(
    *,
    template: dict[str, Any],
    astrbot_config: dict[str, Any],
    plugin_config: dict[str, Any],
    mode: str,
    api_base: str | None,
    api_key: str | None,
    provider_source_id: str,
    evidence_path: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if template.get("schema_version") != 1:
        raise ValueError("unsupported candidate template schema")
    additions = template.get("astrbot_config_additions")
    candidate_plugin = template.get("dududa_plugin_config")
    if not isinstance(additions, dict) or not isinstance(candidate_plugin, dict):
        raise TypeError("candidate template is missing config sections")
    if mode not in {"disabled", "shadow"}:
        raise ValueError("mode must be disabled or shadow")

    sources = additions.get("provider_sources")
    providers = additions.get("provider")
    if not isinstance(sources, list) or not isinstance(providers, list):
        raise TypeError("candidate provider additions must be arrays")

    enabled = mode == "shadow"
    rendered_sources: list[dict[str, Any]] = []
    matched_source = False
    for source in sources:
        if not isinstance(source, dict):
            raise TypeError("provider source addition must be an object")
        rendered = dict(source)
        if rendered.get("id") == provider_source_id:
            matched_source = True
            rendered["enable"] = enabled
            if api_base:
                rendered["api_base"] = api_base.rstrip("/")
            if api_key:
                rendered["key"] = [api_key]
        rendered_sources.append(rendered)
    if not matched_source:
        raise ValueError(
            f"provider source is absent from template: {provider_source_id}"
        )

    rendered_providers: list[dict[str, Any]] = []
    for provider in providers:
        if not isinstance(provider, dict):
            raise TypeError("provider addition must be an object")
        rendered = dict(provider)
        if rendered.get("provider_source_id") == provider_source_id:
            rendered["enable"] = enabled
        rendered_providers.append(rendered)

    if enabled:
        selected_source = next(
            source
            for source in rendered_sources
            if source.get("id") == provider_source_id
        )
        selected_base = selected_source.get("api_base")
        selected_keys = selected_source.get("key")
        if (
            not isinstance(selected_base, str)
            or not selected_base.strip()
            or "example.invalid" in selected_base
        ):
            raise ValueError("shadow mode requires a real API base")
        if (
            not isinstance(selected_keys, list)
            or not selected_keys
            or not isinstance(selected_keys[0], str)
            or not selected_keys[0].strip()
            or selected_keys[0].startswith("$")
        ):
            raise ValueError("shadow mode requires a Provider API key")
        if not evidence_path:
            raise ValueError("shadow mode requires a private Provider evidence path")

    rendered_astrbot = dict(astrbot_config)
    rendered_astrbot["provider_sources"] = merge_by_id(
        astrbot_config.get("provider_sources", []),
        rendered_sources,
        field="provider_sources",
    )
    rendered_astrbot["provider"] = merge_by_id(
        astrbot_config.get("provider", []),
        rendered_providers,
        field="provider",
    )

    rendered_plugin = dict(plugin_config)
    rendered_plugin.update(candidate_plugin)
    rendered_plugin.update(
        {
            "runtime_enabled": enabled,
            "rollout_mode": "shadow" if enabled else "off",
            "rollout_delivery_enabled": False,
            "rollout_kill_switch": True,
            "rollout_tools_enabled": False,
            "rollout_memory_enabled": False,
            "rollout_allowlisted_groups": [],
        }
    )
    if evidence_path:
        rendered_plugin["runtime_provider_evidence_path"] = evidence_path
    else:
        rendered_plugin.pop("runtime_provider_evidence_path", None)
    return rendered_astrbot, rendered_plugin


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render an isolated Luna/Terra/Sol AstrBot candidate configuration."
    )
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--mode", choices=("disabled", "shadow"), default="disabled")
    parser.add_argument("--api-base")
    parser.add_argument("--api-base-env", default="DUDUDA_GPT56_API_BASE")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--api-key-env", default="DUDUDA_GPT56_API_KEY")
    parser.add_argument("--provider-source-id", default="dududa-gpt56-source")
    parser.add_argument("--evidence-path")
    args = parser.parse_args()

    astrbot_path = args.data_root / "cmd_config.json"
    plugin_path = args.data_root / "config" / PLUGIN_CONFIG_NAME
    template = load_object(args.template)
    astrbot_config = load_object(astrbot_path)
    plugin_config = load_object(plugin_path) if plugin_path.exists() else {}
    api_base = args.api_base or os.environ.get(args.api_base_env, "").strip() or None
    api_key = read_api_key(key_file=args.api_key_file, key_env=args.api_key_env)

    rendered_astrbot, rendered_plugin = render_candidate(
        template=template,
        astrbot_config=astrbot_config,
        plugin_config=plugin_config,
        mode=args.mode,
        api_base=api_base,
        api_key=api_key,
        provider_source_id=args.provider_source_id,
        evidence_path=args.evidence_path,
    )
    write_json(astrbot_path, rendered_astrbot)
    write_json(plugin_path, rendered_plugin)
    print(
        json.dumps(
            {
                "astrbot_config": str(astrbot_path),
                "mode": args.mode,
                "plugin_config": str(plugin_path),
                "provider_count": len(
                    template["astrbot_config_additions"]["provider"]
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
