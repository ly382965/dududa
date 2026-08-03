from __future__ import annotations

import unittest
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal

from dududa.domain.primitives import DigestString, PrivacyLevel, RuntimeBudget
from dududa.domain.task import (
    ContextPressure,
    TaskAmbiguity,
    TaskComplexityAssessment,
    TaskComplexityLevel,
    TaskReasoningDepth,
)
from dududa.errors import DududaError
from dududa.models.contracts import (
    ModelEndpointDescriptor,
    ModelEndpointRef,
    ModelFailureKind,
    ModelInputModality,
    ModelOutputModality,
    ModelProviderDescriptor,
    ModelRole,
    ModelTier,
    StructuredOutputSupport,
)
from dududa.models.digests import (
    bootstrap_tier_decision_digest,
    bootstrap_tier_selection_fingerprint,
    model_endpoint_descriptor_digest,
    routing_catalog_digest,
    task_complexity_assessment_digest,
    tier_authority_digest,
    tier_decision_digest,
    tier_policy_definition_digest,
    tier_selection_context_digest,
    tier_selection_fingerprint,
)
from dududa.models.policy import (
    BootstrapTierDecision,
    ConfidenceHandling,
    ModelCapabilitiesRequirement,
    ModelFallbackPolicy,
    ModelRoutePolicy,
    ModelRoutingSnapshot,
    TierBudgetRequirement,
    TierDecision,
    TierFallbackEdge,
    TierPolicyDefinition,
    TierSelectionContext,
    validate_routing_snapshot,
    validate_tier_authority,
)

from .helpers import NOW, endpoint, reasoning_profiles, revision


def _ref(
    provider_id: str,
    descriptor: ModelEndpointDescriptor,
    priority: int,
) -> ModelEndpointRef:
    return ModelEndpointRef(
        schema_version=1,
        provider_id=provider_id,
        endpoint_id=descriptor.endpoint_id,
        model_id=descriptor.model_id,
        endpoint_descriptor_digest=descriptor.descriptor_digest,
        tier=descriptor.tier,
        priority=priority,
    )


def _route_policy(
    endpoints: tuple[ModelEndpointDescriptor, ...],
) -> ModelRoutePolicy:
    return ModelRoutePolicy(
        schema_version=1,
        policy_id="direct-chat",
        role=ModelRole.DIRECT_CHAT,
        default_tier=ModelTier.SONNET,
        allowed_tiers=frozenset({ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS}),
        candidate_endpoints=tuple(
            _ref("provider-a", descriptor, index * 10)
            for index, descriptor in enumerate(endpoints, 1)
        ),
        requirements=ModelCapabilitiesRequirement(
            schema_version=1,
            input_modalities=frozenset({ModelInputModality.TEXT}),
            output_modalities=frozenset({ModelOutputModality.TEXT}),
            minimum_native_structured_output=StructuredOutputSupport.JSON_SCHEMA,
            requires_schema_validation=True,
            minimum_context_tokens=32_000,
            minimum_output_tokens=512,
            reasoning_profile_id="balanced",
        ),
        allowed_data_classes=frozenset(
            {PrivacyLevel.PUBLIC, PrivacyLevel.CONVERSATION}
        ),
        fallback=ModelFallbackPolicy(
            schema_version=1,
            max_retries_per_endpoint=1,
            max_same_tier_failovers=1,
            max_tier_hops=2,
            max_total_attempts=4,
            retryable_failure_kinds=frozenset(
                {
                    ModelFailureKind.TRANSIENT_NETWORK,
                    ModelFailureKind.TIMEOUT,
                    ModelFailureKind.RATE_LIMITED,
                }
            ),
            deterministic_fallback_id="direct-chat-unavailable",
        ),
        tier_fallback_edges=(
            TierFallbackEdge(
                schema_version=1,
                from_tier=ModelTier.OPUS,
                to_tier=ModelTier.SONNET,
                failure_kinds=frozenset({ModelFailureKind.TIMEOUT}),
            ),
            TierFallbackEdge(
                schema_version=1,
                from_tier=ModelTier.SONNET,
                to_tier=ModelTier.HAIKU,
                failure_kinds=frozenset(
                    {ModelFailureKind.TIMEOUT, ModelFailureKind.RATE_LIMITED}
                ),
            ),
        ),
        policy_revision="direct-chat-v1",
    )


