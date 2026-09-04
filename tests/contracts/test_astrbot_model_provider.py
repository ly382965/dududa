from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from dududa.contracts.canonical import canonical_schema_digest
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    PrivacyLevel,
    SchemaRef,
)
from dududa.models.contracts import (
    ModelFailureKind,
    ModelRetentionMode,
    ModelRole,
    ReasoningDepth,
    ReasoningProfile,
    RouteAttemptKind,
)
from dududa.models.digests import model_endpoint_descriptor_digest
from dududa.models.errors import ModelProviderError
from astrbot_plugin_dududa_core.adapters.model import (
    AstrBotModelProviderAdapter,
    AstrBotPromptArtifact,
    AstrBotProviderBindingEvidence,
    astrbot_prompt_artifact_digest,
    reasoning_effort_for_model,
)
from astrbot_plugin_dududa_core.adapters.model_codec import (
    JsonSchemaDocumentRegistry,
)

from tests.unit.models.helpers import NOW, revision

from .model_provider_conformance import (
    ModelProviderConformanceMixin,
    ProviderConformanceFixture,
)
from .model_provider_fixtures import (
    compatible_descriptor,
    compatible_provider_request,
    provider_call,
)


STRUCTURED_OUTPUT_INSTRUCTION = "Return exactly one JSON document matching this schema."
REPAIR_INSTRUCTION = (
    "The previous result failed schema validation. Produce a fresh valid document only."
)
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}
OUTPUT_SCHEMA_REF = SchemaRef(
    schema_id="astrbot-contract-output",
    schema_version=1,
    digest=canonical_schema_digest(
        OUTPUT_SCHEMA,
        schema_id="astrbot-contract-output",
        schema_version=1,
    ),
)


class _AstrBotProvider:
    def __init__(self, outcome=None) -> None:
        self.calls: list[dict[str, object]] = []
        self.outcome = outcome or SimpleNamespace(
            completion_text="ok",
            usage=SimpleNamespace(input_other=10, input_cached=2, output=5),
        )

    def meta(self):
        return SimpleNamespace(id="astrbot-provider-1")

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _RaisingResponse:
    def __init__(self, field: str, secret: str) -> None:
        self._field = field
        self._secret = secret

    @property
    def completion_text(self):
        if self._field == "completion_text":
            raise RuntimeError(self._secret)
        return "ok"

    @property
    def usage(self):
        if self._field == "usage":
            raise RuntimeError(self._secret)
        return _RaisingUsage(self._secret)


class _RaisingUsage:
    def __init__(self, secret: str) -> None:
        self._secret = secret

    @property
    def input_other(self):
        raise RuntimeError(self._secret)

    input_cached = 0
    output = 1


class _RaisingMetadataError(RuntimeError):
    @property
    def status_code(self):
        raise RuntimeError(str(self))

    @property
    def status(self):
        raise RuntimeError(str(self))

    @property
    def response(self):
        raise RuntimeError(str(self))

    @property
    def code(self):
        raise RuntimeError(str(self))


class _RaisingTextChatProvider:
    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.calls = []

    def meta(self):
        return SimpleNamespace(id="astrbot-provider-1")

    @property
    def text_chat(self):
        raise RuntimeError(self.secret)


class _StubbornThenSuccessProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.release = asyncio.Event()
        self.finished = asyncio.Event()

    def meta(self):
        return SimpleNamespace(id="astrbot-provider-1")

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            try:
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        continue
            finally:
                self.finished.set()
        return SimpleNamespace(
            completion_text="ok",
            usage=SimpleNamespace(input_other=1, input_cached=0, output=1),
        )


class _BrokenCancellation:
    @property
    def is_cancelled(self):
        return False

    def wait(self):
        raise RuntimeError("cancellation watcher secret")


