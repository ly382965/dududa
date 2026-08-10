from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal

from dududa.contracts.canonical import canonical_digest
from dududa.domain.capability import CapabilityDefinition
from dududa.domain.primitives import (
    ComponentRevision,
    PrivacyLevel,
    RiskLevel,
)
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.capabilities import CapabilityHealthRegistry, CapabilityRegistry
from dududa.ports.context import PortCallContext
from dududa.security.models import AuthorizationDecision, AuthorizationRequest
from dududa.security.ports import AuthorizationDecisionVerifier, AuthorizationPolicy

from .authorization import (
    CapabilityAuthorizationPurpose,
    build_capability_authorization_request,
    capability_authorization_allows,
)
from .contracts import (
    MAX_CAPABILITY_CANDIDATES,
    CapabilityCandidate,
    CapabilityCatalogSnapshot,
    CapabilityHealthSnapshot,
    CapabilityHealthStatus,
    CapabilityProviderHealth,
    CapabilityProviderKind,
    CapabilityRetrievalRequest,
    CapabilityRetrievalResult,
)
from .digests import (
    capability_candidate_digest,
    capability_retrieval_result_digest,
)

_TERM = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+")
_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}
_PRIVACY_ORDER = {
    PrivacyLevel.PUBLIC: 0,
    PrivacyLevel.CONVERSATION: 1,
    PrivacyLevel.PERSONAL: 2,
    PrivacyLevel.SENSITIVE: 3,
    PrivacyLevel.RESTRICTED: 4,
}


