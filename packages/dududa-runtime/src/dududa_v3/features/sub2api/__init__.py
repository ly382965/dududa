"""Sub2API usage statistics (port of the AstrBot plugin ``astrbot_plugin_sub2api_readonly``).

``/sub2api <子命令>`` (aliases ``sub2``, ``用量``) answers only in ``group_whitelist`` groups and for
``private_user_whitelist`` users. ``exclusive_groups`` are groups where the bot handles nothing but
these commands; that is enforced by a ``Gate`` before routing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...router import Route, strip_prefix
from ..base import Command, Ctx, Delegate, Gate, Inbound, Registry, Reply, Task
from .client import (
    DateRange,
    Sub2APIAuthError,
    Sub2APIClient,
    Sub2APIConfigError,
    Sub2APIError,
    Sub2APIRequestError,
    fallback_cost_overview,
    overview_history_period,
    parse_date_range,
    parse_trend_period,
    parse_user_trend_request,
    today_in_timezone,
    urllib_transport,
)
from .formatters import (
    format_account,
    format_accounts,
    format_cost_overview_snapshot,
    format_models,
    format_overview_history,
    format_range,
    format_status,
    format_today,
    format_total,
    format_total_trend_text,
    format_user_ranking,
    format_user_trend_text,
)

FEATURE = "sub2api"
TASK = "sub2api"
COMMAND_NAMES = ("sub2api", "sub2", "用量")
CHART_SCRIPT = Path(__file__).with_name("charts.py")
CHART_TIMEOUT_SECONDS = 60.0
TREND_USERS = 10
log = logging.getLogger("dududa_v3.sub2api")

HELP_TEXT = """Sub2API 只读查询
/sub2api overview - 今日、当前计费轮、7 月 13 日至今累计和上游账号状态
/sub2api today - 今日 Token 与用户排名
/sub2api total - 历史累计用量
/sub2api range YYYY-MM-DD YYYY-MM-DD - 日期区间汇总
/sub2api trendtotal [天数d] - 总 Token 用量趋势图，默认 7d
/sub2api trenduser [天数d] - 前 10 名用户 Token 趋势图，默认 7d
/sub2api trenduser sum [天数d] - 前 10 名用户区间累计趋势，默认 7d
/sub2api users [开始日期] [结束日期] - 用户 Token 排名，默认今日
/sub2api models [开始日期] [结束日期] - 模型用量，默认今日
/sub2api accounts - 上游账号状态
/sub2api account <账号ID> - 单个账号状态与今日用量
/sub2api status - 连接和统计状态
/sub2api help - 本帮助
所有业务数据均来自 Sub2API 管理网页使用的只读 GET 接口。"""


# ---------------------------------------------------------------- configuration


def _str_set(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple, set)):
        return frozenset(str(item).strip() for item in value if str(item).strip())
    return frozenset()


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _clamp(value: Any, default: float, minimum: float, maximum: float, kind: type = int) -> Any:
    try:
        parsed = kind(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


@dataclass(frozen=True)
class Options:
    """``features.sub2api`` with the plugin's defaults and clamps."""

    enabled: bool = False
    base_url: str = ""
    admin_email: str = ""
    admin_password: str = field(default="", repr=False)
    group_whitelist: frozenset[str] = frozenset()
    exclusive_groups: frozenset[str] = frozenset()
    private_user_whitelist: frozenset[str] = frozenset()
    timezone: str = "Asia/Shanghai"
    ranking_limit: int = 10
    account_limit: int = 30
    model_limit: int = 10
    max_trend_rows: int = 14
    max_range_days: int = 90
    request_timeout_seconds: float = 30
    cache_ttl_seconds: float = 30
    reveal_user_identifiers: bool = False
    show_account_names: bool = False
    chart_python: str = ""

    @classmethod
    def from_config(cls, cfg: dict) -> Options:
        return cls(
            enabled=_bool(cfg.get("enabled", False), False),
            base_url=str(cfg.get("base_url") or "").strip(),
            admin_email=str(cfg.get("admin_email") or "").strip(),
            admin_password=str(cfg.get("admin_password") or "").strip(),
            group_whitelist=_str_set(cfg.get("group_whitelist", [])),
            exclusive_groups=_str_set(cfg.get("exclusive_groups", [])),
            private_user_whitelist=_str_set(cfg.get("private_user_whitelist", [])),
            timezone=str(cfg.get("timezone", "Asia/Shanghai") or "").strip(),
            ranking_limit=_clamp(cfg.get("ranking_limit", 10), 10, 1, 100),
            account_limit=_clamp(cfg.get("account_limit", 30), 30, 1, 100),
            model_limit=_clamp(cfg.get("model_limit", 10), 10, 1, 50),
            max_trend_rows=_clamp(cfg.get("max_trend_rows", 14), 14, 1, 90),
            max_range_days=_clamp(cfg.get("max_range_days", 90), 90, 1, 3660),
            request_timeout_seconds=_clamp(cfg.get("request_timeout_seconds", 30), 30, 3, 60, float),
            cache_ttl_seconds=_clamp(cfg.get("cache_ttl_seconds", 30), 30, 0, 600, float),
            reveal_user_identifiers=_bool(cfg.get("reveal_user_identifiers", False), False),
            show_account_names=_bool(cfg.get("show_account_names", False), False),
            chart_python=str(cfg.get("chart_python") or "").strip(),
        )


