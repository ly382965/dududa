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
_PLATFORM_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_MESSAGE_PATTERN = re.compile(r"^-?\d{1,20}$")


def runtime_status(plugin: object) -> dict[str, object]:
    """Project current process state, never credentials or raw configuration."""
    config = getattr(plugin, "config", {})
    assembly = getattr(plugin, "runtime_assembly", None)
    terminated = getattr(plugin, "_dududa_runtime_terminated", False) is True
    ready = (
        getattr(assembly, "ready", False) is True
        and getattr(plugin, "rollout_bridge", None) is not None
        and not terminated
    )
    try:
        specs = json.loads(config.get("runtime_models_json", "[]"))
    except (TypeError, ValueError):
        specs = []
    models = {}
    for spec in specs if isinstance(specs, list) else []:
        if not isinstance(spec, dict):
            continue
        tier, model = spec.get("tier"), spec.get("model_id")
        if tier in ("haiku", "sonnet", "opus") and isinstance(model, str):
            models[tier] = model
    controls: dict[str, object] = {
        name: config.get(name) is True
        for name in (
            "runtime_enabled", "rollout_delivery_enabled", "proactive_talk_enabled"
        )
    }
    controls["runtime_enabled"] = (
        controls["runtime_enabled"] and getattr(plugin, "enabled", False) is True
    )
    control_error = False
    try:
        current = plugin.rollout_controls.current()
        controls.update({
            "rollout_mode": current.mode.value,
            "rollout_delivery_enabled": current.delivery_enabled,
            "rollout_kill_switch": current.kill_switch,
            "all_groups": "*" in current.allowlisted_group_ids,
        })
    except Exception:  # noqa: BLE001 -- status fails closed without serializing config errors
        control_error = True
        controls.update({
            "rollout_mode": "off", "rollout_delivery_enabled": False,
            "rollout_kill_switch": True, "all_groups": False,
        })
    return {
        "ready": ready,
        "reason": "runtime_ready" if ready else (
            "runtime_stopped" if terminated else "runtime_not_ready"
        ),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "modelMapping": models,
        "controls": controls,
        "modelHealth": "not_probed",
        "previewScope": "group",
        "controlReason": "rollout_config_invalid" if control_error else "rollout_config_current",
    }


async def runtime_status_response(plugin: object):
    from astrbot.api.web import json_response

    return json_response({"status": "ok", "data": runtime_status(plugin)})


class At:
    def __init__(self, qq: str) -> None:
        self.qq = qq
        self.name = None


class WebRuntimePreviewEvent:
    def __init__(self, *, bot_id: str, group_id: str, prompt: str, history: dict | None = None) -> None:
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
        self.dududa_preview_history = history

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
    history = _preview_history(payload.get("history"), account_id, conversation_id)
    return (
        WebRuntimePreviewEvent(
            bot_id=account.group(1),
            group_id=conversation.group(2),
            prompt=prompt,
            history=history,
        ),
        prompt,
    )


def _preview_history(value: object, account_id: str, conversation_id: str) -> dict | None:
    """Validate host-only context input; this grants no identity or delivery authority."""
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("accountId") != account_id or value.get("conversationId") != conversation_id:
        raise ValueError("preview_history_scope_mismatch")
    if value.get("source") not in {"server_recent", "synthetic"}:
        raise ValueError("invalid_preview_history_source")
    messages = value.get("messages")
    if not isinstance(messages, list) or len(messages) > 100:
        raise ValueError("invalid_preview_history_messages")
    seen: set[str] = set()
    total = 0
    for item in messages:
        if not isinstance(item, dict) or set(item) - {"id", "senderId", "senderName", "content", "timestamp", "replyToId"}:
            raise ValueError("invalid_preview_history_record")
        for key, maximum in (("id", 256), ("senderId", 128), ("senderName", 100), ("content", 2_000)):
            field = item.get(key)
            if not isinstance(field, str) or len(field) > maximum or (key != "senderName" and not field.strip()):
                raise ValueError("invalid_preview_history_record")
        if item["id"] in seen:
            raise ValueError("duplicate_preview_history_message")
        seen.add(item["id"])
        timestamp = item.get("timestamp")
        if timestamp is not None:
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError
                item["timestamp"] = parsed.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError, AttributeError):
                raise ValueError("invalid_preview_history_timestamp") from None
        reply = item.get("replyToId")
        if reply is not None and (not isinstance(reply, str) or len(reply) > 256):
            raise ValueError("invalid_preview_history_reply")
        total += len(item["content"])
    if total > 36_000 or type(value.get("truncated")) is not bool:
        raise ValueError("invalid_preview_history_limit")
    return value


async def runtime_preview_response(plugin: object):
    from astrbot.api.web import error_response, request

    payload = await request.json(default={})
    try:
        event, prompt = preview_event(payload)
    except ValueError as exc:
        return error_response(str(exc), status_code=400)
    return await _runtime_preview_json(plugin, event, prompt)


