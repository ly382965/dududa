from __future__ import annotations

from typing import Any

import httpx

# wttr.in English condition -> Chinese mapping (subset used by wttr.in)
_WEATHER_MAP = {
    "sunny": "晴",
    "clear": "晴",
    "partly cloudy": "多云",
    "cloudy": "阴天",
    "overcast": "阴天",
    "mist": "薄雾",
    "fog": "雾",
    "light rain": "小雨",
    "light rain shower": "短时小雨",
    "patchy rain nearby": "附近零星小雨",
    "patchy light rain": "局部小雨",
    "moderate rain": "中雨",
    "moderate rain at times": "有时中雨",
    "heavy rain": "大雨",
    "heavy rain at times": "有时大雨",
    "light drizzle": "毛毛雨",
    "drizzle": "毛毛雨",
    "thundery outbreaks possible": "可能雷阵雨",
    "thunderstorm": "雷阵雨",
    "moderate or heavy rain with thunder": "雷雨",
    "snow": "雪",
    "light snow": "小雪",
    "blizzard": "暴雪",
    "windy": "大风",
    "moderate or heavy snow": "中到大雪",
    "freezing fog": "冻雾",
    "patchy light drizzle": "局部毛毛雨",
}

_WIND_DIR = {
    "N": "北", "NNE": "北东北", "NE": "东北", "ENE": "东北东",
    "E": "东", "ESE": "东南东", "SE": "东南", "SSE": "南东南",
    "S": "南", "SSW": "南西南", "SW": "西南", "WSW": "西南西",
    "W": "西", "WNW": "西北西", "NW": "西北", "NNW": "北西北",
}


def _cond_cn(desc: str) -> str:
    d = (desc or "").strip().lower()
    if not d:
        return "未知"
    return _WEATHER_MAP.get(d, d)


def _wind_cn(wind_dir: str, wind_kmph: Any) -> str:
    d = (wind_dir or "").strip().upper()
    dir_cn = _WIND_DIR.get(d, d or "")
    try:
        speed = int(float(str(wind_kmph).split(" ")[0]))
    except Exception:
        speed = 0
    return f"{dir_cn}风{speed}km/h" if dir_cn else f"{speed}km/h"


def _emoji(desc: str) -> str:
    d = (desc or "").lower()
    if any(k in d for k in ("thunder", "storm", "雷")):
        return "⛈️"
    if any(k in d for k in ("rain", "drizzle")):
        return "🌧️"
    if any(k in d for k in ("snow", "blizzard")):
        return "❄️"
    if any(k in d for k in ("fog", "mist")):
        return "🌫️"
    if any(k in d for k in ("cloud", "overcast")):
        return "☁️"
    if "sunny" in d or "clear" in d:
        return "☀️"
    return "🌤️"


def _chinese_city(code: str) -> str:
    if code == "xingning":
        return "广东梅州兴宁"
    return "合肥"


def fetch_weather(city_code: str, timeout: float = 20.0) -> dict[str, Any]:
    """Fetch current+today weather from wttr.in as a flat dict."""
    url = f"https://wttr.in/{city_code}?format=j1&lang=zh"
    with httpx.Client(timeout=timeout, headers={"User-Agent": "curl"}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    current = (data.get("current_condition") or [{}])[0]
    today = (data.get("weather") or [{}])[0]
    hourly = today.get("hourly") or []
    hour0 = hourly[0] if hourly else {}

    desc_en = current.get("lang_zh") and current["lang_zh"][0].get("value") or current.get("weatherDesc") and current["weatherDesc"][0].get("value") or ""
    feels = current.get("FeelsLikeC")
    temp = current.get("temp_C")
    humidity = current.get("humidity")
    wind_kmph = current.get("windspeedKmph") or current.get("windspeedKmph")
    wind_dir = current.get("winddir16Point") or current.get("winddirDegree")
    max_temp = today.get("maxtempC")
    min_temp = today.get("mintempC")
    date = today.get("date", "")

    return {
        "city_cn": _chinese_city(city_code),
        "desc": _cond_cn(desc_en),
        "emoji": _emoji(desc_en),
        "temp": temp,
        "feels": feels,
        "humidity": humidity,
        "wind": _wind_cn(str(wind_dir), wind_kmph),
        "max_temp": max_temp,
        "min_temp": min_temp,
        "date": date,
    }


def format_broadcast(w: dict[str, Any]) -> str:
    lines = [
        f"早上好呀☀️ 这里是嘟嘟哒的天气预报~",
        f"{w['emoji']} {w['city_cn']}今天：{w['desc']}",
        f"🌡️ 当前 {w['temp']}℃（体感 {w['feels']}℃），最高 {w['max_temp']}℃ / 最低 {w['min_temp']}℃",
        f"💧 湿度 {w['humidity']}%，风 {w['wind']}",
        "出门记得看天气带伞穿合适哒，祝你有美好的一天～",
    ]
    return "\n".join(lines)
