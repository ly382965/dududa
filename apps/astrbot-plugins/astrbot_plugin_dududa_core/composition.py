from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from dududa.adapters import InMemoryAttachmentRepository
from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.domain.delivery import DeliveryConstraints
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    PrivacyLevel,
    ResourceUsage,
    RiskLevel,
    RuntimeBudget,
)
from dududa.domain.task import TaskReasoningDepth
from dududa.errors import ErrorCategory, error
from dududa.models.admission import InMemoryModelAdmissionController
from dududa.models.contracts import (
    EndpointHealthStatus,
    EndpointLoadSnapshot,
    EndpointTrafficPolicy,
    LoadCounterScope,
    ModelCapabilities,
    ModelEndpointDescriptor,
    ModelEndpointHealth,
    ModelEndpointRef,
    ModelInputModality,
    ModelOperationalSnapshot,
    ModelOutputModality,
    ModelProcessingBoundary,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRetentionMode,
    ModelRole,
    ModelTier,
    ReasoningDepth,
    ReasoningProfile,
    StaleSnapshotPolicy,
    StructuredOutputSupport,
)
from dududa.models.digests import model_endpoint_descriptor_digest
from dududa.models.estimation import (
    ConservativeModelInvocationEstimator,
    ModelTokenPricing,
)
from dududa.models.health import BoundedModelHealthPublisher, ModelHealthEvidence
from dududa.models.policy import (
    ModelCapabilitiesRequirement,
    ModelFallbackPolicy,
    ModelRoutePolicy,
    TierBudgetRequirement,
    TierPolicyDefinition,
)
from dududa.models.registry import (
    InMemoryModelOperationalStateRegistry,
    InMemoryModelRoutingRegistry,
)
from dududa.models.router import StaticModelRouter
from dududa.models.tiering import DeterministicModelTierPolicy
from dududa.perception.complexity import (
    DeterministicComplexityAssessor,
    default_complexity_assessor_config,
)
from dududa.perception.contracts import (
    ClarificationKey,
    GroupInteractionMode,
    PerceptionLimits,
)
from dududa.perception.merge import (
    DeterministicPerceptionMerger,
    PerceptionMergeConfig,
)
from dududa.perception.rules import (
    DeterministicRulePerception,
    default_rule_perception_config,
)
from dududa.perception.social import (
    DeterministicSocialDecisionPolicy,
    SocialDecisionConfig,
)
from dududa.persona.assets import load_persona_directory
from dududa.persona.registry import InMemoryPersonaRegistry
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.ports.models import ModelOperationalStateRegistry
from dududa.ports.runtime import AgentRuntime, InputConnector
from dududa.responses import (
    DeterministicResponseProfilePolicy,
    DeterministicResponseProfileValidator,
    UnicodeVisibleTokenCounter,
    pilot_response_profile_policy_config,
)
from dududa.rollout import (
    BoundedShadowSupervisor,
    CanaryCoordinator,
    InMemoryRolloutMetrics,
    SQLiteRolloutLedger,
    SQLiteRolloutLedgerConfig,
)
from dududa.runtime.budget import RuntimeModelBudgetPlan
from dududa.runtime.composition import (
    DeterministicPersonaRenderer,
    DeterministicPersonaRendererConfig,
    DeterministicRenderValidator,
    FinalResponseSafetyValidator,
    MinimalResponseComposer,
    MinimalResponseComposerConfig,
)
from dududa.runtime.context import (
    CurrentMessageContextBuilder,
    CurrentMessageContextBuilderConfig,
)
from dududa.runtime.contracts import OfflineRuntimePolicySnapshot
from dududa.runtime.delivery import (
    DeliveryRequestBuilder,
    DeliveryRequestBuilderConfig,
)
from dududa.runtime.direct_chat import (
    DirectChatModelCall,
    DirectChatModelCallConfig,
)
from dududa.runtime.orchestrator import (
    OfflineRuntimeOrchestrator,
    OfflineRuntimeOrchestratorConfig,
)
from dududa.runtime.perception import RuleOnlyRuntimePerception
from dududa.runtime.shadow import ShadowRunner
from dududa.runtime.store import (
    InMemoryRuntimeStateStore,
    InMemoryRuntimeStateStoreConfig,
)
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.content_safety import DefaultContentSafetyPolicy

from .adapters.mcp_runtime import build_icourse_client
from .adapters.message import AstrBotInputConnector
from .adapters.model import (
    AstrBotModelProviderAdapter,
    AstrBotPromptArtifact,
    AstrBotProviderBindingEvidence,
    astrbot_prompt_artifact_digest,
)
from .adapters.model_codec import JsonSchemaDocumentRegistry
from .adapters.model_evidence import AstrBotProviderEvidenceStore
from .adapters.output import ASTRBOT_OUTPUT_REVISION, InMemoryDeliveryLedger
from .config import (
    MCP_REGISTRY_DIR,
    MCP_WORKER_PYTHON,
    PLUGIN_DATA_DIR,
    ROLLOUT_LEDGER_PATH,
    AstrBotRolloutControlProvider,
    ensure_dirs,
    load_json,
)
from .rollout_bridge import AstrBotRolloutBridge, AstrBotRuntimeRequestFactory

