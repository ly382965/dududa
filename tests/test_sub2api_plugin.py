from __future__ import annotations

import ast
import asyncio
import math
import unittest
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from plugins.astrbot_plugin_sub2api_readonly.charts import (
    cumulative_user_series,
    linear_axis_bounds,
    render_total_trend_chart,
    render_user_trend_chart,
    smooth_curve,
    sqrt_axis_bounds,
    trend_points,
    user_trend_series,
)
from plugins.astrbot_plugin_sub2api_readonly.client import (
    DateRange,
    Sub2APIClient,
    Sub2APIConfigError,
    Sub2APIRequestError,
    access_error,
    is_sub2api_command,
    is_sub2api_event_command,
    normalize_base_url,
    overview_history_period,
    parse_date_range,
    parse_trend_period,
    parse_user_trend_request,
    should_block_exclusive_group,
    today_in_timezone,
)
from plugins.astrbot_plugin_sub2api_readonly.formatters import (
    format_accounts,
    format_overview_history,
    format_range,
    format_today,
    mask_identifier,
)

ROOT = Path(__file__).resolve().parents[1]


def response(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"code": 0, "message": "success", "data": data})


def login_response() -> httpx.Response:
    return response({"access_token": "unit-token", "expires_in": 3600})


class Sub2APIUtilityTests(unittest.TestCase):
    def test_normalize_base_url_accepts_dashboard_and_api_urls(self) -> None:
        self.assertEqual(
            normalize_base_url("https://example.invalid/admin/dashboard"),
            "https://example.invalid",
        )
        self.assertEqual(
            normalize_base_url("https://example.invalid/prefix/api/v1/"),
            "https://example.invalid/prefix",
        )
        with self.assertRaises(Sub2APIConfigError):
            normalize_base_url("https://user:secret@example.invalid")
        with self.assertRaises(Sub2APIConfigError):
            normalize_base_url("https://example.invalid?target=other")
        with self.assertRaises(Sub2APIConfigError):
            normalize_base_url("http://example.invalid")

    def test_date_range_is_inclusive_and_bounded(self) -> None:
        period = parse_date_range(
            "2026-07-01",
            "2026-07-24",
            timezone="Asia/Shanghai",
            max_days=30,
        )
        self.assertEqual(period.days, 24)
        with self.assertRaises(Sub2APIConfigError):
            parse_date_range(
                "2026-07-24",
                "2026-07-01",
                timezone="Asia/Shanghai",
                max_days=30,
            )
        with self.assertRaises(Sub2APIConfigError):
            parse_date_range(
                "2026-07-01",
                "2026-07-24",
                timezone="Asia/Shanghai",
                max_days=10,
            )

        overview_period = overview_history_period("Asia/Shanghai")
        self.assertEqual(overview_period.start, date(2026, 7, 13))
        self.assertEqual(overview_period.end, today_in_timezone("Asia/Shanghai"))
        tomorrow = today_in_timezone("Asia/Shanghai") + timedelta(days=1)
        with self.assertRaises(Sub2APIConfigError):
            parse_date_range(
                tomorrow.isoformat(),
                tomorrow.isoformat(),
                timezone="Asia/Shanghai",
                max_days=10,
            )

    def test_trend_period_requires_days_suffix_and_respects_limit(self) -> None:
        period = parse_trend_period("7d", timezone="Asia/Shanghai", max_days=90)
        self.assertEqual(period.days, 7)
        self.assertEqual(period.end, today_in_timezone("Asia/Shanghai"))
        for invalid in ("", "7", "0d", "-1d", "91d"):
            with self.subTest(value=invalid), self.assertRaises(Sub2APIConfigError):
                parse_trend_period(
                    invalid, timezone="Asia/Shanghai", max_days=90
                )

    def test_user_trend_sum_mode_and_default_days(self) -> None:
        period, cumulative = parse_user_trend_request(
            "sum", "30d", timezone="Asia/Shanghai", max_days=90
        )
        self.assertEqual(period.days, 30)
        self.assertTrue(cumulative)

        period, cumulative = parse_user_trend_request(
            None, None, timezone="Asia/Shanghai", max_days=90
        )
        self.assertEqual(period.days, 7)
        self.assertFalse(cumulative)

        period, cumulative = parse_user_trend_request(
            "14d", None, timezone="Asia/Shanghai", max_days=90
        )
        self.assertEqual(period.days, 14)
        self.assertFalse(cumulative)
        with self.assertRaises(Sub2APIConfigError):
            parse_user_trend_request(
                "other", "7d", timezone="Asia/Shanghai", max_days=90
            )

    def test_trend_chart_fills_missing_days_and_renders_png(self) -> None:
        period = DateRange(start=date(2026, 8, 1), end=date(2026, 8, 4))
        snapshot = {
            "trend": [
                {"date": "2026-08-01", "total_tokens": 1_000},
                {"date": "2026-08-03T00:00:00Z", "total_tokens": 3_000},
                {"date": "invalid", "total_tokens": 999_999},
            ]
        }
        self.assertEqual(
            trend_points(snapshot, period),
            [
                (date(2026, 8, 1), 1_000),
                (date(2026, 8, 2), 0),
                (date(2026, 8, 3), 3_000),
                (date(2026, 8, 4), 0),
            ],
        )
        png = render_total_trend_chart(snapshot, period)
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (1440, 900))

    def test_sqrt_axis_uses_ninety_percent_and_smoothing_preserves_points(self) -> None:
        values = [0, 1_000, 1_000_000, 1_000_000_000]
        axis_min, axis_max = sqrt_axis_bounds(values, occupancy=0.9)
        transformed = [math.sqrt(value) for value in values]
        self.assertAlmostEqual(
            (max(transformed) - min(transformed)) / (axis_max - axis_min),
            0.9,
        )
        self.assertLessEqual(axis_min, min(transformed))
        self.assertGreaterEqual(axis_max, max(transformed))

        points = [(0, 100), (10, 50), (20, 80), (30, 20)]
        rendered = smooth_curve(points, samples_per_segment=8)
        self.assertGreater(len(rendered), len(points))
        self.assertEqual(rendered[0], points[0])
        self.assertEqual(rendered[-1], points[-1])
        for point in points:
            self.assertIn(point, rendered)
        self.assertTrue(all(20 <= y <= 100 for _, y in rendered))

    def test_cumulative_linear_axis_starts_at_zero(self) -> None:
        axis_min, axis_max = linear_axis_bounds(
            [0, 500, 1_000], occupancy=0.9
        )
        self.assertEqual(axis_min, 0)
        self.assertAlmostEqual(1_000 / axis_max, 0.9)

    def test_user_trend_selects_top_ten_masks_labels_and_renders_png(self) -> None:
        period = DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3))
        rows = []
        for user_id in range(1, 13):
            tokens = (13 - user_id) * 100
            rows.extend(
                (
                    {
                        "date": "2026-08-01",
                        "user_id": user_id,
                        "username": f"long-user-{user_id}",
                        "email": f"user{user_id}@example.invalid",
                        "tokens": tokens,
                    },
                    {
                        "date": "2026-08-03",
                        "user_id": user_id,
                        "username": f"long-user-{user_id}",
                        "email": f"user{user_id}@example.invalid",
                        "tokens": tokens // 2,
                    },
                )
            )
        snapshot = {"users_trend": rows}
        series = user_trend_series(
            snapshot, period, reveal_identifiers=False, limit=10
        )
        self.assertEqual(len(series), 10)
        self.assertEqual(series[0].label, "lo***1")
        self.assertEqual(series[0].values, (1_200, 0, 600))
        self.assertEqual(series[0].total, 1_800)
        self.assertGreater(series[0].total, series[-1].total)

        cumulative = cumulative_user_series(series)
        self.assertEqual(cumulative[0].values, (1_200, 1_200, 1_800))
        self.assertEqual(cumulative[0].values[-1], cumulative[0].total)
        self.assertTrue(
            all(
                earlier <= later
                for earlier, later in zip(
                    cumulative[0].values, cumulative[0].values[1:]
                )
            )
        )

        revealed = user_trend_series(
            snapshot, period, reveal_identifiers=True, limit=10
        )
        self.assertEqual(revealed[0].label, "long-user-1")

        localized = user_trend_series(
            {
                "users_trend": [
                    {
                        "date": "2026-08-01",
                        "user_id": 99,
                        "username": "中文用户",
                        "email": "localized@example.invalid",
                        "tokens": 100,
                    }
                ]
            },
            period,
            reveal_identifiers=True,
            limit=10,
        )
        self.assertEqual(localized[0].label, "localized@example.invalid")
        png = render_user_trend_chart(
            snapshot, period, reveal_identifiers=False, limit=10
        )
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (1440, 900))
        cumulative_png = render_user_trend_chart(
            snapshot,
            period,
            reveal_identifiers=False,
            limit=10,
            cumulative=True,
        )
        with Image.open(BytesIO(cumulative_png)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (1440, 900))

    def test_access_policy_fails_closed(self) -> None:
        self.assertIsNotNone(
            access_error(
                enabled=True,
                group_id="100",
                sender_id="1",
                group_whitelist=[],
                private_user_whitelist=[],
            )
        )
        self.assertIsNone(
            access_error(
                enabled=True,
                group_id=100,
                sender_id="1",
                group_whitelist={"100"},
                private_user_whitelist=[],
            )
        )
        self.assertIsNotNone(
            access_error(
                enabled=True,
                group_id="200",
                sender_id="1",
                group_whitelist={"100"},
                private_user_whitelist=[],
            )
        )
        self.assertIsNone(
            access_error(
                enabled=True,
                group_id="",
                sender_id=42,
                group_whitelist=set(),
                private_user_whitelist={"42"},
            )
        )
        self.assertIsNotNone(
            access_error(
                enabled=True,
                group_id="",
                sender_id="43",
                group_whitelist=set(),
                private_user_whitelist={"42"},
            )
        )

    def test_exclusive_group_only_allows_sub2api_commands(self) -> None:
        allowed_messages = (
            "/sub2api",
            "/sub2api today",
            "/SUB2API accounts",
            "/sub2 today",
            "/用量 状态",
            "[At:bot-fixture] /sub2api users",
            "[CQ:at,qq=bot-fixture] /sub2api total",
            "@嘟嘟哒 /sub2api models",
        )
        for message in allowed_messages:
            with self.subTest(message=message):
                self.assertTrue(is_sub2api_command(message))
                self.assertFalse(
                    should_block_exclusive_group(
                        group_id="group-fixture",
                        message=message,
                        exclusive_groups={"group-fixture"},
                    )
                )

        blocked_messages = (
            "",
            "普通聊天",
            "/help",
            "/course search 数学分析",
            "帮我执行 /sub2api today",
            "/sub2api_evil",
            "[Poke:123]",
        )
        for message in blocked_messages:
            with self.subTest(message=message):
                self.assertTrue(
                    should_block_exclusive_group(
                        group_id="group-fixture",
                        message=message,
                        exclusive_groups={"group-fixture"},
                    )
                )

        self.assertFalse(
            should_block_exclusive_group(
                group_id="other-group",
                message="普通聊天",
                exclusive_groups={"group-fixture"},
            )
        )

    def test_exclusive_group_uses_original_message_after_wake_prefix_is_removed(
        self,
    ) -> None:
        is_command = is_sub2api_event_command(
            awakened=True,
            current_message="sub2api overview",
            original_message="/sub2api overview",
            message_outline="[At:bot-fixture] /sub2api overview",
        )
        self.assertTrue(is_command)
        self.assertFalse(
            should_block_exclusive_group(
                group_id="group-fixture",
                message="sub2api overview",
                exclusive_groups={"group-fixture"},
                command_allowed=is_command,
            )
        )

        self.assertFalse(
            is_sub2api_event_command(
                awakened=False,
                current_message="@其他人 /sub2api overview",
                original_message="@其他人 /sub2api overview",
                message_outline="[At:123456] /sub2api overview",
            )
        )
        self.assertFalse(
            is_sub2api_event_command(
                awakened=True,
                current_message="普通聊天",
                original_message="普通聊天",
                message_outline="[At:bot-fixture] 普通聊天",
            )
        )

    def test_formatters_use_token_ranking_and_exact_range_stats(self) -> None:
        stats = {
            "today_tokens": 300,
            "today_requests": 3,
            "today_actual_cost": 1.25,
            "today_input_tokens": 100,
            "today_output_tokens": 20,
            "today_cache_creation_tokens": 0,
            "today_cache_read_tokens": 180,
        }
        ranking = {
            "users": [
                {
                    "email": "low@example.invalid",
                    "total_tokens": 100,
                    "requests": 2,
                    "actual_cost": 1,
                },
                {
                    "email": "high@example.invalid",
                    "total_tokens": 200,
                    "requests": 1,
                    "actual_cost": 0.25,
                },
            ]
        }
        rendered = format_today(stats, ranking, reveal_users=False, ranking_limit=10)
        self.assertLess(
            rendered.index("hi***@example.invalid"),
            rendered.index("lo***@example.invalid"),
        )
        self.assertNotIn("high@example.invalid", rendered)

        period = DateRange(
            start=today_in_timezone("Asia/Shanghai"),
            end=today_in_timezone("Asia/Shanghai"),
        )
        range_text = format_range(
            {"trend": [{"date": str(period.start), "total_tokens": 999}], "models": []},
            ranking,
            {"total_tokens": 123, "total_requests": 4, "total_actual_cost": 2},
            period,
            reveal_users=False,
            ranking_limit=10,
            max_trend_rows=10,
            max_model_rows=10,
        )
        self.assertIn("Token：123", range_text)

        history_text = format_overview_history(
            {
                "total_tokens": 500,
                "total_requests": 5,
                "total_actual_cost": 3,
                "total_input_tokens": 200,
                "total_output_tokens": 100,
                "total_cache_creation_tokens": 50,
                "total_cache_read_tokens": 150,
                "average_duration_ms": 1250,
            },
            ranking,
            DateRange(start=date(2026, 7, 13), end=date(2026, 7, 26)),
            reveal_users=False,
            ranking_limit=10,
        )
        self.assertIn("Sub2API 历史累计用量（2026-07-13 至 2026-07-26）", history_text)
        self.assertIn("Token：500", history_text)
        self.assertIn("历史累计 Token 用户排名", history_text)
        self.assertLess(
            history_text.index("hi***@example.invalid"),
            history_text.index("lo***@example.invalid"),
        )

    def test_identifier_masking(self) -> None:
        self.assertEqual(mask_identifier("ab@example.com"), "ab***@example.com")
        self.assertEqual(
            mask_identifier("ab@example.com", reveal=True), "ab@example.com"
        )

    def test_client_source_has_no_business_mutation_methods(self) -> None:
        source_path = (
            ROOT
            / "apps"
            / "astrbot-plugins"
            / "astrbot_plugin_sub2api_readonly"
            / "client.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        methods = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        post_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "post"
        ]
        self.assertFalse({"put", "patch", "delete"} & methods)
        self.assertEqual(len(post_calls), 1)
        self.assertIn("get", methods)

    def test_api_error_does_not_echo_server_message(self) -> None:
        response = httpx.Response(
            200,
            json={
                "code": "UPSTREAM_ERROR",
                "message": "password=value Bearer opaque-value",
                "data": None,
            },
        )
        with self.assertRaises(Sub2APIRequestError) as context:
            Sub2APIClient._decode_response(response, auth=False)
        message = str(context.exception)
        self.assertNotIn("opaque-value", message)
        self.assertNotIn("password=value", message)
        self.assertIn("UPSTREAM_ERROR", message)

    def test_account_status_uses_only_future_recovery_times(self) -> None:
        now = datetime.now(timezone.utc)
        future = (now + timedelta(hours=1)).isoformat()
        past = (now - timedelta(hours=1)).isoformat()
        rendered = format_accounts(
            [
                {
                    "id": 1,
                    "platform": "openai",
                    "type": "oauth",
                    "registration_email": "account@example.invalid",
                    "status": "active",
                    "schedulable": True,
                    "rate_limit_reset_at": future,
                },
                {
                    "id": 2,
                    "platform": "openai",
                    "status": "active",
                    "schedulable": True,
                    "rate_limit_reset_at": past,
                    "temp_unschedulable_until": past,
                    "overload_until": past,
                },
            ],
            show_account_names=False,
            reveal_identifiers=False,
            max_rows=10,
        )
        self.assertIn("上游限流 1", rendered)
        self.assertIn("正常可调度 1", rendered)
        self.assertIn("[openai/oauth]", rendered)
        self.assertIn("注册邮箱 ac***@example.invalid", rendered)
        self.assertNotIn("account@example.invalid", rendered)
        self.assertIn(f"限流重置：{future}", rendered)
        self.assertNotIn(f"暂停至：{past}", rendered)


