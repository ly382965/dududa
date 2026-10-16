"""Exercise the real V3 Host; only the external Codex protocol is substituted."""

import asyncio
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dududa_v3 import SESSION_PROFILE
from dududa_v3.__main__ import state_lock
from dududa_v3.config import Settings
from dududa_v3.runtime import Runtime
from dududa_v3.server import create_server

ROOT = Path(__file__).resolve().parents[2]


class CodexProtocolDouble:
    def __init__(self):
        self.instances = []
        self.calls = []
        self.started = asyncio.Queue()
        self.release = asyncio.Event()
        self.release.set()
        self.active = 0
        self.max_active = 0
        self.fail = False

    def __call__(self, **config):
        owner = self

        class Client:
            closed = False
            cancelled = False

            async def run(self, text, thread_id=None, instructions='', on_event=None, skills=()):
                owner.calls.append({'text': text, 'thread_id': thread_id, 'config': config, 'skills': skills})
                if owner.fail:
                    raise RuntimeError('resume unavailable')
                result_thread = thread_id or f'thread-{len(owner.calls)}'
                turn = f'turn-{len(owner.calls)}'
                owner.active += 1
                owner.max_active = max(owner.max_active, owner.active)
                try:
                    if on_event:
                        await on_event({'method': 'thread/started', 'params': {'thread': {'id': result_thread}}})
                        await on_event({'method': 'turn/started', 'params': {'threadId': result_thread, 'turn': {'id': turn}}})
                    owner.started.put_nowait(self)
                    await owner.release.wait()
                    return SimpleNamespace(thread_id=result_thread, turn_id=turn, text='protocol response',
                                           model='protocol-double', tool_calls=[], status='completed')
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
                finally:
                    owner.active -= 1

            async def close(self):
                self.closed = True

        client = Client()
        self.instances.append(client)
        return client


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {'CODEX_HOME': str(self.state / 'empty-codex')})
        self.environment.start()
        self.settings = Settings(root=ROOT, state_dir=self.state,
                                 allowed_scopes=('bot/qq:bot:group:1', 'bot/qq:bot:group:2'),
                                 rules=({'match': '规则问候', 'reply': '规则回答'},))
        self.protocol = CodexProtocolDouble()
        self.runtime = Runtime(self.settings, client_factory=self.protocol)
        self.sequence = 0

    async def asyncTearDown(self):
        await self.runtime.close()
        self.environment.stop()
        self.directory.cleanup()

    def request(self, text='hello', **changes):
        self.sequence += 1
        return dict(account_id='bot', conversation_id='qq:bot:group:1', user_id='alice',
                    message_id=f'msg-{self.sequence}', text=text, source='qq', mentioned=True, **changes)

    async def execute(self, text='hello', **changes):
        request = self.request(text)
        request.update(changes)
        run = await self.runtime.submit(request)
        return await self.runtime.wait(run['run_id'])

    def session_for(self, request):
        return self.runtime.store.session(json.dumps([
            request['account_id'], request['conversation_id'],
            'preview:' + request['user_id'] if request.get('preview') else request.get('source', 'qq'),
        ], ensure_ascii=False))

    async def test_rules_never_construct_codex(self):
        for text in ('/ping', '/help', '/status', '规则问候', '/校车 工作日东区到西区最早一班'):
            result = await self.execute(text)
            self.assertEqual(result['runtime'], 'dududa-3.0')
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['route'], 'rule')
            self.assertEqual(result['model'], 'rules')
            self.assertTrue(result['text'])
        self.assertEqual(self.protocol.instances, [])

    async def test_summary_skill_is_injected_only_for_summary_turns(self):
        for prompt in ('总结群聊', '总结今日消息', '近5h消息', '帮我总结一下', '请把群聊消息总结一下'):
            result = await self.execute(prompt)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['response_kind'], 'conversation_summary')
            self.assertEqual(result['skills'], ['summarize-chat'])
            self.assertEqual(self.protocol.calls[-1]['skills'], (ROOT / 'skills/summarize-chat/SKILL.md',))
        result = await self.execute('你好')
        self.assertEqual(result['response_kind'], 'chat')
        self.assertEqual(self.protocol.calls[-1]['skills'], ())

    async def test_memory_delete_requires_scope_and_owner(self):
        await self.execute('/remember 茶偏好')
        session = self.session_for(self.request())
        memory_id = self.runtime.store.memories(session['id'])[0]['id']
        denied = await self.execute(f'/forget {memory_id}', user_id='bob')
        self.assertIn('未找到', denied['text'])
        hidden = await self.execute('/memory', conversation_id='qq:bot:group:2')
        self.assertNotIn('茶偏好', hidden['text'])
        cross_scope = await self.execute(f'/forget {memory_id}', conversation_id='qq:bot:group:2')
        self.assertIn('未找到', cross_scope['text'])
        deleted = await self.execute(f'/forget {memory_id}')
        self.assertEqual(deleted['text'], '已删除。')
        self.assertEqual(self.runtime.store.memories(session['id']), [])
        self.assertEqual(self.protocol.instances, [])

    async def test_preview_does_not_write_memory_or_claim_delivery(self):
        result = await self.execute('/remember preview-secret', source='web', preview=True)
        self.assertIn('不写入', result['text'])
        with self.runtime.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM memories').fetchone()[0], 0)
        with self.assertRaisesRegex(ValueError, 'cannot be delivered'):
            self.runtime.store.delivery(result['run_id'], 'sending')

    async def test_preview_context_and_threads_are_separate_from_qq_and_other_users(self):
        await self.execute('qq-only-background')
        preview = await self.execute('alice-preview', source='web', preview=True,
                                     history={'messages': [{'role': 'user', 'content': 'provided preview history'}]})
        self.assertIsNone(self.protocol.calls[-1]['thread_id'])
        self.assertNotIn('qq-only-background', self.protocol.calls[-1]['text'])
        self.assertIn('provided preview history', self.protocol.calls[-1]['text'])
        await self.execute('bob-preview', source='web', preview=True, user_id='bob')
        self.assertIsNone(self.protocol.calls[-1]['thread_id'])
        self.assertNotIn('alice-preview', self.protocol.calls[-1]['text'])
        resumed = await self.execute('alice-followup', source='web', preview=True)
        self.assertEqual(self.protocol.calls[-1]['thread_id'], preview['thread_id'])
        self.assertEqual(resumed['thread_id'], preview['thread_id'])

    async def test_group_whitelist_and_silent_ordinary_messages(self):
        request = self.request()
        request['conversation_id'] = 'qq:bot:group:forbidden'
        with self.assertRaises(PermissionError):
            await self.runtime.submit(request)
        result = await self.execute('ordinary group chat', mentioned=False)
        self.assertEqual(result['status'], 'ignored')
        self.assertEqual(result['text'], '')
        self.assertEqual(self.protocol.instances, [])

    async def test_live_model_is_pinned_and_legacy_commands_do_not_start_an_agent(self):
        self.assertEqual(self.runtime.health()['model'], 'gpt-5.6-luna')
        self.assertEqual(self.runtime.health()['reasoning_effort'], 'max')
        result = await self.execute('/arc b50')
        self.assertEqual(result['status'], 'ignored')
        self.assertEqual(self.protocol.instances, [])
        request = self.request('hello')
        request.update(model='other-model', reasoning_effort='low')
        run = await self.runtime.submit(request)
        result = await self.runtime.wait(run['run_id'])
        self.assertEqual(self.protocol.calls[-1]['config']['model'], 'gpt-5.6-luna')
        self.assertEqual(self.protocol.calls[-1]['config']['reasoning_effort'], 'max')
        self.assertEqual(result['reasoning_effort'], 'max')

    async def test_context_counts_current_message_and_truncates_whole_history_messages(self):
        history = {'messages': ([{'senderName': '较早用户', 'content': '较早消息'} for _ in range(21)]
                                + [{'senderName': '历史用户', 'content': '甲' * 2100} for _ in range(10)])}
        result = await self.execute('当前问题', source='web', preview=True, history=history)
        self.assertEqual(result['context_messages'], 10)  # Nine clipped history items plus the prompt.
        self.assertEqual(result['context_characters'], 18000 + len('当前问题'))
        self.assertTrue(result['context_truncated'])
        prompt = self.protocol.calls[-1]['text']
        background = json.loads(prompt.split('\n', 1)[1].split('\n当前用户请求：\n', 1)[0])
        self.assertEqual(len(background), 9)
        self.assertTrue(all(len(item['text']) == 2000 for item in background))
        for invalid in ([], {'messages': ['bad']}, {'messages': [{'content': 123}]}):
            request = self.request()
            request['history'] = invalid
            with self.assertRaises(ValueError):
                await self.runtime.submit(request)

    async def test_migrated_proactive_limits_are_retained(self):
        scope = 'bot/qq:bot:group:1'
        self.settings.proactive_scopes = (scope,)
        self.settings.proactive_policies = {scope: {'probabilityPercent': 100, 'cooldownSeconds': 5,
                                                  'maximumPerHour': 1, 'minimumMessages': 2}}
        first = await self.execute('first background', mentioned=False)
        self.assertEqual(first['status'], 'ignored')
        second = await self.execute('second background', mentioned=False)
        self.assertEqual(second['status'], 'completed')
        self.runtime.last_proactive[scope] -= 10
        third = await self.execute('hour limit', mentioned=False)
        self.assertEqual(third['status'], 'ignored')
        mentioned = await self.execute('explicit request')
        self.assertEqual(mentioned['status'], 'completed')

    async def test_live_agent_loads_qq_history_but_rules_do_not(self):
        self.settings.qq_gateway_url = 'http://gateway.invalid'
        history = {'messages': [{'id': 'older', 'content': 'gateway older history', 'senderName': '用户'}],
                   'truncated': False}
        with patch('dududa_v3.services.ServiceHub.conversation_history', return_value=history) as fetch:
            await self.execute('/ping')
            fetch.assert_not_called()
            await self.execute('总结群聊')
            fetch.assert_called_once_with(30)
            self.assertIn('gateway older history', self.protocol.calls[-1]['text'])

    async def test_instruction_profile_rotates_old_thread_without_erasing_memory(self):
        session = self.session_for(self.request())
        self.runtime.store.thread(session['id'], 'old-thread', 'previous-profile')
        self.runtime.store.remember(session['id'], 'alice', '保留的记忆')
        first = await self.execute('刷新执行配置')
        self.assertIsNone(self.protocol.calls[-1]['thread_id'])
        current = self.session_for(self.request())
        self.assertEqual(current['profile'], SESSION_PROFILE)
        self.assertEqual(len(self.runtime.store.memories(session['id'])), 1)
        second = await self.execute('继续当前配置')
        self.assertEqual(self.protocol.calls[-1]['thread_id'], first['thread_id'])
        self.assertEqual(second['thread_id'], first['thread_id'])

    async def test_cli_check_does_not_recover_running_work_or_require_host_lock(self):
        session = self.session_for(self.request())
        running, _ = self.runtime.store.create_run(session['id'], {'message_id': 'cli-check-active'})
        self.runtime.store.update(running['run_id'], status='running')
        env = {**os.environ, 'DUDUDA_REPOSITORY': str(ROOT), 'DUDUDA_V3_STATE_DIR': str(self.state),
               'DUDUDA_V3_CODEX_BINARY': sys.executable,
               'PYTHONPATH': str(ROOT / 'packages/dududa-runtime/src')}
        with state_lock(self.settings):
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'dududa_v3', 'check', env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
        self.assertEqual(process.returncode, 0, stderr.decode())
        self.assertEqual(json.loads(stdout)['runtime'], 'dududa-3.0')
        self.assertEqual(self.runtime.store.get(running['run_id'])['status'], 'running')

    async def test_duplicate_message_creates_one_run_and_one_memory(self):
        request = self.request('/remember once')
        first, second = await asyncio.gather(self.runtime.submit(request), self.runtime.submit(request))
        self.assertEqual(first['run_id'], second['run_id'])
        await self.runtime.wait(first['run_id'])
        with self.runtime.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM memories').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 1)

    async def test_same_session_serializes_and_other_session_runs_concurrently(self):
        self.protocol.release.clear()
        first = await self.runtime.submit(self.request('first'))
        await asyncio.wait_for(self.protocol.started.get(), 2)
        second = await self.runtime.submit(self.request('second'))
        other_request = self.request('other scope')
        other_request['conversation_id'] = 'qq:bot:group:2'
        third = await self.runtime.submit(other_request)
        await asyncio.wait_for(self.protocol.started.get(), 2)
        self.assertEqual(len(self.protocol.instances), 2)
        self.assertEqual(self.protocol.max_active, 2)
        self.protocol.release.set()
        results = await asyncio.gather(*(self.runtime.wait(run['run_id']) for run in (first, second, third)))
        self.assertEqual(results[0]['thread_id'], results[1]['thread_id'])
        self.assertNotEqual(results[0]['thread_id'], results[2]['thread_id'])
        self.assertEqual(self.protocol.calls[-1]['thread_id'], results[0]['thread_id'])
        self.assertTrue(all(client.closed for client in self.protocol.instances))

    async def test_resume_failure_stays_failed_without_new_thread_or_fallback(self):
        first = await self.execute('first')
        self.protocol.fail = True
        failed = await self.execute('continue')
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['route'], 'agent')
        self.assertIn('resume unavailable', failed['error'])
        self.assertEqual(len(self.protocol.instances), 2)
        self.assertEqual(self.protocol.calls[-1]['thread_id'], first['thread_id'])
        self.assertEqual(self.session_for(self.request())['thread_id'], first['thread_id'])
        self.assertTrue(self.protocol.instances[-1].closed)

    async def test_cancel_rule_interrupts_agent_and_new_clears_thread(self):
        self.protocol.release.clear()
        active = await self.runtime.submit(self.request('long running'))
        client = await asyncio.wait_for(self.protocol.started.get(), 2)
        cancelled = await self.execute('/cancel')
        self.assertEqual(cancelled['route'], 'rule')
        self.assertTrue(client.cancelled)
        self.assertTrue(client.closed)
        self.assertEqual(self.runtime.store.get(active['run_id'])['status'], 'cancelled')
        reset = await self.execute('/new')
        self.assertEqual(reset['route'], 'rule')
        self.assertIsNone(self.session_for(self.request())['thread_id'])
        self.protocol.release.set()
        await self.execute('new conversation')
        self.assertIsNone(self.protocol.calls[-1]['thread_id'])

    async def test_delivery_claim_cannot_reopen_or_misreport_terminal_state(self):
        result = await self.execute('/ping')
        run_id = result['run_id']
        self.assertTrue(self.runtime.store.delivery(run_id, 'sending')['claimed'])
        self.assertFalse(self.runtime.store.delivery(run_id, 'sending')['claimed'])
        self.assertTrue(self.runtime.store.delivery(run_id, 'unknown')['claimed'])
        refused = self.runtime.store.delivery(run_id, 'sent', 'unexpected-id')
        self.assertFalse(refused['claimed'])
        self.assertEqual(refused['state'], 'unknown')
        self.assertFalse(self.runtime.store.delivery(run_id, 'sending')['claimed'])

    async def test_restart_marks_inflight_work_failed_without_replay(self):
        completed = await self.execute('/ping')
        self.runtime.store.delivery(completed['run_id'], 'sending')
        session = self.session_for(self.request())
        queued, _ = self.runtime.store.create_run(session['id'], {'message_id': 'orphan-queued'})
        running, _ = self.runtime.store.create_run(session['id'], {'message_id': 'orphan-running'})
        self.runtime.store.update(running['run_id'], status='running')
        restarted = Runtime(self.settings, client_factory=self.protocol)
        try:
            # The CLI invokes recovery only after acquiring the state lock;
            # merely inspecting Runtime must not change another worker's runs.
            self.assertEqual(restarted.store.get(queued['run_id'])['status'], 'queued')
            restarted.store.recover()
            self.assertEqual(restarted.store.get(queued['run_id'])['status'], 'failed')
            self.assertEqual(restarted.store.get(running['run_id'])['status'], 'failed')
            self.assertEqual(restarted.store.get(completed['run_id'])['status'], 'completed')
            self.assertEqual(restarted.store.delivery(completed['run_id'], 'sending')['state'], 'unknown')
            self.assertEqual(restarted.tasks, {})
            self.assertEqual(self.protocol.instances, [])
        finally:
            await restarted.close()

    async def test_http_auth_body_limit_and_v3_submission(self):
        server = create_server(self.runtime, asyncio.get_running_loop(), '127.0.0.1', 0, 'test-token')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method, path, body=None, headers=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            try:
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        try:
            status, _ = await asyncio.to_thread(request, 'GET', '/v3/health')
            self.assertEqual(status, 401)
            headers = {'Authorization': 'Bearer test-token'}
            status, value = await asyncio.to_thread(request, 'GET', '/v3/health', None, headers)
            self.assertEqual(status, 200)
            self.assertEqual(value['runtime'], 'dududa-3.0')
            for length in ('65537', '-1'):
                status, _ = await asyncio.to_thread(request, 'POST', '/v3/runs', b'',
                                                  {**headers, 'Content-Length': length})
                self.assertEqual(status, 400)
            status, _ = await asyncio.to_thread(request, 'POST', '/v3/runs', '[]', headers)
            self.assertEqual(status, 400)
            status, value = await asyncio.to_thread(request, 'POST', '/v3/runs',
                                                   json.dumps(self.request('/ping')), headers)
            self.assertEqual(status, 200)
            result = await self.runtime.wait(value['run_id'])
            self.assertEqual(result['route'], 'rule')
            self.assertEqual(self.protocol.instances, [])
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
