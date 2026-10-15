from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from dududa._compat import StrEnum
from dududa.domain.primitives import (
    ActionId,
    RiskLevel,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error
from dududa.ports.context import ServiceCallContext


class OperationalSurface(StrEnum):
    RUNS = "runs"
    MODEL_ROUTER = "model_router"
    MCP_CAPABILITY = "mcp_capability"
    PLUGINS = "plugins"
    MEMORY = "memory"
    PROACTIVE = "proactive"


class OperationalStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    OFF = "off"
    SHADOW = "shadow"
    UNAVAILABLE = "unavailable"


class OperationalEvidenceMode(StrEnum):
    UNAVAILABLE = "unavailable"
    FIXTURE = "fixture"
    OFFLINE = "offline"
    SHADOW = "shadow"
    CANARY = "canary"
    LIVE = "live"


class MutationScopeKind(StrEnum):
    BOT = "bot"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class OperationalScope:
    schema_version: int
    platform: str
    bot_id: str
    group_id: str | None = None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.platform, "platform")
        require_non_empty(self.bot_id, "bot_id")
        if self.group_id is not None:
            require_non_empty(self.group_id, "group_id")


@dataclass(frozen=True, slots=True)
class OperationalFact:
    schema_version: int
    fact_id: str
    label: str
    status: OperationalStatus
    revision: str
    detail: str
    reason_codes: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("fact_id", "label", "revision", "detail"):
            require_non_empty(str(getattr(self, name)), name)
        if not isinstance(self.status, OperationalStatus):
            raise validation_error("invalid_operational_fact_status")
        object.__setattr__(
            self,
            "reason_codes",
            _reason_codes(self.reason_codes, "operational_fact_reason_codes"),
        )
        require_aware(self.observed_at, "operational_fact_observed_at")


@dataclass(frozen=True, slots=True)
class OperationalProjection:
    schema_version: int
    surface: OperationalSurface
    scope: OperationalScope
    revision: str
    evidence_mode: OperationalEvidenceMode
    status: OperationalStatus
    facts: tuple[OperationalFact, ...]
    reason_codes: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.surface, OperationalSurface):
            raise validation_error("invalid_operational_surface")
        if not isinstance(self.scope, OperationalScope):
            raise validation_error("invalid_operational_scope")
        require_non_empty(self.revision, "operational_projection_revision")
        if not isinstance(self.evidence_mode, OperationalEvidenceMode):
            raise validation_error("invalid_operational_evidence_mode")
        if not isinstance(self.status, OperationalStatus):
            raise validation_error("invalid_operational_projection_status")
        facts = tuple(self.facts)
        if any(not isinstance(item, OperationalFact) for item in facts):
            raise validation_error("invalid_operational_facts")
        ids = tuple(item.fact_id for item in facts)
        if len(ids) != len(set(ids)):
            raise validation_error("duplicate_operational_fact")
        reasons = _reason_codes(
            self.reason_codes,
            "operational_projection_reason_codes",
        )
        if self.status is OperationalStatus.UNAVAILABLE:
            if self.evidence_mode is not OperationalEvidenceMode.UNAVAILABLE or not reasons:
                raise validation_error("invalid_unavailable_operational_projection")
        elif self.evidence_mode is OperationalEvidenceMode.UNAVAILABLE:
            raise validation_error("available_projection_has_unavailable_evidence")
        if any(item.observed_at > self.observed_at for item in facts):
            raise validation_error("operational_fact_from_future")
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "reason_codes", reasons)
        require_aware(self.observed_at, "operational_projection_observed_at")


@dataclass(frozen=True, slots=True)
class GovernedMutationDescriptor:
    schema_version: int
    action: ActionId
    display_name: str
    handler_id: str
    scope_kind: MutationScopeKind
    risk_level: RiskLevel

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(str(self.action), "governed_mutation_action")
        require_non_empty(self.display_name, "governed_mutation_display_name")
        require_non_empty(self.handler_id, "governed_mutation_handler_id")
        if not isinstance(self.scope_kind, MutationScopeKind):
            raise validation_error("invalid_mutation_scope_kind")
        if not isinstance(self.risk_level, RiskLevel):
            raise validation_error("invalid_mutation_risk_level")


@dataclass(frozen=True, slots=True)
class OperationalProjectionQuery:
    schema_version: int
    query_id: str
    session_ref: str
    scope: OperationalScope
    surfaces: tuple[OperationalSurface, ...]
    requested_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.query_id, "query_id")
        require_non_empty(self.session_ref, "session_ref")
        if not isinstance(self.scope, OperationalScope):
            raise validation_error("invalid_operational_scope")
        surfaces = tuple(self.surfaces)
        if not surfaces or any(not isinstance(item, OperationalSurface) for item in surfaces):
            raise validation_error("invalid_operational_query_surfaces")
        if len(surfaces) != len(set(surfaces)):
            raise validation_error("duplicate_operational_query_surface")
        object.__setattr__(self, "surfaces", surfaces)
        require_aware(self.requested_at, "query_requested_at")


