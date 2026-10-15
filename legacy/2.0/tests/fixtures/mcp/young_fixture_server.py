#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

FETCHED_AT = "2026-08-29T00:00:00+08:00"
SOURCE_URL = "https://young.ustc.edu.cn/"


def activity(
    activity_id: str,
    name: str,
    *,
    start: str,
    end: str,
    valid_hours: float,
    registered: int,
    limit: int,
    module: str,
    labels: list[str],
    description: str,
    status_code: int = 26,
    status_text: str = "报名中",
    kind: str = "activity",
) -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "name": name,
        "status": {"code": status_code, "text": status_text},
        "kind": kind,
        "apply_window": {
            "start": "2026-08-20T08:00:00",
            "end": "2026-08-29T18:00:00",
        },
        "event_window": {"start": start, "end": end},
        "valid_hours": valid_hours,
        "capacity": {"registered": registered, "limit": limit},
        "is_registered": False,
        "can_apply": status_code == 26 and registered < limit,
        "module": {"id": f"module-{module}", "name": module},
        "department": {"id": "department-fixture", "name": "校团委"},
        "labels": [
            {"id": f"label-{index}", "name": value}
            for index, value in enumerate(labels, start=1)
        ],
        "description": description,
        "contact": "0551-00000000",
    }


ACTIVITIES = (
    activity(
        "ai-lecture-20260829",
        "人工智能前沿公开讲座",
        start="2026-08-29T19:00:00",
        end="2026-08-29T21:00:00",
        valid_hours=2,
        registered=180,
        limit=300,
        module="智育",
        labels=["学术讲座", "人工智能"],
        description="面向全校学生的公开讲座，无选拔要求，现场签到。",
    ),
    activity(
        "art-20260830",
        "校园美育艺术赏析",
        start="2026-08-30T14:00:00",
        end="2026-08-30T16:00:00",
        valid_hours=2,
        registered=72,
        limit=100,
        module="美育",
        labels=["艺术实践"],
        description="艺术作品赏析与交流，面向全校学生。",
    ),
    activity(
        "volunteer-20260830",
        "校园劳动志愿服务",
        start="2026-08-30T08:00:00",
        end="2026-08-30T11:00:00",
        valid_hours=3,
        registered=36,
        limit=40,
        module="劳育",
        labels=["劳动实践", "志愿服务"],
        description="需要按分组完成校园公共区域整理。",
    ),
    activity(
        "ethics-20260831",
        "科学精神与学术道德",
        start="2026-08-31T19:00:00",
        end="2026-08-31T20:30:00",
        valid_hours=2,
        registered=90,
        limit=200,
        module="德育",
        labels=["思想成长", "学术诚信"],
        description="公开主题报告，无需提交作品。",
    ),
    activity(
        "sport-20260901",
        "新生体能训练体验",
        start="2026-09-01T17:00:00",
        end="2026-09-01T18:30:00",
        valid_hours=1.5,
        registered=45,
        limit=60,
        module="体育",
        labels=["体育锻炼"],
        description="需穿运动服装，根据个人身体情况参加。",
    ),
    activity(
        "club-workshop-20260829",
        "机器人社团小组工作坊",
        start="2026-08-29T15:00:00",
        end="2026-08-29T18:00:00",
        valid_hours=1,
        registered=12,
        limit=12,
        module="智育",
        labels=["社团活动", "实践训练"],
        description="小组动手活动，需要自带电脑并完成预习材料。",
    ),
    activity(
        "history-lecture-20260822",
        "科技史专题讲座",
        start="2026-08-22T19:00:00",
        end="2026-08-22T21:00:00",
        valid_hours=2,
        registered=150,
        limit=200,
        module="智育",
        labels=["学术讲座"],
        description="已经结束的公开讲座。",
        status_code=40,
        status_text="结项",
    ),
    activity(
        "series-career-2026",
        "生涯发展系列讲座",
        start="2026-08-29T09:00:00",
        end="2026-09-05T21:00:00",
        valid_hours=0,
        registered=0,
        limit=500,
        module="智育",
        labels=["系列活动"],
        description="系列入口，请查看各子活动场次。",
        kind="series",
    ),
)

SERIES_CHILDREN = (
    activity(
        "series-career-child-1",
        "生涯发展系列讲座第一场",
        start="2026-08-29T09:00:00",
        end="2026-08-29T10:30:00",
        valid_hours=1.5,
        registered=120,
        limit=300,
        module="智育",
        labels=["系列活动", "公开讲座"],
        description="系列活动第一场。",
    ),
)


def result(items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "available": True,
        "authentication": "connected",
        "items": items,
        "total": len(items),
        "source_url": SOURCE_URL,
        "fetched_at": FETCHED_AT,
        **extra,
    }


def public_activity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"is_registered", "can_apply", "contact"}
    }


def create_mcp() -> FastMCP:
    mcp = FastMCP("USTC Young fixture")

    @mcp.tool()
    def young_connection_status() -> dict[str, Any]:
        return {
            "ok": True,
            "available": True,
            "authentication": "configured",
            "reason": None,
            "provider": "fixture",
            "provider_revision": "young-fixture-v1",
            "fetched_at": FETCHED_AT,
        }

    @mcp.tool()
    def young_search_activities(
        query: str = "",
        state: str = "applying",
        module_id: str = "",
        department_id: str = "",
        label_ids: list[str] | None = None,
        start_time: str = "",
        end_time: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        del module_id, department_id, label_ids
        values = [public_activity(item) for item in ACTIVITIES]
        if state.casefold() in {"ended", "finished", "history"}:
            values = [item for item in values if item["status"]["code"] != 26]
        else:
            values = [item for item in values if item["status"]["code"] == 26]
        if query:
            values = [item for item in values if query.casefold() in str(item["name"]).casefold()]
        if start_time:
            start = datetime.fromisoformat(start_time)
            end = datetime.fromisoformat(end_time or start_time)
            values = [
                item
                for item in values
                if datetime.fromisoformat(str(item["event_window"]["start"])) <= end
                and datetime.fromisoformat(str(item["event_window"]["end"])) >= start
            ]
        return result(values[:limit])

    @mcp.tool()
    def young_get_activity(
        activity_id: str,
        include_children: bool = False,
    ) -> dict[str, Any]:
        source = next(
            (value for value in ACTIVITIES if value["activity_id"] == activity_id),
            None,
        )
        item = public_activity(source) if source is not None else None
        values = [item] if item is not None else []
        return result(
            values,
            activity=item,
            children=(
                [public_activity(value) for value in SERIES_CHILDREN]
                if include_children and item is not None
                else []
            ),
        )

    @mcp.tool()
    def young_list_facets(facet: str) -> dict[str, Any]:
        values = {
            "module": [
                {"id": f"module-{name}", "name": name, "level": None}
                for name in ("德育", "智育", "体育", "美育", "劳育")
            ],
            "label": [
                {"id": "label-lecture", "name": "学术讲座", "level": None},
                {"id": "label-volunteer", "name": "志愿服务", "level": None},
            ],
            "department": [
                {"id": "department-fixture", "name": "校团委", "level": 1}
            ],
        }.get(facet, [])
        return result(values)

    return mcp


if __name__ == "__main__":
    create_mcp().run()
