"""Weather via keyless Open-Meteo: `天气 [城市] [今天|明天|后天]`, agent tools `weather_query` and `world_time`."""

from __future__ import annotations

import time
from datetime import date
from urllib.parse import urlencode

from .base import Command, Ctx, FeatureError, Registry, Task, Tool
from .core import WEEKDAYS, world_time

FEATURE = "weather"
TASK = "weather"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "Asia/Shanghai"
FORECAST_TTL = 600.0
DAY_WORDS = (("大后天", 3), ("后天", 2), ("明天", 1), ("明日", 1), ("今天", 0), ("今日", 0))
DAY_LABELS = ("今天", "明天", "后天", "大后天")
RAIN_MM, RAIN_PROBABILITY = 0.1, 50
# Higher-level populated places first when a name is ambiguous (e.g. 朝阳).
FEATURE_RANK = {"PPLC": 0, "PPLA": 1, "PPLA2": 2, "PPLA3": 3}
# Open-Meteo's Chinese (and even English) search misses many foreign cities: 东京/纽约 return nothing,
# Chinese villages or York, Nebraska. Common ones are pinned: name -> (country_code, country, admin, lat, lon).
FOREIGN_CITIES = {
    "东京": ("JP", "日本", "东京都", 35.6895, 139.6917), "大阪": ("JP", "日本", "大阪府", 34.6937, 135.5023),
    "札幌": ("JP", "日本", "北海道", 43.0642, 141.3469), "福冈": ("JP", "日本", "福冈县", 33.5904, 130.4017),
    "横滨": ("JP", "日本", "神奈川县", 35.4437, 139.6380), "首尔": ("KR", "韩国", "", 37.5665, 126.9780),
    "釜山": ("KR", "韩国", "", 35.1796, 129.0756), "台北": ("TW", "中国台湾", "", 25.0330, 121.5654),
    "河内": ("VN", "越南", "", 21.0278, 105.8342), "胡志明市": ("VN", "越南", "", 10.8231, 106.6297),
    "纽约": ("US", "美国", "纽约州", 40.7128, -74.0060), "伦敦": ("GB", "英国", "英格兰", 51.5074, -0.1278),
    "西雅图": ("US", "美国", "华盛顿州", 47.6062, -122.3321),
    "温哥华": ("CA", "加拿大", "不列颠哥伦比亚省", 49.2827, -123.1207),
    "华盛顿": ("US", "美国", "哥伦比亚特区", 38.9072, -77.0369), "罗马": ("IT", "意大利", "", 41.9028, 12.4964),
    "米兰": ("IT", "意大利", "", 45.4642, 9.1900), "马德里": ("ES", "西班牙", "", 40.4168, -3.7038),
    "巴塞罗那": ("ES", "西班牙", "", 41.3874, 2.1686), "阿姆斯特丹": ("NL", "荷兰", "", 52.3676, 4.9041),
    "维也纳": ("AT", "奥地利", "", 48.2082, 16.3738), "苏黎世": ("CH", "瑞士", "", 47.3769, 8.5417),
    "日内瓦": ("CH", "瑞士", "", 46.2044, 6.1432), "慕尼黑": ("DE", "德国", "巴伐利亚州", 48.1351, 11.5820),
    "伊斯坦布尔": ("TR", "土耳其", "", 41.0082, 28.9784), "开罗": ("EG", "埃及", "", 30.0444, 31.2357),
    "新德里": ("IN", "印度", "", 28.6139, 77.2090), "孟买": ("IN", "印度", "", 19.0760, 72.8777),
    "雅加达": ("ID", "印度尼西亚", "", -6.2088, 106.8456), "马尼拉": ("PH", "菲律宾", "", 14.5995, 120.9842),
    "奥克兰": ("NZ", "新西兰", "", -36.8485, 174.7633),
}
REGIONS = {"TW": "中国台湾", "HK": "中国香港", "MO": "中国澳门"}

WMO = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "强阵雨", 82: "暴雨", 85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}
DIRECTIONS = ("北", "东北", "东", "东南", "南", "西南", "西", "西北")
# Beaufort upper bounds in m/s for levels 0..11; anything above is 12级.
BEAUFORT = (0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7)

_forecasts: dict[tuple, tuple[float, dict]] = {}


# ---------------------------------------------------------------- pure helpers


