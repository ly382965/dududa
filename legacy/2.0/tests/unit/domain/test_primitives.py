from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import unittest

from dududa.domain.primitives import freeze_json
from dududa.domain.primitives import ResourceUsage, RuntimeBudget
from dududa.errors import DududaError


class PrimitiveTests(unittest.TestCase):
    def test_freeze_json_recursively_copies_mutable_values(self) -> None:
        source = {"items": [{"value": Decimal("1.25")}]}
        frozen = freeze_json(source)
        source["items"][0]["value"] = Decimal("9")
        self.assertEqual(frozen["items"][0]["value"], Decimal("1.25"))
        with self.assertRaises(TypeError):
            frozen["new"] = True

    def test_freeze_json_rejects_unsafe_values(self) -> None:
        for value in (
            float("nan"),
            float("inf"),
            Decimal("NaN"),
            Decimal("Infinity"),
            b"secret",
            Path("/tmp/x"),
            object(),
        ):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(DududaError):
                    freeze_json(value)

    def test_budget_cost_requires_finite_decimal(self) -> None:
        for value in (1.5, Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(value=value), self.assertRaises(DududaError):
                RuntimeBudget(0, 0, 0, 0, 0, value)  # type: ignore[arg-type]
            with self.subTest(usage=value), self.assertRaises(DududaError):
                ResourceUsage(1, 0, 0, 0, 0, 0, value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
