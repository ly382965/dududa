from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.content import (
    DraftResponse,
    FinalResponse,
    ResponseProfileValidationResult,
)
from dududa.domain.primitives import ComponentRevision
from dududa.errors import validation_error
from dududa.ports.responses import VisibleTokenCounter

from .contracts import ResponsePlan
from .counting import visible_character_count
from .digests import response_plan_digest


class DeterministicResponseProfileValidator:
    def __init__(
        self,
        counter: VisibleTokenCounter,
        revision: ComponentRevision,
    ) -> None:
        if not isinstance(counter, VisibleTokenCounter):
            raise TypeError("counter does not implement VisibleTokenCounter")
        if not isinstance(revision, ComponentRevision):
            raise TypeError("invalid Response Profile Validator revision")
        self._counter = counter
        self._revision = revision

    @property
    def revision(self) -> ComponentRevision:
        return self._revision

    def validate(
        self,
        draft: DraftResponse,
        rendered: FinalResponse,
        plan: ResponsePlan,
    ) -> ResponseProfileValidationResult:
        if not isinstance(draft, DraftResponse) or not isinstance(
            rendered, FinalResponse
        ):
            raise validation_error("invalid_profile_validation_response")
        if not isinstance(plan, ResponsePlan):
            raise validation_error("invalid_profile_validation_plan")
        plan_digest = response_plan_digest(plan)
        rendered_digest = canonical_digest(rendered, domain="response:final:v1")
        reasons: set[str] = set()
        if (
            draft.response_plan_digest != plan_digest
            or rendered.render_metadata.response_plan_digest != plan_digest
        ):
            reasons.add("response_plan_digest_mismatch")

        texts = tuple(
            block.content.text
            for block in rendered.blocks
            if block.content.text is not None
        )
        visible_tokens = sum(self._counter.count(text) for text in texts)
        visible_characters = sum(visible_character_count(text) for text in texts)
        if visible_tokens > plan.visible_token_limit:
            reasons.add("visible_token_limit_exceeded")
        if visible_characters > plan.visible_character_limit:
            reasons.add("visible_character_limit_exceeded")

        required = _draft_requirement_ids(draft)
        actual = _final_requirement_ids(rendered)
        missing = tuple(sorted(set(required) - set(actual)))
        unexpected = tuple(sorted(set(actual) - set(required)))
        if missing:
            reasons.add("required_content_missing")
        if unexpected:
            reasons.add("unexpected_content_added")
        if not reasons:
            reasons.add("response_profile_validation_passed")
        return ResponseProfileValidationResult(
            schema_version=1,
            valid=reasons == {"response_profile_validation_passed"},
            response_plan_digest=plan_digest,
            rendered_digest=rendered_digest,
            selected_profile=plan.selected_profile.value,
            visible_token_units=visible_tokens,
            visible_characters=visible_characters,
            required_content_ids=required,
            missing_content_ids=missing,
            unexpected_content_ids=unexpected,
            reason_codes=tuple(sorted(reasons)),
            counter_revision=self._counter.revision,
            validator_revision=self._revision,
        )


def _draft_requirement_ids(value: DraftResponse) -> tuple[str, ...]:
    return _requirement_ids(
        block_ids=tuple(item.block_id for item in value.content_blocks),
        fact_ids=tuple(item.anchor_id for item in value.fact_anchors),
        citation_ids=tuple(item.citation_id for item in value.citations),
        uncertainty_ids=tuple(item.note_id for item in value.uncertainty),
        warning_ids=tuple(item.notice_id for item in value.warnings),
        refusal=(value.refusal.reason_code if value.refusal is not None else None),
        targets=value.target_users,
        attachment_ids=tuple(item.asset_id for item in value.attachments),
        notice_keys=value.immutable_constraints.required_notice_keys,
    )


def _final_requirement_ids(value: FinalResponse) -> tuple[str, ...]:
    return _requirement_ids(
        block_ids=tuple(item.block_id for item in value.blocks),
        fact_ids=tuple(item.anchor_id for item in value.fact_anchors),
        citation_ids=tuple(item.citation_id for item in value.citations),
        uncertainty_ids=tuple(item.note_id for item in value.uncertainty),
        warning_ids=tuple(item.notice_id for item in value.warnings),
        refusal=(value.refusal.reason_code if value.refusal is not None else None),
        targets=value.target_users,
        attachment_ids=tuple(item.asset_id for item in value.attachments),
        notice_keys=value.immutable_constraints.required_notice_keys,
    )


def _requirement_ids(
    *,
    block_ids: tuple[str, ...],
    fact_ids: tuple[str, ...],
    citation_ids: tuple[str, ...],
    uncertainty_ids: tuple[str, ...],
    warning_ids: tuple[str, ...],
    refusal: str | None,
    targets: tuple[object, ...],
    attachment_ids: tuple[str, ...],
    notice_keys: tuple[str, ...],
) -> tuple[str, ...]:
    values = {
        *(f"block:{value}" for value in block_ids),
        *(f"fact:{value}" for value in fact_ids),
        *(f"citation:{value}" for value in citation_ids),
        *(f"uncertainty:{value}" for value in uncertainty_ids),
        *(f"warning:{value}" for value in warning_ids),
        *(f"attachment:{value}" for value in attachment_ids),
        *(f"notice:{value}" for value in notice_keys),
        *(
            "target:"
            + str(
                canonical_digest(
                    target,
                    domain="response:required-target:v1",
                )
            )
            for target in targets
        ),
    }
    if refusal is not None:
        values.add(f"refusal:{refusal}")
    return tuple(sorted(values))


__all__ = ["DeterministicResponseProfileValidator"]
