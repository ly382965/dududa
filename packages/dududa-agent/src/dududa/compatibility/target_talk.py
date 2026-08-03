from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class TargetUser:
    qq: str
    alias: str
    enabled: bool
    group_whitelist: frozenset[str]
    probability: float | None
    reply_style: str
    prompt_template: str


def should_handle_message(
    *,
    enabled: bool,
    group_id: str,
    sender_id: str,
    self_id: str,
    is_at_or_wake_command: bool,
    ignore_at_or_wake_command: bool,
    configured_targets: Mapping[str, TargetUser],
    group_whitelist: frozenset[str] | set[str],
    text: str,
    minimum_characters: int,
    maximum_characters: int,
    exclude_patterns: Sequence[str],
    trigger_patterns: Sequence[str],
    on_invalid_regex: Callable[[str, re.error], None] | None = None,
) -> bool:
    if not enabled:
        return False
    if not group_id or not sender_id:
        return False
    if sender_id == self_id:
        return False
    if group_whitelist and group_id not in group_whitelist:
        return False
    if ignore_at_or_wake_command and is_at_or_wake_command:
        return False
    if sender_id not in configured_targets:
        return False

    normalized = (text or "").strip()
    if len(normalized) < minimum_characters:
        return False
    if maximum_characters and len(normalized) > maximum_characters:
        return False
    if exclude_patterns and matches_any(exclude_patterns, normalized, on_invalid_regex):
        return False
    if trigger_patterns and not matches_any(
        trigger_patterns, normalized, on_invalid_regex
    ):
        return False
    return True


def target_enabled_for_group(target: TargetUser, group_id: str) -> bool:
    return target.enabled and (
        not target.group_whitelist or group_id in target.group_whitelist
    )


def in_cooldown(last: float, now: float, seconds: int) -> bool:
    return seconds > 0 and now - last < seconds


def matches_any(
    patterns: Sequence[str],
    text: str,
    on_invalid_regex: Callable[[str, re.error], None] | None = None,
) -> bool:
    for pattern in patterns:
        if not pattern:
            continue
        if pattern.startswith("re:"):
            try:
                if re.search(pattern[3:], text, flags=re.I):
                    return True
            except re.error as exc:
                if on_invalid_regex is not None:
                    on_invalid_regex(pattern, exc)
            continue
        if pattern.lower() in text.lower():
            return True
    return False


def load_targets(raw_targets: object) -> dict[str, TargetUser]:
    targets: dict[str, TargetUser] = {}
    if not isinstance(raw_targets, list):
        raw_targets = []
    for item in raw_targets:
        if isinstance(item, str):
            qq = item.strip()
            data: Mapping[str, Any] = {}
        elif isinstance(item, Mapping):
            data = item
            qq = str(data.get("qq", "") or "").strip()
        else:
            continue
        if not qq or not qq.isdigit():
            continue
        probability = float_or_none(data.get("probability", -1))
        if probability is not None and probability < 0:
            probability = None
        if probability is not None:
            probability = max(0.0, min(1.0, probability))
        targets[qq] = TargetUser(
            qq=qq,
            alias=str(data.get("alias", "") or "").strip(),
            enabled=coerce_bool(data.get("enabled", True), True),
            group_whitelist=frozenset(
                coerce_string_list(data.get("group_whitelist", []))
            ),
            probability=probability,
            reply_style=str(data.get("reply_style", "") or "").strip(),
            prompt_template=str(data.get("prompt_template", "") or "").strip(),
        )
    return targets


def clean_reply(text: str, maximum_characters: int) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"^\s*(回复|回答|输出)\s*[:：]\s*", "", text)
    text = text.strip(" \t\r\n\"'“”")
    text = re.sub(r"\[CQ:at,qq=\d+\]\s*", "", text)
    text = re.sub(r"@\S+\s*", "", text)
    if len(text) > maximum_characters:
        text = text[:maximum_characters].rstrip()
        if text and text[-1] not in "。！？!?~～":
            text += "..."
    return text


def safe_format(template: str, values: Mapping[str, str]) -> tuple[str, bool]:
    try:
        return template.format(**values), True
    except Exception:
        return template, False


def history_entry(sender: str, text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if len(normalized) > 180:
        normalized = normalized[:177] + "..."
    return f"{sender}: {normalized}"


def coerce_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[,，\n]", value)
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off", "否"}


def coerce_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def clamp_float(value: object, default: float, minimum: float, maximum: float) -> float:
    parsed = float_or_none(value)
    if parsed is None:
        parsed = default
    return max(minimum, min(maximum, parsed))
