from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import MappingProxyType

from dududa.contracts.canonical import canonical_digest, canonical_json_bytes
from dududa.domain.content import (
    ContentBlock,
    ContentSafetyDecision,
    DraftResponse,
    FinalResponse,
    RenderedBlock,
    RenderedContent,
    RenderMetadata,
    RenderValidationResult,
    SafetyStage,
    ValidatedFinalResponse,
)
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import ComponentRevision, JsonValue, freeze_json
from dududa.errors import validation_error
from dududa.perception.contracts import ClarificationKey, SocialAction, SocialDecision
from dududa.ports.context import PortCallContext
from dududa.ports.responses import ResponseProfileValidator
from dududa.ports.runtime import OfflineRenderValidator
from dududa.responses.contracts import ResponsePlan
from dududa.responses.digests import response_plan_digest
from dududa.security.digests import (
    actor_digest,
    content_safety_content_digest,
    content_safety_request_digest,
    scope_digest,
)
from dududa.security.models import ContentSafetyRequest
from dududa.security.ports import ContentSafetyPolicy

from .contracts import CurrentMessageContext, DirectChatContent


@dataclass(frozen=True, slots=True)
class MinimalResponseComposerConfig:
    schema_version: int
    clarification_messages: Mapping[ClarificationKey, str]
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        messages = dict(self.clarification_messages)
        if set(messages) != set(ClarificationKey) or any(
            not isinstance(key, ClarificationKey)
            or not isinstance(value, str)
            or not value.strip()
            for key, value in messages.items()
        ):
            raise validation_error("invalid_clarification_message_catalog")
        object.__setattr__(
            self,
            "clarification_messages",
            MappingProxyType(messages),
        )
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_response_composer_revision")


class MinimalResponseComposer:
    def __init__(
        self,
        config: MinimalResponseComposerConfig,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, MinimalResponseComposerConfig):
            raise TypeError("invalid minimal Response Composer config")
        self._config = config
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    @property
    def config(self) -> MinimalResponseComposerConfig:
        return self._config

    def compose(
        self,
        context: CurrentMessageContext,
        decision: SocialDecision,
        direct_content: DirectChatContent | None,
        response_plan: ResponsePlan | None = None,
    ) -> DraftResponse:
        if not isinstance(context, CurrentMessageContext):
            raise validation_error("invalid_composer_context")
        if not isinstance(decision, SocialDecision):
            raise validation_error("invalid_composer_social_decision")
        if response_plan is not None and not isinstance(response_plan, ResponsePlan):
            raise validation_error("invalid_composer_response_plan")
        expected_plan_digest = (
            response_plan_digest(response_plan) if response_plan is not None else None
        )
        if decision.action in {SocialAction.DIRECT_REPLY, SocialAction.USE_TOOLS}:
            if not isinstance(direct_content, DirectChatContent):
                raise validation_error("direct_reply_missing_direct_content")
            if direct_content.response_plan_digest != expected_plan_digest:
                raise validation_error("composer_direct_response_plan_mismatch")
            if context.perception.current_message_ref not in direct_content.source_refs:
                raise validation_error("direct_content_source_outside_context")
            text = direct_content.text
            source_refs = direct_content.source_refs
            intent = (
                "tool_assisted_chat"
                if decision.action is SocialAction.USE_TOOLS
                else "direct_chat"
            )
        elif decision.action is SocialAction.ASK_CLARIFICATION:
            if direct_content is not None or decision.clarification_key is None:
                raise validation_error("invalid_clarification_composition")
            text = self._config.clarification_messages[decision.clarification_key]
            source_refs = (context.perception.current_message_ref,)
            intent = decision.clarification_key.value
        else:
            raise validation_error("social_action_has_no_visible_composition")

        targets = tuple(
            context.resolve(identity_ref)
            for identity_ref in decision.target_identity_refs
        )
        response_id = self._id_factory()
        return DraftResponse(
            schema_version=1,
            response_id=response_id,
            producer=self._config.component_revision,
            intent=intent,
            content_blocks=(
                ContentBlock(
                    block_id=f"{response_id}:text",
                    kind="text",
                    content=text,
                    source_refs=source_refs,
                ),
            ),
            target_users=targets,
            immutable_constraints=decision.response_constraints,
            response_plan_digest=(expected_plan_digest),
        )