logger = logging.getLogger(__name__)


_TIER_ORDER = {
    ModelTier.HAIKU: 0,
    ModelTier.SONNET: 1,
    ModelTier.OPUS: 2,
}


@dataclass(frozen=True, slots=True)
class _RuntimeModelConfig:
    provider_id: str
    astrbot_provider_id: str
    endpoint_id: str
    model_id: str
    tier: ModelTier
    reasoning_depth: ReasoningDepth
    max_context_tokens: int
    max_output_tokens: int
    max_concurrency: int
    rpm_limit: int
    tpm_limit: int


class ProductionRuntimeAssembly:
    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        ready: bool,
        closeables: Iterable[object] = (),
        abort_callbacks: Iterable[Callable[[], None]] = (),
        model_operational_registry: ModelOperationalStateRegistry | None = None,
        model_health_publisher: BoundedModelHealthPublisher | None = None,
        model_endpoint_load: Iterable[EndpointLoadSnapshot] = (),
    ) -> None:
        if not isinstance(runtime, AgentRuntime):
            raise TypeError("runtime does not implement AgentRuntime")
        if type(ready) is not bool:
            raise TypeError("invalid production Runtime readiness")
        resources = tuple(closeables)
        if any(not callable(getattr(item, "close", None)) for item in resources):
            raise TypeError("production Runtime resource is not closeable")
        callbacks = tuple(abort_callbacks)
        if any(not callable(callback) for callback in callbacks):
            raise TypeError("invalid production Runtime abort callback")
        if model_operational_registry is not None and not isinstance(
            model_operational_registry,
            ModelOperationalStateRegistry,
        ):
            raise TypeError("invalid model operational registry")
        if model_health_publisher is not None and not isinstance(
            model_health_publisher,
            BoundedModelHealthPublisher,
        ):
            raise TypeError("invalid model health publisher")
        endpoint_load = tuple(model_endpoint_load)
        if any(not isinstance(item, EndpointLoadSnapshot) for item in endpoint_load):
            raise TypeError("invalid model endpoint load")
        self.runtime = runtime
        self.ready = ready
        self.model_operational_registry = model_operational_registry
        self.model_health_publisher = model_health_publisher
        self._model_endpoint_load = endpoint_load
        self._closeables = list(resources)
        self._abort_callbacks = list(callbacks)
        self._abort_started = False
        self._aborted = False
        self._closed = False
        self._installed = False

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def installable(self) -> bool:
        return not self._installed and not self._abort_started and not self._closed

    def mark_installed(self) -> None:
        if not self.installable:
            raise RuntimeError("production Runtime assembly is not installable")
        self._installed = True

    async def publish_model_health(
        self,
        evidence: Iterable[ModelHealthEvidence],
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ModelOperationalSnapshot:
        if self.model_health_publisher is None:
            raise RuntimeError("model health publisher is unavailable")
        return await self.model_health_publisher.publish(
            tuple(evidence),
            self._model_endpoint_load,
            call=call,
        )

    def abort(self) -> None:
        if self._aborted or self._closed:
            return
        self._abort_started = True
        first_error = self._run_abort_callbacks()
        if first_error is not None:
            raise first_error

    def _run_abort_callbacks(self) -> BaseException | None:
        first_error: BaseException | None = None
        failed: list[Callable[[], None]] = []
        for callback in reversed(self._abort_callbacks):
            try:
                callback()
            except BaseException as exc:  # cleanup continues before surfacing
                first_error = first_error or exc
                failed.append(callback)
        self._abort_callbacks = list(reversed(failed))
        self._aborted = not self._abort_callbacks
        return first_error

    async def close(self) -> None:
        if self._closed:
            return
        first_error: BaseException | None = None
        if self._abort_started and self._abort_callbacks:
            first_error = self._run_abort_callbacks()
        failed: list[object] = []
        for resource in reversed(self._closeables):
            try:
                result = resource.close()
                if inspect.isawaitable(result):
                    await result
            except BaseException as exc:  # cleanup continues before surfacing
                first_error = first_error or exc
                failed.append(resource)
        self._closeables = list(reversed(failed))
        self._closed = not self._closeables and (
            not self._abort_started or self._aborted
        )
        if first_error is not None:
            raise first_error


class _UnavailableAgentRuntime:
    async def run(self, request: object, *, call: object) -> object:
        raise _runtime_unavailable()

    async def acknowledge_delivery(self, receipt: object, *, call: object) -> object:
        raise _runtime_unavailable()

    async def reconcile_delivery(self, receipt: object, *, call: object) -> object:
        raise _runtime_unavailable()


def unavailable_runtime_assembly() -> ProductionRuntimeAssembly:
    return ProductionRuntimeAssembly(_UnavailableAgentRuntime(), ready=False)


def _revision(component_id: str) -> ComponentRevision:
    return ComponentRevision(
        component_id,
        "1.0.0",
        "production-shape-v1",
        DigestString(f"builtin:{component_id}"),
    )


def _required_text(
    item: dict[str, object],
    field: str,
    index: int,
) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"runtime model {index} has invalid {field}")
    return value.strip()


