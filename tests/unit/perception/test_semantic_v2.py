from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
import unittest

from jsonschema import Draft202012Validator

from dududa.contracts.canonical import canonical_json_bytes
from dududa.domain.primitives import DigestString, freeze_json
from dududa.errors import DududaError
from dududa.perception.contracts import EntityKind, ReferenceKind
from dududa.perception.digests import (
    model_perception_projection_digest,
    perception_context_digest,
)
from dududa.perception.schema import decode_model_projection
from dududa.perception.semantic import (
    EntityMention,
    IntentCandidateV2,
    ReferenceLinkSource,
    ReferenceMention,
    SemanticDecision,
    SemanticDecisionAction,
    SemanticProjectionV2,
    TextOffsetUnit,
    TextSpan,
    VersionedModelPerceptionProjection,
    normalized_codepoint_offset,
    normalized_codepoint_span,
    normalized_text,
    semantic_projection_digest,
    semantic_text_digest,
)
from dududa.perception.semantic_schema import (
    decode_versioned_model_projection,
    encode_versioned_model_projection,
    model_projection_v2_schema,
    model_projection_v2_schema_ref,
)
from dududa.perception.semantic_validation import (
    validate_versioned_model_projection,
)

from .helpers import context, limits, model_payload, model_payload_v2, revision


