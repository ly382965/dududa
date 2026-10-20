"""LLM provider status: on-demand overview and push alerts for DeepSeek, Anthropic and OpenAI incidents."""

from __future__ import annotations

import asyncio
import time

from .base import (
    Command,
    Ctx,
    FeatureError,
    Job,
    JobCtx,
    Registry,
    Reply,
    Task,
    Tool,
    Toolkit,
)

FEATURE = "status_alerts"
TASK = "llm_status_alerts"
INTERVAL_SECONDS = 300

# DeepSeek's status page is hosted by Flashcat; ``summary/active`` lists unresolved changes.
DEEPSEEK_ACTIVE = "https://status.deepseek.com/api/status-page/6410630422455/summary/active"
PROVIDERS = {
    "openai": {"label": "OpenAI", "url": "https://status.openai.com/",
               # incident.io page exposing the Statuspage-compatible summary (no incident list) + incidents.json.
               "summary": "https://status.openai.com/api/v2/summary.json",
               "incidents": "https://status.openai.com/api/v2/incidents.json"},
    "anthropic": {"label": "Anthropic", "url": "https://status.claude.com/",
                  "summary": "https://status.claude.com/api/v2/summary.json"},
    "deepseek": {"label": "DeepSeek", "url": "https://status.deepseek.com/", "flashcat": DEEPSEEK_ACTIVE},
}
INDICATOR_LABELS = {"none": "✅ 正常", "minor": "⚠️ 轻微异常", "major": "🟠 部分中断", "critical": "🔴 严重中断",
                    "maintenance": "🛠 维护中", "unknown": "❔ 获取失败"}
SEVERITY = {"none": 0, "maintenance": 1, "minor": 2, "major": 3, "critical": 4}
STATUS_LABELS = {"investigating": "调查中", "identified": "已定位", "monitoring": "观察中", "resolved": "已解决",
                 "postmortem": "复盘", "in_progress": "进行中", "scheduled": "计划中", "verifying": "验证中",
                 "ongoing": "进行中", "completed": "已完成"}
CLOSED = {"resolved", "postmortem", "completed", "cancelled"}
COMPONENT_IMPACT = {"degraded": "minor", "degraded_performance": "minor", "partial_outage": "major",
                    "full_outage": "critical", "major_outage": "critical", "under_maintenance": "maintenance"}


# ---------------------------------------------------------------- parsers (pure)


def parse_statuspage(summary: dict, incidents: dict | None, url: str) -> dict:
    """Statuspage ``summary.json`` (+ optional ``incidents.json`` for pages whose summary omits them)."""
    indicator = str((summary.get("status") or {}).get("indicator") or "none")
    seen, components = set(), []
    for component in summary.get("components") or []:
        status = component.get("status") or "operational"
        if status != "operational" and not component.get("group") and component.get("name") not in seen:
            seen.add(component.get("name"))
            components.append({"name": component.get("name", ""), "status": status})
    raw = list(summary.get("incidents") or [])
    raw += [item for item in summary.get("scheduled_maintenances") or [] if item.get("status") in ("in_progress", "verifying")]
    if incidents is not None:
        known = {item.get("id") for item in raw}
        raw += [item for item in incidents.get("incidents") or [] if item.get("id") not in known]
    active = []
    for item in raw:
        if item.get("status") in CLOSED:
            continue
        names = [c.get("name", "") for c in item.get("components") or []]
        updates = item.get("incident_updates") or []
        active.append({"id": str(item.get("id")), "name": item.get("name", ""), "status": item.get("status", ""),
                       "impact": item.get("impact") or "", "components": names,
                       "update": (updates[0].get("body") or "")[:200] if updates else "",
                       "url": item.get("shortlink") or url.rstrip("/") + f"/incidents/{item.get('id')}"})
    if active and indicator == "none":
        indicator = max((item["impact"] for item in active if item["impact"] in SEVERITY), key=SEVERITY.get,
                        default="minor")
    return {"indicator": indicator, "description": (summary.get("status") or {}).get("description") or "",
            "components": components, "incidents": active}


