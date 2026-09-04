"""Bounded synthetic probes of saved official DeepSeek pools. Never print secrets/content."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("dududa_key_projection", ROOT / "apps/astrbot-plugins/astrbot_plugin_dududa_core/adapters/api_key_pools.py")
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)


async def probe(pool, effort):
    if urlsplit(pool.base_url).hostname != "api.deepseek.com" or pool.base_url not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
        raise ValueError("probe_requires_official_deepseek_url")
    credential = next((key for key in pool.ordered_usable_keys() if key.secret), None)
    if credential is None:
        raise ValueError("probe_requires_saved_usable_key")
    started = time.monotonic()
    result = {"tier": pool.tier, "model": pool.model, "effort": effort}
    async with httpx.AsyncClient(timeout=90, trust_env=False, follow_redirects=False) as client:
        try:
            response = await client.post(pool.base_url.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {credential.secret}"}, json={
                "model": pool.model, "messages": [{"role": "user", "content": "Health check: reply only OK."}],
                "thinking": {"type": "enabled"}, "reasoning_effort": effort, "max_tokens": 4096, "stream": False,
            })
            result["status"] = response.status_code
            if response.status_code == 200:
                data = response.json()
                choice = data.get("choices", [{}])[0]
                result.update(nonempty=bool(choice.get("message", {}).get("content", "").strip()),
                              finishReason=choice.get("finish_reason"), outputTokens=data.get("usage", {}).get("completion_tokens"))
            else:
                result["nonempty"] = False
        except Exception as exc:
            result.update(nonempty=False, errorType=type(exc).__name__)
    result["latencyMs"] = round((time.monotonic() - started) * 1000)
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    snapshot = adapter.load_api_key_pool_snapshot(args.store)
    efforts = {"haiku": "low", "sonnet": "high", "opus": "max"}
    results = await asyncio.gather(*(probe(pool, efforts[pool.tier]) for pool in snapshot.pools))
    print(json.dumps({"storeRevision": snapshot.revision, "probes": results}, ensure_ascii=True), flush=True)
    return 0 if all(item.get("nonempty") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
