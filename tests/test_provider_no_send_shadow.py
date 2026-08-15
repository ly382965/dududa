from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "cli" / "run_provider_no_send_shadow.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("run_provider_no_send_shadow", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("shadow runner module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProviderNoSendShadowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = load_runner()
        self.config = self.runner.PrivateProviderConfig(
            "https://private.invalid/v1",
            "private-test-key",
            1.0,
        )

    def test_three_tiers_emit_only_sanitized_no_send_receipts(self) -> None:
        requests: list[tuple[str, dict[str, object]]] = []

        def fake_sender(url, body, config):
            requests.append((url, dict(body)))
            model = str(body["model"])
            return {
                "model": model,
                "output_text": "private model answer",
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "total_tokens": 10,
                },
            }

        receipt = self.runner.run_samples(self.config, sender=fake_sender)

        self.assertEqual(len(requests), 3)
        self.assertEqual(
            [item["tier"] for item in receipt], ["haiku", "sonnet", "opus"]
        )
        self.assertTrue(all(item["success"] for item in receipt))
        self.assertTrue(all(item["provider_calls"] == 1 for item in receipt))
        self.assertTrue(all(item["output_calls"] == 0 for item in receipt))
        allowed = {
            "model",
            "tier",
            "success",
            "latency_ms",
            "usage",
            "provider_calls",
            "output_calls",
        }
        self.assertTrue(all(set(item) == allowed for item in receipt))
        serialized = json.dumps(receipt)
        self.assertNotIn("private-test-key", serialized)
        self.assertNotIn("private.invalid", serialized)
        self.assertNotIn("private model answer", serialized)
        self.assertNotIn("Synthetic no-send shadow check", serialized)

    def test_failure_discards_provider_details_and_receipt_is_private(self) -> None:
        def failing_sender(url, body, config):
            raise RuntimeError(
                "provider body with private-test-key and private model answer"
            )

        receipt = [
            self.runner.sample_model(
                "gpt-5.6-luna",
                "haiku",
                self.config,
                sender=failing_sender,
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            self.runner.write_receipt(path, receipt)
            serialized = path.read_text(encoding="utf-8")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        self.assertFalse(receipt[0]["success"])
        self.assertIsNone(receipt[0]["usage"])
        self.assertEqual(receipt[0]["provider_calls"], 1)
        self.assertEqual(receipt[0]["output_calls"], 0)
        self.assertNotIn("private-test-key", serialized)
        self.assertNotIn("private model answer", serialized)


if __name__ == "__main__":
    unittest.main()
