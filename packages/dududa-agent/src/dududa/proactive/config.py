from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dududa.domain.primitives import DigestString
from dududa.errors import validation_error

from .contracts import (
    LocalTimeWindow,
    ProactiveRunMode,
    ProactiveTriggerKind,
)

_REVISION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_BEHAVIOR_FIELDS = frozenset(
    {
        "schema_version",
        "mode",
        "revision",
        "timezone",
        "delivery_enabled",
        "allowlisted_scope_digests",
        "kill_switch",
        "maximum_global_messages",
        "maximum_scope_messages",
        "quota_window_seconds",
        "quiet_hours",
    }
)
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "policy_revision",
        "digest",
        "probe",
    }
)
_WINDOW_FIELDS = frozenset({"start", "end"})


@dataclass(frozen=True, slots=True)
class ProactiveBehaviorControl:
    schema_version: int
    mode: ProactiveRunMode
    revision: str
    timezone: str
    delivery_enabled: bool
    allowlisted_scope_digests: frozenset[DigestString]
    kill_switch: bool
    maximum_global_messages: int
    maximum_scope_messages: int
    quota_window: timedelta
    quiet_hours: tuple[LocalTimeWindow, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.mode, ProactiveRunMode):
            raise validation_error("invalid_proactive_mode")
        if self.mode is ProactiveRunMode.PREVIEW:
            raise validation_error("preview_mode_forbidden_in_delivery_control")
        _revision(self.revision, "proactive_behavior_revision")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise validation_error("invalid_proactive_timezone")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise validation_error("invalid_proactive_timezone") from None
        if (
            type(self.delivery_enabled) is not bool
            or type(self.kill_switch) is not bool
        ):
            raise validation_error("invalid_proactive_control_boolean")
        scopes = frozenset(self.allowlisted_scope_digests)
        if any(
            not isinstance(value, str) or not value.strip() or value != value.strip()
            for value in scopes
        ):
            raise validation_error("invalid_proactive_scope_allowlist")
        for field_name in (
            "maximum_global_messages",
            "maximum_scope_messages",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or not 1 <= value <= 100_000:
                raise validation_error("invalid_proactive_quota", field_name)
        if not isinstance(self.quota_window, timedelta) or not (
            timedelta(minutes=1) <= self.quota_window <= timedelta(days=366)
        ):
            raise validation_error("invalid_proactive_quota_window")
        windows = tuple(self.quiet_hours)
        if any(not isinstance(value, LocalTimeWindow) for value in windows):
            raise validation_error("invalid_proactive_quiet_hours")
        if len(windows) != len(set(windows)) or len(windows) > 32:
            raise validation_error("invalid_proactive_quiet_hours")
        if self.mode is ProactiveRunMode.CANARY:
            if not self.delivery_enabled:
                raise validation_error("canary_delivery_not_enabled")
        elif self.delivery_enabled:
            raise validation_error("non_canary_delivery_enabled")
        object.__setattr__(self, "allowlisted_scope_digests", scopes)
        object.__setattr__(self, "quiet_hours", windows)


@dataclass(frozen=True, slots=True)
class ProactiveControlConfig:
    schema_version: int
    policy_revision: str
    digest: ProactiveBehaviorControl
    probe: ProactiveBehaviorControl

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _revision(self.policy_revision, "proactive_policy_revision")
        if not isinstance(self.digest, ProactiveBehaviorControl) or not isinstance(
            self.probe, ProactiveBehaviorControl
        ):
            raise validation_error("invalid_proactive_behavior_control")
        if self.digest.revision == self.probe.revision:
            raise validation_error("proactive_behavior_revision_collision")

    def for_trigger(self, kind: ProactiveTriggerKind) -> ProactiveBehaviorControl:
        if not isinstance(kind, ProactiveTriggerKind):
            raise validation_error("invalid_proactive_trigger_kind")
        if kind is ProactiveTriggerKind.SCHEDULED_DIGEST:
            return self.digest
        return self.probe


def default_proactive_control_config() -> ProactiveControlConfig:
    common = {
        "schema_version": 1,
        "mode": ProactiveRunMode.OFF,
        "timezone": "Asia/Shanghai",
        "delivery_enabled": False,
        "allowlisted_scope_digests": frozenset(),
        "kill_switch": True,
        "maximum_global_messages": 1,
        "maximum_scope_messages": 1,
        "quota_window": timedelta(days=1),
        "quiet_hours": (),
    }
    return ProactiveControlConfig(
        schema_version=1,
        policy_revision="proactive-default-deny-v1",
        digest=ProactiveBehaviorControl(
            revision="digest-default-deny-v1",
            **common,
        ),
        probe=ProactiveBehaviorControl(
            revision="probe-default-deny-v1",
            **common,
        ),
    )


def parse_proactive_control_config(
    document: Mapping[str, object],
) -> ProactiveControlConfig:
    if not isinstance(document, Mapping) or set(document) != _ROOT_FIELDS:
        raise validation_error("invalid_proactive_config_fields")
    return ProactiveControlConfig(
        schema_version=_int(document["schema_version"], "schema_version"),
        policy_revision=_string(document["policy_revision"], "policy_revision"),
        digest=_parse_behavior(document["digest"], "digest"),
        probe=_parse_behavior(document["probe"], "probe"),
    )


def _parse_behavior(value: object, field_name: str) -> ProactiveBehaviorControl:
    if not isinstance(value, Mapping) or set(value) != _BEHAVIOR_FIELDS:
        raise validation_error("invalid_proactive_behavior_fields", field_name)
    raw_mode = value["mode"]
    if not isinstance(raw_mode, str):
        raise validation_error("invalid_proactive_mode", field_name)
    try:
        mode = ProactiveRunMode(raw_mode)
    except ValueError:
        raise validation_error("invalid_proactive_mode", field_name) from None
    raw_scopes = value["allowlisted_scope_digests"]
    if isinstance(raw_scopes, (str, bytes)) or not isinstance(
        raw_scopes, (list, tuple, set, frozenset)
    ):
        raise validation_error("invalid_proactive_scope_allowlist", field_name)
    raw_windows = value["quiet_hours"]
    if isinstance(raw_windows, (str, bytes)) or not isinstance(
        raw_windows, (list, tuple)
    ):
        raise validation_error("invalid_proactive_quiet_hours", field_name)
    return ProactiveBehaviorControl(
        schema_version=_int(value["schema_version"], "schema_version"),
        mode=mode,
        revision=_string(value["revision"], "revision"),
        timezone=_string(value["timezone"], "timezone"),
        delivery_enabled=_bool(value["delivery_enabled"], "delivery_enabled"),
        allowlisted_scope_digests=frozenset(raw_scopes),
        kill_switch=_bool(value["kill_switch"], "kill_switch"),
        maximum_global_messages=_int(
            value["maximum_global_messages"], "maximum_global_messages"
        ),
        maximum_scope_messages=_int(
            value["maximum_scope_messages"], "maximum_scope_messages"
        ),
        quota_window=timedelta(
            seconds=_int(value["quota_window_seconds"], "quota_window_seconds")
        ),
        quiet_hours=tuple(
            _parse_window(item, f"quiet_hours[{index}]")
            for index, item in enumerate(raw_windows)
        ),
    )


def _parse_window(value: object, field_name: str) -> LocalTimeWindow:
    if not isinstance(value, Mapping) or set(value) != _WINDOW_FIELDS:
        raise validation_error("invalid_proactive_quiet_window", field_name)
    return LocalTimeWindow.from_strings(
        _string(value["start"], f"{field_name}.start"),
        _string(value["end"], f"{field_name}.end"),
    )


def _v1(value: object) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _revision(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise validation_error("invalid_proactive_revision", field_name)
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise validation_error("invalid_proactive_string", field_name)
    return value


def _bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise validation_error("invalid_proactive_boolean", field_name)
    return value


def _int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise validation_error("invalid_proactive_integer", field_name)
    return value


__all__ = [
    "ProactiveBehaviorControl",
    "ProactiveControlConfig",
    "default_proactive_control_config",
    "parse_proactive_control_config",
]
