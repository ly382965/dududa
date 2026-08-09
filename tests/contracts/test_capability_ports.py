from __future__ import annotations

import unittest

import dududa.ports as public_ports
from dududa.ports.capabilities import (
    ArgumentBinder,
    BoundedCapabilityRuntime,
    CapabilityCatalogPublisher,
    CapabilityHealthRegistry,
    CapabilityProvider,
    CapabilityProviderRegistry,
    CapabilityRegistry,
    CapabilityRetriever,
    CapabilitySchemaValidator,
    ToolExecutor,
    ToolInvocationLedger,
    ToolPlanner,
    ToolPlanValidator,
    ToolResultValidator,
)


class _SchemaValidator:
    def check_schema(self, document):
        return None

    def validate(self, value, document):
        return value


class _Registry:
    def acquire_snapshot(self):
        raise NotImplementedError

    def snapshot_by_id(self, snapshot_id, *, expected_digest=None):
        raise NotImplementedError

    def get_definition(self, snapshot, capability_id):
        raise NotImplementedError

    def get_schema(self, snapshot, schema_ref):
        raise NotImplementedError

    def get_mcp_mapping(self, snapshot, capability_id):
        raise NotImplementedError


class _Publisher:
    async def publish(self, update, *, call):
        raise NotImplementedError


class _ProviderRegistry:
    def resolve(self, snapshot, provider):
        raise NotImplementedError


class _HealthRegistry:
    async def snapshot(self, providers, *, call):
        raise NotImplementedError


class _Retriever:
    async def retrieve(self, request, *, call):
        raise NotImplementedError


class _Planner:
    async def plan(self, request, *, call):
        raise NotImplementedError


class _PlanValidator:
    def validate(self, request):
        raise NotImplementedError


class _Binder:
    def bind(self, request):
        raise NotImplementedError


class _Provider:
    @property
    def descriptor(self):
        raise NotImplementedError

    async def health(self, *, call):
        raise NotImplementedError

    async def invoke(self, request, *, call):
        raise NotImplementedError

    async def close(self):
        return None


class _Executor:
    async def execute(self, request, *, call):
        raise NotImplementedError


class _ResultValidator:
    async def validate(self, request, *, call):
        raise NotImplementedError


class _Ledger:
    async def acquire(self, request, *, call):
        raise NotImplementedError

    async def complete(self, claim, observation, *, call):
        raise NotImplementedError

    async def wait(self, claim, *, call):
        raise NotImplementedError


class _Runtime:
    async def run(self, request, *, call):
        raise NotImplementedError


class CapabilityPortContractTests(unittest.TestCase):
    def test_ports_are_runtime_checkable_and_framework_neutral(self) -> None:
        implementations = (
            (_SchemaValidator(), CapabilitySchemaValidator),
            (_Registry(), CapabilityRegistry),
            (_Publisher(), CapabilityCatalogPublisher),
            (_ProviderRegistry(), CapabilityProviderRegistry),
            (_HealthRegistry(), CapabilityHealthRegistry),
            (_Retriever(), CapabilityRetriever),
            (_Planner(), ToolPlanner),
            (_PlanValidator(), ToolPlanValidator),
            (_Binder(), ArgumentBinder),
            (_Provider(), CapabilityProvider),
            (_Executor(), ToolExecutor),
            (_ResultValidator(), ToolResultValidator),
            (_Ledger(), ToolInvocationLedger),
            (_Runtime(), BoundedCapabilityRuntime),
        )
        for implementation, protocol in implementations:
            with self.subTest(protocol=protocol.__name__):
                self.assertIsInstance(implementation, protocol)

    def test_public_port_exports_resolve_to_the_owning_module(self) -> None:
        expected = {
            "ArgumentBinder": ArgumentBinder,
            "BoundedCapabilityRuntime": BoundedCapabilityRuntime,
            "CapabilityCatalogPublisher": CapabilityCatalogPublisher,
            "CapabilityHealthRegistry": CapabilityHealthRegistry,
            "CapabilityProvider": CapabilityProvider,
            "CapabilityProviderRegistry": CapabilityProviderRegistry,
            "CapabilityRegistry": CapabilityRegistry,
            "CapabilityRetriever": CapabilityRetriever,
            "CapabilitySchemaValidator": CapabilitySchemaValidator,
            "ToolExecutor": ToolExecutor,
            "ToolInvocationLedger": ToolInvocationLedger,
            "ToolPlanner": ToolPlanner,
            "ToolPlanValidator": ToolPlanValidator,
            "ToolResultValidator": ToolResultValidator,
        }
        self.assertLessEqual(set(expected), set(public_ports.__all__))
        for name, protocol in expected.items():
            with self.subTest(name=name):
                self.assertIs(getattr(public_ports, name), protocol)


if __name__ == "__main__":
    unittest.main()
