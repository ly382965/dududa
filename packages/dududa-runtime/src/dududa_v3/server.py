from __future__ import annotations

import asyncio
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import RUNTIME
from .runtime import Runtime


def create_server(runtime: Runtime, loop: asyncio.AbstractEventLoop, host: str, port: int, token: str) -> ThreadingHTTPServer:
    if not token:
        raise ValueError("DUDUDA_V3_TOKEN must be configured")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.reply(401, {"error": "unauthorized"})
                return
            try:
                self.connection.settimeout(10)
                path = urlparse(self.path).path
                body = {}
                if self.command == "POST":
                    length = int(self.headers.get("Content-Length", "0"))
                    limit = 16 * 1024 * 1024 if path == "/v3/outbox" else 256 * 1024
                    if not 0 <= length <= limit:
                        raise ValueError(f"Request body exceeds {limit // 1024} KiB")
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError("Expected JSON object")
                if self.command == "GET" and path == "/v3/health":
                    result = runtime.health()
                elif self.command == "POST" and path == "/v3/runs":
                    result = asyncio.run_coroutine_threadsafe(runtime.submit(body), loop).result(10)
                elif self.command == "POST" and path == "/v3/outbox":
                    # Trusted local workers (e.g. the notify worker) queue proactive messages.
                    scope = f"{body.get('account_id')}/{body.get('conversation_id')}"
                    if scope not in runtime.settings.allowed_scopes:
                        raise PermissionError("Outbox scope is not enabled")
                    actions = body.get("actions")
                    if not isinstance(actions, list) or not all(isinstance(item, dict) for item in actions):
                        raise ValueError("actions must be a list of objects")
                    dedupe = body.get("dedupe")
                    queued = runtime.store.outbox_push(body["account_id"], body["conversation_id"], actions,
                                                       str(dedupe)[:300] if dedupe else None)
                    result = {"queued": queued}
                elif self.command == "POST" and path == "/v3/outbox/claim":
                    result = {"items": runtime.store.outbox_claim(int(body.get("limit", 10)))}
                elif self.command == "POST" and path.startswith("/v3/outbox/") and path.endswith("/authorize"):
                    from .features.affinity.greetings import authorize
                    item_id = int(path[len("/v3/outbox/"):-len("/authorize")])
                    if not isinstance(body.get("target_valid"), bool):
                        raise ValueError("target_valid must be a boolean from a fresh bridge target check")
                    result = authorize(runtime, item_id, body["target_valid"])
                elif self.command == "POST" and path.startswith("/v3/outbox/") and path.endswith("/result"):
                    item_id = int(path[len("/v3/outbox/"):-len("/result")])
                    result = {"updated": runtime.store.outbox_result(item_id, body.get("state"), body.get("message_id"))}
                elif path.startswith("/v3/runs/"):
                    pieces = path[len("/v3/runs/"):].split("/")
                    run_id = pieces[0]
                    if self.command == "GET" and len(pieces) == 1:
                        result = runtime.store.get(run_id)
                    elif self.command == "POST" and len(pieces) == 2 and pieces[1] == "cancel":
                        result = asyncio.run_coroutine_threadsafe(runtime.cancel(run_id), loop).result(15)
                    elif self.command == "POST" and len(pieces) == 2 and pieces[1] == "delivery":
                        result = runtime.store.delivery(run_id, body.get("state"), body.get("message_id"))
                    else:
                        raise KeyError(path)
                else:
                    raise KeyError(path)
                self.reply(200, result)
            except PermissionError as error:
                self.reply(403, {"error": str(error)})
            except KeyError:
                self.reply(404, {"error": "not_found"})
            except (ValueError, TypeError) as error:
                self.reply(400, {"error": str(error)})
            except Exception:  # noqa: BLE001 -- HTTP boundary returns a sanitized response for internal errors.
                self.reply(500, {"error": "runtime_request_failed"})

        def reply(self, status: int, value: dict):
            encoded = json.dumps({"runtime": RUNTIME, **value}, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

    return ThreadingHTTPServer((host, port), Handler)
