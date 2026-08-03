from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "packages" / "dududa-agent" / "src" / "dududa"
PUBLIC_PACKAGES = (
    "dududa",
    "dududa.adapters",
    "dududa.compatibility",
    "dududa.config",
    "dududa.contracts",
    "dududa.domain",
    "dududa.evaluation",
    "dududa.memory",
    "dududa.models",
    "dududa.perception",
    "dududa.ports",
    "dududa.runtime",
    "dududa.security",
    "dududa.testing",
)
ORDER_SENSITIVE_MODULES = (
    "dududa.domain.attachments",
    "dududa.domain.delivery",
    "dududa.domain.task",
    "dududa.models.contracts",
    "dududa.models.errors",
    "dududa.models.policy",
    "dududa.perception.contracts",
    "dududa.ports.context",
    "dududa.ports.models",
    "dududa.ports.perception",
    "dududa.security.models",
)

FORBIDDEN_INTERNAL_IMPORTS = {
    "dududa.perception": ("dududa.models", "dududa.runtime"),
    "dududa.models": ("dududa.perception", "dududa.runtime"),
}


class ImportBoundaryTests(unittest.TestCase):
    def test_core_has_only_standard_library_and_internal_imports(self) -> None:
        violations: list[str] = []
        for path in SOURCE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif (
                    isinstance(node, ast.ImportFrom) and node.module and node.level == 0
                ):
                    names.append(node.module)
                for name in names:
                    root = name.split(".", 1)[0]
                    if root != "dududa" and root not in sys.stdlib_module_names:
                        violations.append(f"{path.relative_to(ROOT)}: {name}")
        self.assertEqual(violations, [])

    def test_selection_packages_preserve_one_way_internal_dependencies(self) -> None:
        violations: list[str] = []
        for owner, forbidden in FORBIDDEN_INTERNAL_IMPORTS.items():
            package = SOURCE / owner.rsplit(".", 1)[-1]
            for path in package.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = tuple(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = (node.module,) if node.level == 0 else ()
                    else:
                        names = ()
                    for name in names:
                        if any(
                            name == prefix or name.startswith(f"{prefix}.")
                            for prefix in forbidden
                        ):
                            violations.append(
                                f"{path.relative_to(ROOT)}: {owner} imports {name}"
                            )
        self.assertEqual(violations, [])

    def test_public_packages_are_valid_first_imports(self) -> None:
        for module in PUBLIC_PACKAGES + ORDER_SENSITIVE_MODULES:
            with self.subTest(module=module):
                self._assert_clean_import((module,))

    def test_public_exports_survive_forward_and_reverse_import_order(self) -> None:
        for modules in (PUBLIC_PACKAGES, tuple(reversed(PUBLIC_PACKAGES))):
            with self.subTest(first=modules[0]):
                self._assert_clean_import(modules, resolve_exports=True)

    def _assert_clean_import(
        self,
        modules: tuple[str, ...],
        *,
        resolve_exports: bool = False,
    ) -> None:
        source = str(ROOT / "packages" / "dududa-agent" / "src")
        statements = [f"import {module}" for module in modules]
        if resolve_exports:
            statements.extend(
                (
                    "import importlib",
                    (
                        "packages=[importlib.import_module(name) "
                        f"for name in {PUBLIC_PACKAGES!r}]"
                    ),
                    (
                        "[[getattr(package, name) "
                        "for name in getattr(package, '__all__', ())] "
                        "for package in packages]"
                    ),
                )
            )
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = os.pathsep.join(
            item for item in (source, environment.get("PYTHONPATH", "")) if item
        )
        completed = subprocess.run(
            [sys.executable, "-c", ";".join(statements)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
