"""Read-only Sub2API admin client: the same GET endpoints the admin web UI uses.

The only POST is ``/auth/login`` for a short-lived in-memory token. Redirects are
never followed, so the bearer token cannot leak to another host.
"""

from __future__ import annotations

import asyncio
import copy
import http.client
import json
import math
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import timezone as datetime_timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..base import FeatureError

LOGIN_PATH = "/auth/login"
READ_ONLY_PATHS = frozenset({
    "/admin/dashboard/stats",
    "/admin/dashboard/snapshot-v2",
    "/admin/dashboard/user-breakdown",
    "/admin/usage",
    "/admin/usage/stats",
    "/admin/accounts",
    "/admin/system/version",
})
ACCOUNT_TODAY_STATS_PATH = re.compile(r"^/admin/accounts/[1-9][0-9]*/today-stats$")
OVERVIEW_HISTORY_START = date(2026, 7, 13)
CURRENT_BILLING_PERIOD_START = "2026-08-13 14:00"
COST_OVERVIEW_URL = "https://mmdustc.top/api/projects/cost/overview"
COST_OVERVIEW_TIMEOUT_SECONDS = 60.0
TREND_DAYS_RE = re.compile(r"^([1-9][0-9]*)d$", re.IGNORECASE)
USER_AGENT = "Dududa-Sub2API-Readonly/0.1"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

# (method, url, headers, body, timeout) -> (status, body)
Transport = Callable[[str, str, Mapping[str, str], "bytes | None", float], "tuple[int, bytes]"]


class Sub2APIError(FeatureError):
    """Base error safe to translate into a user-facing message."""


class Sub2APIConfigError(Sub2APIError):
    pass


class Sub2APIAuthError(Sub2APIError):
    pass


class Sub2APIRequestError(Sub2APIError):
    pass


class TransportError(Exception):
    """The request never produced an HTTP response."""


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_params(self) -> dict[str, str]:
        return {"start_date": self.start.isoformat(), "end_date": self.end.isoformat()}


@dataclass
class _CacheEntry:
    expires_at: float
    value: Any


# ---------------------------------------------------------------- transport


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _read_limited(response: Any) -> bytes:
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise TransportError("response_too_large")
    return body


def urllib_transport(*, proxy_url: str | None, direct_hosts: Iterable[str]) -> Transport:
    """Blocking transport with the Host proxy policy (direct hosts bypass the proxy) and no redirects."""
    direct_hosts = tuple(direct_hosts)

    def send(method: str, url: str, headers: Mapping[str, str], body: bytes | None,
             timeout: float) -> tuple[int, bytes]:
        host = (urlsplit(url).hostname or "").lower()
        direct = any(host == item or host.endswith("." + item) for item in direct_hosts)
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url and not direct else {}
        opener = build_opener(ProxyHandler(proxies), _NoRedirect)
        request = Request(url, data=body, headers={"User-Agent": USER_AGENT, **headers}, method=method)
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, _read_limited(response)
        except HTTPError as error:
            try:
                return error.code, _read_limited(error)
            finally:
                error.close()
        except (URLError, OSError, http.client.HTTPException) as error:
            raise TransportError(type(error).__name__) from None

    return send


# ---------------------------------------------------------------- pure helpers


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


def today_in_timezone(timezone: str) -> date:
    try:
        return datetime.now(ZoneInfo(timezone)).date()
    except ZoneInfoNotFoundError as exc:
        raise Sub2APIConfigError(f"未知时区：{timezone}") from exc


def parse_date_range(start_value: str, end_value: str, *, timezone: str, max_days: int) -> DateRange:
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
    if end > today_in_timezone(timezone):
        raise Sub2APIConfigError("结束日期不能晚于今天。")
    return period


def parse_trend_period(value: str, *, timezone: str, max_days: int) -> DateRange:
    match = TREND_DAYS_RE.fullmatch((value or "").strip())
    if not match:
        raise Sub2APIConfigError("趋势天数格式应为正整数加 d，例如 7d。")
    days = int(match.group(1))
    limit = max(1, max_days)
    if days > limit:
        raise Sub2APIConfigError(f"趋势图最多允许查询 {limit} 天。")
    end = today_in_timezone(timezone)
    return DateRange(start=end - timedelta(days=days - 1), end=end)


