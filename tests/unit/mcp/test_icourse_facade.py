from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from astrbot_plugin_dududa_core.adapters.mcp_runtime import (
    AllowlistedEnvironmentProvider,
    build_icourse_client,
)
from astrbot_plugin_dududa_core.course import (
    ICOURSE_COMPAT_TOOL_ALLOWLIST,
    ICourseClient,
    UnavailableICourseClient,
)
from dududa.contracts.canonical import canonical_json_bytes
from dududa.errors import DududaError
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

    async def test_composition_is_unified_or_fail_closed_unavailable(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "servers"
            registry.mkdir()
            source = ROOT / "configs" / "mcp" / "servers" / "icourse.json"
            (registry / "icourse.json").write_text(
                source.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            worker = root / "python"
            worker.write_text("fixture", encoding="utf-8")
            unified, mode, reason = build_icourse_client(
                {"icourse_mcp_mode": "legacy"},
                registry_directory=registry,
                worker_python=worker,
                environment_provider=AllowlistedEnvironmentProvider({}),
            )
            self.assertIsInstance(unified, ICourseClient)
            self.assertEqual((mode, reason), ("unified", "unified_ready"))
            await unified.close()

            missing, mode, reason = build_icourse_client(
                {},
                registry_directory=root / "missing",
                worker_python=root / "missing-python",
            )
            self.assertIsInstance(missing, UnavailableICourseClient)
            self.assertEqual(
                (mode, reason),
                ("unavailable", "unified_infrastructure_missing"),
            )
            errors = []
            with self.assertRaises(DududaError) as call_error:
                await missing.call("search_courses", {"query": "fixture"})
            errors.append(call_error.exception.info)
            with self.assertRaises(DududaError) as tools_error:
                await missing.list_tools()
            errors.append(tools_error.exception.info)
            self.assertEqual(errors[0], errors[1])
            self.assertEqual(errors[0].code, "icourse_client_unavailable")
            self.assertEqual(
                errors[0].reason_codes,
                ("unified_infrastructure_missing",),
            )
            self.assertFalse(errors[0].retryable)
            await missing.close()
            await missing.close()

            relative, mode, reason = build_icourse_client(
                {"mcp_registry_dir": "relative"},
                registry_directory=registry,
                worker_python=worker,
            )
            self.assertIsInstance(relative, UnavailableICourseClient)
            self.assertEqual(
                (mode, reason),
                ("unavailable", "unified_path_not_absolute"),
            )

            disabled_value = json.loads(source.read_text(encoding="utf-8"))
            disabled_value["enabled"] = False
            (registry / "icourse.json").write_text(
                json.dumps(disabled_value),
                encoding="utf-8",
            )
            disabled, mode, reason = build_icourse_client(
                {},
                registry_directory=registry,
                worker_python=worker,
            )
            self.assertIsInstance(disabled, UnavailableICourseClient)
            self.assertEqual(
                (mode, reason),
                ("unavailable", "icourse_definition_disabled"),
            )

            malformed = root / "malformed"
            malformed.mkdir()
            (malformed / "icourse.json").write_text("{", encoding="utf-8")
            invalid, mode, reason = build_icourse_client(
                {},
                registry_directory=malformed,
                worker_python=worker,
            )
            self.assertIsInstance(invalid, UnavailableICourseClient)
            self.assertEqual(
                (mode, reason),
                ("unavailable", "unified_composition_invalid"),
            )


if __name__ == "__main__":
    unittest.main()
