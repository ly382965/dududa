from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Protocol, runtime_checkable

from dududa._compat import StrEnum
from dududa.domain.delivery import DeliveryStatus
from dududa.domain.primitives import DigestString, require_aware, require_non_empty
from dududa.errors import validation_error


_REVISION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class RolloutMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    CANARY = "canary"


@dataclass(frozen=True, slots=True)
class RolloutControlConfig:
    schema_version: int
    mode: RolloutMode
    revision: str
    delivery_enabled: bool
    allowlisted_group_ids: frozenset[str]
    kill_switch: bool
    tools_enabled: bool
    memory_enabled: bool
    maximum_text_bytes: int
    shadow_max_in_flight: int
    shadow_timeout: timedelta
    canary_timeout: timedelta

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.mode, RolloutMode):
            raise validation_error("invalid_rollout_mode")
        if _REVISION_PATTERN.fullmatch(self.revision) is None:
            raise validation_error("invalid_rollout_revision")
        for field_name in (
            "delivery_enabled",
            "kill_switch",
            "tools_enabled",
            "memory_enabled",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise validation_error("invalid_rollout_boolean", field_name)
        groups = frozenset(self.allowlisted_group_ids)
        if any(
            not isinstance(group_id, str)
            or not group_id.strip()
            or group_id != group_id.strip()
            or len(group_id) > 128
            for group_id in groups
        ):
            raise validation_error("invalid_rollout_group_allowlist")
        if type(self.maximum_text_bytes) is not int or not (
            1 <= self.maximum_text_bytes <= 65_536
        ):
            raise validation_error("invalid_rollout_text_limit")
        if type(self.shadow_max_in_flight) is not int or not (
            1 <= self.shadow_max_in_flight <= 1_024
        ):
            raise validation_error("invalid_shadow_capacity")
        for field_name in ("shadow_timeout", "canary_timeout"):
            value = getattr(self, field_name)
            if not isinstance(value, timedelta) or not (
                timedelta(milliseconds=1) <= value <= timedelta(minutes=30)
            ):
                raise validation_error("invalid_rollout_timeout", field_name)
        object.__setattr__(self, "allowlisted_group_ids", groups)


def parse_rollout_control_config(value: Mapping[str, object]) -> RolloutControlConfig:
    if not isinstance(value, Mapping):
        raise validation_error("invalid_rollout_config")
    expected = {
        "schema_version",
        "mode",
        "revision",
        "delivery_enabled",
        "allowlisted_group_ids",
        "kill_switch",
        "tools_enabled",
        "memory_enabled",
        "maximum_text_bytes",
        "shadow_max_in_flight",
        "shadow_timeout_ms",
        "canary_timeout_ms",
    }
    if set(value) != expected:
        raise validation_error("invalid_rollout_config_fields")
    raw_mode = value["mode"]
    if not isinstance(raw_mode, str):
        raise validation_error("invalid_rollout_mode")
    try:
        mode = RolloutMode(raw_mode)
    except ValueError:
        raise validation_error("invalid_rollout_mode") from None
    raw_groups = value["allowlisted_group_ids"]
    if isinstance(raw_groups, (str, bytes)) or not isinstance(
        raw_groups, (list, tuple, set, frozenset)
    ):
        raise validation_error("invalid_rollout_group_allowlist")
    shadow_timeout_ms = _strict_int(value["shadow_timeout_ms"], "shadow_timeout_ms")
    canary_timeout_ms = _strict_int(value["canary_timeout_ms"], "canary_timeout_ms")
    return RolloutControlConfig(
        schema_version=_strict_int(value["schema_version"], "schema_version"),
        mode=mode,
        revision=_strict_string(value["revision"], "revision"),
        delivery_enabled=_strict_bool(value["delivery_enabled"], "delivery_enabled"),
        allowlisted_group_ids=frozenset(raw_groups),
        kill_switch=_strict_bool(value["kill_switch"], "kill_switch"),
        tools_enabled=_strict_bool(value["tools_enabled"], "tools_enabled"),
        memory_enabled=_strict_bool(value["memory_enabled"], "memory_enabled"),
        maximum_text_bytes=_strict_int(
            value["maximum_text_bytes"], "maximum_text_bytes"
        ),
        shadow_max_in_flight=_strict_int(
            value["shadow_max_in_flight"], "shadow_max_in_flight"
        ),
        shadow_timeout=timedelta(milliseconds=shadow_timeout_ms),
        canary_timeout=timedelta(milliseconds=canary_timeout_ms),
    )


@runtime_checkable
class RolloutControlProvider(Protocol):
    def current(self) -> RolloutControlConfig: ...


class StaticRolloutControlProvider:
    def __init__(self, config: RolloutControlConfig) -> None:
        if not isinstance(config, RolloutControlConfig):
            raise TypeError("invalid rollout control config")
        self._config = config

    def current(self) -> RolloutControlConfig:
        return self._config


class RolloutAdmissionAction(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    CANARY = "canary"


@dataclass(frozen=True, slots=True)
class RolloutAdmissionDecision:
    schema_version: int
    action: RolloutAdmissionAction
    control_revision: str
    message_key_digest: DigestString
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.action, RolloutAdmissionAction):
            raise validation_error("invalid_rollout_admission_action")
        if _REVISION_PATTERN.fullmatch(self.control_revision) is None:
            raise validation_error("invalid_rollout_revision")
        require_non_empty(str(self.message_key_digest), "rollout_message_key_digest")
        reasons = _reason_codes(self.reason_codes)
        if not reasons:
            raise validation_error("empty_rollout_reason_codes")
        object.__setattr__(self, "reason_codes", reasons)


class RolloutOwnershipState(StrEnum):
    CLAIMED = "claimed"
    RUNTIME_STARTED = "runtime_started"
    READY_TO_SEND = "ready_to_send"
    SEND_STARTED = "send_started"
    NO_DELIVERY = "no_delivery"
    SUPPRESSED = "suppressed"
    ABORTED = "aborted"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.NO_DELIVERY,
            self.SUPPRESSED,
            self.ABORTED,
            self.SUCCEEDED,
            self.PARTIAL,
            self.FAILED,
            self.UNKNOWN,
        }


