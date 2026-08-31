from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_DATA_PATH = Path(__file__).with_name("data") / "timetable.v1.json"
_MAX_RETURNED_TRIPS = 24
_STATION_ALIASES = {
    "太湖路园区": "太湖路园区",
    "太湖路": "太湖路园区",
    "高新校区": "高新校区",
    "高新区": "高新校区",
    "高新": "高新校区",
    "先研院": "先研院",
    "东校区": "东区",
    "西校区": "西区",
    "南校区": "南区",
    "北校区": "北区",
    "东区": "东区",
    "西区": "西区",
    "南区": "南区",
    "北区": "北区",
}
_ARABIC_TIME = re.compile(
    r"(?<!\d)(?P<hour>[01]?\d|2[0-3])(?:[:：点时])(?P<minute>[0-5]\d)?"
)
_CHINESE_TIME = re.compile(
    r"(?P<hour>零|一|二|两|三|四|五|六|七|八|九|十|十一|十二)点"
    r"(?:(?P<half>半)|(?P<minute>[一二三四五]?十?[一二三四五六七八九]?分?))?"
)
_CHINESE_HOURS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}
_WEEKDAY_TERMS = {
    "周一": 0,
    "星期一": 0,
    "礼拜一": 0,
    "周二": 1,
    "星期二": 1,
    "礼拜二": 1,
    "周三": 2,
    "星期三": 2,
    "礼拜三": 2,
    "周四": 3,
    "星期四": 3,
    "礼拜四": 3,
    "周五": 4,
    "星期五": 4,
    "礼拜五": 4,
    "周六": 5,
    "星期六": 5,
    "礼拜六": 5,
    "周日": 6,
    "周天": 6,
    "星期日": 6,
    "星期天": 6,
    "礼拜日": 6,
    "礼拜天": 6,
}


class ShuttleSchedule:
    """Query one immutable local timetable snapshot without network access."""

    def __init__(self, data_path: Path = _DATA_PATH) -> None:
        document = json.loads(data_path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1 or not isinstance(
            document.get("services"), list
        ):
            raise ValueError("invalid_shuttle_timetable")
        self._document = document

    @property
    def dataset_id(self) -> str:
        return str(self._document["dataset_id"])

    def query(self, query: str, *, at: datetime | str | None = None) -> dict[str, Any]:
        text = str(query or "").strip()
        if not text or len(text) > 2_000:
            raise ValueError("invalid_shuttle_query")
        observed_at = _local_datetime(at)
        origin, destination, mentioned_stations = _route_request(text)
        service_ids = _service_ids(text, mentioned_stations)
        requested_days = _requested_days(text, observed_at)
        time_request = _requested_time(text, observed_at)
        selector = _selector(text, time_request)

        items: list[dict[str, Any]] = []
        notices: list[str] = []
        effective_dates: dict[str, str] = {}
        for service in self._document["services"]:
            if service["service_id"] not in service_ids:
                continue
            effective_dates[service["service_id"]] = service["effective_date"]
            notices.extend(str(value) for value in service.get("notes", ()))
            schedules = service.get("schedules") or (
                {"service_day": service["service_day"], "routes": service["routes"]},
            )
            for schedule in schedules:
                for route in schedule["routes"]:
                    indexes = _route_indexes(route["stops"], origin, destination)
                    if indexes is None:
                        continue
                    for trip in route["trips"]:
                        if not _trip_runs(
                            schedule["service_day"], trip, requested_days
                        ):
                            continue
                        items.append(
                            _project_trip(
                                service,
                                schedule["service_day"],
                                route,
                                trip,
                                indexes,
                            )
                        )

        items.sort(key=_trip_sort_key)
        items = _apply_time_selection(items, time_request, selector)
        if len(items) > _MAX_RETURNED_TRIPS:
            items = items[:_MAX_RETURNED_TRIPS]
            notices.append(
                f"匹配班次较多，仅返回按时间排序后的前 {_MAX_RETURNED_TRIPS} 条；"
                "请补充校区、起终点或时间以缩小范围。"
            )
        if origin == "北区" or destination == "北区":
            notices.append("北区仅标为途经站，当前时刻表没有给出北区固定到发时间。")

        return {
            "ok": True,
            "matched": bool(items),
            "query": text,
            "observed_at": observed_at.isoformat(timespec="seconds"),
            "request": {
                "origin": origin,
                "destination": destination,
                "service_days": sorted(requested_days),
                "after": _format_minutes(time_request),
                "selector": selector,
            },
            "items": items,
            "total": len(items),
            "notices": _unique(notices),
            "semantics": {
                "holiday": "学期中节假日仍运行。",
                "no_public_bus": "该趟没有公交车辆运行，不等于班次取消。",
                "on_demand": "途经站即停即走，没有固定发车时间。",
            },
            "source": {
                "dataset_id": self.dataset_id,
                "source_kind": self._document["source_kind"],
                "effective_dates": effective_dates,
            },
        }


def _local_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(_LOCAL_TIMEZONE)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("invalid_shuttle_query_time")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_LOCAL_TIMEZONE)
    return parsed.astimezone(_LOCAL_TIMEZONE)


