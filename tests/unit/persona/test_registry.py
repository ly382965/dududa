from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.errors import DududaError
from dududa.persona.contracts import PersonaCatalogUpdate
from dududa.persona.registry import InMemoryPersonaRegistry
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    ServiceCallContext,
    ServicePrincipal,
)

from tests.unit.persona._fixtures import NOW, definition


def _call(*, cancelled: bool = False, expired: bool = False) -> ServiceCallContext:
    cancellation = ManualCancellationToken() if cancelled else NeverCancelled()
    if cancelled:
        cancellation.cancel()
    return ServiceCallContext(
        operation_id="persona-publish",
        principal=ServicePrincipal("tests", "one", frozenset({"catalog-admin"})),
        operation_kind="persona.catalog.publish",
        trace=TraceContext("trace-persona"),
        deadline=NOW - timedelta(seconds=1) if expired else NOW + timedelta(minutes=1),
        cancellation=cancellation,
        budget=RuntimeBudget(0, 0, 0, 0, 0, None),
        policy_snapshot_id="policy-v1",
    )


class PersonaRegistryTests(unittest.IsolatedAsyncioTestCase):
    def _registry(self, *, history_limit: int = 32) -> InMemoryPersonaRegistry:
        identifiers = iter(("one", "two", "three", "four"))
        return InMemoryPersonaRegistry(
            (definition(), definition("neutral")),
            fallback_persona_id="neutral",
            fallback_version="1.0.0",
            clock=lambda: NOW,
            id_factory=lambda: next(identifiers),
            history_limit=history_limit,
        )

    def test_resolve_exact_latest_and_explicit_neutral_fallback(self) -> None:
        registry = self._registry()
        snapshot = registry.acquire_snapshot()

        exact = registry.resolve(snapshot, "dududa", "1.0.0")
        latest = registry.resolve(snapshot, "dududa")
        fallback = registry.resolve(snapshot, "missing")

        self.assertFalse(exact.fallback_used)
        self.assertEqual(latest.definition.version, "1.0.0")
        self.assertTrue(fallback.fallback_used)
        self.assertEqual(fallback.definition.persona_id, "neutral")
        self.assertEqual(fallback.reason_code, "neutral_persona_fallback")

    async def test_publish_is_cas_atomic_and_retains_last_known_good(self) -> None:
        registry = self._registry()
        original = registry.acquire_snapshot()

        with self.assertRaises(DududaError) as caught:
            await registry.publish(
                PersonaCatalogUpdate(
                    schema_version=1,
                    expected_revision=original.revision,
                    definitions=(definition("dududa", "2.0.0"),),
                ),
                call=_call(),
            )
        self.assertEqual(caught.exception.info.code, "persona_fallback_not_found")
        self.assertIs(registry.acquire_snapshot(), original)

        updated = await registry.publish(
            PersonaCatalogUpdate(
                schema_version=1,
                expected_revision=original.revision,
                definitions=(
                    definition("dududa", "2.0.0"),
                    definition("neutral"),
                ),
            ),
            call=_call(),
        )
        self.assertEqual(updated.revision, 2)
        self.assertEqual(
            registry.resolve(updated, "dududa").definition.version, "2.0.0"
        )

        with self.assertRaises(DududaError) as caught:
            await registry.publish(
                PersonaCatalogUpdate(
                    schema_version=1,
                    expected_revision=original.revision,
                    definitions=updated.definitions,
                ),
                call=_call(),
            )
        self.assertEqual(
            caught.exception.info.code, "persona_catalog_revision_conflict"
        )
        self.assertIs(registry.acquire_snapshot(), updated)

    async def test_previous_snapshot_remains_replayable_until_history_eviction(
        self,
    ) -> None:
        registry = self._registry(history_limit=2)
        original = registry.acquire_snapshot()
        second = await registry.publish(
            PersonaCatalogUpdate(
                1,
                1,
                (definition("dududa", "2.0.0"), definition("neutral")),
            ),
            call=_call(),
        )
        self.assertEqual(
            registry.resolve(original, "dududa").definition.version, "1.0.0"
        )
        self.assertEqual(registry.resolve(second, "dududa").definition.version, "2.0.0")

        await registry.publish(
            PersonaCatalogUpdate(
                1,
                2,
                (definition("dududa", "3.0.0"), definition("neutral")),
            ),
            call=_call(),
        )
        with self.assertRaises(DududaError) as caught:
            registry.resolve(original, "dududa")
        self.assertEqual(caught.exception.info.code, "unknown_persona_catalog_snapshot")

    def test_missing_neutral_and_bad_clock_fail_closed(self) -> None:
        with self.assertRaises(DududaError) as caught:
            InMemoryPersonaRegistry(
                (definition(),),
                fallback_persona_id="neutral",
                fallback_version="1.0.0",
                clock=lambda: NOW,
            )
        self.assertEqual(caught.exception.info.code, "persona_fallback_not_found")

        with self.assertRaises(DududaError) as caught:
            InMemoryPersonaRegistry(
                (definition(), definition("neutral")),
                fallback_persona_id="neutral",
                fallback_version="1.0.0",
                clock=lambda: NOW.replace(tzinfo=None),
            )
        self.assertEqual(caught.exception.info.code, "invalid_persona_catalog_clock")

    async def test_foreign_snapshot_and_duplicate_id_fail_closed(self) -> None:
        registry = self._registry()
        original = registry.acquire_snapshot()
        foreign = replace(original, snapshot_id="persona-catalog:foreign")
        with self.assertRaises(DududaError) as caught:
            registry.resolve(foreign, "dududa")
        self.assertEqual(caught.exception.info.code, "unknown_persona_catalog_snapshot")

        duplicate = InMemoryPersonaRegistry(
            (definition(), definition("neutral")),
            fallback_persona_id="neutral",
            fallback_version="1.0.0",
            clock=lambda: NOW,
            id_factory=lambda: "same",
        )
        with self.assertRaises(DududaError) as caught:
            await duplicate.publish(
                PersonaCatalogUpdate(1, 1, (definition(), definition("neutral"))),
                call=_call(),
            )
        self.assertEqual(
            caught.exception.info.code, "persona_catalog_snapshot_id_conflict"
        )
        self.assertEqual(duplicate.acquire_snapshot().revision, 1)

    async def test_expired_and_cancelled_publish_preserve_last_known_good(self) -> None:
        registry = self._registry()
        original = registry.acquire_snapshot()
        update = PersonaCatalogUpdate(1, 1, (definition(), definition("neutral")))
        for call, code in (
            (_call(expired=True), "persona_catalog_call_expired"),
            (_call(cancelled=True), "persona_catalog_call_cancelled"),
        ):
            with self.subTest(code=code), self.assertRaises(DududaError) as caught:
                await registry.publish(update, call=call)
            self.assertEqual(caught.exception.info.code, code)
            self.assertIs(registry.acquire_snapshot(), original)

    def test_fallback_must_be_explicit_versioned_neutral(self) -> None:
        for fallback_id, fallback_version, code in (
            ("dududa", "1.0.0", "invalid_persona_fallback_id"),
            ("neutral", None, "invalid_persona_fallback_version"),
        ):
            with self.subTest(code=code), self.assertRaises(DududaError) as caught:
                InMemoryPersonaRegistry(
                    (definition(), definition("neutral")),
                    fallback_persona_id=fallback_id,
                    fallback_version=fallback_version,  # type: ignore[arg-type]
                    clock=lambda: NOW,
                )
            self.assertEqual(caught.exception.info.code, code)


if __name__ == "__main__":
    unittest.main()