def condition(code: object) -> str:
    return WMO.get(int(code), "未知天气") if isinstance(code, (int, float)) else "未知天气"


def wind_text(speed_kmh: object, direction_deg: object) -> str:
    if not isinstance(speed_kmh, (int, float)):
        return "风力未知"
    ms = speed_kmh / 3.6
    level = next((index for index, bound in enumerate(BEAUFORT) if ms < bound), 12)
    if level == 0:
        return "无风"
    side = DIRECTIONS[int((direction_deg % 360) / 45 + 0.5) % 8] + "风" \
        if isinstance(direction_deg, (int, float)) else "风"
    return f"{side}{level}级"


def hour_ranges(hours: list[int]) -> list[str]:
    """[13, 14, 15, 20] -> ["13-16时", "20-21时"] (end is exclusive, like a clock range)."""
    ranges: list[str] = []
    start = previous = None
    for hour in sorted(hours):
        if start is None:
            start = previous = hour
        elif hour == previous + 1:
            previous = hour
        else:
            ranges.append(f"{start}-{previous + 1}时")
            start = previous = hour
    if start is not None:
        ranges.append(f"{start}-{previous + 1}时")
    return ranges


def parse_args(args: str, default_city: str) -> tuple[str, int]:
    text = args.strip()
    offset = 0
    for word, value in DAY_WORDS:
        if word in text:
            offset = value
            text = text.replace(word, " ")
            break
    city = " ".join(text.replace("的", " ").replace("天气", " ").split()).strip(" ,，。?？")
    return city or default_city, offset


def _importance(item: dict) -> tuple[int, float]:
    return FEATURE_RANK.get(item.get("feature_code", ""), 9), -(item.get("population") or 0)


def pick_place(results: list[dict]) -> dict | None:
    """Prefer the most important Chinese match, unless the only Chinese ones are minor towns and a
    foreign capital/province seat matches (东京 should be Tokyo, not a village in 江苏)."""
    results = [item for item in results if str(item.get("feature_code") or "").startswith("PPL")] or results
    if not results:
        return None
    chinese = [item for item in results if item.get("country_code") == "CN"]
    if not chinese:
        return min(results, key=lambda item: -(item.get("population") or 0))
    best = min(chinese, key=_importance)
    foreign = [item for item in results if item.get("country_code") != "CN"
               and FEATURE_RANK.get(item.get("feature_code", ""), 9) <= 1]
    if foreign and _importance(best)[0] >= 3:
        return min(foreign, key=_importance)
    return best


def place_label(place: dict) -> str:
    name = place.get("name") or "?"
    region = [part for part in (place.get("admin1"), place.get("admin2"))
              if part and part != name and part.rstrip("市") != name]
    country = REGIONS.get(place.get("country_code") or "") or place.get("country")
    if place.get("country_code") != "CN" and country:
        region = [country, *region[:1]]
    return f"{name}（{'·'.join(region)}）" if region else name


def _at(series: dict, key: str, index: int) -> object:
    values = series.get(key) or []
    return values[index] if index < len(values) else None


def day_summary(forecast: dict, index: int) -> dict:
    daily = forecast.get("daily") or {}
    dates = daily.get("time") or []
    if index >= len(dates):
        raise FeatureError("没有这一天的预报数据")
    day = dates[index]
    hourly = forecast.get("hourly") or {}
    rain_hours, peak = [], 0
    for position, stamp in enumerate(hourly.get("time") or []):
        if not stamp.startswith(day):
            continue
        amount = _at(hourly, "precipitation", position) or 0
        probability = _at(hourly, "precipitation_probability", position) or 0
        peak = max(peak, probability)
        if amount >= RAIN_MM or probability >= RAIN_PROBABILITY:
            rain_hours.append(int(stamp[11:13]))
    parsed = date.fromisoformat(day)
    return {
        "date": day,
        "label": DAY_LABELS[index] if index < len(DAY_LABELS) else f"{parsed.month}月{parsed.day}日",
        "weekday": "周" + WEEKDAYS[parsed.weekday()],
        "condition": condition(_at(daily, "weather_code", index)),
        "weather_code": _at(daily, "weather_code", index),
        "temp_min_c": _at(daily, "temperature_2m_min", index),
        "temp_max_c": _at(daily, "temperature_2m_max", index),
        "precip_probability_max": _at(daily, "precipitation_probability_max", index),
        "precip_sum_mm": _at(daily, "precipitation_sum", index),
        "wind": wind_text(_at(daily, "wind_speed_10m_max", index), _at(daily, "wind_direction_10m_dominant", index)),
        "wind_max_kmh": _at(daily, "wind_speed_10m_max", index),
        "uv_index_max": _at(daily, "uv_index_max", index),
        "rain_hours": hour_ranges(rain_hours),
        "hourly_precip_probability_peak": peak,
    }