def access_error(options: Options, inbound: Inbound) -> str | None:
    """The plugin's default-deny scope check; ``None`` means the caller may query."""
    if not options.enabled:
        return "Sub2API 查询插件当前已关闭。"
    if inbound.is_group:
        if not options.group_whitelist:
            return "Sub2API 群聊白名单尚未配置，已拒绝查询。"
        if inbound.peer_id not in options.group_whitelist:
            return f"当前群（{inbound.peer_id}）不在 Sub2API 查询白名单中。"
        return None
    if inbound.sender.id.strip() in options.private_user_whitelist:
        return None
    return "Sub2API 私聊查询未授权。"


def is_exclusive_group(options: Options, inbound: Inbound) -> bool:
    return inbound.is_group and inbound.peer_id in options.exclusive_groups


def exclusive_allows(ctx: Ctx, decision: Route) -> bool:
    """Gate: in ``exclusive_groups`` only Sub2API commands get through (everything else is dropped silently)."""
    if not ctx.inbound.is_group:
        return True
    cfg = ctx.config(FEATURE)
    if not _bool(cfg.get("enabled", False), False) or ctx.inbound.peer_id not in _str_set(
            cfg.get("exclusive_groups", [])):
        return True
    return decision.kind == "command" and decision.command is not None and decision.command.task == TASK


# ---------------------------------------------------------------- client and charts

_clients: dict[tuple, Sub2APIClient] = {}


def client_for(ctx: Ctx, options: Options) -> Sub2APIClient:
    """One long-lived client per configuration, so the login token and response cache are reused."""
    key = (options.base_url, options.admin_email, hashlib.sha256(options.admin_password.encode()).hexdigest(),
           options.timezone, options.request_timeout_seconds, options.cache_ttl_seconds,
           ctx.settings.proxy_url, ctx.settings.direct_hosts)
    client = _clients.get(key)
    if client is None:
        client = Sub2APIClient(
            base_url=options.base_url, email=options.admin_email, password=options.admin_password,
            transport=urllib_transport(proxy_url=ctx.settings.proxy_url, direct_hosts=ctx.settings.direct_hosts),
            timezone=options.timezone, timeout_seconds=options.request_timeout_seconds,
            cache_ttl_seconds=options.cache_ttl_seconds)
        _clients.clear()
        _clients[key] = client
    return client


