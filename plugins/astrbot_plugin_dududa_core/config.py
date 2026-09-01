from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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
COLLEGE_NOTICE_ROOT = DATA_ROOT / "college-notice-mcp"
COLLEGE_NOTICE_DB = Path(
    os.environ.get(
        "COLLEGE_NOTICE_MCP_DB_PATH",
        str(DATA_ROOT / "college-notice-cache" / "college-notice.sqlite3"),
    )
)
TRAINING_PLAN_ROOT = DATA_ROOT / "training-plan-mcp"
TRAINING_PLAN_DB = Path(
    os.environ.get(
        "TRAINING_PLAN_MCP_DB_PATH",
        str(DATA_ROOT / "training-plan-cache" / "training-plan.sqlite3"),
    )
)
LIBRARY_ROOT = DATA_ROOT / "library-mcp"
LIBRARY_DB = Path(
    os.environ.get(
        "LIBRARY_MCP_DB_PATH",
        str(DATA_ROOT / "library-cache" / "library.sqlite3"),
    )
)
CAMPUS_EVENTS_ROOT = DATA_ROOT / "campus-events-mcp"
CAMPUS_EVENTS_DB = Path(
    os.environ.get(
        "CAMPUS_EVENTS_MCP_DB_PATH",
        str(DATA_ROOT / "campus-events-cache" / "campus-events.sqlite3"),
    )
)
ACADEMIC_CALENDAR_ROOT = DATA_ROOT / "academic-calendar-mcp"
ACADEMIC_CALENDAR_DB = Path(
    os.environ.get(
        "ACADEMIC_CALENDAR_MCP_DB_PATH",
        str(DATA_ROOT / "academic-calendar-cache" / "calendar.sqlite3"),
    )
)
LOCAL_RECS_ROOT = DATA_ROOT / "local-recs-mcp"
LOCAL_RECS_DB = Path(
    os.environ.get(
        "LOCAL_RECS_MCP_DB_PATH",
        str(DATA_ROOT / "local-recs-cache" / "local-recs.sqlite3"),
    )
)


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
