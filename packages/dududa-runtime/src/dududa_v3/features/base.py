"""Feature contract: commands, passive observers, scheduled jobs, agent tools and task switches.

Every module in ``dududa_v3.features`` (other than this one) exposes
``register(registry: Registry) -> None`` and is discovered automatically.

Replies are lists of delivery *actions* consumed by the QQ bridge:

- ``{"type": "text", "text": str}``
- ``{"type": "mention", "user_id": str}`` (QQ group at; does not alter ``plain_text``)
- ``{"type": "image", "data": base64, "mime": str}`` or ``{"type": "image", "url": str}``
- ``{"type": "face", "id": str}`` (QQ system face)
- ``{"type": "forward", "nodes": [{"name": str, "actions": [text/image actions]}]}``
- ``{"type": "reaction", "message_id": str, "emoji_id": str}`` (NapCat ``set_msg_emoji_like``)
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

if TYPE_CHECKING:
    from ..config import Settings
    from ..omp import OmpResult
    from ..runtime import Runtime
    from ..store import Store

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


class FeatureError(RuntimeError):
    """A user-presentable feature failure."""


# ---------------------------------------------------------------- messages


@dataclass
class Sender:
    id: str
    name: str = ""
    card: str = ""
    nickname: str = ""
    role: str = "member"

    @property
    def display(self) -> str:
        return self.card or self.nickname or self.name or self.id


@dataclass
class Inbound:
    """One incoming platform message, with identity supplied by the trusted adapter."""

    account_id: str
    conversation_id: str
    message_id: str
    text: str
    sender: Sender
    source: str = "qq"
    mentioned: bool = False
    preview: bool = False
    segments: list[dict] = field(default_factory=list)
    reply: dict | None = None
    mentions: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    timestamp: float | None = None

    @property
    def kind(self) -> str:
        if ":group:" in self.conversation_id:
            return "group"
        if ":private:" in self.conversation_id:
            return "private"
        return "web"

    @property
    def is_group(self) -> bool:
        return self.kind == "group"

    @property
    def peer_id(self) -> str:
        return self.conversation_id.rsplit(":", 1)[-1]

    @property
    def bot_id(self) -> str:
        return self.account_id.removeprefix("qq-")

    @property
    def scope(self) -> str:
        return f"{self.account_id}/{self.conversation_id}"

    @classmethod
    def from_request(cls, request: dict) -> Inbound:
        raw = request.get("sender") if isinstance(request.get("sender"), dict) else {}
        sender = Sender(id=request["user_id"], name=str(raw.get("name") or "")[:120],
                        card=str(raw.get("card") or "")[:120], nickname=str(raw.get("nickname") or "")[:120],
                        role=str(raw.get("role") or "member")[:20])
        return cls(account_id=request["account_id"], conversation_id=request["conversation_id"],
                   message_id=request["message_id"], text=request["text"], sender=sender,
                   source=request.get("source", "web"), mentioned=bool(request.get("mentioned")),
                   preview=bool(request.get("preview")),
                   segments=[s for s in request.get("segments") or [] if isinstance(s, dict)],
                   reply=request.get("reply") if isinstance(request.get("reply"), dict) else None,
                   mentions=[m for m in request.get("mentions") or [] if isinstance(m, dict)],
                   images=[i for i in request.get("images") or [] if isinstance(i, dict)],
                   timestamp=request.get("timestamp") if isinstance(request.get("timestamp"), (int, float)) else None)


class Reply:
    """Ordered delivery actions; ``plain_text`` is what Web preview shows."""

    def __init__(self, *actions: dict):
        self.actions: list[dict] = list(actions)

    @classmethod
    def of_text(cls, text: str) -> Reply:
        return cls({"type": "text", "text": text})

    def text(self, text: str) -> Reply:
        if text:
            self.actions.append({"type": "text", "text": text})
        return self

    def mention(self, user_id: str) -> Reply:
        self.actions.append({"type": "mention", "user_id": str(user_id)})
        return self

    def image(self, data: bytes | None = None, *, url: str | None = None, mime: str = "image/png") -> Reply:
        if data is not None:
            self.actions.append({"type": "image", "data": base64.b64encode(data).decode(), "mime": mime})
        elif url:
            self.actions.append({"type": "image", "url": url})
        return self

    def face(self, face_id: str) -> Reply:
        self.actions.append({"type": "face", "id": str(face_id)})
        return self

    def forward(self, nodes: list[dict]) -> Reply:
        self.actions.append({"type": "forward", "nodes": nodes})
        return self

    def reaction(self, message_id: str, emoji_id: str) -> Reply:
        self.actions.append({"type": "reaction", "message_id": message_id, "emoji_id": str(emoji_id)})
        return self

    @property
    def plain_text(self) -> str:
        parts = []
        for action in self.actions:
            if action["type"] == "text":
                parts.append(action["text"])
            elif action["type"] == "image":
                parts.append("[图片]")
            elif action["type"] == "face":
                parts.append("[表情]")
            elif action["type"] == "forward":
                parts.append("\n".join(item.get("text", "") for node in action["nodes"]
                                       for item in node.get("actions", []) if item.get("type") == "text"))
            elif action["type"] == "reaction":
                parts.append(f"[回应表情 {action['emoji_id']}]")
            elif action["type"] == "file":
                parts.append(f"[文件 {action.get('name', '')}]")
        return "\n".join(part for part in parts if part)

    def __bool__(self) -> bool:
        return bool(self.actions)


@dataclass
class Delegate:
    """A command asking the agent to answer, optionally as a chat summary."""

    prompt: str
    summary: bool = False


# ---------------------------------------------------------------- contexts


class Toolkit:
    """Shared helpers for every feature context."""

    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    @property
    def settings(self) -> Settings:
        return self.runtime.settings

    @property
    def store(self) -> Store:
        return self.runtime.store

    def config(self, feature: str) -> dict:
        return self.settings.feature(feature)

    def state_dir(self, feature: str) -> Path:
        path = self.settings.state_dir / "features" / feature
        path.mkdir(parents=True, exist_ok=True)
        return path

    def kv_get(self, feature: str, key: str, default: Any = None) -> Any:
        return self.store.kv_get(feature, key, default)

    def kv_set(self, feature: str, key: str, value: Any) -> None:
        self.store.kv_set(feature, key, value)

    def enabled(self, task: str) -> bool:
        return self.runtime.task_enabled(task)

    async def fetch(self, url: str, *, headers: dict | None = None, data: bytes | None = None,
                    timeout: float = 20, max_bytes: int = 16 * 1024 * 1024,
                    proxy: bool | None = None) -> tuple[bytes, dict[str, str], str]:
        """HTTP(S) request; returns (body, lowercase headers, final URL).

        ``proxy=None`` routes domestic ``direct_hosts`` directly and everything
        else through the configured outbound proxy.
        """
        return await asyncio.to_thread(self._fetch, url, headers or {}, data, timeout, max_bytes, proxy)

    async def fetch_json(self, url: str, **kwargs: Any) -> Any:
        body, _, _ = await self.fetch(url, headers={"Accept": "application/json", **kwargs.pop("headers", {})},
                                      **kwargs)
        return json.loads(body.decode("utf-8"))

    def _fetch(self, url: str, headers: dict, data: bytes | None, timeout: float, max_bytes: int,
               proxy: bool | None) -> tuple[bytes, dict[str, str], str]:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FeatureError("只支持 http(s) 链接")
        host = parts.hostname.lower()
        direct = any(host == item or host.endswith("." + item) for item in self.settings.direct_hosts)
        use_proxy = (not direct) if proxy is None else proxy
        proxies = {"http": self.settings.proxy_url, "https": self.settings.proxy_url} \
            if use_proxy and self.settings.proxy_url else {}
        opener = build_opener(ProxyHandler(proxies))
        request = Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", **headers})
        # Idempotent GETs get one retry: the outbound proxy occasionally drops a connection.
        for attempt in range(2 if data is None else 1):
            try:
                with opener.open(request, timeout=timeout) as response:
                    body = response.read(max_bytes + 1)
                    if len(body) > max_bytes:
                        raise FeatureError("响应过大")
                    info = {key.lower(): value for key, value in response.headers.items()}
                    if info.get("content-encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body, info, response.geturl()
            except HTTPError as exc:
                raise FeatureError(f"请求失败（HTTP {exc.code}）") from None
            except (URLError, OSError, TimeoutError) as exc:
                if attempt == 0 and data is None:
                    continue
                raise FeatureError(f"网络请求失败：{type(exc).__name__}") from None
        raise FeatureError("网络请求失败")

    async def agent_once(self, prompt: str, *, service: str = "qa", images: list[dict] | tuple = (),
                         builtin_tools: tuple[str, ...] = (), system: str | None = None,
                         timeout: float = 180, config_overlay: Path | None = None) -> OmpResult:
        """One ephemeral omp turn on the model bound to ``service`` (no session, no Host tools).

        ``images`` are ``{"data": base64, "mimeType": mime}``.
        """
        return await self.runtime.agent_once(prompt, service=service, images=images, builtin_tools=builtin_tools,
                                             system=system, timeout=timeout, config_overlay=config_overlay)

    def push(self, scope: str, reply: Reply, *, dedupe: str | None = None) -> bool:
        """Queue a proactive message for ``account_id/conversation_id``; returns False on duplicate."""
        account_id, _, conversation_id = scope.partition("/")
        return self.store.outbox_push(account_id, conversation_id, reply.actions, dedupe)


@dataclass
class Ctx(Toolkit):
    """Context for commands and observers handling one inbound message."""

    runtime: Runtime
    inbound: Inbound
    session_id: int
    run_id: str
    args: str = ""
    # True when the message was addressed to the bot (private, @mention, name prefix or slash command).
    addressed: bool = False
    # Delivery hint set by host classification, never by user-supplied mention targets.
    mention_sender: bool = False

    @property
    def is_admin(self) -> bool:
        return self.inbound.sender.id in self.settings.admins

    async def download_images(self, limit: int = 4, max_bytes: int = 8 * 1024 * 1024) -> list[dict]:
        """Fetch inbound images (and the quoted message's images) as omp image inputs."""
        result = []
        for image in [*self.inbound.images, *((self.inbound.reply or {}).get("images") or [])][:limit]:
            if not image.get("url"):
                continue
            try:
                body, info, _ = await self.fetch(image["url"], max_bytes=max_bytes, timeout=20)
            except FeatureError:
                continue
            mime = sniff_mime(body) or info.get("content-type", "").split(";")[0]
            if mime.startswith("image/"):
                result.append({"data": base64.b64encode(body).decode(), "mimeType": mime})
        return result


class JobCtx(Toolkit):
    """Context for scheduled jobs."""


def sniff_mime(body: bytes) -> str | None:
    if body.startswith(b"\x89PNG"):
        return "image/png"
    if body.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    return None


# ---------------------------------------------------------------- registry

CommandHandler = Callable[[Ctx], Awaitable["Reply | Delegate | str | None"]]
ObserverHandler = Callable[[Ctx], Awaitable["Reply | None"]]
JobHandler = Callable[[JobCtx], Awaitable[None]]
ToolHandler = Callable[[Ctx, dict], Awaitable[Any]]
# Receives the message context and the router's decision (dududa_v3.router.Route).
GatePredicate = Callable[[Ctx, Any], bool]


@dataclass
class Task:
    """A global on/off switch, managed by `task on|off|reset`."""

    id: str
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    default: bool = True


@dataclass
class Command:
    """``names`` are matched case-insensitively against the start of the addressed text.

    Multi-word names (``"task list"``) are allowed; the remainder becomes ``ctx.args``.
    """

    names: tuple[str, ...]
    handler: CommandHandler
    help: str
    admin: bool = False
    counted: bool = True
    task: str | None = None
    # Exact commands take no arguments: the addressed text must equal a name (trailing ?！ allowed).
    exact: bool = False


@dataclass
class Observer:
    """Runs on group/private messages that are not addressed to the bot."""

    task: str
    handler: ObserverHandler
    order: int = 50


@dataclass
class Job:
    task: str
    interval_seconds: float
    handler: JobHandler
    initial_delay_seconds: float = 30


@dataclass
class Tool:
    """A Host tool offered to the chat agent; ``parameters`` is a JSON schema object."""

    name: str
    description: str
    parameters: dict
    handler: ToolHandler
    task: str | None = None


@dataclass
class Gate:
    """Runs before any handling; returning False drops the message silently (e.g. exclusive groups)."""

    task: str
    allows: GatePredicate


@dataclass
class Hook:
    """Cross-cutting request and agent extensions; every callable is optional.

    - ``intercept(ctx)``: synchronous, deterministic reply for an addressed request, after gates
      but before ``addressed`` events. Task enabled only. A reply bypasses rules, commands and the
      agent (including reply rewriting); the ``addressed`` event still runs before delivery.
    - ``system``: text appended to the chat agent's system prompt while the task is enabled.
    - ``turn(ctx)``: extra lines for the current-message block of an agent turn (task enabled only).
    - ``reply(ctx, text)``: rewrites the agent's final text. Always runs, so it can strip its own
      markers even after the task is switched off; check ``ctx.enabled(task)`` before side effects.
    - ``event(ctx, name)``: host events: ``addressed`` (each addressed message, after gates),
      ``rate_limited`` and ``ping_spam``. Task enabled only.
    """

    task: str
    system: str = ""
    turn: Callable[[Ctx], Awaitable[list[str]]] | None = None
    reply: Callable[[Ctx, str], Awaitable[str]] | None = None
    event: Callable[[Ctx, str], Awaitable[None]] | None = None
    intercept: Callable[[Ctx], Reply | None] | None = None

@dataclass
class Registry:
    tasks: dict[str, Task] = field(default_factory=dict)
    commands: list[Command] = field(default_factory=list)
    observers: list[Observer] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    tools: dict[str, Tool] = field(default_factory=dict)
    gates: list[Gate] = field(default_factory=list)
    hooks: list[Hook] = field(default_factory=list)

    def task(self, task: Task) -> None:
        if task.id in self.tasks:
            raise ValueError(f"Duplicate task {task.id}")
        self.tasks[task.id] = task

    def command(self, command: Command) -> None:
        taken = {name.lower() for item in self.commands for name in item.names}
        for name in command.names:
            if name.lower() in taken:
                raise ValueError(f"Duplicate command name {name}")
        self.commands.append(command)

    def observer(self, observer: Observer) -> None:
        self.observers.append(observer)

    def job(self, job: Job) -> None:
        self.jobs.append(job)

    def tool(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"Duplicate tool {tool.name}")
        self.tools[tool.name] = tool

    def gate(self, gate: Gate) -> None:
        self.gates.append(gate)

    def hook(self, hook: Hook) -> None:
        self.hooks.append(hook)
