from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import subprocess
import threading
import uuid
from contextlib import contextmanager

from . import RUNTIME, VERSION
from .config import Settings
from .runtime import Runtime
from .server import create_server


@contextmanager
def state_lock(settings: Settings):
    import fcntl
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    with (settings.state_dir / "host.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("This state directory is in use; use the running Host API or DUDUDA_V3_STATE_DIR")
        yield


def token_for(settings: Settings) -> str:
    if os.environ.get("DUDUDA_V3_TOKEN"):
        return os.environ["DUDUDA_V3_TOKEN"]
    path = settings.state_dir / "token"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as output:
                output.write(secrets.token_urlsafe(32))
    return path.read_text().strip()


async def chat(settings: Settings, text: str, conversation: str, preview: bool) -> int:
    runtime = Runtime(settings)
    runtime.store.recover()
    try:
        run = await runtime.submit({"account_id": "local", "conversation_id": conversation,
                                        "user_id": "owner", "message_id": str(uuid.uuid4()),
                                        "text": text, "source": "web", "mentioned": True, "preview": preview})
        result = await runtime.wait(run["run_id"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in ("completed", "ignored") else 1
    finally:
        await runtime.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Dududa 3.0: rules + local Codex CLI")
    parser.add_argument("--config", help="Runtime JSON configuration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Check local executable without an LLM call")
    query = sub.add_parser("chat", help="Run a message through the actual 3.0 runtime")
    query.add_argument("text")
    query.add_argument("--conversation", default="private:local")
    query.add_argument("--preview", action="store_true")
    server = sub.add_parser("serve", help="Serve the authenticated v3 API")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8783)
    args = parser.parse_args()
    settings = Settings.load(args.config)
    if args.command == "chat":
        with state_lock(settings):
            return asyncio.run(chat(settings, args.text, args.conversation, args.preview))
    if args.command == "check":
        health = {"runtime": RUNTIME, "version": VERSION,
                  "codex_available": shutil.which(settings.codex_binary) is not None}
        if health["codex_available"]:
            health["codex_version"] = subprocess.run([settings.codex_binary, "--version"], capture_output=True,
                                                       text=True, timeout=10, check=True).stdout.strip()
        print(json.dumps(health, ensure_ascii=False, indent=2))
        return 0 if health["codex_available"] else 1
    with state_lock(settings):
        return serve(settings, args.host, args.port)


def serve(settings: Settings, host: str, port: int) -> int:
    token = token_for(settings)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    runtime = Runtime(settings)
    runtime.store.recover()
    httpd = create_server(runtime, loop, host, port, token)
    print(f"Dududa 3.0 listening at http://{host}:{port}", flush=True)
    if not os.environ.get("DUDUDA_V3_TOKEN"):
        print(f"Token file: {settings.state_dir / 'token'}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        asyncio.run_coroutine_threadsafe(runtime.close(), loop).result(20)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
