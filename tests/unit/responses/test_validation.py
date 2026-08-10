from __future__ import annotations

import unittest
from dataclasses import replace

from dududa.domain.content import FactAnchor
from dududa.errors import DududaError
from dududa.ports.responses import ResponseProfileValidator
from dududa.responses import (
    DeterministicResponseProfileValidator,
    UnicodeVisibleTokenCounter,
)

from tests.unit.runtime.test_composition import (
    _composer,
    _context,
    _decision,
    _direct,
    _persona_resolution,
    _renderer,
    _revision,
)
from tests.unit.runtime.test_direct_chat import _assessment, _response_plan


def _validator() -> DeterministicResponseProfileValidator:
    return DeterministicResponseProfileValidator(
        UnicodeVisibleTokenCounter(_revision("visible-token-counter")),
        _revision("response-profile-validator"),
    )


class ResponseProfileValidatorTests(unittest.TestCase):
    def test_validator_implements_port_and_records_mechanical_evidence(self) -> None:
        context, _ = _context()
        plan = _response_plan(_assessment(context))
        draft = _composer().compose(
            context,
            _decision(context),
            _direct(context, response_plan=plan),
            plan,
        )
        rendered = _renderer().render(
            draft,
            plan,
            persona_resolution=_persona_resolution(),
        )
        validator = _validator()

        result = validator.validate(draft, rendered, plan)

        self.assertIsInstance(validator, ResponseProfileValidator)
        self.assertTrue(result.valid)
        self.assertEqual(result.visible_token_units, 4)
        self.assertEqual(result.visible_characters, len("A bounded answer."))
        self.assertIn("block:response-1:text", result.required_content_ids)
        self.assertEqual(
            len(
                tuple(
                    item
                    for item in result.required_content_ids
                    if item.startswith("target:")
                )
            ),
            1,
        )
        self.assertEqual(result.missing_content_ids, ())
        self.assertEqual(result.unexpected_content_ids, ())

    def test_token_overflow_and_typed_content_drift_fail_closed(self) -> None:
        context, _ = _context()
        plan = _response_plan(_assessment(context))
        draft = _composer().compose(
            context,
            _decision(context),
            _direct(context, response_plan=plan),
            plan,
        )
        resolution = _persona_resolution()
        rendered = _renderer().render(
            draft,
            plan,
            persona_resolution=resolution,
        )
        overflow = replace(
            rendered,
            blocks=(
                replace(
                    rendered.blocks[0],
                    content=replace(rendered.blocks[0].content, text="a," * 65),
                ),
            ),
        )

        overflow_result = _validator().validate(draft, overflow, plan)

        self.assertFalse(overflow_result.valid)
        self.assertIn(
            "visible_token_limit_exceeded",
            overflow_result.reason_codes,
        )

        anchored_draft = replace(
            draft,
            fact_anchors=(FactAnchor("fact:1", "42", ("source:1",), True),),
        )
        anchored_render = _renderer().render(
            anchored_draft,
            plan,
            persona_resolution=resolution,
        )
        missing = _validator().validate(
            anchored_draft,
            replace(anchored_render, fact_anchors=()),
            plan,
        )
        self.assertFalse(missing.valid)
        self.assertEqual(missing.missing_content_ids, ("fact:fact:1",))
        with self.assertRaises(DududaError):
            replace(missing, valid=True)


if __name__ == "__main__":
    unittest.main()
