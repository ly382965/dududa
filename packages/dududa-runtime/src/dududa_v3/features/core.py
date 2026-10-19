"""Built-in commands: help, ping, status, time, memory, session control, tasks and models."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import CHANNELS, SERVICES
from .base import Command, Ctx, Delegate, Registry, Reply

ZONES = (("上海", "Asia/Shanghai"), ("美西", "America/Los_Angeles"), ("美东", "America/New_York"),
         ("巴黎", "Europe/Paris"))
WEEKDAYS = "一二三四五六日"
SERVICE_LABELS = {"qa": "问答", "summary": "群聊总结", "vision": "识图（猫图等）", "image": "生图"}
CHANNEL_LABELS = {"chat": "问答与工具调用", "summary": "群聊总结", "image": "生图"}
PING_WINDOW, PING_LIMIT = 60.0, 3
_pings: dict[str, list[float]] = {}


def duration(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    parts = [f"{days}天" if days else "", f"{hours}小时" if hours or days else "", f"{minutes}分钟"]
    return "".join(parts)


async def help_command(ctx: Ctx) -> Reply:
    lines = ["【嘟嘟哒功能列表】", "用法：嘟嘟哒 <指令>、/<指令> 或 @嘟嘟哒 <指令>；其他内容直接当作提问。"]
    for command in ctx.runtime.registry.commands:
        if command.task and not ctx.runtime.task_enabled(command.task):
            continue
        if not command.help or (command.admin and not ctx.is_admin):
            continue
        lines.append("· " + command.help)
    registry = ctx.runtime.registry
    # Commands already describe themselves; list passive observers, and background jobs for admins only.
    passive = [item.task for item in registry.observers]
    if ctx.is_admin:
        passive += [item.task for item in registry.jobs]
    automatic = [registry.tasks[task] for task in dict.fromkeys(passive)
                 if task in registry.tasks and ctx.runtime.task_enabled(task)]
    if automatic:
        lines.append("【自动功能】")
        lines += [f"· {task.name}：{task.description}" for task in automatic]
    limits = ctx.settings.rate_limits
    lines.append(f"【频率限制】主动回复每 {int(limits.get('window_seconds', 300)) // 60} 分钟："
                 f"私聊 {int(limits.get('private', 50))} 次、群聊 {int(limits.get('group', 30))} 次。")
    return Reply.of_text("\n".join(lines))


async def ping_command(ctx: Ctx) -> Reply | None:
    key = ctx.inbound.scope + "/" + ctx.inbound.sender.id
    now = time.monotonic()
    recent = [at for at in _pings.get(key, []) if now - at < PING_WINDOW] + [now]
    _pings[key] = recent
    if len(recent) > PING_LIMIT:
        if len(recent) == PING_LIMIT + 1:
            await ctx.runtime.emit(ctx, "ping_spam")
        return None
    if len(recent) == PING_LIMIT:
        return Reply.of_text("在的在的！再问我就不理你了哼～")
    return Reply.of_text("在呢～")


async def status_command(ctx: Ctx) -> Reply:
    health = ctx.runtime.health()
    name, spec = ctx.runtime.model_spec("qa")
    return Reply.of_text(
        f"嘟嘟哒已持续服务 {duration(health['uptime_seconds'])}\n"
        f"版本 {health['version']} · 核心 omp + {spec.model.split('/')[-1]}（{name}，{spec.thinking}）\n"
        f"其他进行中的对话 {max(0, health['active_runs'] - 1)} 个 · 定时任务 {health['jobs']} 个")


def world_time() -> str:
    lines = []
    for label, zone in ZONES:
        now = datetime.now(ZoneInfo(zone))
        offset = now.utcoffset()
        hours = int(offset.total_seconds() // 3600) if offset else 0
        lines.append(f"{label}：{now:%Y-%m-%d %H:%M} 周{WEEKDAYS[now.weekday()]}（{now.tzname()}，UTC{hours:+d}）")
    return "\n".join(lines)


async def time_command(ctx: Ctx) -> Reply:
    return Reply.of_text(world_time())


async def remember_command(ctx: Ctx) -> str:
    if ctx.inbound.preview:
        return "预览模式不写入记忆。"
    if not ctx.args:
        return "用法：嘟嘟哒 记住 <内容>"
    memory_id = ctx.store.remember(ctx.session_id, ctx.inbound.sender.id, ctx.args)
    return f"已记住（当前会话 #{memory_id}）。"


async def memory_command(ctx: Ctx) -> str:
    memories = ctx.store.memories(ctx.session_id, ctx.args)
    return "\n".join(f"#{item['id']} {item['text']}" for item in memories) or "当前会话没有匹配记忆。"


async def forget_command(ctx: Ctx) -> str:
    if ctx.inbound.preview:
        return "预览模式不删除记忆。"
    if not ctx.args.isdigit():
        return "用法：嘟嘟哒 忘记 <记忆编号>"
    deleted = ctx.store.forget(ctx.session_id, ctx.inbound.sender.id, int(ctx.args))
    return "已删除。" if deleted else "未找到你在当前会话写入的这条记忆。"


async def cancel_command(ctx: Ctx) -> str:
    await ctx.runtime.cancel_session(ctx.session_id, ctx.run_id)
    return "已取消当前会话任务。"


async def new_command(ctx: Ctx) -> str:
    await ctx.runtime.cancel_session(ctx.session_id, ctx.run_id)
    ctx.store.thread(ctx.session_id, None)
    return "已开始新对话。"


async def shuttle_command(ctx: Ctx) -> str:
    if not ctx.args:
        return "用法：嘟嘟哒 校车 明天东区到高新校区"
    from ..services import ServiceHub
    hub = ServiceHub(ctx.settings, ctx.store, ctx.session_id, ctx.run_id)
    result = await asyncio.to_thread(hub.call, "shuttle_query", {"query": ctx.args})
    return json.dumps(result, ensure_ascii=False, indent=2)


async def summary_command(ctx: Ctx) -> Delegate:
    return Delegate(prompt=ctx.args or "总结群聊", summary=True)


# ---------------------------------------------------------------- tasks


def find_task(ctx: Ctx, query: str):
    query = query.strip().lower()
    for task in ctx.runtime.registry.tasks.values():
        if query in (task.id.lower(), task.name.lower(), *(alias.lower() for alias in task.aliases)):
            return task
    return None


def task_line(ctx: Ctx, task) -> str:
    switches = ctx.store.switches()
    state = "开" if ctx.runtime.task_enabled(task.id) else "关"
    source = "（手动）" if task.id in switches else "（默认）"
    return f"[{state}]{source} {task.id} · {task.name}"


async def task_command(ctx: Ctx) -> str:
    action, _, target = ctx.args.partition(" ")
    action = action.lower()
    tasks = ctx.runtime.registry.tasks
    if action in ("", "list", "列表", "ls"):
        if not tasks:
            return "当前没有可开关的任务。"
        return "【全局任务开关】\n" + "\n".join(task_line(ctx, task) for task in tasks.values())
    task = find_task(ctx, target)
    if task is None:
        if target.strip().lower() in ("防撤回", "recall", "recall_forward"):
            return "防撤回为群独立设置。请在目标群中由超级管理员发送：@嘟嘟哒 /开启防撤回 或 /关闭防撤回"
        return f"没有找到任务「{target}」。发送 嘟嘟哒 task list 查看全部任务。"
    if action in ("show", "详情"):
        aliases = "、".join(task.aliases) or "无"
        return f"{task_line(ctx, task)}\n说明：{task.description}\n别名：{aliases}\n默认：{'开' if task.default else '关'}"
    if action in ("on", "开启", "打开"):
        ctx.store.set_switch(task.id, True, ctx.inbound.sender.id)
    elif action in ("off", "关闭"):
        ctx.store.set_switch(task.id, False, ctx.inbound.sender.id)
    elif action in ("reset", "重置"):
        ctx.store.set_switch(task.id, None, ctx.inbound.sender.id)
    else:
        return "用法：task list | task show <任务> | task on|off|reset <任务>"
    return "已更新：" + task_line(ctx, task)


def switch_alias(action: str):
    async def handler(ctx: Ctx) -> str:
        ctx.args = f"{action} {ctx.args}".strip()
        return await task_command(ctx)
    return handler


# ---------------------------------------------------------------- models


def model_catalog(ctx: Ctx) -> str:
    return "\n".join(f"  {name}: {value['model']} · {value.get('thinking', 'max')}"
                     for name, value in ctx.settings.models.items())


async def model_command(ctx: Ctx) -> str:
    words = ctx.args.split()
    bindings = ctx.store.model_bindings()
    if words[:1] == ["service"]:
        action, rest = (words[1].lower() if len(words) > 1 else "list"), words[2:]
        if action == "list":
            lines = ["【模型服务】"]
            for service, label in SERVICE_LABELS.items():
                name = ctx.runtime.model_spec(service)[0]
                origin = "管理员设置" if f"service:{service}" in bindings else (
                    "配置默认" if service in ctx.settings.service_defaults else f"继承 {SERVICES[service]}")
                lines.append(f"  {service}（{label}）→ {name}（{origin}）")
            return "\n".join(lines) + "\n可用注册名：\n" + model_catalog(ctx)
        if action == "set" and len(rest) == 2 and rest[0] in SERVICES and rest[1] in ctx.settings.models:
            ctx.store.bind_model(f"service:{rest[0]}", rest[1], ctx.inbound.sender.id)
            return f"已将 {rest[0]} 服务切换为 {rest[1]}。"
        if action == "reset" and len(rest) == 1 and rest[0] in SERVICES:
            ctx.store.bind_model(f"service:{rest[0]}", None, ctx.inbound.sender.id)
            return f"已重置 {rest[0]} 服务，现在使用 {ctx.runtime.model_spec(rest[0])[0]}。"
        return ("用法：model service list | model service set <" + "|".join(SERVICES) + "> <注册名> | "
                "model service reset <服务>")
    action, rest = (words[0].lower() if words else "list"), words[1:]
    if action == "list":
        lines = ["【模型通道】"]
        for channel, label in CHANNEL_LABELS.items():
            name = bindings.get(f"channel:{channel}") or ctx.settings.model_defaults.get(channel)
            origin = "管理员设置" if f"channel:{channel}" in bindings else "默认"
            lines.append(f"  {channel}（{label}）→ {name}（{origin}）")
        return "\n".join(lines) + "\n可用注册名：\n" + model_catalog(ctx)
    if action == "set" and len(rest) == 2 and rest[0] in CHANNELS and rest[1] in ctx.settings.models:
        ctx.store.bind_model(f"channel:{rest[0]}", rest[1], ctx.inbound.sender.id)
        return f"已将 {rest[0]} 通道切换为 {rest[1]}。"
    if action == "reset" and len(rest) == 1 and rest[0] in CHANNELS:
        ctx.store.bind_model(f"channel:{rest[0]}", None, ctx.inbound.sender.id)
        return f"已重置 {rest[0]} 通道为 {ctx.settings.model_defaults.get(rest[0])}。"
    return "用法：model list | model set <" + "|".join(CHANNELS) + "> <注册名> | model reset <通道> | model service ..."


def register(registry: Registry) -> None:
    add = registry.command
    add(Command(("help", "帮助", "菜单"), help_command, "help / 帮助：查看功能列表", exact=True))
    add(Command(("ping", "在吗", "在不在"), ping_command, "ping / 在吗：检查是否在线（反复刷会被无视）", exact=True))
    add(Command(("status", "状态"), status_command, "status / 状态：查看持续服务时长与运行状态", exact=True))
    add(Command(("time", "时间", "几点了"), time_command, "time / 时间：上海、美西、美东、巴黎时间（自动夏令时）", exact=True))
    add(Command(("群里最近在说什么", "近期消息省流", "总结群聊", "summary"), summary_command,
                "群里最近在说什么 / 近期消息省流：群聊总结（可加“今日”“近5h”）"))
    add(Command(("remember", "记住"), remember_command, "记住 <内容>：保存当前会话记忆"))
    add(Command(("memory", "记忆"), memory_command, "记忆 [关键词]：搜索当前会话记忆"))
    add(Command(("forget", "忘记"), forget_command, "忘记 <编号>：删除自己写入的记忆"))
    add(Command(("shuttle", "校车"), shuttle_command, "校车 <条件>：查询科大校车"))
    add(Command(("cancel", "取消"), cancel_command, "取消：取消当前会话的任务", exact=True))
    add(Command(("new", "新对话"), new_command, "新对话：开启新的 AI 对话（保留记忆）", exact=True))
    add(Command(("task", "任务"), task_command, "task list|show|on|off|reset <任务>：全局任务开关（白名单）", admin=True))
    add(Command(("开启",), switch_alias("on"), "开启/关闭 <任务>：例如 开启 复读机（白名单）", admin=True))
    add(Command(("关闭",), switch_alias("off"), "", admin=True))
    add(Command(("model", "模型"), model_command,
                "model list|set|reset、model service list|set|reset：切换模型（白名单）", admin=True))
