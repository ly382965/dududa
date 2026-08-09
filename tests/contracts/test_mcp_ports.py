from __future__ import annotations

import unittest

from dududa.ports.mcp import (
    McpEnvironmentProvider,
    McpSchemaValidator,
    McpSecretResolver,
    McpServerRegistry,
    McpTransportSession,
    McpTransportSessionFactory,
    UnifiedMcpClient,
)


class _Client:
    async def discover(self, server_id, *, refresh=False, call):
        raise NotImplementedError

    async def call_tool(self, server_id, tool_name, arguments, *, call):
        raise NotImplementedError

    async def health(self, server_id, *, call):
        raise NotImplementedError

    async def close(self):
        return None


class _Registry:
    def acquire_snapshot(self):
        raise NotImplementedError

    def resolve_server(self, snapshot, server_id):
        raise NotImplementedError

    async def reload(self, *, call):
        raise NotImplementedError


class _Session:
    server_id = "fake-a"
    generation = 1
    is_closed = False

    async def discover(self, *, call):
        return ()

    async def call_tool(self, tool_name, arguments, *, call):
        raise NotImplementedError

    async def close(self):
        return None


class _Factory:
    async def open(self, definition, generation, *, call):
        raise NotImplementedError


class _Validator:
    def check_schema(self, schema, *, schema_id):
        return None

    def validate(self, value, schema, *, schema_id):
        return value


class _Secrets:
    async def resolve(self, reference, *, call):
        return "secret"


class _Environment:
    def select(self, allowlist):
        return {}


class McpPortContractTests(unittest.TestCase):
    def test_minimal_implementations_structurally_conform(self) -> None:
        implementations = (
            (_Client(), UnifiedMcpClient),
            (_Registry(), McpServerRegistry),
            (_Session(), McpTransportSession),
            (_Factory(), McpTransportSessionFactory),
            (_Validator(), McpSchemaValidator),
            (_Secrets(), McpSecretResolver),
            (_Environment(), McpEnvironmentProvider),
        )
        for implementation, protocol in implementations:
            with self.subTest(protocol=protocol.__name__):
                self.assertIsInstance(implementation, protocol)


if __name__ == "__main__":
    unittest.main()