def tip(day: dict) -> str:
    code = day.get("weather_code") or 0
    low, high = day.get("temp_min_c"), day.get("temp_max_c")
    probability, amount = day.get("precip_probability_max") or 0, day.get("precip_sum_mm") or 0
    parts = []
    if code >= 95:
        parts.append("有雷雨，少在空旷处逗留")
    elif code in (71, 73, 75, 77, 85, 86):
        parts.append("有雪，注意路滑保暖")
    elif probability >= RAIN_PROBABILITY or amount >= 1:
        parts.append("记得带伞")
    elif probability >= 30:
        parts.append("可能有雨，备把伞更安心")
    if isinstance(low, (int, float)) and isinstance(high, (int, float)):
        if high >= 33:
            parts.append("很热，注意防暑多喝水")
        elif high >= 28:
            parts.append("短袖就好")
        elif low <= 0:
            parts.append("超冷，羽绒服安排上")
        elif low <= 8:
            parts.append("挺冷的，厚外套别忘了")
        elif low <= 15:
            parts.append("早晚凉，加件外套")
        if high - low >= 10:
            parts.append("温差大注意增减衣物")
    if (day.get("uv_index_max") or 0) >= 7 and probability < 30:
        parts.append("紫外线强注意防晒")
    return "，".join(parts[:3]) + "～" if parts else "天气不错，出门玩吧～"


def _num(value: object) -> str:
    return f"{value:.0f}" if isinstance(value, (int, float)) else "?"


def format_report(place: dict, forecast: dict, index: int) -> str:
    day = day_summary(forecast, index)
    month, dom = int(day["date"][5:7]), int(day["date"][8:10])
    lines = [f"{place_label(place)} {day['label']} {month}月{dom}日 {day['weekday']}：{day['condition']}"]
    temps = f"气温 {_num(day['temp_min_c'])}~{_num(day['temp_max_c'])}°C"
    current = forecast.get("current") or {}
    if index == 0 and isinstance(current.get("temperature_2m"), (int, float)):
        temps += f"，现在 {current['temperature_2m']:.0f}°C {condition(current.get('weather_code'))}"
        if isinstance(current.get("apparent_temperature"), (int, float)):
            temps += f"（体感 {current['apparent_temperature']:.0f}°C）"
    lines.append(temps)
    rain = f"降水概率 {_num(day['precip_probability_max'])}%，降水量 {day['precip_sum_mm'] or 0:.1f}mm"
    if day["rain_hours"]:
        rain += "，可能下雨：" + "、".join(day["rain_hours"][:4])
    lines.append(rain)
    lines.append(f"{day['wind']}（最大 {_num(day['wind_max_kmh'])}km/h）")
    lines.append("小贴士：" + tip(day))
    return "\n".join(lines)


def tool_payload(place: dict, forecast: dict, days: int) -> dict:
    current = forecast.get("current") or {}
    count = min(days, len((forecast.get("daily") or {}).get("time") or []))
    return {
        "ok": True,
        "location": {"name": place.get("name"), "admin1": place.get("admin1"), "admin2": place.get("admin2"),
                     "country": place.get("country"), "latitude": place.get("latitude"),
                     "longitude": place.get("longitude"), "label": place_label(place)},
        "timezone": TIMEZONE,
        "current": {"time": current.get("time"), "temp_c": current.get("temperature_2m"),
                    "apparent_temp_c": current.get("apparent_temperature"),
                    "humidity_pct": current.get("relative_humidity_2m"),
                    "condition": condition(current.get("weather_code")),
                    "wind": wind_text(current.get("wind_speed_10m"), current.get("wind_direction_10m"))},
        "daily": [day_summary(forecast, index) for index in range(count)],
        "note": (f"rain_hours 为该日逐小时降水量≥{RAIN_MM}mm 或降水概率≥{RAIN_PROBABILITY}% 的时段（北京时间）；"
                 "数据来自 Open-Meteo 数值预报。"),
    }


