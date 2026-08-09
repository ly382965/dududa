from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPIKE = ROOT / "spikes" / "mcp-v2"
SPIKE_ID = "s12a-mcp-v2-spike-v1"


class McpV2SpikeArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads((SPIKE / "report.json").read_text(encoding="utf-8"))

    def test_report_is_digest_bound_and_all_hard_gates_pass(self) -> None:
        report_without_digest = dict(self.report)
        observed_digest = report_without_digest.pop("report_digest")
        encoded = json.dumps(
            report_without_digest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        expected_digest = (
            "sha-256:"
            + hashlib.sha256(SPIKE_ID.encode() + b"\x00" + encoded).hexdigest()
        )

        self.assertEqual(observed_digest, expected_digest)
        self.assertEqual(self.report["decision"], "adopt")
        self.assertEqual(len(self.report["hard_gates"]), 13)
        self.assertTrue(all(self.report["hard_gates"].values()))

    def test_report_contains_only_sanitized_stable_evidence(self) -> None:
        rendered = json.dumps(self.report, ensure_ascii=False, sort_keys=True)
        for forbidden in ("/home/", "/tmp/", "stderr", '"api_key":', '"secret":'):
            self.assertNotIn(forbidden, rendered.lower())
        self.assertEqual(self.report["fixtures"]["network_attempts"], 0)
        self.assertEqual(self.report["fixtures"]["off_policy_database_opens"], 0)
        self.assertEqual(self.report["fixtures"]["capability_grants"], 0)
        self.assertEqual(self.report["metrics"]["sequential_calls"], 100)
        self.assertEqual(self.report["metrics"]["concurrent_calls"], 20)
        self.assertEqual(self.report["metrics"]["max_active_calls"], 4)

    def test_v2_lock_is_isolated_from_the_root_v1_workspace(self) -> None:
        script = (SPIKE / "run_spike.py").read_text(encoding="utf-8")
        spike_lock = (SPIKE / "run_spike.py.lock").read_text(encoding="utf-8")
        root_lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
        service_project = (
            ROOT / "services" / "icourse-mcp" / "pyproject.toml"
        ).read_text(encoding="utf-8")

        self.assertIn('"mcp==2.0.0"', script)
        self.assertRegex(spike_lock, r'(?s)name = "mcp"\nversion = "2\.0\.0"')
        self.assertRegex(root_lock, r'(?s)name = "mcp"\nversion = "1\.29\.0"')
        self.assertNotRegex(root_lock, r'(?s)name = "mcp"\nversion = "2\.0\.0"')
        self.assertIn('"mcp>=1.2.0,<2.0.0"', service_project)

    def test_adr_binds_the_exact_adoption_evidence_and_limits_claims(self) -> None:
        adr = (
            ROOT / "docs" / "adr" / "0006-adopt-mcp-v2-for-unified-client.md"
        ).read_text(encoding="utf-8")
        self.assertIn(self.report["report_digest"], adr)
        self.assertIn("ADOPT", adr)
        self.assertIn("UnifiedMcpClient 尚未实现", adr)
        self.assertIn("iCourse 仍是唯一真实 MCP Server", adr)


if __name__ == "__main__":
    unittest.main()
