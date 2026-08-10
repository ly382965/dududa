from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.contracts.canonical import canonical_digest
from dududa.domain.content import (
    ContentSafetyDecision,
    FinalResponse,
    RenderedBlock,
    RenderedContent,
    RenderMetadata,
    RenderValidationResult,
    SafetyStage,
    ValidatedFinalResponse,
)
from dududa.domain.primitives import (
    ComponentRevision,
    ResponseConstraints,
)
from dududa.errors import DududaError
from dududa.proactive.contracts import (
    DispatchClaim,
    PreparedDispatch,
    ProactivePolicyDecision,
)
from dududa.proactive.digests import (
    dispatch_claim_digest,
    initiated_run_request_digest,
    prepared_dispatch_digest,
    proactive_authorization_grant_digest,
    proactive_delivery_idempotency_key,
    proactive_policy_decision_digest,
    proactive_preview_request_digest,
    proactive_subscription_digest,
    proactive_target_policy_digest,
    proactive_trigger_digest,
    schedule_occurrence_digest,
)
from dududa.responses.contracts import AnswerProfile
from dududa.security.digests import actor_digest, scope_digest

from ._fixtures import ProactiveFixture


def _revision(name: str, config_revision: str = "cfg-v1") -> ComponentRevision:
    return ComponentRevision(
        name,
        "1.0.0",
        config_revision,
        canonical_digest(name, domain="test:proactive-artifact:v1"),
    )


def _response(fixture: ProactiveFixture) -> ValidatedFinalResponse:
    producer = _revision("response-fixture")
    response_plan_digest = canonical_digest(
        {"profile": "medium"},
        domain="test:proactive-response-plan:v1",
    )
    draft_digest = canonical_digest(
        {"draft": 1},
        domain="test:proactive-draft:v1",
    )
    response = FinalResponse(
        1,
        "response-1",
        producer,
        (RenderedBlock("block-1", RenderedContent("text", text="A notice.")),),
        (),
        (),
        (),
        (),
        None,
        ResponseConstraints(),
        (),
        (),
        RenderMetadata(
            "dududa",
            "1",
            producer,
            draft_digest,
            response_plan_digest=response_plan_digest,
        ),
    )
    rendered_digest = canonical_digest(response, domain="response:final:v1")
    validation = RenderValidationResult(
        1,
        True,
        draft_digest,
        rendered_digest,
        (),
        (),
        producer,
    )
    safety = ContentSafetyDecision(
        1,
        "safety-1",
        SafetyStage.FINAL_OUTPUT,
        canonical_digest({}, domain="test:proactive-safety-request:v1"),
        rendered_digest,
        actor_digest(fixture.actor),
        scope_digest(fixture.scope),
        True,
        ResponseConstraints(),
        (),
        "safety-v1",
        producer,
        fixture.now,
    )
    return ValidatedFinalResponse(1, response, validation, safety)


def _binding(config_revision: str) -> NegotiatedBindingReceipt:
    return NegotiatedBindingReceipt(
        1,
        "proactive-output-adapter",
        "1.0.0",
        {
            "deliver": (
                canonical_digest("input", domain="test:proactive-schema:v1"),
                canonical_digest("output", domain="test:proactive-schema:v1"),
            )
        },
        frozenset({"text"}),
        _revision("fake-proactive-output", config_revision),
        ProactiveFixture().now,
    )


def _prepared_dispatch(
    fixture: ProactiveFixture,
    *,
    adapter_revision: str,
) -> PreparedDispatch:
    response = _response(fixture)
    response_digest = canonical_digest(response.response, domain="response:final:v1")
    response_plan_digest = response.response.render_metadata.response_plan_digest
    assert response_plan_digest is not None
    decision = ProactivePolicyDecision(
        1,
        "policy-decision-1",
        fixture.trigger.trigger_digest,
        fixture.policy.as_ref(),
        True,
        scope_digest(fixture.scope),
        AnswerProfile.MEDIUM,
        10,
        fixture.authorization_decision_digest,
        "quota-lease-1",
        ("allowed",),
        "proactive-policy-v1",
        fixture.now,
        fixture.now + timedelta(hours=1),
    )
    item_set_digest = canonical_digest(
        {"items": ("notice-1",)},
        domain="test:proactive-item-set:v1",
    )
    key = proactive_delivery_idempotency_key(
        trigger_kind=fixture.trigger.kind,
        trigger_source_digest=fixture.trigger.source_digest,
        target_scope=fixture.scope,
        item_set_digest=item_set_digest,
        validated_response_digest=response_digest,
    )
    return PreparedDispatch(
        1,
        "dispatch-1",
        fixture.trigger.kind,
        fixture.trigger.trigger_digest,
        fixture.trigger.source_digest,
        fixture.policy.as_ref(),
        decision.decision_digest,
        canonical_digest({}, domain="test:proactive-source-batch:v1"),
        item_set_digest,
        response_plan_digest,
        response_digest,
        response,
        fixture.scope,
        key,
        _binding(adapter_revision),
        fixture.now,
        fixture.now + timedelta(hours=1),
    )


class ProactiveDigestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProactiveFixture()

    def test_all_primary_contracts_use_self_excluding_named_digests(self) -> None:
        fixture = self.fixture

        self.assertEqual(
            fixture.operator_grant.grant_digest,
            proactive_authorization_grant_digest(fixture.operator_grant),
        )
        self.assertEqual(
            fixture.policy.target_policy_digest,
            proactive_target_policy_digest(fixture.policy),
        )
        self.assertEqual(
            fixture.subscription.subscription_digest,
            proactive_subscription_digest(fixture.subscription),
        )
        self.assertEqual(
            fixture.occurrence.occurrence_digest,
            schedule_occurrence_digest(fixture.occurrence),
        )
        self.assertEqual(
            fixture.trigger.trigger_digest,
            proactive_trigger_digest(fixture.trigger),
        )
        self.assertEqual(
            fixture.run.start_digest,
            initiated_run_request_digest(fixture.run),
        )
        self.assertEqual(
            fixture.preview.request_digest,
            proactive_preview_request_digest(fixture.preview),
        )

    def test_mapping_projection_excludes_only_the_declared_digest_field(self) -> None:
        trigger = self.fixture.trigger
        values = {
            field: getattr(trigger, field) for field in trigger.__dataclass_fields__
        }
        values["trigger_digest"] = "ignored-caller-value"

        self.assertEqual(proactive_trigger_digest(values), trigger.trigger_digest)
        values["trigger_id"] = "trigger-2"
        self.assertNotEqual(proactive_trigger_digest(values), trigger.trigger_digest)

    def test_occurrence_date_projection_has_a_fixed_golden_digest(self) -> None:
        self.assertEqual(
            self.fixture.occurrence.occurrence_digest,
            "dududa-c14n-v1:proactive:schedule-occurrence:v1:sha-256:"
            "fe5f5f1e1ab985512c9801daa9210081f1475ba85faabfc11a520c0aa4f8e0bb",
        )

    def test_delivery_key_excludes_adapter_worker_attempt_and_wall_clock(self) -> None:
        fixture = self.fixture
        dispatch_v1 = _prepared_dispatch(fixture, adapter_revision="adapter-v1")
        dispatch_v2 = replace(
            dispatch_v1,
            adapter_binding=_binding("adapter-v2"),
            prepared_at=dispatch_v1.prepared_at + timedelta(seconds=30),
            expires_at=dispatch_v1.expires_at + timedelta(seconds=30),
            prepared_dispatch_digest="",
        )
        claim_v1 = DispatchClaim(
            1,
            "claim-1",
            dispatch_v1.dispatch_id,
            dispatch_v1.prepared_dispatch_digest,
            "worker-1",
            1,
            fixture.now,
            fixture.now + timedelta(minutes=1),
        )
        claim_v2 = replace(
            claim_v1,
            claim_id="claim-2",
            worker_id="worker-2",
            lease_revision=2,
            claim_digest="",
        )

        self.assertEqual(dispatch_v1.idempotency_key, dispatch_v2.idempotency_key)
        self.assertNotEqual(
            prepared_dispatch_digest(dispatch_v1),
            prepared_dispatch_digest(dispatch_v2),
        )
        self.assertNotEqual(
            dispatch_claim_digest(claim_v1), dispatch_claim_digest(claim_v2)
        )

    def test_delivery_key_changes_for_each_business_identity_input(self) -> None:
        fixture = self.fixture
        response_digest = canonical_digest(
            {"response": 1},
            domain="test:proactive-validated-response:v1",
        )
        item_set_digest = canonical_digest(
            {"items": 1},
            domain="test:proactive-item-set:v1",
        )
        base = proactive_delivery_idempotency_key(
            trigger_kind=fixture.trigger.kind,
            trigger_source_digest=fixture.trigger.source_digest,
            target_scope=fixture.scope,
            item_set_digest=item_set_digest,
            validated_response_digest=response_digest,
        )

        changes = (
            {
                "trigger_source_digest": canonical_digest(
                    {"occurrence": 2},
                    domain="test:proactive-occurrence:v1",
                )
            },
            {"item_set_digest": None},
            {
                "validated_response_digest": canonical_digest(
                    {"response": 2},
                    domain="test:proactive-validated-response:v1",
                )
            },
        )
        common = {
            "trigger_kind": fixture.trigger.kind,
            "trigger_source_digest": fixture.trigger.source_digest,
            "target_scope": fixture.scope,
            "item_set_digest": item_set_digest,
            "validated_response_digest": response_digest,
        }
        for changed in changes:
            with self.subTest(changed=tuple(changed)):
                self.assertNotEqual(
                    base,
                    proactive_delivery_idempotency_key(**(common | changed)),
                )

    def test_supplied_tampered_digest_is_not_silently_resealed(self) -> None:
        with self.assertRaises(DududaError) as caught:
            replace(
                self.fixture.policy,
                target_policy_digest=canonical_digest(
                    {"tampered": True},
                    domain="test:proactive-tamper:v1",
                ),
            )
        self.assertEqual(
            caught.exception.info.code,
            "proactive_contract_digest_mismatch",
        )

    def test_prepared_dispatch_digest_binds_adapter_evidence_separately(self) -> None:
        dispatch = _prepared_dispatch(self.fixture, adapter_revision="adapter-v1")
        decision_digest = proactive_policy_decision_digest(
            ProactivePolicyDecision(
                1,
                "policy-decision-2",
                self.fixture.trigger.trigger_digest,
                self.fixture.policy.as_ref(),
                False,
                scope_digest(self.fixture.scope),
                AnswerProfile.MEDIUM,
                0,
                self.fixture.authorization_decision_digest,
                None,
                ("denied",),
                "proactive-policy-v1",
                self.fixture.now,
                self.fixture.now + timedelta(minutes=1),
            )
        )

        self.assertEqual(
            dispatch.prepared_dispatch_digest,
            prepared_dispatch_digest(dispatch),
        )
        self.assertNotEqual(dispatch.policy_decision_digest, decision_digest)


if __name__ == "__main__":
    unittest.main()