def _positive_integer(
    item: dict[str, object],
    field: str,
    index: int,
) -> int:
    value = item.get(field)
    if type(value) is not int or value <= 0:
        raise ValueError(f"runtime model {index} has invalid {field}")
    return value


def _parse_runtime_models(config: dict[str, object]) -> tuple[_RuntimeModelConfig, ...]:
    raw = config.get("runtime_models_json")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("runtime_models_json must be a non-empty JSON array")
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("runtime_models_json is invalid") from exc
    if not isinstance(values, list) or not values:
        raise ValueError("runtime_models_json must be a non-empty JSON array")

    result: list[_RuntimeModelConfig] = []
    provider_ids: set[str] = set()
    endpoint_ids: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ValueError(f"runtime model {index} must be an object")
        item = dict(value)
        provider_id = _required_text(item, "provider_id", index)
        endpoint_id = _required_text(item, "endpoint_id", index)
        tier_value = _required_text(item, "tier", index)
        try:
            tier = ModelTier(tier_value)
        except ValueError as exc:
            raise ValueError(f"runtime model {index} has invalid tier") from exc
        reasoning_value = item.get("reasoning_depth", ReasoningDepth.OFF.value)
        try:
            reasoning_depth = ReasoningDepth(reasoning_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"runtime model {index} has invalid reasoning_depth"
            ) from exc
        if provider_id in provider_ids:
            raise ValueError("runtime model provider_id must be unique")
        if endpoint_id in endpoint_ids:
            raise ValueError("runtime model endpoint_id must be unique")

        max_context_tokens = _positive_integer(
            item,
            "max_context_tokens",
            index,
        )
        max_output_tokens = _positive_integer(
            item,
            "max_output_tokens",
            index,
        )
        if max_output_tokens >= max_context_tokens:
            raise ValueError(
                f"runtime model {index} output limit must be below context limit"
            )
        result.append(
            _RuntimeModelConfig(
                provider_id=provider_id,
                astrbot_provider_id=_required_text(
                    item,
                    "astrbot_provider_id",
                    index,
                ),
                endpoint_id=endpoint_id,
                model_id=_required_text(item, "model_id", index),
                tier=tier,
                reasoning_depth=reasoning_depth,
                max_context_tokens=max_context_tokens,
                max_output_tokens=max_output_tokens,
                max_concurrency=_positive_integer(
                    item,
                    "max_concurrency",
                    index,
                ),
                rpm_limit=_positive_integer(item, "rpm_limit", index),
                tpm_limit=_positive_integer(item, "tpm_limit", index),
            )
        )
        provider_ids.add(provider_id)
        endpoint_ids.add(endpoint_id)
    return tuple(result)


def _direct_chat_prompt() -> AstrBotPromptArtifact:
    values = {
        "role": ModelRole.DIRECT_CHAT,
        "schema_repair": False,
        "system_prompt": "你是嘟嘟哒，请根据当前对话直接回答。",
        "structured_output_instruction": "返回普通文本回答。",
        "repair_instruction": None,
    }
    return AstrBotPromptArtifact(
        schema_version=1,
        **values,
        revision=ComponentRevision(
            "astrbot-direct-chat-prompt",
            "1.0.0",
            "production-v1",
            astrbot_prompt_artifact_digest(**values),
        ),
    )