def _prompt_artifact(*, repair: bool = False) -> AstrBotPromptArtifact:
    role = ModelRole.DIRECT_CHAT
    repair_instruction = REPAIR_INSTRUCTION if repair else None
    digest = astrbot_prompt_artifact_digest(
        role=role,
        schema_repair=repair,
        system_prompt="system prompt",
        structured_output_instruction=STRUCTURED_OUTPUT_INSTRUCTION,
        repair_instruction=repair_instruction,
    )
    return AstrBotPromptArtifact(
        schema_version=1,
        role=role,
        schema_repair=repair,
        system_prompt="system prompt",
        structured_output_instruction=STRUCTURED_OUTPUT_INSTRUCTION,
        repair_instruction=repair_instruction,
        revision=ComponentRevision(
            component_id=(
                "astrbot-direct-chat-repair-prompt"
                if repair
                else "astrbot-direct-chat-prompt"
            ),
            implementation_version="1",
            config_revision="test-v1",
            artifact_digest=digest,
        ),
    )


def _request(descriptor):
    return replace(
        compatible_provider_request(descriptor),
        prompt_template_revision=_prompt_artifact().revision,
    )


def _evidence(descriptor, **changes) -> AstrBotProviderBindingEvidence:
    endpoint = descriptor.endpoints[0]
    values = {
        "schema_version": 1,
        "astrbot_provider_id": "astrbot-provider-1",
        "host_version": "conformance-harness-1",
        "conformance_revision": revision("astrbot-host-conformance"),
        "verified_model_id": endpoint.model_id,
        "verified_max_output_tokens": endpoint.capabilities.max_output_tokens,
        "verified_data_residencies": endpoint.available_data_residencies,
        "verified_retention_modes": endpoint.supported_retention_modes,
        "single_request_verified": True,
        "model_binding_verified": True,
        "output_limit_verified": True,
        "residency_verified": True,
        "retention_verified": True,
        "sanitized_logging_verified": True,
        "deadline_enforcement_verified": True,
        "cancellation_enforcement_verified": True,
    }
    values.update(changes)
    return AstrBotProviderBindingEvidence(**values)


def _adapter(
    raw: object,
    *,
    descriptor=None,
    evidence=None,
    schema_documents=None,
    prompt_artifacts=None,
    clock=None,
    idempotency_capacity=1_024,
    idempotency_ttl_seconds=600,
):
    descriptor = descriptor or compatible_descriptor()
    return (
        AstrBotModelProviderAdapter(
            raw,
            descriptor,
            evidence or _evidence(descriptor),
            schema_registry=JsonSchemaDocumentRegistry(schema_documents or {}),
            prompt_artifacts=prompt_artifacts or (_prompt_artifact(),),
            clock=clock or (lambda: NOW),
            idempotency_capacity=idempotency_capacity,
            idempotency_ttl_seconds=idempotency_ttl_seconds,
        ),
        descriptor,
    )


