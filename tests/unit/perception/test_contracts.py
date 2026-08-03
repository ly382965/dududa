from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType
import unittest

from dududa.domain.primitives import DigestString, freeze_json
from dududa.errors import DududaError
from dududa.perception.contracts import (
    PerceptionIdentity,
    PerceptionMessage,
)
from dududa.perception.digests import (
    model_perception_projection_digest,
    model_perception_projection_fingerprint,
    perception_context_digest,
    perception_context_fingerprint,
)
from dududa.perception.schema import (
    decode_model_projection,
    model_projection_schema,
    model_projection_schema_ref,
)
from dududa.perception.validation import validate_model_projection

from .helpers import context, limits, model_payload, revision


class PerceptionContextContractTests(unittest.TestCase):
    def test_context_is_frozen_bounded_and_canonical(self) -> None:
        value = context(
            available_capability_categories=("search", "code"),
        )

        self.assertEqual(value.available_capability_categories, ("code", "search"))
        self.assertEqual(value.current_message.message_ref, "message:current")
        self.assertEqual(
            perception_context_digest(value), perception_context_digest(value)
        )
        replay = replace(value, context_id="context-replay")
        self.assertNotEqual(
            perception_context_digest(value), perception_context_digest(replay)
        )
        self.assertEqual(
            perception_context_fingerprint(value),
            perception_context_fingerprint(replay),
        )
        with self.assertRaises(FrozenInstanceError):
            value.context_id = "changed"  # type: ignore[misc]

    def test_context_rejects_unknown_forward_and_bot_references(self) -> None:
        current = context().messages[-1]
        invalid_messages = (
            replace(current, author_identity_ref="identity:unknown"),
            replace(current, reply_to_message_ref="message:unknown"),
            replace(current, is_bot_authored=True),
        )
        for invalid in invalid_messages:
            with self.subTest(invalid=invalid), self.assertRaises(DududaError):
                context(messages=(invalid,))

        with self.assertRaises(DududaError):
            context(
                identities=(
                    PerceptionIdentity(1, "identity:bot", True),
                    PerceptionIdentity(1, "identity:second-bot", True),
                )
            )

    def test_context_rejects_direct_construction_past_limits(self) -> None:
        tiny = limits(
            max_messages=1,
            max_characters_per_message=4,
            max_total_characters=4,
        )
        message = PerceptionMessage(
            1,
            "message:current",
            "identity:user",
            "12345",
            None,
        )
        with self.assertRaises(DududaError):
            context(messages=(message,), limits=tiny)
        with self.assertRaises(DududaError):
            limits(max_messages=65)
        with self.assertRaises(DududaError):
            limits(max_messages=True)  # type: ignore[arg-type]
        with self.assertRaises(DududaError):
            PerceptionIdentity(1, "identity:" + "x" * 121, False)
        with self.assertRaises(DududaError):
            context(
                limits=limits(max_degraded_components=1),
                degraded_components=("model-a", "model-b"),
            )


class ModelProjectionContractTests(unittest.TestCase):
    def _decode(self, payload: object | None = None):
        current = context()
        value = freeze_json(payload if payload is not None else model_payload())
        return current, decode_model_projection(
            value,
            context_digest=perception_context_digest(current),
            projection_id="projection-1",
            request_fingerprint=DigestString("request-fingerprint"),
            route_receipt_digest=DigestString("route-receipt"),
            component_revision=revision("model-perception"),
        )

    def test_schema_is_strict_bounded_and_digestible(self) -> None:
        document = model_projection_schema(limits())
        self.assertIsInstance(document, MappingProxyType)
        self.assertFalse(document["additionalProperties"])
        self.assertEqual(
            document["properties"]["topics"]["maxItems"],  # type: ignore[index]
            16,
        )
        self.assertEqual(
            model_projection_schema_ref(limits()),
            model_projection_schema_ref(limits()),
        )

    def test_exact_decoder_and_semantic_validator_accept_valid_projection(self) -> None:
        current, projection = self._decode()

        self.assertIs(validate_model_projection(current, projection), projection)
        self.assertEqual(projection.target_identity_refs, ("identity:user",))
        self.assertEqual(len(projection.complexity_signals), 2)

    def test_decoder_rejects_unknown_properties_and_bool_as_integer(self) -> None:
        unknown = model_payload(extra="user-supplied-opus")
        with self.assertRaises(DududaError):
            self._decode(unknown)

        invalid = model_payload(expected_tool_steps=True)
        with self.assertRaises(DududaError):
            self._decode(invalid)

    def test_core_decoder_rechecks_schema_size_ceilings(self) -> None:
        payloads = (
            model_payload(task_kind="x" * 129),
            model_payload(expected_tool_steps=65),
            model_payload(
                topics=[
                    {
                        "topic_id": "topic:oversized",
                        "label": "x" * 257,
                        "confidence": 1.0,
                        "evidence_refs": ["message:current"],
                    }
                ]
            ),
            model_payload(
                topics=[
                    {
                        "topic_id": f"topic:{index}",
                        "label": f"topic {index}",
                        "confidence": 1.0,
                        "evidence_refs": ["message:current"],
                    }
                    for index in range(65)
                ]
            ),
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(DududaError):
                self._decode(payload)

    def test_whole_projection_rejects_unknown_semantic_references(self) -> None:
        payloads = (
            model_payload(target_identity_refs=["identity:outside"]),
            model_payload(
                capability_categories=["outside"],
                need_tools=True,
                expected_tool_steps=1,
            ),
            model_payload(
                topics=[
                    {
                        "topic_id": "topic:outside",
                        "label": "outside",
                        "confidence": 1.0,
                        "evidence_refs": ["message:outside"],
                    }
                ]
            ),
            model_payload(
                references=[
                    {
                        "reference_id": "reference:outside",
                        "kind": "message",
                        "target_ref": "message:outside",
                        "confidence": 1.0,
                        "evidence_refs": ["message:current"],
                    }
                ]
            ),
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                current, projection = self._decode(payload)
                with self.assertRaises(DududaError):
                    validate_model_projection(current, projection)

    def test_projection_fingerprint_excludes_execution_identity_and_receipt(
        self,
    ) -> None:
        _, projection = self._decode()
        replay = replace(
            projection,
            projection_id="projection-replay",
            route_receipt_digest=DigestString("other-route-receipt"),
        )

        self.assertNotEqual(
            model_perception_projection_digest(projection),
            model_perception_projection_digest(replay),
        )
        self.assertEqual(
            model_perception_projection_fingerprint(projection),
            model_perception_projection_fingerprint(replay),
        )


if __name__ == "__main__":
    unittest.main()