@dataclass(frozen=True, slots=True)
class DeterministicPersonaRendererConfig:
    schema_version: int
    persona_id: str
    persona_version: str
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.persona_id, str) or not self.persona_id.strip():
            raise validation_error("invalid_persona_id")
        if (
            not isinstance(self.persona_version, str)
            or not self.persona_version.strip()
        ):
            raise validation_error("invalid_persona_version")
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_persona_renderer_revision")


class DeterministicPersonaRenderer:
    def __init__(self, config: DeterministicPersonaRendererConfig) -> None:
        if not isinstance(config, DeterministicPersonaRendererConfig):
            raise TypeError("invalid deterministic Persona Renderer config")
        self._config = config

    @property
    def config(self) -> DeterministicPersonaRendererConfig:
        return self._config

    def render(
        self,
        draft: DraftResponse,
        response_plan: ResponsePlan | None = None,
    ) -> FinalResponse:
        if not isinstance(draft, DraftResponse):
            raise validation_error("invalid_persona_render_draft")
        if response_plan is not None and not isinstance(response_plan, ResponsePlan):
            raise validation_error("invalid_persona_response_plan")
        expected_plan_digest = (
            response_plan_digest(response_plan) if response_plan is not None else None
        )
        if draft.response_plan_digest != expected_plan_digest:
            raise validation_error("persona_response_plan_mismatch")
        blocks: list[RenderedBlock] = []
        for block in draft.content_blocks:
            if not isinstance(block.content, str):
                raise validation_error("s10_renderer_requires_text_blocks")
            blocks.append(
                RenderedBlock(
                    block_id=block.block_id,
                    content=RenderedContent(kind=block.kind, text=block.content),
                )
            )
        return FinalResponse(
            schema_version=1,
            response_id=draft.response_id,
            producer=self._config.component_revision,
            blocks=tuple(blocks),
            fact_anchors=draft.fact_anchors,
            citations=draft.citations,
            uncertainty=draft.uncertainty,
            warnings=draft.warnings,
            refusal=draft.refusal,
            immutable_constraints=draft.immutable_constraints,
            target_users=draft.target_users,
            attachments=draft.attachments,
            render_metadata=RenderMetadata(
                persona_id=self._config.persona_id,
                persona_version=self._config.persona_version,
                renderer_revision=self._config.component_revision,
                draft_digest=canonical_digest(draft, domain="response:draft:v1"),
                response_plan_digest=expected_plan_digest,
            ),
        )


class DeterministicRenderValidator:
    def __init__(self, revision: ComponentRevision) -> None:
        if not isinstance(revision, ComponentRevision):
            raise TypeError("invalid deterministic Render Validator revision")
        self._revision = revision

    @property
    def revision(self) -> ComponentRevision:
        return self._revision

    def validate(
        self,
        draft: DraftResponse,
        rendered: FinalResponse,
    ) -> RenderValidationResult:
        if not isinstance(draft, DraftResponse) or not isinstance(
            rendered, FinalResponse
        ):
            raise validation_error("invalid_render_validation_input")
        reasons: set[str] = set()
        if draft.response_id != rendered.response_id:
            reasons.add("response_id_changed")
        expected_blocks = tuple(
            (block.block_id, block.kind, block.content)
            for block in draft.content_blocks
        )
        rendered_blocks = tuple(
            (block.block_id, block.content.kind, block.content.text)
            for block in rendered.blocks
        )
        if expected_blocks != rendered_blocks:
            reasons.add("content_blocks_changed")
        for name in (
            "fact_anchors",
            "citations",
            "uncertainty",
            "warnings",
            "refusal",
            "immutable_constraints",
            "target_users",
            "attachments",
        ):
            if getattr(draft, name) != getattr(rendered, name):
                reasons.add(f"{name}_changed")
        draft_digest = canonical_digest(draft, domain="response:draft:v1")
        if rendered.render_metadata.draft_digest != draft_digest:
            reasons.add("render_metadata_draft_digest_changed")
        if draft.response_plan_digest != rendered.render_metadata.response_plan_digest:
            reasons.add("response_plan_digest_changed")
        changed_anchor_ids = _changed_anchor_ids(draft, rendered)
        return RenderValidationResult(
            schema_version=1,
            valid=not reasons,
            draft_digest=draft_digest,
            rendered_digest=canonical_digest(rendered, domain="response:final:v1"),
            reason_codes=tuple(sorted(reasons)),
            changed_anchor_ids=changed_anchor_ids,
            validator_revision=self._revision,
        )