def build_production_runtime(
    plugin: Any,
    config: dict[str, object],
    *,
    clock: Callable[[], datetime] | None = None,
) -> ProductionRuntimeAssembly:
    """Build the smallest config-driven inbound production Runtime."""

    specs = _parse_runtime_models(config)
    provider_context = getattr(plugin, "context", None)
    get_provider = getattr(provider_context, "get_provider_by_id", None)
    if not callable(get_provider):
        raise ValueError("AstrBot provider registry is unavailable")
    resolve_evidence = getattr(
        provider_context,
        "resolve_dududa_model_provider_evidence",
        None,
    )
    evidence_store: AstrBotProviderEvidenceStore | None = None
    evidence_store_path: Path | None = None
    evidence_path = config.get("runtime_provider_evidence_path")
    if isinstance(evidence_path, str) and evidence_path.strip():
        evidence_store_path = Path(evidence_path.strip()).expanduser()
    if not callable(resolve_evidence) and evidence_store_path is None:
        raise ValueError("AstrBot provider conformance evidence is unavailable")

    prompt = _direct_chat_prompt()
    adapters: list[AstrBotModelProviderAdapter] = []
    configured_endpoints: list[
        tuple[int, _RuntimeModelConfig, ModelEndpointDescriptor]
    ] = []
    provider_health: list[ModelProviderHealth] = []
    endpoint_load: list[EndpointLoadSnapshot] = []
    effective_clock = clock or (lambda: datetime.now(timezone.utc))
    now = effective_clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock returned a naive datetime")
    now = now.astimezone(timezone.utc)

    for index, spec in enumerate(specs):
        astrbot_provider = get_provider(spec.astrbot_provider_id)
        if astrbot_provider is None:
            raise ValueError("configured AstrBot provider is unavailable")
        traffic_policy = EndpointTrafficPolicy(
            schema_version=1,
            policy_id=f"{spec.endpoint_id}-traffic",
            policy_revision="production-v1",
            max_concurrency=spec.max_concurrency,
            rpm_limit=spec.rpm_limit,
            tpm_limit=spec.tpm_limit,
            max_queue_depth=0,
            max_p95_latency_ms=None,
            max_429_rate=1.0,
            max_error_rate=1.0,
            observation_window_seconds=60,
            minimum_samples=1,
            cooldown_seconds=0,
            max_snapshot_age_seconds=300,
            stale_snapshot_policy=StaleSnapshotPolicy.EXCLUDE,
        )
        reasoning_profile = ReasoningProfile(
            schema_version=1,
            profile_id="provider-default",
            depth=spec.reasoning_depth,
            max_reasoning_tokens=None,
            required=False,
        )
        endpoint = ModelEndpointDescriptor(
            schema_version=1,
            endpoint_id=spec.endpoint_id,
            model_id=spec.model_id,
            descriptor_digest=DigestString("pending"),
            tier=spec.tier,
            capabilities=ModelCapabilities(
                schema_version=1,
                input_modalities=frozenset({ModelInputModality.TEXT}),
                output_modalities=frozenset({ModelOutputModality.TEXT}),
                native_structured_output=StructuredOutputSupport.NONE,
                max_context_tokens=spec.max_context_tokens,
                max_input_tokens=(spec.max_context_tokens - spec.max_output_tokens),
                max_output_tokens=spec.max_output_tokens,
                supports_temperature=False,
                supports_streaming=False,
                supports_seed=False,
            ),
            reasoning_profiles=(reasoning_profile,),
            default_reasoning_profile_id=reasoning_profile.profile_id,
            allowed_data_classes=frozenset(
                {PrivacyLevel.PUBLIC, PrivacyLevel.CONVERSATION}
            ),
            processing_boundary=ModelProcessingBoundary.EXTERNAL,
            available_data_residencies=frozenset({"global"}),
            supported_retention_modes=frozenset({ModelRetentionMode.NO_RETENTION}),
            quota_pool_id=f"{spec.provider_id}:{spec.endpoint_id}",
            traffic_policy=traffic_policy,
            enabled=True,
        )
        endpoint = replace(
            endpoint,
            descriptor_digest=model_endpoint_descriptor_digest(endpoint),
        )
        descriptor = ModelProviderDescriptor(
            schema_version=1,
            provider_id=spec.provider_id,
            revision=_revision(f"model-provider:{spec.provider_id}"),
            endpoints=(endpoint,),
        )
        evidence = (
            resolve_evidence(spec.astrbot_provider_id, descriptor)
            if callable(resolve_evidence)
            else None
        )
        if evidence is None and evidence_store_path is not None:
            evidence_store = evidence_store or AstrBotProviderEvidenceStore(
                evidence_store_path
            )
            evidence = evidence_store.resolve(spec.astrbot_provider_id, descriptor)
        if not isinstance(evidence, AstrBotProviderBindingEvidence):
            raise ValueError("AstrBot provider conformance evidence is unavailable")
        adapter = AstrBotModelProviderAdapter(
            astrbot_provider,
            descriptor,
            evidence,
            schema_registry=JsonSchemaDocumentRegistry({}),
            prompt_artifacts=(prompt,),
            clock=effective_clock,
        )
        adapters.append(adapter)
        configured_endpoints.append((index, spec, endpoint))
        provider_health.append(
            ModelProviderHealth(
                schema_version=1,
                provider_id=spec.provider_id,
                status=EndpointHealthStatus.UNKNOWN,
                endpoints=(
                    ModelEndpointHealth(
                        schema_version=1,
                        endpoint_id=spec.endpoint_id,
                        endpoint_descriptor_digest=endpoint.descriptor_digest,
                        status=EndpointHealthStatus.UNKNOWN,
                        reason_codes=("preflight_health_not_observed",),
                    ),
                ),
                snapshot_revision="production-v1",
                checked_at=now,
                reason_codes=("preflight_health_not_observed",),
            )
        )
        endpoint_load.append(
            EndpointLoadSnapshot(
                schema_version=1,
                provider_id=spec.provider_id,
                endpoint_id=spec.endpoint_id,
                endpoint_descriptor_digest=endpoint.descriptor_digest,
                quota_pool_id=endpoint.quota_pool_id,
                traffic_policy_id=traffic_policy.policy_id,
                traffic_policy_revision=traffic_policy.policy_revision,
                counter_scope=LoadCounterScope.EXTERNAL_TO_ADMISSION_CONTROLLER,
                in_flight=0,
                requests_per_minute=0,
                tokens_per_minute=0,
                queue_depth=0,
                p95_latency_ms=None,
                rate_429=0.0,
                error_rate=0.0,
                sample_count=traffic_policy.minimum_samples,
                cooldown_until=None,
                checked_at=now,
                snapshot_revision="production-v1",
            )
        )

    tiers = frozenset(spec.tier for spec in specs)
    ordered_tiers = tuple(sorted(tiers, key=_TIER_ORDER.__getitem__))
    default_tier = ModelTier.SONNET if ModelTier.SONNET in tiers else ordered_tiers[0]
    ordered_candidates = sorted(
        configured_endpoints,
        key=lambda item: (_TIER_ORDER[item[1].tier], item[0]),
    )
    candidates = tuple(
        ModelEndpointRef(
            schema_version=1,
            provider_id=spec.provider_id,
            endpoint_id=spec.endpoint_id,
            model_id=spec.model_id,
            endpoint_descriptor_digest=endpoint.descriptor_digest,
            tier=spec.tier,
            priority=(position + 1) * 10,
        )
        for position, (_, spec, endpoint) in enumerate(ordered_candidates)
    )
    route_policy = ModelRoutePolicy(
        schema_version=1,
        policy_id="direct-chat-route",
        role=ModelRole.DIRECT_CHAT,
        default_tier=default_tier,
        allowed_tiers=tiers,
        candidate_endpoints=candidates,
        requirements=ModelCapabilitiesRequirement(
            schema_version=1,
            input_modalities=frozenset({ModelInputModality.TEXT}),
            output_modalities=frozenset({ModelOutputModality.TEXT}),
            minimum_native_structured_output=StructuredOutputSupport.NONE,
            requires_schema_validation=False,
            minimum_context_tokens=1,
            minimum_output_tokens=1,
            reasoning_profile_id="provider-default",
        ),
        allowed_data_classes=frozenset(
            {PrivacyLevel.PUBLIC, PrivacyLevel.CONVERSATION}
        ),
        fallback=ModelFallbackPolicy(
            schema_version=1,
            max_retries_per_endpoint=0,
            max_same_tier_failovers=0,
            max_tier_hops=0,
            max_total_attempts=1,
            max_schema_repairs=0,
            retryable_failure_kinds=frozenset(),
            deterministic_fallback_id="direct-chat-no-fallback",
        ),
        tier_fallback_edges=(),
        policy_revision="direct-chat-route-v1",
    )
    routing = InMemoryModelRoutingRegistry(
        adapters,
        (route_policy,),
        clock=effective_clock,
    )
    operational = InMemoryModelOperationalStateRegistry(
        routing,
        ModelOperationalSnapshot(
            schema_version=1,
            snapshot_id="production-initial",
            provider_health=tuple(provider_health),
            endpoint_load=tuple(endpoint_load),
            acquired_at=now,
        ),
        clock=effective_clock,
    )
    health_publisher = BoundedModelHealthPublisher(
        routing,
        operational,
        clock=effective_clock,
    )
    admission = InMemoryModelAdmissionController(
        routing,
        health_publisher,
        admission_revision="production-v1",
        clock=effective_clock,
    )
    endpoints = tuple(item[2] for item in configured_endpoints)
    estimator = ConservativeModelInvocationEstimator(
        revision=_revision("model-estimator"),
        role_prompt_tokens={ModelRole.DIRECT_CHAT: 256},
        provider_wrapping_tokens={
            endpoint.descriptor_digest: 64 for endpoint in endpoints
        },
        schema_tokens={},
        pricing={
            endpoint.descriptor_digest: ModelTokenPricing(
                schema_version=1,
                input_cost_per_million=Decimal("0"),
                generated_cost_per_million=Decimal("0"),
            )
            for endpoint in endpoints
        },
    )
    router = StaticModelRouter(
        routing,
        health_publisher,
        admission,
        estimator,
        output_codec=None,
        prompt_template_revisions={ModelRole.DIRECT_CHAT: prompt.revision},
        schema_repair_prompt_revisions={},
        clock=effective_clock,
    )

    complexity_config = default_complexity_assessor_config(
        _revision("complexity-assessor")
    )
    social_config = SocialDecisionConfig("social-v1", 0.6)
    tier_policy = TierPolicyDefinition(
        schema_version=1,
        policy_id="direct-chat-tier-policy",
        role=ModelRole.DIRECT_CHAT,
        allowed_tiers=tiers,
        default_tier=default_tier,
        low_complexity_tier=ordered_tiers[0],
        high_complexity_tier=ordered_tiers[-1],
        low_confidence_threshold=0.6,
        minimum_high_tier_confidence=0.85,
        minimum_high_complexity_signals=2,
        high_complexity_reason_codes=frozenset(
            {
                "deep_reasoning",
                "independent_verification",
                "multi_constraint_synthesis",
            }
        ),
        tier_budget_requirements=tuple(
            TierBudgetRequirement(
                schema_version=1,
                tier=tier,
                minimum_input_tokens_remaining=1,
                minimum_generated_tokens_remaining=1,
                minimum_cost_units_remaining=Decimal("0"),
            )
            for tier in ordered_tiers
        ),
        policy_revision="direct-chat-tier-v1",
    )
    runtime_policy = OfflineRuntimePolicySnapshot(
        schema_version=1,
        snapshot_id="production-shape-v1",
        authorization_policy_revision="authorization-v1",
        group_mode=GroupInteractionMode.NORMAL,
        complexity_assessor=complexity_config,
        social_decision=social_config,
        direct_chat_tier=tier_policy,
    )
    context_builder = CurrentMessageContextBuilder(
        CurrentMessageContextBuilderConfig(
            schema_version=1,
            limits=PerceptionLimits(
                schema_version=1,
                max_messages=4,
                max_identities=8,
                max_characters_per_message=2_000,
                max_total_characters=4_000,
                max_capability_categories=4,
                max_degraded_components=4,
                max_candidates_per_kind=8,
                max_evidence_refs_per_item=4,
            ),
            maximum_content_input_tokens=8_000,
            private_data_classification=PrivacyLevel.PERSONAL,
            group_data_classification=PrivacyLevel.CONVERSATION,
            component_revision=_revision("current-message-context"),
        )
    )
    rules = DeterministicRulePerception(
        default_rule_perception_config(_revision("rule-perception"))
    )
    merger = DeterministicPerceptionMerger(
        PerceptionMergeConfig(
            pipeline_revision=_revision("perception-pipeline"),
            merger_revision=_revision("perception-merger"),
            validator_revision=_revision("perception-validator"),
            fallback_confidence_ceiling=0.59,
            conflict_confidence_ceiling=0.55,
        )
    )
    perception = RuleOnlyRuntimePerception(rules, merger)

    direct_output_limit = min(
        1_536,
        *(endpoint.capabilities.max_output_tokens for endpoint in endpoints),
    )
    budget_plan = RuntimeModelBudgetPlan(
        schema_version=1,
        perception_reservation=ResourceUsage(
            schema_version=1,
            model_calls=1,
            tool_steps=0,
            retries=0,
            input_tokens=8_000,
            output_tokens=512,
            cost_units=Decimal("0"),
        ),
        direct_chat_reservation=ResourceUsage(
            schema_version=1,
            model_calls=1,
            tool_steps=0,
            retries=0,
            input_tokens=24_000,
            output_tokens=direct_output_limit,
            cost_units=Decimal("0"),
        ),
        revision=_revision("runtime-model-budget"),
    )
    direct_chat = DirectChatModelCall(
        router,
        DirectChatModelCallConfig(
            schema_version=1,
            # S08's RoutePolicy binds one profile id, so depth is fixed per Endpoint.
            reasoning_profiles={
                depth: "provider-default" for depth in TaskReasoningDepth
            },
            max_output_tokens=direct_output_limit,
            prompt_tokens_upper_bound=256,
            maximum_response_characters=6_000,
            allow_external_provider=True,
            allowed_residencies=frozenset({"global"}),
            allow_provider_retention=False,
            component_revision=_revision("direct-chat"),
        ),
        visible_token_counter=UnicodeVisibleTokenCounter(
            _revision("direct-chat-visible-counter")
        ),
    )
    composer = MinimalResponseComposer(
        MinimalResponseComposerConfig(
            schema_version=1,
            clarification_messages={
                ClarificationKey.TARGET: "请说明要回复谁。",
                ClarificationKey.REFERENCE: "请说明你指的是哪一项。",
                ClarificationKey.SCOPE: "请说明问题范围。",
                ClarificationKey.TASK: "请说明希望我完成什么任务。",
                ClarificationKey.TOOL_INPUT: "请补充执行所需的信息。",
            },
            component_revision=_revision("response-composer"),
        )
    )
    renderer = DeterministicPersonaRenderer(
        DeterministicPersonaRendererConfig(
            schema_version=1,
            persona_id="dududa",
            persona_version="1.0.0",
            component_revision=_revision("persona-renderer"),
        )
    )
    persona_registry = InMemoryPersonaRegistry(
        load_persona_directory(
            Path(__file__).resolve().parents[3] / "configs/personas/registry-v1"
        ),
        fallback_persona_id="neutral",
        fallback_version="1.0.0",
    )

    authorization_constraints = {
        "message.respond": AuthorizationConstraint(
            resource_types=frozenset({"conversation"}),
            resource_ids=frozenset({"*"}),
            maximum_risk=RiskLevel.LOW,
        ),
        "message.send": AuthorizationConstraint(
            resource_types=frozenset({"delivery"}),
            resource_ids=frozenset({"*"}),
            maximum_risk=RiskLevel.LOW,
        ),
    }
    authorization = RoleAuthorizationPolicy(
        AuthorizationPolicyConfig(
            policy_revision="authorization-v1",
            role_permissions={
                "normal_user": frozenset({"message.respond", "message.send"}),
                "admin": frozenset({"message.respond", "message.send"}),
            },
            role_constraints={
                "normal_user": authorization_constraints,
                "admin": authorization_constraints,
            },
            decision_ttl=timedelta(minutes=5),
        )
    )
    binding = NegotiatedBindingReceipt(
        schema_version=1,
        port_id="output-adapter",
        protocol_version="1.0.0",
        operation_schema_digests={
            "deliver": (DigestString("request"), DigestString("receipt"))
        },
        enabled_capability_flags=frozenset(),
        component_revision=ASTRBOT_OUTPUT_REVISION,
        negotiated_at=now,
    )
    delivery_builder = DeliveryRequestBuilder(
        DeliveryRequestBuilderConfig(
            schema_version=1,
            constraints=DeliveryConstraints(
                schema_version=1,
                max_parts=64,
                max_bytes_per_part=512,
                allow_forward_bundle=False,
                allowed_attachment_schemes=frozenset(),
                reconciliation_window=timedelta(minutes=10),
            ),
            adapter_binding=binding,
        ),
        authorization,
    )
    state_store = InMemoryRuntimeStateStore(
        InMemoryRuntimeStateStoreConfig(
            schema_version=1,
            checkpoint_ttl=timedelta(minutes=30),
            tombstone_ttl=timedelta(minutes=30),
            maximum_checkpoints=1_000,
            maximum_dedup_records=1_000,
            component_revision=_revision("runtime-state-store"),
        )
    )
    final_validator = FinalResponseSafetyValidator(
        DeterministicRenderValidator(_revision("render-validator")),
        DefaultContentSafetyPolicy(),
        profile_validator=DeterministicResponseProfileValidator(
            UnicodeVisibleTokenCounter(_revision("visible-token-counter")),
            _revision("response-profile-validator"),
        ),
    )
    runtime = OfflineRuntimeOrchestrator(
        OfflineRuntimeOrchestratorConfig(
            schema_version=1,
            persona_id="dududa",
            model_budget_plan=budget_plan,
            runtime_policy=runtime_policy,
            negotiated_bindings=(binding,),
            component_revision=_revision("offline-runtime"),
        ),
        store=state_store,
        context_builder=context_builder,
        authorization_policy=authorization,
        authorization_verifier=authorization,
        perception=perception,
        complexity=DeterministicComplexityAssessor(complexity_config),
        social=DeterministicSocialDecisionPolicy(social_config),
        tier_policy=DeterministicModelTierPolicy(),
        direct_chat=direct_chat,
        composer=composer,
        renderer=renderer,
        final_validator=final_validator,
        delivery_builder=delivery_builder,
        response_profile_policy=DeterministicResponseProfilePolicy(
            pilot_response_profile_policy_config(_revision("response-profile-policy"))
        ),
        detail_detector_revision=_revision("detail-detector"),
        persona_registry=persona_registry,
        capability_runtime=None,
    )
    return ProductionRuntimeAssembly(
        runtime,
        ready=True,
        closeables=adapters,
        model_operational_registry=health_publisher,
        model_health_publisher=health_publisher,
        model_endpoint_load=endpoint_load,
    )


