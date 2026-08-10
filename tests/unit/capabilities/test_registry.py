from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from dududa.capabilities.contracts import (
    CapabilityCatalogSnapshot,
    CapabilityCatalogUpdate,
    CapabilityProviderDescriptor,
    CapabilityResult,
    CapabilitySchemaDocument,
    ProviderInvocation,
)
from dududa.capabilities.digests import (
    capability_catalog_digest,
    capability_catalog_update_digest,
    mcp_capability_mapping_digest,
)
from dududa.capabilities.registry import (
    InMemoryCapabilityProviderRegistry,
    InMemoryCapabilityRegistry,
)
from dududa.domain.capability import CostHint, capability_definition_digest
from dududa.domain.primitives import DigestString, RuntimeBudget, TraceContext
from dududa.errors import DududaError, validation_error
from dududa.ports.context import NeverCancelled, ServiceCallContext, ServicePrincipal

from astrbot_plugin_dududa_core.adapters.mcp_schema import (
    JsonSchemaCapabilityValidator,
)
from tests.unit.capabilities.test_contracts import (
    NOW,
    catalog_values,
    definition,
    mapping,
    provider_descriptor,
    schema,
)


class SchemaValidator:
    def __init__(self) -> None:
        self.reject = False
        self.checked: list[str] = []

    def check_schema(self, document: CapabilitySchemaDocument) -> None:
        self.checked.append(document.schema_ref.schema_id)
        if self.reject:
            raise validation_error("fixture_schema_rejected")

    def validate(self, value, document: CapabilitySchemaDocument):
        return value


class FakeProvider:
    def __init__(self, descriptor: CapabilityProviderDescriptor) -> None:
        self._descriptor = descriptor
        self.close_calls = 0

    @property
    def descriptor(self) -> CapabilityProviderDescriptor:
        return self._descriptor

    async def health(self, *, call):
        raise NotImplementedError

    async def invoke(
        self,
        request: ProviderInvocation,
        *,
        call,
    ) -> CapabilityResult:
        raise NotImplementedError

    async def close(self) -> None:
        self.close_calls += 1


def call() -> ServiceCallContext:
    return ServiceCallContext(
        operation_id="catalog-publish",
        principal=ServicePrincipal("tests", "one", frozenset({"catalog-admin"})),
        operation_kind="capability.catalog.publish",
        trace=TraceContext("trace-catalog"),
        deadline=NOW + timedelta(minutes=1),
        cancellation=NeverCancelled(),
        budget=RuntimeBudget(0, 0, 0, 0, 0, None),
        policy_snapshot_id="policy-v1",
    )


def catalog_fixture():
    input_document = schema("capability.icourse.search.input")
    output_document = schema("capability.icourse.search.output")
    item = definition(input_document.schema_ref, output_document.schema_ref)
    descriptor = provider_descriptor(item)
    formal_mapping = mapping(item)
    values = catalog_values(
        (item,),
        (input_document, output_document),
        (descriptor,),
        (formal_mapping,),
    )
    snapshot = CapabilityCatalogSnapshot(
        snapshot_id="capability-catalog:initial",
        catalog_digest=capability_catalog_digest(values),
        acquired_at=NOW,
        **values,
    )
    return snapshot, item, descriptor


def update_for(
    snapshot: CapabilityCatalogSnapshot,
    cost_units: int,
    *,
    bump_provider_revision: bool = False,
):
    current = snapshot.definitions[0]
    provider = current.provider
    if bump_provider_revision:
        provider = replace(
            provider,
            revision=replace(
                provider.revision,
                config_revision=f"cfg-v{cost_units}",
                artifact_digest=DigestString(f"artifact-v{cost_units}"),
            ),
        )
    definition_values = {
        "schema_version": current.schema_version,
        "capability_id": current.capability_id,
        "name": current.name,
        "description": current.description,
        "category": current.category,
        "provider": provider,
        "input_schema": current.input_schema,
        "output_schema": current.output_schema,
        "risk_level": current.risk_level,
        "privacy_level": current.privacy_level,
        "allowed_contexts": current.allowed_contexts,
        "required_permissions": current.required_permissions,
        "cost_hint": CostHint(cost_units),
        "latency_hint": current.latency_hint,
        "tags": current.tags,
        "idempotency": current.idempotency,
        "side_effects": current.side_effects,
        "enabled": current.enabled,
    }
    revised = type(current)(
        definition_digest=capability_definition_digest(definition_values),
        **definition_values,
    )
    content = catalog_values(
        (revised,),
        snapshot.schema_documents,
        (provider_descriptor(revised),),
        (mapping(revised),),
    )
    values = {
        **content,
        "expected_revision": snapshot.catalog_revision,
    }
    return CapabilityCatalogUpdate(
        update_digest=capability_catalog_update_digest(values),
        **values,
    )


