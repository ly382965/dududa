from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from dududa.capabilities.config import ConfigCapabilityRegistry
from dududa.capabilities.contracts import CapabilityCatalogSnapshot
from dududa.capabilities.registry import InMemoryCapabilityProviderRegistry
from dududa.errors import DududaError

from tests.unit.capabilities.test_registry import (
    NOW,
    FakeProvider,
    SchemaValidator,
    call,
    catalog_fixture,
    update_for,
)


def _thaw(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_thaw(item) for item in value]
    return value


def _schema_document(snapshot: CapabilityCatalogSnapshot, schema_ref):
    for document in snapshot.schema_documents:
        if document.schema_ref == schema_ref:
            return {
                "schema_id": schema_ref.schema_id,
                "schema_version": schema_ref.schema_version,
                "digest": str(schema_ref.digest),
                "document": _thaw(document.document),
            }
    raise AssertionError("schema not found")


def _definition_document(snapshot: CapabilityCatalogSnapshot):
    item = snapshot.definitions[0]
    descriptor = snapshot.provider_descriptors[0]
    revision = item.provider.revision
    return {
        "schema_version": item.schema_version,
        "capability_id": item.capability_id,
        "definition_digest": str(item.definition_digest),
        "name": item.name,
        "description": item.description,
        "category": item.category,
        "provider": {
            "provider_id": item.provider.provider_id,
            "revision": {
                "component_id": revision.component_id,
                "implementation_version": revision.implementation_version,
                "config_revision": revision.config_revision,
                "artifact_digest": str(revision.artifact_digest),
            },
        },
        "provider_kind": descriptor.kind.value,
        "input_schema": _schema_document(snapshot, item.input_schema),
        "output_schema": _schema_document(snapshot, item.output_schema),
        "risk_level": item.risk_level.value,
        "privacy_level": item.privacy_level.value,
        "allowed_contexts": sorted(value.value for value in item.allowed_contexts),
        "required_permissions": sorted(item.required_permissions),
        "cost_hint_units": item.cost_hint.units,
        "latency_hint": {
            "expected_ms": item.latency_hint.expected_ms,
            "maximum_ms": item.latency_hint.maximum_ms,
        },
        "tags": sorted(item.tags),
        "idempotency": item.idempotency.value,
        "side_effects": sorted(value.value for value in item.side_effects),
        "enabled": item.enabled,
    }


def _mapping_document(snapshot: CapabilityCatalogSnapshot):
    item = snapshot.mcp_mappings[0]
    return {
        "schema_version": item.schema_version,
        "capability_id": item.capability_id,
        "capability_definition_digest": str(item.capability_definition_digest),
        "server_id": item.server_id,
        "tool_name": item.tool_name,
        "expected_input_schema_digest": str(item.expected_input_schema_digest),
        "expected_output_schema_digest": (
            str(item.expected_output_schema_digest)
            if item.expected_output_schema_digest is not None
            else None
        ),
        "semantics": item.semantics.value,
        "fixed_arguments": _thaw(item.fixed_arguments),
        "argument_mapping_revision": item.argument_mapping_revision,
        "result_mapping_revision": item.result_mapping_revision,
        "enabled": item.enabled,
        "mapping_digest": str(item.mapping_digest),
    }


def _write_catalog(root: Path, snapshot: CapabilityCatalogSnapshot):
    definitions = root / "definitions"
    mappings = root / "mappings"
    definitions.mkdir(exist_ok=True)
    mappings.mkdir(exist_ok=True)
    capability_id = snapshot.definitions[0].capability_id
    (definitions / f"{capability_id}.json").write_text(
        json.dumps(_definition_document(snapshot), ensure_ascii=True),
        encoding="utf-8",
    )
    (mappings / f"{capability_id}.json").write_text(
        json.dumps(_mapping_document(snapshot), ensure_ascii=True),
        encoding="utf-8",
    )
    return definitions, mappings


def _registry(root: Path, snapshot: CapabilityCatalogSnapshot):
    definitions, mappings = _write_catalog(root, snapshot)
    provider = FakeProvider(snapshot.provider_descriptors[0])
    providers = InMemoryCapabilityProviderRegistry((provider,))
    identifiers = iter(("initial", "reload", "third"))
    registry = ConfigCapabilityRegistry(
        definitions,
        mappings,
        schema_validator=SchemaValidator(),
        provider_registry=providers,
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    return registry, definitions, mappings


class CapabilityConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_and_atomic_reload_use_content_addressed_revisions(self) -> None:
        source, _, _ = catalog_fixture()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry, _, _ = _registry(root, source)
            initial = registry.acquire_snapshot()
            self.assertEqual(initial.catalog_digest, source.catalog_digest)
            self.assertIs(await registry.reload(call=call()), initial)

            update = update_for(initial, 2)
            definition_path = next((root / "definitions").iterdir())
            mapping_path = next((root / "mappings").iterdir())
            fixture = SimpleNamespace(
                definitions=update.definitions,
                schema_documents=source.schema_documents,
                provider_descriptors=source.provider_descriptors,
                mcp_mappings=update.mcp_mappings,
            )
            definition_path.write_text(
                json.dumps(_definition_document(fixture)),
                encoding="utf-8",
            )
            mapping_path.write_text(
                json.dumps(_mapping_document(fixture)),
                encoding="utf-8",
            )
            reloaded = await registry.reload(call=call())
            self.assertNotEqual(reloaded.catalog_revision, initial.catalog_revision)
            self.assertEqual(reloaded.definitions[0].cost_hint.units, 2)

    async def test_invalid_reload_retains_same_last_known_good_object(self) -> None:
        source, _, _ = catalog_fixture()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry, definitions, _ = _registry(root, source)
            before = registry.acquire_snapshot()
            path = next(definitions.iterdir())
            path.write_text(
                '{"schema_version":1,"schema_version":1}',
                encoding="utf-8",
            )
            with self.assertRaises(DududaError):
                await registry.reload(call=call())
            self.assertIs(registry.acquire_snapshot(), before)

    def test_strict_loader_rejects_unknown_fields_filename_drift_and_symlink(
        self,
    ) -> None:
        source, _, _ = catalog_fixture()
        mutators = (
            self._add_unknown_field,
            self._rename_definition,
            self._add_symlink,
        )
        for mutate in mutators:
            with (
                self.subTest(mutate=mutate.__name__),
                TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                definitions, mappings = _write_catalog(root, source)
                mutate(definitions, mappings)
                provider = FakeProvider(source.provider_descriptors[0])
                with self.assertRaises(DududaError):
                    ConfigCapabilityRegistry(
                        definitions,
                        mappings,
                        schema_validator=SchemaValidator(),
                        provider_registry=InMemoryCapabilityProviderRegistry(
                            (provider,)
                        ),
                        clock=lambda: NOW,
                    )

    @staticmethod
    def _add_unknown_field(definitions: Path, mappings: Path) -> None:
        path = next(definitions.iterdir())
        document = json.loads(path.read_text(encoding="utf-8"))
        document["unknown"] = True
        path.write_text(json.dumps(document), encoding="utf-8")

    @staticmethod
    def _rename_definition(definitions: Path, mappings: Path) -> None:
        path = next(definitions.iterdir())
        path.rename(definitions / "wrong.v1.json")

    @staticmethod
    def _add_symlink(definitions: Path, mappings: Path) -> None:
        target = next(mappings.iterdir())
        (mappings / "linked.v1.json").symlink_to(target)


if __name__ == "__main__":
    unittest.main()
