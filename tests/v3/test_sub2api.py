import asyncio
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from dududa_v3.config import Settings
from dududa_v3.features import sub2api
from dududa_v3.features.base import Ctx, Delegate, Inbound, Sender
from dududa_v3.features.sub2api import charts, client, formatters
from dududa_v3.runtime import Runtime

ROOT = Path(__file__).resolve().parents[2]
BOT = 'qq-10000'
GROUP = BOT + ':group:100'
GROUP2 = BOT + ':group:200'
PRIVATE = BOT + ':private:42'
CONFIG = {'enabled': True, 'base_url': 'https://sub2api.example/api/v1', 'admin_email': 'admin@example.com',
          'admin_password': 'hunter2', 'group_whitelist': ['100'], 'exclusive_groups': ['100'],
          'private_user_whitelist': [], 'cache_ttl_seconds': 0, 'chart_python': '/nonexistent/python'}
STATS = {'total_tokens': 1234567, 'total_requests': 89, 'total_actual_cost': 12.5, 'total_users': 3,
         'active_users': 1, 'stats_updated_at': '2026-10-18T18:22:47Z'}


def inbound(conversation=GROUP, text='/sub2api', user='7', mentioned=False):
    return Inbound(account_id=BOT, conversation_id=conversation, message_id='m', text=text,
                   sender=Sender(id=user), mentioned=mentioned)


def envelope(data, code=0):
    return json.dumps({'code': code, 'message': 'ok', 'data': data}).encode()


class FakeSub2API:
    """Transport double for the admin API; ``expire`` makes the next GET answer 401 once."""

    def __init__(self):
        self.calls = []
        self.logins = 0
        self.expire = False

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers)))
        if url.endswith('/auth/login'):
            self.logins += 1
            return 200, envelope({'access_token': f'tok-{self.logins}', 'expires_in': 3600})
        if self.expire:
            self.expire = False
            return 401, b'{}'
        if headers.get('Authorization') != f'Bearer tok-{self.logins}':
            return 401, b'{}'
        if '/admin/dashboard/stats' in url:
            return 200, envelope(STATS)
        if '/admin/accounts' in url:
            return 200, envelope({'items': [{'id': 3, 'name': 'pro', 'status': 'active', 'schedulable': True,
                                             'credentials': {'email': 'owner@example.com', 'access_token': 'secret'},
                                             'extra': {'codex_7d_used_percent': 40, 'session_cookie': 'secret'}}],
                                  'pages': 1})
        if '/admin/dashboard/snapshot-v2' in url:
            return 200, envelope({'trend': [{'date': '2026-08-01', 'total_tokens': 10}]})
        return 404, b''


