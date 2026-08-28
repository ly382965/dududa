from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from .rollout_bridge import AstrBotRuntimePreviewError

_ACCOUNT_PATTERN = re.compile(r"^qq-(\d{5,20})$")
_GROUP_PATTERN = re.compile(r"^qq-(\d{5,20}):group:(\d{5,20})$")


class At:
    def __init__(self, qq: str) -> None:
        self.qq = qq
        self.name = None


class WebRuntimePreviewEvent:
    def __init__(self, *, bot_id: str, group_id: str, prompt: str) -> None:
        now = datetime.now(timezone.utc)
        self.message_str = f"@嘟嘟哒 {prompt}"
        self.message_obj = SimpleNamespace(
            message_id=f"web-preview-{uuid4().hex}",
            timestamp=now.timestamp(),
            message=[At(bot_id)],
            raw_message={"time": now.timestamp(), "message": []},
        )
        self._bot_id = bot_id
        self._group_id = group_id

    def get_platform_id(self) -> str:
        return "aiocqhttp"

    def get_platform_name(self) -> str:
        return "aiocqhttp-web-preview"

    def get_self_id(self) -> str:
        return self._bot_id

    def get_sender_id(self) -> str:
        return "web-super-admin-preview"

    def get_group_id(self) -> str:
        return self._group_id

    def get_message_type(self) -> str:
        return "group"

    def get_messages(self) -> list[object]:
        return list(self.message_obj.message)

    def is_admin(self) -> bool:
        return False


def preview_event(payload: object) -> tuple[WebRuntimePreviewEvent, str]:
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    account_id = str(payload.get("accountId") or "").strip()
    conversation_id = str(payload.get("conversationId") or "").strip()
    prompt = str(payload.get("prompt") or "").strip()
    account = _ACCOUNT_PATTERN.fullmatch(account_id)
    conversation = _GROUP_PATTERN.fullmatch(conversation_id)
    if (
        account is None
        or conversation is None
        or account.group(1) != conversation.group(1)
    ):
        raise ValueError("invalid_scope")
    if not prompt or len(prompt) > 8_192:
        raise ValueError("invalid_prompt")
    return (
        WebRuntimePreviewEvent(
            bot_id=account.group(1),
            group_id=conversation.group(2),
            prompt=prompt,
        ),
        prompt,
    )


async def runtime_preview_response(plugin: object):
    from astrbot.api.web import error_response, json_response, request

    payload = await request.json(default={})
    try:
        event, prompt = preview_event(payload)
    except ValueError as exc:
        return error_response(str(exc), status_code=400)
    bridge = getattr(plugin, "rollout_bridge", None)
    if bridge is None:
        return error_response("runtime_unavailable", status_code=503)
    started = time.perf_counter()
    try:
        preview = await bridge.preview(event)
    except AstrBotRuntimePreviewError as exc:
        return error_response(exc.code, status_code=409)
    except Exception:
        return error_response("runtime_preview_failed", status_code=502)
    result = preview.runtime_result
    response = result.final_response
    candidate = ""
    answer_profile = "medium"
    if response is not None:
        candidate = "\n\n".join(
            block.content.text
            for block in response.response.blocks
            if block.content.text is not None
        ).strip()
        if response.profile_validation is not None:
            answer_profile = response.profile_validation.selected_profile
    tier = (
        result.selection_summary.selected_tier.value
        if result.selection_summary is not None
        else "haiku"
    )
    model, reasoning = _model_selection(getattr(plugin, "config", {}), tier)
    return json_response(
        {
            "status": "ok",
            "data": {
                "runId": result.run_id,
                "candidate": candidate,
                "tier": tier,
                "model": model,
                "reasoning": reasoning,
                "answerProfile": answer_profile,
                "reasonCodes": [*result.reason_codes, "runtime.preview.no_send"],
                "latencyMs": max(0, round((time.perf_counter() - started) * 1000)),
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "messagesRead": 1,
                "charactersRead": len(prompt),
                "outputCalls": 0,
                "memoryWrites": 0,
                "toolCalls": preview.tool_calls,
            },
        }
    )


def _model_selection(config: object, tier: str) -> tuple[str, str]:
    values = config.get("runtime_models_json") if isinstance(config, dict) else None
    try:
        models = json.loads(values) if isinstance(values, str) else values
    except json.JSONDecodeError:
        models = []
    if not isinstance(models, list):
        models = []
    for item in models:
        if not isinstance(item, dict) or str(item.get("tier") or "") != tier:
            continue
        model = str(item.get("model_id") or "").strip()
        depth = str(item.get("reasoning_depth") or "light").strip().lower()
        reasoning = {
            "balanced": "medium",
            "deep": "high",
            "maximum": "high",
        }.get(depth, "low")
        return model or f"unknown-{tier}", reasoning
    return f"unknown-{tier}", "low"


__all__ = ["WebRuntimePreviewEvent", "preview_event", "runtime_preview_response"]
