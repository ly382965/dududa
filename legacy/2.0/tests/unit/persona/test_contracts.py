from __future__ import annotations

import unittest
from dataclasses import replace

from dududa.domain.primitives import ConversationType, DigestString
from dududa.errors import DududaError
from dududa.persona.contracts import (
    PersonaCatalogSnapshot,
    PersonaCatalogUpdate,
    PersonaChannelStyle,
    PersonaDefinition,
    persona_catalog_digest,
    persona_definition_source_digest,
)

from tests.unit.persona._fixtures import NOW, definition


class PersonaContractTests(unittest.TestCase):
    def test_definition_is_digest_bound_and_channel_mapping_is_immutable(self) -> None:
        item = definition()

        self.assertEqual(item.source_digest, persona_definition_source_digest(item))
        self.assertEqual(set(item.channel_rules), set(ConversationType))
        with self.assertRaises(TypeError):
            item.channel_rules[ConversationType.GROUP] = PersonaChannelStyle(  # type: ignore[index]
                schema_version=1,
                tone_tags=("changed",),
                emoji_budget=0,
                prefer_short_sentences=True,
            )

        with self.assertRaises(DududaError) as caught:
            replace(item, display_name="changed")
        self.assertEqual(caught.exception.info.code, "persona_source_digest_mismatch")

    def test_snapshot_requires_sorted_unique_digest_bound_definitions(self) -> None:
        definitions = (definition(), definition("neutral"))
        digest = persona_catalog_digest(1, definitions, "neutral", "1.0.0")
        snapshot = PersonaCatalogSnapshot(
            schema_version=1,
            snapshot_id="snapshot-1",
            revision=1,
            definitions=definitions,
            fallback_persona_id="neutral",
            fallback_version="1.0.0",
            acquired_at=NOW,
            catalog_digest=digest,
        )
        self.assertEqual(snapshot.catalog_digest, digest)

        with self.assertRaises(DududaError) as caught:
            replace(snapshot, catalog_digest=DigestString("tampered"))
        self.assertEqual(caught.exception.info.code, "persona_catalog_digest_mismatch")

        with self.assertRaises(DududaError) as caught:
            PersonaCatalogUpdate(
                schema_version=1,
                expected_revision=1,
                definitions=(definitions[0], definitions[0]),
            )
        self.assertEqual(caught.exception.info.code, "duplicate_persona_version")

    def test_definition_rejects_missing_channel_and_wrong_digest_type(self) -> None:
        item = definition()
        with self.assertRaises(DududaError) as caught:
            PersonaDefinition(
                schema_version=1,
                persona_id=item.persona_id,
                version=item.version,
                display_name=item.display_name,
                default_locale=item.default_locale,
                voice=item.voice,
                channel_rules={
                    ConversationType.GROUP: item.channel_rules[ConversationType.GROUP]
                },
                renderer_mode=item.renderer_mode,
                safety_note_ids=item.safety_note_ids,
                source_digest=item.source_digest,
            )
        self.assertEqual(caught.exception.info.code, "invalid_persona_channel_rules")

        with self.assertRaises(DududaError) as caught:
            replace(item, source_digest=object())  # type: ignore[arg-type]
        self.assertEqual(caught.exception.info.code, "invalid_persona_source_digest")

    def test_malformed_direct_inputs_and_unbounded_semver_are_normalized(self) -> None:
        item = definition()
        cases = (
            (lambda: replace(item, persona_id=None), "invalid_persona_id"),  # type: ignore[arg-type]
            (
                lambda: replace(item, version="1" + "0" * 5000 + ".0.0"),
                "invalid_persona_version",
            ),
            (
                lambda: replace(item, display_name=None),  # type: ignore[arg-type]
                "invalid_persona_definition_field",
            ),
            (
                lambda: PersonaCatalogUpdate(1, 1, None),  # type: ignore[arg-type]
                "empty_persona_catalog_update",
            ),
        )
        for build, code in cases:
            with self.subTest(code=code), self.assertRaises(DududaError) as caught:
                build()
            self.assertEqual(caught.exception.info.code, code)


if __name__ == "__main__":
    unittest.main()