class PureLogicTests(unittest.TestCase):
    def test_options_defaults_clamps_and_secret_repr(self):
        options = sub2api.Options.from_config({'enabled': 'yes', 'group_whitelist': '1, 2,', 'ranking_limit': 999,
                                               'cache_ttl_seconds': 'x', 'admin_password': 'hunter2'})
        self.assertTrue(options.enabled)
        self.assertEqual(options.group_whitelist, {'1', '2'})
        self.assertEqual(options.ranking_limit, 100)
        self.assertEqual(options.cache_ttl_seconds, 30)
        self.assertEqual(options.timezone, 'Asia/Shanghai')
        self.assertNotIn('hunter2', repr(options))
        self.assertFalse(sub2api.Options.from_config({}).enabled)

    def test_access_is_default_deny(self):
        options = sub2api.Options.from_config(CONFIG)
        self.assertIsNone(sub2api.access_error(options, inbound(GROUP)))
        self.assertIn('不在 Sub2API 查询白名单', sub2api.access_error(options, inbound(GROUP2)))
        self.assertEqual(sub2api.access_error(options, inbound(PRIVATE, user='42')), 'Sub2API 私聊查询未授权。')
        allowed = sub2api.Options.from_config({**CONFIG, 'private_user_whitelist': ['42']})
        self.assertIsNone(sub2api.access_error(allowed, inbound(PRIVATE, user='42')))
        empty = sub2api.Options.from_config({**CONFIG, 'group_whitelist': []})
        self.assertIn('尚未配置', sub2api.access_error(empty, inbound(GROUP)))
        disabled = sub2api.Options.from_config({**CONFIG, 'enabled': False})
        self.assertIn('已关闭', sub2api.access_error(disabled, inbound(GROUP)))

    @patch.object(client, 'today_in_timezone', return_value=date(2026, 10, 23))
    def test_date_parsing(self, _today):
        period = client.parse_date_range('2026-08-20', '2026-08-26', timezone='Asia/Shanghai', max_days=90)
        self.assertEqual(period.days, 7)
        self.assertEqual(period.as_params(), {'start_date': '2026-08-20', 'end_date': '2026-08-26'})
        for start, end, message in (('2026-08-26', '2026-08-20', '不能晚于结束'), ('08-20', '2026-08-26', '格式'),
                                    ('2026-01-01', '2026-08-26', '最多允许 90 天'),
                                    ('2026-10-24', '2026-10-24', '不能晚于今天')):
            with self.assertRaisesRegex(client.Sub2APIConfigError, message):
                client.parse_date_range(start, end, timezone='Asia/Shanghai', max_days=90)
        trend, cumulative = client.parse_user_trend_request('sum', '30d', timezone='Asia/Shanghai', max_days=90)
        self.assertTrue(cumulative)
        self.assertEqual(trend.days, 30)
        self.assertEqual(client.parse_user_trend_request(None, None, timezone='Asia/Shanghai', max_days=90)[0].days, 7)
        with self.assertRaises(client.Sub2APIConfigError):
            client.parse_user_trend_request('7d', '30d', timezone='Asia/Shanghai', max_days=90)
        with self.assertRaisesRegex(client.Sub2APIConfigError, '最多允许查询 90'):
            client.parse_trend_period('91d', timezone='Asia/Shanghai', max_days=90)
        with self.assertRaises(client.Sub2APIConfigError):
            client.parse_trend_period('7', timezone='Asia/Shanghai', max_days=90)

    def test_base_url_normalization(self):
        self.assertEqual(client.normalize_base_url('https://gpt.example/api/v1/'), 'https://gpt.example')
        self.assertEqual(client.normalize_base_url('https://gpt.example/admin/dashboard'), 'https://gpt.example')
        for bad in ('http://gpt.example', 'https://u:p@gpt.example', 'https://gpt.example/?a=1', ''):
            with self.assertRaises(client.Sub2APIConfigError):
                client.normalize_base_url(bad)

    def test_sanitize_account_drops_credentials(self):
        account = client.sanitize_account({
            'id': 5, 'name': 'a', 'status': 'active',
            'credentials': {'email': 'reg@example.com', 'refresh_token': 'SECRET-R'},
            'extra': {'codex_7d_used_percent': 12, 'cookie': 'SECRET-C'},
            'groups': [{'id': 1, 'name': 'g', 'secret': 'SECRET-G'}]})
        self.assertEqual(account['registration_email'], 'reg@example.com')
        self.assertEqual(account['extra'], {'codex_7d_used_percent': 12})
        self.assertEqual(account['groups'], [{'id': 1, 'name': 'g'}])
        self.assertNotIn('credentials', account)
        self.assertNotIn('SECRET', json.dumps(account))

    def test_decode_response_rules(self):
        self.assertEqual(client.decode_response(200, envelope({'a': 1}), auth=False), {'a': 1})
        cases = ((302, b'', client.Sub2APIRequestError, '重定向'), (401, b'', client.Sub2APIAuthError, '已失效'),
                 (403, b'', client.Sub2APIAuthError, '无权'), (500, b'', client.Sub2APIRequestError, 'HTTP 500'),
                 (200, b'<html>', client.Sub2APIRequestError, '非 JSON'),
                 (200, envelope(None, code='E<script>'), client.Sub2APIRequestError, r'业务错误（Escript）'),
                 (200, b'{"code": 0}', client.Sub2APIRequestError, '缺少 data'))
        for status, body, error, message in cases:
            with self.assertRaisesRegex(error, message):
                client.decode_response(status, body, auth=False)
        with self.assertRaisesRegex(client.Sub2APIAuthError, '账号或密码错误'):
            client.decode_response(401, b'', auth=True)

    def test_subtract_usage_trims_boundary_rows(self):
        stats = {'total_tokens': 1000, 'total_requests': 4, 'total_actual_cost': 4.0, 'total_input_tokens': 600,
                 'total_cache_read_tokens': 400, 'average_duration_ms': 100}
        ranking = {'users': [{'user_id': 1, 'total_tokens': 700, 'requests': 3, 'actual_cost': 3.0},
                             {'user_id': 2, 'total_tokens': 300, 'requests': 1, 'actual_cost': 1.0}]}
        excluded = [{'user_id': 1, 'input_tokens': 500, 'cache_read_tokens': 100, 'actual_cost': 2.5,
                     'duration_ms': 200}]
        result = client.subtract_usage(stats, ranking, excluded, limit=10)
        self.assertEqual((result['total_tokens'], result['total_requests']), (400, 3))
        self.assertAlmostEqual(result['total_actual_cost'], 1.5)
        self.assertEqual((result['total_input_tokens'], result['total_cache_read_tokens']), (100, 300))
        self.assertAlmostEqual(result['average_duration_ms'], 200 / 3)
        self.assertEqual([row['user_id'] for row in result['users']], [2, 1])
        self.assertEqual(result['users'][1]['total_tokens'], 100)

    def test_fallback_cost_overview_picks_latest_used_account(self):
        now = datetime.now(timezone.utc)
        accounts = [
            {'id': 1, 'platform': 'openai', 'status': 'active', 'last_used_at': (now - timedelta(hours=5)).isoformat(),
             'extra': {'codex_7d_used_percent': 50, 'codex_7d_reset_at': (now + timedelta(days=2)).isoformat()}},
            {'id': 2, 'platform': 'openai', 'status': 'active', 'last_used_at': (now - timedelta(hours=1)).isoformat(),
             'extra': {'codex_7d_used_percent': 20, 'codex_7d_reset_at': (now + timedelta(days=6)).isoformat(),
                       'codex_7d_window_minutes': 7 * 24 * 60}},
            {'id': 3, 'platform': 'openai', 'status': 'active',
             'extra': {'codex_7d_used_percent': 90, 'codex_7d_reset_at': (now - timedelta(days=1)).isoformat()}},
        ]
        overview = client.fallback_cost_overview(accounts, timezone='Asia/Shanghai')
        self.assertEqual(overview['period_start'], client.CURRENT_BILLING_PERIOD_START)
        self.assertEqual(overview['pro_estimate']['account_id'], 2)
        self.assertIsNone(client.fallback_cost_overview([], timezone='Asia/Shanghai')['pro_estimate'])


