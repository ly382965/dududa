"""V3 shared-service and native MCP tests; never import a legacy runtime."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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

    def test_mcp_has_no_memory_write_or_admin_tools(self):
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
        self.settings.campus_capabilities = ('public', 'sensitive', 'private-only', 'offline')
        return calls

    def test_console_catalog_and_invocation_enforce_public_allowlist(self):
        calls = self.console()
        result = self.hub.call('services_list')
        self.assertEqual({item['id'] for item in result['campus_capabilities']}, {'public', 'offline'})
        result = self.hub.call('campus_query', {'capability_id': 'public', 'arguments': {'query': '线性代数'}})
        self.assertTrue(result['ok'])
        self.assertEqual(calls[-1], ('POST', '/v1/invoke', {
            'capabilityId': 'public', 'arguments': {'query': '线性代数'},
        }))
        for denied in ('sensitive', 'private-only', 'unlisted', 'offline'):
            with self.assertRaises(ServiceError):
                self.hub.call('campus_query', {'capability_id': denied})
        self.assertEqual(sum(method == 'POST' for method, _, _ in calls), 1)

    def test_private_chat_still_cannot_invoke_sensitive_capability(self):
        calls = self.console()
        private = self.store.session(json.dumps(['bot', 'qq:bot:private:alice', 'qq']))
        hub = ServiceHub(self.settings, self.store, private['id'], self.run['run_id'])
        self.assertEqual(hub.context, 'private')
        with self.assertRaises(ServiceError):
            hub.call('campus_query', {'capability_id': 'sensitive'})
        self.assertFalse(any(method == 'POST' for method, _, _ in calls))

    def test_native_mcp_process_serves_only_protocol_on_stdout(self):
        self.store.remember(self.session['id'], 'alice', 'MCP 专用记忆')
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'memory_search', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'remember', 'arguments': {'text': 'write'}}},
        ]
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'packages/dududa-runtime/src'))
        process = subprocess.run(
            [sys.executable, '-m', 'dududa_v3.mcp', '--root', str(ROOT),
             '--database', str(self.settings.database), '--session-id', str(self.session['id']),
             '--run-id', self.run['run_id']],
            input='\n'.join(json.dumps(message) for message in messages) + '\n',
            text=True, capture_output=True, timeout=5, env=env, check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, '')
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([response['id'] for response in responses], [1, 2, 3, 4])
        self.assertEqual(responses[0]['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(len(responses[1]['result']['tools']), 6)
        self.assertFalse(responses[2]['result']['isError'])
        data = json.loads(responses[2]['result']['content'][0]['text'])
        self.assertEqual(data['items'][0]['text'], 'MCP 专用记忆')
        self.assertTrue(responses[3]['result']['isError'])
        self.assertIn('error', json.loads(responses[3]['result']['content'][0]['text']))
        self.assertEqual(self.store.tools(self.run['run_id']), ['memory_search'])

    def test_qq_history_pages_to_1000_and_rejects_other_scopes(self):
        paths = []
        crossed = []
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
                             'timestampMs': 1792108700000 + i * 1000}
                            for i in range(first, end)]
                if first == 1:
                    messages[0].update(status='recalled', content='不能泄漏的撤回内容')
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'messages': messages, 'beforeCursor': str(first),
                                            'hasMoreBefore': first > 1}).encode())
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


if __name__ == '__main__':
    unittest.main()
