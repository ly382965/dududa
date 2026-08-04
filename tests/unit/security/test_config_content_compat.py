from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.config import parse_security_config
from dududa.domain.content import SafetyStage
from dududa.domain.primitives import DigestString, RuntimeBudget, TraceContext
from dududa.errors import DududaError, ErrorCategory, error
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.security.authorization import LegacyActorInput, LegacyRolePolicy
from dududa.security.content_safety import DefaultContentSafetyPolicy
from dududa.security.digests import (
    content_safety_content_digest,
    content_safety_request_digest,
)
from dududa.security.models import ContentSafetyRequest


class ConfigContentCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_security_config_is_strict_and_immutable(self) -> None:
        config = parse_security_config(
            {
                "schema_version": 1,
                "policy_revision": "policy-v1",
                "role_permissions": {"owner": ["*"]},
                "role_constraints": {
                    "owner": {
                        "*": {
                            "resource_types": ["*"],
                            "resource_ids": ["*"],
                            "capability_ids": ["*"],
                        }
                    }
                },
                "interaction_limits": {"chat.reply": 3},
            }
        )
        self.assertEqual(config.interaction_limits["chat.reply"], 3)
        with self.assertRaises(TypeError):
            config.interaction_limits["chat.reply"] = 4  # type: ignore[index]
        for invalid in (
            {"schema_version": True, "policy_revision": "x", "role_permissions": {}},
            {
                "schema_version": 1,
                "policy_revision": "x",
                "role_permissions": {"owner": ["*"]},
            },
            {
                "schema_version": 1,
                "policy_revision": "x",
                "role_permissions": {},
                "unknown": 1,
            },
        ):
            with self.assertRaises(DududaError):
                parse_security_config(invalid)

    def test_legacy_role_priority_is_preserved(self) -> None:
        policy = LegacyRolePolicy(
            owners=frozenset({"owner"}),
            global_admins=frozenset({"admin"}),
            trusted_users=frozenset({"trusted", "muted"}),
            muted_users=frozenset({"muted"}),
            group_admins={"g-1": frozenset({"group-admin"})},
        )
        self.assertEqual(
            policy.resolve(LegacyActorInput("muted", "g-1", True)), "muted_user"
        )
        self.assertEqual(policy.resolve(LegacyActorInput("owner", "", False)), "owner")
        self.assertEqual(
            policy.resolve(LegacyActorInput("group-admin", "g-1", False)), "admin"
        )
        self.assertEqual(
            policy.resolve(LegacyActorInput("normal", "g-1", False)), "normal_user"
        )

    async def test_content_safety_binds_stage_content_and_request(self) -> None:
        now = datetime.now(timezone.utc)
        call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            now + timedelta(minutes=1),
            NeverCancelled(),
            RuntimeBudget(1, 0, 0, 100, 100, Decimal(1)),
            "policy-v1",
        )
        content = {"text": "safe response"}
        request = ContentSafetyRequest(
            1,
            "safety-1",
            DigestString("pending"),
            SafetyStage.FINAL_OUTPUT,
            content,
            content_safety_content_digest(content, SafetyStage.FINAL_OUTPUT),
            DigestString("actor"),
            DigestString("scope"),
        )
        request = replace(
            request, request_digest=content_safety_request_digest(request)
        )
        policy = DefaultContentSafetyPolicy()
        decision = await policy.evaluate(request, call=call)
        self.assertTrue(decision.allowed)
        with self.assertRaises(DududaError):
            await policy.evaluate(
                replace(request, content={"text": "changed"}), call=call
            )

    def test_public_error_never_exposes_private_detail(self) -> None:
        caught = error(
            "provider_failed",
            ErrorCategory.EXTERNAL,
            "provider.unavailable",
            detail="Bearer secret /home/private/config.json",
        )
        self.assertEqual(str(caught), "provider.unavailable")
        self.assertNotIn("secret", repr(caught))


if __name__ == "__main__":
    unittest.main()