async def runtime_native_message_preview_response(plugin: object):
    """Replay one live NapCat message through the native adapter without output."""

    from astrbot.api.web import error_response, request

    payload = await request.json(default={})
    try:
        event, prompt, source = await native_message_preview_event(plugin, payload)
    except ValueError as exc:
        return error_response(str(exc), status_code=400)
    except LookupError as exc:
        return error_response(str(exc), status_code=404)
    except RuntimeError as exc:
        return error_response(str(exc), status_code=502)
    return await _runtime_preview_json(plugin, event, prompt, source=source)


async def native_message_preview_event(
    plugin: object,
    payload: object,
) -> tuple[object, str, dict[str, str]]:
    """Fetch one message from NapCat and run AstrBot's installed conversion path."""

    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    account_id = str(payload.get("accountId") or "").strip()
    conversation_id = str(payload.get("conversationId") or "").strip()
    platform_id = str(payload.get("platformId") or "").strip()
    message_id = str(payload.get("messageId") or "").strip()
    account = _ACCOUNT_PATTERN.fullmatch(account_id)
    conversation = _GROUP_PATTERN.fullmatch(conversation_id)
    if (
        account is None
        or conversation is None
        or account.group(1) != conversation.group(1)
    ):
        raise ValueError("invalid_scope")
    if _PLATFORM_PATTERN.fullmatch(platform_id) is None:
        raise ValueError("invalid_platform")
    if _MESSAGE_PATTERN.fullmatch(message_id) is None:
        raise ValueError("invalid_message_id")

    context = getattr(plugin, "context", None)
    resolve_platform = getattr(context, "get_platform_inst", None)
    adapter = resolve_platform(platform_id) if callable(resolve_platform) else None
    if adapter is None:
        raise LookupError("native_platform_not_found")
    meta = getattr(adapter, "meta", lambda: None)()
    if getattr(meta, "name", None) != "aiocqhttp":
        raise ValueError("native_platform_not_onebot")
    get_client = getattr(adapter, "get_client", None)
    client = get_client() if callable(get_client) else None
    call_action = getattr(client, "call_action", None)
    if not callable(call_action):
        raise RuntimeError("native_platform_unavailable")

    try:
        history = await call_action(
            action="get_group_msg_history",
            group_id=int(conversation.group(2)),
            count=100,
            reverse_order=False,
            disable_get_url=False,
            parse_mult_msg=True,
            self_id=int(account.group(1)),
        )
    except Exception as exc:
        raise RuntimeError("native_message_lookup_failed") from exc
    messages = history.get("messages") if isinstance(history, dict) else None
    raw = (
        next(
            (
                item
                for item in messages
                if isinstance(item, dict)
                and str(item.get("message_id")) == message_id
            ),
            None,
        )
        if isinstance(messages, list)
        else None
    )
    if raw is None:
        raise LookupError("native_message_not_found")
    raw_group_id = str(raw.get("group_id") or "")
    if raw_group_id != conversation.group(2):
        raise ValueError("native_message_scope_mismatch")
    sender = raw.get("sender")
    if not isinstance(sender, dict) or not isinstance(raw.get("message"), list):
        raise RuntimeError("native_message_shape_invalid")
    sender_id = str(raw.get("user_id") or sender.get("user_id") or "").strip()
    if not sender_id:
        raise RuntimeError("native_message_shape_invalid")

    onebot_payload = dict(raw)
    onebot_payload.update(
        {
            "self_id": int(account.group(1)),
            "post_type": "message",
            "message_type": "group",
            "sub_type": str(raw.get("sub_type") or "normal"),
            "group_id": int(conversation.group(2)),
            "user_id": int(sender_id),
        }
    )
    onebot_event = _onebot_event_from_payload(onebot_payload)
    if onebot_event is None:
        raise RuntimeError("native_message_shape_invalid")
    convert_message = getattr(adapter, "convert_message", None)
    create_event = getattr(adapter, "create_event", None)
    if not callable(convert_message) or not callable(create_event):
        raise RuntimeError("native_platform_unavailable")
    message = await convert_message(onebot_event)
    if message is None:
        raise RuntimeError("native_message_ignored")
    event = create_event(message)
    prompt = str(getattr(message, "message_str", "") or "").strip()
    if not prompt:
        raise ValueError("native_message_has_no_text")
    return (
        event,
        prompt,
        {
            "kind": "napcat.get_group_msg_history",
            "platformId": platform_id,
            "messageId": message_id,
            "senderId": sender_id,
        },
    )


async def _runtime_preview_json(
    plugin: object,
    event: object,
    prompt: str,
    *,
    source: dict[str, str] | None = None,
):
    from astrbot.api.web import error_response, json_response

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
    data = {
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
        "capabilityIds": list(preview.capability_ids),
        "outcome": result.outcome.value if candidate or result.outcome.value != "response" else "empty",
        "runtimeState": preview.completion.final_phase.value,
        "generationObserved": getattr(preview, "generation_observed", False),
    }
    usage = getattr(preview, "context_usage", None)
    if usage is not None:
        data.update(usage)
    if source is not None:
        data["source"] = source
    return json_response({"status": "ok", "data": data})


def _onebot_event_from_payload(payload: dict[str, object]) -> object | None:
    from aiocqhttp.event import Event

    return Event.from_payload(payload)


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


__all__ = [
    "WebRuntimePreviewEvent",
    "native_message_preview_event",
    "preview_event",
    "runtime_native_message_preview_response",
    "runtime_preview_response",
]
