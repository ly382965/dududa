from __future__ import annotations

import math
import unittest
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal
from types import MappingProxyType

from dududa.domain.primitives import DigestString, PrivacyLevel
from dududa.errors import DududaError, ErrorCategory, ErrorInfo
from dududa.models.contracts import (
    AdmissionDisposition,
    EndpointAdmissionRequest,
    EndpointAdmissionResult,
    EndpointCapacityLease,
    EndpointCapacityReceipt,
    EndpointHealthStatus,
    EndpointLoadSnapshot,
    LoadCounterScope,
    EndpointRejection,
    EndpointRouteCandidatePlan,
    EndpointTrafficPolicy,
    ModelCapabilities,
    ModelEndpointHealth,
    ModelEndpointRef,
    ModelFailureKind,
    ModelInput,
    ModelInputModality,
    ModelInputPart,
    ModelInvocationEstimate,
    ModelOperationalSnapshot,
    ModelPrivacyPolicy,
    ModelProcessingBoundary,
    ModelProcessingReceipt,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRequest,
    ModelResponse,
    ModelRetentionMode,
    ModelRole,
    ModelTier,
    ModelUsage,
    ProviderResponse,
    ReasoningDepth,
    ReasoningProfile,
    RouteAttempt,
    RouteAttemptKind,
    RouteDecision,
    RouteHint,
    SafetyAnnotation,
    StaleSnapshotPolicy,
)
from dududa.models.digests import (
    model_endpoint_descriptor_digest,
    model_invocation_estimate_digest,
    model_request_digest,
    model_request_fingerprint,
    route_decision_digest,
    route_plan_fingerprint,
)
from dududa.models.errors import ModelInvocationError, ModelProviderError

from .helpers import NOW, endpoint, reasoning_profiles, revision, traffic_policy


def _execution_evidence(
    descriptor,
    selected: ModelEndpointRef,
    reasoning_profile: ReasoningProfile,
    *,
    request_id: str,
    suffix: str,
) -> tuple[
    EndpointRouteCandidatePlan,
    EndpointAdmissionResult,
    EndpointCapacityReceipt,
    DigestString,
]:
    estimate = ModelInvocationEstimate(
        schema_version=1,
        model_request_digest=DigestString(f"model-request-{suffix}"),
        endpoint_descriptor_digest=selected.endpoint_descriptor_digest,
        reasoning_profile_id=reasoning_profile.profile_id,
        input_tokens_upper_bound=100,
        generated_tokens_upper_bound=50,
        reasoning_tokens_upper_bound=25,
        total_context_tokens_upper_bound=150,
        cost_units_upper_bound=Decimal("0.5"),
        estimator_revision=revision("model-estimator"),
    )
    estimate_digest = model_invocation_estimate_digest(estimate)
    candidate = EndpointRouteCandidatePlan(
        schema_version=1,
        endpoint=selected,
        estimate=estimate,
        reasoning_profile=reasoning_profile,
        selected_data_residency="global",
        required_retention_mode=ModelRetentionMode.NO_RETENTION,
    )
    admission_request = EndpointAdmissionRequest(
        schema_version=1,
        reservation_id=f"reservation-{suffix}",
        model_request_id=request_id,
        model_request_digest=estimate.model_request_digest,
        provider_id=selected.provider_id,
        endpoint_id=selected.endpoint_id,
        endpoint_descriptor_digest=selected.endpoint_descriptor_digest,
        quota_pool_id=descriptor.quota_pool_id,
        traffic_policy_id=descriptor.traffic_policy.policy_id,
        traffic_policy_revision=descriptor.traffic_policy.policy_revision,
        operational_snapshot_id="operational-snapshot-1",
        operational_snapshot_digest=DigestString("operational-digest-1"),
        invocation_estimate_digest=estimate_digest,
        invocation_estimate=estimate,
        reserved_input_tokens=estimate.input_tokens_upper_bound,
        reserved_generated_tokens=estimate.generated_tokens_upper_bound,
        reserved_reasoning_tokens=estimate.reasoning_tokens_upper_bound,
        reserved_cost_units=estimate.cost_units_upper_bound,
        expires_at=NOW + timedelta(seconds=30),
    )
    lease = EndpointCapacityLease(
        schema_version=1,
        lease_id=f"lease-{suffix}",
        request=admission_request,
        admission_revision="admission-v1",
        issued_at=NOW,
    )
    admission = EndpointAdmissionResult(
        schema_version=1,
        request=admission_request,
        disposition=AdmissionDisposition.RESERVED,
        lease=lease,
        admission_revision="admission-v1",
        reason_codes=("capacity_reserved",),
        decided_at=NOW,
    )
    charged = ModelUsage(
        schema_version=1,
        input_tokens=100,
        generated_tokens=50,
        reasoning_tokens=25,
        cached_input_tokens=None,
        cost_units=Decimal("0.5"),
    )
    receipt = EndpointCapacityReceipt(
        schema_version=1,
        lease_id=lease.lease_id,
        disposition=AdmissionDisposition.SETTLED,
        usage=charged,
        reason_codes=("usage_settled",),
        recorded_at=NOW,
    )
    return candidate, admission, receipt, estimate_digest


