from __future__ import annotations

import asyncio
import copy
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

LOGIN_PATH = "/auth/login"
READ_ONLY_PATHS = frozenset(
    {
        "/admin/dashboard/stats",
        "/admin/dashboard/snapshot-v2",
        "/admin/dashboard/user-breakdown",
        "/admin/usage/stats",
        "/admin/accounts",
        "/admin/system/version",
    }
)
ACCOUNT_TODAY_STATS_PATH = re.compile(r"^/admin/accounts/[1-9][0-9]*/today-stats$")
OVERVIEW_HISTORY_START = date(2026, 7, 13)
SUB2API_COMMAND_RE = re.compile(
    r"^(?:(?:\[(?:At|at):[^\]]+\]|\[CQ:at,[^\]]+\]|@\S+)\s*)*"
    r"/(?:sub2api|sub2|用量)(?:\s|$)",
    re.IGNORECASE,
)
TREND_DAYS_RE = re.compile(r"^([1-9][0-9]*)d$", re.IGNORECASE)


class Sub2APIError(RuntimeError):
    """Base error safe to translate into a user-facing message."""


class Sub2APIConfigError(Sub2APIError):
    pass


class Sub2APIAuthError(Sub2APIError):
    pass


class Sub2APIRequestError(Sub2APIError):
    pass


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_params(self) -> dict[str, str]:
        return {
            "start_date": self.start.isoformat(),
            "end_date": self.end.isoformat(),
        }


@dataclass
class _CacheEntry:
    expires_at: float
    value: Any


def normalize_base_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise Sub2APIConfigError("尚未配置 Sub2API 地址。")
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname:
        raise Sub2APIConfigError("Sub2API 地址必须是有效的 HTTPS URL。")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise Sub2APIConfigError("Sub2API 地址不能包含凭据、查询参数或片段。")

    path = parts.path.rstrip("/")
    for suffix in ("/admin/dashboard", "/api/v1"):
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def parse_date_range(
    start_value: str,
    end_value: str,
    *,
    timezone: str,
    max_days: int,
) -> DateRange:
    try:
        start = date.fromisoformat((start_value or "").strip())
        end = date.fromisoformat((end_value or "").strip())
    except ValueError as exc:
        raise Sub2APIConfigError("日期格式应为 YYYY-MM-DD。") from exc

    if start > end:
        raise Sub2APIConfigError("开始日期不能晚于结束日期。")
    period = DateRange(start=start, end=end)
    if period.days > max(1, max_days):
        raise Sub2APIConfigError(f"单次查询最多允许 {max(1, max_days)} 天。")
    try:
        today = datetime.now(ZoneInfo(timezone)).date()
    except ZoneInfoNotFoundError as exc:
        raise Sub2APIConfigError(f"未知时区：{timezone}") from exc
    if end > today:
        raise Sub2APIConfigError("结束日期不能晚于今天。")
    return period


def today_in_timezone(timezone: str) -> date:
    try:
        return datetime.now(ZoneInfo(timezone)).date()
    except ZoneInfoNotFoundError as exc:
        raise Sub2APIConfigError(f"未知时区：{timezone}") from exc


def parse_trend_period(
    value: str, *, timezone: str, max_days: int
) -> DateRange:
    match = TREND_DAYS_RE.fullmatch((value or "").strip())
    if not match:
        raise Sub2APIConfigError("趋势天数格式应为正整数加 d，例如 7d。")
    days = int(match.group(1))
    limit = max(1, max_days)
    if days > limit:
        raise Sub2APIConfigError(f"趋势图最多允许查询 {limit} 天。")
    end = today_in_timezone(timezone)
    return DateRange(start=end - timedelta(days=days - 1), end=end)


def parse_user_trend_request(
    mode_or_days: str | None,
    days: str | None,
    *,
    timezone: str,
    max_days: int,
) -> tuple[DateRange, bool]:
    first = (mode_or_days or "").strip()
    second = (days or "").strip()
    if first.lower() == "sum":
        return (
            parse_trend_period(
                second or "7d", timezone=timezone, max_days=max_days
            ),
            True,
        )
    if second:
        raise Sub2APIConfigError(
            "trenduser 参数格式应为 [天数d] 或 sum [天数d]。"
        )
    return (
        parse_trend_period(first or "7d", timezone=timezone, max_days=max_days),
        False,
    )


