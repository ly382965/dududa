"""Pure, shared external DeepSeek-to-AstrBot configuration projection."""

from __future__ import annotations

import copy
import json

from .api_key_pools import project_pool_to_astrbot

DEPTHS = {"low": "light", "high": "deep", "max": "maximum"}


def build_candidate(
    command: dict, core: dict, snapshot, *, accept_retention: bool
) -> tuple[dict, dict]:
    if not accept_retention:
        raise ValueError("provider_retention_requires_explicit_approval")
    command, core = copy.deepcopy(command), copy.deepcopy(core)
    models = json.loads(core["runtime_models_json"])
    if len(models) != 3 or {model["tier"] for model in models} != {
        "haiku",
        "sonnet",
        "opus",
    }:
        raise ValueError("expected_three_existing_runtime_tiers")
    provider_ids = {pool.provider_id for pool in snapshot.pools}
    source_ids = {pool.source_id for pool in snapshot.pools}
    for field in ("provider", "provider_sources"):
        ids = [item["id"] for item in command[field]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_astrbot_binding")
    if any(
        item["id"] not in provider_ids and item.get("provider_source_id") in source_ids
        for item in command["provider"]
    ):
        raise ValueError("pool_source_shared_by_unrelated_provider")
    sources, providers = {}, {}
    for pool in snapshot.pools:
        if (
            pool.provider != "deepseek"
            or pool.base_url
            not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
            or pool.protocol != "openai_chat_completion"
            or not pool.model.startswith("deepseek-v4-")
        ):
            raise ValueError("expected_official_deepseek_pool")
        if (
            pool.reasoning_effort not in DEPTHS
            or not 8192 <= pool.max_output_tokens <= 32768
        ):
            raise ValueError("unsupported_reasoning_or_output_budget")
        projection = project_pool_to_astrbot(pool)
        if not projection.enabled:
            raise ValueError("pool_requires_enabled_usable_credentials")
        fragment = projection.for_astrbot()
        # Provider-managed retention is explicit, not a false store=false promise.
        fragment["provider"].pop("custom_extra_body", None)
        sources[pool.source_id] = fragment["provider_source"]
        providers[pool.provider_id] = fragment["provider"]
        model = next(item for item in models if item["tier"] == pool.tier)
        if model["astrbot_provider_id"] != pool.provider_id:
            raise ValueError("existing_runtime_provider_binding_mismatch")
        if model["max_context_tokens"] <= pool.max_output_tokens:
            raise ValueError("output_cap_exceeds_existing_context_budget")
        model.update(
            model_id=pool.model,
            reasoning_depth=DEPTHS[pool.reasoning_effort],
            max_output_tokens=pool.max_output_tokens,
            data_residency="CN",
            retention_mode="provider_managed",
        )
    for field, replacement in (("provider", providers), ("provider_sources", sources)):
        old_ids = {item["id"] for item in command[field]}
        command[field] = [replacement.get(item["id"], item) for item in command[field]]
        command[field].extend(
            value for key, value in replacement.items() if key not in old_ids
        )
    core.update(
        runtime_models_json=json.dumps(models, ensure_ascii=False),
        runtime_allow_provider_retention=True,
    )
    core.setdefault("runtime_direct_output_tokens", 8192)
    core.setdefault("runtime_perception_output_tokens", 4096)
    core.setdefault("runtime_reasoning_output_reserve_tokens", 4096)
    return command, core
