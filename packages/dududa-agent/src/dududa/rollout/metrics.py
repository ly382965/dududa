from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
import threading

from dududa._compat import StrEnum
from dududa.domain.delivery import DeliveryStatus
from dududa.domain.primitives import Outcome
from dududa.errors import validation_error
from dududa.models.contracts import ModelRole, ModelTier

from .contracts import RolloutMode


class RolloutMetricStage(StrEnum):
    ADMISSION = "admission"
    SHADOW = "shadow"
    CLAIM = "claim"
    RUNTIME = "runtime"
    DELIVERY = "delivery"
    RECOVERY = "recovery"


class RolloutFailureKind(StrEnum):
    NONE = "none"
    NOT_ADMITTED = "not_admitted"
    CONFIG_INVALID = "config_invalid"
    CAPACITY = "capacity"
    TIMEOUT = "timeout"
    CONFLICT = "conflict"
    RUNTIME = "runtime"
    CONTROL_CHANGED = "control_changed"
    KILL_SWITCH = "kill_switch"
    DELIVERY_DISABLED = "delivery_disabled"
    OUTPUT = "output"
    ACKNOWLEDGEMENT = "acknowledgement"
    OUTCOME_UNKNOWN = "outcome_unknown"
    OTHER = "other"


class RolloutLatencyBucket(StrEnum):
    LE_10_MS = "le_10_ms"
    LE_50_MS = "le_50_ms"
    LE_100_MS = "le_100_ms"
    LE_250_MS = "le_250_ms"
    LE_500_MS = "le_500_ms"
    LE_1_S = "le_1_s"
    LE_2_5_S = "le_2_5_s"
    LE_5_S = "le_5_s"
    GT_5_S = "gt_5_s"
    NOT_RECORDED = "not_recorded"


def latency_bucket(milliseconds: int | None) -> RolloutLatencyBucket:
    if milliseconds is None:
        return RolloutLatencyBucket.NOT_RECORDED
    if type(milliseconds) is not int or milliseconds < 0:
        raise validation_error("invalid_rollout_latency")
    for limit, bucket in (
        (10, RolloutLatencyBucket.LE_10_MS),
        (50, RolloutLatencyBucket.LE_50_MS),
        (100, RolloutLatencyBucket.LE_100_MS),
        (250, RolloutLatencyBucket.LE_250_MS),
        (500, RolloutLatencyBucket.LE_500_MS),
        (1_000, RolloutLatencyBucket.LE_1_S),
        (2_500, RolloutLatencyBucket.LE_2_5_S),
        (5_000, RolloutLatencyBucket.LE_5_S),
    ):
        if milliseconds <= limit:
            return bucket
    return RolloutLatencyBucket.GT_5_S