def chart_python(ctx: Ctx, options: Options) -> Path:
    if options.chart_python:
        return Path(options.chart_python)
    return ctx.settings.state_dir / "features/notify/worker-venv/bin/python"


async def render_chart(python: Path, request: dict) -> bytes | None:
    """PNG from ``charts.py`` under a Pillow-capable interpreter; ``None`` means fall back to text."""
    if not python.is_file() or not os.access(python, os.X_OK):
        log.warning("sub2api chart interpreter %s is unavailable; sending text", python)
        return None
    process = await asyncio.create_subprocess_exec(
        str(python), "-I", str(CHART_SCRIPT), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(request, ensure_ascii=False).encode("utf-8")), CHART_TIMEOUT_SECONDS)
    except TimeoutError:
        log.warning("sub2api chart worker timed out")
        return None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode or not stdout.startswith(b"\x89PNG"):
        log.warning("sub2api chart worker failed (%s): %s", process.returncode,
                    stderr.decode("utf-8", "replace")[-400:])
        return None
    return stdout


# ---------------------------------------------------------------- subcommands


def today_period(options: Options) -> DateRange:
    today = today_in_timezone(options.timezone)
    return DateRange(start=today, end=today)


def optional_period(options: Options, args: list[str]) -> DateRange:
    if not args:
        return today_period(options)
    if len(args) < 2:
        raise Sub2APIConfigError("请同时提供开始日期和结束日期。")
    return parse_date_range(args[0], args[1], timezone=options.timezone, max_days=options.max_range_days)


async def cost_overview_optional(client: Sub2APIClient) -> dict[str, Any] | None:
    try:
        return await client.get_cost_overview()
    except Sub2APIRequestError:
        return None


async def overview_command(ctx: Ctx, options: Options, args: list[str]) -> Reply:
    client = client_for(ctx, options)
    period = today_period(options)
    history_period = overview_history_period(options.timezone)
    stats, today_ranking, cost_overview, history_stats, history_ranking, accounts = await asyncio.gather(
        client.get_stats(),
        client.get_user_ranking(period, limit=options.ranking_limit),
        cost_overview_optional(client),
        client.get_usage_stats(history_period),
        client.get_user_ranking(history_period, limit=options.ranking_limit),
        client.get_accounts())
    if cost_overview is None:
        log.warning("Sub2API cost overview unavailable; using account metadata fallback")
        cost_overview = fallback_cost_overview(accounts, timezone=options.timezone)
        estimate = cost_overview.get("pro_estimate")
        if isinstance(estimate, dict):
            try:
                cost_overview["pro_estimate"] = await client.get_pro_quota_estimate(
                    estimate, synced_at=str(cost_overview.get("synced_at") or "") or None)
            except Sub2APIError as exc:
                log.warning("Sub2API Pro quota fallback unavailable: %s", type(exc).__name__)
    cycle_usage = await client.get_usage_ranking_since(
        str(cost_overview.get("period_start") or ""), str(cost_overview.get("period_end") or ""),
        synced_at=str(cost_overview.get("synced_at") or "") or None, limit=options.ranking_limit)
    reveal = options.reveal_user_identifiers
    sections = (
        format_today(stats, today_ranking, reveal_users=reveal, ranking_limit=options.ranking_limit),
        format_cost_overview_snapshot(cost_overview, cycle_usage, ranking_limit=options.ranking_limit),
        format_overview_history(history_stats, history_ranking, history_period, reveal_users=reveal,
                                ranking_limit=options.ranking_limit),
        format_accounts(accounts, show_account_names=options.show_account_names, reveal_identifiers=reveal,
                        max_rows=options.account_limit),
    )
    return Reply().forward([{"name": "Sub2API", "actions": [{"type": "text", "text": section}]}
                            for section in sections])


async def today_command(ctx: Ctx, options: Options, args: list[str]) -> str:
    client = client_for(ctx, options)
    stats, ranking = await asyncio.gather(
        client.get_stats(), client.get_user_ranking(today_period(options), limit=options.ranking_limit))
    return format_today(stats, ranking, reveal_users=options.reveal_user_identifiers,
                        ranking_limit=options.ranking_limit)


