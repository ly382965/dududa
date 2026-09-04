from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.errors import DududaError, ErrorInfo, validation_error
from dududa.models.contracts import (
    EndpointHealthStatus,
    ModelEndpointHealth,
    ModelFailureKind,
    ModelInputModality,
    ModelOutputModality,
    ModelProcessingBoundary,
    ModelProcessingReceipt,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRetentionMode,
    ModelRole,
    ModelUsage,
    ProviderRequest,
    ProviderResponse,
    ReasoningDepth,
    RouteAttemptKind,
    StructuredOutputSupport,
)
from dududa.models.digests import provider_request_digest
from dududa.models.errors import ModelProviderError, model_error_info
from dududa.models.health import ModelHealthEvidence
from dududa.ports.context import PortCallContext, ServiceCallContext

from .model_codec import JsonSchemaDocumentRegistry

_ATTRIBUTE_READ_FAILED = object()

_REASONING_EFFORT_BY_DEPTH = {
    ReasoningDepth.OFF: None,
    ReasoningDepth.LIGHT: "low",
    ReasoningDepth.BALANCED: "medium",
    ReasoningDepth.DEEP: "high",
    ReasoningDepth.MAXIMUM: "xhigh",
}


def reasoning_effort_for_model(model_id: str, depth: ReasoningDepth) -> str | None:
    effort = _REASONING_EFFORT_BY_DEPTH[depth]
    if model_id.startswith("deepseek-v4-"):
        return {"medium": "high", "xhigh": "max"}.get(effort, effort)
    return effort


@dataclass(frozen=True, slots=True)
class _IdempotencyFailure:
    failure_kind: ModelFailureKind
    info: ErrorInfo


@dataclass(frozen=True, slots=True)
class _IdempotencyEntry:
    request_digest: DigestString
    result: ProviderResponse | _IdempotencyFailure
    expires_at: datetime


def astrbot_prompt_artifact_digest(
    *,
    role: ModelRole,
    schema_repair: bool,
    system_prompt: str,
    structured_output_instruction: str,
    repair_instruction: str | None,
) -> DigestString:
    return canonical_digest(
        {
            "role": role.value,
            "schema_repair": schema_repair,
            "system_prompt": system_prompt,
            "structured_output_instruction": structured_output_instruction,
            "repair_instruction": repair_instruction,
        },
        domain="astrbot:prompt-artifact:v1",
    )


