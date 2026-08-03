from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.errors import validation_error

from .contracts import (
    ModelEndpointDescriptor,
    ModelInputModality,
    ModelInvocationEstimate,
    ModelRequest,
    ModelRole,
    ReasoningDepth,
    ReasoningProfile,
)
from .digests import model_endpoint_descriptor_digest, model_request_digest


@dataclass(frozen=True, slots=True)
class ModelTokenPricing:
    schema_version: int
    input_cost_per_million: Decimal
    generated_cost_per_million: Decimal

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        for field_name in (
            "input_cost_per_million",
            "generated_cost_per_million",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise validation_error("invalid_model_token_price", field_name)


class ConservativeModelInvocationEstimator:
    """Provider-neutral upper-bound estimator with explicit overhead inputs."""

    def __init__(
        self,
        *,
        revision: ComponentRevision,
        role_prompt_tokens: Mapping[ModelRole, int],
        provider_wrapping_tokens: Mapping[DigestString, int],
        schema_tokens: Mapping[DigestString, int],
        pricing: Mapping[DigestString, ModelTokenPricing] | None = None,
    ) -> None:
        if not isinstance(revision, ComponentRevision):
            raise ValueError("revision must be a ComponentRevision")
        self._revision = revision
        self._role_prompt_tokens = MappingProxyType(
            _validate_role_tokens(role_prompt_tokens)
        )
        self._provider_wrapping_tokens = MappingProxyType(
            _validate_digest_tokens(
                provider_wrapping_tokens,
                "provider_wrapping_tokens",
            )
        )
        self._schema_tokens = MappingProxyType(
            _validate_digest_tokens(schema_tokens, "schema_tokens")
        )
        pricing_values = dict(pricing or {})
        if any(
            not isinstance(digest, str)
            or not digest.strip()
            or not isinstance(value, ModelTokenPricing)
            for digest, value in pricing_values.items()
        ):
            raise ValueError("invalid pricing configuration")
        self._pricing = MappingProxyType(pricing_values)

    @property
    def revision(self) -> ComponentRevision:
        return self._revision

    def estimate(
        self,
        request: ModelRequest,
        endpoint: ModelEndpointDescriptor,
        reasoning_profile: ReasoningProfile,
    ) -> ModelInvocationEstimate:
        if not isinstance(request, ModelRequest):
            raise validation_error("invalid_model_request")
        if not isinstance(endpoint, ModelEndpointDescriptor):
            raise validation_error("invalid_model_endpoint_descriptor")
        if not isinstance(reasoning_profile, ReasoningProfile):
            raise validation_error("invalid_reasoning_profile")
        if endpoint.descriptor_digest != model_endpoint_descriptor_digest(endpoint):
            raise validation_error("endpoint_descriptor_digest_mismatch")
        configured_profile = next(
            (
                profile
                for profile in endpoint.reasoning_profiles
                if profile.profile_id == reasoning_profile.profile_id
            ),
            None,
        )
        if configured_profile != reasoning_profile:
            raise validation_error("endpoint_reasoning_profile_mismatch")
        try:
            prompt_tokens = self._role_prompt_tokens[request.role]
        except KeyError:
            raise validation_error("missing_role_prompt_estimate") from None
        try:
            wrapping_tokens = self._provider_wrapping_tokens[endpoint.descriptor_digest]
        except KeyError:
            raise validation_error("missing_provider_wrapping_estimate") from None

        schema_token_count = 0
        if request.output_schema is not None:
            try:
                schema_token_count = self._schema_tokens[request.output_schema.digest]
            except KeyError:
                raise validation_error("missing_schema_token_estimate") from None
        observed_text_upper_bound = sum(
            len(part.text.encode("utf-8"))
            for part in request.input.parts
            if part.modality is ModelInputModality.TEXT and part.text is not None
        )
        content_tokens = max(
            request.content_input_tokens_upper_bound,
            observed_text_upper_bound,
        )
        input_tokens = (
            content_tokens + prompt_tokens + schema_token_count + wrapping_tokens
        )
        generated_tokens = request.max_output_tokens
        reasoning_tokens = _reasoning_upper_bound(
            reasoning_profile,
            generated_tokens,
        )
        pricing = self._pricing.get(endpoint.descriptor_digest)
        cost = None
        if pricing is not None:
            million = Decimal(1_000_000)
            cost = (
                Decimal(input_tokens) * pricing.input_cost_per_million
                + Decimal(generated_tokens) * pricing.generated_cost_per_million
            ) / million
        return ModelInvocationEstimate(
            schema_version=1,
            model_request_digest=model_request_digest(request),
            endpoint_descriptor_digest=endpoint.descriptor_digest,
            reasoning_profile_id=reasoning_profile.profile_id,
            input_tokens_upper_bound=input_tokens,
            generated_tokens_upper_bound=generated_tokens,
            reasoning_tokens_upper_bound=reasoning_tokens,
            total_context_tokens_upper_bound=input_tokens + generated_tokens,
            cost_units_upper_bound=cost,
            estimator_revision=self._revision,
        )


def _reasoning_upper_bound(profile: ReasoningProfile, generated_tokens: int) -> int:
    if profile.depth is ReasoningDepth.OFF:
        return 0
    if profile.max_reasoning_tokens is None:
        return generated_tokens
    return min(profile.max_reasoning_tokens, generated_tokens)


def _validate_role_tokens(values: Mapping[ModelRole, int]) -> dict[ModelRole, int]:
    result = dict(values)
    if not result or any(
        not isinstance(role, ModelRole) or type(tokens) is not int or tokens < 0
        for role, tokens in result.items()
    ):
        raise ValueError("invalid role prompt token configuration")
    return result


def _validate_digest_tokens(
    values: Mapping[DigestString, int],
    field: str,
) -> dict[DigestString, int]:
    result = dict(values)
    if any(
        not isinstance(digest, str)
        or not digest.strip()
        or type(tokens) is not int
        or tokens < 0
        for digest, tokens in result.items()
    ):
        raise ValueError(f"invalid {field} configuration")
    return result
