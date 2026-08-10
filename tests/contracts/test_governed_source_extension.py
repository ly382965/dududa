from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from dududa.errors import DududaError
from dududa.proactive.contracts import SourceCategory
from dududa.proactive.source_contracts import (
    SourceFetchStatus,
    SourceIdentityRule,
)
from dududa.testing.sources import load_source_fixture_bundle

from tests.unit.proactive._source_fixtures import (
    SOURCE_FIXTURE_DIRECTORY,
    GovernedSourceFixture,
    source_definition,
    source_definitions,
)


class GovernedSourceExtensionContractTests(unittest.IsolatedAsyncioTestCase):
    def test_manifest_binds_every_fixture_payload(self) -> None:
        loaded = load_source_fixture_bundle(SOURCE_FIXTURE_DIRECTORY)
        self.assertEqual(
            set(loaded),
            {"arxiv-fixture", "campus-fixture", "industry-fixture"},
        )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "sources"
            shutil.copytree(SOURCE_FIXTURE_DIRECTORY, root)
            campus = root / "campus.json"
            campus.write_bytes(campus.read_bytes() + b" ")
            with self.assertRaises(DududaError) as caught:
                load_source_fixture_bundle(root)
            self.assertEqual(
                caught.exception.info.code,
                "source_fixture_digest_mismatch",
            )

    async def test_fourth_source_needs_only_definition_fixture_and_binding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "sources"
            shutil.copytree(SOURCE_FIXTURE_DIRECTORY, root)
            fixture_path = root / "lab.json"
            document = {
                "schema_version": 1,
                "source_id": "lab-fixture",
                "capability_id": "lab.list_public_briefs.v1",
                "provider_id": "fixture-capability-provider",
                "provider_generation": 1,
                "source_snapshot_revision": "lab-snapshot-v1",
                "next_cursor_token": "lab-cursor-v1",
                "observed_at": "2026-08-09T00:00:00Z",
                "data": {
                    "schema_version": 1,
                    "items": [
                        {
                            "external_id": "lab-brief-001",
                            "title": "Synthetic lab brief",
                            "summary": "Fixture-only extension contract metadata.",
                            "canonical_url": "https://labs.example.net/briefs/001",
                            "published_at": "2026-08-08T12:00:00Z",
                            "source_revision": "lab-v1",
                        }
                    ],
                },
            }
            payload = (json.dumps(document, indent=2) + "\n").encode()
            fixture_path.write_bytes(payload)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["sources"].append(
                {
                    "source_id": "lab-fixture",
                    "file": "lab.json",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

            lab_definition = source_definition(
                "lab-fixture",
                SourceCategory.CAMPUS,
                "lab.list_public_briefs.v1",
                "labs.example.net",
                "/briefs",
                SourceIdentityRule.EXTERNAL_ID,
            )
            fixture = GovernedSourceFixture(
                definitions=source_definitions() + (lab_definition,),
                fixtures=load_source_fixture_bundle(root),
            )

            receipt = await fixture.provider.fetch(
                fixture.request,
                call=fixture.call(),
            )

            self.assertEqual(receipt.status, SourceFetchStatus.SUCCEEDED)
            self.assertEqual(len(receipt.batch.items), 4)
            self.assertIn("lab-fixture", receipt.batch.succeeded_sources)


if __name__ == "__main__":
    unittest.main()