@dataclass(frozen=True, slots=True)
class AstrBotPromptArtifact:
    schema_version: int
    role: ModelRole
    schema_repair: bool
    system_prompt: str
    structured_output_instruction: str
    repair_instruction: str | None
    revision: ComponentRevision

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.role, ModelRole):
            raise validation_error("invalid_astrbot_prompt_role")
        if type(self.schema_repair) is not bool:
            raise validation_error("invalid_astrbot_prompt_repair_flag")
        if not isinstance(self.revision, ComponentRevision):
            raise validation_error("invalid_astrbot_prompt_revision")
        for field_name in ("system_prompt", "structured_output_instruction"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise validation_error("empty_astrbot_prompt_artifact", field_name)
        if self.schema_repair:
            if (
                not isinstance(self.repair_instruction, str)
                or not self.repair_instruction.strip()
            ):
                raise validation_error("repair_prompt_instruction_missing")
        elif self.repair_instruction is not None:
            raise validation_error("primary_prompt_has_repair_instruction")
        expected = astrbot_prompt_artifact_digest(
            role=self.role,
            schema_repair=self.schema_repair,
            system_prompt=self.system_prompt,
            structured_output_instruction=self.structured_output_instruction,
            repair_instruction=self.repair_instruction,
        )
        if self.revision.artifact_digest != expected:
            raise validation_error("astrbot_prompt_artifact_digest_mismatch")


@dataclass(frozen=True, slots=True)
class AstrBotProviderBindingEvidence:
    schema_version: int
    astrbot_provider_id: str
    host_version: str
    conformance_revision: ComponentRevision
    verified_model_id: str
    verified_max_output_tokens: int
    verified_data_residencies: frozenset[str]
    verified_retention_modes: frozenset[ModelRetentionMode]
    single_request_verified: bool
    model_binding_verified: bool
    output_limit_verified: bool
    residency_verified: bool
    retention_verified: bool
    sanitized_logging_verified: bool
    deadline_enforcement_verified: bool
    cancellation_enforcement_verified: bool

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        for field_name in (
            "astrbot_provider_id",
            "host_version",
            "verified_model_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise validation_error("empty_astrbot_binding_evidence", field_name)
        if not isinstance(self.conformance_revision, ComponentRevision):
            raise validation_error("invalid_astrbot_conformance_revision")
        if (
            type(self.verified_max_output_tokens) is not int
            or self.verified_max_output_tokens <= 0
        ):
            raise validation_error("invalid_astrbot_verified_output_limit")
        residencies = frozenset(self.verified_data_residencies)
        if not residencies or any(
            not isinstance(value, str) or not value.strip() for value in residencies
        ):
            raise validation_error("invalid_astrbot_verified_residencies")
        retention_modes = frozenset(self.verified_retention_modes)
        if not retention_modes or not all(
            isinstance(value, ModelRetentionMode) for value in retention_modes
        ):
            raise validation_error("invalid_astrbot_verified_retention_modes")
        object.__setattr__(self, "verified_data_residencies", residencies)
        object.__setattr__(self, "verified_retention_modes", retention_modes)
        for field_name in (
            "single_request_verified",
            "model_binding_verified",
            "output_limit_verified",
            "residency_verified",
            "retention_verified",
            "sanitized_logging_verified",
            "deadline_enforcement_verified",
            "cancellation_enforcement_verified",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise validation_error("invalid_astrbot_evidence_flag", field_name)

    @property
    def permits_enablement(self) -> bool:
        return all(
            (
                self.single_request_verified,
                self.model_binding_verified,
                self.output_limit_verified,
                self.residency_verified,
                self.retention_verified,
                self.sanitized_logging_verified,
                self.deadline_enforcement_verified,
                self.cancellation_enforcement_verified,
            )
        )


class AstrBotModelProviderAdapter:
    """Conservative bridge to a conformance-proven AstrBot Chat Provider."""

    def __init__(
        self,
        provider: object,
        descriptor: ModelProviderDescriptor,
        evidence: AstrBotProviderBindingEvidence,
        *,
        schema_registry: JsonSchemaDocumentRegistry,
        prompt_artifacts: Iterable[AstrBotPromptArtifact],
        clock: Callable[[], datetime] | None = None,
        idempotency_capacity: int = 1_024,
        idempotency_ttl_seconds: int = 600,
    ) -> None:
        if not isinstance(descriptor, ModelProviderDescriptor):
            raise ValueError("descriptor must be ModelProviderDescriptor")
        if not isinstance(evidence, AstrBotProviderBindingEvidence):
            raise ValueError("evidence must be AstrBotProviderBindingEvidence")
        if not evidence.permits_enablement:
            raise validation_error("astrbot_provider_binding_unverified")
        if not isinstance(schema_registry, JsonSchemaDocumentRegistry):
            raise ValueError("schema_registry must be JsonSchemaDocumentRegistry")
        if type(idempotency_capacity) is not int or idempotency_capacity <= 0:
            raise ValueError("idempotency_capacity must be positive")
        if type(idempotency_ttl_seconds) is not int or idempotency_ttl_seconds <= 0:
            raise ValueError("idempotency_ttl_seconds must be positive")
        _validate_descriptor(descriptor, evidence)
        actual_provider_id = _astrbot_provider_id(provider)
        if actual_provider_id != evidence.astrbot_provider_id:
            raise validation_error("astrbot_provider_identity_mismatch")
        artifacts = tuple(prompt_artifacts)
        if not artifacts or not all(
            isinstance(artifact, AstrBotPromptArtifact) for artifact in artifacts
        ):
            raise ValueError("invalid AstrBot prompt artifacts")
        prompts: dict[ComponentRevision, AstrBotPromptArtifact] = {}
        for artifact in artifacts:
            if artifact.revision in prompts:
                raise ValueError("duplicate AstrBot prompt revision")
            prompts[artifact.revision] = artifact
        self._provider = provider
        self._descriptor = descriptor
        self._evidence = evidence
        self._schema_registry = schema_registry
        self._prompt_artifacts = MappingProxyType(prompts)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._idempotency_capacity = idempotency_capacity
        self._idempotency_ttl = timedelta(seconds=idempotency_ttl_seconds)
        self._idempotency_results: OrderedDict[str, _IdempotencyEntry] = OrderedDict()
        self._idempotency_locks = tuple(asyncio.Lock() for _ in range(64))

    @property
    def descriptor(self) -> ModelProviderDescriptor:
        return self._descriptor

    @property
    def evidence(self) -> AstrBotProviderBindingEvidence:
        return self._evidence

    async def generate(
        self,
        request: ProviderRequest,
        *,
        call: PortCallContext,
    ) -> ProviderResponse:
        endpoint = _validate_request(self._descriptor, request)
        _validate_call(call, self._now())
        request_digest = provider_request_digest(request)
        if request.idempotency_key is None:
            return await self._generate_once(
                request,
                request_digest,
                endpoint,
                call,
            )
        lock = self._idempotency_lock(request.idempotency_key)
        async with lock:
            now = self._now()
            self._prune_idempotency(now)
            existing = self._idempotency_results.get(request.idempotency_key)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise _failure(
                        ModelFailureKind.INVALID_REQUEST,
                        "astrbot_idempotency_conflict",
                    )
                self._idempotency_results.move_to_end(request.idempotency_key)
                if isinstance(existing.result, _IdempotencyFailure):
                    raise ModelProviderError(
                        existing.result.failure_kind,
                        existing.result.info,
                    )
                return existing.result
            unknown_failure = None
            try:
                response = await self._generate_once(
                    request,
                    request_digest,
                    endpoint,
                    call,
                )
            except ModelProviderError as exc:
                if not exc.info.outcome_unknown:
                    raise
                unknown_failure = _IdempotencyFailure(exc.failure_kind, exc.info)
            result = response if unknown_failure is None else unknown_failure
            self._store_idempotency(
                request.idempotency_key,
                _IdempotencyEntry(
                    request_digest=request_digest,
                    result=result,
                    expires_at=now + self._idempotency_ttl,
                ),
            )
            if unknown_failure is not None:
                raise ModelProviderError(
                    unknown_failure.failure_kind,
                    unknown_failure.info,
                )
            return response

    async def health(
        self,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ModelProviderHealth:
        _validate_call(call, self._now())
        endpoint = self._descriptor.endpoints[0]
        return ModelProviderHealth(
            schema_version=1,
            provider_id=self._descriptor.provider_id,
            status=EndpointHealthStatus.UNKNOWN,
            endpoints=(
                ModelEndpointHealth(
                    schema_version=1,
                    endpoint_id=endpoint.endpoint_id,
                    endpoint_descriptor_digest=endpoint.descriptor_digest,
                    status=EndpointHealthStatus.UNKNOWN,
                    reason_codes=("no_reliable_astrbot_health_probe",),
                ),
            ),
            snapshot_revision="astrbot-passive-health-v1",
            checked_at=self._now(),
            reason_codes=("no_reliable_astrbot_health_probe",),
        )

    async def probe_health(
        self,
        *,
        timeout_seconds: float,
        evidence_ttl: timedelta,
    ) -> ModelHealthEvidence:
        """Run one bounded, content-free probe against the bound model."""

        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")
        if not isinstance(evidence_ttl, timedelta) or evidence_ttl <= timedelta(0):
            raise ValueError("evidence_ttl must be positive")

        endpoint = self._descriptor.endpoints[0]
        status = EndpointHealthStatus.UNKNOWN
        reason_codes = ("astrbot_active_health_probe_failed",)
        task: asyncio.Task[object] | None = None
        try:
            text_chat = getattr(self._provider, "text_chat", None)
            if not callable(text_chat):
                raise TypeError("AstrBot Provider has no text_chat")
            task = asyncio.create_task(
                text_chat(
                    prompt="Reply with OK.",
                    system_prompt="Health check. Return only OK.",
                    model=endpoint.model_id,
                    max_tokens=256 if endpoint.model_id.startswith("deepseek-v4-") else 8,
                    request_max_retries=1,
                    **({"thinking": {"type": "disabled"}} if endpoint.model_id.startswith("deepseek-v4-") else {}),
                )
            )
            done, _ = await asyncio.wait((task,), timeout=float(timeout_seconds))
            if task not in done:
                if await _cancel_task(task):
                    raise asyncio.CancelledError
            else:
                response = task.result()
                completion = _safe_getattr(response, "completion_text")
                if isinstance(completion, str) and completion.strip():
                    status = EndpointHealthStatus.HEALTHY
                    reason_codes = ()
        except asyncio.CancelledError:
            if task is not None:
                await _cancel_task(task)
            raise
        except Exception:  # noqa: BLE001 - failures become sanitized UNKNOWN evidence
            if task is not None and await _cancel_task(task):
                raise asyncio.CancelledError

        checked_at = self._now()
        health = ModelProviderHealth(
            schema_version=1,
            provider_id=self._descriptor.provider_id,
            status=status,
            endpoints=(
                ModelEndpointHealth(
                    schema_version=1,
                    endpoint_id=endpoint.endpoint_id,
                    endpoint_descriptor_digest=endpoint.descriptor_digest,
                    status=status,
                    reason_codes=reason_codes,
                ),
            ),
            snapshot_revision="astrbot-active-health-v1",
            checked_at=checked_at,
            reason_codes=reason_codes,
        )
        return ModelHealthEvidence(
            schema_version=1,
            provider_revision=self._descriptor.revision,
            health=health,
            expires_at=checked_at + evidence_ttl,
            evidence_revision="astrbot-active-health-v1",
        )

    async def close(self) -> None:
        # AstrBot owns the Provider lifecycle.
        self._idempotency_results.clear()
        return None

    async def _generate_once(
        self,
        request: ProviderRequest,
        request_digest,
        endpoint,
        call: PortCallContext,
    ) -> ProviderResponse:
        artifact = self._prompt_artifact(request)
        prompt = self._render_prompt(request, artifact)
        startup_error = None
        try:
            text_chat = getattr(self._provider, "text_chat", None)
        except asyncio.CancelledError:
            text_chat = None
            startup_error = _failure(
                ModelFailureKind.CANCELLED,
                "astrbot_text_chat_lookup_cancelled",
            )
        except BaseException:
            text_chat = None
            startup_error = _failure(
                ModelFailureKind.INTERNAL,
                "astrbot_text_chat_lookup_failed",
            )
        if startup_error is not None:
            raise startup_error
        if not callable(text_chat):
            raise _failure(
                ModelFailureKind.CAPABILITY_MISMATCH,
                "astrbot_text_chat_missing",
            )
        try:
            provider_kwargs: dict[str, object] = {
                "prompt": prompt,
                "system_prompt": artifact.system_prompt,
                "model": request.model_id,
                "max_tokens": request.max_output_tokens,
                "request_max_retries": 1,
            }
            reasoning_effort = reasoning_effort_for_model(request.model_id, request.reasoning_profile.depth)
            if request.model_id.startswith("deepseek-v4-"):
                provider_kwargs["thinking"] = {"type": "disabled" if reasoning_effort is None else "enabled"}
            if reasoning_effort is not None:
                provider_kwargs["reasoning_effort"] = reasoning_effort
            provider_awaitable = text_chat(
                **provider_kwargs,
            )
            task = asyncio.create_task(provider_awaitable)
        except asyncio.CancelledError:
            startup_error = _failure(
                ModelFailureKind.CANCELLED,
                "astrbot_text_chat_start_cancelled",
                outcome_unknown=True,
            )
        except BaseException:
            startup_error = _failure(
                ModelFailureKind.INTERNAL,
                "astrbot_text_chat_start_failed",
                outcome_unknown=True,
            )
        if startup_error is not None:
            raise startup_error
        watcher_start_error = None
        try:
            cancellation_task = asyncio.create_task(call.cancellation.wait())
        except asyncio.CancelledError:
            await _cancel_task(task)
            watcher_start_error = _failure(
                ModelFailureKind.CANCELLED,
                "astrbot_cancellation_watch_start_cancelled",
                outcome_unknown=True,
            )
        except BaseException:
            await _cancel_task(task)
            watcher_start_error = _failure(
                ModelFailureKind.INTERNAL,
                "astrbot_cancellation_watch_start_failed",
                outcome_unknown=True,
            )
        if watcher_start_error is not None:
            raise watcher_start_error
        remaining = max(0.0, (call.deadline - self._now()).total_seconds())
        provider_error = None
        raw_response = None
        try:
            done, _ = await asyncio.wait(
                (task, cancellation_task),
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_task in done:
                watcher_failed = False
                try:
                    cancellation_task.result()
                except BaseException:
                    watcher_failed = True
                await _cancel_task(task)
                provider_error = (
                    _failure(
                        ModelFailureKind.INTERNAL,
                        "astrbot_cancellation_watch_failed",
                        outcome_unknown=True,
                    )
                    if watcher_failed
                    else _failure(
                        ModelFailureKind.CANCELLED,
                        "astrbot_call_cancelled",
                        outcome_unknown=True,
                    )
                )
            elif task not in done:
                await _cancel_task(task)
                provider_error = _failure(
                    ModelFailureKind.TIMEOUT,
                    "astrbot_call_deadline_exceeded",
                    outcome_unknown=True,
                )
            else:
                try:
                    raw_response = task.result()
                except asyncio.CancelledError:
                    provider_error = _failure(
                        ModelFailureKind.CANCELLED,
                        "astrbot_provider_cancelled",
                        outcome_unknown=True,
                    )
                except ModelProviderError as exc:
                    provider_error = exc
                except Exception as exc:
                    provider_error = _classify_exception(exc)
        except asyncio.CancelledError:
            await _cancel_task(task)
            provider_error = _failure(
                ModelFailureKind.CANCELLED,
                "astrbot_adapter_task_cancelled",
                outcome_unknown=True,
            )
        finally:
            cancelled_during_cleanup = await _cancel_task(cancellation_task)
            if cancelled_during_cleanup and provider_error is None:
                provider_error = _failure(
                    ModelFailureKind.CANCELLED,
                    "astrbot_adapter_task_cancelled",
                    outcome_unknown=True,
                )
        if provider_error is not None:
            raise provider_error

        mapped_response = None
        mapping_error = None
        try:
            completion = _safe_getattr(raw_response, "completion_text")
            if not isinstance(completion, str) or not completion.strip():
                raise _failure(
                    ModelFailureKind.OUTPUT_INVALID,
                    "astrbot_completion_missing",
                )
            usage = _map_usage(_safe_getattr(raw_response, "usage"))
            processing = ModelProcessingReceipt(
                schema_version=1,
                provider_id=request.provider_id,
                provider_revision=request.provider_revision,
                endpoint_id=request.endpoint_id,
                endpoint_descriptor_digest=request.endpoint_descriptor_digest,
                model_id=request.model_id,
                provider_request_digest=request_digest,
                processing_boundary=endpoint.processing_boundary,
                data_residency=request.selected_data_residency,
                retention_mode=request.required_retention_mode,
                requested_reasoning_profile_id=request.reasoning_profile.profile_id,
                effective_reasoning_profile_id=request.reasoning_profile.profile_id,
                requested_seed=None,
                effective_seed=None,
            )
            mapped_response = ProviderResponse(
                schema_version=1,
                request_id=request.request_id,
                provider_id=request.provider_id,
                endpoint_id=request.endpoint_id,
                model_id=request.model_id,
                provider_revision=request.provider_revision,
                output=completion,
                finish_reason="unknown",
                usage=usage,
                safety_annotations=(),
                processing=processing,
            )
        except ModelProviderError as exc:
            mapping_error = exc
        except Exception:
            mapping_error = _failure(
                ModelFailureKind.INTERNAL,
                "astrbot_response_mapping_failed",
            )
        if mapping_error is not None:
            raise mapping_error
        if mapped_response is None:
            raise _failure(
                ModelFailureKind.OUTPUT_INVALID,
                "astrbot_response_mapping_missing",
            )
        return mapped_response

    def _prompt_artifact(self, request: ProviderRequest) -> AstrBotPromptArtifact:
        artifact = self._prompt_artifacts.get(request.prompt_template_revision)
        if artifact is None:
            raise _failure(
                ModelFailureKind.INVALID_REQUEST,
                "astrbot_prompt_revision_unknown",
            )
        is_repair = request.attempt_kind is RouteAttemptKind.SCHEMA_REPAIR
        if artifact.role is not request.role or artifact.schema_repair is not is_repair:
            raise _failure(
                ModelFailureKind.INVALID_REQUEST,
                "astrbot_prompt_binding_mismatch",
            )
        return artifact

    def _render_prompt(
        self,
        request: ProviderRequest,
        artifact: AstrBotPromptArtifact,
    ) -> str:
        text_parts = tuple(
            part.text
            for part in request.input.parts
            if part.modality is ModelInputModality.TEXT and part.text is not None
        )
        if not text_parts or len(text_parts) != len(request.input.parts):
            raise _failure(
                ModelFailureKind.CAPABILITY_MISMATCH,
                "astrbot_requires_one_text_part",
            )
        sections = [
            "[DUDUDA_USER_INPUT]",
            "\n\n".join(text_parts),
            "[/DUDUDA_USER_INPUT]",
        ]
        if request.output_schema is not None:
            try:
                schema = self._schema_registry.document(request.output_schema)
            except DududaError:
                raise _failure(
                    ModelFailureKind.INVALID_REQUEST,
                    "astrbot_output_schema_unavailable",
                ) from None
            sections.extend(
                (
                    artifact.structured_output_instruction,
                    json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
                )
            )
        if request.attempt_kind is RouteAttemptKind.SCHEMA_REPAIR:
            if request.output_schema is None or artifact.repair_instruction is None:
                raise _failure(
                    ModelFailureKind.INVALID_REQUEST,
                    "astrbot_schema_repair_without_schema",
                )
            sections.append(artifact.repair_instruction)
        return "\n".join(sections)

    def _idempotency_lock(self, key: str) -> asyncio.Lock:
        return self._idempotency_locks[hash(key) % len(self._idempotency_locks)]

    def _prune_idempotency(self, now: datetime) -> None:
        for key, entry in tuple(self._idempotency_results.items()):
            if entry.expires_at <= now:
                self._idempotency_results.pop(key, None)

    def _store_idempotency(self, key: str, entry: _IdempotencyEntry) -> None:
        self._idempotency_results[key] = entry
        self._idempotency_results.move_to_end(key)
        while len(self._idempotency_results) > self._idempotency_capacity:
            self._idempotency_results.popitem(last=False)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock returned a naive datetime")
        return value


def _validate_descriptor(
    descriptor: ModelProviderDescriptor,
    evidence: AstrBotProviderBindingEvidence,
) -> None:
    if len(descriptor.endpoints) != 1:
        raise validation_error("astrbot_adapter_requires_one_endpoint")
    endpoint = descriptor.endpoints[0]
    capabilities = endpoint.capabilities
    if not endpoint.enabled:
        raise validation_error("astrbot_adapter_endpoint_disabled")
    if endpoint.processing_boundary is not ModelProcessingBoundary.EXTERNAL:
        raise validation_error("astrbot_adapter_processing_boundary_mismatch")
    if (
        endpoint.model_id != evidence.verified_model_id
        or capabilities.max_output_tokens > evidence.verified_max_output_tokens
        or endpoint.available_data_residencies != evidence.verified_data_residencies
        or endpoint.supported_retention_modes != evidence.verified_retention_modes
    ):
        raise validation_error("astrbot_binding_evidence_mismatch")
    if (
        capabilities.input_modalities != frozenset({ModelInputModality.TEXT})
        or capabilities.output_modalities != frozenset({ModelOutputModality.TEXT})
        or capabilities.native_structured_output is not StructuredOutputSupport.NONE
        or capabilities.supports_temperature
        or capabilities.supports_streaming
        or capabilities.supports_seed
    ):
        raise validation_error("astrbot_adapter_capability_overclaim")
    if any(
        profile.depth not in _REASONING_EFFORT_BY_DEPTH
        or profile.max_reasoning_tokens is not None
        for profile in endpoint.reasoning_profiles
    ):
        raise validation_error("astrbot_adapter_reasoning_overclaim")


def _validate_request(
    descriptor: ModelProviderDescriptor,
    request: ProviderRequest,
):
    endpoint = descriptor.endpoints[0]
    if (
        request.provider_id != descriptor.provider_id
        or request.provider_revision != descriptor.revision
        or request.endpoint_id != endpoint.endpoint_id
        or request.endpoint_descriptor_digest != endpoint.descriptor_digest
        or request.model_id != endpoint.model_id
        or request.selected_tier is not endpoint.tier
    ):
        raise _failure(
            ModelFailureKind.INVALID_REQUEST,
            "astrbot_request_binding_mismatch",
        )
    if request.reasoning_profile not in endpoint.reasoning_profiles:
        raise _failure(
            ModelFailureKind.CAPABILITY_MISMATCH,
            "astrbot_reasoning_profile_mismatch",
        )
    if (
        endpoint.processing_boundary is ModelProcessingBoundary.EXTERNAL
        and not request.privacy.allow_external_provider
    ):
        raise _failure(
            ModelFailureKind.INVALID_REQUEST,
            "astrbot_external_processing_forbidden",
        )
    if request.privacy.data_classification not in endpoint.allowed_data_classes:
        raise _failure(
            ModelFailureKind.INVALID_REQUEST,
            "astrbot_data_classification_forbidden",
        )
    if request.max_output_tokens > endpoint.capabilities.max_output_tokens:
        raise _failure(
            ModelFailureKind.INVALID_REQUEST,
            "astrbot_output_limit_exceeded",
        )
    if request.temperature is not None:
        raise _failure(
            ModelFailureKind.CAPABILITY_MISMATCH,
            "astrbot_temperature_unverified",
        )
    if request.random_seed is not None:
        raise _failure(
            ModelFailureKind.CAPABILITY_MISMATCH,
            "astrbot_seed_unverified",
        )
    if request.selected_data_residency not in endpoint.available_data_residencies:
        raise _failure(
            ModelFailureKind.INVALID_REQUEST,
            "astrbot_residency_mismatch",
        )
    if request.required_retention_mode not in endpoint.supported_retention_modes:
        raise _failure(
            ModelFailureKind.INVALID_REQUEST,
            "astrbot_retention_mismatch",
        )
    return endpoint


def _validate_call(
    call: PortCallContext | ServiceCallContext,
    now: datetime,
) -> None:
    if call.cancellation.is_cancelled:
        raise _failure(
            ModelFailureKind.CANCELLED,
            "astrbot_cancelled_before_call",
        )
    if now >= call.deadline:
        raise _failure(
            ModelFailureKind.TIMEOUT,
            "astrbot_deadline_before_call",
        )


def _astrbot_provider_id(provider: object) -> str:
    meta = getattr(provider, "meta", None)
    if not callable(meta):
        raise validation_error("astrbot_provider_meta_missing")
    value = meta()
    provider_id = (
        value.get("id") if isinstance(value, Mapping) else getattr(value, "id", None)
    )
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise validation_error("astrbot_provider_meta_id_missing")
    return provider_id


def _map_usage(raw: object) -> ModelUsage | None:
    if raw is None:
        return None
    values = tuple(
        _safe_getattr(raw, field_name)
        for field_name in ("input_other", "input_cached", "output")
    )
    if any(type(value) is not int or value < 0 for value in values):
        raise _failure(
            ModelFailureKind.INTERNAL,
            "astrbot_usage_invalid",
        )
    input_other, input_cached, output = values
    if input_other == 0 and input_cached == 0 and output == 0:
        return None
    return ModelUsage(
        schema_version=1,
        input_tokens=input_other + input_cached,
        generated_tokens=output,
        reasoning_tokens=None,
        cached_input_tokens=input_cached,
        cost_units=None,
    )


def _classify_exception(exc: Exception) -> ModelProviderError:
    status = _status_code(exc)
    code = _structured_code(exc)
    class_name = type(exc).__name__
    if code in {
        "content_filter",
        "content_policy_violation",
        "moderation_blocked",
        "safety_rejection",
    }:
        return _failure(ModelFailureKind.SAFETY_REJECTED, "astrbot_safety_rejected")
    if code == "context_length_exceeded":
        return _failure(
            ModelFailureKind.CONTEXT_TOO_LONG,
            "astrbot_context_too_long",
        )
    if status in {401, 403}:
        return _failure(
            ModelFailureKind.AUTHENTICATION, "astrbot_authentication_failed"
        )
    if status == 408 or isinstance(exc, TimeoutError):
        return _failure(
            ModelFailureKind.TIMEOUT,
            "astrbot_timeout",
            outcome_unknown=True,
        )
    if status == 429:
        return _failure(
            ModelFailureKind.RATE_LIMITED,
            "astrbot_rate_limited",
        )
    if status is not None and 500 <= status <= 599:
        return _failure(
            ModelFailureKind.PROVIDER_UNAVAILABLE,
            "astrbot_provider_unavailable",
            outcome_unknown=True,
        )
    if status in {400, 422}:
        return _failure(ModelFailureKind.INVALID_REQUEST, "astrbot_invalid_request")
    if class_name == "EmptyModelOutputError":
        return _failure(
            ModelFailureKind.OUTPUT_INVALID,
            "astrbot_empty_model_output",
        )
    if isinstance(exc, (ConnectionError, OSError)):
        return _failure(
            ModelFailureKind.TRANSIENT_NETWORK,
            "astrbot_network_failure",
            outcome_unknown=True,
        )
    return _failure(ModelFailureKind.INTERNAL, "astrbot_unclassified_failure")


def _status_code(exc: Exception) -> int | None:
    response = _safe_getattr(exc, "response")
    for value in (
        _safe_getattr(exc, "status_code"),
        _safe_getattr(exc, "status"),
        _safe_getattr(response, "status_code"),
    ):
        if type(value) is int:
            return value
    return None


def _structured_code(exc: Exception) -> str | None:
    response = _safe_getattr(exc, "response")
    for value in (
        _safe_getattr(exc, "code"),
        _safe_getattr(response, "code"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    return None


def _safe_getattr(value: object, name: str) -> object | None:
    try:
        return getattr(value, name, None)
    except BaseException:
        return _ATTRIBUTE_READ_FAILED


def _failure(
    failure_kind: ModelFailureKind,
    reason_code: str,
    *,
    outcome_unknown: bool = False,
) -> ModelProviderError:
    return ModelProviderError(
        failure_kind,
        model_error_info(
            failure_kind,
            code=f"astrbot_{failure_kind.value}",
            reason_codes=(reason_code,),
            outcome_unknown=outcome_unknown,
        ),
    )


async def _cancel_task(task: asyncio.Task[object]) -> bool:
    cleanup = asyncio.create_task(_bounded_cancel_task(task))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
            continue
    cleanup.result()
    return cancelled


async def _bounded_cancel_task(task: asyncio.Task[object]) -> None:
    if task.done():
        _consume_task(task)
        return
    task.cancel()
    done, _ = await asyncio.wait((task,), timeout=0.1)
    if task not in done:
        task.add_done_callback(_consume_task)
        return
    _consume_task(task)


def _consume_task(task: asyncio.Task[object]) -> None:
    try:
        task.result()
    except BaseException:
        pass
