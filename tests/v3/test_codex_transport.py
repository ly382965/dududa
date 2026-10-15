"""V3 stdio protocol tests using a fake executable, not model acceptance tests.

Real-model acceptance is exercised separately through the V3 runtime. These
tests specifically cover races, failures, and permissions at its CLI boundary.
"""

import asyncio
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from dududa_v3.codex import CodexClient, CodexError, CodexTimeout

FAKE_SERVER = r'''
import json
import sys

options = {}
for i, arg in enumerate(sys.argv):
    if arg == '-c':
        key, value = sys.argv[i + 1].split('=', 1)
        options[key] = json.loads(value)
mode = options.get('fake_mode', 'normal')
record = options['fake_record']

def log(message):
    with open(record, 'a') as stream:
        stream.write(json.dumps(message) + '\n')

def send(message):
    print(json.dumps(message), flush=True)

def notify(method, params):
    send({'method': method, 'params': params})

def completed():
    status = 'failed' if mode == 'failed' else 'completed'
    notify('turn/completed', {'threadId': 'thread-1', 'turn': {
        'id': 'turn-1', 'status': status, 'items': [],
        'error': {'message': 'model unavailable'} if mode == 'failed' else None,
    }})

log({'argv': sys.argv})
for line in sys.stdin:
    msg = json.loads(line)
    log(msg)
    method = msg.get('method')
    request_id = msg.get('id')
    if method == 'initialize':
        send({'id': request_id, 'result': {'userAgent': 'test'}})
    elif method in ('thread/start', 'thread/resume'):
        if method == 'thread/resume' and mode == 'missing':
            send({'id': request_id, 'error': {'code': -32000, 'message': 'thread not found'}})
            continue
        notify('thread/started', {'thread': {'id': 'thread-1'}})
        send({'id': request_id, 'result': {'thread': {'id': 'thread-1'}, 'model': 'test-model'}})
    elif method == 'turn/start':
        if mode == 'exit':
            sys.exit(7)
        notify('turn/started', {'threadId': 'thread-1', 'turn': {'id': 'turn-1'}})
        # Intentionally deliver notifications before turn/start's response.
        notify('item/completed', {'threadId': 'thread-other', 'turnId': 'turn-1',
            'item': {'type': 'agentMessage', 'id': 'wrong-thread',
                     'text': 'WRONG THREAD', 'phase': 'final_answer'}})
        notify('item/completed', {'threadId': 'thread-1', 'turnId': 'turn-other',
            'item': {'type': 'agentMessage', 'id': 'wrong-turn',
                     'text': 'WRONG TURN', 'phase': 'final_answer'}})
        notify('item/completed', {'threadId': 'thread-1', 'turnId': 'turn-1',
            'item': {'type': 'agentMessage', 'id': 'comment',
                     'text': 'checking', 'phase': 'commentary'}})
        notify('item/completed', {'threadId': 'thread-1', 'turnId': 'turn-1',
            'item': {'type': 'mcpToolCall', 'id': 'tool-1', 'server': 'dududa',
                     'tool': 'status', 'arguments': {}, 'status': 'completed'}})
        if mode != 'commentary':
            notify('item/completed', {'threadId': 'thread-1', 'turnId': 'turn-1',
                'item': {'type': 'agentMessage', 'id': 'final',
                         'text': '完成', 'phase': 'final_answer'}})
        send({'id': request_id, 'result': {'turn': {'id': 'turn-1', 'status': 'inProgress', 'items': []}}})
        if mode == 'approval':
            send({'id': 'approval-1', 'method': 'item/commandExecution/requestApproval',
                  'params': {'threadId': 'thread-1', 'turnId': 'turn-1'}})
        elif mode != 'hang':
            completed()
    elif method == 'turn/interrupt':
        send({'id': request_id, 'result': {}})
    elif request_id == 'approval-1':
        completed()
'''


class CodexTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.binary = self.root / 'fake-codex'
        self.binary.write_text(f'#!{sys.executable}\n' + textwrap.dedent(FAKE_SERVER))
        self.binary.chmod(0o755)
        self.record = self.root / 'requests.jsonl'
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        self.directory.cleanup()

    def client(self, mode='normal', timeout=3):
        client = CodexClient(
            str(self.binary), cwd=self.root, timeout=timeout,
            config_overrides=[
                f'fake_mode={json.dumps(mode)}',
                f'fake_record={json.dumps(str(self.record))}',
                'sandbox_mode="danger-full-access"',
            ],
        )
        self.clients.append(client)
        return client

    def messages(self):
        return [json.loads(line) for line in self.record.read_text().splitlines()]

    async def test_preserves_final_before_completion_and_filters_other_turns(self):
        events = []

        async def on_event(event):
            events.append(event)

        result = await self.client().run('hello', instructions='persona', on_event=on_event)
        self.assertEqual(result.text, '完成')
        self.assertEqual(result.thread_id, 'thread-1')
        self.assertEqual(result.turn_id, 'turn-1')
        self.assertEqual(result.model, 'test-model')
        self.assertEqual(result.status, 'completed')
        self.assertEqual([item['id'] for item in result.tool_calls], ['tool-1'])
        self.assertIn('thread/started', [event['method'] for event in events])
        self.assertIn('turn/started', [event['method'] for event in events])
        self.assertNotIn('WRONG', json.dumps(events))
        messages = self.messages()
        argv = messages[0]['argv']
        self.assertEqual(argv[-3:], ['app-server', '--listen', 'stdio://'])
        self.assertGreater(argv.index('sandbox_mode="read-only"'), argv.index('sandbox_mode="danger-full-access"'))
        start = next(message for message in messages if message.get('method') == 'thread/start')
        self.assertEqual(start['params']['sandbox'], 'read-only')
        self.assertEqual(start['params']['approvalPolicy'], 'never')
        self.assertEqual(start['params']['developerInstructions'], 'persona')
        turn = next(message for message in messages if message.get('method') == 'turn/start')
        self.assertEqual(turn['params']['sandboxPolicy'], {'type': 'readOnly', 'networkAccess': False})
        self.assertEqual(turn['params']['approvalPolicy'], 'never')

    async def test_commentary_is_not_a_final_reply(self):
        result = await self.client('commentary').run('hello')
        self.assertEqual(result.text, '')

    async def test_resume_keeps_permissions(self):
        result = await self.client().run('continue', thread_id='thread-1')
        self.assertEqual(result.thread_id, 'thread-1')
        request = next(message for message in self.messages() if message.get('method') == 'thread/resume')
        self.assertEqual(request['params']['sandbox'], 'read-only')
        self.assertEqual(request['params']['approvalPolicy'], 'never')

    async def test_missing_thread_does_not_fall_back_to_new_thread(self):
        with self.assertRaisesRegex(CodexError, 'thread not found'):
            await self.client('missing').run('continue', thread_id='thread-1')
        methods = [message.get('method') for message in self.messages()]
        self.assertNotIn('thread/start', methods)
        self.assertNotIn('turn/start', methods)

    async def test_timeout_interrupts_active_turn(self):
        with self.assertRaises(CodexTimeout):
            await self.client('hang', timeout=0.3).run('hello')
        request = next(message for message in self.messages() if message.get('method') == 'turn/interrupt')
        self.assertEqual(request['params'], {'threadId': 'thread-1', 'turnId': 'turn-1'})

    async def test_task_cancellation_interrupts_active_turn(self):
        started = asyncio.Event()

        async def on_event(event):
            if event['method'] == 'turn/started':
                started.set()

        task = asyncio.create_task(self.client('hang').run('hello', on_event=on_event))
        await asyncio.wait_for(started.wait(), 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIn('turn/interrupt', [message.get('method') for message in self.messages()])

    async def test_unknown_approval_request_is_never_granted(self):
        await self.client('approval').run('hello')
        reply = next(message for message in self.messages() if message.get('id') == 'approval-1')
        self.assertEqual(reply['error']['code'], -32601)
        self.assertNotIn('result', reply)

    async def test_process_exit_fails_pending_request_promptly(self):
        with self.assertRaisesRegex(CodexError, 'exited|closed'):
            await asyncio.wait_for(self.client('exit').run('hello'), 1)

    async def test_failed_turn_is_an_error(self):
        with self.assertRaisesRegex(CodexError, 'model unavailable'):
            await self.client('failed').run('hello')

    async def test_overlapping_run_is_explicitly_rejected(self):
        started = asyncio.Event()

        async def on_event(event):
            if event['method'] == 'turn/started':
                started.set()

        client = self.client('hang')
        first = asyncio.create_task(client.run('hello', on_event=on_event))
        await asyncio.wait_for(started.wait(), 3)
        with self.assertRaisesRegex(CodexError, 'active run'):
            await client.run('second')
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first


if __name__ == '__main__':
    unittest.main()