class Sub2APIClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_and_get_are_cached_and_include_ui_headers(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/auth/login"):
                self.assertEqual(request.method, "POST")
                return login_response()
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.headers["Authorization"], "Bearer unit-token")
            self.assertEqual(request.headers["X-Admin-UI-Request"], "1")
            self.assertEqual(request.url.params["timezone"], "Asia/Shanghai")
            return response({"today_tokens": 12})

        client = self._client(handler)
        try:
            self.assertEqual((await client.get_stats())["today_tokens"], 12)
            self.assertEqual((await client.get_stats())["today_tokens"], 12)
        finally:
            await client.close()
        self.assertEqual([request.method for request in requests], ["POST", "GET"])

    async def test_401_causes_one_bounded_relogin(self) -> None:
        methods: list[str] = []
        get_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal get_count
            methods.append(request.method)
            if request.method == "POST":
                return login_response()
            get_count += 1
            if get_count == 1:
                return httpx.Response(401, json={"code": 401, "message": "expired"})
            return response({"version": "test"})

        client = self._client(handler)
        try:
            self.assertEqual((await client.get_system_version())["version"], "test")
        finally:
            await client.close()
        self.assertEqual(methods, ["POST", "GET", "POST", "GET"])

    async def test_only_sanitized_accounts_are_cached(self) -> None:
        account_gets = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal account_gets
            if request.method == "POST":
                return login_response()
            account_gets += 1
            return response(
                {
                    "items": [
                        {
                            "id": 7,
                            "name": "safe-label",
                            "platform": "openai",
                            "status": "active",
                            "schedulable": True,
                            "error_message": "must-not-survive",
                            "temp_unschedulable_reason": "must-not-survive",
                            "credentials": {
                                "access_token": "must-not-survive",
                                "refresh_token": "must-not-survive",
                                "email": "account@example.invalid",
                            },
                            "extra": {
                                "email": "hidden@example.invalid",
                                "codex_primary_used_percent": 25,
                            },
                            "groups": [
                                {"id": 4, "name": "default", "description": "drop"}
                            ],
                        }
                    ],
                    "page": 1,
                    "pages": 1,
                }
            )

        client = self._client(handler)
        try:
            first = await client.get_accounts()
            second = await client.get_accounts()
        finally:
            await client.close()
        self.assertEqual(account_gets, 1)
        self.assertNotIn("credentials", first[0])
        self.assertNotIn("error_message", first[0])
        self.assertNotIn("temp_unschedulable_reason", first[0])
        self.assertNotIn("email", first[0]["extra"])
        self.assertEqual(first[0]["extra"]["codex_primary_used_percent"], 25)
        self.assertEqual(first[0]["registration_email"], "account@example.invalid")
        self.assertEqual(first[0]["groups"], [{"id": 4, "name": "default"}])
        self.assertEqual(first, second)

    async def test_range_queries_use_token_breakdown_and_exact_stats(self) -> None:
        seen_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return login_response()
            seen_paths.append(request.url.path)
            if request.url.path.endswith("/dashboard/user-breakdown"):
                self.assertEqual(request.url.params["sort_by"], "total_tokens")
                self.assertEqual(request.url.params["limit"], "10")
                return response({"users": []})
            if request.url.path.endswith("/usage/stats"):
                self.assertEqual(request.url.params["start_date"], "2026-07-23")
                self.assertEqual(request.url.params["end_date"], "2026-07-24")
                return response({"total_tokens": 42})
            raise AssertionError(f"unexpected GET: {request.url}")

        client = self._client(handler)
        period = DateRange(
            start=date.fromisoformat("2026-07-23"),
            end=date.fromisoformat("2026-07-24"),
        )
        try:
            ranking, stats = await asyncio.gather(
                client.get_user_ranking(period, limit=10),
                client.get_usage_stats(period),
            )
        finally:
            await client.close()
        self.assertEqual(ranking, {"users": []})
        self.assertEqual(stats["total_tokens"], 42)
        self.assertCountEqual(
            seen_paths,
            [
                "/api/v1/admin/dashboard/user-breakdown",
                "/api/v1/admin/usage/stats",
            ],
        )

    async def test_user_trend_uses_server_side_top_ten(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return login_response()
            self.assertEqual(
                request.url.path, "/api/v1/admin/dashboard/snapshot-v2"
            )
            self.assertEqual(request.url.params["granularity"], "day")
            self.assertEqual(request.url.params["include_trend"], "false")
            self.assertEqual(request.url.params["include_users_trend"], "true")
            self.assertEqual(request.url.params["users_trend_limit"], "10")
            return response({"users_trend": []})

        client = self._client(handler)
        period = DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3))
        try:
            payload = await client.get_user_trend(period, limit=10)
        finally:
            await client.close()
        self.assertEqual(payload, {"users_trend": []})

    async def test_unknown_path_is_rejected_before_network(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        client = self._client(handler)
        try:
            with self.assertRaises(Sub2APIRequestError):
                await client._get("/admin/settings")
        finally:
            await client.close()

    @staticmethod
    def _client(handler) -> Sub2APIClient:
        return Sub2APIClient(
            base_url="https://example.invalid",
            email="admin@example.invalid",
            password="pw",
            cache_ttl_seconds=30,
            transport=httpx.MockTransport(handler),
        )


if __name__ == "__main__":
    unittest.main()