async def total_command(ctx: Ctx, options: Options, args: list[str]) -> str:
    return format_total(await client_for(ctx, options).get_stats())


async def range_command(ctx: Ctx, options: Options, args: list[str]) -> str:
    if len(args) < 2:
        return "用法：/sub2api range YYYY-MM-DD YYYY-MM-DD"
    period = parse_date_range(args[0], args[1], timezone=options.timezone, max_days=options.max_range_days)
    client = client_for(ctx, options)
    snapshot, ranking, usage_stats = await asyncio.gather(
        client.get_snapshot(period), client.get_user_ranking(period, limit=options.ranking_limit),
        client.get_usage_stats(period))
    return format_range(snapshot, ranking, usage_stats, period, reveal_users=options.reveal_user_identifiers,
                        ranking_limit=options.ranking_limit, max_trend_rows=options.max_trend_rows,
                        max_model_rows=options.model_limit)


async def trend_total_command(ctx: Ctx, options: Options, args: list[str]) -> Reply | str:
    period = parse_trend_period(args[0] if args else "7d", timezone=options.timezone,
                                max_days=options.max_range_days)
    snapshot = await client_for(ctx, options).get_snapshot(period)
    png = await render_chart(chart_python(ctx, options), {
        "kind": "total", "snapshot": snapshot, "start": period.start.isoformat(), "end": period.end.isoformat()})
    if png:
        return Reply().image(png)
    return format_total_trend_text(snapshot, period, max_rows=options.max_trend_rows)


async def trend_user_command(ctx: Ctx, options: Options, args: list[str]) -> Reply | str:
    if len(args) > 2:
        raise Sub2APIConfigError("trenduser 参数格式应为 [天数d] 或 sum [天数d]。")
    period, cumulative = parse_user_trend_request(*(args + [None, None])[:2], timezone=options.timezone,
                                                  max_days=options.max_range_days)
    snapshot = await client_for(ctx, options).get_user_trend(period, limit=TREND_USERS)
    png = await render_chart(chart_python(ctx, options), {
        "kind": "user", "snapshot": snapshot, "start": period.start.isoformat(), "end": period.end.isoformat(),
        "reveal_identifiers": options.reveal_user_identifiers, "limit": TREND_USERS, "cumulative": cumulative})
    if png:
        return Reply().image(png)
    return format_user_trend_text(snapshot, period, reveal_identifiers=options.reveal_user_identifiers,
                                  cumulative=cumulative, limit=TREND_USERS)


async def users_command(ctx: Ctx, options: Options, args: list[str]) -> str:
    period = optional_period(options, args)
    client = client_for(ctx, options)
    ranking, usage_stats = await asyncio.gather(
        client.get_user_ranking(period, limit=options.ranking_limit), client.get_usage_stats(period))
    return format_user_ranking(ranking, period, usage_stats=usage_stats,
                               reveal_users=options.reveal_user_identifiers, ranking_limit=options.ranking_limit)


async def models_command(ctx: Ctx, options: Options, args: list[str]) -> str:
    period = optional_period(options, args)
    snapshot = await client_for(ctx, options).get_snapshot(period)
    return format_models(snapshot, period, max_rows=options.model_limit)


async def accounts_command(ctx: Ctx, options: Options, args: list[str]) -> str:
    rows = await client_for(ctx, options).get_accounts()
    return format_accounts(rows, show_account_names=options.show_account_names,
                           reveal_identifiers=options.reveal_user_identifiers, max_rows=options.account_limit)


