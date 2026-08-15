"""Run one real, synthetic, no-send Provider sample for each Dududa tier.

The runner reads the Endpoint and API key from repository-external Codex files.
It never imports a QQ connector or Output adapter, and it discards model text and
Provider error bodies.  The persisted receipt contains only bounded operational
metadata suitable for an isolated S23 candidate check.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import tomllib

_SAMPLES = (
    ("gpt-5.6-luna", "haiku"),
    ("gpt-5.6-terra", "sonnet"),
    ("gpt-5.6-sol", "opus"),
)
_INSTRUCTIONS = "Return one short acknowledgement."
_INPUT = "Synthetic no-send shadow check."
_MAX_RESPONSE_BYTES = 1_000_000


class ShadowSampleError(RuntimeError):
    """Content-free Provider sample failure."""


@dataclass(frozen=True, slots=True)
class PrivateProviderConfig:
    base_url: str
    api_key: str
    timeout_seconds: float


PostJson = Callable[
    [str, Mapping[str, object], PrivateProviderConfig], Mapping[str, object]
]


def load_private_provider_config(
    codex_config_path: Path,
    auth_path: Path,
    *,
    provider_name: str | None,
    timeout_seconds: float,
) -> PrivateProviderConfig:
    if timeout_seconds <= 0:
        raise ShadowSampleError("invalid_timeout")
    try:
        codex_config = tomllib.loads(codex_config_path.read_text(encoding="utf-8"))
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ShadowSampleError("private_config_unavailable") from exc
    selected = provider_name or codex_config.get("model_provider")
    providers = codex_config.get("model_providers")
    if (
        not isinstance(selected, str)
        or not selected.strip()
        or not isinstance(providers, dict)
    ):
        raise ShadowSampleError("private_provider_missing")
    provider = providers.get(selected)
    if not isinstance(provider, dict):
        raise ShadowSampleError("private_provider_missing")
    base_url = provider.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ShadowSampleError("private_base_url_missing")
    if not isinstance(auth, dict):
        raise ShadowSampleError("private_auth_invalid")
    api_key = auth.get("OPENAI_API_KEY")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ShadowSampleError("private_api_key_missing")
    return PrivateProviderConfig(
        base_url=base_url.strip(),
        api_key=api_key.strip(),
        timeout_seconds=float(timeout_seconds),
    )


def endpoint_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base + "/responses"
    return base + "/v1/responses"


def post_json(
    url: str,
    body: Mapping[str, object],
    config: PrivateProviderConfig,
) -> Mapping[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "dududa-s23-no-send-shadow/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=config.timeout_seconds
        ) as response:
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ShadowSampleError("provider_http_failure") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ShadowSampleError("provider_network_failure") from exc
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise ShadowSampleError("provider_response_too_large")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ShadowSampleError("provider_response_not_json") from exc
    if not isinstance(value, Mapping):
        raise ShadowSampleError("provider_response_not_object")
    return value


def _has_output_text(response: Mapping[str, object]) -> bool:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return True
    outputs = response.get("output")
    if not isinstance(outputs, list):
        return False
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
                and bool(str(item["text"]).strip())
            ):
                return True
    return False


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


def sample_model(
    model: str,
    tier: str,
    config: PrivateProviderConfig,
    *,
    sender: PostJson = post_json,
) -> dict[str, object]:
    started = time.perf_counter()
    success = False
    usage: dict[str, int] | None = None
    try:
        response = sender(
            endpoint_url(config.base_url),
            {
                "model": model,
                "instructions": _INSTRUCTIONS,
                "input": _INPUT,
                "max_output_tokens": 32,
            },
            config,
        )
        success = response.get("model") == model and _has_output_text(response)
        usage = _usage(response)
    except Exception:  # noqa: BLE001
        # Provider details can contain request data, URLs, or credentials.  The
        # sanitized receipt intentionally records only success/failure.
        success = False
    return {
        "model": model,
        "tier": tier,
        "success": success,
        "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
        "usage": usage,
        "provider_calls": 1,
        "output_calls": 0,
    }


def run_samples(
    config: PrivateProviderConfig,
    *,
    sender: PostJson = post_json,
) -> list[dict[str, object]]:
    with ThreadPoolExecutor(max_workers=len(_SAMPLES)) as executor:
        futures = [
            executor.submit(sample_model, model, tier, config, sender=sender)
            for model, tier in _SAMPLES
        ]
        return [future.result() for future in futures]


def write_receipt(path: Path, value: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Luna/Terra/Sol once each without any QQ Output path."
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
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    try:
        config = load_private_provider_config(
            args.codex_config,
            args.auth_file,
            provider_name=args.provider,
            timeout_seconds=args.timeout_seconds,
        )
        receipt = run_samples(config)
        write_receipt(args.receipt, receipt)
    except ShadowSampleError:
        return 2
    print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
    return 0 if all(item["success"] for item in receipt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
