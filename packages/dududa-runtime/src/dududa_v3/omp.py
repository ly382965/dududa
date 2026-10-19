"""Async transport for the locally installed omp CLI in ``--mode rpc``.

One process serves one agent run. Conversation continuity comes from omp's
own session directory (``open_session``), which the Host keys per QQ scope.
Business tools are registered as RPC host tools, so every tool call is
answered in-process by the Host with the identity it bound to the run.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ToolHandler = Callable[[str, dict[str, Any]], Awaitable[tuple[str, bool]]]
EventCallback = Callable[[dict[str, Any]], Awaitable[None]]

THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
STREAM_LIMIT = 64 * 1024 * 1024
MAX_INBOUND_FRAME_BYTES = 1_000_000


class OmpError(RuntimeError):
    """A local transport, protocol, or agent turn failure."""


class OmpTimeout(OmpError):
    """The turn exceeded its deadline and was aborted."""


@dataclass(frozen=True)
class ModelSpec:
    """A registered model: ``provider/model`` plus a thinking level."""

    model: str
    thinking: str = "max"

    def __post_init__(self) -> None:
        if "/" not in self.model:
            raise ValueError(f"Model must be provider/model: {self.model}")
        if self.thinking not in THINKING_LEVELS:
            raise ValueError(f"Invalid thinking level: {self.thinking}")

    @property
    def provider(self) -> str:
        return self.model.split("/", 1)[0]

    @property
    def model_id(self) -> str:
        return self.model.split("/", 1)[1]


@dataclass
class OmpResult:
    text: str
    model: str
    thinking: str
    status: str = "completed"
    session_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class OmpClient:
    """Run one prompt through ``omp --mode rpc``.

    ``session_dir=None`` runs an ephemeral session (``--no-session``).
    ``builtin_tools`` enables named omp tools (for example ``web_search`` or
    ``generate_image``); every other built-in tool stays disabled.
    """

    spec: ModelSpec
    system_prompt: Path
    cwd: Path
    binary: str = "omp"
    session_dir: Path | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_handler: ToolHandler | None = None
    builtin_tools: tuple[str, ...] = ()
    config_overlay: Path | None = None
    timeout: float = 180
    on_event: EventCallback | None = None

    def __post_init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._prompt_done: asyncio.Future | None = None
        self._ready: asyncio.Future | None = None
        self._reader: asyncio.Task | None = None
        self._tool_tasks: set[asyncio.Task] = set()
        self._chunks: dict[str, list[str]] = {}
        self._counter = 0
        self._tool_calls: list[dict[str, Any]] = []
        self._images: list[dict[str, str]] = []
        self._usage: dict[str, Any] = {}
        self._model = self.spec.model
        self._stderr: list[str] = []

    def command(self) -> list[str]:
        args = [self.binary, "--mode", "rpc", "--no-ui", "--model", self.spec.model,
                "--thinking", self.spec.thinking, "--no-skills", "--no-rules", "--no-extensions",
                "--no-lsp", "--no-title", "--system-prompt", str(self.system_prompt)]
        args += ["--tools", ",".join(self.builtin_tools)] if self.builtin_tools else ["--no-tools"]
        if self.session_dir is None:
            args.append("--no-session")
        if self.config_overlay is not None:
            args += ["--config", str(self.config_overlay)]
        return args

    async def run(self, text: str, images: list[dict[str, str]] | tuple = ()) -> OmpResult:
        """Send one prompt; ``images`` are ``{"data": base64, "mimeType": mime}``."""
        try:
            return await asyncio.wait_for(self._run(text, list(images)), self.timeout)
        except asyncio.TimeoutError:
            await self._abort()
            raise OmpTimeout(f"omp turn exceeded {self.timeout:g}s") from None
        finally:
            await self.close()

    async def _run(self, text: str, images: list[dict[str, str]]) -> OmpResult:
        await self._start()
        session_id = None
        if self.session_dir is not None:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            opened = await self._request({"type": "open_session", "sessionDir": str(self.session_dir),
                                          "provider": self.spec.provider, "modelId": self.spec.model_id})
            session_id = (opened or {}).get("sessionId")
            # A resumed session restores its saved thinking level; pin the registered one.
            await self._request({"type": "set_thinking_level", "level": self.spec.thinking})
        if self.tools:
            await self._request({"type": "set_host_tools", "tools": self.tools})
        loop = asyncio.get_running_loop()
        self._prompt_done = loop.create_future()
        prompt: dict[str, Any] = {"type": "prompt", "message": text}
        if images:
            prompt["images"] = [{"type": "image", "data": item["data"], "mimeType": item["mimeType"]}
                                for item in images]
        self._prompt_id = f"h{self._counter + 1}"
        await self._send(prompt)
        outcome = await self._prompt_done
        status = outcome.get("status")
        if status == "error":
            error = outcome.get("error") or {}
            raise OmpError(f"omp turn failed: {str(error.get('message', 'unknown error'))[:400]}")
        last = await self._request({"type": "get_last_assistant_text"})
        return OmpResult(text=((last or {}).get("text") or "").strip(), model=self._model,
                         thinking=self.spec.thinking, status="completed" if status == "completed" else "cancelled",
                         session_id=session_id, tool_calls=self._tool_calls, images=self._images,
                         usage=self._usage)

    async def _start(self) -> None:
        env = dict(os.environ)
        env["PI_NO_TITLE"] = "1"
        self._process = await asyncio.create_subprocess_exec(
            *self.command(), cwd=self.cwd, env=env, limit=STREAM_LIMIT,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._reader = asyncio.create_task(self._read())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        ready = await self._ready
        if 2 in ready.get("supportedProtocolVersions", []):
            await self._request({"type": "negotiate_protocol", "protocolVersion": 2})

    async def close(self) -> None:
        process, self._process = self._process, None
        for task in list(self._tool_tasks):
            task.cancel()
        if process is None:
            return
        if process.stdin and not process.stdin.is_closing():
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 10)
        except asyncio.TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
        for task in (self._reader, getattr(self, "_stderr_task", None)):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task

    async def _abort(self) -> None:
        if self._process and self._process.returncode is None:
            with suppress(Exception):
                await asyncio.wait_for(self._request({"type": "abort"}), 5)

    async def _send(self, message: dict[str, Any]) -> str:
        self._counter += 1
        message_id = f"h{self._counter}"
        message = {"id": message_id, **message}
        await self._write(message)
        return message_id

    async def _write(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.stdin.is_closing():
            raise OmpError("omp process is not running")
        process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        try:
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise OmpError("omp process disconnected") from exc

    async def _request(self, message: dict[str, Any]) -> Any:
        future = asyncio.get_running_loop().create_future()
        self._counter += 1
        message_id = f"h{self._counter}"
        self._pending[message_id] = future
        await self._write({"id": message_id, **message})
        return await future

    def _fail(self, error: OmpError) -> None:
        for future in [*self._pending.values(), self._ready, self._prompt_done]:
            if future is not None and not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def _read(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    detail = " ".join(self._stderr[-3:])[:400]
                    self._fail(OmpError(f"omp exited unexpectedly{': ' + detail if detail else ''}"))
                    return
                if not line.strip():
                    continue
                frame = json.loads(line)
                frame = self._reassemble(frame)
                if frame is not None:
                    await self._dispatch(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- Every reader failure must fail the waiting run.
            self._fail(OmpError(f"omp protocol reader failed: {type(exc).__name__}: {exc}"[:300]))

    def _reassemble(self, frame: dict[str, Any]) -> dict[str, Any] | None:
        if frame.get("type") != "rpc_chunk":
            return frame
        chunk_id, index, count = frame["chunkId"], frame["index"], frame["count"]
        parts = self._chunks.setdefault(chunk_id, [])
        if index != len(parts):
            raise OmpError("omp chunk sequence interrupted")
        parts.append(frame["data"])
        if len(parts) < count:
            return None
        del self._chunks[chunk_id]
        payload = b"".join(base64.b64decode(part) for part in parts)
        if len(payload) != frame["byteLength"]:
            raise OmpError("omp chunk length mismatch")
        return json.loads(payload.decode("utf-8"))

    async def _dispatch(self, frame: dict[str, Any]) -> None:
        kind = frame.get("type")
        if kind == "ready":
            if self._ready and not self._ready.done():
                self._ready.set_result(frame)
        elif kind == "response":
            future = self._pending.pop(frame.get("id"), None)
            if future is None:
                if frame.get("id") == getattr(self, "_prompt_id", None):
                    if not frame.get("success"):
                        self._finish({"status": "error", "error": {"message": frame.get("error")}})
                    elif (frame.get("data") or {}).get("agentInvoked") is False:
                        self._finish({"status": "completed"})
                return
            if frame.get("success"):
                future.set_result(frame.get("data"))
            else:
                future.set_exception(OmpError(f"omp {frame.get('command')} failed: {frame.get('error')}"[:400]))
        elif kind == "prompt_result":
            if frame.get("id") == getattr(self, "_prompt_id", None):
                self._finish(frame)
        elif kind == "host_tool_call":
            task = asyncio.create_task(self._answer_tool(frame))
            self._tool_tasks.add(task)
            task.add_done_callback(self._tool_tasks.discard)
        elif kind == "tool_execution_end":
            name = frame.get("toolName", "")
            self._tool_calls.append({"name": name, "error": bool(frame.get("isError"))})
            details = (frame.get("result") or {}).get("details") or {}
            for image in details.get("images") or []:
                if isinstance(image, dict) and image.get("data"):
                    self._images.append({"data": image["data"], "mimeType": image.get("mimeType", "image/png")})
        elif kind == "message_end":
            message = frame.get("message") or {}
            if message.get("role") == "assistant":
                self._model = f"{message.get('provider', self.spec.provider)}/{message.get('model', self.spec.model_id)}"
                usage = message.get("usage") or {}
                for key in ("input", "output", "cacheRead", "totalTokens"):
                    if isinstance(usage.get(key), (int, float)):
                        self._usage[key] = self._usage.get(key, 0) + usage[key]
        if self.on_event and kind in ("tool_execution_start", "tool_execution_end", "turn_start", "turn_end",
                                      "agent_start", "agent_end", "auto_retry_start"):
            with suppress(Exception):
                await self.on_event({"type": kind, "tool": frame.get("toolName")})

    def _finish(self, outcome: dict[str, Any]) -> None:
        if self._prompt_done is not None and not self._prompt_done.done():
            self._prompt_done.set_result(outcome)

    async def _answer_tool(self, frame: dict[str, Any]) -> None:
        name, args = frame.get("toolName", ""), frame.get("arguments") or {}
        try:
            if self.tool_handler is None:
                raise OmpError("no host tool handler")
            text, is_error = await self.tool_handler(name, args if isinstance(args, dict) else {})
        except Exception as exc:  # noqa: BLE001 -- The tool boundary returns a sanitized error to the model.
            text, is_error = json.dumps({"error": f"{type(exc).__name__}: {exc}"[:500]}, ensure_ascii=False), True
        message = {"type": "host_tool_result", "id": frame.get("id"),
                   "result": {"content": [{"type": "text", "text": text}]}, "isError": is_error}
        # Inbound RPC frames must stay within omp's 1 MiB physical-frame limit.
        while len(json.dumps(message, ensure_ascii=False).encode()) > MAX_INBOUND_FRAME_BYTES:
            text = text[: int(len(text) * 0.8)]
            message["result"]["content"][0]["text"] = text + "\n…[工具结果过长，已截断]"
        with suppress(OmpError):
            await self._write(message)

    async def _drain_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while line := await self._process.stderr.readline():
            self._stderr = (self._stderr + [line.decode(errors="replace").strip()])[-20:]