class AstrBotModelProviderContractTests(
    ModelProviderConformanceMixin,
    unittest.IsolatedAsyncioTestCase,
):
    def make_provider_fixture(self) -> ProviderConformanceFixture:
        raw = _AstrBotProvider()
        adapter, descriptor = _adapter(raw)
        return ProviderConformanceFixture(
            provider=adapter,
            request=_request(descriptor),
            call=provider_call(),
            underlying_call_count=lambda: len(raw.calls),
        )

    async def test_astrbot_kwargs_usage_and_local_idempotency(self) -> None:
        raw = _AstrBotProvider()
        adapter, descriptor = _adapter(raw)
        request = _request(descriptor)
        first = await adapter.generate(request, call=provider_call())
        duplicate = await adapter.generate(request, call=provider_call())
        self.assertEqual(first, duplicate)
        self.assertEqual(len(raw.calls), 1)
        self.assertEqual(
            raw.calls[0],
            {
                "prompt": "[DUDUDA_USER_INPUT]\nhello\n[/DUDUDA_USER_INPUT]",
                "system_prompt": "system prompt",
                "model": "provider-native-sonnet",
                "max_tokens": 128,
                "request_max_retries": 1,
            },
        )
        self.assertEqual(first.usage.input_tokens, 12)  # type: ignore[union-attr]
        self.assertEqual(first.usage.cached_input_tokens, 2)  # type: ignore[union-attr]
        self.assertEqual(first.usage.generated_tokens, 5)  # type: ignore[union-attr]

    async def test_declared_reasoning_profiles_reach_public_text_chat(self) -> None:
        raw = _AstrBotProvider()
        descriptor = compatible_descriptor()
        profiles = tuple(
            ReasoningProfile(
                schema_version=1,
                profile_id=f"provider-{depth.value}",
                depth=depth,
                max_reasoning_tokens=None,
                required=False,
            )
            for depth in (
                ReasoningDepth.LIGHT,
                ReasoningDepth.BALANCED,
                ReasoningDepth.DEEP,
                ReasoningDepth.MAXIMUM,
            )
        )
        endpoint = replace(
            descriptor.endpoints[0],
            descriptor_digest=DigestString("pending"),
            reasoning_profiles=profiles,
            default_reasoning_profile_id=profiles[0].profile_id,
        )
        endpoint = replace(
            endpoint,
            descriptor_digest=model_endpoint_descriptor_digest(endpoint),
        )
        descriptor = replace(descriptor, endpoints=(endpoint,))
        adapter, _ = _adapter(raw, descriptor=descriptor)
        request = _request(descriptor)

        for index, (profile, expected_effort) in enumerate(
            zip(profiles, ("low", "medium", "high", "xhigh"), strict=True)
        ):
            await adapter.generate(
                replace(
                    request,
                    request_id=f"reasoning-request-{index}",
                    idempotency_key=f"reasoning-key-{index}",
                    reasoning_profile=profile,
                ),
                call=provider_call(),
            )
            self.assertEqual(raw.calls[-1]["reasoning_effort"], expected_effort)

        self.assertEqual(len(raw.calls), 4)

    def test_deepseek_effort_mapping_preserves_gpt_maximum(self) -> None:
        for model in ("deepseek-v4-flash", "deepseek-v4-pro"):
            self.assertEqual(reasoning_effort_for_model(model, ReasoningDepth.LIGHT), "low")
            self.assertEqual(reasoning_effort_for_model(model, ReasoningDepth.BALANCED), "high")
            self.assertEqual(reasoning_effort_for_model(model, ReasoningDepth.DEEP), "high")
            self.assertEqual(reasoning_effort_for_model(model, ReasoningDepth.MAXIMUM), "max")
            self.assertIsNone(reasoning_effort_for_model(model, ReasoningDepth.OFF))
        self.assertEqual(reasoning_effort_for_model("gpt-5.6-sol", ReasoningDepth.MAXIMUM), "xhigh")

    async def test_deepseek_health_uses_bounded_non_thinking_probe(self) -> None:
        raw = _AstrBotProvider()
        descriptor = compatible_descriptor()
        endpoint = replace(descriptor.endpoints[0], model_id="deepseek-v4-pro", descriptor_digest=DigestString("pending"))
        endpoint = replace(endpoint, descriptor_digest=model_endpoint_descriptor_digest(endpoint))
        adapter, _ = _adapter(raw, descriptor=replace(descriptor, endpoints=(endpoint,)))
        await adapter.probe_health(timeout_seconds=2, evidence_ttl=timedelta(minutes=5))
        self.assertEqual(raw.calls[0]["thinking"], {"type": "disabled"})
        self.assertEqual(raw.calls[0]["max_tokens"], 256)
        self.assertEqual(raw.calls[0]["request_max_retries"], 1)

    async def test_unknown_outcome_creates_idempotency_tombstone(self) -> None:
        raw = _StubbornThenSuccessProvider()
        adapter, descriptor = _adapter(
            raw,
            clock=lambda: datetime.now(timezone.utc),
        )
        request = _request(descriptor)
        first_call = replace(
            provider_call(),
            deadline=datetime.now(timezone.utc) + timedelta(milliseconds=30),
        )
        try:
            with self.assertRaises(ModelProviderError) as first:
                await adapter.generate(request, call=first_call)
            self.assertEqual(first.exception.failure_kind, ModelFailureKind.TIMEOUT)
            self.assertTrue(first.exception.info.outcome_unknown)

            replay_call = replace(
                provider_call(),
                deadline=datetime.now(timezone.utc) + timedelta(seconds=1),
            )
            with self.assertRaises(ModelProviderError) as replay:
                await adapter.generate(request, call=replay_call)
            self.assertEqual(replay.exception.info, first.exception.info)
            self.assertEqual(len(raw.calls), 1)
        finally:
            raw.release.set()
            await asyncio.wait_for(raw.finished.wait(), timeout=1)

    async def test_idempotency_ledger_is_bounded_expires_and_clears(self) -> None:
        now = [NOW]
        raw = _AstrBotProvider()
        adapter, descriptor = _adapter(
            raw,
            clock=lambda: now[0],
            idempotency_capacity=2,
            idempotency_ttl_seconds=1,
        )
        base = _request(descriptor)
        requests = tuple(
            replace(
                base,
                request_id=f"bounded-request-{index}",
                idempotency_key=f"bounded-key-{index}",
            )
            for index in range(3)
        )
        for request in requests:
            await adapter.generate(request, call=provider_call())

        self.assertEqual(len(raw.calls), 3)
        self.assertEqual(len(adapter._idempotency_results), 2)
        self.assertNotIn("bounded-key-0", adapter._idempotency_results)
        self.assertEqual(len(adapter._idempotency_locks), 64)

        now[0] = NOW + timedelta(seconds=2)
        await adapter.generate(requests[1], call=provider_call())
        self.assertEqual(len(raw.calls), 4)
        await adapter.close()
        self.assertEqual(adapter._idempotency_results, {})

    async def test_cancellation_watcher_start_failure_is_sanitized(self) -> None:
        raw = _AstrBotProvider()
        adapter, descriptor = _adapter(raw)
        broken_call = replace(
            provider_call(),
            cancellation=_BrokenCancellation(),
        )

        with self.assertRaises(ModelProviderError) as captured:
            await adapter.generate(
                replace(_request(descriptor), idempotency_key=None),
                call=broken_call,
            )

        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.INTERNAL)
        self.assertTrue(captured.exception.info.outcome_unknown)
        self.assertNotIn("cancellation watcher secret", repr(captured.exception))
        self.assertIsNone(captured.exception.__context__)

    def test_unverified_binding_cannot_construct_adapter(self) -> None:
        raw = _AstrBotProvider()
        descriptor = compatible_descriptor()
        for flag in (
            "single_request_verified",
            "deadline_enforcement_verified",
            "cancellation_enforcement_verified",
        ):
            with self.subTest(flag=flag), self.assertRaises(Exception):
                AstrBotModelProviderAdapter(
                    raw,
                    descriptor,
                    _evidence(descriptor, **{flag: False}),
                    schema_registry=JsonSchemaDocumentRegistry({}),
                    prompt_artifacts=(_prompt_artifact(),),
                )

    def test_binding_evidence_is_exactly_scoped_to_descriptor(self) -> None:
        descriptor = compatible_descriptor()
        mismatches = (
            {"verified_model_id": "other-model"},
            {"verified_max_output_tokens": 999},
            {"verified_data_residencies": frozenset({"eu"})},
            {
                "verified_retention_modes": frozenset(
                    {ModelRetentionMode.PROVIDER_MANAGED}
                )
            },
        )
        for changes in mismatches:
            with self.subTest(changes=changes), self.assertRaises(Exception):
                _adapter(
                    _AstrBotProvider(),
                    descriptor=descriptor,
                    evidence=_evidence(descriptor, **changes),
                )

    def test_schema_repair_request_requires_schema(self) -> None:
        descriptor = compatible_descriptor()
        with self.assertRaises(Exception):
            replace(
                _request(descriptor),
                attempt=2,
                attempt_kind=RouteAttemptKind.SCHEMA_REPAIR,
            )

    async def test_schema_and_repair_prompts_bind_exact_artifacts(self) -> None:
        raw = _AstrBotProvider()
        primary = _prompt_artifact()
        repair = _prompt_artifact(repair=True)
        adapter, descriptor = _adapter(
            raw,
            schema_documents={OUTPUT_SCHEMA_REF: OUTPUT_SCHEMA},
            prompt_artifacts=(primary, repair),
        )
        request = replace(
            _request(descriptor),
            output_schema=OUTPUT_SCHEMA_REF,
            prompt_template_revision=primary.revision,
            idempotency_key="schema-primary",
        )
        await adapter.generate(request, call=provider_call())
        await adapter.generate(
            replace(
                request,
                request_id="provider-request-repair",
                attempt=2,
                attempt_kind=RouteAttemptKind.SCHEMA_REPAIR,
                prompt_template_revision=repair.revision,
                idempotency_key="schema-repair",
            ),
            call=provider_call(),
        )

        encoded_schema = (
            '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
            '"additionalProperties":false,"properties":{"answer":{"type":"string"}},'
            '"required":["answer"],"type":"object"}'
        )
        self.assertEqual(len(raw.calls), 2)
        self.assertIn(STRUCTURED_OUTPUT_INSTRUCTION, raw.calls[0]["prompt"])
        self.assertIn(encoded_schema, raw.calls[0]["prompt"])
        self.assertNotIn(REPAIR_INSTRUCTION, raw.calls[0]["prompt"])
        self.assertIn(encoded_schema, raw.calls[1]["prompt"])
        self.assertEqual(raw.calls[1]["prompt"].count(REPAIR_INSTRUCTION), 1)

    async def test_unknown_prompt_and_schema_fail_before_host_call(self) -> None:
        raw = _AstrBotProvider()
        primary = _prompt_artifact()
        adapter, descriptor = _adapter(raw, prompt_artifacts=(primary,))
        request = _request(descriptor)
        unknown_revision = replace(
            primary.revision,
            component_id="unknown-prompt",
            artifact_digest=DigestString("unknown-artifact"),
        )
        with self.assertRaises(ModelProviderError) as unknown:
            await adapter.generate(
                replace(request, prompt_template_revision=unknown_revision),
                call=provider_call(),
            )
        self.assertEqual(
            unknown.exception.failure_kind, ModelFailureKind.INVALID_REQUEST
        )

        with self.assertRaises(ModelProviderError) as missing_schema:
            await adapter.generate(
                replace(
                    request,
                    output_schema=OUTPUT_SCHEMA_REF,
                    prompt_template_revision=primary.revision,
                ),
                call=provider_call(),
            )
        self.assertEqual(
            missing_schema.exception.failure_kind,
            ModelFailureKind.INVALID_REQUEST,
        )
        self.assertEqual(raw.calls, [])

    async def test_request_privacy_and_output_gates_repeat_at_adapter(self) -> None:
        raw = _AstrBotProvider()
        adapter, descriptor = _adapter(raw)
        request = _request(descriptor)
        invalid_requests = (
            replace(
                request,
                privacy=replace(request.privacy, allow_external_provider=False),
            ),
            replace(
                request,
                privacy=replace(
                    request.privacy,
                    data_classification=PrivacyLevel.SENSITIVE,
                ),
            ),
            replace(request, max_output_tokens=1_001),
            replace(
                request,
                selected_data_residency="eu",
                privacy=replace(
                    request.privacy,
                    allowed_residencies=frozenset({"global", "eu"}),
                ),
            ),
            replace(
                request,
                required_retention_mode=ModelRetentionMode.PROVIDER_MANAGED,
                privacy=replace(request.privacy, allow_provider_retention=True),
            ),
        )
        for invalid in invalid_requests:
            with self.subTest(request=invalid), self.assertRaises(ModelProviderError):
                await adapter.generate(invalid, call=provider_call())
        self.assertEqual(raw.calls, [])

    async def test_structured_status_errors_are_sanitized(self) -> None:
        secrets = (
            "https://provider.invalid/v1/chat?api_key=query-secret",
            "Authorization: Bearer header-secret",
            "/private/provider/path-secret.json",
            "prompt-secret-user-content",
            '{"error":{"message":"provider-body-secret"}}',
        )
        failure = RuntimeError("\n".join(secrets))
        failure.status_code = 429  # type: ignore[attr-defined]
        raw = _AstrBotProvider(failure)
        adapter, descriptor = _adapter(raw)
        with self.assertRaises(ModelProviderError) as captured:
            await adapter.generate(
                replace(
                    _request(descriptor),
                    idempotency_key=None,
                ),
                call=provider_call(),
            )
        self.assertEqual(captured.exception.failure_kind, ModelFailureKind.RATE_LIMITED)
        self.assertIsNone(captured.exception.detail)
        self.assertIsNone(captured.exception.__context__)
        self.assertIsNone(captured.exception.__cause__)
        public_surfaces = (
            str(captured.exception),
            repr(captured.exception),
            repr(captured.exception.info),
        )
        for secret in secrets:
            for surface in public_surfaces:
                self.assertNotIn(secret, surface)

    async def test_external_property_failures_are_sanitized_without_exception_chain(
        self,
    ) -> None:
        secret = "https://provider.invalid/v1?token=property-secret"
        cases = (
            _AstrBotProvider(_RaisingMetadataError(secret)),
            _AstrBotProvider(_RaisingResponse("completion_text", secret)),
            _AstrBotProvider(_RaisingResponse("usage", secret)),
            _AstrBotProvider(_RaisingResponse("usage_fields", secret)),
            _RaisingTextChatProvider(secret),
        )
        for raw in cases:
            with self.subTest(raw=type(raw).__name__):
                adapter, descriptor = _adapter(raw)
                with self.assertRaises(ModelProviderError) as captured:
                    await adapter.generate(
                        replace(_request(descriptor), idempotency_key=None),
                        call=provider_call(),
                    )
                self.assertNotIn(secret, str(captured.exception))
                self.assertNotIn(secret, repr(captured.exception))
                self.assertNotIn(secret, repr(captured.exception.info))
                self.assertIsNone(captured.exception.detail)
                self.assertIsNone(captured.exception.__context__)
                self.assertIsNone(captured.exception.__cause__)

    async def test_structured_error_mapping_matrix(self) -> None:
        cases = (
            ({"status_code": 400}, ModelFailureKind.INVALID_REQUEST, False),
            ({"status_code": 422}, ModelFailureKind.INVALID_REQUEST, False),
            ({"status_code": 401}, ModelFailureKind.AUTHENTICATION, False),
            ({"status_code": 403}, ModelFailureKind.AUTHENTICATION, False),
            ({"status_code": 408}, ModelFailureKind.TIMEOUT, True),
            ({"status_code": 429}, ModelFailureKind.RATE_LIMITED, False),
            ({"status_code": 503}, ModelFailureKind.PROVIDER_UNAVAILABLE, True),
            (
                {"code": "context_length_exceeded"},
                ModelFailureKind.CONTEXT_TOO_LONG,
                False,
            ),
            (
                {"code": "content_policy_violation"},
                ModelFailureKind.SAFETY_REJECTED,
                False,
            ),
        )
        for attributes, expected_kind, outcome_unknown in cases:
            with self.subTest(attributes=attributes):
                failure = RuntimeError("synthetic provider body")
                for name, value in attributes.items():
                    setattr(failure, name, value)
                raw = _AstrBotProvider(failure)
                adapter, descriptor = _adapter(raw)
                with self.assertRaises(ModelProviderError) as captured:
                    await adapter.generate(
                        replace(
                            _request(descriptor),
                            idempotency_key=None,
                        ),
                        call=provider_call(),
                    )
                self.assertEqual(captured.exception.failure_kind, expected_kind)
                self.assertEqual(
                    captured.exception.info.outcome_unknown, outcome_unknown
                )


if __name__ == "__main__":
    unittest.main()