class ModelContractTests(unittest.TestCase):
    def test_public_leaf_receipts_are_versioned(self) -> None:
        for contract in (
            ModelEndpointRef,
            ModelInputPart,
            SafetyAnnotation,
            ModelEndpointHealth,
            RouteAttempt,
            EndpointRejection,
            EndpointAdmissionResult,
            EndpointRouteCandidatePlan,
        ):
            with self.subTest(contract=contract.__name__):
                self.assertIn(
                    "schema_version", {field.name for field in fields(contract)}
                )

    def test_endpoint_identity_is_separate_from_native_model_id(self) -> None:
        first = endpoint("deployment-a", ModelTier.HAIKU, model_id="same-model")
        second = endpoint("deployment-b", ModelTier.HAIKU, model_id="same-model")
        provider = ModelProviderDescriptor(
            schema_version=1,
            provider_id="provider-a",
            revision=revision(),
            endpoints=(first, second),
        )

        self.assertEqual(len(provider.endpoints), 2)
        self.assertEqual(
            first.descriptor_digest,
            model_endpoint_descriptor_digest(first),
        )
        self.assertNotEqual(first.descriptor_digest, second.descriptor_digest)

    def test_reasoning_context_and_traffic_limits_fail_closed(self) -> None:
        with self.assertRaises(DududaError):
            ReasoningProfile(
                schema_version=1,
                profile_id="off",
                depth=ReasoningDepth.OFF,
                max_reasoning_tokens=1,
                required=True,
            )
        with self.assertRaises(DududaError):
            ModelCapabilities(
                schema_version=1,
                input_modalities=frozenset({ModelInputModality.TEXT}),
                output_modalities=endpoint(
                    "x", ModelTier.HAIKU
                ).capabilities.output_modalities,
                native_structured_output=endpoint(
                    "y", ModelTier.HAIKU
                ).capabilities.native_structured_output,
                max_context_tokens=10,
                max_input_tokens=11,
                max_output_tokens=1,
                supports_temperature=True,
                supports_streaming=True,
                supports_seed=False,
            )
        with self.assertRaises(DududaError):
            replace(traffic_policy(), max_429_rate=math.nan)
        with self.assertRaises(DududaError):
            replace(traffic_policy(), minimum_samples=0)
        with self.assertRaises(DududaError):
            EndpointTrafficPolicy(
                schema_version=1,
                policy_id="invalid",
                policy_revision="traffic-v1",
                max_concurrency=0,
                rpm_limit=None,
                tpm_limit=None,
                max_queue_depth=0,
                max_p95_latency_ms=None,
                max_429_rate=0,
                max_error_rate=0,
                observation_window_seconds=60,
                minimum_samples=0,
                cooldown_seconds=0,
                max_snapshot_age_seconds=10,
                stale_snapshot_policy=StaleSnapshotPolicy.EXCLUDE,
            )

    def test_route_hint_has_no_tier_authority(self) -> None:
        names = {field.name for field in fields(RouteHint)}
        self.assertNotIn("tier", names)
        self.assertNotIn("model_tier", names)
        with self.assertRaises(DududaError):
            RouteHint(
                schema_version=1,
                provider_id=None,
                endpoint_id=None,
                model_id=None,
            )

    def test_model_input_privacy_and_nested_output_are_strict(self) -> None:
        text = ModelInputPart(
            schema_version=1,
            part_id="part-1",
            modality=ModelInputModality.TEXT,
            text="hello",
            content_ref=None,
            content_digest=None,
            media_type=None,
        )
        model_input = ModelInput(
            schema_version=1,
            parts=(text,),
            source_refs=("message:m1",),
        )
        privacy = ModelPrivacyPolicy(
            schema_version=1,
            data_classification=PrivacyLevel.CONVERSATION,
            allow_external_provider=True,
            allowed_residencies=frozenset({"global"}),
            allow_provider_retention=False,
        )
        request = ModelRequest(
            schema_version=1,
            request_id="request-1",
            role=ModelRole.DIRECT_CHAT,
            input=model_input,
            output_schema=None,
            max_output_tokens=256,
            content_input_tokens_upper_bound=32,
            temperature=0.2,
            privacy=privacy,
            reasoning_profile_id="balanced",
            random_seed=None,
            idempotency_key="idem-1",
            route_hint=None,
        )

        self.assertEqual(request.input.parts, (text,))
        replay_request = replace(
            request,
            request_id="request-replay",
            idempotency_key="idem-replay",
        )
        self.assertNotEqual(
            model_request_digest(request), model_request_digest(replay_request)
        )
        self.assertEqual(
            model_request_fingerprint(request),
            model_request_fingerprint(replay_request),
        )
        descriptor = endpoint("estimate-endpoint", ModelTier.SONNET)
        estimate = ModelInvocationEstimate(
            schema_version=1,
            model_request_digest=model_request_digest(request),
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            reasoning_profile_id="balanced",
            input_tokens_upper_bound=40,
            generated_tokens_upper_bound=256,
            reasoning_tokens_upper_bound=128,
            total_context_tokens_upper_bound=296,
            cost_units_upper_bound=Decimal("0.5"),
            estimator_revision=revision("invocation-estimator"),
        )
        self.assertEqual(
            model_invocation_estimate_digest(estimate),
            model_invocation_estimate_digest(estimate),
        )
        with self.assertRaises(DududaError):
            replace(estimate, total_context_tokens_upper_bound=295)
        with self.assertRaises(DududaError):
            replace(privacy, data_classification=PrivacyLevel.RESTRICTED)
        with self.assertRaises(DududaError):
            replace(privacy, allowed_residencies="global")
        with self.assertRaises(DududaError):
            replace(text, content_ref="opaque-ref")
        with self.assertRaises(DududaError):
            replace(model_input, parts=(text, text))
        for field_name, invalid in (
            ("input", {"parts": []}),
            ("privacy", {"data_classification": "conversation"}),
            ("output_schema", {"schema_id": "answer"}),
            ("route_hint", {"provider_id": "provider-a"}),
        ):
            with self.subTest(field=field_name), self.assertRaises(DududaError):
                replace(request, **{field_name: invalid})
        with self.assertRaises(DududaError):
            replace(request, role=ModelRole.PERCEPTION)

    def test_load_snapshot_and_capacity_receipt_validate_observations(self) -> None:
        descriptor = endpoint("load-endpoint", ModelTier.SONNET)
        load = EndpointLoadSnapshot(
            schema_version=1,
            provider_id="provider-a",
            endpoint_id=descriptor.endpoint_id,
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            quota_pool_id=descriptor.quota_pool_id,
            traffic_policy_id=descriptor.traffic_policy.policy_id,
            traffic_policy_revision=descriptor.traffic_policy.policy_revision,
            counter_scope=LoadCounterScope.EXTERNAL_TO_ADMISSION_CONTROLLER,
            in_flight=1,
            requests_per_minute=2,
            tokens_per_minute=300,
            queue_depth=0,
            p95_latency_ms=500,
            rate_429=0,
            error_rate=0.05,
            sample_count=20,
            cooldown_until=None,
            checked_at=NOW,
            snapshot_revision="load-v1",
        )
        usage = ModelUsage(
            schema_version=1,
            input_tokens=10,
            generated_tokens=5,
            reasoning_tokens=2,
            cached_input_tokens=0,
            cost_units=Decimal("0.1"),
        )

        self.assertEqual(load.sample_count, 20)
        self.assertEqual(usage.total_generated_tokens, 5)
        self.assertEqual(usage.total_tokens, 15)
        with self.assertRaises(DududaError):
            replace(usage, cached_input_tokens=11)
        with self.assertRaises(DududaError):
            replace(usage, reasoning_tokens=6)
        operational = ModelOperationalSnapshot(
            schema_version=1,
            snapshot_id="operational-1",
            provider_health=(),
            endpoint_load=(load,),
            acquired_at=NOW,
        )
        with self.assertRaises(DududaError):
            replace(operational, acquired_at=NOW - timedelta(seconds=1))
        admission_estimate = ModelInvocationEstimate(
            schema_version=1,
            model_request_digest=DigestString("model-request-digest"),
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            reasoning_profile_id="balanced",
            input_tokens_upper_bound=100,
            generated_tokens_upper_bound=50,
            reasoning_tokens_upper_bound=25,
            total_context_tokens_upper_bound=150,
            cost_units_upper_bound=Decimal("0.5"),
            estimator_revision=revision("model-estimator"),
        )
        admission = EndpointAdmissionRequest(
            schema_version=1,
            reservation_id="reservation-1",
            model_request_id="request-1",
            model_request_digest=DigestString("model-request-digest"),
            provider_id="provider-a",
            endpoint_id=descriptor.endpoint_id,
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            quota_pool_id=descriptor.quota_pool_id,
            traffic_policy_id=descriptor.traffic_policy.policy_id,
            traffic_policy_revision=descriptor.traffic_policy.policy_revision,
            operational_snapshot_id=operational.snapshot_id,
            operational_snapshot_digest=DigestString("operational-digest"),
            invocation_estimate_digest=model_invocation_estimate_digest(
                admission_estimate
            ),
            invocation_estimate=admission_estimate,
            reserved_input_tokens=100,
            reserved_generated_tokens=50,
            reserved_reasoning_tokens=25,
            reserved_cost_units=Decimal("0.5"),
            expires_at=NOW + timedelta(seconds=30),
        )
        with self.assertRaises(DududaError):
            replace(admission, traffic_policy_revision="")
        with self.assertRaises(DududaError):
            replace(admission, reserved_reasoning_tokens=51)
        with self.assertRaises(DududaError):
            replace(load, error_rate=1.1)
        with self.assertRaises(DududaError):
            EndpointCapacityReceipt(
                schema_version=1,
                lease_id="lease-1",
                disposition=AdmissionDisposition.SETTLED,
                usage=None,
                reason_codes=(),
                recorded_at=NOW,
            )
        with self.assertRaises(DududaError):
            EndpointCapacityReceipt(
                schema_version=1,
                lease_id="lease-1",
                disposition=AdmissionDisposition.RELEASED,
                usage=usage,
                reason_codes=(),
                recorded_at=NOW,
            )

    def test_provider_response_freezes_output_and_binds_processing(self) -> None:
        descriptor = endpoint("provider-endpoint", ModelTier.SONNET)
        provider_revision = revision()
        processing = ModelProcessingReceipt(
            schema_version=1,
            provider_id="provider-a",
            provider_revision=provider_revision,
            endpoint_id=descriptor.endpoint_id,
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            model_id=descriptor.model_id,
            provider_request_digest=DigestString("provider-request-1"),
            processing_boundary=ModelProcessingBoundary.EXTERNAL,
            data_residency="global",
            retention_mode=ModelRetentionMode.NO_RETENTION,
            requested_reasoning_profile_id="balanced",
            effective_reasoning_profile_id="balanced",
            requested_seed=None,
            effective_seed=None,
        )
        raw = {"answer": ["ok"]}
        response = ProviderResponse(
            schema_version=1,
            request_id="request-1",
            provider_id="provider-a",
            endpoint_id=descriptor.endpoint_id,
            model_id=descriptor.model_id,
            provider_revision=provider_revision,
            output=raw,
            finish_reason="stop",
            usage=None,
            safety_annotations=(),
            processing=processing,
        )
        raw["answer"].append("mutated")

        self.assertIsInstance(response.output, MappingProxyType)
        self.assertEqual(response.output["answer"], ("ok",))
        with self.assertRaises(DududaError):
            replace(response, endpoint_id="other-endpoint")

    def test_provider_health_rejects_duplicate_endpoints(self) -> None:
        descriptor = endpoint("health-endpoint", ModelTier.HAIKU)
        health_item = descriptor.endpoint_id
        endpoint_health = ModelEndpointHealth(
            schema_version=1,
            endpoint_id=health_item,
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            status=EndpointHealthStatus.HEALTHY,
            reason_codes=(),
        )
        with self.assertRaises(DududaError):
            ModelProviderHealth(
                schema_version=1,
                provider_id="provider-a",
                status=EndpointHealthStatus.HEALTHY,
                endpoints=(endpoint_health, endpoint_health),
                snapshot_revision="health-v1",
                checked_at=NOW + timedelta(seconds=1),
                reason_codes=(),
            )

    def test_route_decision_and_model_response_bind_success_receipts(self) -> None:
        descriptor = endpoint("selected-endpoint", ModelTier.SONNET)
        selected = ModelEndpointRef(
            schema_version=1,
            provider_id="provider-a",
            endpoint_id=descriptor.endpoint_id,
            model_id=descriptor.model_id,
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            tier=descriptor.tier,
            priority=10,
        )
        reasoning_profile = reasoning_profiles()[1]
        candidate, admission, capacity_receipt, estimate_digest = _execution_evidence(
            descriptor,
            selected,
            reasoning_profile,
            request_id="request-1",
            suffix="success-1",
        )
        attempt = RouteAttempt(
            schema_version=1,
            attempt=1,
            kind=RouteAttemptKind.PRIMARY,
            provider_id=selected.provider_id,
            endpoint_id=selected.endpoint_id,
            model_id=selected.model_id,
            tier=selected.tier,
            invocation_estimate_digest=estimate_digest,
            admission_reservation_id=admission.request.reservation_id,
            provider_request_digest=DigestString("provider-request-1"),
            prompt_template_revision=revision("direct-chat-prompt"),
            started_at=NOW,
            latency_ms=25,
            failure_kind=None,
            error=None,
        )
        route_fingerprint = route_plan_fingerprint(
            model_request_fingerprint=DigestString("model-request-plan-1"),
            tier_selection_fingerprint=DigestString("tier-plan-1"),
            requested_tier=ModelTier.SONNET,
            catalog_revision="catalog-v1",
            route_policy_digest=DigestString("direct-chat-policy-digest"),
            output_schema_digest=None,
            output_codec_revision=None,
            candidate_plans=(candidate,),
            rejected_endpoints=(),
            planned_endpoint=selected,
        )
        decision = RouteDecision(
            schema_version=1,
            decision_id="route-decision-1",
            request_id="request-1",
            model_request_digest=DigestString("model-request-1"),
            model_request_fingerprint=DigestString("model-request-plan-1"),
            role=ModelRole.DIRECT_CHAT,
            requested_tier=ModelTier.SONNET,
            selected_tier=ModelTier.SONNET,
            tier_authority_digest=DigestString("tier-decision-digest"),
            tier_selection_fingerprint=DigestString("tier-plan-1"),
            routing_snapshot_id="catalog-snapshot-1",
            catalog_revision="catalog-v1",
            route_policy_revision="direct-chat-v1",
            operational_snapshot_id="operational-snapshot-1",
            operational_snapshot_digest=DigestString("operational-digest-1"),
            output_schema_digest=None,
            output_codec_revision=None,
            route_plan_fingerprint=route_fingerprint,
            candidate_plans=(candidate,),
            eligible_endpoints=(selected,),
            rejected_endpoints=(),
            planned_endpoint=selected,
            selected_endpoint=selected,
            reasoning_profile=reasoning_profile,
            admission_results=(admission,),
            capacity_receipts=(capacity_receipt,),
            attempts=(attempt,),
            terminal_failure_kind=None,
            terminal_error=None,
            decided_at=NOW,
        )
        processing = ModelProcessingReceipt(
            schema_version=1,
            provider_id=selected.provider_id,
            provider_revision=revision(),
            endpoint_id=selected.endpoint_id,
            endpoint_descriptor_digest=selected.endpoint_descriptor_digest,
            model_id=selected.model_id,
            provider_request_digest=attempt.provider_request_digest,
            processing_boundary=ModelProcessingBoundary.EXTERNAL,
            data_residency="global",
            retention_mode=ModelRetentionMode.NO_RETENTION,
            requested_reasoning_profile_id="balanced",
            effective_reasoning_profile_id="balanced",
            requested_seed=None,
            effective_seed=None,
        )
        raw = {"answer": ["ok"]}
        response = ModelResponse(
            schema_version=1,
            request_id="request-1",
            role=ModelRole.DIRECT_CHAT,
            output_schema_digest=None,
            output=raw,
            finish_reason="stop",
            usage=None,
            latency_ms=25,
            route_decision=decision,
            safety_annotations=(),
            processing=processing,
        )
        raw["answer"].append("mutated")

        self.assertEqual(response.output["answer"], ("ok",))
        self.assertEqual(
            route_decision_digest(decision), route_decision_digest(decision)
        )
        with self.assertRaises(DududaError):
            replace(
                decision,
                output_schema_digest=DigestString("schema-digest"),
            )
        with self.assertRaises(DududaError):
            replace(
                response,
                output_schema_digest=DigestString("schema-digest"),
            )
        with self.assertRaises(DududaError):
            replace(
                response,
                processing=replace(
                    processing,
                    endpoint_descriptor_digest=DigestString("stale-descriptor"),
                ),
            )
        with self.assertRaises(DududaError):
            replace(
                response,
                processing=replace(
                    processing,
                    requested_reasoning_profile_id="quick",
                ),
            )
        with self.assertRaises(DududaError):
            replace(
                response,
                processing=replace(
                    processing,
                    effective_reasoning_profile_id="quick",
                ),
            )

    def test_failed_route_is_recordable_but_cannot_form_success_response(self) -> None:
        descriptor = endpoint("failed-endpoint", ModelTier.OPUS)
        selected = ModelEndpointRef(
            schema_version=1,
            provider_id="provider-a",
            endpoint_id=descriptor.endpoint_id,
            model_id=descriptor.model_id,
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            tier=descriptor.tier,
            priority=10,
        )
        mutable_reasons = ["deadline_exceeded"]
        failure = ErrorInfo(
            schema_version=1,
            code="model_timeout",
            category=ErrorCategory.TIMEOUT,
            retryable=True,
            outcome_unknown=False,
            public_message_key="model.unavailable",
            reason_codes=mutable_reasons,
        )
        mutable_reasons.append("mutated")
        self.assertEqual(failure.reason_codes, ("deadline_exceeded",))
        reasoning_profile = reasoning_profiles()[2]
        candidate, admission, capacity_receipt, estimate_digest = _execution_evidence(
            descriptor,
            selected,
            reasoning_profile,
            request_id="request-failed",
            suffix="failed-1",
        )
        failed_attempt = RouteAttempt(
            schema_version=1,
            attempt=1,
            kind=RouteAttemptKind.PRIMARY,
            provider_id=selected.provider_id,
            endpoint_id=selected.endpoint_id,
            model_id=selected.model_id,
            tier=selected.tier,
            invocation_estimate_digest=estimate_digest,
            admission_reservation_id=admission.request.reservation_id,
            provider_request_digest=DigestString("provider-request-failed-1"),
            prompt_template_revision=revision("direct-chat-prompt"),
            started_at=NOW,
            latency_ms=1_000,
            failure_kind=ModelFailureKind.TIMEOUT,
            error=failure,
        )
        with self.assertRaises(DududaError):
            replace(failed_attempt, failure_kind=ModelFailureKind.RATE_LIMITED)
        decision = RouteDecision(
            schema_version=1,
            decision_id="route-decision-failed",
            request_id="request-failed",
            model_request_digest=DigestString("model-request-failed"),
            model_request_fingerprint=DigestString("model-request-plan-failed"),
            role=ModelRole.DIRECT_CHAT,
            requested_tier=ModelTier.OPUS,
            selected_tier=ModelTier.OPUS,
            tier_authority_digest=DigestString("tier-decision-digest"),
            tier_selection_fingerprint=DigestString("tier-plan-failed"),
            routing_snapshot_id="catalog-snapshot-1",
            catalog_revision="catalog-v1",
            route_policy_revision="direct-chat-v1",
            operational_snapshot_id="operational-snapshot-1",
            operational_snapshot_digest=DigestString("operational-digest-1"),
            output_schema_digest=None,
            output_codec_revision=None,
            route_plan_fingerprint=DigestString("route-plan-failed"),
            candidate_plans=(candidate,),
            eligible_endpoints=(selected,),
            rejected_endpoints=(),
            planned_endpoint=selected,
            selected_endpoint=selected,
            reasoning_profile=reasoning_profile,
            admission_results=(admission,),
            capacity_receipts=(capacity_receipt,),
            attempts=(failed_attempt,),
            terminal_failure_kind=ModelFailureKind.TIMEOUT,
            terminal_error=failure,
            decided_at=NOW,
        )
        processing = ModelProcessingReceipt(
            schema_version=1,
            provider_id=selected.provider_id,
            provider_revision=revision(),
            endpoint_id=selected.endpoint_id,
            endpoint_descriptor_digest=selected.endpoint_descriptor_digest,
            model_id=selected.model_id,
            provider_request_digest=failed_attempt.provider_request_digest,
            processing_boundary=ModelProcessingBoundary.EXTERNAL,
            data_residency="global",
            retention_mode=ModelRetentionMode.NO_RETENTION,
            requested_reasoning_profile_id="deep",
            effective_reasoning_profile_id="deep",
            requested_seed=None,
            effective_seed=None,
        )

        self.assertEqual(decision.attempts[-1].failure_kind, ModelFailureKind.TIMEOUT)
        provider_error = ModelProviderError(ModelFailureKind.TIMEOUT, failure)
        invocation_error = ModelInvocationError(
            ModelFailureKind.TIMEOUT,
            failure,
            decision,
        )
        self.assertIs(provider_error.info, failure)
        self.assertIs(invocation_error.route_decision, decision)
        unsafe = ErrorInfo(
            schema_version=1,
            code="https://provider.invalid/?token=secret",
            category=ErrorCategory.TIMEOUT,
            retryable=True,
            outcome_unknown=True,
            public_message_key="Authorization: Bearer secret",
            reason_codes=("provider response body secret",),
        )
        with self.assertRaises(DududaError):
            ModelProviderError(ModelFailureKind.TIMEOUT, unsafe)
        with self.assertRaises(DududaError):
            ModelProviderError(
                ModelFailureKind.TIMEOUT,
                failure,
                detail="provider response body secret",
            )
        with self.assertRaises(DududaError):
            ModelResponse(
                schema_version=1,
                request_id=decision.request_id,
                role=decision.role,
                output_schema_digest=None,
                output={"answer": "must not escape"},
                finish_reason="error",
                usage=None,
                latency_ms=1_000,
                route_decision=decision,
                safety_annotations=(),
                processing=processing,
            )
        with self.assertRaises(DududaError):
            replace(decision, attempts=(replace(failed_attempt, attempt=2),))
        with self.assertRaises(DududaError):
            replace(
                decision,
                attempts=(
                    replace(
                        failed_attempt,
                        kind=RouteAttemptKind.SAME_TIER_FAILOVER,
                    ),
                ),
            )
        other_descriptor = endpoint("other-opus", ModelTier.OPUS)
        other = ModelEndpointRef(
            schema_version=1,
            provider_id="provider-a",
            endpoint_id=other_descriptor.endpoint_id,
            model_id=other_descriptor.model_id,
            endpoint_descriptor_digest=other_descriptor.descriptor_digest,
            tier=other_descriptor.tier,
            priority=20,
        )
        invalid_retry = RouteAttempt(
            schema_version=1,
            attempt=2,
            kind=RouteAttemptKind.ENDPOINT_RETRY,
            provider_id=other.provider_id,
            endpoint_id=other.endpoint_id,
            model_id=other.model_id,
            tier=other.tier,
            invocation_estimate_digest=DigestString("retry-estimate"),
            admission_reservation_id="reservation-retry-2",
            provider_request_digest=DigestString("provider-request-retry-2"),
            prompt_template_revision=revision("direct-chat-prompt"),
            started_at=NOW,
            latency_ms=10,
            failure_kind=None,
            error=None,
        )
        with self.assertRaises(DududaError):
            replace(
                decision,
                eligible_endpoints=(selected, other),
                selected_endpoint=other,
                attempts=(failed_attempt, invalid_retry),
            )
        with self.assertRaises(DududaError):
            ModelInvocationError(
                ModelFailureKind.RATE_LIMITED,
                failure,
                decision,
            )


if __name__ == "__main__":
    unittest.main()