class FinalResponseSafetyValidator:
    def __init__(
        self,
        render_validator: OfflineRenderValidator,
        content_safety: ContentSafetyPolicy,
        *,
        profile_validator: ResponseProfileValidator | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(render_validator, OfflineRenderValidator):
            raise TypeError(
                "render validator does not implement OfflineRenderValidator"
            )
        if not isinstance(content_safety, ContentSafetyPolicy):
            raise TypeError("content safety does not implement ContentSafetyPolicy")
        if profile_validator is not None and not isinstance(
            profile_validator, ResponseProfileValidator
        ):
            raise TypeError("profile validator does not implement its port")
        self._render_validator = render_validator
        self._content_safety = content_safety
        self._profile_validator = profile_validator
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def validate(
        self,
        draft: DraftResponse,
        rendered: FinalResponse,
        actor: Actor,
        scope: ConversationScope,
        *,
        response_plan: ResponsePlan | None = None,
        call: PortCallContext,
    ) -> ValidatedFinalResponse:
        if not isinstance(actor, Actor) or not isinstance(scope, ConversationScope):
            raise validation_error("invalid_final_response_security_identity")
        if response_plan is not None and not isinstance(response_plan, ResponsePlan):
            raise validation_error("invalid_final_response_plan")
        expected_plan_digest = (
            response_plan_digest(response_plan) if response_plan is not None else None
        )
        if (
            draft.response_plan_digest != expected_plan_digest
            or rendered.render_metadata.response_plan_digest != expected_plan_digest
        ):
            raise validation_error("final_response_plan_mismatch")
        render_validation = self._render_validator.validate(draft, rendered)
        if not render_validation.valid or render_validation.changed_anchor_ids:
            raise validation_error("render_validation_failed")
        profile_validation = None
        if response_plan is not None:
            if self._profile_validator is None:
                raise validation_error("response_profile_validator_missing")
            profile_validation = self._profile_validator.validate(
                draft,
                rendered,
                response_plan,
            )
            if not profile_validation.valid:
                raise validation_error("response_profile_validation_failed")
        projection = _json_projection(rendered)
        content_digest = content_safety_content_digest(
            projection,
            SafetyStage.FINAL_OUTPUT,
        )
        actual_digest = canonical_digest(rendered, domain="response:final:v1")
        if content_digest != actual_digest:
            raise validation_error("final_response_projection_digest_mismatch")
        request = ContentSafetyRequest(
            schema_version=1,
            request_id=self._id_factory(),
            request_digest=canonical_digest({}, domain="pending:v1"),
            stage=SafetyStage.FINAL_OUTPUT,
            content=projection,
            content_digest=content_digest,
            actor_digest=actor_digest(actor),
            scope_digest=scope_digest(scope),
        )
        request = replace(
            request,
            request_digest=content_safety_request_digest(request),
        )
        decision = await self._content_safety.evaluate(request, call=call)
        _validate_safety_decision(decision, request)
        return ValidatedFinalResponse(
            schema_version=1,
            response=rendered,
            render_validation=render_validation,
            content_safety=decision,
            profile_validation=profile_validation,
        )


def _validate_safety_decision(
    decision: ContentSafetyDecision,
    request: ContentSafetyRequest,
) -> None:
    if not isinstance(decision, ContentSafetyDecision):
        raise validation_error("invalid_content_safety_decision")
    if (
        decision.request_id != request.request_id
        or decision.request_digest != request.request_digest
        or decision.stage is not request.stage
        or decision.content_digest != request.content_digest
        or decision.actor_digest != request.actor_digest
        or decision.scope_digest != request.scope_digest
    ):
        raise validation_error("content_safety_decision_binding_mismatch")


def _changed_anchor_ids(
    draft: DraftResponse,
    rendered: FinalResponse,
) -> tuple[str, ...]:
    draft_by_id = {anchor.anchor_id: anchor for anchor in draft.fact_anchors}
    rendered_by_id = {anchor.anchor_id: anchor for anchor in rendered.fact_anchors}
    return tuple(
        sorted(
            anchor_id
            for anchor_id in set(draft_by_id) | set(rendered_by_id)
            if draft_by_id.get(anchor_id) != rendered_by_id.get(anchor_id)
        )
    )


def _json_projection(value: object) -> JsonValue:
    projected = json.loads(canonical_json_bytes(value).decode("utf-8"))
    return freeze_json(projected)
