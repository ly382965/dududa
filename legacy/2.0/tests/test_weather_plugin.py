from __future__ import annotations

import ast
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx
from astrbot_plugin_weather import WttrWeatherSource, format_weather_summary

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "apps" / "astrbot-plugins" / "astrbot_plugin_weather"
NOW = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)


def _weather_payload() -> dict[str, object]:
    return {
        "current_condition": [
            {
                "lang_zh": [{"value": "晴"}],
                "weatherDesc": [{"value": "Sunny"}],
                "temp_C": "28",
                "FeelsLikeC": "30",
                "humidity": "65",
                "windspeedKmph": "11",
                "winddir16Point": "NE",
            }
        ],
        "weather": [{"date": "2026-08-31", "mintempC": "22", "maxtempC": "31"}],
        "nearest_area": [
            {
                "areaName": [{"value": "Hefei"}],
                "region": [{"value": "Anhui"}],
                "country": [{"value": "China"}],
            }
        ],
    }


class WeatherPluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_city_returns_structured_provenance(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=_weather_payload())

        source = WttrWeatherSource(
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )
        try:
            result = await source.fetch("  合肥  ")
        finally:
            await source.close()

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.host, "wttr.in")
        self.assertEqual(requests[0].url.params["format"], "j1")
        self.assertEqual(requests[0].url.params["lang"], "zh")
        self.assertEqual(result["city"], "合肥")
        self.assertEqual(result["current"]["temperature_c"], 28)
        self.assertEqual(result["today"]["maximum_c"], 31)
        self.assertEqual(result["provenance"]["provider"], "wttr.in")
        self.assertIn("wttr.in", result["provenance"]["source_url"])
        self.assertEqual(result["fetched_at"], "2026-08-31T00:00:00+00:00")
        self.assertEqual(
            format_weather_summary(result),
            "Hefei：晴，当前 28℃，体感 30℃；今日 22℃ 至 31℃，湿度 65%，东北风 11 km/h。",
        )

    async def test_city_is_required_before_network_access(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=_weather_payload())

        source = WttrWeatherSource(transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(ValueError):
                await source.fetch("   ")
        finally:
            await source.close()
        self.assertEqual(calls, 0)

    def test_astrbot_entry_has_no_handler_scheduler_or_direct_send(self) -> None:
        tree = ast.parse((PLUGIN / "main.py").read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        self.assertTrue(
            names.isdisjoint(
                {
                    "AsyncIOScheduler",
                    "CronTrigger",
                    "filter",
                    "get_group_list",
                    "send_group_msg",
                }
            )
        )

    def test_plugin_is_default_off_and_metadata_matches_runtime_asset(self) -> None:
        schema = json.loads((PLUGIN / "_conf_schema.json").read_text(encoding="utf-8"))
        metadata = (PLUGIN / "metadata.yaml").read_text(encoding="utf-8")

        self.assertIs(schema["enabled"]["default"], False)
        self.assertIn("version: v2.0.0", metadata)
        self.assertIn("不自行调度或发送消息", metadata)


if __name__ == "__main__":
    unittest.main()