class RolloutClaimDisposition(StrEnum):
    ACQUIRED = "acquired"
    EXISTING = "existing"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class RolloutOwnershipRecord:
    schema_version: int
    message_key_digest: DigestString
    invocation_digest: DigestString
    control_revision: str
    state: RolloutOwnershipState
    revision: int
    delivery_id: str | None
    delivery_request_digest: DigestString | None
    delivery_status: DeliveryStatus | None
    reason_code: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(str(self.message_key_digest), "rollout_message_key_digest")
        require_non_empty(str(self.invocation_digest), "rollout_invocation_digest")
        if _REVISION_PATTERN.fullmatch(self.control_revision) is None:
            raise validation_error("invalid_rollout_revision")
        if not isinstance(self.state, RolloutOwnershipState):
            raise validation_error("invalid_rollout_ownership_state")
        if type(self.revision) is not int or self.revision < 1:
            raise validation_error("invalid_rollout_ownership_revision")
        if (self.delivery_id is None) != (self.delivery_request_digest is None):
            raise validation_error("incomplete_rollout_delivery_binding")
        if self.delivery_id is not None:
            require_non_empty(self.delivery_id, "rollout_delivery_id")
            require_non_empty(
                str(self.delivery_request_digest), "rollout_delivery_request_digest"
            )
        if self.delivery_status is not None and not isinstance(
            self.delivery_status, DeliveryStatus
        ):
            raise validation_error("invalid_rollout_delivery_status")
        expected_status = {
            RolloutOwnershipState.NO_DELIVERY: DeliveryStatus.NOT_REQUIRED,
            RolloutOwnershipState.SUCCEEDED: DeliveryStatus.SUCCEEDED,
            RolloutOwnershipState.PARTIAL: DeliveryStatus.PARTIAL,
            RolloutOwnershipState.FAILED: DeliveryStatus.FAILED,
            RolloutOwnershipState.UNKNOWN: DeliveryStatus.UNKNOWN,
        }.get(self.state)
        if expected_status is not None and self.delivery_status is not expected_status:
            raise validation_error("rollout_delivery_status_state_mismatch")
        if expected_status is None and self.delivery_status is not None:
            raise validation_error("unexpected_rollout_delivery_status")
        if self.reason_code is not None:
            _reason_codes((self.reason_code,))
        require_aware(self.created_at, "rollout_created_at")
        require_aware(self.updated_at, "rollout_updated_at")
        if self.updated_at < self.created_at:
            raise validation_error("invalid_rollout_record_time")


@dataclass(frozen=True, slots=True)
class RolloutClaimResult:
    schema_version: int
    disposition: RolloutClaimDisposition
    record: RolloutOwnershipRecord

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.disposition, RolloutClaimDisposition):
            raise validation_error("invalid_rollout_claim_disposition")
        if not isinstance(self.record, RolloutOwnershipRecord):
            raise validation_error("invalid_rollout_ownership_record")


def _strict_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise validation_error("invalid_rollout_boolean", field_name)
    return value


def _strict_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise validation_error("invalid_rollout_integer", field_name)
    return value


def _strict_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_rollout_string", field_name)
    return value


def _reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_rollout_reason_codes")
    result = tuple(values)
    if len(result) != len(set(result)) or any(
        not isinstance(value, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,127}", value) is None
        for value in result
    ):
        raise validation_error("invalid_rollout_reason_codes")
    return tuple(sorted(result))


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