def initialize_plugin(
    plugin: Any,
    config: dict | None = None,
    *,
    runtime_assembly: ProductionRuntimeAssembly | None = None,
) -> None:
    from .audit import AuditLog
    from .permissions import PermissionManager

    if getattr(plugin, "_dududa_runtime_initialized", False):
        raise RuntimeError("Dududa Runtime plugin is already initialized")
    plugin._dududa_runtime_initialized = True
    plugin.config = config or {}
    plugin.enabled = bool(plugin.config.get("enabled", True))
    ensure_dirs()
    plugin.perms = PermissionManager(plugin.config)
    plugin.audit = AuditLog()
    plugin.icourse, plugin.icourse_mode, icourse_reason = build_icourse_client(
        plugin.config,
        registry_directory=MCP_REGISTRY_DIR,
        worker_python=MCP_WORKER_PYTHON,
    )
    plugin.icourse_reason = icourse_reason
    if plugin.icourse_mode != "unified":
        logger.warning("Unified iCourse MCP unavailable: reason=%s", icourse_reason)
    plugin.pending = {}
    plugin.course_refresh_at = {}
    plugin.user_state_path = PLUGIN_DATA_DIR / "user_state.json"
    plugin.group_state_path = PLUGIN_DATA_DIR / "group_state.json"
    plugin.user_state = load_json(plugin.user_state_path, {})
    plugin.group_state = load_json(plugin.group_state_path, {})
    plugin.rollout_controls = AstrBotRolloutControlProvider(plugin.config)
    plugin.rollout_metrics = InMemoryRolloutMetrics()
    plugin.rollout_ledger = None
    plugin.rollout_bridge = None
    plugin.runtime_assembly = None
    plugin._dududa_runtime_cleanup_assemblies = []
    plugin._dududa_runtime_terminated = False
    try:
        plugin.rollout_ledger = SQLiteRolloutLedger(
            SQLiteRolloutLedgerConfig(
                schema_version=1,
                path=ROLLOUT_LEDGER_PATH,
                busy_timeout=timedelta(seconds=5),
                terminal_ttl=timedelta(days=30),
                maximum_records=100_000,
                component_revision=ComponentRevision(
                    "rollout-ledger.sqlite",
                    "1.0.0",
                    "s11-v1",
                    DigestString("builtin"),
                ),
            )
        )
        recovered = plugin.rollout_ledger.recover_incomplete()
        if recovered:
            logger.warning(
                "Dududa rollout recovered %d incomplete ownership records",
                len(recovered),
            )
    except Exception:  # noqa: BLE001 - unavailable persistence keeps rollout disabled
        logger.error("Dududa rollout persistence unavailable; rollout remains disabled")
    if runtime_assembly is not None:
        assembly = runtime_assembly
    elif plugin.config.get("runtime_enabled") is True:
        try:
            assembly = build_production_runtime(plugin, plugin.config)
        except Exception:  # unavailable composition preserves the legacy owner
            logger.warning(
                "Dududa production Runtime unavailable: "
                "reason=runtime_composition_failed"
            )
            assembly = unavailable_runtime_assembly()
    else:
        assembly = unavailable_runtime_assembly()
    install_production_runtime(
        plugin,
        assembly,
        _default_runtime_budget(),
        "production-shape-v1",
    )
    logger.info("DududaCore loaded: enabled=%s", plugin.enabled)


