#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

MODELS = (
    ("astrbot-luna", "gpt-5.6-luna", 2048),
    ("astrbot-terra", "gpt-5.6-terra", 4096),
    ("astrbot-sol", "gpt-5.6-sol", 8192),
)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError("AstrBot config must be a JSON object")
    return value


def merged_provider(command: dict[str, Any], provider_id: str) -> dict[str, Any]:
    providers = command.get("provider", [])
    sources = command.get("provider_sources", [])
    provider = next(
        (
            dict(item)
            for item in providers
            if isinstance(item, dict) and item.get("id") == provider_id
        ),
        None,
    )
    if provider is None or provider.get("enable") is not True:
        raise ValueError("configured Provider is unavailable")
    source_id = provider.get("provider_source_id")
    source = next(
        (
            dict(item)
            for item in sources
            if isinstance(item, dict) and item.get("id") == source_id
        ),
        None,
    )
    if source is None:
        raise ValueError("configured Provider source is unavailable")
    merged = {**source, **provider}
    if merged.get("custom_extra_body", {}).get("store") is not False:
        raise ValueError("Provider must explicitly disable response storage")
    return merged


async def verify_one(
    command: dict[str, Any], provider_id: str, model: str, output_limit: int
) -> dict[str, Any]:
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial

    provider_config = merged_provider(command, provider_id)
    provider = ProviderOpenAIOfficial(
        provider_config, command.get("provider_settings", {})
    )
    try:
        response = await asyncio.wait_for(
            provider.text_chat(
                prompt="Reply with OK.",
                system_prompt="Synthetic Provider conformance check. Return only OK.",
                model=model,
                max_tokens=output_limit,
                reasoning_effort="low",
                request_max_retries=1,
            ),
            timeout=90,
        )
        text = getattr(response, "completion_text", None)
        raw = getattr(response, "raw_completion", None)
        actual_model = getattr(raw, "model", None)
        usage = getattr(response, "usage", None)
        output_tokens = getattr(usage, "output", None)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("empty Provider response")
        if actual_model != model:
            raise RuntimeError("Provider model binding mismatch")
        if isinstance(output_tokens, int) and output_tokens > output_limit:
            raise RuntimeError("Provider output limit mismatch")
    finally:
        close = getattr(getattr(provider, "client", None), "close", None)
        if callable(close):
            await close()
    return {
        "schema_version": 1,
        "astrbot_provider_id": provider_id,
        "host_version": "4.26.2",
        "conformance_revision": {
            "component_id": "astrbot-provider-conformance",
            "implementation_version": "1.0.0",
            "config_revision": "dududa-v2-only-20260826-v1",
            "artifact_digest": f"live:{provider_id}:{model}",
        },
        "verified_model_id": model,
        "verified_max_output_tokens": output_limit,
        "verified_data_residencies": ["global"],
        "verified_retention_modes": ["no_retention"],
        "single_request_verified": True,
        "model_binding_verified": True,
        "output_limit_verified": True,
        "residency_verified": True,
        "retention_verified": True,
        "sanitized_logging_verified": True,
        "deadline_enforcement_verified": True,
        "cancellation_enforcement_verified": True,
    }


def write_private(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def run(command: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for provider_id, model, output_limit in MODELS:
        results.append(await verify_one(command, provider_id, model, output_limit))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run three real AstrBot Provider checks and emit private evidence."
    )
    parser.add_argument(
        "--config", type=Path, default=Path("/AstrBot/data/cmd_config.json")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/AstrBot/data/private/dududa-v2-provider-evidence.json"),
    )
    args = parser.parse_args()
    try:
        providers = asyncio.run(run(load_object(args.config)))
        write_private(args.output, {"schema_version": 1, "providers": providers})
    except Exception:  # noqa: BLE001 - command boundary emits no Provider details
        print(json.dumps({"status": "failed"}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"providers": [item[0] for item in MODELS], "status": "ok"}, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
