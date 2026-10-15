from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from dududa.capabilities.authorization import (
    CapabilityAuthorizationPurpose,
    build_capability_authorization_request,
    capability_authorization_allows,
)
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ConversationType,
    RoleId,
    RuntimeBudget,
    TraceContext,
)
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)

from tests.unit.capabilities.test_contracts import NOW
from tests.unit.capabilities.test_registry import catalog_fixture


class CapabilityAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_permission_is_bound_to_exact_capability_scope_and_catalog(
        self,
    ) -> None:
        catalog, definition, _ = catalog_fixture()
        actor = Actor("qq", "bot", "user", frozenset({RoleId("member")}))
        scope = ConversationScope(
            "qq",
            "bot",
            ConversationType.GROUP,
            "group",
            "group",
            "dududa",
        )
        permission = next(iter(definition.required_permissions))
        request = build_capability_authorization_request(
            definition,
            actor,
            scope,
            catalog,
            permission=permission,
            purpose=CapabilityAuthorizationPurpose.RETRIEVAL,
            policy_snapshot_id="policy-v1",
        )
        self.assertEqual(request.resource.resource_type, "capability")
        self.assertEqual(request.resource.resource_id, definition.capability_id)
        self.assertEqual(request.capability_id, definition.capability_id)
        self.assertEqual(request.action, permission)
        self.assertEqual(request.metadata["catalog_snapshot_id"], catalog.snapshot_id)

        constraint = AuthorizationConstraint(
            resource_types=frozenset({"capability"}),
            resource_ids=frozenset({definition.capability_id}),
            capability_ids=frozenset({definition.capability_id}),
            allow_without_capability=False,
        )
        policy = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                policy_revision="policy-v1",
                role_permissions={"member": frozenset({permission})},
                role_constraints={"member": {permission: constraint}},
            ),
            clock=lambda: NOW,
            id_factory=lambda: "decision-one",
        )
        decision = await policy.decide(
            request,
            call=PortCallContext(
                run_id="authorization-run",
                trace=TraceContext("authorization-trace"),
                deadline=NOW + timedelta(minutes=1),
                cancellation=NeverCancelled(),
                budget=RuntimeBudget(0, 1, 0, 0, 0, Decimal(1)),
                policy_snapshot_id="policy-v1",
            ),
        )
        self.assertTrue(
            capability_authorization_allows(
                request,
                decision,
                policy,
                at=NOW,
                expected_policy_revision="policy-v1",
            )
        )
        self.assertFalse(
            capability_authorization_allows(
                request,
                replace(decision, policy_revision="policy-drift"),
                policy,
                at=NOW,
                expected_policy_revision="policy-v1",
            )
        )


if __name__ == "__main__":
    unittest.main()