def install_production_runtime(
    plugin: Any,
    assembly: ProductionRuntimeAssembly,
    runtime_budget: RuntimeBudget,
    policy_snapshot_id: str,
    *,
    connector: InputConnector[object] | None = None,
    clock: Any = None,
) -> AstrBotRolloutBridge | None:
    if not isinstance(assembly, ProductionRuntimeAssembly):
        raise TypeError("invalid production Runtime assembly")
    existing = getattr(plugin, "rollout_bridge", None)
    if existing is not None:
        if getattr(plugin, "runtime_assembly", None) is assembly:
            return existing
        if not assembly.installable:
            raise RuntimeError("production Runtime assembly is not installable")
        try:
            assembly.abort()
        except Exception:
            logger.error("Duplicate Dududa Runtime assembly abort failed")
        _retain_cleanup_assembly(plugin, assembly)
        return existing
    if not assembly.installable or any(
        item is assembly
        for item in getattr(plugin, "_dududa_runtime_cleanup_assemblies", ())
    ):
        raise RuntimeError("production Runtime assembly is not installable")
    try:
        bridge = install_rollout_runtime(
            plugin,
            assembly.runtime,
            runtime_budget,
            policy_snapshot_id,
            connector=connector,
            clock=clock,
            runtime_ready=assembly.ready,
        )
    except Exception:  # unavailable composition preserves the legacy owner
        try:
            assembly.abort()
        except Exception:
            logger.error("Dududa Runtime assembly abort failed")
        plugin.rollout_bridge = None
        plugin.runtime_assembly = None
        _retain_cleanup_assembly(plugin, assembly)
        logger.error("Dududa Runtime composition unavailable; legacy remains owner")
        return None
    assembly.mark_installed()
    plugin.runtime_assembly = assembly
    return bridge


