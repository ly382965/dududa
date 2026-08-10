from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from dududa.domain.content import (
    Citation,
    FactAnchor,
    GeneratedAssetRef,
    Refusal,
    SafetyNotice,
    UncertaintyNote,
)
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    ResponseConstraints,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.perception.contracts import (
    ClarificationKey,
    SocialAction,
    SocialDecision,
)
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.responses import response_plan_digest
from dududa.runtime.composition import (
    DeterministicPersonaRenderer,
    DeterministicPersonaRendererConfig,
    DeterministicRenderValidator,
    FinalResponseSafetyValidator,
    MinimalResponseComposer,
    MinimalResponseComposerConfig,
)
from dududa.runtime.contracts import DirectChatContent
from dududa.security.content_safety import DefaultContentSafetyPolicy

from tests.unit.models.helpers import NOW
from tests.unit.runtime.test_s10_context_budget import actor, builder, message, scope


def _revision(name: str) -> ComponentRevision:
    return ComponentRevision(
        name,
        "1.0.0",
        "config-v1",
        DigestString(f"artifact:{name}"),
    )


def _context():
    envelope = message(private=False, mentioned=True)
    preprocess = builder().preprocess(envelope, actor(envelope))
    return (
        builder().build(envelope, actor(envelope), scope(envelope), preprocess),
        envelope,
    )


def _decision(context, *, clarification: bool = False) -> SocialDecision:
    return SocialDecision(
        schema_version=1,
        decision_id="social-1",
        perception_result_digest=DigestString("perception-result"),
        action=(
            SocialAction.ASK_CLARIFICATION
            if clarification
            else SocialAction.DIRECT_REPLY
        ),
        confidence=0.9,
        reason_codes=(
            "bounded_clarification_required"
            if clarification
            else "explicit_direct_reply",
        ),
        target_identity_refs=(context.current_author_identity_ref,),
        clarification_key=ClarificationKey.TASK if clarification else None,
        response_constraints=ResponseConstraints(
            max_characters=2_000,
            allow_markdown=True,
            allow_attachments=False,
        ),
        policy_revision="social-v1",
        decided_at=NOW,
    )


def _direct(
    context,
    *,
    text: str = "A bounded answer.",
    response_plan=None,
) -> DirectChatContent:
    return DirectChatContent(
        1,
        "direct-content-1",
        text,
        (context.perception.current_message_ref,),
        DigestString("request-fingerprint"),
        DigestString("response-digest"),
        response_plan_digest(response_plan) if response_plan is not None else None,
    )


def _composer() -> MinimalResponseComposer:
    return MinimalResponseComposer(
        MinimalResponseComposerConfig(
            1,
            {
                ClarificationKey.TARGET: "请说明要回复谁。",
                ClarificationKey.REFERENCE: "请说明你指的是哪一项。",
                ClarificationKey.SCOPE: "请说明问题的范围。",
                ClarificationKey.TASK: "请说明希望我完成什么任务。",
                ClarificationKey.TOOL_INPUT: "请补充执行所需的信息。",
            },
            _revision("composer"),
        ),
        id_factory=lambda: "response-1",
    )


def _renderer() -> DeterministicPersonaRenderer:
    return DeterministicPersonaRenderer(
        DeterministicPersonaRendererConfig(
            1,
            "dududa",
            "s10-v1",
            _revision("renderer"),
        )
    )


def _call() -> PortCallContext:
    return PortCallContext(
        "run-1",
        TraceContext("trace-1"),
        NOW + timedelta(days=1),
        NeverCancelled(),
        RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
        "policy-v1",
    )


class _ForgingSafetyPolicy:
    def __init__(self) -> None:
        self._inner = DefaultContentSafetyPolicy(clock=lambda: NOW)

    async def evaluate(self, request, *, call):
        decision = await self._inner.evaluate(request, call=call)
        return replace(decision, scope_digest=DigestString("forged-scope"))


class CompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_composition_stages_bind_the_same_response_plan(self) -> None:
        from tests.unit.runtime.test_direct_chat import _assessment, _response_plan

        context, envelope = _context()
        plan = _response_plan(_assessment(context))
        direct = _direct(context, response_plan=plan)
        draft = _composer().compose(context, _decision(context), direct, plan)
        rendered = _renderer().render(draft, plan)
        validator = FinalResponseSafetyValidator(
            DeterministicRenderValidator(_revision("render-validator")),
            DefaultContentSafetyPolicy(clock=lambda: NOW),
            clock=lambda: NOW,
        )

        validated = await validator.validate(
            draft,
            rendered,
            actor(envelope),
            scope(envelope),
            response_plan=plan,
            call=_call(),
        )

        digest = response_plan_digest(plan)
        self.assertEqual(draft.response_plan_digest, digest)
        self.assertEqual(
            validated.response.render_metadata.response_plan_digest,
            digest,
        )
        with self.assertRaises(DududaError):
            _renderer().render(draft, replace(plan, plan_id="plan:forged"))

    async def test_direct_content_reaches_validated_final_without_fact_drift(
        self,
    ) -> None:
        context, envelope = _context()
        draft = _composer().compose(context, _decision(context), _direct(context))
        rendered = _renderer().render(draft)
        validator = FinalResponseSafetyValidator(
            DeterministicRenderValidator(_revision("render-validator")),
            DefaultContentSafetyPolicy(clock=lambda: NOW),
            clock=lambda: NOW,
            id_factory=lambda: "safety-1",
        )

        validated = await validator.validate(
            draft,
            rendered,
            actor(envelope),
            scope(envelope),
            call=_call(),
        )

        self.assertEqual(validated.response.blocks[0].content.text, "A bounded answer.")
        self.assertEqual(validated.response.target_users, draft.target_users)
        self.assertEqual(
            validated.response.immutable_constraints,
            draft.immutable_constraints,
        )
        self.assertTrue(validated.render_validation.valid)
        self.assertTrue(validated.content_safety.allowed)

    async def test_clarification_is_deterministic_and_skips_direct_content(
        self,
    ) -> None:
        context, _ = _context()
        decision = _decision(context, clarification=True)

        draft = _composer().compose(context, decision, None)

        self.assertEqual(draft.intent, ClarificationKey.TASK.value)
        self.assertEqual(draft.content_blocks[0].content, "请说明希望我完成什么任务。")
        with self.assertRaises(DududaError):
            _composer().compose(context, decision, _direct(context))

    async def test_validator_rejects_every_protected_field_mutation(self) -> None:
        context, envelope = _context()
        draft = _composer().compose(context, _decision(context), _direct(context))
        rendered = _renderer().render(draft)
        validator = DeterministicRenderValidator(_revision("render-validator"))
        mutations = {
            "fact_anchors": (FactAnchor("fact-1", "changed", ("source-1",), True),),
            "citations": (Citation("citation-1", "label", "source-1"),),
            "uncertainty": (UncertaintyNote("note-1", "uncertain"),),
            "warnings": (SafetyNotice("notice-1", "warning"),),
            "refusal": Refusal("forged", "refusal.forged"),
            "immutable_constraints": ResponseConstraints(max_characters=1),
            "target_users": (),
            "attachments": (
                GeneratedAssetRef(
                    "asset-1",
                    "asset:1",
                    DigestString("asset-digest"),
                    "text/plain",
                    Sensitivity.PUBLIC,
                ),
            ),
        }
        for field_name, value in mutations.items():
            with self.subTest(field_name=field_name):
                result = validator.validate(
                    draft,
                    replace(rendered, **{field_name: value}),
                )
                self.assertFalse(result.valid)
                self.assertIn(f"{field_name}_changed", result.reason_codes)

        changed_text = replace(
            rendered,
            blocks=(
                replace(
                    rendered.blocks[0],
                    content=replace(rendered.blocks[0].content, text="changed"),
                ),
            ),
        )
        self.assertFalse(validator.validate(draft, changed_text).valid)

        safety = FinalResponseSafetyValidator(
            validator,
            DefaultContentSafetyPolicy(clock=lambda: NOW),
            clock=lambda: NOW,
        )
        with self.assertRaises(DududaError):
            await safety.validate(
                draft,
                changed_text,
                actor(envelope),
                scope(envelope),
                call=_call(),
            )

    async def test_safety_decision_must_bind_actual_actor_scope_and_content(
        self,
    ) -> None:
        context, envelope = _context()
        draft = _composer().compose(context, _decision(context), _direct(context))
        rendered = _renderer().render(draft)
        validator = FinalResponseSafetyValidator(
            DeterministicRenderValidator(_revision("render-validator")),
            _ForgingSafetyPolicy(),
            clock=lambda: NOW,
        )

        with self.assertRaises(DududaError):
            await validator.validate(
                draft,
                rendered,
                actor(envelope),
                scope(envelope),
                call=_call(),
            )


if __name__ == "__main__":
    unittest.main()