def _route_request(text: str) -> tuple[str | None, str | None, tuple[str, ...]]:
    mentions: list[tuple[int, str]] = []
    occupied: list[tuple[int, int]] = []
    for alias in sorted(_STATION_ALIASES, key=len, reverse=True):
        start = 0
        while (position := text.find(alias, start)) >= 0:
            end = position + len(alias)
            if not any(position < right and end > left for left, right in occupied):
                mentions.append((position, _STATION_ALIASES[alias]))
                occupied.append((position, end))
            start = end
    ordered = tuple(value for _, value in sorted(mentions))
    unique = tuple(dict.fromkeys(ordered))
    return (
        unique[0] if unique else None,
        unique[1] if len(unique) > 1 else None,
        unique,
    )


def _service_ids(text: str, stations: tuple[str, ...]) -> frozenset[str]:
    if "太湖" in text or "太湖路园区" in stations:
        return frozenset({"taihu"})
    if "高新" in text or "高新校区" in stations or "先研院" in stations:
        return frozenset({"hightech"})
    if (
        any(value in stations for value in ("南区", "北区"))
        or len(stations) >= 2
        and set(stations[:2]) <= {"东区", "西区", "南区", "北区"}
    ):
        return frozenset({"campus"})
    return frozenset({"campus", "hightech", "taihu"})


def _requested_days(text: str, at: datetime) -> frozenset[str]:
    if "工作日" in text:
        return frozenset({"workday"})
    if any(value in text for value in ("双休", "周末")):
        return frozenset({"saturday", "sunday", "holiday"})
    if any(value in text for value in ("节假日", "假期")):
        return frozenset({"holiday"})
    for term, weekday in _WEEKDAY_TERMS.items():
        if term in text:
            return frozenset({_weekday_mode(weekday)})
    if "明天" in text:
        return frozenset({_weekday_mode((at.weekday() + 1) % 7)})
    if "后天" in text:
        return frozenset({_weekday_mode((at.weekday() + 2) % 7)})
    return frozenset({_weekday_mode(at.weekday())})


def _weekday_mode(weekday: int) -> str:
    return "saturday" if weekday == 5 else "sunday" if weekday == 6 else "workday"


def _requested_time(text: str, at: datetime) -> int | None:
    if "现在" in text:
        return at.hour * 60 + at.minute
    match = _ARABIC_TIME.search(text)
    if match is not None:
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        return _period_adjusted_minutes(text, match.start(), hour, minute)
    match = _CHINESE_TIME.search(text)
    if match is None:
        return None
    minute_text = match.group("minute") or ""
    minute = 30 if match.group("half") else _chinese_minute(minute_text)
    return _period_adjusted_minutes(
        text,
        match.start(),
        _CHINESE_HOURS[match.group("hour")],
        minute,
    )


