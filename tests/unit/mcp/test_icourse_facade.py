from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from dududa.contracts.canonical import canonical_json_bytes
from dududa.mcp import (
    ManagedUnifiedMcpClient,
    McpContentBlock,
    McpContentKind,
    McpOperationSemantics,
    McpRegistrySnapshot,
    McpTransportToolResult,
    mcp_registry_digest,
)
from dududa.testing import (
    FakeMcpSessionPlan,
    RecordingFakeMcpSessionFactory,
    RecordingMcpSchemaValidator,
)

from plugins.astrbot_plugin_dududa_core.adapters.mcp_runtime import (
    AllowlistedEnvironmentProvider,
    build_icourse_client,
)
from plugins.astrbot_plugin_dududa_core.course import (
    ICOURSE_COMPAT_TOOL_ALLOWLIST,
    ICourseClient,
    LegacyICourseClient,
)

from .helpers import (
    NOW,
    replace_server_definition,
    server_definition,
    tool_descriptor,
)

ROOT = Path(__file__).resolve().parents[3]


class _Registry:
    def __init__(self, definition) -> None:
        definitions = (definition,)
        digest = mcp_registry_digest(definitions)
        self.snapshot = McpRegistrySnapshot(
            schema_version=1,
            snapshot_id="registry:icourse-facade",
            registry_revision=str(digest),
            registry_digest=digest,
            definitions=definitions,
            acquired_at=NOW,
        )

    def acquire_snapshot(self):
        return self.snapshot

    def resolve_server(self, snapshot, server_id):
        if snapshot != self.snapshot or server_id != "icourse":
            raise ValueError("unknown server")
        return self.snapshot.definitions[0]

    async def reload(self, *, call):
        return self.snapshot


def result(value: str) -> McpTransportToolResult:
    structured = {"value": value, "items": []}
    text = json.dumps(structured)
    return McpTransportToolResult(
        schema_version=1,
        is_error=False,
        structured_content=structured,
        content=(
            McpContentBlock(
                schema_version=1,
                kind=McpContentKind.TEXT,
                text=text,
                mime_type="application/json",
                uri=None,
                data_digest=None,
                size_bytes=len(text.encode("utf-8")),
            ),
        ),
        total_size_bytes=len(canonical_json_bytes(structured))
        + len(text.encode("utf-8")),
    )


class ICourseFacadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_facade_reuses_unified_session_and_derives_exact_semantics(
        self,
    ) -> None:
        denied = {
            "check_robots",
            "crawl_courses",
            "crawl_latest_reviews",
            "export_dataset",
        }
        definition = replace_server_definition(
            server_definition("icourse"),
            allowed_tools=ICOURSE_COMPAT_TOOL_ALLOWLIST,
            denied_tools=frozenset(denied),
            maximum_concurrency=1,
            schema_ttl=timedelta(minutes=5),
        )
        tools = tuple(
            sorted(
                (
                    tool_descriptor(name)
                    for name in ICOURSE_COMPAT_TOOL_ALLOWLIST | denied
                ),
                key=lambda item: item.name,
            )
        )
        plan = FakeMcpSessionPlan(
            tools=tools,
            call_outcomes=(result("search"), result("refresh")),
        )
        factory = RecordingFakeMcpSessionFactory((plan,))
        unified = ManagedUnifiedMcpClient(
            _Registry(definition),
            factory,
            RecordingMcpSchemaValidator(),
            wall_clock=lambda: NOW,
            monotonic_clock=lambda: 1.0,
            id_factory=lambda: "schema",
        )
        ids = iter(("search", "refresh", "tools"))
        facade = ICourseClient(
            unified,
            clock=lambda: NOW,
            id_factory=lambda: next(ids),
        )
        search = await facade.call("search_courses", {"query": "fixture"})
        refresh = await facade.call(
            "get_course",
            {"course_id": 1, "refresh": True},
        )
        visible = await facade.list_tools()

        self.assertEqual(search["items"], [])
        self.assertEqual(refresh["value"], "refresh")
        self.assertEqual(visible, sorted(ICOURSE_COMPAT_TOOL_ALLOWLIST))
        self.assertEqual(len(factory.sessions), 1)
        calls = factory.sessions[0].call_records
        self.assertEqual(calls[0][2].semantics, McpOperationSemantics.READ_ONLY)
        self.assertEqual(
            calls[1][2].semantics,
            McpOperationSemantics.NON_IDEMPOTENT,
        )
        await facade.close()

    async def test_composition_selection_is_explicit_and_startup_only(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "servers"
            registry.mkdir()
            source = ROOT / "config" / "mcp" / "servers" / "icourse.json"
            (registry / "icourse.json").write_text(
                source.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            worker = root / "python"
            worker.write_text("fixture", encoding="utf-8")
            unified, mode, reason = build_icourse_client(
                {},
                registry_directory=registry,
                worker_python=worker,
                environment_provider=AllowlistedEnvironmentProvider({}),
            )
            self.assertIsInstance(unified, ICourseClient)
            self.assertEqual((mode, reason), ("unified", "unified_ready"))
            await unified.close()

            legacy, mode, reason = build_icourse_client(
                {"icourse_mcp_mode": "legacy"},
                registry_directory=registry,
                worker_python=worker,
            )
            self.assertIsInstance(legacy, LegacyICourseClient)
            self.assertEqual((mode, reason), ("legacy", "operator_selected_legacy"))

            missing, mode, reason = build_icourse_client(
                {},
                registry_directory=root / "missing",
                worker_python=root / "missing-python",
            )
            self.assertIsInstance(missing, LegacyICourseClient)
            self.assertEqual(
                (mode, reason),
                ("legacy", "unified_infrastructure_missing"),
            )


if __name__ == "__main__":
    unittest.main()
