"""V3 shared-service tests (Host tools); never import a legacy runtime."""

import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from dududa_v3.config import Settings
from dududa_v3.services import ServiceError, ServiceHub
from dududa_v3.store import Store

ROOT = Path(__file__).resolve().parents[2]


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(root=ROOT, state_dir=Path(self.directory.name))
        self.store = Store(self.settings.database)
        self.session = self.store.session(json.dumps(['bot', 'qq:bot:group:1', 'qq']))
        self.other = self.store.session(json.dumps(['bot', 'qq:bot:group:2', 'qq']))
        self.run, _ = self.store.create_run(self.session['id'], {'message_id': 'msg-1'})
        self.hub = ServiceHub(self.settings, self.store, self.session['id'], self.run['run_id'])

    def test_shuttle_uses_extracted_business_service(self):
        result = self.hub.call('shuttle_query', {'query': '工作日东区到西区最早一班'})
        self.assertTrue(result['ok'])
        self.assertTrue(result['matched'])
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['origin'], '东区')
        self.assertEqual(result['items'][0]['destination'], '西区')
        self.assertIn('dataset_id', result['source'])
        self.assertEqual(self.store.tools(self.run['run_id']), ['shuttle_query'])

    def test_memory_and_context_are_bound_to_launch_scope(self):
        self.store.remember(self.session['id'], 'alice', '当前群偏好绿茶')
        self.store.remember(self.other['id'], 'bob', '其他群私有记忆')
        self.store.observe(self.session['id'], 'alice', '当前聊天')
        self.store.observe(self.other['id'], 'bob', '其他聊天')
        memories = self.hub.call('memory_search', {'query': '绿茶'})
        recent = self.hub.call('context_recent', {})
        self.assertEqual([row['text'] for row in memories['items']], ['当前群偏好绿茶'])
        self.assertEqual([row['text'] for row in recent['items']], ['当前聊天'])
        with self.assertRaises(ServiceError):
            self.hub.call('memory_search', {'query': '', 'session_id': self.other['id']})
        self.assertEqual(self.store.tools(self.run['run_id']), ['memory_search', 'context_recent'])
        self.hub.call('memory_search', {}, record=False)
        self.assertEqual(self.store.tools(self.run['run_id']), ['memory_search', 'context_recent'])

    def test_host_tools_have_no_memory_write_or_admin_tools(self):
        definitions = self.hub.tool_definitions()
        self.assertEqual({item['name'] for item in definitions}, {
            'shuttle_query', 'memory_search', 'context_recent', 'conversation_history', 'services_list', 'campus_query',
        })
        self.assertTrue(all(item['annotations']['readOnlyHint'] for item in definitions))
        with self.assertRaises(ServiceError):
            self.hub.call('memory_write', {'text': 'injected'})
        with self.assertRaises(ServiceError):
            self.hub.call('context_recent', {'limit': True})

    def test_unconfigured_console_has_clear_error(self):
        result = self.hub.call('services_list')
        self.assertFalse(result['campus_configured'])
        with self.assertRaisesRegex(ServiceError, '未配置'):
            self.hub.call('campus_query', {'capability_id': 'courses'})

    def console(self):
        calls = []
        capabilities = [
            {'id': 'public', 'name': '公开课程', 'privacy': 'public', 'allowedContexts': ['group', 'private'], 'available': True},
            {'id': 'sensitive', 'name': '私人课表', 'privacy': 'private', 'allowedContexts': ['group', 'private'], 'available': True},
            {'id': 'private-only', 'name': '仅私聊', 'privacy': 'public', 'allowedContexts': ['private'], 'available': True},
            {'id': 'unlisted', 'name': '未启用', 'privacy': 'public', 'allowedContexts': ['group'], 'available': True},
            {'id': 'campus', 'name': '校园会话能力', 'privacy': 'conversation', 'allowedContexts': ['group'], 'available': True},
            {'id': 'offline', 'name': '离线能力', 'privacy': 'public', 'allowedContexts': ['group'], 'available': False},
        ]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(('GET', self.path, None))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'capabilities': capabilities}).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(('POST', self.path, body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'result': {'title': '线性代数'}}).encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def close():
            server.shutdown()
            server.server_close()
            thread.join()

        self.addCleanup(close)
        self.settings.mcp_console_url = f'http://127.0.0.1:{server.server_port}'
        self.settings.campus_capabilities = ('public', 'campus', 'sensitive', 'private-only', 'offline')
        return calls

    def test_console_catalog_and_invocation_enforce_public_allowlist(self):
        calls = self.console()
        # The local Console is never reached through the outbound proxy from the environment.
        dead_proxy = {name: 'http://127.0.0.1:9' for name in ('http_proxy', 'HTTP_PROXY', 'https_proxy', 'HTTPS_PROXY')}
        with patch.dict(os.environ, {**dead_proxy, 'no_proxy': '', 'NO_PROXY': ''}):
            result = self.hub.call('services_list')
            self.assertEqual({item['id'] for item in result['campus_capabilities']}, {'public', 'campus', 'offline'})
            result = self.hub.call('campus_query', {'capability_id': 'public', 'arguments': {'query': '线性代数'}})
            self.assertTrue(result['ok'])
            self.assertEqual(calls[-1], ('POST', '/v1/invoke', {
                'capabilityId': 'public', 'arguments': {'query': '线性代数'},
            }))
            self.assertTrue(self.hub.call('campus_query', {'capability_id': 'campus'})['ok'])
            for denied in ('sensitive', 'private-only', 'unlisted', 'offline'):
                with self.assertRaises(ServiceError):
                    self.hub.call('campus_query', {'capability_id': denied})
        self.assertEqual(sum(method == 'POST' for method, _, _ in calls), 2)

    def test_private_chat_still_cannot_invoke_sensitive_capability(self):
        calls = self.console()
        private = self.store.session(json.dumps(['bot', 'qq:bot:private:alice', 'qq']))
        hub = ServiceHub(self.settings, self.store, private['id'], self.run['run_id'])
        self.assertEqual(hub.context, 'private')
        with self.assertRaises(ServiceError):
            hub.call('campus_query', {'capability_id': 'sensitive'})
        self.assertFalse(any(method == 'POST' for method, _, _ in calls))

    def test_qq_history_pages_to_1000_and_rejects_other_scopes(self):
        paths = []
        crossed = []
        base_time = int((time.time() - 1800) * 1000)
        session = self.store.session(json.dumps(['qq-123', 'qq-123:group:456', 'qq']))
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                query = parse_qs(urlsplit(self.path).query)
                end = int(query.get('before', ['1001'])[0])
                first = max(1, end - int(query['limit'][0]))
                messages = [{'accountId': 'other' if crossed else 'qq-123', 'conversationId': 'qq-123:group:456',
                             'messageId': str(i), 'senderId': '789', 'senderName': '测试用户',
                             'content': f'历史消息{i}', 'timestamp': '00:01' if i > 500 else '23:59',
                             'timestampMs': base_time + i * 1000}
                            for i in range(first, end)]
                if first == 1:
                    messages[0].update(status='recalled', content='不能泄漏的撤回内容')
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'messages': messages, 'beforeCursor': str(first),
                                            'hasMoreBefore': False}).encode())  # Simulate a false-negative boundary probe.
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.settings.qq_gateway_url = f'http://127.0.0.1:{server.server_port}'
        hub = ServiceHub(self.settings, self.store, session['id'], self.run['run_id'])
        result = hub.call('conversation_history', {'limit': 1000})
        self.assertEqual(result['returned'], 1000)
        self.assertEqual(len(paths), 10)
        self.assertFalse(result['truncated'])
        self.assertTrue(all(path.startswith('/api/accounts/qq-123/conversations/group/456/messages?') for path in paths))
        self.assertEqual(result['messages'][0]['content'], '[已撤回]')
        self.assertEqual(result['messages'][0]['id'], '1')
        self.assertEqual(result['messages'][-1]['id'], '1000')
        self.assertIn('T', result['oldest_at'])
        self.assertEqual(self.store.get(self.run['run_id'])['history_queries'][-1]['returned'], 1000)
        for args in ({'limit': 1001}, {'limit': True}, {'limit': 10, 'account_id': 'other'}):
            with self.assertRaises(ServiceError): hub.call('conversation_history', args)
        crossed.append(True)
        with self.assertRaisesRegex(ServiceError, '范围不一致'):
            hub.call('conversation_history', {'limit': 1})

    def test_history_defaults_to_three_hours_and_supports_today_and_five_hours(self):
        fixed = datetime(2026, 10, 16, 7, 0, tzinfo=timezone.utc)  # 15:00 Beijing
        times = ['2026-10-15T23:30:00+08:00', '2026-10-16T00:30:00+08:00',
                 '2026-10-16T10:30:00+08:00', '2026-10-16T12:30:00+08:00', '2026-10-16T14:30:00+08:00']
        messages = [{'accountId': 'qq-123', 'conversationId': 'qq-123:group:456', 'messageId': str(i),
                     'content': f'消息{i}', 'timestampMs': datetime.fromisoformat(at).timestamp() * 1000}
                    for i, at in enumerate(times)]
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.astimezone(tz)
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                count = int(parse_qs(urlsplit(self.path).query)['limit'][0])
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'messages': messages[-count:], 'beforeCursor': 'older',
                                            'hasMoreBefore': len(messages) > count}).encode())
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        self.settings.qq_gateway_url = f'http://127.0.0.1:{server.server_port}'
        session = self.store.session(json.dumps(['qq-123', 'qq-123:group:456', 'qq']))
        hub = ServiceHub(self.settings, self.store, session['id'], self.run['run_id'])
        with patch('dududa_v3.services.datetime', Clock):
            recent = hub.call('conversation_history', {})
            self.assertEqual(recent['returned'], 2)
            self.assertEqual(recent['hours'], 3)
            self.assertEqual(recent['window_start'], '2026-10-16T12:00:00+08:00')
            self.assertFalse(recent['limit_reached'])
            five = hub.call('conversation_history', {'hours': 5})
            self.assertEqual(five['returned'], 3)
            self.assertEqual(five['window_start'], '2026-10-16T10:00:00+08:00')
            today = hub.call('conversation_history', {'period': 'today'})
            self.assertEqual(today['returned'], 4)
            self.assertEqual(today['window_start'], '2026-10-16T00:00:00+08:00')
            capped = hub.call('conversation_history', {'period': 'today', 'limit': 2})
            self.assertEqual(capped['returned'], 2)
            self.assertTrue(capped['limit_reached'])
            for invalid in ({'hours': 0}, {'hours': True}, {'hours': 200}, {'period': 'today', 'hours': 5}):
                with self.assertRaises(ServiceError): hub.call('conversation_history', invalid)
            for prompt, expected_period, expected_hours, count in (
                ('总结群聊', 'recent', 3, 2), ('总结今日消息', 'today', None, 4),
                ('总结近5h消息', 'recent', 5, 3), ('请总结近5小时消息', 'recent', 5, 3),
                ('近5h消息', 'recent', 5, 3),
                ('请把今日群聊消息总结一下', 'today', None, 4),
            ):
                run, _ = self.store.create_run(session['id'], {'message_id': prompt, 'text': prompt})
                bound = ServiceHub(self.settings, self.store, session['id'], run['run_id'])
                actual = bound.call('conversation_history', {'hours': 3})
                self.assertEqual((actual['period'], actual['hours'], actual['returned']),
                                 (expected_period, expected_hours, count))
                self.assertEqual(actual['window_source'], 'user_prompt_rule')

    def test_history_marks_bot_messages_and_reply_targets(self):
        now_ms = int(time.time() * 1000)
        messages = [
            {'accountId': 'qq-123', 'conversationId': 'qq-123:group:456', 'messageId': 'a', 'senderId': '789',
             'senderName': '小红', 'content': '问个问题', 'timestampMs': now_ms - 60000},
            {'accountId': 'qq-123', 'conversationId': 'qq-123:group:456', 'messageId': 'b', 'senderId': '123',
             'senderName': '嘟嘟哒', 'content': '机器人回答', 'timestampMs': now_ms - 50000,
             'segments': [{'type': 'reply', 'messageId': 'a', 'senderId': '789', 'senderName': '小红'},
                          {'type': 'text', 'text': '机器人回答'}]},
            {'accountId': 'qq-123', 'conversationId': 'qq-123:group:456', 'messageId': 'c', 'senderId': '790',
             'senderName': '小蓝', 'content': '引用但无发送者', 'timestampMs': now_ms - 40000,
             'segments': [{'type': 'reply', 'messageId': 'zz'}]},
        ]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'messages': messages, 'beforeCursor': None,
                                            'hasMoreBefore': False}).encode())
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        self.settings.qq_gateway_url = f'http://127.0.0.1:{server.server_port}'
        session = self.store.session(json.dumps(['qq-123', 'qq-123:group:456', 'qq']))
        hub = ServiceHub(self.settings, self.store, session['id'], self.run['run_id'])
        result = {item['id']: item for item in hub.call('conversation_history', {})['messages']}
        self.assertEqual(list(result), ['a', 'b', 'c'])
        self.assertNotIn('isBot', result['a'])
        self.assertNotIn('replyTo', result['a'])
        self.assertTrue(result['b']['isBot'])
        self.assertEqual(result['b']['replyTo'], {'senderId': '789', 'senderName': '小红'})
        self.assertNotIn('isBot', result['c'])
        self.assertNotIn('replyTo', result['c'])


if __name__ == '__main__':
    unittest.main()