def overview_history_period(timezone: str) -> DateRange:
    end = today_in_timezone(timezone)
    if end < OVERVIEW_HISTORY_START:
        raise Sub2APIConfigError("概览累计开始日期不能晚于今天。")
    return DateRange(start=OVERVIEW_HISTORY_START, end=end)


def access_error(
    *,
    enabled: bool,
    group_id: Any,
    sender_id: Any,
    group_whitelist: Iterable[str],
    private_user_whitelist: Iterable[str],
) -> str | None:
    if not enabled:
        return "Sub2API 查询插件当前已关闭。"
    group = str(group_id or "").strip()
    allowed_groups = {
        str(item).strip() for item in group_whitelist if str(item).strip()
    }
    if group:
        if not allowed_groups:
            return "Sub2API 群聊白名单尚未配置，已拒绝查询。"
        if group not in allowed_groups:
            return f"当前群（{group}）不在 Sub2API 查询白名单中。"
        return None
    sender = str(sender_id or "").strip()
    allowed_users = {
        str(item).strip() for item in private_user_whitelist if str(item).strip()
    }
    if sender and sender in allowed_users:
        return None
    return "Sub2API 私聊查询未授权。"


def is_sub2api_command(value: Any) -> bool:
    return bool(SUB2API_COMMAND_RE.match(str(value or "").strip()))


def is_sub2api_event_command(
    *,
    awakened: Any,
    current_message: Any,
    original_message: Any,
    message_outline: Any,
) -> bool:
    if not bool(awakened):
        return False
    return any(
        is_sub2api_command(candidate)
        for candidate in (original_message, message_outline, current_message)
    )


def should_block_exclusive_group(
    *,
    group_id: Any,
    message: Any,
    exclusive_groups: Iterable[str],
    command_allowed: bool | None = None,
) -> bool:
    group = str(group_id or "").strip()
    restricted = {str(item).strip() for item in exclusive_groups if str(item).strip()}
    allowed = (
        is_sub2api_command(message) if command_allowed is None else command_allowed
    )
    return bool(group and group in restricted and not allowed)