class SemanticV2ContractTests(unittest.TestCase):
    def _decode(self, payload: object | None = None):
        current = context()
        return current, decode_versioned_model_projection(
            freeze_json(payload if payload is not None else model_payload_v2()),
            context_digest=perception_context_digest(current),
            projection_id="projection-v2",
            request_fingerprint=DigestString("request-fingerprint"),
            route_receipt_digest=DigestString("route-receipt"),
            component_revision=revision("model-perception"),
            semantic_component_revision=revision("semantic-v2"),
            taxonomy_revision=revision("intent-taxonomy"),
            calibration_revision=revision("uncalibrated-pilot"),
            threshold_policy_revision=revision("pilot-thresholds"),
        )

    def test_v1_reader_digest_and_round_trip_remain_compatible(self) -> None:
        current = context()
        payload = freeze_json(model_payload())
        legacy = decode_model_projection(
            payload,
            context_digest=perception_context_digest(current),
            projection_id="projection-1",
            request_fingerprint=DigestString("request-fingerprint"),
            route_receipt_digest=DigestString("route-receipt"),
            component_revision=revision("model-perception"),
        )
        versioned = decode_versioned_model_projection(
            payload,
            context_digest=perception_context_digest(current),
            projection_id="projection-1",
            request_fingerprint=DigestString("request-fingerprint"),
            route_receipt_digest=DigestString("route-receipt"),
            component_revision=revision("model-perception"),
        )

        self.assertEqual(versioned.schema_version, 1)
        self.assertEqual(versioned.base_projection, legacy)
        self.assertIsNone(versioned.semantic)
        self.assertEqual(encode_versioned_model_projection(versioned), payload)
        self.assertEqual(
            str(model_perception_projection_digest(legacy)),
            "dududa-c14n-v1:perception:model-projection:v1:sha-256:"
            "f3ccef80fd611659db243fc5a629d5d229fb3d7047987e80a9d8976625d0a769",
        )

    def test_v2_schema_round_trip_and_v1_downgrade_are_exact(self) -> None:
        schema = json.loads(
            canonical_json_bytes(model_projection_v2_schema(limits())).decode("utf-8")
        )
        payload_document = model_payload_v2()
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(payload_document)
        payload = freeze_json(payload_document)
        current, projection = self._decode(payload)

        self.assertIs(
            validate_versioned_model_projection(current, projection),
            projection,
        )
        self.assertEqual(encode_versioned_model_projection(projection), payload)
        self.assertEqual(projection.base_projection.schema_version, 1)
        self.assertEqual(
            projection.semantic.base_projection_digest,  # type: ignore[union-attr]
            model_perception_projection_digest(projection.base_projection),
        )
        self.assertEqual(
            str(model_projection_v2_schema_ref(limits()).digest),
            "dududa-c14n-v1:schema:dududa.perception.model-projection:v2:"
            "sha-256:e437c8731641a1f1c4c5268bae757c32d5864ebd309fe2ab73f6e2dc32939e00",
        )
        semantic = projection.semantic
        self.assertIsNotNone(semantic)
        assert semantic is not None
        self.assertEqual(
            str(semantic_projection_digest(semantic)),
            "dududa-c14n-v1:perception:semantic-projection:v2:sha-256:"
            "c39eff5249032fd079baa206e747ba8b8f296bcd3e990e7aed51a95ee850c5c4",
        )

        reordered_decision = replace(
            semantic.decision,
            reason_codes=("synthetic_z", "synthetic_a"),
        )
        canonical_decision = replace(
            semantic.decision,
            reason_codes=("synthetic_a", "synthetic_z"),
        )
        self.assertEqual(
            semantic_projection_digest(replace(semantic, decision=reordered_decision)),
            semantic_projection_digest(replace(semantic, decision=canonical_decision)),
        )
        self.assertNotEqual(
            semantic_projection_digest(semantic),
            semantic_projection_digest(
                replace(
                    semantic,
                    decision=replace(
                        semantic.decision,
                        action=SemanticDecisionAction.CLARIFY,
                    ),
                )
            ),
        )
        changed_taxonomy = revision("intent-taxonomy-v2")
        taxonomy_changed = replace(
            semantic,
            taxonomy_revision=changed_taxonomy,
            intents=tuple(
                replace(intent, taxonomy_revision=changed_taxonomy)
                for intent in semantic.intents
            ),
        )
        self.assertNotEqual(
            semantic_projection_digest(semantic),
            semantic_projection_digest(taxonomy_changed),
        )

    def test_contracts_are_frozen_bounded_and_cross_projected(self) -> None:
        current, projection = self._decode()
        semantic = projection.semantic
        self.assertIsNotNone(semantic)
        with self.assertRaises(FrozenInstanceError):
            semantic.entities = ()  # type: ignore[union-attr,misc]

        payload = model_payload_v2()
        payload["entities"] = [
            {
                "entity_id": "entity:legacy-only",
                "kind": "artifact",
                "value": "legacy",
                "confidence": 1.0,
                "evidence_refs": [current.current_message_ref],
            }
        ]
        with self.assertRaises(DududaError):
            self._decode(payload)

    def test_unknown_versions_properties_and_authority_revisions_fail_closed(
        self,
    ) -> None:
        unknown_version = model_payload_v2(schema_version=3)
        with self.assertRaises(DududaError):
            self._decode(unknown_version)

        unknown_property = model_payload_v2()
        unknown_property["semantic"]["operator_override"] = True  # type: ignore[index]
        with self.assertRaises(DududaError):
            self._decode(unknown_property)

        current = context()
        with self.assertRaises(DududaError):
            decode_versioned_model_projection(
                freeze_json(model_payload_v2()),
                context_digest=perception_context_digest(current),
                projection_id="projection-v2",
                request_fingerprint=DigestString("request-fingerprint"),
                route_receipt_digest=DigestString("route-receipt"),
                component_revision=revision("model-perception"),
            )

    def test_legacy_reader_remains_strict_for_v2_payloads(self) -> None:
        current = context()
        with self.assertRaises(DududaError):
            decode_model_projection(
                freeze_json(model_payload_v2()),
                context_digest=perception_context_digest(current),
                projection_id="projection-v2",
                request_fingerprint=DigestString("request-fingerprint"),
                route_receipt_digest=DigestString("route-receipt"),
                component_revision=revision("model-perception"),
            )

    def test_bool_offsets_and_oversized_semantic_values_fail_closed(self) -> None:
        bool_offset = model_payload_v2()
        bool_offset["semantic"]["references"][0]["mention_span"][  # type: ignore[index]
            "start"
        ] = True
        oversized_reasons = model_payload_v2()
        oversized_reasons["semantic"]["decision"]["reason_codes"] = [  # type: ignore[index]
            f"reason:{index}" for index in range(17)
        ]
        huge_confidence = model_payload_v2()
        huge_confidence["semantic"]["references"][0]["confidence"] = (  # type: ignore[index]
            10**400
        )
        huge_base_confidence = model_payload_v2(confidence=10**400)

        for payload in (
            bool_offset,
            oversized_reasons,
            huge_confidence,
            huge_base_confidence,
        ):
            with self.subTest(payload=payload), self.assertRaises(DududaError):
                self._decode(payload)

    def test_slot_ceiling_and_unicode_digest_inputs_are_consistent(self) -> None:
        slot_refs = tuple(f"entity:{index}" for index in range(64))
        candidate = IntentCandidateV2(
            1,
            "intent:bounded",
            revision("intent-taxonomy"),
            slot_refs,
            0.5,
            ("message:current",),
        )
        self.assertEqual(candidate.slot_entity_refs, tuple(sorted(slot_refs)))
        with self.assertRaises(DududaError):
            replace(candidate, slot_entity_refs=slot_refs + ("entity:overflow",))

        for invalid_reason in ("Cafe\u0301", "\ud800"):
            with (
                self.subTest(reason=repr(invalid_reason)),
                self.assertRaises(DududaError),
            ):
                SemanticDecision(
                    1,
                    SemanticDecisionAction.CLARIFY,
                    revision("uncalibrated-pilot"),
                    revision("pilot-thresholds"),
                    (invalid_reason,),
                )