# ---------------------------------------------------------------- network


def pinned_place(city: str) -> dict | None:
    pinned = FOREIGN_CITIES.get(city)
    if not pinned:
        return None
    code, country, admin, latitude, longitude = pinned
    return {"name": city, "admin1": admin or None, "admin2": None, "country": country, "country_code": code,
            "latitude": latitude, "longitude": longitude}


async def geocode(ctx: Ctx, city: str) -> dict:
    pinned = pinned_place(city)
    if pinned:
        return pinned
    key = "geo:" + city
    cached = ctx.kv_get(FEATURE, key)
    if isinstance(cached, dict):
        return cached
    names = [city]
    for suffix in ("市", "县", "区"):
        if city.endswith(suffix) and len(city) > 2:
            names.append(city[:-1])
    for name in names:
        query = urlencode({"name": name, "count": 10, "language": "zh", "format": "json"})
        data = await ctx.fetch_json(f"{GEOCODE_URL}?{query}", timeout=15)
        place = pick_place(data.get("results") or [] if isinstance(data, dict) else [])
        if place:
            place = {k: place.get(k) for k in ("name", "admin1", "admin2", "country", "country_code",
                                                "latitude", "longitude", "feature_code", "population")}
            ctx.kv_set(FEATURE, key, place)
            return place
    raise FeatureError(f"没找到“{city}”这个地方，换个写法试试？")


async def forecast_for(ctx: Ctx, place: dict, days: int) -> dict:
    key = (place["latitude"], place["longitude"], days)
    hit = _forecasts.get(key)
    if hit and time.monotonic() - hit[0] < FORECAST_TTL:
        return hit[1]
    query = urlencode({
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": TIMEZONE,
        "forecast_days": days, "wind_speed_unit": "kmh",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
                   "wind_speed_10m,wind_direction_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                 "precipitation_sum,wind_speed_10m_max,wind_direction_10m_dominant,uv_index_max",
        "hourly": "precipitation_probability,precipitation",
    })
    data = await ctx.fetch_json(f"{FORECAST_URL}?{query}", timeout=20)
    if not isinstance(data, dict) or not (data.get("daily") or {}).get("time"):
        raise FeatureError("天气服务没返回数据，稍后再试～")
    _forecasts[key] = (time.monotonic(), data)
    return data


# ---------------------------------------------------------------- handlers


def default_city(ctx: Ctx) -> str:
    return str(ctx.config(FEATURE).get("default_city") or "合肥")


async def weather_command(ctx: Ctx) -> str:
    city, offset = parse_args(ctx.args, default_city(ctx))
    place = await geocode(ctx, city)
    forecast = await forecast_for(ctx, place, 7)
    return format_report(place, forecast, offset)


async def weather_tool(ctx: Ctx, args: dict) -> dict:
    city = str(args.get("city") or "").strip() or default_city(ctx)
    days = args.get("days", 3)
    days = max(1, min(7, int(days))) if isinstance(days, (int, float)) else 3
    try:
        place = await geocode(ctx, city)
        forecast = await forecast_for(ctx, place, 7)
    except FeatureError as error:
        return {"ok": False, "error": str(error)}
    return tool_payload(place, forecast, days)


async def world_time_tool(ctx: Ctx, args: dict) -> str:
    return world_time()


def register(registry: Registry) -> None:
    registry.task(Task(TASK, "天气", "天气指令与天气/世界时间查询工具", aliases=("weather",)))
    registry.command(Command(("天气", "weather"), weather_command,
                             "天气 [城市] [今天|明天|后天]：查天气预报", task=TASK))
    registry.tool(Tool(
        "weather_query",
        "查询某城市未来 1-7 天天气预报（北京时间）：每日天气、气温范围、降水概率与降水量、风力，"
        "以及每天可能下雨的小时段 rain_hours。用于回答“明天上海会下雨吗”之类问题；回答时带上地区名。",
        {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名，中文优先，如 上海、合肥、东京"},
            "days": {"type": "integer", "minimum": 1, "maximum": 7, "description": "预报天数，默认 3（含今天）"}},
         "required": ["city"]},
        weather_tool, task=TASK))
    registry.tool(Tool("world_time", "当前上海、美西、美东、巴黎的日期时间（自动夏令时）。",
                       {"type": "object", "properties": {}}, world_time_tool, task=TASK))