def _snapshot(
    endpoints: tuple[ModelEndpointDescriptor, ...],
    policy: ModelRoutePolicy | None = None,
) -> ModelRoutingSnapshot:
    provider = ModelProviderDescriptor(
        schema_version=1,
        provider_id="provider-a",
        revision=revision(),
        endpoints=endpoints,
    )
    route_policy = policy or _route_policy(endpoints)
    catalog_revision = str(routing_catalog_digest((provider,), (route_policy,)))
    return ModelRoutingSnapshot(
        schema_version=1,
        snapshot_id="snapshot-1",
        catalog_revision=catalog_revision,
        provider_descriptors=(provider,),
        route_policies=(route_policy,),
        acquired_at=NOW,
    )


def _tier_policy_definition() -> TierPolicyDefinition:
    return TierPolicyDefinition(
        schema_version=1,
        policy_id="tier-policy",
        role=ModelRole.DIRECT_CHAT,
        allowed_tiers=frozenset({ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS}),
        default_tier=ModelTier.SONNET,
        low_complexity_tier=ModelTier.HAIKU,
        high_complexity_tier=ModelTier.OPUS,
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
        tier_budget_requirements=(
            TierBudgetRequirement(1, ModelTier.HAIKU, 1_000, 256, Decimal("0.1")),
            TierBudgetRequirement(1, ModelTier.SONNET, 2_000, 512, Decimal(1)),
            TierBudgetRequirement(1, ModelTier.OPUS, 4_000, 1_024, Decimal(4)),
        ),
        policy_revision="tier-policy-v1",
    )


class ModelPolicyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.endpoints = (
            endpoint("haiku", ModelTier.HAIKU),
            endpoint("sonnet", ModelTier.SONNET),
            endpoint("opus", ModelTier.OPUS),
        )

    def test_valid_snapshot_binds_catalog_endpoint_and_policy_revisions(self) -> None:
        snapshot = _snapshot(self.endpoints)

        validate_routing_snapshot(snapshot)
        self.assertTrue(snapshot.catalog_revision.startswith("dududa-c14n-v1:"))

    def test_bootstrap_tier_authority_is_only_perception_haiku(self) -> None:
        policy_digest = DigestString("bootstrap-policy-digest")
        selection_fingerprint = bootstrap_tier_selection_fingerprint(
            role=ModelRole.PERCEPTION,
            selected_tier=ModelTier.HAIKU,
            tier_policy_digest=policy_digest,
            policy_revision="bootstrap-v1",
            reason_codes=("fixed_perception_bootstrap",),
        )
        decision = BootstrapTierDecision(
            schema_version=1,
            decision_id="bootstrap-perception-1",
            role=ModelRole.PERCEPTION,
            selected_tier=ModelTier.HAIKU,
            selection_fingerprint=selection_fingerprint,
            tier_policy_digest=policy_digest,
            policy_revision="bootstrap-v1",
            reason_codes=("fixed_perception_bootstrap",),
            decided_at=NOW,
        )

        names = {field.name for field in fields(BootstrapTierDecision)}
        self.assertNotIn("assessment_digest", names)
        self.assertEqual(
            tier_authority_digest(decision),
            bootstrap_tier_decision_digest(decision),
        )
        validate_tier_authority(ModelRole.PERCEPTION, decision)
        with self.assertRaises(DududaError):
            validate_tier_authority(ModelRole.DIRECT_CHAT, decision)
        with self.assertRaises(DududaError):
            replace(decision, role=ModelRole.DIRECT_CHAT)
        with self.assertRaises(DududaError):
            replace(decision, selected_tier=ModelTier.SONNET)

    def test_perception_route_policy_is_fixed_haiku_with_strict_schema(self) -> None:
        descriptor = self.endpoints[0]
        direct = _route_policy(self.endpoints)
        policy = ModelRoutePolicy(
            schema_version=1,
            policy_id="perception",
            role=ModelRole.PERCEPTION,
            default_tier=ModelTier.HAIKU,
            allowed_tiers=frozenset({ModelTier.HAIKU}),
            candidate_endpoints=(_ref("provider-a", descriptor, 10),),
            requirements=replace(
                direct.requirements,
                minimum_native_structured_output=StructuredOutputSupport.NONE,
                requires_schema_validation=True,
            ),
            allowed_data_classes=direct.allowed_data_classes,
            fallback=direct.fallback,
            tier_fallback_edges=(),
            policy_revision="perception-v1",
        )

        self.assertEqual(policy.allowed_tiers, frozenset({ModelTier.HAIKU}))
        prompt_only = replace(
            descriptor,
            capabilities=replace(
                descriptor.capabilities,
                native_structured_output=StructuredOutputSupport.NONE,
            ),
        )
        prompt_only = replace(
            prompt_only,
            descriptor_digest=model_endpoint_descriptor_digest(prompt_only),
        )
        prompt_policy = replace(
            policy,
            candidate_endpoints=(_ref("provider-a", prompt_only, 10),),
        )
        validate_routing_snapshot(_snapshot((prompt_only,), prompt_policy))
        with self.assertRaises(DududaError):
            replace(
                policy,
                requirements=replace(
                    policy.requirements,
                    requires_schema_validation=False,
                ),
            )
        with self.assertRaises(DududaError):
            replace(policy, default_tier=ModelTier.SONNET)

    def test_fallback_cycle_and_unsafe_failure_are_rejected(self) -> None:
        policy = _route_policy(self.endpoints)
        self.assertIn(
            "schema_version",
            {field.name for field in fields(TierFallbackEdge)},
        )
        with self.assertRaises(DududaError):
            replace(
                policy,
                tier_fallback_edges=policy.tier_fallback_edges
                + (
                    TierFallbackEdge(
                        schema_version=1,
                        from_tier=ModelTier.HAIKU,
                        to_tier=ModelTier.OPUS,
                        failure_kinds=frozenset({ModelFailureKind.TIMEOUT}),
                    ),
                ),
            )
        with self.assertRaises(DududaError):
            TierFallbackEdge(
                schema_version=1,
                from_tier=ModelTier.SONNET,
                to_tier=ModelTier.OPUS,
                failure_kinds=frozenset({ModelFailureKind.SAFETY_REJECTED}),
            )
        with self.assertRaises(DududaError):
            TierFallbackEdge(
                schema_version=1,
                from_tier=ModelTier.SONNET,
                to_tier=ModelTier.HAIKU,
                failure_kinds=frozenset({ModelFailureKind.OUTPUT_INVALID}),
            )

    def test_snapshot_rejects_descriptor_and_reference_drift(self) -> None:
        snapshot = _snapshot(self.endpoints)
        with self.assertRaises(DududaError):
            validate_routing_snapshot(
                replace(snapshot, catalog_revision="not-the-catalog-digest")
            )

        changed_endpoint = replace(
            self.endpoints[0],
            model_id="changed-without-new-descriptor-digest",
        )
        changed_provider = replace(
            snapshot.provider_descriptors[0],
            endpoints=(changed_endpoint,) + self.endpoints[1:],
        )
        changed_catalog = str(
            routing_catalog_digest(
                (changed_provider,),
                snapshot.route_policies,
            )
        )
        with self.assertRaises(DududaError):
            validate_routing_snapshot(
                replace(
                    snapshot,
                    provider_descriptors=(changed_provider,),
                    catalog_revision=changed_catalog,
                )
            )

        unknown = replace(
            snapshot.route_policies[0].candidate_endpoints[0],
            endpoint_id="missing",
        )
        changed_policy = replace(
            snapshot.route_policies[0],
            candidate_endpoints=(unknown,)
            + snapshot.route_policies[0].candidate_endpoints[1:],
        )
        with self.assertRaises(DududaError):
            validate_routing_snapshot(_snapshot(self.endpoints, changed_policy))

    def test_snapshot_rejects_unmapped_reasoning_profile(self) -> None:
        quick_only = (reasoning_profiles()[0],)
        changed = endpoint(
            "haiku",
            ModelTier.HAIKU,
            profiles=quick_only,
            default_profile_id="quick",
        )
        endpoints = (changed,) + self.endpoints[1:]
        policy = _route_policy(endpoints)

        with self.assertRaises(DududaError):
            validate_routing_snapshot(_snapshot(endpoints, policy))

    def test_snapshot_rejects_conflicting_shared_quota_pool_policy(self) -> None:
        changed = replace(
            self.endpoints[1],
            traffic_policy=replace(
                self.endpoints[1].traffic_policy,
                max_concurrency=99,
            ),
        )
        changed = replace(
            changed,
            descriptor_digest=model_endpoint_descriptor_digest(changed),
        )
        endpoints = (self.endpoints[0], changed, self.endpoints[2])

        with self.assertRaises(DududaError):
            validate_routing_snapshot(_snapshot(endpoints))

    def test_tier_context_and_decision_are_reproducibly_digestible(self) -> None:
        assessment = TaskComplexityAssessment(
            schema_version=1,
            assessment_id="assessment-1",
            level=TaskComplexityLevel.HIGH,
            confidence=0.9,
            task_kind="code_review",
            context_pressure=ContextPressure.MEDIUM,
            reasoning_depth=TaskReasoningDepth.DEEP,
            expected_tool_steps=0,
            ambiguity=TaskAmbiguity.LOW,
            verification_required=True,
            conflicting_evidence=False,
            reason_codes=("deep_reasoning", "independent_verification"),
            evidence_refs=("message:m1",),
            assessor_revision=revision("complexity-assessor"),
        )
        context = TierSelectionContext(
            schema_version=1,
            selection_id="selection-1",
            role=ModelRole.DIRECT_CHAT,
            assessment=assessment,
            content_input_tokens_upper_bound=2_000,
            data_classification=PrivacyLevel.CONVERSATION,
            budget=RuntimeBudget(
                model_calls_remaining=1,
                tool_steps_remaining=0,
                retries_remaining=1,
                input_tokens_remaining=4_000,
                output_tokens_remaining=2_000,
                cost_units_remaining=Decimal(5),
            ),
        )
        context_digest = tier_selection_context_digest(context)
        definition = _tier_policy_definition()
        policy_digest = tier_policy_definition_digest(definition)
        decision = TierDecision(
            schema_version=1,
            decision_id="tier-decision-1",
            role=ModelRole.DIRECT_CHAT,
            selected_tier=ModelTier.OPUS,
            uncapped_tier=ModelTier.OPUS,
            assessment_digest=task_complexity_assessment_digest(assessment),
            selection_context_digest=context_digest,
            selection_fingerprint=tier_selection_fingerprint(context, definition),
            tier_policy_digest=policy_digest,
            policy_revision="tier-policy-v1",
            confidence_handling=ConfidenceHandling.DIRECT,
            reason_codes=("high_complexity_evidence", "budget_allows_opus"),
            decided_at=NOW,
        )
        validate_tier_authority(ModelRole.DIRECT_CHAT, decision)
        with self.assertRaises(DududaError):
            validate_tier_authority(ModelRole.PERCEPTION, decision)

        self.assertEqual(context_digest, tier_selection_context_digest(context))
        self.assertEqual(tier_decision_digest(decision), tier_decision_digest(decision))
        replay_context = replace(context, selection_id="selection-replay")
        self.assertNotEqual(
            tier_selection_context_digest(context),
            tier_selection_context_digest(replay_context),
        )
        self.assertEqual(
            tier_selection_fingerprint(context, definition),
            tier_selection_fingerprint(replay_context, definition),
        )
        replay_decision = replace(
            decision,
            decision_id="tier-decision-replay",
            decided_at=NOW + timedelta(seconds=1),
        )
        self.assertNotEqual(
            tier_decision_digest(decision),
            tier_decision_digest(replay_decision),
        )
        self.assertEqual(
            decision.selection_fingerprint,
            replay_decision.selection_fingerprint,
        )
        with self.assertRaises(DududaError):
            replace(context, assessment={"level": "high"})
        with self.assertRaises(DududaError):
            replace(decision, uncapped_tier=ModelTier.SONNET)
        capped = replace(
            decision,
            selected_tier=ModelTier.SONNET,
            confidence_handling=ConfidenceHandling.BUDGET_CAPPED,
            reason_codes=("high_complexity_evidence", "budget_capped"),
        )
        self.assertEqual(capped.uncapped_tier, ModelTier.OPUS)

    def test_tier_policy_thresholds_and_allowed_tiers_are_strict(self) -> None:
        policy = _tier_policy_definition()
        self.assertEqual(policy.default_tier, ModelTier.SONNET)
        with self.assertRaises(DududaError):
            replace(policy, minimum_high_tier_confidence=0.5)
        with self.assertRaises(DududaError):
            replace(policy, role=ModelRole.PERCEPTION)
        with self.assertRaises(DududaError):
            replace(
                policy,
                allowed_tiers=frozenset({ModelTier.HAIKU, ModelTier.SONNET}),
            )
        with self.assertRaises(DududaError):
            replace(
                policy,
                tier_budget_requirements=policy.tier_budget_requirements[:-1],
            )


if __name__ == "__main__":
    unittest.main()