def parse_user_trend_request(mode_or_days: str | None, days: str | None, *, timezone: str,
                             max_days: int) -> tuple[DateRange, bool]:
    first = (mode_or_days or "").strip()
    second = (days or "").strip()
    if first.lower() == "sum":
        return parse_trend_period(second or "7d", timezone=timezone, max_days=max_days), True
    if second:
        raise Sub2APIConfigError("trenduser 参数格式应为 [天数d] 或 sum [天数d]。")
    return parse_trend_period(first or "7d", timezone=timezone, max_days=max_days), False


def overview_history_period(timezone: str) -> DateRange:
    end = today_in_timezone(timezone)
    if end < OVERVIEW_HISTORY_START:
        raise Sub2APIConfigError("概览累计开始日期不能晚于今天。")
    return DateRange(start=OVERVIEW_HISTORY_START, end=end)


def fallback_cost_overview(accounts: Iterable[dict[str, Any]], *, timezone: str) -> dict[str, Any]:
    """Current-cycle snapshot derived from account quota metadata when the cost site is down."""
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise Sub2APIConfigError(f"未知时区：{timezone}") from exc
    now = datetime.now(zone)
    candidates: list[tuple[datetime, dict[str, Any], float, datetime]] = []
    for account in accounts:
        if account.get("platform") != "openai" or account.get("status") != "active":
            continue
        extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
        try:
            used_percent = float(extra.get("codex_7d_used_percent") or 0)
            resets_at = datetime.fromisoformat(
                str(extra.get("codex_7d_reset_at") or "").replace("Z", "+00:00")).astimezone(zone)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(used_percent) or not 0 < used_percent <= 100 or resets_at <= now:
            continue
        last_used_at = datetime.min.replace(tzinfo=datetime_timezone.utc)
        try:
            last_used_at = datetime.fromisoformat(str(account.get("last_used_at") or "").replace("Z", "+00:00"))
            if last_used_at.tzinfo is None:
                last_used_at = last_used_at.replace(tzinfo=zone)
        except ValueError:
            pass
        candidates.append((last_used_at, account, used_percent, resets_at))

    estimate = None
    if candidates:
        _, account, used_percent, resets_at = max(candidates, key=lambda item: item[0])
        extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
        try:
            window_minutes = int(extra.get("codex_7d_window_minutes") or 7 * 24 * 60)
        except (TypeError, ValueError):
            window_minutes = 7 * 24 * 60
        cycle_started_at = resets_at - timedelta(minutes=max(1, window_minutes))
        estimate = {
            "account_id": account.get("id"),
            "used_percent": used_percent,
            "cycle_started_at": cycle_started_at.isoformat(timespec="seconds"),
            "resets_at": resets_at.isoformat(timespec="seconds"),
        }
    return {
        "source": "sub2api-account-fallback",
        "period_start": CURRENT_BILLING_PERIOD_START,
        "period_end": now.date().isoformat(),
        "synced_at": now.isoformat(timespec="seconds"),
        "members": [],
        "total_actual_cost": 0,
        "pro_estimate": estimate,
    }


def sanitize_account(value: dict[str, Any]) -> dict[str, Any]:
    """Keep only status fields; credentials never leave this function."""
    safe_keys = {
        "id", "name", "platform", "type", "concurrency", "priority", "rate_multiplier", "status",
        "last_used_at", "expires_at", "schedulable", "rate_limited_at", "rate_limit_reset_at",
        "overload_until", "temp_unschedulable_until", "quota_dimension", "group_ids", "current_concurrency",
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
            "codex_primary_used_percent", "codex_primary_reset_at", "codex_7d_used_percent",
            "codex_7d_reset_at", "codex_7d_window_minutes", "codex_usage_updated_at",
        }
        result["extra"] = {key: extra.get(key) for key in extra_keys if key in extra}
    groups = value.get("groups")
    if isinstance(groups, list):
        result["groups"] = [{"id": group.get("id"), "name": group.get("name")}
                            for group in groups if isinstance(group, dict)]
    return result


def _as_positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _as_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _as_nonnegative_float(value: Any) -> float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed >= 0 else 0.0


def _expect_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Sub2APIRequestError("Sub2API 响应格式不兼容。")
    return value