def parse_flashcat(payload: dict, url: str) -> dict:
    """Flashcat status page ``summary/active`` → normalized snapshot."""
    data = payload.get("data") or {}
    active, worst, components = [], "none", {}
    for change in data.get("active_changes") or []:
        if change.get("status") in CLOSED:
            continue
        maintenance = change.get("type") == "maintenance"
        impact = "maintenance" if maintenance else "none"
        names = []
        for component in change.get("affected_components") or []:
            status = component.get("status") or "operational"
            names.append(component.get("name", ""))
            if status != "operational":
                components[component.get("name", "")] = status
                level = COMPONENT_IMPACT.get(status, "minor")
                impact = level if SEVERITY[level] > SEVERITY[impact] else impact
        if impact == "none":
            impact = "minor"
        worst = impact if SEVERITY[impact] > SEVERITY[worst] else worst
        active.append({"id": str(change.get("change_id")), "name": change.get("title", ""),
                       "status": change.get("status", ""), "impact": impact, "components": names,
                       "update": (change.get("description") or "")[:200], "url": url})
    return {"indicator": worst, "description": "", "incidents": active,
            "components": [{"name": name, "status": status} for name, status in components.items()]}


def diff_events(provider: str, previous: dict, current: dict) -> list[dict]:
    """Alert-worthy changes between two snapshots: ``[{"key", "kind", "incident"?}]``."""
    events = []
    before = {item["id"]: item for item in previous.get("incidents") or []}
    after = {item["id"]: item for item in current.get("incidents") or []}
    for incident_id, item in after.items():
        old = before.get(incident_id)
        if old is None:
            events.append({"key": f"{provider}:{incident_id}:{item['status']}", "kind": "new", "incident": item})
        elif old["status"] != item["status"]:
            events.append({"key": f"{provider}:{incident_id}:{item['status']}", "kind": "update", "incident": item})
    for incident_id, item in before.items():
        if incident_id not in after:
            events.append({"key": f"{provider}:{incident_id}:resolved", "kind": "resolved", "incident": item})
    if not events:   # Degradation without a published incident (or its recovery).
        old, new = previous.get("indicator", "none"), current.get("indicator", "none")
        if old != new and (old == "none" or new == "none"):
            events.append({"key": f"{provider}:indicator:{new}:{int(time.time())}",
                           "kind": "recovered" if new == "none" else "degraded"})
    return events


def format_alert(provider: str, snapshot: dict, events: list[dict]) -> str:
    label = PROVIDERS[provider]["label"]
    recovered = all(event["kind"] in ("resolved", "recovered") for event in events)
    lines = [f"【{label} 服务{'恢复' if recovered else '状态告警'}】"]
    for event in events:
        item = event.get("incident")
        if event["kind"] == "new":
            lines.append(f"新事件：{item['name']}（{STATUS_LABELS.get(item['status'], item['status'])}）")
        elif event["kind"] == "update":
            lines.append(f"事件进展：{item['name']} → {STATUS_LABELS.get(item['status'], item['status'])}")
        elif event["kind"] == "resolved":
            lines.append(f"已解决：{item['name']}")
        elif event["kind"] == "degraded":
            lines.append("官方状态页显示服务异常（暂未发布事件说明）")
        else:
            lines.append("所有组件已恢复正常")
        if item and event["kind"] != "resolved":
            if item["components"]:
                lines.append("影响：" + "、".join(item["components"][:6]) + ("等" if len(item["components"]) > 6 else ""))
            if item["update"]:
                lines.append("说明：" + item["update"].replace("\n", " "))
    lines.append(f"当前总体：{INDICATOR_LABELS.get(snapshot['indicator'], snapshot['indicator'])}")
    if snapshot["components"] and not recovered:
        lines.append("异常组件：" + "、".join(f"{c['name']}({c['status']})" for c in snapshot["components"][:6]))
    lines.append(PROVIDERS[provider]["url"])
    return "\n".join(lines)