@dataclass(frozen=True, slots=True)
class RolloutMetricObservation:
    schema_version: int
    mode: RolloutMode
    stage: RolloutMetricStage
    control_revision: str
    role: ModelRole | None
    tier: ModelTier | None
    endpoint_revision: str | None
    candidate_outcome: Outcome | None
    actual_delivery_status: DeliveryStatus | None
    failure_kind: RolloutFailureKind
    latency: RolloutLatencyBucket
    ttft: RolloutLatencyBucket
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_units: Decimal | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.mode, RolloutMode):
            raise validation_error("invalid_rollout_metric_mode")
        if not isinstance(self.stage, RolloutMetricStage):
            raise validation_error("invalid_rollout_metric_stage")
        _revision(self.control_revision, "control_revision")
        if self.role is not None and not isinstance(self.role, ModelRole):
            raise validation_error("invalid_rollout_metric_role")
        if self.tier is not None and not isinstance(self.tier, ModelTier):
            raise validation_error("invalid_rollout_metric_tier")
        if self.endpoint_revision is not None:
            _revision(self.endpoint_revision, "endpoint_revision")
        if self.candidate_outcome is not None and not isinstance(
            self.candidate_outcome, Outcome
        ):
            raise validation_error("invalid_rollout_metric_outcome")
        if self.actual_delivery_status is not None and not isinstance(
            self.actual_delivery_status, DeliveryStatus
        ):
            raise validation_error("invalid_rollout_metric_delivery_status")
        if not isinstance(self.failure_kind, RolloutFailureKind):
            raise validation_error("invalid_rollout_metric_failure")
        if not isinstance(self.latency, RolloutLatencyBucket) or not isinstance(
            self.ttft, RolloutLatencyBucket
        ):
            raise validation_error("invalid_rollout_metric_latency")
        for field_name in ("model_calls", "input_tokens", "output_tokens"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise validation_error("invalid_rollout_metric_usage", field_name)
        if self.cost_units is not None and (
            not isinstance(self.cost_units, Decimal)
            or not self.cost_units.is_finite()
            or self.cost_units < 0
        ):
            raise validation_error("invalid_rollout_metric_usage", "cost_units")


@dataclass(frozen=True, slots=True)
class RolloutMetricSeries:
    schema_version: int
    mode: RolloutMode
    stage: RolloutMetricStage
    control_revision: str
    role: ModelRole | None
    tier: ModelTier | None
    endpoint_revision: str | None
    candidate_outcome: Outcome | None
    actual_delivery_status: DeliveryStatus | None
    failure_kind: RolloutFailureKind
    latency: RolloutLatencyBucket
    ttft: RolloutLatencyBucket
    count: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost_units: Decimal | None


@dataclass(frozen=True, slots=True)
class RolloutMetricSummary:
    schema_version: int
    series: tuple[RolloutMetricSeries, ...]
    dropped_series: int

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        values = tuple(self.series)
        if any(not isinstance(item, RolloutMetricSeries) for item in values):
            raise validation_error("invalid_rollout_metric_summary")
        if type(self.dropped_series) is not int or self.dropped_series < 0:
            raise validation_error("invalid_rollout_metric_summary")
        object.__setattr__(self, "series", values)


class InMemoryRolloutMetrics:
    def __init__(self, maximum_series: int = 256) -> None:
        if type(maximum_series) is not int or not (1 <= maximum_series <= 4_096):
            raise validation_error("invalid_rollout_metric_capacity")
        self._maximum_series = maximum_series
        self._lock = threading.Lock()
        self._series: dict[tuple[object, ...], list[object]] = {}
        self._dropped_series = 0

    def record(self, observation: RolloutMetricObservation) -> None:
        if not isinstance(observation, RolloutMetricObservation):
            raise validation_error("invalid_rollout_metric_observation")
        key = _series_key(observation)
        with self._lock:
            aggregate = self._series.get(key)
            if aggregate is None:
                if len(self._series) >= self._maximum_series:
                    self._dropped_series += 1
                    return
                aggregate = [0, 0, 0, 0, None]
                self._series[key] = aggregate
            aggregate[0] = int(aggregate[0]) + 1
            aggregate[1] = int(aggregate[1]) + observation.model_calls
            aggregate[2] = int(aggregate[2]) + observation.input_tokens
            aggregate[3] = int(aggregate[3]) + observation.output_tokens
            if observation.cost_units is not None:
                aggregate[4] = (aggregate[4] or Decimal("0")) + observation.cost_units

    def summary(self) -> RolloutMetricSummary:
        with self._lock:
            rows = tuple(
                RolloutMetricSeries(
                    schema_version=1,
                    mode=key[0],
                    stage=key[1],
                    control_revision=key[2],
                    role=key[3],
                    tier=key[4],
                    endpoint_revision=key[5],
                    candidate_outcome=key[6],
                    actual_delivery_status=key[7],
                    failure_kind=key[8],
                    latency=key[9],
                    ttft=key[10],
                    count=int(value[0]),
                    model_calls=int(value[1]),
                    input_tokens=int(value[2]),
                    output_tokens=int(value[3]),
                    cost_units=value[4],
                )
                for key, value in sorted(
                    self._series.items(),
                    key=lambda item: tuple(str(v) for v in item[0]),
                )
            )
            return RolloutMetricSummary(1, rows, self._dropped_series)


def _series_key(value: RolloutMetricObservation) -> tuple[object, ...]:
    return (
        value.mode,
        value.stage,
        value.control_revision,
        value.role,
        value.tier,
        value.endpoint_revision,
        value.candidate_outcome,
        value.actual_delivery_status,
        value.failure_kind,
        value.latency,
        value.ttft,
    )


def _revision(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None
    ):
        raise validation_error("invalid_rollout_metric_revision", field_name)