async def account_command(ctx: Ctx, options: Options, args: list[str]) -> str:
    if not args:
        return "用法：/sub2api account <账号ID>"
    try:
        account_id = int(args[0])
        client = client_for(ctx, options)
        accounts, today_stats = await asyncio.gather(client.get_accounts(),
                                                     client.get_account_today_stats(account_id))
        row = next((item for item in accounts if int(item.get("id") or 0) == account_id), None)
    except (TypeError, ValueError):
        return "账号 ID 必须是正整数。"
    if row is None:
        raise Sub2APIRequestError(f"未找到账号 #{account_id}。")
    return format_account(row, today_stats, show_account_names=options.show_account_names,
                          reveal_identifiers=options.reveal_user_identifiers)


async def status_command(ctx: Ctx, options: Options, args: list[str]) -> str:
    client = client_for(ctx, options)
    version, stats = await asyncio.gather(client.get_system_version(), client.get_stats())
    return format_status(version, stats)


async def help_command(ctx: Ctx, options: Options, args: list[str]) -> str:
    return HELP_TEXT


Handler = Callable[[Ctx, Options, list[str]], Awaitable["Reply | str"]]
SUBCOMMANDS: tuple[tuple[tuple[str, ...], Handler], ...] = (
    (("help", "帮助"), help_command),
    (("overview", "概览", "汇总"), overview_command),
    (("today", "今日", "今天"), today_command),
    (("total", "历史", "累计"), total_command),
    (("range", "范围", "区间"), range_command),
    (("trendtotal", "trend", "总趋势"), trend_total_command),
    (("trenduser", "用户趋势"), trend_user_command),
    (("users", "用户", "排名", "排行"), users_command),
    (("models", "模型"), models_command),
    (("accounts", "账号", "账户"), accounts_command),
    (("account", "单账号", "单账户"), account_command),
    (("status", "状态", "连接"), status_command),
)
SUBCOMMAND_INDEX = {name: handler for names, handler in SUBCOMMANDS for name in names}


def error_reply(exc: Sub2APIError) -> str:
    if isinstance(exc, Sub2APIConfigError):
        return f"Sub2API 配置或参数错误：{exc}"
    if isinstance(exc, Sub2APIAuthError):
        log.warning("Sub2API authentication failed: %s", type(exc).__name__)
        return f"Sub2API 认证失败：{exc}"
    log.warning("Sub2API read-only query failed: %s", type(exc).__name__)
    return f"Sub2API 查询失败：{exc}"


async def sub2api_command(ctx: Ctx) -> Reply | Delegate | str | None:
    options = Options.from_config(ctx.config(FEATURE))
    body, slash, _ = strip_prefix(ctx.inbound.text, ctx.settings.bot_names)
    # `用量…` is also ordinary chat: name/@-addressed messages that are not a usable Sub2API
    # query go to the agent; explicit `/` commands keep the plugin's replies (silent in groups).
    error = access_error(options, ctx.inbound)
    if error:
        if not slash:
            return Delegate(body)
        return None if ctx.inbound.is_group else error
    words = ctx.args.split()
    if not words:
        return HELP_TEXT
    handler = SUBCOMMAND_INDEX.get(words[0].lower())
    if handler is None:
        if not slash and not is_exclusive_group(options, ctx.inbound):
            return Delegate(body)
        return f"未知的 Sub2API 子命令「{words[0][:20]}」。\n\n{HELP_TEXT}"
    try:
        reply = await handler(ctx, options, words[1:])
    except Sub2APIError as exc:
        reply = error_reply(exc)
    # Switched off while the request was running: stay silent like the plugin's output guard.
    return reply if ctx.enabled(TASK) else None


def register(registry: Registry) -> None:
    registry.task(Task(TASK, "Sub2API 用量统计", "授权群内用 /sub2api 查询 Sub2API Token 用量、排名与上游账号状态",
                       aliases=("用量统计",)))
    registry.command(Command(COMMAND_NAMES, sub2api_command,
                             "sub2api / 用量 <子命令>：Sub2API 用量统计（仅限授权群，/sub2api help 查看子命令）",
                             task=TASK))
    registry.gate(Gate(TASK, exclusive_allows))