def format_overview(snapshots: dict[str, dict]) -> str:
    lines = ["【大模型服务状态】"]
    for provider, snapshot in snapshots.items():
        label = PROVIDERS[provider]["label"]
        if snapshot.get("error"):
            lines.append(f"· {label}：{INDICATOR_LABELS['unknown']}（{snapshot['error']}）")
            continue
        lines.append(f"· {label}：{INDICATOR_LABELS.get(snapshot['indicator'], snapshot['indicator'])}")
        for item in snapshot["incidents"][:3]:
            lines.append(f"  - {item['name']}（{STATUS_LABELS.get(item['status'], item['status'])}）")
        if not snapshot["incidents"] and snapshot["components"]:
            lines.append("  异常组件：" + "、".join(c["name"] for c in snapshot["components"][:5]))
    return "\n".join(lines)


# ---------------------------------------------------------------- fetching


async def fetch_snapshot(ctx: Toolkit, provider: str) -> dict:
    spec = PROVIDERS[provider]
    if "flashcat" in spec:
        return parse_flashcat(await ctx.fetch_json(spec["flashcat"], timeout=20), spec["url"])
    summary = await ctx.fetch_json(spec["summary"], timeout=20)
    incidents = await ctx.fetch_json(spec["incidents"], timeout=20) if "incidents" in spec else None
    return parse_statuspage(summary, incidents, spec["url"])


async def fetch_all(ctx: Toolkit) -> dict[str, dict]:
    results = await asyncio.gather(*(fetch_snapshot(ctx, provider) for provider in PROVIDERS), return_exceptions=True)
    snapshots = {}
    for provider, result in zip(PROVIDERS, results):
        if isinstance(result, FeatureError):
            snapshots[provider] = {"error": str(result)}
        elif isinstance(result, Exception):
            snapshots[provider] = {"error": f"解析失败：{type(result).__name__}"}
        else:
            snapshots[provider] = result
    return snapshots


# ---------------------------------------------------------------- handlers


async def alert_job(ctx: JobCtx) -> None:
    targets = [str(scope) for scope in ctx.config(FEATURE).get("targets") or [] if "/" in str(scope)]
    snapshots = await fetch_all(ctx)
    for provider, snapshot in snapshots.items():
        if snapshot.get("error"):
            continue   # Keep the previous state; a fetch blip is not an incident.
        previous = ctx.kv_get(FEATURE, f"state:{provider}")
        ctx.kv_set(FEATURE, f"state:{provider}", {**snapshot, "at": time.time()})
        if previous is None:
            continue   # First observation is the baseline.
        events = diff_events(provider, previous, snapshot)
        if not events:
            continue
        text = format_alert(provider, snapshot, events)
        key = "|".join(sorted(event["key"] for event in events))
        for scope in targets:
            ctx.push(scope, Reply.of_text(text), dedupe=f"status:{key}@{scope}")


async def status_command(ctx: Ctx) -> str:
    return format_overview(await fetch_all(ctx))


async def status_tool(ctx: Ctx, args: dict) -> dict:
    snapshots = await fetch_all(ctx)
    return {"ok": True, "providers": {PROVIDERS[p]["label"]: s for p, s in snapshots.items()},
            "summary": format_overview(snapshots)}


def register(registry: Registry) -> None:
    registry.task(Task(TASK, "LLM 状态告警", "OpenAI / Anthropic / DeepSeek 官方状态页出现故障或恢复时推送提醒",
                       aliases=("状态告警",)))
    registry.command(Command(("状态告警", "llm status", "llm状态"), status_command,
                             "状态告警 / llm status：查看 OpenAI、Anthropic、DeepSeek 服务状态", exact=True))
    registry.tool(Tool("llm_service_status",
                       "查询 OpenAI、Anthropic(Claude)、DeepSeek 官方状态页的实时状态与进行中的故障事件。"
                       "用户问某个模型/API 是不是挂了、为什么用不了时使用。",
                       {"type": "object", "properties": {}, "additionalProperties": False}, status_tool))
    registry.job(Job(TASK, INTERVAL_SECONDS, alert_job, initial_delay_seconds=45))
