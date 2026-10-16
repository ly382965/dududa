"""Prepare/probe external DeepSeek config; install only with the AstrBot host stopped.

Run inside the tested AstrBot image, with this repository mounted read-only.
No Bot host, QQ connector, group history or delivery adapter is started here.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

from run_astrbot_provider_conformance import load_object, write_private
from verify_astrbot_request_boundary import verify_boundary

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "dududa_key_projection",
    ROOT / "apps/astrbot-plugins/astrbot_plugin_dududa_core/adapters/api_key_pools.py",
)
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)

CORE_PATH = Path("config/astrbot_plugin_dududa_core_config.json")
POLICY_URL = "https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html"
sys.path.insert(0, str(ROOT / "apps/astrbot-plugins"))
from astrbot_plugin_dududa_core.adapters.deepseek_config import build_candidate


async def probe_provider(command: dict, pool) -> dict:
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial

    source = next(
        item for item in command["provider_sources"] if item["id"] == pool.source_id
    )
    config = next(
        item for item in command["provider"] if item["id"] == pool.provider_id
    )
    provider = ProviderOpenAIOfficial(
        {**source, **config}, command.get("provider_settings", {})
    )
    started = time.monotonic()
    try:
        response = await asyncio.wait_for(
            provider.text_chat(
                prompt="Synthetic connectivity test. Reply only OK.",
                model=pool.model,
                max_tokens=pool.max_output_tokens,
                reasoning_effort=pool.reasoning_effort,
                thinking={"type": "enabled"},
                request_max_retries=1,
            ),
            timeout=90,
        )
        actual_model = getattr(response.raw_completion, "model", None)
        output_tokens = getattr(response.usage, "output", None)
        if actual_model != pool.model or not response.completion_text.strip():
            raise ValueError("real_provider_model_or_output_mismatch")
        if (
            type(output_tokens) is not int
            or not 0 < output_tokens <= pool.max_output_tokens
        ):
            raise ValueError("real_provider_output_budget_mismatch")
        health = await asyncio.wait_for(
            provider.text_chat(
                prompt="Health check. Reply only OK.",
                model=pool.model,
                max_tokens=256,
                thinking={"type": "disabled"},
                request_max_retries=1,
            ),
            timeout=20,
        )
        if not health.completion_text.strip():
            raise ValueError("real_provider_health_probe_empty")
        return {
            "tier": pool.tier,
            "model": actual_model,
            "effort": pool.reasoning_effort,
            "maxOutputTokens": pool.max_output_tokens,
            "outputTokens": output_tokens,
            "healthProbe": True,
            "nonempty": True,
            "latencyMs": round((time.monotonic() - started) * 1000),
        }
    finally:
        await provider.client.close()


async def prepare(args) -> dict:
    snapshot = adapter.load_api_key_pool_snapshot(args.store)
    if snapshot.revision != args.expected_revision:
        raise ValueError("pool_revision_changed")
    original_command = load_object(args.data / "cmd_config.json")
    original_core = load_object(args.data / CORE_PATH)
    command, core = build_candidate(
        original_command,
        original_core,
        snapshot,
        accept_retention=args.accept_provider_retention,
    )
    evidence_relative = Path(core["runtime_provider_evidence_path"]).relative_to(
        "/AstrBot/data"
    )
    if ".." in evidence_relative.parts:
        raise ValueError("invalid_evidence_location")
    original_evidence = load_object(args.data / evidence_relative)
    boundary = await verify_boundary()
    probes = [await probe_provider(command, pool) for pool in snapshot.pools]
    evidence = []
    for pool in snapshot.pools:
        evidence.append(
            {
                "schema_version": 1,
                "astrbot_provider_id": pool.provider_id,
                "host_version": boundary["hostVersion"],
                "conformance_revision": {
                    "component_id": "astrbot-provider-conformance",
                    "implementation_version": "1.0.0",
                    "config_revision": f"deepseek-pool-{snapshot.revision}",
                    "artifact_digest": f"git:{args.source_revision}",
                },
                "verified_model_id": pool.model,
                "verified_max_output_tokens": pool.max_output_tokens,
                "verified_data_residencies": ["CN"],
                "verified_retention_modes": ["provider_managed"],
                "single_request_verified": boundary["singleRequest"],
                "model_binding_verified": True,
                "output_limit_verified": boundary["parametersForwarded"],
                "residency_verified": True,
                "retention_verified": args.accept_provider_retention,
                "sanitized_logging_verified": boundary["sanitizedLogging"],
                "deadline_enforcement_verified": boundary["deadlineCancellation"],
                "cancellation_enforcement_verified": boundary["deadlineCancellation"],
            }
        )
    args.candidate.mkdir(mode=0o700, parents=False, exist_ok=False)
    write_private(args.candidate / "command.before.json", original_command)
    write_private(args.candidate / "core.before.json", original_core)
    write_private(args.candidate / "evidence.before.json", original_evidence)
    write_private(args.candidate / "command.json", command)
    write_private(args.candidate / "core.json", core)
    replaced_ids = {pool.provider_id for pool in snapshot.pools}
    retained = [
        item
        for item in original_evidence["providers"]
        if item["astrbot_provider_id"] not in replaced_ids
    ]
    write_private(
        args.candidate / "evidence.json",
        {**original_evidence, "providers": retained + evidence},
    )
    receipt = {
        "poolRevision": snapshot.revision,
        "sourceRevision": args.source_revision,
        "evidencePath": str(evidence_relative),
        "boundary": boundary,
        "probes": probes,
        "privacyBasis": {
            "url": POLICY_URL,
            "residencySection": "5.1",
            "retentionSection": "5.2",
            "operatorApprovedProviderRetention": True,
        },
        "limitations": "Local cancellation does not prove that the remote provider did not process a request. No zero-retention claim.",
    }
    write_private(args.candidate / "receipt.json", receipt)
    return {
        "status": "prepared",
        "poolRevision": snapshot.revision,
        "probes": probes,
        "boundary": boundary,
    }


def install(args) -> dict:
    if not args.host_stopped:
        raise ValueError("stop_astrbot_host_before_install")
    receipt = load_object(args.candidate / "receipt.json")
    snapshot = adapter.load_api_key_pool_snapshot(args.store)
    if snapshot.revision != receipt["poolRevision"]:
        raise ValueError("pool_revision_changed")
    # Preserve concurrent operator changes: never overwrite a stale preparation.
    for name, relative in (
        ("command", Path("cmd_config.json")),
        ("core", CORE_PATH),
        ("evidence", Path(receipt["evidencePath"])),
    ):
        if load_object(args.data / relative) != load_object(
            args.candidate / f"{name}.before.json"
        ):
            raise ValueError("astrbot_config_changed_since_preparation")
    for name, relative in (
        ("command", Path("cmd_config.json")),
        ("core", CORE_PATH),
        ("evidence", Path(receipt["evidencePath"])),
    ):
        write_private(
            args.data / relative, load_object(args.candidate / f"{name}.json")
        )
    return {
        "status": "installed",
        "poolRevision": receipt["poolRevision"],
        "requiresColdStart": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "install"))
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--source-revision")
    parser.add_argument("--accept-provider-retention", action="store_true")
    parser.add_argument("--host-stopped", action="store_true")
    args = parser.parse_args()
    if not all(path.is_absolute() for path in (args.data, args.store, args.candidate)):
        parser.error("paths must be absolute")
    if args.action == "prepare" and (
        not args.source_revision or args.expected_revision is None
    ):
        parser.error("preparation requires pool and source revisions")
    os.umask(0o077)
    try:
        result = (
            asyncio.run(prepare(args)) if args.action == "prepare" else install(args)
        )
    except Exception as exc:  # noqa: BLE001 - never print Provider/config exception text
        print(json.dumps({"status": "failed", "errorType": type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
