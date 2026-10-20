import json
import unittest

from dududa_v3.features import weather

FORECAST = json.loads("""
{
  "current": {"time": "2026-10-19T09:00", "temperature_2m": 18.4, "apparent_temperature": 17.2,
              "relative_humidity_2m": 80, "weather_code": 3, "wind_speed_10m": 12.0, "wind_direction_10m": 45},
  "daily": {
    "time": ["2026-10-19", "2026-10-20"],
    "weather_code": [3, 63],
    "temperature_2m_max": [24.6, 19.2],
    "temperature_2m_min": [13.1, 14.0],
    "precipitation_probability_max": [10, 85],
    "precipitation_sum": [0.0, 6.4],
    "wind_speed_10m_max": [12.0, 30.0],
    "wind_direction_10m_dominant": [45, 180],
    "uv_index_max": [4.0, 1.5]
  },
  "hourly": {
    "time": ["2026-10-19T13:00", "2026-10-19T14:00", "2026-10-20T08:00", "2026-10-20T09:00",
             "2026-10-20T10:00", "2026-10-20T15:00"],
    "precipitation_probability": [5, 10, 60, 70, 40, 20],
    "precipitation": [0.0, 0.0, 0.0, 1.2, 0.5, 0.0]
  }
}
""")
PLACE = {"name": "上海", "admin1": "上海市", "admin2": None, "country": "中国", "country_code": "CN",
         "latitude": 31.22, "longitude": 121.46}


class WeatherTests(unittest.TestCase):
    def test_codes_and_wind(self):
        self.assertEqual(weather.condition(0), "晴")
        self.assertEqual(weather.condition(95.0), "雷阵雨")
        self.assertEqual(weather.condition(42), "未知天气")
        self.assertEqual(weather.condition(None), "未知天气")
        self.assertEqual(weather.wind_text(12.0, 45), "东北风2级")
        self.assertEqual(weather.wind_text(0.5, 0), "无风")
        self.assertEqual(weather.wind_text(30.0, 180), "南风5级")

    def test_hour_ranges_and_args(self):
        self.assertEqual(weather.hour_ranges([15, 8, 9, 10]), ["8-11时", "15-16时"])
        self.assertEqual(weather.parse_args("上海 明天", "合肥"), ("上海", 1))
        self.assertEqual(weather.parse_args("后天", "合肥"), ("合肥", 2))
        self.assertEqual(weather.parse_args("大后天北京", "合肥"), ("北京", 3))
        self.assertEqual(weather.parse_args("", "合肥"), ("合肥", 0))

    def test_pick_place_prefers_chinese_admin_center(self):
        results = [{"name": "Chaoyang", "country_code": "KR", "feature_code": "PPLA"},
                   {"name": "朝阳", "country_code": "CN", "feature_code": "PPLA4", "population": 13524},
                   {"name": "朝阳", "country_code": "CN", "feature_code": "PPLA2", "population": 300000,
                    "admin1": "辽宁"}]
        self.assertEqual(weather.pick_place(results)["admin1"], "辽宁")
        self.assertEqual(weather.pick_place(results[:1])["country_code"], "KR")
        self.assertIsNone(weather.pick_place([]))
        tokyo = [{"name": "东京", "country_code": "CN", "feature_code": "PPL", "admin1": "江苏"},
                 {"name": "东京", "country_code": "JP", "feature_code": "PPLC", "population": 8336599}]
        self.assertEqual(weather.pick_place(tokyo)["country_code"], "JP")
        self.assertEqual(weather.place_label(weather.pinned_place("纽约")), "纽约（美国·纽约州）")
        self.assertEqual(weather.place_label(weather.pinned_place("台北")), "台北（中国台湾）")
        self.assertIsNone(weather.pinned_place("合肥"))
        self.assertEqual(weather.place_label({"name": "合肥", "admin1": "安徽", "admin2": "合肥市",
                                              "country_code": "CN"}), "合肥（安徽）")

    def test_day_summary_rain_hours(self):
        tomorrow = weather.day_summary(FORECAST, 1)
        self.assertEqual(tomorrow["label"], "明天")
        self.assertEqual(tomorrow["condition"], "中雨")
        self.assertEqual(tomorrow["rain_hours"], ["8-11时"])
        self.assertEqual(tomorrow["weekday"], "周二")
        self.assertEqual(weather.day_summary(FORECAST, 0)["rain_hours"], [])

    def test_format_report(self):
        today = weather.format_report(PLACE, FORECAST, 0).splitlines()
        self.assertLessEqual(len(today), 6)
        self.assertEqual(today[0], "上海 今天 10月19日 周一：阴")
        self.assertIn("现在 18°C 阴（体感 17°C）", today[1])
        self.assertIn("温差大", today[-1])
        tomorrow = weather.format_report(PLACE, FORECAST, 1)
        self.assertNotIn("现在", tomorrow)
        self.assertIn("降水概率 85%，降水量 6.4mm，可能下雨：8-11时", tomorrow)
        self.assertIn("记得带伞", tomorrow)
        with self.assertRaises(weather.FeatureError):
            weather.day_summary(FORECAST, 2)

    def test_tool_payload(self):
        payload = weather.tool_payload(PLACE, FORECAST, 7)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["daily"]), 2)
        self.assertEqual(payload["daily"][1]["precip_probability_max"], 85)
        self.assertEqual(payload["current"]["wind"], "东北风2级")
        self.assertEqual(payload["location"]["label"], "上海")


if __name__ == "__main__":
    unittest.main()
