from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .omp import ModelSpec

# Model channels and the services that inherit from them unless bound explicitly.
CHANNELS = ("chat", "summary", "image")
SERVICES = {"qa": "chat", "summary": "summary", "vision": "chat", "image": "image"}

DEFAULT_MODELS = {
    "luna-max": {"model": "openai-codex/gpt-5.6-luna", "thinking": "max"},
    "luna-low": {"model": "openai-codex/gpt-5.6-luna", "thinking": "low"},
    "sol-max": {"model": "openai-codex/gpt-5.6-sol", "thinking": "max"},
    "terra-max": {"model": "openai-codex/gpt-5.6-terra", "thinking": "max"},
}


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
    omp_binary: str = "omp"
    # Registered model names usable by `model set`; values are provider/model + thinking.
    models: dict[str, dict] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    # Defaults for channels (chat/summary/image) and optional per-service overrides.
    model_defaults: dict[str, str] = field(default_factory=lambda: {
        "chat": "luna-max", "summary": "luna-max", "image": "luna-max"})
    service_defaults: dict[str, str] = field(default_factory=lambda: {"vision": "luna-low"})
    # omp built-in tools available to the chat agent besides Host tools.
    agent_builtin_tools: tuple[str, ...] = ("web_search",)
    timeout_seconds: float = 300
    concurrency: int = 2
    bot_names: tuple[str, ...] = ("嘟嘟哒", "dududa")
    admins: tuple[str, ...] = ()
    allowed_scopes: tuple[str, ...] = ()
    proactive_scopes: tuple[str, ...] = ()
    proactive_cooldown_seconds: float = 120
    proactive_policies: dict[str, dict] = field(default_factory=dict)
    # Replies the bot actively produces (commands and addressed agent turns) per conversation window.
    rate_limits: dict[str, float] = field(default_factory=lambda: {"window_seconds": 300, "group": 30, "private": 50})
    mcp_console_url: str | None = None
    qq_gateway_url: str | None = None
    campus_capabilities: tuple[str, ...] = ()
    rules: tuple[dict, ...] = ()
    # Hosts fetched without the outbound proxy (domestic services and QQ media).
    direct_hosts: tuple[str, ...] = (
        "qq.com", "qpic.cn", "bilibili.com", "b23.tv", "hdslb.com", "bilivideo.com", "xiaohongshu.com",
        "xhslink.com", "xhscdn.com", "weixin.qq.com", "ustc.edu.cn", "localhost", "127.0.0.1")
    proxy_url: str | None = None
    # Per-feature configuration, keyed by feature module name.
    features: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.state_dir = (self.state_dir or self.root / "runtime/v3").resolve()
        if not 1 <= self.concurrency <= 8 or self.timeout_seconds <= 0:
            raise ValueError("Invalid concurrency or timeout")
        for name, value in self.models.items():
            ModelSpec(value["model"], value.get("thinking", "max"))
            if not name or " " in name:
                raise ValueError(f"Invalid model name: {name!r}")
        for channel, name in self.model_defaults.items():
            if channel not in CHANNELS or name not in self.models:
                raise ValueError(f"Invalid model default {channel}={name}")
        for service, name in self.service_defaults.items():
            if service not in SERVICES or name not in self.models:
                raise ValueError(f"Invalid service default {service}={name}")
        for rule in self.rules:
            if not isinstance(rule.get("match"), str) or not isinstance(rule.get("reply"), str):
                raise TypeError("Rules require exact match and reply strings")

    @property
    def database(self) -> Path:
        return self.state_dir / "runtime.sqlite3"

    def model(self, name: str) -> ModelSpec:
        value = self.models[name]
        return ModelSpec(value["model"], value.get("thinking", "max"))

    def feature(self, name: str) -> dict:
        return self.features.get(name, {})

    @classmethod
    def load(cls, path: str | None = None) -> Settings:
        root = repository_root()
        values = json.loads(Path(path).read_text()) if path else {}
        values["root"] = root
        if values.get("state_dir"):
            values["state_dir"] = root / values["state_dir"]
        if os.environ.get("DUDUDA_V3_STATE_DIR"):
            values["state_dir"] = Path(os.environ["DUDUDA_V3_STATE_DIR"])
        if os.environ.get("DUDUDA_V3_OMP_BINARY"):
            values["omp_binary"] = os.environ["DUDUDA_V3_OMP_BINARY"]
        if "DUDUDA_V3_QQ_SCOPES" in os.environ:
            values["allowed_scopes"] = tuple(filter(None, os.environ["DUDUDA_V3_QQ_SCOPES"].split(",")))
        values.setdefault("proxy_url", os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
        if "models" in values:
            values["models"] = {**DEFAULT_MODELS, **values["models"]}
        for key in ("allowed_scopes", "proactive_scopes", "campus_capabilities", "rules", "admins",
                    "bot_names", "agent_builtin_tools", "direct_hosts"):
            if key in values:
                values[key] = tuple(values[key])
        return cls(**values)
