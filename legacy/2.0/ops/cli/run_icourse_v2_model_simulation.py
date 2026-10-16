"""Compare Dududa 2.0 answer models on one fixed iCourse Observation.

This is a repository-external, no-send quality sample. The deterministic Runtime
contract separately proves Perception -> Unified MCP -> Observation. This runner
starts at the validated Observation, asks Luna/Terra/Sol for the final answer with
the minimum supported reasoning effort, and asks Luna to review each answer once.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path

if __package__:
    from .run_provider_no_send_shadow import (
        PostJson,
        PrivateProviderConfig,
        ShadowSampleError,
        endpoint_url,
        load_private_provider_config,
        post_json,
    )
else:
    from run_provider_no_send_shadow import (
        PostJson,
        PrivateProviderConfig,
        ShadowSampleError,
        endpoint_url,
        load_private_provider_config,
        post_json,
    )

MODELS = (
    ("gpt-5.6-luna", "haiku"),
    ("gpt-5.6-terra", "sonnet"),
    ("gpt-5.6-sol", "opus"),
)
REVIEW_MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "low"
MAX_RESPONSE_CHARACTERS = 4_000

_ANSWER_SYSTEM = (
    "你是嘟嘟哒 2.0 的 DIRECT_CHAT 总结器。只使用给出的已验证 Observation 回答"
    "当前问题；缺失信息要明确说不知道，不得补写网页搜索结果。自然融入群聊语气，"
    "不要复述人格、工具计划、调用过程、Observation 原文或隐藏思维，只输出一次最终答复。"
)
_REVIEW_SYSTEM = (
    "你是 Luna Review。只检查候选答复是否忠于给定 Observation、是否回答问题、是否"
    "隐藏内部计划和思维过程。不要改写答案，不要输出分析过程，只返回指定 JSON。"
)
_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "passed": {"type": "boolean"},
        "grounded": {"type": "boolean"},
        "useful": {"type": "boolean"},
        "process_hidden": {"type": "boolean"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "issues": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 240},
        },
    },
    "required": [
        "passed",
        "grounded",
        "useful",
        "process_hidden",
        "score",
        "issues",
    ],
}


def load_scenario(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShadowSampleError("simulation_scenario_unavailable") from exc
    required = {
        "schema_version",
        "scenario_id",
        "question",
        "capability_id",
        "mcp_server_id",
        "mcp_tool_name",
        "mcp_arguments",
        "observation",
    }
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise ShadowSampleError("simulation_scenario_invalid")
    if value.get("schema_version") != 1:
        raise ShadowSampleError("simulation_scenario_invalid")
    return value


def _response_text(response: Mapping[str, object]) -> str:
    direct = response.get("output_text")
    fragments = [direct] if isinstance(direct, str) and direct.strip() else []
    outputs = response.get("output")
    if not fragments and isinstance(outputs, list):
        for output in outputs:
            if not isinstance(output, Mapping):
                continue
            content = output.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if (
                    isinstance(item, Mapping)
                    and item.get("type") == "output_text"
                    and isinstance(item.get("text"), str)
                    and str(item["text"]).strip()
                ):
                    fragments.append(str(item["text"]))
    text = "".join(fragments).strip()
    if not text:
        raise ShadowSampleError("simulation_response_empty")
    if len(text) > MAX_RESPONSE_CHARACTERS:
        raise ShadowSampleError("simulation_response_too_large")
    return text


def _usage(response: Mapping[str, object]) -> dict[str, int] | None:
    value = response.get("usage")
    if not isinstance(value, Mapping):
        return None
    result: dict[str, int] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        count = value.get(name)
        if type(count) is int and count >= 0:
            result[name] = count
    return result or None


def _answer_body(model: str, scenario: Mapping[str, object]) -> dict[str, object]:
    payload = {
        "question": scenario["question"],
        "expected_capability": scenario["capability_id"],
        "mcp_call": {
            "server_id": scenario["mcp_server_id"],
            "tool_name": scenario["mcp_tool_name"],
            "arguments": scenario["mcp_arguments"],
        },
        "validated_observation": scenario["observation"],
    }
    return {
        "model": model,
        "instructions": _ANSWER_SYSTEM,
        "input": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "reasoning": {"effort": REASONING_EFFORT},
        "max_output_tokens": 512,
    }


def _review_body(
    candidate_model: str,
    answer: str,
    scenario: Mapping[str, object],
) -> dict[str, object]:
    payload = {
        "question": scenario["question"],
        "expected_capability": scenario["capability_id"],
        "validated_observation": scenario["observation"],
        "candidate_model": candidate_model,
        "candidate_answer": answer,
    }
    return {
        "model": REVIEW_MODEL,
        "instructions": _REVIEW_SYSTEM,
        "input": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "reasoning": {"effort": REASONING_EFFORT},
        "max_output_tokens": 256,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "dududa_icourse_luna_review_v1",
                "strict": True,
                "schema": _REVIEW_SCHEMA,
            }
        },
    }


def _generate(
    model: str,
    tier: str,
    scenario: Mapping[str, object],
    config: PrivateProviderConfig,
    sender: PostJson,
    clock: Callable[[], float],
) -> dict[str, object]:
    started = clock()
    response = sender(
        endpoint_url(config.base_url),
        _answer_body(model, scenario),
        config,
    )
    if response.get("model") != model:
        raise ShadowSampleError("simulation_model_binding_mismatch")
    return {
        "model": model,
        "tier": tier,
        "reasoning_effort": REASONING_EFFORT,
        "answer": _response_text(response),
        "answer_latency_ms": max(0, round((clock() - started) * 1_000)),
        "answer_usage": _usage(response),
    }


def _review(
    candidate: Mapping[str, object],
    scenario: Mapping[str, object],
    config: PrivateProviderConfig,
    sender: PostJson,
    clock: Callable[[], float],
) -> dict[str, object]:
    started = clock()
    response = sender(
        endpoint_url(config.base_url),
        _review_body(str(candidate["model"]), str(candidate["answer"]), scenario),
        config,
    )
    if response.get("model") != REVIEW_MODEL:
        raise ShadowSampleError("simulation_review_model_binding_mismatch")
    try:
        review = json.loads(_response_text(response))
    except json.JSONDecodeError as exc:
        raise ShadowSampleError("simulation_review_not_json") from exc
    required = {
        "passed",
        "grounded",
        "useful",
        "process_hidden",
        "score",
        "issues",
    }
    if not isinstance(review, Mapping) or set(review) != required:
        raise ShadowSampleError("simulation_review_invalid")
    if (
        any(type(review[name]) is not bool for name in required - {"score", "issues"})
        or type(review["score"]) is not int
        or not 0 <= review["score"] <= 100
        or not isinstance(review["issues"], list)
        or any(not isinstance(item, str) for item in review["issues"])
    ):
        raise ShadowSampleError("simulation_review_invalid")
    return {
        "model": REVIEW_MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "latency_ms": max(0, round((clock() - started) * 1_000)),
        "usage": _usage(response),
        **dict(review),
    }


def run_simulation(
    scenario: Mapping[str, object],
    config: PrivateProviderConfig,
    *,
    sender: PostJson = post_json,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, object]:
    candidates = [
        _generate(model, tier, scenario, config, sender, clock)
        for model, tier in MODELS
    ]
    reviews = [
        _review(candidate, scenario, config, sender, clock)
        for candidate in candidates
    ]
    return {
        "schema_version": 1,
        "scenario": dict(scenario),
        "review_model": REVIEW_MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "provider_calls": len(candidates) + len(reviews),
        "output_calls": 0,
        "candidates": [
            {**candidate, "review": review}
            for candidate, review in zip(candidates, reviews, strict=True)
        ],
    }


def sanitized_summary(result: Mapping[str, object]) -> dict[str, object]:
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        raise ShadowSampleError("simulation_result_invalid")
    return {
        "schema_version": 1,
        "scenario_id": result["scenario"]["scenario_id"],
        "reasoning_effort": result["reasoning_effort"],
        "review_model": result["review_model"],
        "provider_calls": result["provider_calls"],
        "output_calls": result["output_calls"],
        "models": [
            {
                "model": item["model"],
                "tier": item["tier"],
                "answer_latency_ms": item["answer_latency_ms"],
                "review_passed": item["review"]["passed"],
                "review_score": item["review"]["score"],
            }
            for item in candidates
        ],
    }


def write_private_result(path: Path, result: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a no-send Dududa 2.0 iCourse model comparison and Luna review."
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path("tests/fixtures/mcp/icourse-v2-wu-tian-simulation.json"),
    )
    parser.add_argument(
        "--codex-config",
        type=Path,
        default=Path.home() / ".codex" / "config.toml",
    )
    parser.add_argument(
        "--auth-file",
        type=Path,
        default=Path.home() / ".codex" / "auth.json",
    )
    parser.add_argument("--provider")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()

    try:
        scenario = load_scenario(args.scenario)
        config = load_private_provider_config(
            args.codex_config,
            args.auth_file,
            provider_name=args.provider,
            timeout_seconds=args.timeout_seconds,
        )
        result = run_simulation(scenario, config)
        write_private_result(args.result, result)
        summary = sanitized_summary(result)
    except ShadowSampleError as exc:
        print(
            json.dumps({"error": str(exc)}, ensure_ascii=False, separators=(",", ":")),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    return 0 if all(item["review_passed"] for item in summary["models"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
