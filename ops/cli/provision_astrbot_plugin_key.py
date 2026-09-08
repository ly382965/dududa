#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a plugin-scoped AstrBot API key for the Dududa Web service."
    )
    parser.add_argument("--config", type=Path, default=Path("/AstrBot/data/cmd_config.json"))
    parser.add_argument("--api-url", default="http://127.0.0.1:6185/api/v1")
    parser.add_argument("--wait-seconds", type=float, default=90.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        deadline = time.monotonic() + max(0.0, args.wait_seconds)
        with httpx.Client(timeout=20, trust_env=False) as client:
            while True:
                try:
                    config = json.loads(args.config.read_text(encoding="utf-8"))
                    secret = config.get("dashboard", {}).get("jwt_secret")
                    if not isinstance(secret, str) or not secret:
                        raise RuntimeError("AstrBot dashboard JWT secret is unavailable")
                    now = datetime.now(timezone.utc)
                    token = jwt.encode(
                        {
                            "username": "dududa-web-plugin-manager",
                            "iat": now,
                            "exp": now + timedelta(minutes=5),
                        },
                        secret,
                        algorithm="HS256",
                    )
                    response = client.post(
                        f"{args.api_url.rstrip('/')}/api-keys",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"name": "Dududa Web Plugin Manager", "scopes": ["plugin"]},
                    )
                    if response.status_code not in {502, 503}:
                        break
                    if time.monotonic() >= deadline:
                        break
                except (OSError, json.JSONDecodeError, httpx.TransportError, RuntimeError):
                    if time.monotonic() >= deadline:
                        raise
                time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
        payload = response.json()
        api_key = payload.get("data", {}).get("api_key") if isinstance(payload, dict) else None
        if response.status_code != 200 or not isinstance(api_key, str) or not api_key:
            raise RuntimeError("AstrBot rejected plugin API key provisioning")
        sys.stdout.write(api_key)
        return 0
    except Exception as exc:
        print(f"plugin API key provisioning failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
