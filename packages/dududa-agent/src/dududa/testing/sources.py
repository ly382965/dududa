from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import PrivacyLevel, freeze_json
from dududa.errors import DududaError, validation_error
from dududa.ports.context import PortCallContext
from dududa.proactive.source_contracts import (
    SourceCapabilityObservation,
    SourceCursor,
    SourceDefinition,
    SourceFetchRequest,
)

_MANIFEST_KEYS = {"schema_version", "fixture_kind", "bundle_revision", "sources"}
_SOURCE_KEYS = {"source_id", "file", "sha256"}
_FIXTURE_KEYS = {
    "schema_version",
    "source_id",
    "capability_id",
    "provider_id",
    "provider_generation",
    "source_snapshot_revision",
    "next_cursor_token",
    "observed_at",
    "data",
}


class FixtureSourceCapabilityReader:
    def __init__(
        self,
        fixtures: Mapping[str, Mapping[str, object]],
        *,
        failures: Mapping[str, DududaError] | None = None,
    ) -> None:
        values = {key: dict(value) for key, value in fixtures.items()}
        if not values or any(
            key != value.get("source_id") for key, value in values.items()
        ):
            raise validation_error("invalid_source_fixture_mapping")
        scripted = dict(failures or {})
        if any(not isinstance(value, DududaError) for value in scripted.values()):
            raise validation_error("invalid_source_fixture_failure")
        self._fixtures = values
        self._failures = scripted
        self.calls: list[tuple[str, SourceCursor | None, str]] = []

    async def read(
        self,
        definition: SourceDefinition,
        cursor: SourceCursor | None,
        request: SourceFetchRequest,
        *,
        call: PortCallContext,
    ) -> SourceCapabilityObservation:
        if not isinstance(definition, SourceDefinition) or not isinstance(
            request, SourceFetchRequest
        ):
            raise validation_error("invalid_source_fixture_request")
        self.calls.append((definition.source_id, cursor, request.request_digest))
        failure = self._failures.get(definition.source_id)
        if failure is not None:
            raise failure
        fixture = self._fixtures.get(definition.source_id)
        if fixture is None:
            raise validation_error("source_fixture_not_found")
        _exact_keys(fixture, _FIXTURE_KEYS, "source_fixture")
        if (
            type(fixture["schema_version"]) is not int
            or fixture["schema_version"] != 1
            or fixture["capability_id"] != definition.capability_id
        ):
            raise validation_error("source_fixture_definition_mismatch")
        data = fixture["data"]
        if not isinstance(data, Mapping):
            raise validation_error("invalid_source_fixture_data")
        frozen = freeze_json(dict(data))
        if not isinstance(frozen, Mapping):
            raise validation_error("invalid_source_fixture_data")
        observed_at = _datetime(fixture["observed_at"], "fixture_observed_at")
        provider_result_digest = canonical_digest(
            {
                "source_id": definition.source_id,
                "capability_id": definition.capability_id,
                "data": frozen,
                "observed_at": observed_at,
            },
            domain="proactive:fixture-provider-result:v1",
        )
        return SourceCapabilityObservation(
            schema_version=1,
            source_id=definition.source_id,
            capability_id=definition.capability_id,
            capability_definition_digest=definition.capability_definition_digest,
            provider_id=_string(fixture["provider_id"], "provider_id"),
            provider_generation=_integer(
                fixture["provider_generation"],
                "provider_generation",
            ),
            provider_result_digest=provider_result_digest,
            schema_revision=definition.schema_revision,
            result_mapping_revision=definition.result_mapping_revision,
            source_snapshot_revision=_string(
                fixture["source_snapshot_revision"],
                "source_snapshot_revision",
            ),
            next_cursor_token=_string(
                fixture["next_cursor_token"],
                "next_cursor_token",
            ),
            data=frozen,
            sensitivity=PrivacyLevel.PUBLIC,
            observed_at=observed_at,
            truncated=False,
        )


def load_source_fixture_bundle(directory: Path) -> dict[str, Mapping[str, object]]:
    root = Path(directory).resolve()
    manifest_path = root / "manifest.json"
    manifest = _json_object(manifest_path.read_bytes(), "source_fixture_manifest")
    _exact_keys(manifest, _MANIFEST_KEYS, "source_fixture_manifest")
    if (
        manifest["schema_version"] != 1
        or manifest["fixture_kind"] != "synthetic_governed_sources"
        or manifest["bundle_revision"] != "source-fixtures-v1"
    ):
        raise validation_error("invalid_source_fixture_manifest")
    sources = manifest["sources"]
    if not isinstance(sources, list) or not sources:
        raise validation_error("invalid_source_fixture_manifest_sources")
    result: dict[str, Mapping[str, object]] = {}
    for entry in sources:
        if not isinstance(entry, dict):
            raise validation_error("invalid_source_fixture_manifest_entry")
        _exact_keys(entry, _SOURCE_KEYS, "source_fixture_manifest_entry")
        source_id = _string(entry["source_id"], "source_id")
        relative = Path(_string(entry["file"], "fixture_file"))
        if relative.is_absolute() or ".." in relative.parts:
            raise validation_error("invalid_source_fixture_path")
        path = (root / relative).resolve()
        if path.parent != root:
            raise validation_error("invalid_source_fixture_path")
        payload = path.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != entry["sha256"]:
            raise validation_error("source_fixture_digest_mismatch")
        document = _json_object(payload, "source_fixture")
        _exact_keys(document, _FIXTURE_KEYS, "source_fixture")
        if document["source_id"] != source_id or source_id in result:
            raise validation_error("source_fixture_identity_mismatch")
        result[source_id] = document
    return result


def _json_object(payload: bytes, field_name: str) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, ValueError):
        raise validation_error("invalid_source_fixture_json", field_name) from None
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise validation_error("invalid_source_fixture_json", field_name)
    return value


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise validation_error("invalid_source_fixture_fields", field_name)


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise validation_error("invalid_source_fixture_string", field_name)
    return value


def _integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise validation_error("invalid_source_fixture_integer", field_name)
    return value


def _datetime(value: object, field_name: str) -> datetime:
    raw = _string(value, field_name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise validation_error("invalid_source_fixture_datetime", field_name) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise validation_error("invalid_source_fixture_datetime", field_name)
    return parsed.astimezone(timezone.utc)


__all__ = ["FixtureSourceCapabilityReader", "load_source_fixture_bundle"]