def _period_adjusted_minutes(
    text: str, position: int, hour: int, minute: int
) -> int:
    prefix = text[max(0, position - 4) : position]
    if any(value in prefix for value in ("下午", "晚上", "晚间", "傍晚")) and hour < 12:
        hour += 12
    if "中午" in prefix and hour < 11:
        hour += 12
    return hour * 60 + minute


def _chinese_minute(value: str) -> int:
    compact = value.removesuffix("分")
    if not compact:
        return 0
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if compact == "十":
        return 10
    if "十" in compact:
        left, right = compact.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(compact, 0)


def _selector(text: str, time_request: int | None) -> str:
    if any(value in text for value in ("最后一班", "最晚一班")):
        return "last"
    if any(value in text for value in ("最早一班", "最早", "第一班")):
        return "first"
    if any(value in text for value in ("这班", "这一班")):
        return "exact"
    if time_request is not None:
        return "next"
    return "all"


def _route_indexes(
    stops: list[str], origin: str | None, destination: str | None
) -> tuple[int, int] | None:
    start = 0 if origin is None else stops.index(origin) if origin in stops else -1
    end = len(stops) - 1 if destination is None else (
        stops.index(destination) if destination in stops else -1
    )
    return (start, end) if 0 <= start < end < len(stops) else None


def _trip_runs(
    service_day: str, trip: dict[str, Any], requested_days: frozenset[str]
) -> bool:
    if service_day == "workday":
        return "workday" in requested_days or (
            "holiday" in requested_days and trip.get("holiday") is True
        )
    if service_day == "weekend_holiday":
        return bool(requested_days & {"saturday", "sunday", "holiday"})
    if service_day == "monday_to_saturday":
        if trip.get("saturday_only") is True:
            return "saturday" in requested_days
        return bool(requested_days & {"workday", "saturday"})
    return service_day == "sunday" and "sunday" in requested_days


def _project_trip(
    service: dict[str, Any],
    service_day: str,
    route: dict[str, Any],
    trip: dict[str, Any],
    indexes: tuple[int, int],
) -> dict[str, Any]:
    start, end = indexes
    stops = route["stops"]
    times = trip["times"]
    on_demand = frozenset(route.get("on_demand_stops", ()))
    projected_stops = [
        {
            "name": stops[index],
            "time": times[index],
            "on_demand": stops[index] in on_demand,
        }
        for index in range(start, end + 1)
    ]
    reference_time = next(
        (value for value in times[start:] if isinstance(value, str)),
        next(value for value in times if isinstance(value, str)),
    )
    return {
        "service_id": service["service_id"],
        "service_name": service["name"],
        "effective_date": service["effective_date"],
        "service_day": service_day,
        "direction": route["direction"],
        "origin": stops[start],
        "destination": stops[end],
        "departure": times[start],
        "arrival": times[end],
        "reference_departure": reference_time,
        "stops": projected_stops,
        "holiday": trip.get("holiday") is True,
        "no_public_bus": trip.get("no_public_bus") is True,
        "saturday_only": trip.get("saturday_only") is True,
    }


def _apply_time_selection(
    items: list[dict[str, Any]], requested: int | None, selector: str
) -> list[dict[str, Any]]:
    if selector == "last":
        return items[-1:] if items else []
    if selector == "first":
        return items[:1]
    if requested is None:
        return items
    if selector == "exact":
        return [
            item
            for item in items
            if _minutes(item.get("departure") or item["reference_departure"])
            == requested
        ]
    eligible = [
        item
        for item in items
        if _minutes(item.get("departure") or item["reference_departure"])
        >= requested
    ]
    return eligible[:1]


def _trip_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    return (
        _minutes(item.get("departure") or item["reference_departure"]),
        item["service_id"],
        item["direction"],
    )


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _format_minutes(value: int | None) -> str | None:
    return None if value is None else f"{value // 60:02d}:{value % 60:02d}"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = ["ShuttleSchedule"]
