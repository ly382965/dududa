"""Start a separate AstrBot instance for the fixed recording scenarios."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
BOT_ID = "1000000001"
GROUP_ID = "2000000001"
CONTAINER = "dududa-recording-astrbot"


def initial_policy() -> dict:
    def axis(preferred, allowed):
        return {"mode": "adaptive", "preferred": preferred, "allowed": allowed}

    return {
        "schemaVersion": 1,
        "scope": {
            "accountId": f"qq-{BOT_ID}",
            "conversationId": f"qq-{BOT_ID}:group:{GROUP_ID}",
        },
        "enabled": True,
        "modelTier": axis("sonnet", ["haiku", "sonnet", "opus"]),
        "reasoning": axis("medium", ["low", "medium", "high"]),
        "answerProfile": axis("medium", ["short", "medium", "long"]),
        "replyIntensity": axis("normal", ["quiet", "normal", "active"]),
        "contextLength": axis("standard", ["standard", "extended"]),
        "groupChatStyle": axis(
            "natural", ["restrained", "natural", "lively", "technical"]
        ),
        "proactiveTalk": {
            "probabilityPercent": 100,
            "cooldownSeconds": 5,
            "maximumPerHour": 60,
            "minimumMessages": 20,
        },
        "plugins": {"social.proactive_talk": "on", "icourse.read": "off"},
        "adaptivePlugins": ["icourse.read"],
    }


def write_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state", type=Path, default=ROOT.parent / "dududa-recording-state"
    )
    parser.add_argument("--source-container", default="dududa-astrbot-1")
    parser.add_argument("--source-console", default="dududa-mcp-console-1")
    parser.add_argument("--port", type=int, default=6186)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = json.loads(
        subprocess.check_output(["docker", "inspect", args.source_container])
    )[0]

    def read_live(path: str) -> bytes:
        return subprocess.check_output(
            ["docker", "exec", args.source_container, "cat", path]
        )

    # Copy provider settings only into the private rehearsal directory; QQ is disconnected.
    config = json.loads(read_live("/AstrBot/data/cmd_config.json"))
    config["platform"] = []
    config["admins_id"] = ["3000000001"]
    config["disable_metrics"] = True
    config["plugin_set"] = [
        "astrbot_plugin_dududa_core",
        "astrbot_plugin_emoji_kitchen",
        "astrbot_plugin_reread",
        "astrbot_plugin_arc_proxy",
        "astrbot_plugin_sub2api_readonly",
    ]
    config["dashboard"].update(
        host="0.0.0.0", port=6185, jwt_secret=secrets.token_urlsafe(32)
    )
    write_private(
        state / "data/cmd_config.json", json.dumps(config, ensure_ascii=False).encode()
    )
    core = json.loads(
        read_live("/AstrBot/data/config/astrbot_plugin_dududa_core_config.json")
    )
    core.update(
        rollout_allowlisted_groups=[GROUP_ID],
        rollout_revision="recording-rehearsal-v1",
        rollout_delivery_enabled=True,
        rollout_kill_switch=False,
        rollout_mode="canary",
        proactive_talk_enabled=True,
        owners=["3000000001"],
        global_admins=[],
        group_admins={},
        trusted_users=[],
    )
    # This short live demo uses direct synthesis; keep optional extended thinking off.
    # The three model tiers still route normally and keep their verified limits.
    models = json.loads(core["runtime_models_json"])
    for model in models:
        if model["tier"] != "haiku":
            model["reasoning_depth"] = "off"
    core["runtime_models_json"] = json.dumps(models)
    core.update(
        runtime_direct_output_tokens=8192, runtime_reasoning_output_reserve_tokens=0
    )
    write_private(
        state / "data/config/astrbot_plugin_dududa_core_config.json",
        json.dumps(core, ensure_ascii=False).encode(),
    )
    evidence = str(core["runtime_provider_evidence_path"])
    write_private(
        state / "data/private/dududa-v2-provider-evidence.json", read_live(evidence)
    )
    course_cache = state / "data/icourse-cache/icourse.sqlite3"
    if not course_cache.exists():
        snapshot = subprocess.check_output(
            [
                "docker",
                "exec",
                args.source_container,
                "python",
                "-c",
                "import sqlite3,sys; db=sqlite3.connect('file:/AstrBot/data/icourse-cache/icourse.sqlite3?mode=ro',uri=True); sys.stdout.buffer.write(db.serialize())",
            ]
        )
        write_private(course_cache, snapshot)
    for service, filename in (
        ("library", "library.sqlite3"),
        ("local-recs", "local-recs.sqlite3"),
        ("training-plan", "plans.sqlite3"),
        ("campus-events", "events.sqlite3"),
        ("college-notice", "notices.sqlite3"),
    ):
        target = state / f"data/{service}-cache/{filename}"
        if not target.exists():
            source = f"/AstrBot/data/{service}-cache/{filename}"
            snapshot = subprocess.check_output(
                [
                    "docker",
                    "exec",
                    args.source_console,
                    "python",
                    "-c",
                    "import sqlite3,sys; db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); sys.stdout.buffer.write(db.serialize())",
                    source,
                ]
            )
            write_private(target, snapshot)
    pools = ROOT.parent / "dududa-state/api-keys/api-keys.json"
    write_private(state / "api-keys/api-keys.json", pools.read_bytes())
    policy = initial_policy()
    policy_key = f"{quote(policy['scope']['accountId'], safe='')}::{quote(policy['scope']['conversationId'], safe='')}"
    write_private(
        state / "agent/agent-policies.json",
        json.dumps(
            {"schemaVersion": 1, "policies": {policy_key: policy}}, ensure_ascii=False
        ).encode(),
    )
    token_file = state / "secrets/onebot_access_token"
    if not token_file.exists():
        write_private(token_file, secrets.token_urlsafe(32).encode())

    existing = subprocess.run(
        ["docker", "inspect", CONTAINER],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if existing.returncode == 0:
        if not args.restart:
            raise SystemExit(
                f"{CONTAINER} already exists; use --restart to apply current source"
            )
        subprocess.run(
            ["docker", "rm", "-f", CONTAINER], check=True, stdout=subprocess.DEVNULL
        )
    network = next(iter(metadata["NetworkSettings"]["Networks"]))
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER,
        "--network",
        network,
        "--publish",
        f"127.0.0.1:{args.port}:6185",
        "--env",
        "PYTHONPATH=/opt/dududa/live-agent/src",
        "--env",
        "USTC_CAS_CREDENTIALS_FILE=/run/secrets/ustc-cas.toml",
        "--env",
        "DUDUDA_AGENT_POLICY_PATH=/var/lib/dududa/agent/agent-policies.json",
        "--env",
        "DUDUDA_API_KEY_STORE_PATH=/run/dududa/api-keys/api-keys.json",
    ]
    mounts = [
        (state / "data", "/AstrBot/data", "rw"),
        (state / "agent", "/var/lib/dududa/agent", "ro"),
        (state / "api-keys", "/run/dududa/api-keys", "ro"),
        (ROOT / "packages/dududa-agent", "/opt/dududa/live-agent", "ro"),
        (ROOT / "apps/astrbot-plugins", "/AstrBot/data/plugins", "ro"),
        (ROOT / "configs", "/opt/dududa/config", "ro"),
        (ROOT / "ops/cli", "/opt/dududa/scripts", "ro"),
    ]
    for service in (
        "icourse",
        "ustc-campus",
        "notifai",
        "library",
        "local-recs",
        "training-plan",
        "campus-events",
        "college-notice",
    ):
        mounts.append(
            (ROOT / f"services/mcp/{service}", f"/AstrBot/data/{service}-mcp", "ro")
        )
    for mount in metadata["Mounts"]:
        if mount["Destination"] == "/run/secrets/ustc-cas.toml":
            mounts.append((Path(mount["Source"]), mount["Destination"], "ro"))
        if mount["Destination"] == "/AstrBot/data":
            for asset in ("import", "catalog", "renderer-assets"):
                arc_path = f"plugin_data/astrbot_plugin_arc_proxy/{asset}"
                mounts.append(
                    (
                        Path(mount["Source"]) / arc_path,
                        f"/AstrBot/data/{arc_path}",
                        "ro",
                    )
                )
    for source, target, access in mounts:
        command.extend(["--volume", f"{source}:{target}:{access}"])
    command.append(metadata["Config"]["Image"])
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    print(f"Recording Runtime: http://127.0.0.1:{args.port}", flush=True)
    key = subprocess.check_output(
        [
            "docker",
            "exec",
            CONTAINER,
            "python",
            "/opt/dududa/scripts/provision_astrbot_plugin_key.py",
        ]
    )
    write_private(state / "secrets/astrbot_plugin_api_key", key)
    status_url = f"http://127.0.0.1:{args.port}/api/v1/plugins/extensions/astrbot_plugin_dududa_core/runtime/status"
    for _ in range(60):
        try:
            with urlopen(
                Request(status_url, headers={"X-API-Key": key.decode().strip()}),
                timeout=2,
            ) as response:
                if json.load(response).get("data", {}).get("ready"):
                    break
        except (OSError, ValueError):
            pass
        time.sleep(1)
    else:
        raise SystemExit("Recording Runtime did not become ready")
    subprocess.run(
        [
            "docker",
            "exec",
            "-d",
            "-e",
            "USTC_CAS_CREDENTIALS_FILE=/run/secrets/ustc-cas.toml",
            CONTAINER,
            "python",
            "-m",
            "dududa_mcp_console",
            "--host",
            "0.0.0.0",
            "--port",
            "8090",
        ],
        check=True,
    )
    print("Recording API key prepared; no QQ platform is connected.", flush=True)


if __name__ == "__main__":
    main()
