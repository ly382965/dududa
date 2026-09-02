from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.errors import DududaError
from dududa.mcp import ConfigMcpServerRegistry
from dududa.ports.context import (
    NeverCancelled,
    ServiceCallContext,
    ServicePrincipal,
)

from .helpers import NOW, server_document

ROOT = Path(__file__).resolve().parents[3]


def exception_graph_text(error: BaseException) -> str:
    values: list[str] = []
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        values.extend((str(current), repr(current)))
        for related in (current.__cause__, current.__context__):
            if isinstance(related, BaseException):
                pending.append(related)
    return "\n".join(values)


def write_definition(directory: Path, document: dict[str, object]) -> None:
    path = directory / f"{document['server_id']}.json"
    path.write_text(json.dumps(document), encoding="utf-8")


def service_call() -> ServiceCallContext:
    return ServiceCallContext(
        operation_id="reload-mcp-registry",
        principal=ServicePrincipal(
            service_id="test",
            instance_id="registry",
            roles=frozenset({"mcp-registry"}),
        ),
        operation_kind="mcp_registry_reload",
        trace=TraceContext("trace-mcp-registry"),
        deadline=NOW + timedelta(minutes=1),
        cancellation=NeverCancelled(),
        budget=RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
        policy_snapshot_id="policy-v1",
    )


class ConfigMcpServerRegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_repository_config_contains_active_and_optional_mcp_servers(self) -> None:
        registry = ConfigMcpServerRegistry(
            ROOT / "configs" / "mcp" / "servers",
            clock=lambda: NOW,
            id_factory=lambda: "production",
        )
        snapshot = registry.acquire_snapshot()
        self.assertEqual(
            tuple(item.server_id for item in snapshot.definitions),
            (
                "campus-events",
                "college-notice",
                "icourse",
                "library",
                "local-recs",
                "notifai",
                "training-plan",
                "ustc-academic",
                "ustc-curriculum",
                "ustc-young",
            ),
        )
        for server_id in (
            "campus-events",
            "college-notice",
            "library",
            "local-recs",
            "training-plan",
        ):
            self.assertFalse(registry.resolve_server(snapshot, server_id).enabled)
        icourse = registry.resolve_server(snapshot, "icourse")
        self.assertEqual(icourse.maximum_concurrency, 1)
        self.assertEqual(
            icourse.allowed_tools,
            frozenset(
                {
                    "crawl_course",
                    "get_course",
                    "get_reviews",
                    "icourse_public_query",
                    "icourse_stats",
                    "search_courses",
                    "search_site_courses",
                }
            ),
        )
        self.assertEqual(
            icourse.denied_tools,
            frozenset(
                {
                    "check_robots",
                    "crawl_courses",
                    "crawl_latest_reviews",
                    "export_dataset",
                }
            ),
        )

    async def test_invalid_reload_keeps_exact_last_known_good_snapshot(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            document = server_document()
            write_definition(directory, document)
            ids = iter(("initial", "rejected", "accepted"))
            registry = ConfigMcpServerRegistry(
                directory,
                clock=lambda: NOW,
                id_factory=lambda: next(ids),
            )
            initial = registry.acquire_snapshot()

            document["unexpected"] = True
            write_definition(directory, document)
            with self.assertRaises(DududaError):
                await registry.reload(call=service_call())
            self.assertIs(registry.acquire_snapshot(), initial)

            document.pop("unexpected")
            document["config_revision"] = "config-v2"
            document["maximum_concurrency"] = 3
            write_definition(directory, document)
            accepted = await registry.reload(call=service_call())
            self.assertIs(registry.acquire_snapshot(), accepted)
            self.assertNotEqual(accepted.registry_digest, initial.registry_digest)
            self.assertEqual(accepted.definitions[0].maximum_concurrency, 3)

    async def test_second_fake_is_added_by_config_only(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_definition(directory, server_document())
            ids = iter(("initial", "extended"))
            registry = ConfigMcpServerRegistry(
                directory,
                clock=lambda: NOW,
                id_factory=lambda: next(ids),
            )
            write_definition(directory, server_document("fake-b"))
            extended = await registry.reload(call=service_call())
            self.assertEqual(
                tuple(item.server_id for item in extended.definitions),
                ("fake-a", "fake-b"),
            )

    def test_duplicate_json_keys_and_filename_mismatch_are_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "fake-a.json").write_text(
                '{"schema_version":1,"schema_version":1}',
                encoding="utf-8",
            )
            with self.assertRaises(DududaError):
                ConfigMcpServerRegistry(directory, clock=lambda: NOW)

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            document = server_document("fake-a")
            (directory / "other.json").write_text(
                json.dumps(document), encoding="utf-8"
            )
            with self.assertRaises(DududaError):
                ConfigMcpServerRegistry(directory, clock=lambda: NOW)

    def test_snapshot_from_another_registry_cannot_be_resolved(self) -> None:
        with TemporaryDirectory() as first_temp, TemporaryDirectory() as second_temp:
            first_path = Path(first_temp)
            second_path = Path(second_temp)
            write_definition(first_path, server_document("fake-a"))
            write_definition(second_path, server_document("fake-b"))
            first = ConfigMcpServerRegistry(
                first_path,
                clock=lambda: NOW,
                id_factory=lambda: "same-id",
            )
            second = ConfigMcpServerRegistry(
                second_path,
                clock=lambda: NOW,
                id_factory=lambda: "same-id",
            )
            foreign = second.acquire_snapshot()
            with self.assertRaises(DududaError):
                first.resolve_server(foreign, "fake-b")

            tampered = replace(
                first.acquire_snapshot(),
                snapshot_id="mcp-registry:unknown",
            )
            with self.assertRaises(DududaError):
                first.resolve_server(tampered, "fake-a")

    def test_registry_parse_and_callback_errors_are_sanitized(self) -> None:
        sentinels = (
            "config-token-secret",
            "json-body-secret",
            "clock-secret",
            "id-secret",
        )
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / f"{sentinels[0]}.json").write_text(
                f'{{"value":"{sentinels[1]}"',
                encoding="utf-8",
            )
            with self.assertRaises(DududaError) as captured:
                ConfigMcpServerRegistry(directory)
            evidence = exception_graph_text(captured.exception)
            self.assertNotIn(sentinels[0], evidence)
            self.assertNotIn(sentinels[1], evidence)
            self.assertIsNone(captured.exception.__cause__)
            self.assertIsNone(captured.exception.__context__)

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_definition(directory, server_document())

            def broken_clock():
                raise RuntimeError(sentinels[2])

            with self.assertRaises(DududaError) as captured:
                ConfigMcpServerRegistry(directory, clock=broken_clock)
            self.assertNotIn(sentinels[2], exception_graph_text(captured.exception))

            def broken_id():
                raise RuntimeError(sentinels[3])

            with self.assertRaises(DududaError) as captured:
                ConfigMcpServerRegistry(directory, id_factory=broken_id)
            self.assertNotIn(sentinels[3], exception_graph_text(captured.exception))


if __name__ == "__main__":
    unittest.main()
