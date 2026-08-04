from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dududa.rollout import RolloutControlConfig, parse_rollout_control_config


PLUGIN_NAME = "astrbot_plugin_dududa_core"
DATA_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = DATA_ROOT / "config"
PLUGIN_DATA_DIR = DATA_ROOT / "plugin_data" / PLUGIN_NAME
PLUGIN_CONFIG_PATH = CONFIG_DIR / f"{PLUGIN_NAME}_config.json"
ASTRBOT_CONFIG_PATH = DATA_ROOT / "cmd_config.json"
ICOURSE_ROOT = DATA_ROOT / "icourse-mcp"
ICOURSE_DB_PATH = Path(
    os.environ.get(
        "ICOURSE_MCP_DB_PATH",
        str(DATA_ROOT / "icourse-cache" / "icourse.sqlite3"),
    )
)
ROLLOUT_LEDGER_PATH = PLUGIN_DATA_DIR / "rollout.sqlite3"


def ensure_dirs() -> None:
    PLUGIN_DATA_DIR.mkdir(parents=True, exist_ok=True)


def str_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def save_json(path: Path, value: Any) -> None:
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_astrbot_config() -> dict[str, Any]:
    try:
        return json.loads(ASTRBOT_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def save_astrbot_config(value: dict[str, Any]) -> None:
    save_json(ASTRBOT_CONFIG_PATH, value)


def load_plugin_config() -> dict[str, Any]:
    return load_json(PLUGIN_CONFIG_PATH, {})


def save_plugin_config(value: dict[str, Any]) -> None:
    save_json(PLUGIN_CONFIG_PATH, value)


def default_rollout_config() -> RolloutControlConfig:
    return parse_rollout_control_config(
        {
            "schema_version": 1,
            "mode": "off",
            "revision": "rollout-off-v1",
            "delivery_enabled": False,
            "allowlisted_group_ids": [],
            "kill_switch": True,
            "tools_enabled": False,
            "memory_enabled": False,
            "maximum_text_bytes": 8_192,
            "shadow_max_in_flight": 2,
            "shadow_timeout_ms": 30_000,
            "canary_timeout_ms": 60_000,
        }
    )


class AstrBotRolloutControlProvider:
    def __init__(
        self,
        initial_config: dict[str, Any] | None,
        *,
        path: Path = PLUGIN_CONFIG_PATH,
    ) -> None:
        self._initial = dict(initial_config or {})
        self._path = path

    def current(self) -> RolloutControlConfig:
        raw = self._read_current_mapping()
        defaults = default_rollout_config()
        return parse_rollout_control_config(
            {
                "schema_version": 1,
                "mode": raw.get("rollout_mode", defaults.mode.value),
                "revision": raw.get("rollout_revision", defaults.revision),
                "delivery_enabled": raw.get(
                    "rollout_delivery_enabled", defaults.delivery_enabled
                ),
                "allowlisted_group_ids": raw.get(
                    "rollout_allowlisted_groups",
                    list(defaults.allowlisted_group_ids),
                ),
                "kill_switch": raw.get("rollout_kill_switch", defaults.kill_switch),
                "tools_enabled": raw.get(
                    "rollout_tools_enabled", defaults.tools_enabled
                ),
                "memory_enabled": raw.get(
                    "rollout_memory_enabled", defaults.memory_enabled
                ),
                "maximum_text_bytes": raw.get(
                    "rollout_maximum_text_bytes", defaults.maximum_text_bytes
                ),
                "shadow_max_in_flight": raw.get(
                    "rollout_shadow_max_in_flight", defaults.shadow_max_in_flight
                ),
                "shadow_timeout_ms": raw.get(
                    "rollout_shadow_timeout_ms",
                    int(defaults.shadow_timeout.total_seconds() * 1_000),
                ),
                "canary_timeout_ms": raw.get(
                    "rollout_canary_timeout_ms",
                    int(defaults.canary_timeout.total_seconds() * 1_000),
                ),
            }
        )

    def _read_current_mapping(self) -> dict[str, Any]:
        if not self._path.exists():
            return dict(self._initial)
        value = json.loads(self._path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("rollout plugin config must be an object")
        return value
