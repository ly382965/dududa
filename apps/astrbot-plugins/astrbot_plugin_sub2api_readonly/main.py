from __future__ import annotations

import asyncio
import base64
import os
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Node, Nodes, Plain
from astrbot.api.star import Context, Star, register

from .charts import render_total_trend_chart, render_user_trend_chart
from .client import (
    DateRange,
    Sub2APIAuthError,
    Sub2APIClient,
    Sub2APIConfigError,
    Sub2APIError,
    Sub2APIRequestError,
    access_error,
    fallback_cost_overview,
    fetch_cost_overview,
    is_sub2api_event_command,
    overview_history_period,
    parse_date_range,
    parse_trend_period,
    parse_user_trend_request,
    should_block_exclusive_group,
    today_in_timezone,
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
    format_user_ranking,
)
from .policy import resolve_plugin_policy

PLUGIN_POLICY_ID = "sub2api.auto_query"

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


@register(
    "astrbot_plugin_sub2api_readonly",
    "mmdustc",
    "通过管理网页同款只读接口查询 Sub2API 用量和账号状态",
    "0.6.4",
)
class Sub2APIReadonlyPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.enabled = self._bool(self.config.get("enabled", False), False)
        self.group_whitelist = self._str_set(self.config.get("group_whitelist", []))
        self.exclusive_groups = self._str_set(self.config.get("exclusive_groups", []))
        self.private_user_whitelist = self._str_set(
            self.config.get("private_user_whitelist", [])
        )
        self.timezone = str(self.config.get("timezone", "Asia/Shanghai") or "").strip()
        self.ranking_limit = self._clamp_int(
            self.config.get("ranking_limit", 10), 10, 1, 100
        )
        self.account_limit = self._clamp_int(
            self.config.get("account_limit", 30), 30, 1, 100
        )
        self.model_limit = self._clamp_int(
            self.config.get("model_limit", 10), 10, 1, 50
        )
        self.max_trend_rows = self._clamp_int(
            self.config.get("max_trend_rows", 14), 14, 1, 90
        )
        self.max_range_days = self._clamp_int(
            self.config.get("max_range_days", 90), 90, 1, 3660
        )
        self.reveal_user_identifiers = self._bool(
            self.config.get("reveal_user_identifiers", False), False
        )
        self.show_account_names = self._bool(
            self.config.get("show_account_names", False), False
        )
        self.client: Sub2APIClient | None = None
        self.client_config_error = ""
        try:
            self.client = Sub2APIClient(
                base_url=self._setting("SUB2API_BASE_URL", "base_url", ""),
                email=self._setting("SUB2API_ADMIN_EMAIL", "admin_email", ""),
                password=self._setting("SUB2API_ADMIN_PASSWORD", "admin_password", ""),
                timezone=self.timezone,
                timeout_seconds=self._clamp_float(
                    self.config.get("request_timeout_seconds", 30), 30, 3, 60
                ),
                cache_ttl_seconds=self._clamp_float(
                    self.config.get("cache_ttl_seconds", 30), 30, 0, 600
                ),
            )
        except Sub2APIConfigError as exc:
            self.client_config_error = str(exc)
        logger.info(
            "Sub2APIReadonly loaded: enabled=%s groups=%d exclusive_groups=%d "
            "private_users=%d configured=%s policy_managed=%s",
            self.enabled,
            len(self.group_whitelist),
            len(self.exclusive_groups),
            len(self.private_user_whitelist),
            self.client is not None,
            bool(self._policy_path()),
        )

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1000)
    async def enforce_command_access(self, event: AstrMessageEvent):
        """Apply exclusive-group and Sub2API access rules before other plugins."""
        text = (event.message_str or event.get_message_outline() or "").strip()
        original_text = str(
            getattr(getattr(event, "message_obj", None), "message_str", "") or ""
        ).strip()
        outline = (event.get_message_outline() or "").strip()
        is_command = is_sub2api_event_command(
            awakened=event.is_at_or_wake_command,
            current_message=text,
            original_message=original_text,
            message_outline=outline,
        )
        group_id = event.get_group_id()
        policy_enabled = self._policy_enabled(event)
        if policy_enabled and should_block_exclusive_group(
            group_id=group_id,
            message=text,
            exclusive_groups=self.exclusive_groups,
            command_allowed=is_command,
        ):
            event.stop_event()
            return
        if not is_command:
            return
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()

    @filter.command_group("sub2api", alias={"sub2", "用量"})
    def sub2api(self):
        """Sub2API 只读统计命令组"""

    @sub2api.command("help", alias={"帮助"})
    async def sub2api_help(self, event: AstrMessageEvent):
        """查看 Sub2API 查询帮助"""
        if error := self._access_error(event):
            yield event.plain_result(error)
        else:
            yield event.plain_result(HELP_TEXT)
        event.stop_event()

    @sub2api.command("overview", alias={"概览", "汇总"})
    async def overview(self, event: AstrMessageEvent):
        """以合并转发查看今日、当前轮、历史排名和上游账号状态"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            client = self._require_client()
            today_period = self._today_period()
            history_period = overview_history_period(self.timezone)
            (
                stats,
                today_ranking,
                cost_overview,
                history_stats,
                history_ranking,
                accounts,
            ) = await asyncio.gather(
                client.get_stats(),
                client.get_user_ranking(today_period, limit=self.ranking_limit),
                self._fetch_cost_overview_optional(),
                client.get_usage_stats(history_period),
                client.get_user_ranking(history_period, limit=self.ranking_limit),
                client.get_accounts(),
            )
            if cost_overview is None:
                logger.warning(
                    "Sub2API cost overview unavailable; using account metadata fallback"
                )
                cost_overview = fallback_cost_overview(
                    accounts,
                    timezone=self.timezone,
                )
                estimate = cost_overview.get("pro_estimate")
                if isinstance(estimate, dict):
                    try:
                        cost_overview["pro_estimate"] = (
                            await client.get_pro_quota_estimate(
                                estimate,
                                synced_at=str(cost_overview.get("synced_at") or "")
                                or None,
                            )
                        )
                    except Sub2APIError as exc:
                        logger.warning(
                            "Sub2API Pro quota fallback unavailable: %s",
                            type(exc).__name__,
                        )
            cycle_usage = await client.get_usage_ranking_since(
                str(cost_overview.get("period_start") or ""),
                str(cost_overview.get("period_end") or ""),
                synced_at=str(cost_overview.get("synced_at") or "") or None,
                limit=self.ranking_limit,
            )
            sections = (
                format_today(
                    stats,
                    today_ranking,
                    reveal_users=self.reveal_user_identifiers,
                    ranking_limit=self.ranking_limit,
                ),
                format_cost_overview_snapshot(
                    cost_overview,
                    cycle_usage,
                    ranking_limit=self.ranking_limit,
                ),
                format_overview_history(
                    history_stats,
                    history_ranking,
                    history_period,
                    reveal_users=self.reveal_user_identifiers,
                    ranking_limit=self.ranking_limit,
                ),
                format_accounts(
                    accounts,
                    show_account_names=self.show_account_names,
                    reveal_identifiers=self.reveal_user_identifiers,
                    max_rows=self.account_limit,
                ),
            )
            nodes = [
                Node(
                    name="Sub2API",
                    uin=str(event.get_self_id() or "0"),
                    content=[Plain(section)],
                )
                for section in sections
            ]
            result = event.chain_result([Nodes(nodes)])
            result.use_t2i(False)
            result.use_markdown(False)
            logger.info(
                "Sub2API overview prepared merged forward: nodes=%d",
                len(nodes),
            )
        except Sub2APIError as exc:
            yield event.plain_result(self._error_reply(exc))
        else:
            yield result
        event.stop_event()

    @sub2api.command("today", alias={"今日", "今天"})
    async def today(self, event: AstrMessageEvent):
        """查看今日 Token 与用户排名"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            client = self._require_client()
            period = self._today_period()
            stats, ranking = await asyncio.gather(
                client.get_stats(),
                client.get_user_ranking(period, limit=self.ranking_limit),
            )
            reply = format_today(
                stats,
                ranking,
                reveal_users=self.reveal_user_identifiers,
                ranking_limit=self.ranking_limit,
            )
        except Sub2APIError as exc:
            reply = self._error_reply(exc)
        yield event.plain_result(reply)
        event.stop_event()

    @sub2api.command("total", alias={"历史", "累计"})
    async def total(self, event: AstrMessageEvent):
        """查看历史累计用量"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            reply = format_total(await self._require_client().get_stats())
        except Sub2APIError as exc:
            reply = self._error_reply(exc)
        yield event.plain_result(reply)
        event.stop_event()

    @sub2api.command("range", alias={"范围", "区间"})
    async def usage_range(
        self, event: AstrMessageEvent, start_date: str, end_date: str
    ):
        """查看指定日期范围的 Token、用户和模型用量"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            period = self._period(start_date, end_date)
            client = self._require_client()
            snapshot, ranking, usage_stats = await asyncio.gather(
                client.get_snapshot(period),
                client.get_user_ranking(period, limit=self.ranking_limit),
                client.get_usage_stats(period),
            )
            reply = format_range(
                snapshot,
                ranking,
                usage_stats,
                period,
                reveal_users=self.reveal_user_identifiers,
                ranking_limit=self.ranking_limit,
                max_trend_rows=self.max_trend_rows,
                max_model_rows=self.model_limit,
            )
        except Sub2APIError as exc:
            reply = self._error_reply(exc)
        yield event.plain_result(reply)
        event.stop_event()

    @sub2api.command("trendtotal", alias={"trend", "总趋势"})
    async def trend_total(self, event: AstrMessageEvent, days: str | None = None):
        """生成指定天数内的总 Token 用量趋势图"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            period = parse_trend_period(
                days or "7d", timezone=self.timezone, max_days=self.max_range_days
            )
            snapshot = await self._require_client().get_snapshot(period)
            png = await asyncio.to_thread(render_total_trend_chart, snapshot, period)
            encoded = base64.b64encode(png).decode("ascii")
            yield event.chain_result([Image.fromBase64(encoded)])
        except Sub2APIError as exc:
            yield event.plain_result(self._error_reply(exc))
        except Exception:  # noqa: BLE001 - keep chart failures inside this command
            logger.exception("Sub2API total trend chart rendering failed")
            yield event.plain_result("Sub2API 趋势图生成失败，请稍后重试。")
        event.stop_event()

    @sub2api.command("trenduser", alias={"用户趋势"})
    async def trend_user(
        self,
        event: AstrMessageEvent,
        mode_or_days: str | None = None,
        days: str | None = None,
    ):
        """生成指定天数内前 10 名用户的 Token 趋势图"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            period, cumulative = parse_user_trend_request(
                mode_or_days,
                days,
                timezone=self.timezone,
                max_days=self.max_range_days,
            )
            snapshot = await self._require_client().get_user_trend(period, limit=10)
            png = await asyncio.to_thread(
                render_user_trend_chart,
                snapshot,
                period,
                reveal_identifiers=self.reveal_user_identifiers,
                limit=10,
                cumulative=cumulative,
            )
            encoded = base64.b64encode(png).decode("ascii")
            yield event.chain_result([Image.fromBase64(encoded)])
        except Sub2APIError as exc:
            yield event.plain_result(self._error_reply(exc))
        except Exception:  # noqa: BLE001 - keep chart failures inside this command
            logger.exception("Sub2API user trend chart rendering failed")
            yield event.plain_result("Sub2API 趋势图生成失败，请稍后重试。")
        event.stop_event()

    @sub2api.command("users", alias={"用户", "排名", "排行"})
    async def users(
        self,
        event: AstrMessageEvent,
        start_date: str | None = None,
        end_date: str | None = None,
    ):
        """查看用户 Token 排名，默认今日"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            period = self._optional_period(start_date, end_date)
            client = self._require_client()
            ranking, usage_stats = await asyncio.gather(
                client.get_user_ranking(period, limit=self.ranking_limit),
                client.get_usage_stats(period),
            )
            reply = format_user_ranking(
                ranking,
                period,
                usage_stats=usage_stats,
                reveal_users=self.reveal_user_identifiers,
                ranking_limit=self.ranking_limit,
            )
        except Sub2APIError as exc:
            reply = self._error_reply(exc)
        yield event.plain_result(reply)
        event.stop_event()

    @sub2api.command("models", alias={"模型"})
    async def models(
        self,
        event: AstrMessageEvent,
        start_date: str | None = None,
        end_date: str | None = None,
    ):
        """查看模型用量，默认今日"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            period = self._optional_period(start_date, end_date)
            snapshot = await self._require_client().get_snapshot(period)
            reply = format_models(snapshot, period, max_rows=self.model_limit)
        except Sub2APIError as exc:
            reply = self._error_reply(exc)
        yield event.plain_result(reply)
        event.stop_event()

    @sub2api.command("accounts", alias={"账号", "账户"})
    async def accounts(self, event: AstrMessageEvent):
        """查看上游账号状态"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            rows = await self._require_client().get_accounts()
            reply = format_accounts(
                rows,
                show_account_names=self.show_account_names,
                reveal_identifiers=self.reveal_user_identifiers,
                max_rows=self.account_limit,
            )
        except Sub2APIError as exc:
            reply = self._error_reply(exc)
        yield event.plain_result(reply)
        event.stop_event()

    @sub2api.command("account", alias={"单账号", "单账户"})
    async def account(self, event: AstrMessageEvent, account_id: int):
        """查看单个上游账号状态与今日用量"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            client = self._require_client()
            accounts, today_stats = await asyncio.gather(
                client.get_accounts(),
                client.get_account_today_stats(account_id),
            )
            row = next(
                (item for item in accounts if int(item.get("id") or 0) == account_id),
                None,
            )
            if row is None:
                raise Sub2APIRequestError(f"未找到账号 #{account_id}。")
            reply = format_account(
                row,
                today_stats,
                show_account_names=self.show_account_names,
                reveal_identifiers=self.reveal_user_identifiers,
            )
        except (TypeError, ValueError):
            reply = "账号 ID 必须是正整数。"
        except Sub2APIError as exc:
            reply = self._error_reply(exc)
        yield event.plain_result(reply)
        event.stop_event()

    @sub2api.command("status", alias={"状态", "连接"})
    async def status(self, event: AstrMessageEvent):
        """检查 Sub2API 连接和统计状态"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            event.stop_event()
            return
        try:
            client = self._require_client()
            version, stats = await asyncio.gather(
                client.get_system_version(), client.get_stats()
            )
            reply = format_status(version, stats)
        except Sub2APIError as exc:
            reply = self._error_reply(exc)
        yield event.plain_result(reply)
        event.stop_event()

    async def terminate(self) -> None:
        if self.client is not None:
            await self.client.close()

    def _access_error(self, event: AstrMessageEvent) -> str | None:
        return access_error(
            enabled=self._policy_enabled(event),
            group_id=event.get_group_id(),
            sender_id=event.get_sender_id(),
            group_whitelist=self.group_whitelist,
            private_user_whitelist=self.private_user_whitelist,
        )

    def _policy_enabled(self, event: AstrMessageEvent) -> bool:
        self_id = str(event.get_self_id() or "").strip()
        group_id = str(event.get_group_id() or "").strip()
        account_id = f"qq-{self_id}" if self_id else ""
        conversation_id = f"{account_id}:group:{group_id}" if group_id else ""
        return resolve_plugin_policy(
            policy_path=self._policy_path(),
            account_id=account_id,
            conversation_id=conversation_id,
            plugin_id=PLUGIN_POLICY_ID,
            fallback_enabled=self.enabled,
        ).enabled

    @staticmethod
    def _policy_path() -> str:
        return str(os.environ.get("DUDUDA_AGENT_POLICY_PATH") or "").strip()

    def _require_client(self) -> Sub2APIClient:
        if self.client is None:
            raise Sub2APIConfigError(
                self.client_config_error or "Sub2API 客户端尚未配置。"
            )
        return self.client

    def _today_period(self) -> DateRange:
        today = today_in_timezone(self.timezone)
        return DateRange(start=today, end=today)

    @staticmethod
    async def _fetch_cost_overview_optional() -> dict[str, Any] | None:
        try:
            return await fetch_cost_overview()
        except Sub2APIRequestError:
            return None

    def _period(self, start_date: str, end_date: str) -> DateRange:
        return parse_date_range(
            start_date,
            end_date,
            timezone=self.timezone,
            max_days=self.max_range_days,
        )

    def _optional_period(
        self, start_date: str | None, end_date: str | None
    ) -> DateRange:
        start = (start_date or "").strip()
        end = (end_date or "").strip()
        if not start and not end:
            return self._today_period()
        if not start or not end:
            raise Sub2APIConfigError("请同时提供开始日期和结束日期。")
        return self._period(start, end)

    @staticmethod
    def _error_reply(exc: Sub2APIError) -> str:
        if isinstance(exc, Sub2APIConfigError):
            return f"Sub2API 配置或参数错误：{exc}"
        if isinstance(exc, Sub2APIAuthError):
            logger.warning("Sub2API authentication failed: %s", type(exc).__name__)
            return f"Sub2API 认证失败：{exc}"
        logger.warning("Sub2API read-only query failed: %s", type(exc).__name__)
        return f"Sub2API 查询失败：{exc}"

    def _setting(self, env_name: str, config_name: str, default: str) -> str:
        env_value = os.environ.get(env_name)
        if env_value is not None and env_value.strip():
            return env_value.strip()
        return str(self.config.get(config_name, default) or "").strip()

    @staticmethod
    def _str_set(value: Any) -> set[str]:
        if isinstance(value, str):
            return {item.strip() for item in value.split(",") if item.strip()}
        if isinstance(value, (list, tuple, set)):
            return {str(item).strip() for item in value if str(item).strip()}
        return set()

    @staticmethod
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

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    @staticmethod
    def _clamp_float(
        value: Any, default: float, minimum: float, maximum: float
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))
