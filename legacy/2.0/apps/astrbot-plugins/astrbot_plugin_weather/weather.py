from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

import httpx
from dududa.domain.primitives import JsonValue

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
    "N": "北",
    "NNE": "北东北",
    "NE": "东北",
    "ENE": "东北东",
    "E": "东",
    "ESE": "东南东",
    "SE": "东南",
    "SSE": "南东南",
    "S": "南",
    "SSW": "南西南",
    "SW": "西南",
    "WSW": "西南西",
    "W": "西",
    "WNW": "西北西",
    "NW": "西北",
    "NNW": "北西北",
}


class WeatherSourceError(RuntimeError):
    """The public weather source could not produce a usable observation."""


@runtime_checkable
class WeatherSourcePort(Protocol):
    async def fetch(self, city: str) -> Mapping[str, JsonValue]: ...

    async def close(self) -> None: ...


class WttrWeatherSource:
    """Read one explicitly requested city from wttr.in without side effects."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://wttr.in",
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "Dududa/2.0 weather capability"},
            transport=transport,
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._closed = False

    async def fetch(self, city: str) -> Mapping[str, JsonValue]:
        normalized_city = _city(city)
        if self._closed:
            raise WeatherSourceError("weather source is closed")
        try:
            response = await self._client.get(
                f"/{quote(normalized_city, safe='')}",
                params={"format": "j1", "lang": "zh"},
            )
            response.raise_for_status()
            payload = response.json()
            result = _normalize_weather(
                payload,
                city=normalized_city,
                source_url=str(response.url),
                fetched_at=_aware_utc(self._clock()),
            )
        except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
            raise WeatherSourceError("weather source request failed") from exc
        return result

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._client.aclose()


def format_weather_summary(weather: Mapping[str, Any]) -> str:
    """Format structured facts for preview; the Runtime may compose them itself."""

    location = _mapping(weather.get("location"), "location")
    current = _mapping(weather.get("current"), "current")
    today = _mapping(weather.get("today"), "today")
    city_name = str(location.get("name") or weather.get("city") or "未知地点")
    return (
        f"{city_name}：{current.get('condition', '未知')}，"
        f"当前 {current.get('temperature_c')}℃，"
        f"体感 {current.get('feels_like_c')}℃；"
        f"今日 {today.get('minimum_c')}℃ 至 {today.get('maximum_c')}℃，"
        f"湿度 {current.get('humidity_percent')}%，"
        f"{current.get('wind_text', '风况未知')}。"
    )


def _normalize_weather(
    payload: Any,
    *,
    city: str,
    source_url: str,
    fetched_at: datetime,
) -> Mapping[str, JsonValue]:
    document = _mapping(payload, "payload")
    current = _first_mapping(document.get("current_condition"), "current_condition")
    today = _first_mapping(document.get("weather"), "weather")
    nearest = _first_mapping(
        document.get("nearest_area"), "nearest_area", required=False
    )

    description = _localized_description(current)
    location_name = _nested_value(nearest, "areaName") or city
    region = _nested_value(nearest, "region")
    country = _nested_value(nearest, "country")
    wind_direction = str(current.get("winddir16Point") or "")
    wind_kph = _number(current.get("windspeedKmph"))

    return {
        "schema_version": 1,
        "city": city,
        "location": {
            "name": location_name,
            "region": region,
            "country": country,
        },
        "current": {
            "condition": _condition_cn(description),
            "temperature_c": _number(current.get("temp_C")),
            "feels_like_c": _number(current.get("FeelsLikeC")),
            "humidity_percent": _number(current.get("humidity")),
            "wind_direction": wind_direction,
            "wind_kph": wind_kph,
            "wind_text": _wind_cn(wind_direction, wind_kph),
        },
        "today": {
            "date": str(today.get("date") or ""),
            "minimum_c": _number(today.get("mintempC")),
            "maximum_c": _number(today.get("maxtempC")),
        },
        "provenance": {
            "provider": "wttr.in",
            "source_url": source_url,
            "retrieval": "public_https_json",
        },
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
    }


def _city(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("weather city must be a string")
    city = " ".join(value.split())
    if not city or len(city) > 100 or any(char in city for char in "\r\n\x00"):
        raise ValueError("invalid weather city")
    return city


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"invalid weather {field}")
    return value


def _first_mapping(
    value: Any,
    field: str,
    *,
    required: bool = True,
) -> Mapping[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return value[0]
    if required:
        raise ValueError(f"invalid weather {field}")
    return {}


def _nested_value(value: Mapping[str, Any], key: str) -> str:
    nested = value.get(key)
    if not isinstance(nested, list) or not nested or not isinstance(nested[0], Mapping):
        return ""
    result = nested[0].get("value")
    return str(result or "").strip()


def _localized_description(current: Mapping[str, Any]) -> str:
    return _nested_value(current, "lang_zh") or _nested_value(current, "weatherDesc")


def _condition_cn(value: str) -> str:
    normalized = value.strip().lower()
    return _WEATHER_MAP.get(normalized, value.strip() or "未知")


def _number(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    number = float(str(value).strip())
    return int(number) if number.is_integer() else number


def _wind_cn(direction: str, speed: float | None) -> str:
    direction_cn = _WIND_DIR.get(direction.strip().upper(), direction.strip().upper())
    speed_text = "未知" if speed is None else f"{speed:g}"
    return (
        f"{direction_cn}风 {speed_text} km/h"
        if direction_cn
        else f"风速 {speed_text} km/h"
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("weather clock must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "WeatherSourceError",
    "WeatherSourcePort",
    "WttrWeatherSource",
    "format_weather_summary",
]
