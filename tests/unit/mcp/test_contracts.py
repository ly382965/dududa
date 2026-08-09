from __future__ import annotations

import hashlib
import unittest
from base64 import b64encode
from dataclasses import replace
from datetime import timedelta

from dududa.contracts.canonical import canonical_json_bytes
from dududa.errors import DududaError
from dududa.mcp import (
    MAX_CONTENT_BYTES,
    McpContentBlock,
    McpContentKind,
    McpHttpEndpoint,
    McpOperationSemantics,
    McpRegistrySnapshot,
    McpSchemaSnapshot,
    McpToolDescriptor,
    McpTransportToolResult,
    mcp_registry_digest,
    mcp_schema_snapshot_digest,
    mcp_tool_request_digest,
    mcp_tool_schema_facts_digest,
)

from .helpers import NOW, server_definition


def tool(name: str = "echo") -> McpToolDescriptor:
    return McpToolDescriptor(
        schema_version=1,
        name=name,
        description="Returns the supplied value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        annotations={"readOnlyHint": True},
    )


class McpContractTests(unittest.TestCase):
    def test_definition_and_registry_digests_bind_every_definition(self) -> None:
        first = server_definition()
        second = server_definition("fake-b")
        definitions = (first, second)
        snapshot = McpRegistrySnapshot(
            schema_version=1,
            snapshot_id="registry:test",
            registry_revision="registry-v1",
            registry_digest=mcp_registry_digest(definitions),
            definitions=definitions,
            acquired_at=NOW,
        )
        self.assertEqual(snapshot.definitions, definitions)

        with self.assertRaisesRegex(DududaError, "request.invalid"):
            replace(first, maximum_concurrency=3)
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            replace(snapshot, definitions=(first,))

    def test_schema_is_deeply_frozen_and_digest_bound(self) -> None:
        descriptor = tool()
        tools = (descriptor,)
        definition = server_definition()
        snapshot = McpSchemaSnapshot(
            schema_version=1,
            snapshot_id="schema:test",
            snapshot_digest=mcp_schema_snapshot_digest(
                "fake-a",
                "config-v1",
                definition.definition_digest,
                1,
                tools,
            ),
            server_id="fake-a",
            config_revision="config-v1",
            definition_digest=definition.definition_digest,
            schema_facts_digest=mcp_tool_schema_facts_digest(tools),
            generation=1,
            tools=tools,
            observed_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
        with self.assertRaises(TypeError):
            snapshot.tools[0].input_schema["type"] = "array"  # type: ignore[index]
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            replace(snapshot, generation=2)

    def test_remote_schema_refs_and_unsafe_http_endpoints_fail_closed(self) -> None:
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            McpToolDescriptor(
                schema_version=1,
                name="remote",
                description="",
                input_schema={"$ref": "https://schemas.example/tool.json"},
                output_schema=None,
                annotations={},
            )
        for url in (
            "http://mcp.example/tools",
            "https://user:secret@mcp.example/tools",
            "https://mcp.example/tools#fragment",
            "https://mcp.example/tools?token=secret",
        ):
            with (
                self.subTest(url=url),
                self.assertRaisesRegex(DududaError, "request.invalid"),
            ):
                McpHttpEndpoint(url=url, allowed_hosts=frozenset({"mcp.example"}))

    def test_transport_result_is_bounded_and_immutable(self) -> None:
        result = McpTransportToolResult(
            schema_version=1,
            is_error=False,
            structured_content={"answer": ["ok"]},
            content=(
                McpContentBlock(
                    schema_version=1,
                    kind=McpContentKind.TEXT,
                    text="ok",
                    mime_type="text/plain",
                    uri=None,
                    data_digest=None,
                    size_bytes=2,
                ),
            ),
            total_size_bytes=len(canonical_json_bytes({"answer": ("ok",)})) + 2,
        )
        with self.assertRaises(TypeError):
            result.structured_content["answer"] = ()  # type: ignore[index,union-attr]
        with self.assertRaisesRegex(DududaError, "request.invalid"):
            replace(result, total_size_bytes=MAX_CONTENT_BYTES + 1)

    def test_binary_content_binds_payload_size_and_digest(self) -> None:
        payload = b"image-bytes"
        encoded = b64encode(payload).decode("ascii")
        digest = f"sha-256:{hashlib.sha256(payload).hexdigest()}"
        block = McpContentBlock(
            schema_version=1,
            kind=McpContentKind.IMAGE,
            text=None,
            mime_type="image/png",
            uri=None,
            data_digest=digest,
            size_bytes=len(payload),
            data_base64=encoded,
        )
        self.assertEqual(block.data_base64, encoded)
        with self.assertRaises(DududaError):
            replace(block, data_digest=f"sha-256:{'0' * 64}")

    def test_retry_safety_facts_are_bound_into_request_digest(self) -> None:
        descriptor = tool()
        tools = (descriptor,)
        definition = server_definition()
        snapshot = McpSchemaSnapshot(
            schema_version=1,
            snapshot_id="schema:request",
            snapshot_digest=mcp_schema_snapshot_digest(
                "fake-a",
                "config-v1",
                definition.definition_digest,
                1,
                tools,
            ),
            server_id="fake-a",
            config_revision="config-v1",
            definition_digest=definition.definition_digest,
            schema_facts_digest=mcp_tool_schema_facts_digest(tools),
            generation=1,
            tools=tools,
            observed_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
        read_only = mcp_tool_request_digest(
            "fake-a",
            "echo",
            {"value": "ok"},
            snapshot,
            McpOperationSemantics.READ_ONLY,
            None,
        )
        non_idempotent = mcp_tool_request_digest(
            "fake-a",
            "echo",
            {"value": "ok"},
            snapshot,
            McpOperationSemantics.NON_IDEMPOTENT,
            "effect-1",
        )
        self.assertNotEqual(read_only, non_idempotent)


if __name__ == "__main__":
    unittest.main()
