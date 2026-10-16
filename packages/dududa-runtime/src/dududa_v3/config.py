from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def repository_root() -> Path:
    configured = os.environ.get("DUDUDA_REPOSITORY")
    if configured:
        return Path(configured).resolve()
    for path in (Path.cwd(), *Path.cwd().parents, *Path(__file__).resolve().parents):
        if (path / "configs/personas/dududa.md").exists():
            return path
    raise ValueError("Set DUDUDA_REPOSITORY to the Dududa checkout")


@dataclass
class Settings:
    root: Path = field(default_factory=repository_root)
    state_dir: Path | None = None
    codex_binary: str = "codex"
    model: str | None = None
    timeout_seconds: float = 180
    concurrency: int = 2
    allowed_scopes: tuple[str, ...] = ()
    proactive_scopes: tuple[str, ...] = ()
    proactive_cooldown_seconds: float = 120
    mcp_console_url: str | None = None
    campus_capabilities: tuple[str, ...] = ()
    rules: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.state_dir = (self.state_dir or self.root / "runtime/v3").resolve()
        if not 1 <= self.concurrency <= 8 or self.timeout_seconds <= 0:
            raise ValueError("Invalid concurrency or timeout")
        for rule in self.rules:
            if not isinstance(rule.get("match"), str) or not isinstance(rule.get("reply"), str):
                raise TypeError("Rules require exact match and reply strings")

    @property
    def database(self) -> Path:
        return self.state_dir / "runtime.sqlite3"

    @classmethod
    def load(cls, path: str | None = None) -> Settings:
        root = repository_root()
        values = json.loads(Path(path).read_text()) if path else {}
        values["root"] = root
        if values.get("state_dir"):
            values["state_dir"] = root / values["state_dir"]
        if os.environ.get("DUDUDA_V3_STATE_DIR"):
            values["state_dir"] = Path(os.environ["DUDUDA_V3_STATE_DIR"])
        if os.environ.get("DUDUDA_V3_CODEX_BINARY"):
            values["codex_binary"] = os.environ["DUDUDA_V3_CODEX_BINARY"]
        if os.environ.get("DUDUDA_V3_MODEL"):
            values["model"] = os.environ["DUDUDA_V3_MODEL"]
        if "DUDUDA_V3_QQ_SCOPES" in os.environ:
            values["allowed_scopes"] = tuple(filter(None, os.environ["DUDUDA_V3_QQ_SCOPES"].split(",")))
        for key in ("allowed_scopes", "proactive_scopes", "campus_capabilities", "rules"):
            if key in values:
                values[key] = tuple(values[key])
        return cls(**values)
