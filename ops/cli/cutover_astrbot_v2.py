#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CORE_CONFIG = "astrbot_plugin_dududa_core_config.json"
REREAD_CONFIG = "astrbot_plugin_reread_config.json"
PLUGIN_SET = [
    "astrbot_plugin_dududa_core",
    "astrbot_plugin_sub2api_readonly",
    "astrbot_plugin_reread",
]
MODELS = (
    (
        "astrbot-luna",
        "dududa-luna",
        "luna",
        "gpt-5.6-luna",
        "haiku",
        32768,
        2048,
        4,
        30,
        120000,
    ),
    (
        "astrbot-terra",
        "dududa-terra",
        "terra",
        "gpt-5.6-terra",
        "sonnet",
        65536,
        4096,
        2,
        20,
        100000,
    ),
    (
        "astrbot-sol",
        "dududa-sol",
        "sol",
        "gpt-5.6-sol",
        "opus",
        128000,
        8192,
        1,
        10,
        80000,
    ),
)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any], *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.stat() if path.exists() else None
    current_mode = current.st_mode & 0o777 if current is not None else (mode or 0o600)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        if current is not None:
            os.chown(temporary, current.st_uid, current.st_gid)
        os.chmod(temporary, mode or current_mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def backup_legacy(data_root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = data_root / "backups" / f"dududa-legacy-{stamp}"
    target.mkdir(parents=True, mode=0o700)
    sources = (
        data_root / "cmd_config.json",
        data_root / "mcp_server.json",
        data_root / "config" / CORE_CONFIG,
        data_root / "config" / "astrbot_plugin_reply_polish_config.json",
        data_root / "config" / REREAD_CONFIG,
        data_root / "config" / "astrbot_plugin_sub2api_readonly_config.json",
    )
    for source in sources:
        if source.exists():
            destination = target / source.name
            shutil.copyfile(source, destination)
            os.chmod(destination, 0o600)
    return target


def prepare(data_root: Path, source_id: str) -> Path:
    backup = backup_legacy(data_root)
    cmd_path = data_root / "cmd_config.json"
    command = load_object(cmd_path)
    sources = command.get("provider_sources", [])
    if not isinstance(sources, list) or not any(
        isinstance(item, dict) and item.get("id") == source_id for item in sources
    ):
        raise ValueError("selected Provider source is unavailable")

    providers = command.get("provider", [])
    if not isinstance(providers, list):
        raise TypeError("provider must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in providers:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise TypeError("provider entries must have string IDs")
        provider_id = item["id"]
        order.append(provider_id)
        by_id[provider_id] = dict(item)
    for item in by_id.values():
        item["enable"] = False
    for astrbot_id, _, _, model, _, _, _, _, _, _ in MODELS:
        candidate = by_id.get(astrbot_id, {})
        candidate.update(
            {
                "id": astrbot_id,
                "provider_source_id": source_id,
                "model": model,
                "modalities": ["text"],
                "custom_extra_body": {"store": False},
                "enable": True,
            }
        )
        if astrbot_id not in by_id:
            order.append(astrbot_id)
        by_id[astrbot_id] = candidate
    command["provider"] = [by_id[provider_id] for provider_id in order]
    settings = command.setdefault("provider_settings", {})
    if not isinstance(settings, dict):
        raise TypeError("provider_settings must be an object")
    settings.update(
        {
            "enable": False,
            "default_provider_id": "astrbot-luna",
            "web_search": False,
            "display_reasoning_text": False,
            "show_tool_use_status": False,
            "show_tool_call_result": False,
            "buffer_intermediate_messages": False,
        }
    )
    command["plugin_set"] = PLUGIN_SET
    write_json(cmd_path, command)

    write_json(data_root / "mcp_server.json", {"mcpServers": {}})
    reread_path = data_root / "config" / REREAD_CONFIG
    reread = load_object(reread_path) if reread_path.exists() else {}
    reread["enabled"] = True
    write_json(reread_path, reread, mode=0o600)

    core_path = data_root / "config" / CORE_CONFIG
    core = load_object(core_path) if core_path.exists() else {}
    core.update(
        {
            "runtime_enabled": False,
            "rollout_mode": "off",
            "rollout_delivery_enabled": False,
            "rollout_kill_switch": True,
        }
    )
    write_json(core_path, core)
    return backup


def activate(
    data_root: Path,
    evidence_path: str,
    groups: list[str],
    runtime_reader_gid: int | None,
) -> None:
    host_evidence = data_root / Path(evidence_path).name
    if evidence_path.startswith("/AstrBot/data/private/"):
        host_evidence = data_root / "private" / Path(evidence_path).name
    if not host_evidence.is_file():
        raise FileNotFoundError("Provider evidence is unavailable")
    runtime_models = []
    for (
        astrbot_id,
        provider_id,
        endpoint_id,
        model,
        tier,
        context,
        output,
        concurrency,
        rpm,
        tpm,
    ) in MODELS:
        runtime_models.append(
            {
                "provider_id": provider_id,
                "astrbot_provider_id": astrbot_id,
                "endpoint_id": endpoint_id,
                "model_id": model,
                "tier": tier,
                "reasoning_depth": "light",
                "max_context_tokens": context,
                "max_output_tokens": output,
                "max_concurrency": concurrency,
                "rpm_limit": rpm,
                "tpm_limit": tpm,
            }
        )
    core_path = data_root / "config" / CORE_CONFIG
    core = load_object(core_path)
    core.update(
        {
            "runtime_enabled": True,
            "runtime_models_json": json.dumps(
                runtime_models, ensure_ascii=False, separators=(",", ":")
            ),
            "runtime_provider_evidence_path": evidence_path,
            "runtime_health_probe_enabled": True,
            "runtime_health_probe_interval_seconds": 900,
            "runtime_health_evidence_ttl_seconds": 1800,
            "runtime_response_profiles_enabled": True,
            "rollout_mode": "canary",
            "rollout_revision": "dududa-v2-only-20260826-v1",
            "rollout_delivery_enabled": True,
            "rollout_allowlisted_groups": groups,
            "rollout_kill_switch": False,
            "rollout_tools_enabled": True,
            "rollout_memory_enabled": False,
            "rollout_canary_timeout_ms": 180_000,
            "default_model_id": "astrbot-luna",
        }
    )
    write_json(core_path, core)
    if runtime_reader_gid is not None:
        os.chown(core_path, -1, runtime_reader_gid)
        os.chmod(core_path, 0o640)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Switch the single AstrBot host to Dududa 2.0 only."
    )
    parser.add_argument("phase", choices=("prepare", "activate"))
    parser.add_argument("--data-root", type=Path, default=Path("/AstrBot/data"))
    parser.add_argument("--provider-source-id", default="openai")
    parser.add_argument(
        "--evidence-path",
        default="/AstrBot/data/private/dududa-v2-provider-evidence.json",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--group", action="append", default=[])
    scope.add_argument(
        "--all-groups",
        action="store_true",
        help="Route supported explicit mentions from every group to Dududa 2.0.",
    )
    parser.add_argument("--runtime-reader-gid", type=int)
    args = parser.parse_args()
    if args.phase == "prepare":
        backup = prepare(args.data_root, args.provider_source_id)
        print(
            json.dumps(
                {"phase": "prepare", "backup": str(backup), "status": "ok"},
                sort_keys=True,
            )
        )
    else:
        groups = (
            ["*"]
            if args.all_groups
            else [str(value).strip() for value in args.group if str(value).strip()]
        )
        if not groups:
            raise ValueError("at least one rollout group is required")
        activate(
            args.data_root,
            args.evidence_path,
            groups,
            args.runtime_reader_gid,
        )
        print(
            json.dumps(
                {"phase": "activate", "groups": len(groups), "status": "ok"},
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