class SemanticTextOffsetTests(unittest.TestCase):
    def test_utf8_utf16_and_codepoint_offsets_map_to_nfc_text(self) -> None:
        raw = "Cafe\u0301 \U0001f600"
        normalized = normalized_text(raw)
        emoji_raw_index = raw.index("\U0001f600")
        utf8_start = len(raw[:emoji_raw_index].encode("utf-8"))
        utf8_end = len(raw.encode("utf-8"))
        utf16_start = len(raw[:emoji_raw_index].encode("utf-16-le")) // 2
        utf16_end = len(raw.encode("utf-16-le")) // 2

        self.assertEqual(normalized, "Caf\u00e9 \U0001f600")
        self.assertEqual(
            normalized_codepoint_span(
                raw,
                utf8_start,
                utf8_end,
                TextOffsetUnit.UTF8_BYTE,
            ),
            (5, 6),
        )
        self.assertEqual(
            normalized_codepoint_span(
                raw,
                utf16_start,
                utf16_end,
                TextOffsetUnit.UTF16_CODE_UNIT,
            ),
            (5, 6),
        )

    def test_split_or_normalization_unstable_boundaries_fail_closed(self) -> None:
        emoji = "\U0001f600"
        for unit in (TextOffsetUnit.UTF8_BYTE, TextOffsetUnit.UTF16_CODE_UNIT):
            with self.subTest(unit=unit), self.assertRaises(DududaError):
                normalized_codepoint_offset(emoji, 1, unit)

        with self.assertRaises(DududaError):
            normalized_codepoint_offset(
                "e\u0301",
                1,
                TextOffsetUnit.CODE_POINT,
            )
        with self.assertRaises(DududaError):
            normalized_codepoint_offset("text", True, TextOffsetUnit.CODE_POINT)

    def test_span_rejects_non_nfc_and_non_half_open_shapes(self) -> None:
        digest = semantic_text_digest("Caf\u00e9")
        with self.assertRaises(DududaError):
            TextSpan(1, "message:1", 0, 5, "Cafe\u0301", digest)
        with self.assertRaises(DududaError):
            TextSpan(1, "message:1", 1, 1, "x", digest)
        with self.assertRaises(DududaError):
            TextSpan(1, "message:1", True, 1, "x", digest)


