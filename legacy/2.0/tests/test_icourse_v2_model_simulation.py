from __future__ import annotations

import json
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ops.cli.run_icourse_v2_model_simulation import (
    MODELS,
    REASONING_EFFORT,
    REVIEW_MODEL,
    load_scenario,
    run_simulation,
    sanitized_summary,
    write_private_result,
)
from ops.cli.run_provider_no_send_shadow import PrivateProviderConfig

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "tests" / "fixtures" / "mcp" / "icourse-v2-wu-tian-simulation.json"


class _Sender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, url, body, config):
        self.calls.append((url, dict(body)))
        model = str(body["model"])
        if "text" in body:
            content = json.dumps(
                {
                    "passed": True,
                    "grounded": True,
                    "useful": True,
                    "process_hidden": True,
                    "score": 95,
                    "issues": [],
                },
                ensure_ascii=False,
            )
        else:
            content = f"{model}：吴天老师有一条数学分析(B1)记录，评分 9.6。"
        return {
            "model": model,
            "output": [{"content": [{"type": "output_text", "text": content}]}],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 8,
                "total_tokens": 18,
            },
        }


class ICourseV2ModelSimulationTests(unittest.TestCase):
    def test_three_models_use_low_effort_and_each_gets_one_luna_review(self) -> None:
        sender = _Sender()
        scenario = load_scenario(SCENARIO)
        config = PrivateProviderConfig("https://example.invalid", "secret", 1.0)

        result = run_simulation(scenario, config, sender=sender)

        self.assertEqual(len(sender.calls), 6)
        answer_calls = [body for _url, body in sender.calls if "text" not in body]
        review_calls = [body for _url, body in sender.calls if "text" in body]
        self.assertEqual([body["model"] for body in answer_calls], [item[0] for item in MODELS])
        self.assertEqual([body["model"] for body in review_calls], [REVIEW_MODEL] * 3)
        self.assertTrue(
            all(
                body["reasoning"] == {"effort": REASONING_EFFORT}
                for _url, body in sender.calls
            )
        )
        self.assertEqual(result["provider_calls"], 6)
        self.assertEqual(result["output_calls"], 0)
        self.assertTrue(all(item["review"]["passed"] for item in result["candidates"]))

    def test_summary_omits_answers_observation_and_private_provider_values(self) -> None:
        sender = _Sender()
        scenario = load_scenario(SCENARIO)
        config = PrivateProviderConfig("https://private.invalid", "secret-key", 1.0)
        result = run_simulation(scenario, config, sender=sender)

        rendered = json.dumps(sanitized_summary(result), ensure_ascii=False)

        self.assertNotIn("candidate_answer", rendered)
        self.assertNotIn("数学分析(B1)", rendered)
        self.assertNotIn("private.invalid", rendered)
        self.assertNotIn("secret-key", rendered)

    def test_private_result_is_written_with_owner_only_permissions(self) -> None:
        sender = _Sender()
        scenario = load_scenario(SCENARIO)
        result = run_simulation(
            scenario,
            PrivateProviderConfig("https://example.invalid", "secret", 1.0),
            sender=sender,
        )
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "simulation.json"

            write_private_result(output, result)

            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), result)


if __name__ == "__main__":
    unittest.main()
