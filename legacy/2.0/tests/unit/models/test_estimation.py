from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import unittest

from dududa.domain.primitives import DigestString, PrivacyLevel, SchemaRef
from dududa.errors import DududaError
from dududa.models.contracts import (
    ModelInput,
    ModelInputModality,
    ModelInputPart,
    ModelPrivacyPolicy,
    ModelRequest,
    ModelRole,
    ModelTier,
)
from dududa.models.estimation import (
    ConservativeModelInvocationEstimator,
    ModelTokenPricing,
)

from .helpers import endpoint, reasoning_profiles, revision


def _request(schema: SchemaRef | None) -> ModelRequest:
    return ModelRequest(
        schema_version=1,
        request_id="request-1",
        role=ModelRole.DIRECT_CHAT,
        input=ModelInput(
            schema_version=1,
            parts=(
                ModelInputPart(
                    schema_version=1,
                    part_id="text-1",
                    modality=ModelInputModality.TEXT,
                    text="hello",
                    content_ref=None,
                    content_digest=None,
                    media_type=None,
                ),
            ),
            source_refs=("message:m1",),
        ),
        output_schema=schema,
        max_output_tokens=100,
        content_input_tokens_upper_bound=10,
        temperature=0,
        privacy=ModelPrivacyPolicy(
            schema_version=1,
            data_classification=PrivacyLevel.CONVERSATION,
            allow_external_provider=True,
            allowed_residencies=frozenset({"global"}),
            allow_provider_retention=False,
        ),
        reasoning_profile_id="balanced",
        random_seed=None,
        idempotency_key="idempotency-1",
        route_hint=None,
    )


class EstimatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.endpoint = endpoint("sonnet-a", ModelTier.SONNET)
        self.profile = reasoning_profiles()[1]
        self.schema = SchemaRef(
            schema_id="direct-chat-output",
            schema_version=1,
            digest=DigestString("schema-v1"),
        )
        self.estimator = ConservativeModelInvocationEstimator(
            revision=revision("model-estimator"),
            role_prompt_tokens={ModelRole.DIRECT_CHAT: 3},
            provider_wrapping_tokens={self.endpoint.descriptor_digest: 5},
            schema_tokens={self.schema.digest: 7},
            pricing={
                self.endpoint.descriptor_digest: ModelTokenPricing(
                    schema_version=1,
                    input_cost_per_million=Decimal(2),
                    generated_cost_per_million=Decimal(4),
                )
            },
        )

    def test_complete_upper_bound_and_reasoning_is_not_double_counted(self) -> None:
        estimate = self.estimator.estimate(
            _request(self.schema),
            self.endpoint,
            self.profile,
        )

        self.assertEqual(estimate.input_tokens_upper_bound, 25)
        self.assertEqual(estimate.generated_tokens_upper_bound, 100)
        self.assertEqual(estimate.reasoning_tokens_upper_bound, 100)
        self.assertEqual(estimate.total_context_tokens_upper_bound, 125)
        self.assertEqual(estimate.cost_units_upper_bound, Decimal("0.00045"))

    def test_utf8_bytes_raise_a_too_small_content_bound(self) -> None:
        request = _request(None)
        request = replace(
            request,
            input=replace(
                request.input,
                parts=(replace(request.input.parts[0], text="你好"),),
            ),
            content_input_tokens_upper_bound=1,
        )
        estimate = self.estimator.estimate(request, self.endpoint, self.profile)
        self.assertEqual(estimate.input_tokens_upper_bound, 6 + 3 + 5)

    def test_missing_schema_or_wrapping_estimate_fails_closed(self) -> None:
        missing_schema = ConservativeModelInvocationEstimator(
            revision=revision("model-estimator"),
            role_prompt_tokens={ModelRole.DIRECT_CHAT: 0},
            provider_wrapping_tokens={self.endpoint.descriptor_digest: 0},
            schema_tokens={},
        )
        with self.assertRaises(DududaError):
            missing_schema.estimate(_request(self.schema), self.endpoint, self.profile)

        missing_wrapper = ConservativeModelInvocationEstimator(
            revision=revision("model-estimator"),
            role_prompt_tokens={ModelRole.DIRECT_CHAT: 0},
            provider_wrapping_tokens={},
            schema_tokens={self.schema.digest: 1},
        )
        with self.assertRaises(DududaError):
            missing_wrapper.estimate(
                _request(self.schema),
                self.endpoint,
                self.profile,
            )


if __name__ == "__main__":
    unittest.main()
