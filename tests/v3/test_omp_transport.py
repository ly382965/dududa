"""OmpClient against a fake ``omp --mode rpc`` executable speaking the JSONL protocol."""

import asyncio
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dududa_v3.omp import ModelSpec, OmpClient, OmpError, OmpTimeout

FAKE_OMP = r'''
import base64, json, os, sys, time

mode = os.environ.get("FAKE_OMP_MODE", "tool")
log = open(os.environ["FAKE_OMP_LOG"], "a", encoding="utf-8")
BIG = "嘟" * 400000  # 1.2 MB of UTF-8: larger than one v1 frame, split across multibyte boundaries.


def record(kind, value):
    log.write(json.dumps({kind: value}, ensure_ascii=False) + "\n")
    log.flush()


def send(frame):
    sys.stdout.write(json.dumps(frame, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def respond(frame, data=None, success=True, error=None):
    out = {"type": "response", "id": frame.get("id"), "command": frame.get("type"), "success": success}
    if success:
        out["data"] = data
    else:
        out["error"] = error
    send(out)


def send_chunked(frame, size, order=None):
    payload = json.dumps(frame, ensure_ascii=False).encode("utf-8")
    parts = [payload[i:i + size] for i in range(0, len(payload), size)]
    for index in order or range(len(parts)):
        send({"type": "rpc_chunk", "chunkId": "rpc-1", "index": index, "count": len(parts),
              "byteLength": len(payload), "data": base64.b64encode(parts[index]).decode()})


def assistant_end(model):
    send({"type": "message_end", "message": {"role": "assistant", "provider": "openai-codex", "model": model,
                                              "usage": {"input": 10, "output": 5, "cacheRead": 2, "totalTokens": 17}}})


def finish(prompt_id):
    assistant_end("gpt-5.6-luna-served")
    send({"type": "agent_end", "messages": []})
    send({"type": "prompt_result", "id": prompt_id, "agentInvoked": True, "status": "completed",
          "sessionSettled": True})


record("argv", sys.argv[1:])
send({"type": "ready", "protocolVersion": 1,
      "supportedProtocolVersions": [1] if mode == "v1" else [1, 2],
      "maxFrameBytes": 1048576, "maxReassembledFrameBytes": 67108864})
send({"type": "available_commands_update", "commands": []})
prompt_id = None
last_text = "最终回答"
while True:
    line = sys.stdin.readline()
    if not line:
        break
    if not line.strip():
        continue
    frame = json.loads(line)
    record("frame", frame)
    kind = frame.get("type")
    if kind == "negotiate_protocol":
        respond(frame, {"protocolVersion": 2})
    elif kind == "open_session":
        os.makedirs(frame["sessionDir"], exist_ok=True)
        path = os.path.join(frame["sessionDir"], "session.jsonl")
        resumed = os.path.exists(path)
        with open(path, "a") as handle:
            handle.write("{}\n")
        respond(frame, {"cancelled": False, "resumed": resumed, "sessionId": "sess-fake", "sessionFile": path})
    elif kind == "set_thinking_level":
        respond(frame, None)
    elif kind == "set_host_tools":
        respond(frame, {"toolNames": [tool["name"] for tool in frame["tools"]]})
    elif kind == "prompt":
        prompt_id = frame["id"]
        if mode == "local":
            respond(frame, {"agentInvoked": False})
            continue
        if mode == "rejected":
            respond(frame, success=False, error="prompt rejected by extension")
            continue
        respond(frame, {})
        send({"type": "agent_start"})
        if mode == "crash":
            sys.stderr.write("fatal: provider exploded\n")
            sys.stderr.flush()
            time.sleep(0.3)  # Let the host drain stderr before stdout reaches EOF.
            sys.exit(3)
        if mode == "hang":
            continue
        if mode == "error":
            send({"type": "prompt_result", "id": prompt_id, "agentInvoked": True, "status": "error",
                  "error": {"message": "rate limited by provider", "retryable": True}})
            continue
        if mode == "tool":
            send({"type": "tool_execution_start", "toolName": "echo"})
            send({"type": "host_tool_call", "id": "host_1", "toolCallId": "toolu_1", "toolName": "echo",
                  "arguments": {"message": "你好"}})
            continue
        finish(prompt_id)
    elif kind == "host_tool_result":
        text = frame["result"]["content"][0]["text"]
        last_text = "回声：" + text
        send({"type": "tool_execution_end", "toolName": "echo", "isError": frame.get("isError", False),
              "result": {"details": {"images": [{"data": "aW1n", "mimeType": "image/webp"}, {"bogus": 1}]}}})
        assistant_end("gpt-5.6-luna-served")
        finish(prompt_id)
    elif kind == "get_last_assistant_text":
        if mode == "chunk":
            send_chunked({"type": "response", "id": frame["id"], "command": kind, "success": True,
                          "data": {"text": BIG}}, 300001)
        elif mode == "badchunk":
            send_chunked({"type": "response", "id": frame["id"], "command": kind, "success": True,
                          "data": {"text": BIG}}, 300001, order=[1, 0])
        else:
            respond(frame, {"text": "  " + last_text + "\n"})
    elif kind == "abort":
        respond(frame, None)
    else:
        respond(frame, success=False, error="unknown command")
'''


class OmpTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.binary = self.root / "fake-omp"
        self.binary.write_text(f"#!{sys.executable}\n" + FAKE_OMP, encoding="utf-8")
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)
        self.log = self.root / "omp.log"
        self.prompt = self.root / "system.md"
        self.prompt.write_text("你是嘟嘟哒。", encoding="utf-8")
        self.events = []

    def client(self, mode="tool", **overrides):
        environment = patch.dict(os.environ, {"FAKE_OMP_MODE": mode, "FAKE_OMP_LOG": str(self.log)})
        environment.start()
        self.addCleanup(environment.stop)

        async def on_event(event):
            self.events.append(event)

        config = {"spec": ModelSpec("openai-codex/gpt-5.6-luna", "max"), "system_prompt": self.prompt,
                  "cwd": self.root, "binary": str(self.binary), "on_event": on_event, "timeout": 60}
        config.update(overrides)
        return OmpClient(**config)

    def frames(self):
        lines = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [line["frame"] for line in lines if "frame" in line]

    def argv(self):
        return json.loads(self.log.read_text(encoding="utf-8").splitlines()[0])["argv"]

    def test_model_spec_and_command_line(self):
        spec = ModelSpec("openai-codex/gpt-5.6-luna", "max")
        self.assertEqual((spec.provider, spec.model_id), ("openai-codex", "gpt-5.6-luna"))
        for model, thinking in (("no-provider", "max"), ("a/b", "ultra")):
            with self.assertRaises(ValueError):
                ModelSpec(model, thinking)
        client = OmpClient(spec=spec, system_prompt=self.prompt, cwd=self.root)
        command = client.command()
        self.assertEqual(command[:3], ["omp", "--mode", "rpc"])
        self.assertIn("--no-tools", command)
        self.assertIn("--no-session", command)
        self.assertNotIn("--config", command)
        self.assertEqual(command[command.index("--model") + 1], "openai-codex/gpt-5.6-luna")
        self.assertEqual(command[command.index("--thinking") + 1], "max")
        self.assertEqual(command[command.index("--system-prompt") + 1], str(self.prompt))
        overlay = self.root / "overlay.yml"
        tooled = OmpClient(spec=spec, system_prompt=self.prompt, cwd=self.root, session_dir=self.root / "s",
                           builtin_tools=("web_search", "generate_image"), config_overlay=overlay)
        command = tooled.command()
        self.assertEqual(command[command.index("--tools") + 1], "web_search,generate_image")
        self.assertNotIn("--no-tools", command)
        self.assertNotIn("--no-session", command)
        self.assertEqual(command[command.index("--config") + 1], str(overlay))

    async def test_session_turn_answers_host_tool_and_collects_results(self):
        calls = []

        async def handler(name, args):
            calls.append((name, args))
            return json.dumps({"echo": args["message"]}, ensure_ascii=False), False

        tools = [{"name": "echo", "label": "echo", "description": "Echo", "parameters": {"type": "object"}}]
        session_dir = self.root / "sessions" / "thread-1"
        result = await self.client(session_dir=session_dir, tools=tools, tool_handler=handler).run("问题")
        self.assertEqual(calls, [("echo", {"message": "你好"})])
        self.assertEqual(result.text, '回声：{"echo": "你好"}')
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.session_id, "sess-fake")
        self.assertEqual(result.model, "openai-codex/gpt-5.6-luna-served")
        self.assertEqual(result.thinking, "max")
        self.assertEqual(result.tool_calls, [{"name": "echo", "error": False}])
        self.assertEqual(result.images, [{"data": "aW1n", "mimeType": "image/webp"}])
        self.assertEqual(result.usage, {"input": 20, "output": 10, "cacheRead": 4, "totalTokens": 34})
        frames = self.frames()
        self.assertEqual([frame["type"] for frame in frames], [
            "negotiate_protocol", "open_session", "set_thinking_level", "set_host_tools", "prompt",
            "host_tool_result", "get_last_assistant_text"])
        self.assertEqual(len({frame["id"] for frame in frames if "id" in frame and frame["type"] != "host_tool_result"}), 6)
        self.assertEqual(frames[1], {"id": frames[1]["id"], "type": "open_session", "sessionDir": str(session_dir),
                                     "provider": "openai-codex", "modelId": "gpt-5.6-luna"})
        self.assertEqual(frames[2]["level"], "max")
        self.assertEqual(frames[3]["tools"], tools)
        self.assertEqual(frames[4]["message"], "问题")
        self.assertNotIn("images", frames[4])
        self.assertEqual(frames[5], {"type": "host_tool_result", "id": "host_1", "isError": False,
                                     "result": {"content": [{"type": "text", "text": '{"echo": "你好"}'}]}})
        self.assertNotIn("--no-session", self.argv())
        self.assertTrue((session_dir / "session.jsonl").exists())
        kinds = [event["type"] for event in self.events]
        self.assertEqual(kinds, ["agent_start", "tool_execution_start", "tool_execution_end", "agent_end"])
        self.assertEqual(self.events[2]["tool"], "echo")

    async def test_tool_handler_failure_is_returned_as_tool_error(self):
        async def handler(name, args):
            raise RuntimeError("boom")

        result = await self.client(tools=[{"name": "echo", "label": "echo", "description": "",
                                           "parameters": {}}], tool_handler=handler).run("问题")
        reply = next(frame for frame in self.frames() if frame["type"] == "host_tool_result")
        self.assertTrue(reply["isError"])
        self.assertEqual(json.loads(reply["result"]["content"][0]["text"]), {"error": "RuntimeError: boom"})
        self.assertEqual(result.tool_calls, [{"name": "echo", "error": True}])

    async def test_missing_tool_handler_still_answers_the_call(self):
        await self.client().run("问题")
        reply = next(frame for frame in self.frames() if frame["type"] == "host_tool_result")
        self.assertTrue(reply["isError"])
        self.assertIn("no host tool handler", reply["result"]["content"][0]["text"])

    async def test_ephemeral_turn_sends_images_without_session_or_tools(self):
        images = [{"data": "QUJD", "mimeType": "image/jpeg"}]
        result = await self.client("plain").run("看图", images)
        self.assertEqual(result.text, "最终回答")
        self.assertIsNone(result.session_id)
        frames = self.frames()
        self.assertEqual([frame["type"] for frame in frames],
                         ["negotiate_protocol", "prompt", "get_last_assistant_text"])
        self.assertEqual(frames[1]["images"], [{"type": "image", "data": "QUJD", "mimeType": "image/jpeg"}])
        self.assertIn("--no-session", self.argv())
        self.assertIn("--no-tools", self.argv())

    async def test_v1_server_is_not_negotiated(self):
        await self.client("v1").run("你好")
        self.assertEqual([frame["type"] for frame in self.frames()], ["prompt", "get_last_assistant_text"])

    async def test_chunked_response_is_reassembled(self):
        result = await self.client("chunk").run("长回答")
        self.assertEqual(result.text, "嘟" * 400000)

    async def test_interrupted_chunk_sequence_fails_the_turn(self):
        with self.assertRaisesRegex(OmpError, "chunk sequence interrupted"):
            await self.client("badchunk").run("长回答")

    async def test_local_completion_needs_no_prompt_result(self):
        result = await self.client("local").run("/local-command")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.text, "最终回答")

    async def test_turn_error_and_rejected_prompt_raise(self):
        with self.assertRaisesRegex(OmpError, "rate limited by provider"):
            await self.client("error").run("你好")
        with self.assertRaisesRegex(OmpError, "prompt rejected by extension"):
            await self.client("rejected").run("你好")

    async def test_process_exit_reports_stderr(self):
        with self.assertRaisesRegex(OmpError, "exited unexpectedly.*provider exploded"):
            await self.client("crash").run("你好")

    async def test_timeout_aborts_the_turn_and_closes_the_process(self):
        client = self.client("hang", timeout=5)
        with self.assertRaises(OmpTimeout):
            await asyncio.wait_for(client.run("你好"), 60)
        self.assertEqual([frame["type"] for frame in self.frames()][-2:], ["prompt", "abort"])
        self.assertIsNone(client._process)


if __name__ == "__main__":
    unittest.main()