@dataclass(frozen=True, slots=True)
class GovernedOperationsProjection:
    schema_version: int
    scope: OperationalScope
    projections: tuple[OperationalProjection, ...]
    mutations: tuple[GovernedMutationDescriptor, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.scope, OperationalScope):
            raise validation_error("invalid_operational_scope")
        projections = tuple(self.projections)
        mutations = tuple(self.mutations)
        if any(item.scope != self.scope for item in projections):
            raise validation_error("operational_projection_scope_mismatch")
        surfaces = tuple(item.surface for item in projections)
        if len(surfaces) != len(set(surfaces)):
            raise validation_error("duplicate_operational_projection_surface")
        actions = tuple(str(item.action) for item in mutations)
        if len(actions) != len(set(actions)):
            raise validation_error("duplicate_governed_mutation_action")
        object.__setattr__(self, "projections", projections)
        object.__setattr__(self, "mutations", mutations)
        require_aware(self.generated_at, "operational_projection_generated_at")


class OperationalProjectionRegistry:
    def __init__(
        self,
        providers: Iterable[object] = (),
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._providers: dict[OperationalSurface, object] = {}
        for provider in providers:
            surface = getattr(provider, "surface", None)
            if not isinstance(surface, OperationalSurface) or not callable(
                getattr(provider, "project", None)
            ):
                raise validation_error("invalid_operational_projection_provider")
            if surface in self._providers:
                raise validation_error("duplicate_operational_projection_provider")
            self._providers[surface] = provider

    async def project(
        self,
        scope: OperationalScope,
        surfaces: tuple[OperationalSurface, ...],
        *,
        call: ServiceCallContext,
    ) -> tuple[OperationalProjection, ...]:
        _validate_call(call, self._clock())
        results: list[OperationalProjection] = []
        for surface in surfaces:
            provider = self._providers.get(surface)
            if provider is None:
                results.append(
                    unavailable_operational_projection(
                        surface,
                        scope,
                        "projection_provider_not_bound",
                        observed_at=self._clock(),
                    )
                )
                continue
            try:
                projected = await provider.project(scope, call=call)
            except Exception:  # noqa: BLE001 - query failures become explicit unavailable facts.
                _validate_call(call, self._clock())
                projected = unavailable_operational_projection(
                    surface,
                    scope,
                    "projection_provider_failed",
                    observed_at=self._clock(),
                )
            if not isinstance(projected, OperationalProjection):
                raise validation_error("invalid_operational_provider_result")
            if projected.surface is not surface or projected.scope != scope:
                raise validation_error("operational_provider_result_scope_mismatch")
            results.append(projected)
        return tuple(results)


class GovernedMutationRegistry:
    def __init__(self, descriptors: Iterable[GovernedMutationDescriptor] = ()) -> None:
        values = tuple(descriptors)
        actions = tuple(str(item.action) for item in values)
        if any(not isinstance(item, GovernedMutationDescriptor) for item in values):
            raise validation_error("invalid_governed_mutation_descriptor")
        if len(actions) != len(set(actions)):
            raise validation_error("duplicate_governed_mutation_action")
        self._descriptors = tuple(sorted(values, key=lambda item: str(item.action)))

    def discover(self, scope: OperationalScope) -> tuple[GovernedMutationDescriptor, ...]:
        required = MutationScopeKind.GROUP if scope.group_id is not None else MutationScopeKind.BOT
        return tuple(item for item in self._descriptors if item.scope_kind is required)


def group_service_mutation_descriptors() -> tuple[GovernedMutationDescriptor, ...]:
    return tuple(
        GovernedMutationDescriptor(
            1,
            ActionId(f"group_service.{action}"),
            display_name,
            "group-service-lifecycle-v1",
            MutationScopeKind.GROUP,
            RiskLevel.MEDIUM,
        )
        for action, display_name in (
            ("preview", "预览群服务"),
            ("activate", "激活群服务"),
            ("update", "更新群服务"),
            ("pause", "暂停群服务"),
            ("resume", "恢复群服务"),
            ("rollback", "回滚群服务"),
        )
    )


def unavailable_operational_projection(
    surface: OperationalSurface,
    scope: OperationalScope,
    reason_code: str,
    *,
    observed_at: datetime,
) -> OperationalProjection:
    return OperationalProjection(
        1,
        surface,
        scope,
        "unavailable",
        OperationalEvidenceMode.UNAVAILABLE,
        OperationalStatus.UNAVAILABLE,
        (),
        (reason_code,),
        observed_at,
    )


def _reason_codes(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_reason_codes", field)
    result = tuple(values)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise validation_error("invalid_reason_codes", field)
    if len(result) != len(set(result)):
        raise validation_error("duplicate_reason_code", field)
    return result


def _validate_call(call: ServiceCallContext, now: datetime) -> None:
    if not isinstance(call, ServiceCallContext):
        raise validation_error("invalid_control_plane_call_context")
    if call.cancellation.is_cancelled:
        raise validation_error("control_plane_call_cancelled")
    if call.deadline <= now:
        raise validation_error("control_plane_call_expired")


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


__all__ = [
    "GovernedMutationDescriptor",
    "GovernedMutationRegistry",
    "GovernedOperationsProjection",
    "MutationScopeKind",
    "OperationalEvidenceMode",
    "OperationalFact",
    "OperationalProjection",
    "OperationalProjectionQuery",
    "OperationalProjectionRegistry",
    "OperationalScope",
    "OperationalStatus",
    "OperationalSurface",
    "group_service_mutation_descriptors",
    "unavailable_operational_projection",
]