class SemanticAuthorityValidationTests(unittest.TestCase):
    def _decode(self, payload: dict[str, object]):
        current = context()
        projection = decode_versioned_model_projection(
            freeze_json(payload),
            context_digest=perception_context_digest(current),
            projection_id="projection-v2",
            request_fingerprint=DigestString("request-fingerprint"),
            route_receipt_digest=DigestString("route-receipt"),
            component_revision=revision("model-perception"),
            semantic_component_revision=revision("semantic-v2"),
            taxonomy_revision=revision("intent-taxonomy"),
            calibration_revision=revision("uncalibrated-pilot"),
            threshold_policy_revision=revision("pilot-thresholds"),
        )
        return current, projection

    def test_bad_digest_surface_evidence_and_slot_refs_fail_closed(self) -> None:
        mutations = []
        bad_digest = model_payload_v2()
        bad_digest["semantic"]["references"][0]["mention_span"][  # type: ignore[index]
            "text_digest"
        ] = "wrong"
        mutations.append(bad_digest)

        bad_surface = model_payload_v2()
        bad_surface["semantic"]["references"][0]["mention_span"][  # type: ignore[index]
            "surface"
        ] = "those"
        mutations.append(bad_surface)

        bad_evidence = model_payload_v2()
        bad_evidence["semantic"]["references"][0]["evidence_refs"] = [  # type: ignore[index]
            "message:outside"
        ]
        bad_evidence["references"][0]["evidence_refs"] = [  # type: ignore[index]
            "message:outside"
        ]
        mutations.append(bad_evidence)

        bad_slot = model_payload_v2()
        bad_slot["semantic"]["intents"][0]["slot_entity_refs"] = [  # type: ignore[index]
            "entity:missing"
        ]
        mutations.append(bad_slot)

        for payload in mutations:
            with self.subTest(payload=payload), self.assertRaises(DududaError):
                current, projection = self._decode(payload)
                validate_versioned_model_projection(current, projection)

    def test_structural_links_require_connector_reply_or_mention_evidence(self) -> None:
        forged = model_payload_v2()
        forged["references"][0]["target_ref"] = "message:current"  # type: ignore[index]
        forged["semantic"]["references"][0]["target_ref"] = (  # type: ignore[index]
            "message:current"
        )
        current, projection = self._decode(forged)
        with self.assertRaises(DududaError):
            validate_versioned_model_projection(current, projection)

        linguistic = model_payload_v2()
        linguistic["semantic"]["references"][0]["link_source"] = (  # type: ignore[index]
            "linguistic"
        )
        current, projection = self._decode(linguistic)
        self.assertIs(
            validate_versioned_model_projection(current, projection),
            projection,
        )

    def test_direct_contract_construction_cannot_bypass_legacy_binding(self) -> None:
        current, projection = self._decode(model_payload_v2())
        semantic = projection.semantic
        self.assertIsNotNone(semantic)
        span = semantic.references[0].mention_span  # type: ignore[union-attr]
        entity = EntityMention(
            1,
            "entity:extra",
            EntityKind.ARTIFACT,
            span,
            "these",
            1.0,
            (current.current_message_ref,),
        )
        changed = replace(semantic, entities=(entity,))  # type: ignore[arg-type]
        with self.assertRaises(DududaError):
            VersionedModelPerceptionProjection(2, projection.base_projection, changed)

        unresolved = ReferenceMention(
            1,
            "reference:unresolved",
            ReferenceKind.UNRESOLVED,
            span,
            None,
            ReferenceLinkSource.LINGUISTIC,
            0.5,
            (current.current_message_ref,),
        )
        decision = SemanticDecision(
            1,
            SemanticDecisionAction.CLARIFY,
            revision("uncalibrated-pilot"),
            revision("pilot-thresholds"),
            ("ambiguous_reference",),
        )
        changed_semantic = SemanticProjectionV2(
            2,
            DigestString("wrong-base"),
            (),
            (unresolved,),
            (),
            revision("intent-taxonomy"),
            decision,
            revision("semantic-v2"),
        )
        with self.assertRaises(DududaError):
            VersionedModelPerceptionProjection(
                2,
                projection.base_projection,
                changed_semantic,
            )

    def test_accept_without_an_intent_fails_closed(self) -> None:
        payload = model_payload_v2()
        payload["intents"] = []
        payload["semantic"]["intents"] = []  # type: ignore[index]

        with self.assertRaises(DududaError):
            self._decode(payload)


if __name__ == "__main__":
    unittest.main()
