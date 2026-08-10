from __future__ import annotations

import unittest
from dataclasses import replace

from dududa.contracts.canonical import canonical_digest
from dududa.errors import DududaError
from dududa.proactive.digests import (
    source_capability_observation_digest,
    source_cursor_digest,
    source_dedup_receipt_digest,
    source_definition_digest,
    source_fetch_receipt_digest,
    source_fetch_request_digest,
    source_item_identity_digest,
    source_policy_snapshot_digest,
    source_provenance_digest,
    source_state_commit_plan_digest,
    source_state_commit_receipt_digest,
    source_state_mutation_digest,
)
from dududa.proactive.source_contracts import (
    SourceFetchStatus,
    SourceStateCommitPlan,
    SourceStateMutation,
)
from dududa.proactive.source_store import InMemorySourcePolicyRegistry

from ._source_fixtures import GovernedSourceFixture


class GovernedSourceContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = GovernedSourceFixture()

    async def test_all_additive_contracts_are_digest_bound_and_tamper_evident(
        self,
    ) -> None:
        fixture = self.fixture
        fetch_receipt = await fixture.provider.fetch(
            fixture.request,
            call=fixture.call(),
        )
        definition = fixture.definitions[0]
        observation = await fixture.reader.read(
            definition,
            None,
            fixture.request,
            call=fixture.call(),
        )
        cursor = fetch_receipt.next_cursors[0]
        identity = fetch_receipt.identities[0]
        mutation = SourceStateMutation(
            schema_version=1,
            subscription_id=fixture.request.subscription_id,
            source_id=definition.source_id,
            expected_cursor_digest=cursor.cursor_digest,
            next_cursor=cursor,
            identities=(identity,),
            notify_revisions=definition.notify_revisions,
            observed_at=cursor.observed_at,
        )
        plan = SourceStateCommitPlan(
            schema_version=1,
            request_digest=fixture.request.request_digest,
            subscription_id=fixture.request.subscription_id,
            mutations=(mutation,),
            planned_at=fixture.now,
        )
        state_receipt = await fixture.state_store.commit_fetch(
            plan,
            call=fixture.call(),
        )

        cases = (
            (definition, source_definition_digest, "definition_digest"),
            (fixture.policy, source_policy_snapshot_digest, "policy_digest"),
            (cursor, source_cursor_digest, "cursor_digest"),
            (
                observation,
                source_capability_observation_digest,
                "observation_digest",
            ),
            (
                fetch_receipt.provenance[0],
                source_provenance_digest,
                "provenance_digest",
            ),
            (identity, source_item_identity_digest, "identity_digest"),
            (fixture.request, source_fetch_request_digest, "request_digest"),
            (
                fetch_receipt.dedup_receipts[0],
                source_dedup_receipt_digest,
                "receipt_digest",
            ),
            (mutation, source_state_mutation_digest, "mutation_digest"),
            (plan, source_state_commit_plan_digest, "plan_digest"),
            (
                state_receipt,
                source_state_commit_receipt_digest,
                "receipt_digest",
            ),
            (fetch_receipt, source_fetch_receipt_digest, "receipt_digest"),
        )
        tampered = canonical_digest(
            {"tampered": True},
            domain="test:source-tamper:v1",
        )
        for value, digest_fn, field_name in cases:
            with self.subTest(contract=type(value).__name__):
                self.assertEqual(getattr(value, field_name), digest_fn(value))
                with self.assertRaises(DududaError) as caught:
                    replace(value, **{field_name: tampered})
                self.assertEqual(
                    caught.exception.info.code,
                    "proactive_contract_digest_mismatch",
                )

    async def test_fetch_receipt_rejects_cross_wired_identity_evidence(self) -> None:
        receipt = await self.fixture.provider.fetch(
            self.fixture.request,
            call=self.fixture.call(),
        )

        with self.assertRaises(DududaError) as caught:
            replace(
                receipt,
                identities=tuple(reversed(receipt.identities)),
                receipt_digest="",
            )

        self.assertEqual(
            caught.exception.info.code,
            "source_fetch_item_evidence_mismatch",
        )

    async def test_fetch_status_shapes_are_mutually_consistent(self) -> None:
        receipt = await self.fixture.provider.fetch(
            self.fixture.request,
            call=self.fixture.call(),
        )

        with self.assertRaises(DududaError):
            replace(
                receipt,
                status=SourceFetchStatus.PARTIAL,
                receipt_digest="",
            )
        with self.assertRaises(DududaError):
            replace(
                receipt,
                status=SourceFetchStatus.NO_NEW_ITEMS,
                receipt_digest="",
            )

    def test_policy_registry_rejects_stale_or_mismatched_snapshot(self) -> None:
        stale = replace(
            self.fixture.policy,
            valid_until=self.fixture.now,
            policy_digest="",
        )
        registry = InMemorySourcePolicyRegistry(
            (stale,),
            clock=self.fixture.clock,
        )

        with self.assertRaises(DududaError) as caught:
            registry.resolve(stale.policy_id, expected_digest=stale.policy_digest)
        self.assertEqual(
            caught.exception.info.code,
            "source_policy_snapshot_stale",
        )

        with self.assertRaises(DududaError) as caught:
            self.fixture.registry.resolve(
                self.fixture.policy.policy_id,
                expected_digest=canonical_digest(
                    {"policy": "other"},
                    domain="test:source-policy:v1",
                ),
            )
        self.assertEqual(
            caught.exception.info.code,
            "source_policy_digest_mismatch",
        )


if __name__ == "__main__":
    unittest.main()