class Sub2APIClient:
    """Client for the same read-only endpoints used by the Sub2API admin UI."""

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        password: str,
        timezone: str = "Asia/Shanghai",
        timeout_seconds: float = 15,
        cache_ttl_seconds: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.api_root = f"{self.base_url}/api/v1"
        self.email = (email or "").strip()
        self.password = password or ""
        if not self.email or not self.password:
            raise Sub2APIConfigError("尚未配置 Sub2API 管理员邮箱或密码。")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise Sub2APIConfigError(f"未知时区：{timezone}") from exc
        self.timezone = timezone
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(max(3.0, min(float(timeout_seconds), 60.0))),
            follow_redirects=False,
            transport=transport,
            headers={
                "Accept": "application/json",
                "Accept-Language": "zh-CN",
                "User-Agent": "Dududa-Sub2API-Readonly/0.1",
            },
        )
        self._token = ""
        self._token_expires_at = 0.0
        self._login_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], _CacheEntry] = {}

    async def close(self) -> None:
        self._token = ""
        self._cache.clear()
        await self._client.aclose()

    async def get_stats(self) -> dict[str, Any]:
        return self._expect_dict(await self._get("/admin/dashboard/stats"))

    async def get_snapshot(self, period: DateRange) -> dict[str, Any]:
        params = {
            **period.as_params(),
            "granularity": "day",
            "include_stats": "false",
            "include_trend": "true",
            "include_model_stats": "true",
            "include_group_stats": "false",
            "include_users_trend": "false",
        }
        return self._expect_dict(
            await self._get("/admin/dashboard/snapshot-v2", params=params)
        )

    async def get_user_trend(
        self, period: DateRange, *, limit: int = 10
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {
            **period.as_params(),
            "granularity": "day",
            "include_stats": "false",
            "include_trend": "false",
            "include_model_stats": "false",
            "include_group_stats": "false",
            "include_users_trend": "true",
            "users_trend_limit": max(1, min(int(limit), 50)),
        }
        return self._expect_dict(
            await self._get("/admin/dashboard/snapshot-v2", params=params)
        )

    async def get_user_ranking(
        self, period: DateRange, *, limit: int = 10
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {
            **period.as_params(),
            "sort_by": "total_tokens",
            "limit": max(1, min(int(limit), 100)),
        }
        return self._expect_dict(
            await self._get("/admin/dashboard/user-breakdown", params=params)
        )

    async def get_usage_stats(self, period: DateRange) -> dict[str, Any]:
        return self._expect_dict(
            await self._get("/admin/usage/stats", params=period.as_params())
        )

    async def get_accounts(self, *, page_size: int = 100) -> list[dict[str, Any]]:
        size = max(1, min(int(page_size), 100))
        safe_cache_key = ("safe:/admin/accounts", (("page_size", str(size)),))
        cached = await self._get_cached(safe_cache_key)
        if isinstance(cached, list):
            return [item for item in cached if isinstance(item, dict)]
        page = 1
        result: list[dict[str, Any]] = []
        while page <= 100:
            payload = self._expect_dict(
                await self._get(
                    "/admin/accounts",
                    params={
                        "page": page,
                        "page_size": size,
                        "lite": 1,
                        "sort_by": "name",
                        "sort_order": "asc",
                    },
                    use_cache=False,
                )
            )
            items = payload.get("items") or []
            if not isinstance(items, list):
                raise Sub2APIRequestError("账号列表响应格式不兼容。")
            result.extend(
                self._sanitize_account(item) for item in items if isinstance(item, dict)
            )
            pages = self._as_positive_int(payload.get("pages"), default=1)
            if page >= pages:
                break
            page += 1
        await self._put_cached(safe_cache_key, result)
        return result

    async def get_account_today_stats(self, account_id: int) -> dict[str, Any]:
        safe_id = int(account_id)
        if safe_id <= 0:
            raise Sub2APIConfigError("账号 ID 必须是正整数。")
        return self._expect_dict(
            await self._get(f"/admin/accounts/{safe_id}/today-stats")
        )

    async def get_system_version(self) -> dict[str, Any]:
        return self._expect_dict(await self._get("/admin/system/version"))

    async def _get(
        self,
        path: str,
        *,
        params: Mapping[str, str | int | float | bool] | None = None,
        use_cache: bool = True,
    ) -> Any:
        self._assert_read_only_path(path)
        normalized_params = {
            str(key): str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in (params or {}).items()
            if value is not None
        }
        normalized_params.setdefault("timezone", self.timezone)
        cache_key = (path, tuple(sorted(normalized_params.items())))
        if use_cache:
            cached = await self._get_cached(cache_key)
            if cached is not None:
                return cached

        token = await self._ensure_token()
        response = await self._send_get(path, normalized_params, token)
        if response.status_code == 401:
            self._token = ""
            self._token_expires_at = 0.0
            token = await self._ensure_token()
            response = await self._send_get(path, normalized_params, token)
        data = self._decode_response(response, auth=False)
        if use_cache:
            await self._put_cached(cache_key, data)
        return copy.deepcopy(data)

    async def _ensure_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        async with self._login_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token
            try:
                response = await self._client.post(
                    f"{self.api_root}{LOGIN_PATH}",
                    json={"email": self.email, "password": self.password},
                    headers={"Content-Type": "application/json"},
                )
            except httpx.RequestError as exc:
                raise Sub2APIAuthError("无法连接 Sub2API 登录接口。") from exc
            data = self._decode_response(response, auth=True)
            if not isinstance(data, dict):
                raise Sub2APIAuthError("Sub2API 登录响应格式不兼容。")
            if data.get("requires_2fa") is True:
                raise Sub2APIAuthError(
                    "该管理员账号启用了 2FA，当前插件不保存或请求验证码。"
                )
            token = str(data.get("access_token") or "").strip()
            if not token:
                raise Sub2APIAuthError("Sub2API 登录响应缺少访问令牌。")
            expires_in = self._as_positive_int(data.get("expires_in"), default=300)
            self._token = token
            self._token_expires_at = time.monotonic() + max(1, expires_in - 30)
            return token

    async def _send_get(
        self, path: str, params: Mapping[str, str], token: str
    ) -> httpx.Response:
        try:
            return await self._client.get(
                f"{self.api_root}{path}",
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Admin-UI-Request": "1",
                },
            )
        except httpx.RequestError as exc:
            raise Sub2APIRequestError("连接 Sub2API 查询接口失败。") from exc

    @staticmethod
    def _decode_response(response: httpx.Response, *, auth: bool) -> Any:
        if response.is_redirect:
            error_type = Sub2APIAuthError if auth else Sub2APIRequestError
            raise error_type("Sub2API 返回了重定向，已按只读安全策略拒绝跟随。")
        if response.status_code == 401:
            if auth:
                raise Sub2APIAuthError("Sub2API 管理员账号或密码错误。")
            raise Sub2APIAuthError("Sub2API 登录状态已失效。")
        if response.status_code == 403:
            raise Sub2APIAuthError("Sub2API 管理员账号无权读取该数据。")
        if not 200 <= response.status_code < 300:
            error_type = Sub2APIAuthError if auth else Sub2APIRequestError
            raise error_type(f"Sub2API 返回 HTTP {response.status_code}。")
        try:
            payload = response.json()
        except ValueError as exc:
            error_type = Sub2APIAuthError if auth else Sub2APIRequestError
            raise error_type("Sub2API 返回了非 JSON 响应。") from exc
        if not isinstance(payload, dict):
            error_type = Sub2APIAuthError if auth else Sub2APIRequestError
            raise error_type("Sub2API 响应格式不兼容。")
        if payload.get("code") not in (0, "0", None):
            error_type = Sub2APIAuthError if auth else Sub2APIRequestError
            code = re.sub(r"[^A-Za-z0-9_.-]", "", str(payload.get("code")))[:40]
            suffix = f"（{code}）" if code else ""
            raise error_type(f"Sub2API 返回业务错误{suffix}。")
        if "data" not in payload:
            error_type = Sub2APIAuthError if auth else Sub2APIRequestError
            raise error_type("Sub2API 响应缺少 data 字段。")
        return payload["data"]

    async def _get_cached(
        self, key: tuple[str, tuple[tuple[str, str], ...]]
    ) -> Any | None:
        if self.cache_ttl_seconds <= 0:
            return None
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None or entry.expires_at <= time.monotonic():
                self._cache.pop(key, None)
                return None
            return copy.deepcopy(entry.value)

    async def _put_cached(
        self, key: tuple[str, tuple[tuple[str, str], ...]], value: Any
    ) -> None:
        if self.cache_ttl_seconds <= 0:
            return
        async with self._cache_lock:
            self._cache[key] = _CacheEntry(
                expires_at=time.monotonic() + self.cache_ttl_seconds,
                value=copy.deepcopy(value),
            )

    @staticmethod
    def _assert_read_only_path(path: str) -> None:
        if path in READ_ONLY_PATHS or ACCOUNT_TODAY_STATS_PATH.fullmatch(path):
            return
        raise Sub2APIRequestError("请求路径不在插件的只读白名单中。")

    @staticmethod
    def _expect_dict(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise Sub2APIRequestError("Sub2API 响应格式不兼容。")
        return value

    @staticmethod
    def _as_positive_int(value: Any, *, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _sanitize_account(value: dict[str, Any]) -> dict[str, Any]:
        safe_keys = {
            "id",
            "name",
            "platform",
            "type",
            "concurrency",
            "priority",
            "rate_multiplier",
            "status",
            "last_used_at",
            "expires_at",
            "schedulable",
            "rate_limited_at",
            "rate_limit_reset_at",
            "overload_until",
            "temp_unschedulable_until",
            "quota_dimension",
            "group_ids",
            "current_concurrency",
        }
        result = {key: value.get(key) for key in safe_keys if key in value}
        credentials = value.get("credentials")
        extra = value.get("extra")
        registration_email = ""
        if isinstance(credentials, dict):
            registration_email = str(credentials.get("email") or "").strip()
        if not registration_email and isinstance(extra, dict):
            registration_email = str(extra.get("email") or "").strip()
        if registration_email:
            result["registration_email"] = registration_email
        if isinstance(extra, dict):
            extra_keys = {
                "codex_primary_used_percent",
                "codex_primary_reset_at",
                "codex_7d_used_percent",
                "codex_7d_reset_at",
                "codex_usage_updated_at",
            }
            result["extra"] = {
                key: extra.get(key) for key in extra_keys if key in extra
            }
        groups = value.get("groups")
        if isinstance(groups, list):
            result["groups"] = [
                {"id": group.get("id"), "name": group.get("name")}
                for group in groups
                if isinstance(group, dict)
            ]
        return result