def decode_response(status: int, body: bytes, *, auth: bool) -> Any:
    error_type = Sub2APIAuthError if auth else Sub2APIRequestError
    if 300 <= status < 400:
        raise error_type("Sub2API 返回了重定向，已按只读安全策略拒绝跟随。")
    if status == 401:
        raise Sub2APIAuthError("Sub2API 管理员账号或密码错误。" if auth else "Sub2API 登录状态已失效。")
    if status == 403:
        raise Sub2APIAuthError("Sub2API 管理员账号无权读取该数据。")
    if not 200 <= status < 300:
        raise error_type(f"Sub2API 返回 HTTP {status}。")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise error_type("Sub2API 返回了非 JSON 响应。") from exc
    if not isinstance(payload, dict):
        raise error_type("Sub2API 响应格式不兼容。")
    if payload.get("code") not in (0, "0", None):
        code = re.sub(r"[^A-Za-z0-9_.-]", "", str(payload.get("code")))[:40]
        suffix = f"（{code}）" if code else ""
        raise error_type(f"Sub2API 返回业务错误{suffix}。")
    if "data" not in payload:
        raise error_type("Sub2API 响应缺少 data 字段。")
    return payload["data"]


# ---------------------------------------------------------------- client


class Sub2APIClient:
    """Client for the same read-only endpoints used by the Sub2API admin UI."""

    def __init__(self, *, base_url: str, email: str, password: str, transport: Transport,
                 timezone: str = "Asia/Shanghai", timeout_seconds: float = 30,
                 cache_ttl_seconds: float = 30) -> None:
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
        self.timeout = max(3.0, min(float(timeout_seconds), 60.0))
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._transport = transport
        self._token = ""
        self._token_expires_at = 0.0
        self._login_lock = asyncio.Lock()
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], _CacheEntry] = {}

    async def _send(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None = None,
                    timeout: float | None = None) -> tuple[int, bytes]:
        return await asyncio.to_thread(self._transport, method, url,
                                       {"Accept": "application/json", "Accept-Language": "zh-CN", **headers},
                                       body, timeout or self.timeout)

    # ------------------------------------------------------------ endpoints

    async def get_cost_overview(self) -> dict[str, Any]:
        """Current billing-round snapshot published by the cost-sharing site (public, no token)."""
        try:
            status, body = await self._send("GET", COST_OVERVIEW_URL, {}, timeout=COST_OVERVIEW_TIMEOUT_SECONDS)
        except TransportError as exc:
            raise Sub2APIRequestError("无法连接费用分摊网站的当前轮快照。") from exc
        if 300 <= status < 400:
            raise Sub2APIRequestError("费用分摊网站返回了重定向。")
        if not 200 <= status < 300:
            raise Sub2APIRequestError(f"费用分摊网站返回 HTTP {status}。")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise Sub2APIRequestError("费用分摊网站返回了非 JSON 响应。") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("members"), list):
            raise Sub2APIRequestError("费用分摊网站的当前轮快照格式不兼容。")
        return payload

    async def get_stats(self) -> dict[str, Any]:
        return _expect_dict(await self._get("/admin/dashboard/stats"))

    async def get_snapshot(self, period: DateRange) -> dict[str, Any]:
        params = {**period.as_params(), "granularity": "day", "include_stats": "false", "include_trend": "true",
                  "include_model_stats": "true", "include_group_stats": "false", "include_users_trend": "false"}
        return _expect_dict(await self._get("/admin/dashboard/snapshot-v2", params=params))

    async def get_user_trend(self, period: DateRange, *, limit: int = 10) -> dict[str, Any]:
        params: dict[str, str | int] = {
            **period.as_params(), "granularity": "day", "include_stats": "false", "include_trend": "false",
            "include_model_stats": "false", "include_group_stats": "false", "include_users_trend": "true",
            "users_trend_limit": max(1, min(int(limit), 50)),
        }
        return _expect_dict(await self._get("/admin/dashboard/snapshot-v2", params=params))

    async def get_user_ranking(self, period: DateRange, *, limit: int = 10) -> dict[str, Any]:
        params: dict[str, str | int] = {**period.as_params(), "sort_by": "total_tokens",
                                        "limit": max(1, min(int(limit), 100))}
        return _expect_dict(await self._get("/admin/dashboard/user-breakdown", params=params))

    async def get_usage_stats(self, period: DateRange) -> dict[str, Any]:
        return _expect_dict(await self._get("/admin/usage/stats", params=period.as_params()))

    async def get_pro_quota_estimate(self, estimate: dict[str, Any], *,
                                     synced_at: str | None = None) -> dict[str, Any]:
        try:
            account_id = int(estimate.get("account_id") or 0)
        except (TypeError, ValueError) as exc:
            raise Sub2APIConfigError("Pro 额度观测缺少上游账号 ID。") from exc
        if account_id <= 0:
            raise Sub2APIConfigError("Pro 额度观测缺少上游账号 ID。")
        used_percent = _as_nonnegative_float(estimate.get("used_percent"))
        if not 0 < used_percent <= 100:
            raise Sub2APIConfigError("Pro 额度已用比例格式不兼容。")
        cycle_started_at = self._parse_timestamp(estimate.get("cycle_started_at"))
        observed_at = self._parse_timestamp(synced_at) if synced_at else datetime.now(ZoneInfo(self.timezone))
        stats = _expect_dict(await self._get(
            "/admin/usage/stats",
            params={"account_id": account_id, "start_date": cycle_started_at.date().isoformat(),
                    "end_date": observed_at.date().isoformat()},
            use_cache=False))
        pre_reset_cost = await self._get_pre_reset_actual_cost(account_id, cycle_started_at)
        cycle_actual_cost = max(0.0, _as_nonnegative_float(stats.get("total_actual_cost")) - pre_reset_cost)
        if cycle_actual_cost <= 0:
            return dict(estimate)
        estimated_quota = cycle_actual_cost / (used_percent / 100.0)
        if not math.isfinite(estimated_quota) or estimated_quota <= 0:
            return dict(estimate)
        return {**estimate, "cycle_actual_cost": cycle_actual_cost, "estimated_quota": estimated_quota}

    async def _get_pre_reset_actual_cost(self, account_id: int, cycle_started_at: datetime) -> float:
        total = 0.0
        start_date = cycle_started_at.date().isoformat()
        for page in range(1, 101):
            payload = _expect_dict(await self._get(
                "/admin/usage",
                params={"account_id": account_id, "start_date": start_date, "end_date": start_date,
                        "page": page, "page_size": 1000, "sort_by": "created_at", "sort_order": "asc",
                        "exact_total": False},
                use_cache=False))
            items = payload.get("items") or []
            if not isinstance(items, list):
                raise Sub2APIRequestError("Sub2API 用量明细响应格式不兼容。")
            for item in items:
                if not isinstance(item, dict):
                    continue
                if self._parse_timestamp(item.get("created_at")) >= cycle_started_at:
                    return total
                total += _as_nonnegative_float(item.get("actual_cost"))
            if len(items) < 1000:
                return total
        raise Sub2APIRequestError("Pro 周期起点明细超过安全扫描上限。")

    async def get_usage_ranking_since(self, period_start: str, period_end: str, *, synced_at: str | None = None,
                                      limit: int = 10) -> dict[str, Any]:
        """Usage stats and user ranking from an exact timestamp, trimming the partial boundary days."""
        cutoff = self._parse_timestamp(period_start)
        upper_bound = self._parse_timestamp(synced_at) if synced_at else None
        try:
            end_date = date.fromisoformat(period_end.strip())
        except (AttributeError, ValueError) as exc:
            raise Sub2APIConfigError("当前轮结束日期格式不兼容。") from exc
        safe_limit = max(1, min(int(limit), 100))
        cache_key = ("safe:/admin/usage/current-cycle", (
            ("period_start", cutoff.isoformat()), ("period_end", end_date.isoformat()),
            ("synced_at", upper_bound.isoformat() if upper_bound else ""), ("limit", str(safe_limit))))
        cached = self._get_cached(cache_key)
        if isinstance(cached, dict):
            return cached

        effective_end = min(end_date, upper_bound.date()) if upper_bound else end_date
        if effective_end < cutoff.date() or (upper_bound and upper_bound < cutoff):
            raise Sub2APIConfigError("当前轮同步时间不能早于计费起点。")
        period = DateRange(start=cutoff.date(), end=effective_end)
        stats, ranking_payload, excluded = await asyncio.gather(
            self.get_usage_stats(period),
            self.get_user_ranking(period, limit=100),
            self._get_usage_boundary_exclusions(cutoff, upper_bound, effective_end))
        result = subtract_usage(stats, ranking_payload, excluded, limit=safe_limit)
        self._put_cached(cache_key, result)
        return result

    async def _get_usage_boundary_exclusions(self, cutoff: datetime, upper_bound: datetime | None,
                                             end_date: date) -> list[dict[str, Any]]:
        scans = []
        if cutoff.time() != datetime.min.time():
            scans.append(self._scan_usage_boundary(cutoff.date(), boundary=cutoff, before=True))
        if upper_bound and upper_bound.date() == end_date:
            scans.append(self._scan_usage_boundary(upper_bound.date(), boundary=upper_bound, before=False))
        if not scans:
            return []
        return [item for rows in await asyncio.gather(*scans) for item in rows]

    async def _scan_usage_boundary(self, boundary_date: date, *, boundary: datetime,
                                   before: bool) -> list[dict[str, Any]]:
        excluded: list[dict[str, Any]] = []
        for page in range(1, 101):
            payload = _expect_dict(await self._get(
                "/admin/usage",
                params={"start_date": boundary_date.isoformat(), "end_date": boundary_date.isoformat(),
                        "page": page, "page_size": 1000, "sort_by": "created_at",
                        "sort_order": "asc" if before else "desc", "exact_total": False},
                use_cache=False))
            items = payload.get("items") or []
            if not isinstance(items, list):
                raise Sub2APIRequestError("Sub2API 用量明细响应格式不兼容。")
            for item in items:
                if not isinstance(item, dict):
                    continue
                created_at = self._parse_timestamp(item.get("created_at"))
                if not (created_at < boundary if before else created_at > boundary):
                    return excluded
                excluded.append(item)
            if len(items) < 1000:
                return excluded
        raise Sub2APIRequestError("当前轮边界明细超过安全扫描上限。")

    async def get_accounts(self, *, page_size: int = 100) -> list[dict[str, Any]]:
        size = max(1, min(int(page_size), 100))
        safe_cache_key = ("safe:/admin/accounts", (("page_size", str(size)),))
        cached = self._get_cached(safe_cache_key)
        if isinstance(cached, list):
            return [item for item in cached if isinstance(item, dict)]
        result: list[dict[str, Any]] = []
        for page in range(1, 101):
            payload = _expect_dict(await self._get(
                "/admin/accounts",
                params={"page": page, "page_size": size, "lite": 1, "sort_by": "name", "sort_order": "asc"},
                use_cache=False))
            items = payload.get("items") or []
            if not isinstance(items, list):
                raise Sub2APIRequestError("账号列表响应格式不兼容。")
            result.extend(sanitize_account(item) for item in items if isinstance(item, dict))
            if page >= _as_positive_int(payload.get("pages"), default=1):
                break
        self._put_cached(safe_cache_key, result)
        return result

    async def get_account_today_stats(self, account_id: int) -> dict[str, Any]:
        safe_id = int(account_id)
        if safe_id <= 0:
            raise Sub2APIConfigError("账号 ID 必须是正整数。")
        return _expect_dict(await self._get(f"/admin/accounts/{safe_id}/today-stats"))

    async def get_system_version(self) -> dict[str, Any]:
        return _expect_dict(await self._get("/admin/system/version"))

    # ------------------------------------------------------------ plumbing

    async def _get(self, path: str, *, params: Mapping[str, str | int | float | bool] | None = None,
                   use_cache: bool = True) -> Any:
        if path not in READ_ONLY_PATHS and not ACCOUNT_TODAY_STATS_PATH.fullmatch(path):
            raise Sub2APIRequestError("请求路径不在插件的只读白名单中。")
        normalized = {str(key): str(value).lower() if isinstance(value, bool) else str(value)
                      for key, value in (params or {}).items() if value is not None}
        normalized.setdefault("timezone", self.timezone)
        cache_key = (path, tuple(sorted(normalized.items())))
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached
        url = f"{self.api_root}{path}?{urlencode(normalized)}"
        status, body = await self._send_get(url, await self._ensure_token())
        if status == 401:
            self._token, self._token_expires_at = "", 0.0
            status, body = await self._send_get(url, await self._ensure_token())
        data = decode_response(status, body, auth=False)
        if use_cache:
            self._put_cached(cache_key, data)
        return data

    async def _send_get(self, url: str, token: str) -> tuple[int, bytes]:
        try:
            return await self._send("GET", url, {"Authorization": f"Bearer {token}", "X-Admin-UI-Request": "1"})
        except TransportError as exc:
            raise Sub2APIRequestError("连接 Sub2API 查询接口失败。") from exc

    async def _ensure_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        async with self._login_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token
            body = json.dumps({"email": self.email, "password": self.password}).encode()
            try:
                status, raw = await self._send("POST", f"{self.api_root}{LOGIN_PATH}",
                                               {"Content-Type": "application/json"}, body)
            except TransportError as exc:
                raise Sub2APIAuthError("无法连接 Sub2API 登录接口。") from exc
            data = decode_response(status, raw, auth=True)
            if not isinstance(data, dict):
                raise Sub2APIAuthError("Sub2API 登录响应格式不兼容。")
            if data.get("requires_2fa") is True:
                raise Sub2APIAuthError("该管理员账号启用了 2FA，当前插件不保存或请求验证码。")
            token = str(data.get("access_token") or "").strip()
            if not token:
                raise Sub2APIAuthError("Sub2API 登录响应缺少访问令牌。")
            expires_in = _as_positive_int(data.get("expires_in"), default=300)
            self._token = token
            self._token_expires_at = time.monotonic() + max(1, expires_in - 30)
            return token

    def _get_cached(self, key: tuple[str, tuple[tuple[str, str], ...]]) -> Any | None:
        if self.cache_ttl_seconds <= 0:
            return None
        entry = self._cache.get(key)
        if entry is None or entry.expires_at <= time.monotonic():
            self._cache.pop(key, None)
            return None
        return copy.deepcopy(entry.value)

    def _put_cached(self, key: tuple[str, tuple[tuple[str, str], ...]], value: Any) -> None:
        if self.cache_ttl_seconds > 0:
            self._cache[key] = _CacheEntry(time.monotonic() + self.cache_ttl_seconds, copy.deepcopy(value))

    def _parse_timestamp(self, value: Any) -> datetime:
        text = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise Sub2APIConfigError("当前轮用量时间格式不兼容。") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(self.timezone))
        return parsed