class FormatterTests(unittest.TestCase):
    def test_mask_identifier(self):
        self.assertEqual(formatters.mask_identifier('alice@example.com'), 'al***@example.com')
        self.assertEqual(formatters.mask_identifier('bob'), 'b***')
        self.assertEqual(formatters.mask_identifier('carolina'), 'ca***a')
        self.assertEqual(formatters.mask_identifier('alice@example.com', reveal=True), 'alice@example.com')
        self.assertEqual(formatters.mask_identifier(''), '未知用户')

    def test_format_today_ranks_and_redacts_tokens(self):
        stats = {'today_tokens': 1000, 'today_requests': 5, 'today_actual_cost': 1.23456,
                 'stats_updated_at': 'Bearer abc.def'}
        ranking = {'users': [{'user_id': 1, 'email': 'low@example.com', 'total_tokens': 250, 'requests': 1},
                             {'user_id': 2, 'email': 'high@example.com', 'total_tokens': 750, 'requests': 4}]}
        text = formatters.format_today(stats, ranking, reveal_users=False, ranking_limit=10)
        self.assertIn('Token：1,000', text)
        self.assertIn('费用：$1.2346', text)
        self.assertLess(text.index('hi***@example.com - 750 (75.0%)'), text.index('lo***@example.com - 250 (25.0%)'))
        self.assertIn('Bearer [redacted]', text)
        self.assertNotIn('abc.def', text)

    def test_format_accounts_states(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        rows = [{'id': 2, 'status': 'active', 'schedulable': True, 'name': 'pro', 'concurrency': 3,
                 'current_concurrency': 1, 'registration_email': 'owner@example.com'},
                {'id': 1, 'status': 'active', 'schedulable': True, 'rate_limit_reset_at': future},
                {'id': 3, 'status': 'error'}]
        text = formatters.format_accounts(rows, show_account_names=False, reveal_identifiers=False, max_rows=2)
        self.assertIn('总数：3；error 1；上游限流 1；正常可调度 1', text)
        self.assertIn('- #2 [unknown/unknown]：正常可调度，并发 1/3；注册邮箱 ow***@example.com', text)
        self.assertIn('上游限流', text.splitlines()[3])
        self.assertIn('另有 1 个账号未展开。', text)
        self.assertNotIn('pro', text)

    def test_text_trend_fallbacks(self):
        period = client.DateRange(date(2026, 8, 1), date(2026, 8, 3))
        snapshot = {'trend': [{'date': '2026-08-01', 'total_tokens': 10}, {'date': '2026-08-03', 'total_tokens': 30}]}
        text = formatters.format_total_trend_text(snapshot, period, max_rows=2)
        self.assertIn('合计：40；日均：13', text)
        self.assertIn('峰值：2026-08-03 30', text)
        self.assertIn('08-02：0\n08-03：30\n另有 1 天已计入合计', text)
        users = {'users_trend': [{'date': '2026-08-01', 'user_id': 1, 'email': 'alice@example.com', 'tokens': 5},
                                 {'date': '2026-08-03', 'user_id': 1, 'email': 'alice@example.com', 'tokens': 7}]}
        self.assertIn('1. al***@example.com - 12 Token（最后一天 7）',
                      formatters.format_user_trend_text(users, period, reveal_identifiers=False, cumulative=False))


class ChartSeriesTests(unittest.TestCase):
    def test_series_fill_missing_days_and_rank_users(self):
        period = client.DateRange(date(2026, 8, 1), date(2026, 8, 3))
        snapshot = {'trend': [{'date': '2026-08-01', 'total_tokens': 10}, {'date': '2026-09-01', 'total_tokens': 99}]}
        self.assertEqual([value for _, value in charts.trend_points(snapshot, period)], [10, 0, 0])
        rows = {'users_trend': [
            {'date': '2026-08-01', 'user_id': 1, 'username': '小明', 'email': 'ming@example.com', 'tokens': 5},
            {'date': '2026-08-02', 'user_id': 2, 'username': 'bob', 'tokens': 9},
            {'date': '2026-08-03', 'user_id': 1, 'username': '小明', 'email': 'ming@example.com', 'tokens': 6}]}
        series = charts.user_trend_series(rows, period, reveal_identifiers=True)
        self.assertEqual([(item.label, item.total, item.values) for item in series],
                         [('ming@example.com', 11, (5, 0, 6)), ('bob', 9, (0, 9, 0))])
        self.assertEqual(charts.cumulative_user_series(series)[0].values, (5, 5, 11))

    def test_smooth_curve_keeps_endpoints(self):
        points = [(0, 100), (10, 50), (20, 80), (30, 0)]
        curve = charts.smooth_curve(points)
        self.assertEqual((curve[0], curve[-1]), (points[0], points[-1]))
        self.assertTrue(all(0 <= y <= 100 for _, y in curve))
        self.assertEqual(charts.sqrt_axis_bounds([0, 0])[0], 0.0)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_once_reauth_on_401_and_read_only_paths(self):
        fake = FakeSub2API()
        api = client.Sub2APIClient(base_url='https://sub2api.example', email='a@example.com', password='pw',
                                   transport=fake, cache_ttl_seconds=30)
        self.assertEqual(await api.get_stats(), STATS)
        self.assertEqual(await api.get_stats(), STATS)  # cached
        self.assertEqual(fake.logins, 1)
        login = fake.calls[0]
        self.assertEqual((login[0], login[1]), ('POST', 'https://sub2api.example/api/v1/auth/login'))
        self.assertIn('timezone=Asia%2FShanghai', fake.calls[1][1])
        fake.expire = True
        api._cache.clear()
        self.assertEqual(await api.get_stats(), STATS)
        self.assertEqual(fake.logins, 2)
        self.assertTrue(all(method == 'GET' for method, url, _ in fake.calls if not url.endswith('/auth/login')))
        with self.assertRaisesRegex(client.Sub2APIRequestError, '只读白名单'):
            await api._get('/admin/accounts/1/refresh')
        accounts = await api.get_accounts()
        self.assertEqual(accounts[0]['registration_email'], 'owner@example.com')
        self.assertNotIn('secret', json.dumps(accounts))

    async def test_transport_failure_is_user_presentable(self):
        def broken(*args):
            raise client.TransportError('URLError')

        api = client.Sub2APIClient(base_url='https://sub2api.example', email='a@example.com', password='pw',
                                   transport=broken)
        with self.assertRaisesRegex(client.Sub2APIAuthError, '无法连接 Sub2API 登录接口'):
            await api.get_stats()
        with self.assertRaisesRegex(client.Sub2APIRequestError, '费用分摊网站'):
            await api.get_cost_overview()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent_calls = 0
        self.settings = Settings(root=ROOT, state_dir=Path(self.tmp.name),
                                 allowed_scopes=(f'{BOT}/{GROUP}', f'{BOT}/{GROUP2}', f'{BOT}/{PRIVATE}'),
                                 features={'sub2api': dict(CONFIG)})
        self.fake = FakeSub2API()
        sub2api._clients.clear()
        patcher = patch.object(sub2api, 'urllib_transport', lambda **kwargs: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = Runtime(self.settings, client_factory=self.no_agent)

    async def asyncTearDown(self):
        await self.runtime.close()
        sub2api._clients.clear()
        self.tmp.cleanup()

    def no_agent(self, **config):
        self.agent_calls += 1
        raise AssertionError('agent must not run')

    async def send(self, text, conversation=GROUP, mentioned=False):
        run = await self.runtime.submit({'account_id': BOT, 'conversation_id': conversation, 'user_id': '7',
                                         'message_id': f'm-{asyncio.get_running_loop().time()}', 'text': text,
                                         'source': 'qq', 'mentioned': mentioned})
        return await self.runtime.wait(run['run_id'])

    async def test_commands_and_exclusive_gate(self):
        total = await self.send('/sub2api total')
        self.assertEqual(total['status'], 'completed')
        self.assertIn('总 Token：1,234,567', total['text'])
        glued = await self.send('嘟嘟哒 用量累计')
        self.assertIn('总 Token：1,234,567', glued['text'])
        usage = await self.send('/sub2api account x')
        self.assertEqual(usage['text'], '账号 ID 必须是正整数。')
        self.assertIn('/sub2api overview', (await self.send('/用量'))['text'])
        self.assertIn('未知的 Sub2API 子命令「天气」', (await self.send('嘟嘟哒 用量 天气'))['text'])
        # Exclusive group: everything else is dropped before routing, agent included.
        for text, mentioned in (('你好', True), ('嘟嘟哒 help', False), ('/ping', False), ('随便聊聊', False)):
            dropped = await self.send(text, mentioned=mentioned)
            self.assertEqual((dropped['status'], dropped['reason']), ('ignored', 'gate:sub2api'), text)
        self.assertEqual(self.agent_calls, 0)
        # Other groups: explicit commands stay silent, other features keep working.
        silent = await self.send('/sub2api total', conversation=GROUP2)
        self.assertEqual((silent['status'], silent['reason']), ('ignored', 'no_reply'))
        self.assertEqual((await self.send('/ping', conversation=GROUP2))['status'], 'completed')
        private = await self.send('/sub2api total', conversation=PRIVATE)
        self.assertEqual(private['text'], 'Sub2API 私聊查询未授权。')

    async def test_task_off_disables_gate_and_command(self):
        self.runtime.store.set_switch(sub2api.TASK, False, 'admin')
        ping = await self.send('/ping')
        self.assertEqual(ping['status'], 'completed')
        off = await self.send('/sub2api total')
        self.assertEqual((off['status'], off['reason']), ('ignored', 'task_disabled'))

    async def test_text_fallback_without_chart_interpreter(self):
        trend = await self.send('/sub2api trendtotal 3d')
        self.assertEqual(trend['status'], 'completed')
        self.assertIn('Sub2API 总 Token 趋势', trend['text'])

    async def test_named_chat_outside_whitelist_goes_to_agent(self):
        def ctx(conversation, text, args):
            return Ctx(runtime=self.runtime, inbound=inbound(conversation, text), session_id=0, run_id='r', args=args)

        self.assertEqual(await sub2api.sub2api_command(ctx(GROUP2, '嘟嘟哒 用量是多少', '是多少')),
                         Delegate('用量是多少'))
        self.assertIsNone(await sub2api.sub2api_command(ctx(GROUP2, '/用量 today', 'today')))
        # Whitelisted but non-exclusive group: unknown sub-commands addressed by name are chat.
        self.settings.features['sub2api'] = {**CONFIG, 'exclusive_groups': []}
        self.assertEqual(await sub2api.sub2api_command(ctx(GROUP, '嘟嘟哒 用量怎么算', '怎么算')),
                         Delegate('用量怎么算'))


if __name__ == '__main__':
    unittest.main()