def mapping_update(
    snapshot: CapabilityCatalogSnapshot,
    enabled: bool,
) -> CapabilityCatalogUpdate:
    current = snapshot.mcp_mappings[0]
    mapping_values = {
        name: getattr(current, name)
        for name in current.__dataclass_fields__
        if name not in {"enabled", "mapping_digest"}
    }
    mapping_values["enabled"] = enabled
    revised = replace(
        current,
        enabled=enabled,
        mapping_digest=mcp_capability_mapping_digest(mapping_values),
    )
    content = catalog_values(
        snapshot.definitions,
        snapshot.schema_documents,
        snapshot.provider_descriptors,
        (revised,),
    )
    values = {**content, "expected_revision": snapshot.catalog_revision}
    return CapabilityCatalogUpdate(
        update_digest=capability_catalog_update_digest(values),
        **values,
    )


def snapshot_with_mapping(
    snapshot: CapabilityCatalogSnapshot,
    **changes,
) -> CapabilityCatalogSnapshot:
    current = snapshot.mcp_mappings[0]
    values = {
        name: getattr(current, name)
        for name in current.__dataclass_fields__
        if name != "mapping_digest"
    }
    values.update(changes)
    revised = replace(
        current,
        mapping_digest=mcp_capability_mapping_digest(values),
        **changes,
    )
    content = catalog_values(
        snapshot.definitions,
        snapshot.schema_documents,
        snapshot.provider_descriptors,
        (revised,),
    )
    return CapabilityCatalogSnapshot(
        snapshot_id=f"{snapshot.snapshot_id}-mapping-policy",
        catalog_digest=capability_catalog_digest(content),
        acquired_at=NOW,
        **content,
    )


def update_with_mapping(
    update: CapabilityCatalogUpdate,
    **changes,
) -> CapabilityCatalogUpdate:
    current = update.mcp_mappings[0]
    mapping_values = {
        name: getattr(current, name)
        for name in current.__dataclass_fields__
        if name != "mapping_digest"
    }
    mapping_values.update(changes)
    revised = replace(
        current,
        mapping_digest=mcp_capability_mapping_digest(mapping_values),
        **changes,
    )
    content = catalog_values(
        update.definitions,
        update.schema_documents,
        update.provider_descriptors,
        (revised,),
    )
    values = {**content, "expected_revision": update.expected_revision}
    return CapabilityCatalogUpdate(
        update_digest=capability_catalog_update_digest(values),
        **values,
    )


class CapabilityRegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.snapshot, self.definition, self.descriptor = catalog_fixture()
        self.provider = FakeProvider(self.descriptor)
        self.providers = InMemoryCapabilityProviderRegistry((self.provider,))
        self.schemas = SchemaValidator()
        identifiers = iter(("next", "third", "fourth"))
        self.registry = InMemoryCapabilityRegistry(
            self.snapshot,
            schema_validator=self.schemas,
            provider_registry=self.providers,
            clock=lambda: NOW,
            id_factory=lambda: next(identifiers),
            history_limit=2,
        )

    def test_snapshot_lookup_and_provider_resolution_require_exact_bindings(
        self,
    ) -> None:
        acquired = self.registry.acquire_snapshot()
        self.assertIs(acquired, self.snapshot)
        self.assertEqual(
            self.registry.get_definition(acquired, self.definition.capability_id),
            self.definition,
        )
        self.assertEqual(
            self.registry.get_schema(acquired, self.definition.input_schema),
            acquired.schema_documents[0],
        )
        self.assertEqual(
            self.registry.get_mcp_mapping(acquired, self.definition.capability_id),
            acquired.mcp_mappings[0],
        )
        self.assertIs(
            self.providers.resolve(acquired, self.definition.provider),
            self.provider,
        )
        with self.assertRaises(DududaError):
            self.providers.resolve(
                acquired,
                replace(
                    self.definition.provider,
                    revision=replace(
                        self.definition.provider.revision,
                        config_revision="drifted",
                    ),
                ),
            )

    async def test_publish_is_atomic_cas_and_history_bounded(self) -> None:
        first_update = update_for(
            self.snapshot,
            2,
            bump_provider_revision=True,
        )
        self.providers.register(FakeProvider(first_update.provider_descriptors[0]))
        first = await self.registry.publish(
            first_update,
            call=call(),
        )
        current = self.registry.acquire_snapshot()
        self.assertEqual(first.previous_revision, self.snapshot.catalog_revision)
        self.assertNotEqual(current.catalog_revision, self.snapshot.catalog_revision)
        with self.assertRaises(DududaError):
            await self.registry.publish(
                update_for(self.snapshot, 4),
                call=call(),
            )
        second_update = update_for(current, 3, bump_provider_revision=True)
        self.providers.register(FakeProvider(second_update.provider_descriptors[0]))
        await self.registry.publish(second_update, call=call())
        with self.assertRaises(DududaError):
            self.registry.snapshot_by_id(self.snapshot.snapshot_id)

    async def test_invalid_schema_publish_retains_last_known_good(self) -> None:
        before = self.registry.acquire_snapshot()
        update = update_for(before, 2, bump_provider_revision=True)
        self.providers.register(FakeProvider(update.provider_descriptors[0]))
        self.schemas.reject = True
        with self.assertRaises(DududaError):
            await self.registry.publish(
                update,
                call=call(),
            )
        self.assertIs(self.registry.acquire_snapshot(), before)

    async def test_same_provider_revision_allows_revocation_only(self) -> None:
        revoked = await self.registry.publish(
            mapping_update(self.snapshot, False),
            call=call(),
        )
        current = self.registry.snapshot_by_id(revoked.snapshot_id)
        self.assertFalse(current.mcp_mappings[0].enabled)

        with self.assertRaises(DududaError) as definition_change:
            await self.registry.publish(update_for(current, 2), call=call())
        self.assertEqual(
            definition_change.exception.info.code,
            "retired_capability_requires_provider_revision",
        )
        with self.assertRaises(DududaError) as reenable:
            await self.registry.publish(mapping_update(current, True), call=call())
        self.assertEqual(
            reenable.exception.info.code,
            "retired_capability_requires_provider_revision",
        )
        self.assertIs(self.registry.acquire_snapshot(), current)

    async def test_snapshot_id_cannot_be_rebound(self) -> None:
        conflicting = InMemoryCapabilityRegistry(
            self.snapshot,
            schema_validator=self.schemas,
            provider_registry=self.providers,
            clock=lambda: NOW,
            id_factory=lambda: "initial",
        )
        with self.assertRaises(DududaError) as snapshot_error:
            await conflicting.publish(
                update_for(self.snapshot, 2),
                call=call(),
            )
        self.assertEqual(
            snapshot_error.exception.info.code,
            "capability_catalog_snapshot_id_conflict",
        )

    def test_provider_resolution_rejects_foreign_catalog_handle(self) -> None:
        foreign = replace(self.snapshot, snapshot_id="catalog:foreign")
        with self.assertRaises(DududaError) as raised:
            self.providers.resolve(foreign, self.definition.provider)
        self.assertEqual(
            raised.exception.info.code,
            "unbound_capability_catalog_snapshot",
        )

    def test_unknown_provider_revision_rejects_initial_catalog(self) -> None:
        empty = InMemoryCapabilityProviderRegistry()
        with self.assertRaises(DududaError):
            InMemoryCapabilityRegistry(
                self.snapshot,
                schema_validator=self.schemas,
                provider_registry=empty,
                clock=lambda: NOW,
            )

    def test_initial_catalog_rejects_unsupported_or_invalid_mapping_policy(
        self,
    ) -> None:
        cases = (
            {"argument_mapping_revision": "unsupported-v1"},
            {"fixed_arguments": {"unknown": 1}},
            {"fixed_arguments": {"limit": "twenty"}},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(DududaError):
                InMemoryCapabilityRegistry(
                    snapshot_with_mapping(self.snapshot, **changes),
                    schema_validator=JsonSchemaCapabilityValidator(),
                    provider_registry=self.providers,
                    clock=lambda: NOW,
                )

    async def test_publish_validates_mapping_policy_before_replacing_lkg(self) -> None:
        provider_update = update_for(
            self.snapshot,
            2,
            bump_provider_revision=True,
        )
        self.providers.register(FakeProvider(provider_update.provider_descriptors[0]))
        invalid = update_with_mapping(
            provider_update,
            result_mapping_revision="unsupported-v1",
        )

        with self.assertRaises(DududaError):
            await self.registry.publish(invalid, call=call())

        self.assertIs(self.registry.acquire_snapshot(), self.snapshot)

    async def test_provider_registry_closes_each_instance_once(self) -> None:
        self.providers.register(self.provider)
        await self.providers.close()
        self.assertEqual(self.provider.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