def subtract_usage(stats: dict[str, Any], ranking: dict[str, Any], excluded: list[dict[str, Any]], *,
                   limit: int) -> dict[str, Any]:
    """Remove boundary-day usage rows (outside the exact window) from day-granular stats and ranking."""
    result = dict(stats)
    users = {str(item.get("user_id")): dict(item) for item in ranking.get("users") or []
             if isinstance(item, dict) and item.get("user_id")}
    duration_sum = _as_nonnegative_float(result.get("average_duration_ms")) * _as_nonnegative_int(
        result.get("total_requests"))
    for item in excluded:
        token_fields = {field: _as_nonnegative_int(item.get(field))
                        for field in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")}
        tokens = sum(token_fields.values())
        actual_cost = _as_nonnegative_float(item.get("actual_cost"))
        result["total_tokens"] = max(0, _as_nonnegative_int(result.get("total_tokens")) - tokens)
        result["total_requests"] = max(0, _as_nonnegative_int(result.get("total_requests")) - 1)
        result["total_actual_cost"] = max(0.0, _as_nonnegative_float(result.get("total_actual_cost")) - actual_cost)
        for field, value in token_fields.items():
            result[f"total_{field}"] = max(0, _as_nonnegative_int(result.get(f"total_{field}")) - value)
        if "total_cache_tokens" in result:
            result["total_cache_tokens"] = max(
                0, _as_nonnegative_int(result.get("total_cache_tokens"))
                - token_fields["cache_creation_tokens"] - token_fields["cache_read_tokens"])
        duration_sum = max(0.0, duration_sum - _as_nonnegative_float(item.get("duration_ms")))
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        row = users.get(str(item.get("user_id") or user.get("id")))
        if row is None:
            continue
        row["total_tokens"] = max(0, _as_nonnegative_int(row.get("total_tokens")) - tokens)
        row["requests"] = max(0, _as_nonnegative_int(row.get("requests")) - 1)
        row["actual_cost"] = max(0.0, _as_nonnegative_float(row.get("actual_cost")) - actual_cost)
    remaining = _as_nonnegative_int(result.get("total_requests"))
    result["average_duration_ms"] = duration_sum / remaining if remaining else 0
    result["users"] = sorted(users.values(), key=lambda item: _as_nonnegative_int(item.get("total_tokens")),
                             reverse=True)[:limit]
    return result
