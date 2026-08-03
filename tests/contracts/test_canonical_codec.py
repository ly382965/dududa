from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import unittest

from dududa.contracts.canonical import (
    canonical_digest,
    canonical_json_bytes,
    canonical_schema_digest,
    verify_canonical_digest,
)
from dududa.errors import DududaError


ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "scripts" / "contract-vectors" / "c14n-v1.json"


def decode_tagged(value: object) -> object:
    if isinstance(value, list):
        return [decode_tagged(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$datetime"}:
            return datetime.fromisoformat(str(value["$datetime"]))
        if set(value) == {"$decimal"}:
            return Decimal(str(value["$decimal"]))
        if set(value) == {"$set"}:
            return set(decode_tagged(item) for item in value["$set"])
        if set(value) == {"$duration_microseconds"}:
            return timedelta(microseconds=int(value["$duration_microseconds"]))
        return {key: decode_tagged(item) for key, item in value.items()}
    return value


class CanonicalCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vectors = json.loads(VECTORS.read_text(encoding="utf-8"))

    def test_shared_golden_vectors(self) -> None:
        for vector in self.vectors["valid"]:
            with self.subTest(vector=vector["name"]):
                value = decode_tagged(vector["input"])
                self.assertEqual(
                    canonical_json_bytes(value).decode("utf-8"),
                    vector["canonical_json"],
                )
                self.assertEqual(
                    canonical_digest(value, domain=vector["domain"]),
                    vector["digest"],
                )

    def test_domain_separation_and_tamper_detection(self) -> None:
        value = {"message_id": "m-1", "text": "hello"}
        digest = canonical_digest(value, domain="message-envelope:v1")
        other_digest = canonical_digest(value, domain="authorization-request:v1")
        self.assertNotEqual(
            str(digest).rsplit(":", 1)[-1], str(other_digest).rsplit(":", 1)[-1]
        )
        self.assertTrue(
            verify_canonical_digest(value, digest, domain="message-envelope:v1")
        )
        self.assertFalse(
            verify_canonical_digest(
                {"message_id": "m-1", "text": "changed"},
                digest,
                domain="message-envelope:v1",
            )
        )
        self.assertFalse(
            verify_canonical_digest(value, digest, domain="authorization-request:v1")
        )
        self.assertEqual(
            canonical_json_bytes(timedelta(days=30)).decode("utf-8"),
            '"PT2592000.000000S"',
        )
        self.assertEqual(
            canonical_json_bytes(datetime(1, 1, 1, tzinfo=timezone.utc)).decode(
                "utf-8"
            )[:5],
            '"0001',
        )

    def test_rejects_ambiguous_or_unsafe_values(self) -> None:
        cyclic: list[object] = []
        cyclic.append(cyclic)
        cases = (
            datetime(2025, 1, 1),
            Decimal("Infinity"),
            float("nan"),
            b"secret",
            {"é": 1, "e\u0301": 2},
            cyclic,
        )
        for value in cases:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(DududaError):
                    canonical_json_bytes(value)

    def test_schema_bundle_forbids_remote_refs(self) -> None:
        local = {"$defs": {"name": {"type": "string"}}, "$ref": "#/$defs/name"}
        digest = canonical_schema_digest(local, schema_id="message", schema_version=1)
        self.assertTrue(str(digest).startswith("dududa-c14n-v1:schema:message:v1:"))
        for reference in (
            "https://example.invalid/schema.json",
            "file:///tmp/schema.json",
            "ftp://example.invalid/schema.json",
            "urn:example:schema",
            "relative/schema.json",
        ):
            with self.subTest(reference=reference), self.assertRaises(DududaError):
                canonical_schema_digest(
                    {"$ref": reference},
                    schema_id="message",
                    schema_version=1,
                )
        for keyword in ("$dynamicRef", "$recursiveRef"):
            with self.subTest(keyword=keyword), self.assertRaises(DududaError):
                canonical_schema_digest(
                    {keyword: "https://example.invalid/schema.json"},
                    schema_id="message",
                    schema_version=1,
                )


if __name__ == "__main__":
    unittest.main()
