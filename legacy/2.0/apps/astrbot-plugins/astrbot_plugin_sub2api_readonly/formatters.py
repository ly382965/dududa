from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .client import DateRange

COST_TIMEZONE = ZoneInfo("Asia/Shanghai")
# The upstream exposes only the current window, so retain confirmed events for this billing round.
CURRENT_BILLING_RESET_ESTIMATES = (
    datetime(2026, 8, 13, 14, 0, tzinfo=COST_TIMEZONE),
    datetime(2026, 8, 20, 14, 14, 48, tzinfo=COST_TIMEZONE),
    datetime(2026, 8, 24, 8, 42, tzinfo=COST_TIMEZONE),
    datetime(2026, 8, 28, 0, 27, tzinfo=COST_TIMEZONE),
    datetime(2026, 8, 30, 5, 27, tzinfo=COST_TIMEZONE),
    datetime(2026, 8, 31, 10, 27, tzinfo=COST_TIMEZONE),
)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _ranking_rows(ranking: dict[str, Any]) -> list[dict[str, Any]]:
    return _items(ranking.get("users") or ranking.get("ranking"))


def _row_tokens(item: dict[str, Any]) -> int:
    return _int(item.get("total_tokens", item.get("tokens")))


def _clean_text(value: Any, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    text = re.sub(r"(?i)(bearer\s+)[a-z0-9._~+/=-]+", r"\1[redacted]", text)
    text = re.sub(
        r"(?i)(access[_-]?token|refresh[_-]?token|api[_-]?key|password)"
        r"\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _future_timestamp(value: Any) -> str:
    text = _clean_text(value, 60)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        return ""
    return text if parsed.astimezone(timezone.utc) > datetime.now(timezone.utc) else ""


def _snapshot_timestamp(value: Any) -> datetime | None:
    text = _clean_text(value, 60)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=COST_TIMEZONE)
    return parsed.astimezone(COST_TIMEZONE)


def _current_cycle_reset_points(
    snapshot: dict[str, Any], estimate: dict[str, Any]
) -> list[datetime]:
    period_start = _snapshot_timestamp(snapshot.get("period_start"))
    synced_at = _snapshot_timestamp(snapshot.get("synced_at"))
    cycle_started_at = _snapshot_timestamp(estimate.get("cycle_started_at"))
    if not period_start or not synced_at:
        return []

    points = [
        point
        for point in CURRENT_BILLING_RESET_ESTIMATES
        if period_start <= point <= synced_at
    ]
    if (
        cycle_started_at
        and period_start <= cycle_started_at <= synced_at
        and not any(
            abs(cycle_started_at - point) < timedelta(minutes=5) for point in points
        )
    ):
        points.append(cycle_started_at)
    return sorted(points)


def _format_reset_point(value: datetime) -> str:
    return value.astimezone(COST_TIMEZONE).strftime("%Y-%m-%d %H:%M")


def number(value: Any) -> str:
    return f"{_int(value):,}"


def money(value: Any) -> str:
    return f"${_float(value):,.4f}"


def duration_ms(value: Any) -> str:
    milliseconds = max(0.0, _float(value))
    if milliseconds >= 1000:
        return f"{milliseconds / 1000:.2f} 秒"
    return f"{milliseconds:.0f} 毫秒"


def mask_identifier(value: Any, *, reveal: bool = False) -> str:
    text = _clean_text(value, 160)
    if not text:
        return "未知用户"
    if reveal:
        return text
    if "@" in text:
        local, domain = text.rsplit("@", 1)
        visible = local[:2] if len(local) > 1 else local[:1]
        return f"{visible}***@{domain}"
    if len(text) <= 3:
        return text[0] + "***"
    return f"{text[:2]}***{text[-1]}"


def _updated_line(stats: dict[str, Any]) -> str:
    updated = _clean_text(stats.get("stats_updated_at"), 60)
    return f"\n数据更新时间：{updated}" if updated else ""


def format_today(
    stats: dict[str, Any],
    ranking: dict[str, Any],
    *,
    reveal_users: bool,
    ranking_limit: int,
) -> str:
    rows = sorted(_ranking_rows(ranking), key=_row_tokens, reverse=True)[
        : max(1, ranking_limit)
    ]
    total_tokens = _int(stats.get("today_tokens"))
    lines = [
        "Sub2API 今日用量",
        f"Token：{number(total_tokens)}",
        f"请求：{number(stats.get('today_requests'))}",
        f"费用：{money(stats.get('today_actual_cost'))}",
        (
            "Token 构成："
            f"输入 {number(stats.get('today_input_tokens'))} / "
            f"输出 {number(stats.get('today_output_tokens'))} / "
            f"缓存写入 {number(stats.get('today_cache_creation_tokens'))} / "
            f"缓存读取 {number(stats.get('today_cache_read_tokens'))}"
        ),
        "",
        "今日 Token 用户排名",
    ]
    if not rows:
        lines.append("暂无用量。")
    for index, item in enumerate(rows, 1):
        identifier = (
            item.get("email") or item.get("username") or f"用户#{item.get('user_id')}"
        )
        tokens = _row_tokens(item)
        percent = (tokens / total_tokens * 100) if total_tokens else 0
        lines.append(
            f"{index}. {mask_identifier(identifier, reveal=reveal_users)} "
            f"- {number(tokens)} ({percent:.1f}%)，"
            f"{number(item.get('requests'))} 次，{money(item.get('actual_cost'))}"
        )
    updated = _updated_line(stats).lstrip("\n")
    if updated:
        lines.append(updated)
    return "\n".join(lines).strip()


def _format_overview_usage(
    usage_stats: dict[str, Any],
    ranking: dict[str, Any],
    *,
    title: str,
    ranking_title: str,
    reveal_users: bool,
    ranking_limit: int,
) -> str:
    rows = sorted(_ranking_rows(ranking), key=_row_tokens, reverse=True)[
        : max(1, ranking_limit)
    ]
    total_tokens = _int(usage_stats.get("total_tokens"))
    lines = [
        title,
        f"Token：{number(total_tokens)}",
        f"请求：{number(usage_stats.get('total_requests'))}",
        f"费用：{money(usage_stats.get('total_actual_cost'))}",
        (
            "Token 构成："
            f"输入 {number(usage_stats.get('total_input_tokens'))} / "
            f"输出 {number(usage_stats.get('total_output_tokens'))} / "
            f"缓存写入 {number(usage_stats.get('total_cache_creation_tokens'))} / "
            f"缓存读取 {number(usage_stats.get('total_cache_read_tokens'))}"
        ),
        f"平均响应：{duration_ms(usage_stats.get('average_duration_ms'))}",
        "",
        ranking_title,
    ]
    if not rows:
        lines.append("暂无用量。")
    for index, item in enumerate(rows, 1):
        identifier = (
            item.get("email") or item.get("username") or f"用户#{item.get('user_id')}"
        )
        tokens = _row_tokens(item)
        percent = (tokens / total_tokens * 100) if total_tokens else 0
        lines.append(
            f"{index}. {mask_identifier(identifier, reveal=reveal_users)} "
            f"- {number(tokens)} ({percent:.1f}%)，"
            f"{number(item.get('requests'))} 次，{money(item.get('actual_cost'))}"
        )
    return "\n".join(lines).strip()


def format_overview_history(
    usage_stats: dict[str, Any],
    ranking: dict[str, Any],
    period: DateRange,
    *,
    reveal_users: bool,
    ranking_limit: int,
) -> str:
    return _format_overview_usage(
        usage_stats,
        ranking,
        title=f"Sub2API 历史累计用量（{period.start} 至 {period.end}）",
        ranking_title="历史累计 Token 用户排名",
        reveal_users=reveal_users,
        ranking_limit=ranking_limit,
    )


def format_cost_overview_snapshot(
    snapshot: dict[str, Any],
    usage: dict[str, Any],
    *,
    ranking_limit: int,
) -> str:
    period_start = _clean_text(snapshot.get("period_start"), 40) or "未知"
    period_end = _clean_text(snapshot.get("period_end"), 40) or "未知"
    text = _format_overview_usage(
        usage,
        usage,
        title=f"Sub2API 当前计费轮累计（{period_start} 至 {period_end}）",
        ranking_title="当前计费轮 Token 用户排名",
        reveal_users=True,
        ranking_limit=ranking_limit,
    )

    raw_estimate = snapshot.get("pro_estimate")
    estimate = raw_estimate if isinstance(raw_estimate, dict) else {}
    reset_points = _current_cycle_reset_points(snapshot, estimate)
    if reset_points or estimate:
        next_reset = _snapshot_timestamp(estimate.get("resets_at"))
        observation = [
            "Pro 周额度观测",
            f"当前轮重置估算：{len(reset_points)} 次",
        ]
        if reset_points:
            observation.append("估算时间点（Asia/Shanghai）：")
            observation.extend(
                f"{index}. {_format_reset_point(point)}"
                for index, point in enumerate(reset_points, 1)
            )
        else:
            observation.append("重置时间点：暂不可用")
        if _float(estimate.get("used_percent")) > 0:
            observation.append(f"已用：{_float(estimate.get('used_percent')):.1f}%")
        if _float(estimate.get("cycle_actual_cost")) > 0:
            observation.append(
                f"本轮 actual_cost：{money(estimate.get('cycle_actual_cost'))}"
            )
        if _float(estimate.get("estimated_quota")) > 0:
            observation.append(
                f"本轮额度估算：{money(estimate.get('estimated_quota'))}"
            )
        if next_reset:
            observation.append(f"下次重置：{_format_reset_point(next_reset)}")
        text += "\n\n" + "\n".join(observation)
    return text.strip()


def format_total(stats: dict[str, Any]) -> str:
    return (
        "Sub2API 历史累计\n"
        f"总 Token：{number(stats.get('total_tokens'))}\n"
        f"总请求：{number(stats.get('total_requests'))}\n"
        f"总费用：{money(stats.get('total_actual_cost'))}\n"
        "Token 构成："
        f"输入 {number(stats.get('total_input_tokens'))} / "
        f"输出 {number(stats.get('total_output_tokens'))} / "
        f"缓存写入 {number(stats.get('total_cache_creation_tokens'))} / "
        f"缓存读取 {number(stats.get('total_cache_read_tokens'))}\n"
        f"用户：{number(stats.get('total_users'))}（活跃 {number(stats.get('active_users'))}）\n"
        f"API Key：{number(stats.get('total_api_keys'))}（活跃 {number(stats.get('active_api_keys'))}）\n"
        f"上游账号：{number(stats.get('total_accounts'))}（正常 {number(stats.get('normal_accounts'))}，"
        f"错误 {number(stats.get('error_accounts'))}，限流 {number(stats.get('ratelimit_accounts'))}）"
        f"\n平均响应：{duration_ms(stats.get('average_duration_ms'))}"
        f"{_updated_line(stats)}"
    )


def format_user_ranking(
    ranking: dict[str, Any],
    period: DateRange,
    *,
    usage_stats: dict[str, Any] | None,
    reveal_users: bool,
    ranking_limit: int,
) -> str:
    rows = sorted(
        _ranking_rows(ranking),
        key=_row_tokens,
        reverse=True,
    )[: max(1, ranking_limit)]
    totals = usage_stats or ranking
    lines = [
        f"Sub2API 用户 Token 排名（{period.start} 至 {period.end}）",
        (
            f"区间合计：{number(totals.get('total_tokens'))} Token / "
            f"{number(totals.get('total_requests'))} 请求 / {money(totals.get('total_actual_cost'))}"
        ),
    ]
    if not rows:
        lines.append("暂无用量。")
        return "\n".join(lines)
    for index, item in enumerate(rows, 1):
        identifier = (
            item.get("email") or item.get("username") or f"用户#{item.get('user_id')}"
        )
        lines.append(
            f"{index}. {mask_identifier(identifier, reveal=reveal_users)} "
            f"- {number(_row_tokens(item))} Token，"
            f"{number(item.get('requests'))} 次，{money(item.get('actual_cost'))}"
        )
    return "\n".join(lines)


def format_models(snapshot: dict[str, Any], period: DateRange, *, max_rows: int) -> str:
    rows = sorted(
        _items(snapshot.get("models")),
        key=lambda item: _int(item.get("total_tokens")),
        reverse=True,
    )[: max(1, max_rows)]
    lines = [f"Sub2API 模型用量（{period.start} 至 {period.end}）"]
    if not rows:
        lines.append("暂无模型用量。")
        return "\n".join(lines)
    for index, item in enumerate(rows, 1):
        lines.append(
            f"{index}. {_clean_text(item.get('model') or '未知模型', 80)} "
            f"- {number(item.get('total_tokens'))} Token，"
            f"{number(item.get('requests'))} 次，{money(item.get('actual_cost'))}"
        )
    return "\n".join(lines)


def format_range(
    snapshot: dict[str, Any],
    ranking: dict[str, Any],
    usage_stats: dict[str, Any],
    period: DateRange,
    *,
    reveal_users: bool,
    ranking_limit: int,
    max_trend_rows: int,
    max_model_rows: int,
) -> str:
    trend = sorted(
        _items(snapshot.get("trend")), key=lambda item: str(item.get("date") or "")
    )
    total_tokens = _int(usage_stats.get("total_tokens"))
    total_requests = _int(usage_stats.get("total_requests"))
    total_cost = _float(usage_stats.get("total_actual_cost"))

    lines = [
        f"Sub2API 区间用量（{period.start} 至 {period.end}，共 {period.days} 天）",
        f"Token：{number(total_tokens)}",
        f"请求：{number(total_requests)}",
        f"费用：{money(total_cost)}",
        (
            "Token 构成："
            f"输入 {number(usage_stats.get('total_input_tokens'))} / "
            f"输出 {number(usage_stats.get('total_output_tokens'))} / "
            f"缓存写入 {number(usage_stats.get('total_cache_creation_tokens'))} / "
            f"缓存读取 {number(usage_stats.get('total_cache_read_tokens'))}"
        ),
        f"平均响应：{duration_ms(usage_stats.get('average_duration_ms'))}",
        "",
        format_user_ranking(
            ranking,
            period,
            usage_stats=usage_stats,
            reveal_users=reveal_users,
            ranking_limit=ranking_limit,
        ),
        "",
        format_models(snapshot, period, max_rows=max_model_rows),
    ]

    endpoints = sorted(
        _items(usage_stats.get("endpoints")),
        key=lambda item: _int(item.get("total_tokens")),
        reverse=True,
    )[:5]
    if endpoints:
        lines.extend(["", "API 端点分布"])
        for item in endpoints:
            lines.append(
                f"- {_clean_text(item.get('endpoint') or '未知', 80)}："
                f"{number(item.get('total_tokens'))} Token，"
                f"{number(item.get('requests'))} 次"
            )

    if trend:
        limit = max(1, max_trend_rows)
        visible = trend[-limit:]
        lines.extend(["", f"每日趋势（最近 {len(visible)} 天）"])
        for item in visible:
            lines.append(
                f"{_clean_text(item.get('date'), 20)}："
                f"{number(item.get('total_tokens'))} Token，"
                f"{number(item.get('requests'))} 次，{money(item.get('actual_cost'))}"
            )
        if len(trend) > len(visible):
            lines.append(f"另有 {len(trend) - len(visible)} 天已计入合计，未逐日展开。")
    return "\n".join(lines).strip()


def _account_state(account: dict[str, Any]) -> str:
    status = _clean_text(account.get("status") or "unknown", 30)
    schedulable = bool(account.get("schedulable"))
    if _future_timestamp(account.get("temp_unschedulable_until")):
        return "暂时不可调度"
    if _future_timestamp(account.get("overload_until")):
        return "上游过载"
    if _future_timestamp(account.get("rate_limit_reset_at")):
        return "上游限流"
    if status == "active" and schedulable:
        return "正常可调度"
    if status == "active":
        return "启用但不可调度"
    return status


def _quota_summary(account: dict[str, Any]) -> str:
    extra = account.get("extra")
    if not isinstance(extra, dict):
        return ""
    percent = extra.get("codex_primary_used_percent")
    if percent is None:
        percent = extra.get("codex_7d_used_percent")
    if percent is None:
        return ""
    reset = _clean_text(
        extra.get("codex_primary_reset_at") or extra.get("codex_7d_reset_at") or "",
        60,
    )
    suffix = f"，重置 {reset}" if reset else ""
    return f"，周期额度已用 {_float(percent):g}%{suffix}"


def format_accounts(
    accounts: Iterable[dict[str, Any]],
    *,
    show_account_names: bool,
    reveal_identifiers: bool,
    max_rows: int,
) -> str:
    rows = list(accounts)
    states = Counter(_account_state(item) for item in rows)
    lines = [
        "Sub2API 上游账号状态",
        f"总数：{len(rows)}；"
        + "；".join(f"{state} {count}" for state, count in sorted(states.items())),
    ]
    if not rows:
        lines.append("暂无账号。")
        return "\n".join(lines)
    ordered = sorted(
        rows,
        key=lambda item: (_account_state(item) != "正常可调度", _int(item.get("id"))),
    )
    visible = ordered[: max(1, max_rows)]
    for item in visible:
        account_id = _int(item.get("id"))
        name = _clean_text(item.get("name"), 60) if show_account_names else ""
        label = f"#{account_id}" + (f" {name[:60]}" if name else "")
        platform = _clean_text(item.get("platform") or "unknown", 30)
        account_type = _clean_text(item.get("type") or "unknown", 30)
        registration_email = item.get("registration_email")
        email = (
            mask_identifier(registration_email, reveal=reveal_identifiers)
            if registration_email
            else "未提供"
        )
        current = number(item.get("current_concurrency"))
        capacity = number(item.get("concurrency"))
        line = (
            f"- {label} [{platform}/{account_type}]："
            f"{_account_state(item)}，"
            f"并发 {current}/{capacity}{_quota_summary(item)}；注册邮箱 {email}"
        )
        reset = _future_timestamp(item.get("rate_limit_reset_at"))
        if reset:
            line += f"；限流重置：{reset}"
        temp_until = _future_timestamp(item.get("temp_unschedulable_until"))
        if temp_until:
            line += f"；暂停至：{temp_until}"
        overload_until = _future_timestamp(item.get("overload_until"))
        if overload_until:
            line += f"；过载至：{overload_until}"
        expires_at = _clean_text(item.get("expires_at"), 60)
        if expires_at:
            line += f"；凭据到期：{expires_at}"
        lines.append(line)
    if len(rows) > len(visible):
        lines.append(f"另有 {len(rows) - len(visible)} 个账号未展开。")
    return "\n".join(lines)


def format_account(
    account: dict[str, Any],
    today_stats: dict[str, Any],
    *,
    show_account_names: bool,
    reveal_identifiers: bool,
) -> str:
    account_id = _int(account.get("id"))
    name = _clean_text(account.get("name"), 60) if show_account_names else ""
    title = f"Sub2API 账号 #{account_id}" + (f" {name[:60]}" if name else "")
    groups = account.get("groups")
    group_names = []
    if isinstance(groups, list):
        group_names = [
            _clean_text(group.get("name"), 60)
            for group in groups
            if isinstance(group, dict) and group.get("name")
        ]
    lines = [
        title,
        (
            f"平台/类型：{_clean_text(account.get('platform') or 'unknown', 30)} / "
            f"{_clean_text(account.get('type') or 'unknown', 30)}"
        ),
        "注册邮箱："
        + (
            mask_identifier(
                account.get("registration_email"), reveal=reveal_identifiers
            )
            if account.get("registration_email")
            else "未提供"
        ),
        f"状态：{_account_state(account)}",
        f"并发：{number(account.get('current_concurrency'))}/{number(account.get('concurrency'))}",
        f"优先级：{number(account.get('priority'))}；倍率：{_float(account.get('rate_multiplier')):g}",
        (
            f"今日：{number(today_stats.get('tokens'))} Token / "
            f"{number(today_stats.get('requests'))} 请求 / {money(today_stats.get('cost'))}"
        ),
    ]
    if group_names:
        lines.append("账号组：" + "、".join(group_names[:10]))
    quota = _quota_summary(account).lstrip("，")
    if quota:
        lines.append("额度：" + quota)
    last_used = _clean_text(account.get("last_used_at"), 60)
    if last_used:
        lines.append("最近使用：" + last_used)
    expires_at = _clean_text(account.get("expires_at"), 60)
    if expires_at:
        lines.append("凭据到期：" + expires_at)
    for label, key in (
        ("限流重置", "rate_limit_reset_at"),
        ("暂停至", "temp_unschedulable_until"),
        ("过载至", "overload_until"),
    ):
        recovery = _future_timestamp(account.get(key))
        if recovery:
            lines.append(f"{label}：{recovery}")
    return "\n".join(lines)


def format_status(version: dict[str, Any], stats: dict[str, Any]) -> str:
    stale = "是" if stats.get("stats_stale") else "否"
    return (
        "Sub2API 只读连接正常\n"
        f"服务版本：{_clean_text(version.get('version') or '未知', 30)}\n"
        f"统计更新时间：{_clean_text(stats.get('stats_updated_at') or '未知', 60)}\n"
        f"统计是否过期：{stale}\n"
        f"活跃用户：{number(stats.get('active_users'))}\n"
        f"正常账号：{number(stats.get('normal_accounts'))}/{number(stats.get('total_accounts'))}\n"
        f"RPM/TPM：{number(stats.get('rpm'))}/{number(stats.get('tpm'))}\n"
        f"平均响应：{duration_ms(stats.get('average_duration_ms'))}\n"
        "安全模式：业务请求仅允许 GET"
    )