def install_rollout_runtime(
    plugin: Any,
    runtime: AgentRuntime,
    runtime_budget: RuntimeBudget,
    policy_snapshot_id: str,
    *,
    connector: InputConnector[object] | None = None,
    clock: Any = None,
    runtime_ready: bool = True,
) -> AstrBotRolloutBridge:
    if getattr(plugin, "rollout_bridge", None) is not None:
        raise RuntimeError("rollout Runtime is already installed")
    ledger = getattr(plugin, "rollout_ledger", None)
    controls = getattr(plugin, "rollout_controls", None)
    metrics = getattr(plugin, "rollout_metrics", None)
    if not isinstance(ledger, SQLiteRolloutLedger):
        raise RuntimeError("rollout persistence is unavailable")
    if not isinstance(metrics, InMemoryRolloutMetrics):
        raise RuntimeError("rollout metrics are unavailable")
    config = controls.current()
    connector = connector or AstrBotInputConnector(
        InMemoryAttachmentRepository(clock=clock),
        clock=clock,
    )
    requests = AstrBotRuntimeRequestFactory(
        connector,
        runtime_budget,
        policy_snapshot_id,
        response_profiles_enabled=bool(
            getattr(plugin, "config", {}).get(
                "runtime_response_profiles_enabled",
                True,
            )
        ),
        clock=clock,
    )
    shadow = BoundedShadowSupervisor(
        ShadowRunner(runtime, _NoopShadowSink(), clock=clock),
        config,
        metrics,
        clock=clock,
    )
    canary = CanaryCoordinator(
        runtime,
        controls,
        ledger,
        metrics,
        clock=clock,
    )
    bridge = AstrBotRolloutBridge(
        controls,
        requests,
        shadow,
        canary,
        InMemoryDeliveryLedger(),
        runtime_ready=runtime_ready,
    )
    plugin.rollout_bridge = bridge
    return bridge


class _NoopShadowSink:
    async def write(self, receipt: object, *, call: object) -> None:
        return None


def _default_runtime_budget() -> RuntimeBudget:
    return RuntimeBudget(
        model_calls_remaining=2,
        tool_steps_remaining=0,
        retries_remaining=1,
        input_tokens_remaining=32_000,
        output_tokens_remaining=8_000,
        cost_units_remaining=Decimal("0"),
    )


def _retain_cleanup_assembly(
    plugin: Any,
    assembly: ProductionRuntimeAssembly,
) -> None:
    pending = list(getattr(plugin, "_dududa_runtime_cleanup_assemblies", ()))
    if not any(item is assembly for item in pending):
        pending.append(assembly)
    plugin._dududa_runtime_cleanup_assemblies = pending


def _runtime_unavailable():
    return error(
        "production_runtime_unavailable",
        ErrorCategory.EXTERNAL,
        "runtime.unavailable",
        "missing_conformance_evidence",
    )