class DeterministicCapabilityRetriever:
    """Filter eligibility before deterministic lexical quality ranking."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        health: CapabilityHealthRegistry,
        authorization: AuthorizationPolicy,
        verifier: AuthorizationDecisionVerifier,
        *,
        clock: Callable[[], datetime] | None = None,
        revision: ComponentRevision | None = None,
        provider_cap: int = 4,
        category_cap: int = 4,
    ) -> None:
        if not 1 <= provider_cap <= MAX_CAPABILITY_CANDIDATES:
            raise ValueError("provider_cap is outside the retrieval ceiling")
        if not 1 <= category_cap <= MAX_CAPABILITY_CANDIDATES:
            raise ValueError("category_cap is outside the retrieval ceiling")
        self._registry = registry
        self._health = health
        self._authorization = authorization
        self._verifier = verifier
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._revision = revision or ComponentRevision(
            "capability.retriever",
            "1.0.0",
            "deterministic-v1",
            canonical_digest(
                {"implementation": "deterministic-capability-retriever"},
                domain="capability.retriever-artifact:v1",
            ),
        )
        self._provider_cap = provider_cap
        self._category_cap = category_cap

    async def retrieve(
        self,
        request: CapabilityRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> CapabilityRetrievalResult:
        if not isinstance(request, CapabilityRetrievalRequest):
            raise validation_error("invalid_capability_retrieval_request")
        now = self._now()
        _validate_call(call, now)
        catalog = self._registry.acquire_snapshot()
        if not isinstance(catalog, CapabilityCatalogSnapshot):
            raise validation_error("invalid_capability_catalog_snapshot")
        try:
            health = await self._health.snapshot(catalog, call=call)
        except Exception:  # noqa: BLE001 - Health implementation details are hidden.
            _validate_call(call, self._now())
            raise error(
                "capability_health_snapshot_unavailable",
                ErrorCategory.EXTERNAL,
                "service.unavailable",
            ) from None
        if not isinstance(health, CapabilityHealthSnapshot):
            raise validation_error("invalid_capability_health_snapshot")
        now = self._now()
        _validate_call(call, now)
        candidates: list[CapabilityCandidate] = []
        for definition in catalog.definitions:
            if not self._configured(definition, catalog):
                continue
            if _healthy(definition, health, now=now) is None:
                continue
            if request.conversation_scope.conversation_type not in (
                definition.allowed_contexts
            ):
                continue
            if not await self._authorized(
                definition,
                catalog,
                request,
                call=call,
            ):
                continue
            now = self._now()
            _validate_call(call, now)
            if _healthy(definition, health, now=now) is None:
                continue
            if (
                _PRIVACY_ORDER[request.data_classification]
                > _PRIVACY_ORDER[definition.privacy_level]
            ):
                continue
            if (
                _RISK_ORDER[definition.risk_level]
                > _RISK_ORDER[request.query.maximum_risk_level]
            ):
                continue
            if definition.side_effects & request.query.excluded_side_effects:
                continue
            if definition.input_schema not in request.available_input_schemas:
                continue
            if (
                request.query.required_output_schema is not None
                and definition.output_schema != request.query.required_output_schema
            ):
                continue
            now = self._now()
            _validate_call(call, now)
            remaining_ms = int((call.deadline - now).total_seconds() * 1000)
            if (
                definition.latency_hint.maximum_ms > request.maximum_latency_ms
                or definition.latency_hint.maximum_ms > remaining_ms
                or call.budget.tool_steps_remaining < 1
                or (
                    call.budget.cost_units_remaining is not None
                    and Decimal(definition.cost_hint.units)
                    > call.budget.cost_units_remaining
                )
            ):
                continue
            candidates.append(_candidate(definition, request))
        candidates.sort(key=lambda item: (-item.rank_score, item.capability_id))
        selected = _apply_caps(
            candidates,
            limit=request.limit,
            provider_cap=self._provider_cap,
            category_cap=self._category_cap,
        )
        reasons = ("eligible_candidates",) if selected else ("no_eligible_capability",)
        values = {
            "schema_version": 1,
            "request_digest": request.request_digest,
            "query_digest": request.query.query_digest,
            "candidates": selected,
            "catalog_snapshot_id": catalog.snapshot_id,
            "catalog_digest": catalog.catalog_digest,
            "policy_revision": call.policy_snapshot_id,
            "health_snapshot_id": health.snapshot_id,
            "health_snapshot_digest": health.snapshot_digest,
            "retriever_revision": self._revision,
            "reason_codes": reasons,
        }
        return CapabilityRetrievalResult(
            result_digest=capability_retrieval_result_digest(values),
            **values,
        )

    def _configured(
        self,
        definition: CapabilityDefinition,
        catalog: CapabilityCatalogSnapshot,
    ) -> bool:
        if not definition.enabled:
            return False
        descriptor = next(
            (
                item
                for item in catalog.provider_descriptors
                if item.provider == definition.provider
            ),
            None,
        )
        if descriptor is None:
            return False
        if descriptor.kind is not CapabilityProviderKind.MCP:
            return True
        mapping = self._registry.get_mcp_mapping(catalog, definition.capability_id)
        return bool(
            mapping is not None
            and mapping.enabled
            and mapping.capability_definition_digest == definition.definition_digest
        )

    async def _authorized(
        self,
        definition: CapabilityDefinition,
        catalog: CapabilityCatalogSnapshot,
        retrieval: CapabilityRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> bool:
        evidence: list[tuple[AuthorizationRequest, AuthorizationDecision]] = []
        for permission in sorted(definition.required_permissions):
            now = self._now()
            _validate_call(call, now)
            request = build_capability_authorization_request(
                definition,
                retrieval.actor,
                retrieval.conversation_scope,
                catalog,
                permission=permission,
                purpose=CapabilityAuthorizationPurpose.RETRIEVAL,
                policy_snapshot_id=call.policy_snapshot_id,
            )
            try:
                decision = await _bounded_decision(
                    self._authorization.decide(request, call=call),
                    call=call,
                    now=now,
                )
            except Exception:  # noqa: BLE001 - authorization failures deny silently.
                _validate_call(call, self._now())
                return False
            now = self._now()
            if not capability_authorization_allows(
                request,
                decision,
                self._verifier,
                at=now,
                expected_policy_revision=call.policy_snapshot_id,
            ):
                return False
            evidence.append((request, decision))
        final_at = self._now()
        _validate_call(call, final_at)
        return all(
            capability_authorization_allows(
                request,
                decision,
                self._verifier,
                at=final_at,
                expected_policy_revision=call.policy_snapshot_id,
            )
            for request, decision in evidence
        )

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - clock failures are sanitized.
            raise error(
                "capability_retrieval_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_capability_retrieval_clock")
        return value


def _healthy(
    definition: CapabilityDefinition,
    snapshot: CapabilityHealthSnapshot,
    *,
    now: datetime,
) -> CapabilityProviderHealth | None:
    if (
        not isinstance(snapshot, CapabilityHealthSnapshot)
        or snapshot.observed_at > now
        or snapshot.expires_at <= now
    ):
        return None
    provider = next(
        (item for item in snapshot.providers if item.provider == definition.provider),
        None,
    )
    if (
        provider is None
        or provider.status is not CapabilityHealthStatus.HEALTHY
        or provider.observed_at > now
        or provider.expires_at <= now
    ):
        return None
    endpoint = next(
        (
            item
            for item in provider.capabilities
            if item.capability_id == definition.capability_id
        ),
        None,
    )
    if (
        endpoint is None
        or endpoint.definition_digest != definition.definition_digest
        or endpoint.status is not CapabilityHealthStatus.HEALTHY
    ):
        return None
    return provider


def _candidate(
    definition: CapabilityDefinition,
    request: CapabilityRetrievalRequest,
) -> CapabilityCandidate:
    query_terms = _query_terms(request)
    definition_terms = _definition_terms(definition)
    overlap = len(query_terms & definition_terms)
    preferred = definition.category in request.query.preferred_categories
    exact_output = request.query.required_output_schema == definition.output_schema
    score = overlap * 1_000
    score += 500 if preferred else 0
    score += 250 if exact_output else 0
    score += max(0, 200 - definition.latency_hint.expected_ms // 10)
    score -= min(definition.cost_hint.units, 100_000)
    score -= _RISK_ORDER[definition.risk_level] * 100
    score = max(-1_000_000, min(1_000_000, score))
    reasons = ["eligible"]
    if overlap:
        reasons.append("lexical_overlap")
    if preferred:
        reasons.append("preferred_category")
    if exact_output:
        reasons.append("exact_output_schema")
    values = {
        "schema_version": 1,
        "capability_id": definition.capability_id,
        "definition_digest": definition.definition_digest,
        "name": definition.name,
        "description": definition.description,
        "category": definition.category,
        "provider": definition.provider,
        "input_schema": definition.input_schema,
        "output_schema": definition.output_schema,
        "risk_level": definition.risk_level,
        "privacy_level": definition.privacy_level,
        "cost_hint": definition.cost_hint,
        "latency_hint": definition.latency_hint,
        "idempotency": definition.idempotency,
        "side_effects": definition.side_effects,
        "rank_score": score,
        "reason_codes": tuple(reasons),
    }
    return CapabilityCandidate(
        candidate_digest=capability_candidate_digest(values),
        **values,
    )


def _query_terms(request: CapabilityRetrievalRequest) -> frozenset[str]:
    values = (
        *request.query.intent_ids,
        request.query.natural_language_goal,
        *request.query.entity_terms,
        *request.query.preferred_categories,
    )
    return _terms(values)


def _definition_terms(definition: CapabilityDefinition) -> frozenset[str]:
    values = (
        definition.capability_id,
        definition.name,
        definition.description,
        definition.category,
        definition.input_schema.schema_id,
        definition.output_schema.schema_id,
        *definition.tags,
    )
    return _terms(values)


def _terms(values: tuple[str, ...]) -> frozenset[str]:
    terms: set[str] = set()
    for value in values:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        for match in _TERM.findall(normalized):
            terms.add(match)
            if "\u3400" <= match[0] <= "\u9fff":
                terms.update(match)
                terms.update(
                    match[index : index + 2] for index in range(len(match) - 1)
                )
    return frozenset(terms)


def _apply_caps(
    candidates: list[CapabilityCandidate],
    *,
    limit: int,
    provider_cap: int,
    category_cap: int,
) -> tuple[CapabilityCandidate, ...]:
    selected: list[CapabilityCandidate] = []
    provider_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for candidate in candidates:
        provider_id = candidate.provider.provider_id
        if provider_counts.get(provider_id, 0) >= provider_cap:
            continue
        if category_counts.get(candidate.category, 0) >= category_cap:
            continue
        selected.append(candidate)
        provider_counts[provider_id] = provider_counts.get(provider_id, 0) + 1
        category_counts[candidate.category] = (
            category_counts.get(candidate.category, 0) + 1
        )
        if len(selected) >= limit:
            break
    return tuple(selected)


async def _bounded_decision(awaitable, *, call: PortCallContext, now: datetime):
    remaining = (call.deadline - now).total_seconds()
    if remaining <= 0:
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise error(
            "capability_authorization_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )
    operation = asyncio.create_task(awaitable)
    cancelled = asyncio.create_task(call.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (operation, cancelled),
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled in done:
            raise error(
                "capability_authorization_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if operation not in done:
            raise error(
                "capability_authorization_timeout",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )
        result = operation.result()
        if not isinstance(result, AuthorizationDecision):
            raise validation_error("invalid_capability_authorization_decision")
        return result
    finally:
        for task in (operation, cancelled):
            if not task.done():
                task.cancel()
        await asyncio.gather(operation, cancelled, return_exceptions=True)


def _validate_call(call: PortCallContext, now: datetime) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_capability_retrieval_call_context")
    if call.cancellation.is_cancelled:
        raise error(
            "capability_retrieval_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "capability_retrieval_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


__all__ = ["DeterministicCapabilityRetriever"]
