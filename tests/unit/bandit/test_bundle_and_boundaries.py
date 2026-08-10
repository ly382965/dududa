from __future__ import annotations

import ast
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from dududa.bandit import check_bandit_offline_bundle

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "evals" / "bandit-offline-v1"
SOURCE = ROOT / "packages" / "dududa-agent" / "src" / "dududa"


class BanditBundleTests(unittest.TestCase):
    def test_committed_bundle_is_reproducible_and_honest(self) -> None:
        report = check_bandit_offline_bundle(BUNDLE)
        self.assertTrue(report["technical_pass"])
        self.assertTrue(report["order_reproducible"])
        self.assertFalse(report["release_ready"])
        self.assertFalse(report["real_endpoint_claimed"])
        self.assertEqual(report["real_model_call_count"], 0)
        self.assertEqual(report["user_data_record_count"], 0)

    def test_tampered_samples_report_and_json_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dududa-bandit-tamper-") as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(BUNDLE, copied)
            samples_path = copied / "samples.json"
            samples = json.loads(samples_path.read_text(encoding="utf-8"))
            samples["samples"][0]["reward"] = "0"
            samples_path.write_text(
                json.dumps(samples, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                check_bandit_offline_bundle(copied)

        with tempfile.TemporaryDirectory(prefix="dududa-bandit-report-") as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(BUNDLE, copied)
            report_path = copied / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["ips"] = "0.0"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                check_bandit_offline_bundle(copied)

        with tempfile.TemporaryDirectory(prefix="dududa-bandit-json-") as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(BUNDLE, copied)
            manifest_path = copied / "manifest.json"
            text = manifest_path.read_text(encoding="utf-8")
            manifest_path.write_text(
                text.replace(
                    '  "schema_version": 1,',
                    '  "schema_version": 1,\n  "schema_version": 1,',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                check_bandit_offline_bundle(copied)


class BanditImportBoundaryTests(unittest.TestCase):
    def test_bandit_has_no_production_hook_or_external_dependency(self) -> None:
        allowed_internal = {
            "dududa._compat",
            "dududa.contracts.canonical",
            "dududa.domain.primitives",
            "dududa.errors",
            "dududa.models.contracts",
        }
        violations: list[str] = []
        for path in (SOURCE / "bandit").rglob("*.py"):
            for name in _imports(path):
                if name.startswith("dududa.") and name not in allowed_internal:
                    violations.append(f"{path.name}: {name}")
        self.assertEqual(violations, [])

        production_roots = (
            SOURCE / "models",
            SOURCE / "runtime",
            SOURCE / "proactive",
            ROOT / "apps" / "astrbot-plugins",
        )
        reverse_imports = [
            str(path.relative_to(ROOT))
            for root in production_roots
            for path in root.rglob("*.py")
            if any(name.startswith("dududa.bandit") for name in _imports(path))
        ]
        self.assertEqual(reverse_imports, [])


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


if __name__ == "__main__":
    unittest.main()
