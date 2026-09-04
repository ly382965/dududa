"""Exercise the installed AstrBot Provider with mock HTTP, never real traffic."""

from __future__ import annotations

import asyncio
import io
import json
import logging

import httpx


async def verify_boundary() -> dict[str, object]:
    from astrbot import __version__, logger
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
    from openai import AsyncOpenAI

    sentinel = "synthetic-private-boundary-marker"
    captured = io.StringIO()
    sink = logging.StreamHandler(captured)
    sink.setLevel(logging.DEBUG)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(sink)
    passed: list[str] = []
    try:
        for case in (
            "success",
            "empty",
            "malformed_content",
            "invalid_type",
            "rate_limit",
            "context_limit",
            "network",
            "deadline",
            "cancel",
        ):
            calls: list[dict] = []
            started, cancelled = asyncio.Event(), asyncio.Event()

            async def handle(
                request: httpx.Request,
                *,
                calls=calls,
                started=started,
                cancelled=cancelled,
                case=case,
            ) -> httpx.Response:
                calls.append(json.loads(request.content))
                started.set()
                if case in {"deadline", "cancel"}:
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()
                if case == "network":
                    raise httpx.ConnectError(sentinel, request=request)
                if case in {"rate_limit", "context_limit"}:
                    message = (
                        "429 " if case == "rate_limit" else "maximum context length "
                    )
                    return httpx.Response(
                        429 if case == "rate_limit" else 400,
                        json={"error": {"message": message + sentinel}},
                    )
                if case == "invalid_type":
                    return httpx.Response(200, json=sentinel)
                return httpx.Response(
                    200,
                    json={
                        "id": "synthetic-completion",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "deepseek-v4-pro",
                        "private_marker": sentinel,
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {
                                    "role": "assistant",
                                    "content": sentinel
                                    if case == "success"
                                    else {"unknown": sentinel}
                                    if case == "malformed_content"
                                    else "",
                                },
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 5,
                            "completion_tokens": 3,
                            "total_tokens": 8,
                        },
                    },
                )

            provider = ProviderOpenAIOfficial(
                {
                    "id": "boundary-test",
                    "type": "openai_chat_completion",
                    "provider_type": "chat_completion",
                    "key": [sentinel],
                    "api_base": "https://api.deepseek.com",
                    "model": "deepseek-v4-pro",
                },
                {},
            )
            await provider.client.close()
            provider.client = AsyncOpenAI(
                api_key=sentinel,
                base_url="https://api.deepseek.com",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
            )
            task = asyncio.create_task(
                provider.text_chat(
                    prompt=sentinel,
                    model="deepseek-v4-pro",
                    max_tokens=321,
                    reasoning_effort="max",
                    thinking={"type": "enabled"},
                    request_max_retries=1,
                    unrelated_parameter=sentinel,
                )
            )
            try:
                if case == "cancel":
                    await asyncio.wait_for(started.wait(), timeout=2)
                    task.cancel()
                try:
                    response = await asyncio.wait_for(
                        task, timeout=0.05 if case == "deadline" else 5
                    )
                except (Exception, asyncio.CancelledError):  # noqa: BLE001 - expected injected transport failures
                    if case == "success":
                        raise AssertionError("bounded_success_failed") from None
                else:
                    if case != "success" or response.completion_text != sentinel:
                        raise AssertionError("bounded_error_not_propagated")
                assert len(calls) == 1, f"hidden_retry_{case}"
                assert calls[0]["model"] == "deepseek-v4-pro"
                assert calls[0]["max_tokens"] == 321
                assert calls[0]["reasoning_effort"] == "max"
                assert calls[0]["thinking"] == {"type": "enabled"}
                assert "unrelated_parameter" not in calls[0]
                if case in {"deadline", "cancel"}:
                    assert cancelled.is_set(), "http_transport_not_cancelled"
                passed.append(case)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await provider.client.close()
        assert sentinel not in captured.getvalue(), "provider_log_disclosed_content"
    finally:
        logger.removeHandler(sink)
        logger.setLevel(previous_level)
    return {
        "hostVersion": __version__,
        "passed": passed,
        "singleRequest": True,
        "parametersForwarded": True,
        "sanitizedLogging": True,
        "deadlineCancellation": True,
        "externalRequests": 0,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify_boundary()), sort_keys=True))
