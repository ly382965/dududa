"""Exercise the real V3 Host; only the omp process is substituted by a client double."""

import asyncio
import base64
import dataclasses
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dududa_v3 import RUNTIME, SESSION_PROFILE
from dududa_v3.__main__ import state_lock
from dududa_v3.config import Settings
from dududa_v3.features import core
from dududa_v3.features.base import Job, Observer, Registry, Reply, Task, Tool, Toolkit
from dududa_v3.omp import ModelSpec, OmpClient, OmpError, OmpResult
from dududa_v3.runtime import TIRED, Runtime
from dududa_v3.server import create_server

ROOT = Path(__file__).resolve().parents[2]
BOT = '10000'
ACCOUNT = 'qq-' + BOT
GROUP = ACCOUNT + ':group:100'
GROUP2 = ACCOUNT + ':group:200'
PRIVATE = ACCOUNT + ':private:42'
ADMIN = '42'
OMP_FIELDS = {item.name for item in dataclasses.fields(OmpClient)}
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


def core_registry() -> Registry:
    """Only the built-in core module, so other feature modules cannot change routing outcomes."""
    registry = Registry()
    core.register(registry)
    return registry


class OmpDouble:
    """Factory with the ``OmpClient`` constructor contract; records every run."""

    def __init__(self):
        self.instances = []
        self.calls = []
        self.started = asyncio.Queue()
        self.gate = asyncio.Event()
        self.gate.set()
        self.active = 0
        self.max_active = 0
        self.error = None
        self.reply = '嘟嘟哒的回答'
        self.images = []
        self.tool_plan = []
        self.tool_results = []

    def __call__(self, **config):
        unknown = set(config) - OMP_FIELDS
        if unknown:
            raise TypeError(f'OmpClient has no fields {unknown}')
        client = FakeClient(self, config)
        self.instances.append(client)
        return client

    @property
    def last(self):
        return self.calls[-1]


class FakeClient:
    def __init__(self, owner: OmpDouble, config: dict):
        self.owner, self.config = owner, config
        self.cancelled = False

    async def run(self, text, images=()):
        owner = self.owner
        owner.calls.append({'text': text, 'images': list(images), 'config': self.config})
        owner.active += 1
        owner.max_active = max(owner.max_active, owner.active)
        try:
            owner.started.put_nowait(self)
            await owner.gate.wait()
            if owner.error:
                raise owner.error
            session_dir = self.config.get('session_dir')
            if session_dir is not None:
                session_dir.mkdir(parents=True, exist_ok=True)
                with (session_dir / 'session.jsonl').open('a') as handle:
                    handle.write(json.dumps({'prompt': text}, ensure_ascii=False) + '\n')
            for name, args in owner.tool_plan:
                owner.tool_results.append(await self.config['tool_handler'](name, args))
            spec = self.config['spec']
            return OmpResult(text=owner.reply, model=spec.model, thinking=spec.thinking,
                             tool_calls=[{'name': name, 'error': False} for name, _ in owner.tool_plan],
                             images=list(owner.images), usage={'totalTokens': 3})
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            owner.active -= 1


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state = Path(self.directory.name)
        registry = patch('dududa_v3.runtime.load_registry', core_registry)
        registry.start()
        self.addCleanup(registry.stop)
        core._pings.clear()
        self.settings = Settings(root=ROOT, state_dir=self.state, admins=(ADMIN,),
                                 allowed_scopes=(f'{ACCOUNT}/{GROUP}', f'{ACCOUNT}/{GROUP2}', f'{ACCOUNT}/{PRIVATE}'),
                                 rules=({'match': '规则问候', 'reply': '规则回答'},))
        self.omp = OmpDouble()
        self.runtime = Runtime(self.settings, client_factory=self.omp)

    async def asyncTearDown(self):
        await self.runtime.close()
        self.directory.cleanup()

    # ------------------------------------------------------------ helpers

    def request(self, text='hello', **changes):
        request = {'account_id': ACCOUNT, 'conversation_id': GROUP, 'user_id': '7', 'message_id': uuid.uuid4().hex,
                   'text': text, 'source': 'qq', 'mentioned': False,
                   'sender': {'card': '小明', 'nickname': '明明', 'role': 'member'}}
        request.update(changes)
        return request

    async def execute(self, text='hello', **changes):
        run = await self.runtime.submit(self.request(text, **changes))
        return await self.runtime.wait(run['run_id'])

    async def admin(self, text, **changes):
        return await self.execute(text, user_id=ADMIN, **changes)

    def session_for(self, conversation=GROUP, source='qq', user=None):
        third = 'preview:' + user if user else source
        return self.runtime.store.session(json.dumps([ACCOUNT, conversation, third], ensure_ascii=False))

    def serve(self, handler_class) -> str:
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_class)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.addCleanup(close)
        return f'http://127.0.0.1:{server.server_port}'

    def add_echo_features(self):
        seen = []

        async def echo(ctx):
            seen.append(ctx.inbound.text)
            return Reply.of_text('回声：' + ctx.inbound.text)

        async def heart(ctx):
            return Reply().reaction(ctx.inbound.message_id, '66')

        async def broken(ctx):
            raise RuntimeError('observer broke')

        async def echo_tool(ctx, args):
            return {'echo': args.get('text'), 'scope': ctx.inbound.scope}

        registry = self.runtime.registry
        registry.task(Task('echo', '回声机', '复读群友的话', aliases=('回声',)))
        registry.task(Task('heart', '贴心', '给群友贴爱心', default=False))
        registry.task(Task('broken', '坏掉的功能', '总是失败'))
        registry.observer(Observer('echo', echo, order=10))
        registry.observer(Observer('heart', heart, order=5))
        registry.observer(Observer('broken', broken, order=1))
        registry.tool(Tool('echo_tool', '回声工具', {'type': 'object', 'properties': {'text': {'type': 'string'}}},
                           echo_tool, task='echo'))
        return seen

    # ------------------------------------------------------------ routing

    async def test_commands_never_construct_the_client(self):
        for text in ('/ping', '/status', '嘟嘟哒 时间', '嘟嘟哒，几点了？', '嘟嘟哒 规则问候',
                     '/校车 工作日东区到西区最早一班', '嘟嘟哒 记住 喜欢绿茶', '/记忆 绿茶'):
            result = await self.execute(text)
            self.assertEqual(result['runtime'], RUNTIME, text)
            self.assertEqual(result['status'], 'completed', text)
            self.assertEqual(result['route'], 'rule', text)
            self.assertEqual(result['model'], 'rules', text)
            self.assertTrue(result['text'], text)
            self.assertEqual(result['actions'][0]['type'], 'text')
        self.assertIn('喜欢绿茶', result['text'])
        self.assertEqual(self.omp.instances, [])

    async def test_qq_help_uses_packaged_image_without_repository_assets(self):
        self.runtime.settings = dataclasses.replace(self.settings, root=self.state)
        result = await self.execute('/help', mentioned=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([action['type'] for action in result['actions']], ['image'])
        image = result['actions'][0]
        self.assertEqual(image['mime'], 'image/png')
        self.assertEqual(base64.b64decode(image['data'])[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(self.omp.instances, [])

    async def test_help_hides_admin_commands_from_ordinary_users(self):
        ordinary = await self.execute('嘟嘟哒 帮助', source='web')
        self.assertNotIn('task list', ordinary['text'])
        admin = await self.admin('/help', source='web')
        self.assertIn('task list', admin['text'])

    async def test_routing_prefixes_and_exact_commands(self):
        agent_cases = [('嘟嘟哒 你好', {}, '你好'), ('嘟嘟哒，你好呀', {}, '你好呀'), ('DUDUDA hi', {}, 'hi'),
                       ('你好', {'mentioned': True}, '你好'), ('嘟嘟哒 时间管理怎么做', {}, '时间管理怎么做'),
                       ('时间管理怎么做', {'mentioned': True}, '时间管理怎么做'),
                       ('你好', {'conversation_id': PRIVATE, 'user_id': '42'}, '你好')]
        for text, changes, body in agent_cases:
            result = await self.execute(text, **changes)
            self.assertEqual((result['status'], result['route']), ('completed', 'agent'), text)
            self.assertIn('内容：' + body, self.omp.last['text'])
        calls = len(self.omp.calls)
        for text in ('嘟嘟哒怎么这么蠢', '帮助', '时间', '今天天气不错'):
            result = await self.execute(text)
            self.assertEqual((result['status'], result['route']), ('ignored', 'ignore'), text)
        unknown = await self.execute('/unknowncmd 参数')
        self.assertEqual((unknown['status'], unknown['reason']), ('ignored', 'unclaimed_command'))
        self.assertEqual(len(self.omp.calls), calls)
        for text in ('/时间', '嘟嘟哒 时间？', '嘟嘟哒 TIME'):
            result = await self.execute(text)
            self.assertEqual((result['route'], result['command']), ('rule', 'time'), text)
        self.assertEqual(len(self.omp.calls), calls)

    async def test_group_whitelist_and_request_validation(self):
        with self.assertRaises(PermissionError):
            await self.runtime.submit(self.request(conversation_id=ACCOUNT + ':group:999'))
        invalid = [{'history': []}, {'history': {'messages': ['bad']}}, {'history': {'messages': [{'content': 1}]}},
                   {'sender': 'alice'}, {'mentioned': 'yes'}, {'text': '  '}, {'source': 'email'},
                   {'message_id': ''}, {'images': {}}]
        for changes in invalid:
            with self.assertRaises(ValueError, msg=str(changes)):
                await self.runtime.submit(self.request(**changes))

    async def test_duplicate_message_creates_one_run_and_one_memory(self):
        request = self.request('/remember once')
        first, second = await asyncio.gather(self.runtime.submit(request), self.runtime.submit(request))
        self.assertEqual(first['run_id'], second['run_id'])
        await self.runtime.wait(first['run_id'])
        with self.runtime.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM memories').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 1)

    # ------------------------------------------------------------ admin, tasks, limits

    async def test_admin_only_commands(self):
        for text in ('嘟嘟哒 task list', '嘟嘟哒 model list', '/model set chat sol-max', '嘟嘟哒 开启 回声',
                     '嘟嘟哒 关闭回声'):
            result = await self.execute(text)
            self.assertEqual((result['route'], result['text']), ('rule', '这个指令只有白名单用户可以用哦。'), text)
        self.assertEqual(self.runtime.store.model_bindings(), {})
        self.assertEqual(self.runtime.store.switches(), {})
        listed = await self.admin('嘟嘟哒 model list')
        self.assertIn('【模型通道】', listed['text'])
        self.assertEqual((await self.admin('/task list'))['text'], '当前没有可开关的任务。')

    async def test_task_switches_control_observers_and_tools(self):
        seen = self.add_echo_features()
        first = await self.execute('今天好热')
        self.assertEqual((first['status'], first['route']), ('completed', 'observer'))
        self.assertEqual(first['actions'], [{'type': 'text', 'text': '回声：今天好热'}])
        self.assertIn('observer_failed', [event['type'] for event in first['events']])
        enabled = await self.admin('嘟嘟哒 开启贴心')
        self.assertEqual(enabled['text'], '已更新：[开]（手动） heart · 贴心')
        both = await self.execute('再来一次')
        self.assertEqual([action['type'] for action in both['actions']], ['reaction', 'text'])
        message_id = self.runtime.store.request(both['run_id'])['message_id']
        self.assertEqual(both['actions'][0], {'type': 'reaction', 'message_id': message_id, 'emoji_id': '66'})
        missing = await self.admin('嘟嘟哒 task on 不存在')
        self.assertIn('没有找到任务', missing['text'])
        recall = await self.admin('嘟嘟哒 关闭 防撤回')
        self.assertIn('防撤回为群独立设置', recall['text'])
        disabled = await self.admin('嘟嘟哒 关闭 回声')
        self.assertIn('[关]（手动） echo', disabled['text'])
        quiet = await self.execute('还在吗')
        self.assertEqual([action['type'] for action in quiet['actions']], ['reaction'])
        self.assertEqual(seen, ['今天好热', '再来一次'])
        await self.execute('嘟嘟哒 你好')
        tools = {tool['name'] for tool in self.omp.last['config']['tools']}
        self.assertNotIn('echo_tool', tools)
        self.assertTrue({'memory_search', 'shuttle_query', 'conversation_history'} <= tools)
        listed = await self.admin('嘟嘟哒 task list')
        self.assertIn('[关]（手动） echo · 回声机', listed['text'])
        self.assertIn('[开]（默认） broken · 坏掉的功能', listed['text'])
        reset = await self.admin('嘟嘟哒 task reset 回声机')
        self.assertIn('[开]（默认） echo', reset['text'])
        await self.admin('嘟嘟哒 关闭 贴心')
        back = await self.execute('恢复了')
        self.assertEqual(back['actions'], [{'type': 'text', 'text': '回声：恢复了'}])
        await self.execute('嘟嘟哒 你好')
        self.assertIn('echo_tool', {tool['name'] for tool in self.omp.last['config']['tools']})

    async def test_rate_limit_says_tired_once_then_stays_silent(self):
        self.runtime.limiter.window = 3600  # Window expiry must not depend on machine speed.
        for _ in range(30):
            result = await self.execute('嘟嘟哒 时间')
            self.assertEqual(result['route'], 'rule')
            self.assertIn('上海', result['text'])
        tired = await self.execute('嘟嘟哒 时间')
        self.assertEqual((tired['status'], tired['text'], tired['reason']), ('completed', TIRED, 'rate_limited'))
        silent = await self.execute('嘟嘟哒 你好')
        self.assertEqual((silent['status'], silent['reason']), ('ignored', 'rate_limited'))
        self.assertEqual(self.omp.instances, [])
        admin = await self.admin('嘟嘟哒 task list')
        self.assertEqual(admin['status'], 'completed')
        self.assertNotEqual(admin['text'], TIRED)
        other = await self.execute('嘟嘟哒 时间', conversation_id=GROUP2)
        self.assertIn('上海', other['text'])

    async def test_ping_anti_spam(self):
        window = patch('dududa_v3.features.core.PING_WINDOW', 3600.0)
        window.start()
        self.addCleanup(window.stop)
        replies = [(await self.execute(text))['text'] for text in ('/ping', '嘟嘟哒 在吗', '/ping')]
        self.assertEqual(replies, ['在呢～', '在呢～', '在的在的！再问我就不理你了哼～'])
        ignored = await self.execute('/ping')
        self.assertEqual((ignored['status'], ignored['reason']), ('ignored', 'no_reply'))
        self.assertEqual((await self.execute('/ping', user_id='8'))['text'], '在呢～')

    async def test_model_resolution_order(self):
        rt = self.runtime
        self.assertEqual({service: rt.model_spec(service)[0] for service in ('qa', 'summary', 'vision', 'image')},
                         {'qa': 'luna-max', 'summary': 'luna-max', 'vision': 'luna-low', 'image': 'luna-max'})
        self.assertEqual((await self.admin('/model set chat sol-max'))['text'], '已将 chat 通道切换为 sol-max。')
        self.assertEqual(rt.model_spec('qa')[0], 'sol-max')  # channel binding > channel default
        self.assertEqual(rt.model_spec('vision')[0], 'luna-low')  # service default > channel binding
        self.settings.service_defaults['qa'] = 'terra-max'
        self.assertEqual(rt.model_spec('qa')[0], 'terra-max')
        await self.admin('/model service set qa luna-low')
        self.assertEqual(rt.model_spec('qa')[0], 'luna-low')  # service binding > service default
        reset = await self.admin('/model service reset qa')
        self.assertEqual(reset['text'], '已重置 qa 服务，现在使用 terra-max。')
        del self.settings.service_defaults['qa']
        self.assertEqual(rt.model_spec('qa')[0], 'sol-max')
        usage = await self.admin('/model set chat nonexistent')
        self.assertTrue(usage['text'].startswith('用法：'))
        services = await self.admin('/model service list')
        self.assertIn('vision（识图（猫图等））→ luna-low（配置默认）', services['text'])
        self.assertIn('qa（问答）→ sol-max（继承 chat）', services['text'])
        result = await self.execute('嘟嘟哒 你好')
        self.assertEqual(self.omp.last['config']['spec'], ModelSpec('openai-codex/gpt-5.6-sol', 'max'))
        self.assertEqual((result['model_name'], result['model'], result['reasoning_effort']),
                         ('sol-max', 'openai-codex/gpt-5.6-sol', 'max'))
        self.assertEqual(rt.health()['model'], 'openai-codex/gpt-5.6-sol')
        await self.admin('/model reset chat')
        self.assertEqual(rt.model_spec('qa')[0], 'luna-max')
        with self.assertRaises(ValueError):
            rt.model_spec('bogus')

    async def test_health_reports_omp_harness(self):
        health = self.runtime.health()
        self.assertEqual((health['harness'], health['model'], health['model_name'], health['reasoning_effort']),
                         ('omp', 'openai-codex/gpt-5.6-luna', 'luna-max', 'max'))
        self.assertEqual(health['allowed_scope_count'], 3)

    # ------------------------------------------------------------ agent sessions and prompts

    async def test_session_continuity_and_new_rotates(self):
        first = await self.execute('嘟嘟哒 第一问')
        second = await self.execute('嘟嘟哒 第二问')
        first_call, second_call = self.omp.calls
        session = self.session_for()
        expected = self.state / 'agent-sessions' / str(session['id']) / session['thread_id']
        self.assertEqual(first_call['config']['session_dir'], expected)
        self.assertEqual(second_call['config']['session_dir'], expected)
        self.assertEqual((first['thread_id'], second['thread_id']), (session['thread_id'], session['thread_id']))
        self.assertEqual(session['profile'], SESSION_PROFILE)
        self.assertIn('【近期聊天背景】', first_call['text'])
        self.assertIn('【上次回复后的新消息】', second_call['text'])
        config = first_call['config']
        self.assertEqual(config['cwd'], self.state / 'workspaces' / str(session['id']))
        self.assertEqual(config['builtin_tools'], ('web_search',))
        self.assertEqual(config['binary'], 'omp')
        self.assertEqual(config['timeout'], self.settings.timeout_seconds)
        self.assertIn('身份规则', config['system_prompt'].read_text(encoding='utf-8'))
        reset = await self.execute('/new')
        self.assertEqual(reset['text'], '已开始新对话。')
        third = await self.execute('嘟嘟哒 第三问')
        self.assertNotEqual(self.omp.last['config']['session_dir'], expected)
        self.assertNotEqual(third['thread_id'], first['thread_id'])
        self.assertIn('【近期聊天背景】', self.omp.last['text'])
        await self.execute('嘟嘟哒 别的群', conversation_id=GROUP2)
        self.assertNotIn(str(session['id']), self.omp.last['config']['session_dir'].parent.name)

    async def test_profile_change_rotates_session_without_erasing_memory(self):
        session = self.session_for()
        self.runtime.store.thread(session['id'], 'old-thread', 'previous-profile')
        self.runtime.store.remember(session['id'], '7', '保留的记忆')
        first = await self.execute('嘟嘟哒 刷新执行配置')
        self.assertNotEqual(self.omp.last['config']['session_dir'].name, 'old-thread')
        current = self.session_for()
        self.assertEqual(current['profile'], SESSION_PROFILE)
        self.assertEqual(len(self.runtime.store.memories(session['id'])), 1)
        second = await self.execute('嘟嘟哒 继续当前配置')
        self.assertEqual(second['thread_id'], first['thread_id'])
        self.assertEqual(self.omp.calls[0]['config']['session_dir'], self.omp.calls[1]['config']['session_dir'])

    async def test_identity_rendering(self):
        session = self.session_for()
        store = self.runtime.store
        store.observe(session['id'], '8', '我是小明', sender_name='小红')
        store.observe(session['id'], BOT, '上次的回答', sender_name='(bot)', bot=True)
        reply = {'message_id': 'm0', 'sender_id': BOT, 'sender_name': '嘟嘟哒', 'text': '上次的回答'}
        mentions = [{'id': BOT, 'name': '嘟嘟哒'}, {'id': '9', 'name': '小绿'}]
        await self.execute('嘟嘟哒 我是谁？', sender={'card': '小明', 'nickname': '明明', 'role': 'admin'},
                           reply=reply, mentions=mentions)
        prompt = self.omp.last['text']
        self.assertIn(f'【会话】QQ群 100｜你是嘟嘟哒（QQ{BOT}）', prompt)
        self.assertIn('发送者：小明（QQ7；群名片“小明”；QQ昵称“明明”；身份：管理员）', prompt)
        self.assertIn('引用回复：嘟嘟哒(你自己) 的消息「上次的回答」', prompt)
        self.assertIn('提及：@小绿(QQ9)', prompt)
        self.assertNotIn('@嘟嘟哒', prompt)
        self.assertIn('小红(QQ8): 我是小明', prompt)
        self.assertIn('嘟嘟哒(你自己): 上次的回答', prompt)
        self.assertIn('内容：我是谁？', prompt)
        self.assertNotIn('嘟嘟哒 我是谁', prompt)  # The current message is not repeated as background.
        self.assertNotIn('白名单', prompt)
        await self.admin('你好', conversation_id=PRIVATE, sender={'nickname': '管理员'})
        prompt = self.omp.last['text']
        self.assertIn('【会话】与 QQ42 的私聊', prompt)
        self.assertIn('发送者：管理员（QQ42；QQ昵称“管理员”；嘟嘟哒管理白名单）', prompt)

    async def test_continued_session_shows_only_local_messages_after_context_mark(self):
        await self.execute('早先的群聊')
        await self.execute('嘟嘟哒 第一问')
        self.assertIn('早先的群聊', self.omp.last['text'])
        await self.execute('之后的新消息')
        await self.execute('嘟嘟哒 第二问')
        self.assertIn('之后的新消息', self.omp.last['text'])
        self.assertNotIn('早先的群聊', self.omp.last['text'])

    async def test_gateway_history_context_mark_and_images(self):
        now_ms = int(time.time() * 1000)
        gateway = [
            {'messageId': 'g1', 'senderId': '8', 'senderName': '小红', 'content': '网关旧消息',
             'timestampMs': now_ms - 600000},
            {'messageId': 'g2', 'senderId': BOT, 'senderName': '嘟嘟哒', 'content': '机器人说过',
             'timestampMs': now_ms - 500000, 'segments': [{'type': 'reply', 'senderId': '8', 'senderName': '小红'}]},
            {'messageId': 'cur-1', 'senderId': '7', 'senderName': '小明', 'content': '嘟嘟哒 网关提问',
             'timestampMs': now_ms - 400000},
        ]
        paths = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                if self.path == '/img.png':
                    body = PNG
                else:
                    messages = [{'accountId': ACCOUNT, 'conversationId': GROUP, **item} for item in gateway]
                    body = json.dumps({'messages': messages, 'beforeCursor': None, 'hasMoreBefore': False}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        base = self.serve(Handler)
        self.settings.qq_gateway_url = base
        await self.execute('/ping')
        await self.execute('嘟嘟哒 规则问候')
        self.assertEqual(paths, [])
        result = await self.execute('嘟嘟哒 网关提问', message_id='cur-1', images=[{'url': base + '/img.png'}])
        self.assertTrue(paths[0].startswith(f'/api/accounts/{ACCOUNT}/conversations/group/100/messages?'))
        prompt = self.omp.last['text']
        self.assertIn('小红(QQ8): 网关旧消息', prompt)
        self.assertIn('嘟嘟哒(你自己) 回复 小红(QQ8): 机器人说过', prompt)
        self.assertNotIn('嘟嘟哒 网关提问', prompt)
        self.assertIn('附带图片：1 张', prompt)
        self.assertEqual(self.omp.last['images'], [{'data': base64.b64encode(PNG).decode(), 'mimeType': 'image/png'}])
        self.assertEqual(result['context_messages'], 3)
        # A message that arrives after the first answer was produced.
        gateway.append({'messageId': 'g3', 'senderId': '9', 'senderName': '小绿', 'content': '新的网关消息',
                        'timestampMs': int(time.time() * 1000)})
        await self.execute('嘟嘟哒 后续', message_id='cur-2')
        prompt = self.omp.last['text']
        self.assertIn('【上次回复后的新消息】', prompt)
        self.assertIn('小绿(QQ9): 新的网关消息', prompt)
        self.assertNotIn('网关旧消息', prompt)
        self.assertNotIn('机器人说过', prompt)

    async def test_gateway_failure_falls_back_to_local_history(self):
        self.settings.qq_gateway_url = 'http://127.0.0.1:9'
        await self.execute('本地背景')
        result = await self.execute('嘟嘟哒 你好')
        self.assertIn('小明(QQ7): 本地背景', self.omp.last['text'])
        self.assertIn('history_unavailable', [event['type'] for event in result['events']])

    async def test_context_counts_current_message_and_truncates_whole_history_messages(self):
        history = {'messages': ([{'senderName': '较早用户', 'content': '较早消息'} for _ in range(21)]
                                + [{'senderName': '历史用户', 'content': '甲' * 2100} for _ in range(10)])}
        result = await self.execute('当前问题', source='web', preview=True, mentioned=True, history=history)
        self.assertEqual(result['context_messages'], 10)  # Nine clipped history items plus the prompt.
        self.assertEqual(result['context_characters'], 18000 + len('当前问题'))
        self.assertTrue(result['context_truncated'])
        lines = [line for line in self.omp.last['text'].splitlines() if '历史用户: ' in line]
        self.assertEqual(len(lines), 9)
        self.assertTrue(all(line.endswith('甲' * 2000) and '甲' * 2001 not in line for line in lines))
        self.assertNotIn('较早用户', self.omp.last['text'])

    async def test_preview_sessions_are_separate_from_qq_and_other_users(self):
        await self.execute('嘟嘟哒 qq-only-background')
        qq_dir = self.omp.last['config']['session_dir']
        preview = {'source': 'web', 'preview': True, 'mentioned': True}
        await self.execute('alice-preview', user_id='alice', **preview,
                           history={'messages': [{'senderName': '预览用户', 'content': 'provided preview history'}]})
        alice_dir = self.omp.last['config']['session_dir']
        self.assertNotEqual(alice_dir, qq_dir)
        self.assertNotIn('qq-only-background', self.omp.last['text'])
        self.assertIn('provided preview history', self.omp.last['text'])
        await self.execute('bob-preview', user_id='bob', **preview)
        self.assertNotIn(self.omp.last['config']['session_dir'], (qq_dir, alice_dir))
        self.assertNotIn('alice-preview', self.omp.last['text'])
        await self.execute('alice-followup', user_id='alice', **preview)
        self.assertEqual(self.omp.last['config']['session_dir'], alice_dir)
        stored = await self.execute('/remember preview-secret', user_id='alice', **preview)
        self.assertIn('不写入', stored['text'])
        with self.runtime.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM memories').fetchone()[0], 0)
        with self.assertRaisesRegex(ValueError, 'cannot be delivered'):
            self.runtime.store.delivery(stored['run_id'], 'sending')

    async def test_summary_delegation_injects_skill_and_uses_summary_service(self):
        await self.admin('/model set summary terra-max')
        skill = (ROOT / 'skills/summarize-chat/SKILL.md').read_text(encoding='utf-8').split('---', 2)[2].strip()
        for text in ('嘟嘟哒 群里最近在说什么', '/summary 近5h', '嘟嘟哒 总结今日消息', '嘟嘟哒 近期消息省流'):
            result = await self.execute(text)
            self.assertEqual((result['status'], result['route']), ('completed', 'agent'), text)
            self.assertEqual(result['response_kind'], 'conversation_summary', text)
            self.assertEqual(result['skills'], ['summarize-chat'])
            self.assertEqual(result['model_name'], 'terra-max')
            prompt = self.omp.last['text']
            self.assertTrue(prompt.startswith('【本轮任务：群聊总结】'), text)
            self.assertIn(skill, prompt)
            self.assertEqual(self.omp.last['config']['spec'].model, 'openai-codex/gpt-5.6-terra')
        self.assertIn('内容：近5h', self.omp.calls[1]['text'])
        self.assertIn('内容：总结群聊', self.omp.calls[3]['text'])
        chat = await self.execute('嘟嘟哒 你好')
        self.assertEqual((chat['response_kind'], chat['skills'], chat['model_name']), ('chat', [], 'luna-max'))
        self.assertNotIn('群聊总结', self.omp.last['text'])

    async def test_agent_tools_are_bound_to_the_run_scope(self):
        self.add_echo_features()
        store = self.runtime.store
        store.remember(self.session_for()['id'], '7', '喜欢绿茶')
        store.remember(self.session_for(GROUP2)['id'], '8', '别的群也喜欢绿茶')
        self.omp.tool_plan = [('memory_search', {'query': '绿茶'}), ('shuttle_query', {'query': '工作日东区到西区最早一班'}),
                              ('memory_search', {'session_id': 1}), ('echo_tool', {'text': '嗨'}),
                              ('missing_tool', {})]
        result = await self.execute('嘟嘟哒 查一下')
        memory, shuttle, injected, echo, missing = self.omp.tool_results
        self.assertEqual([item['text'] for item in json.loads(memory[0])['items']], ['喜欢绿茶'])
        self.assertFalse(memory[1])
        self.assertTrue(json.loads(shuttle[0])['ok'])
        self.assertTrue(injected[1])
        self.assertIn('error', json.loads(injected[0]))
        self.assertEqual((json.loads(echo[0]), echo[1]), ({'echo': '嗨', 'scope': f'{ACCOUNT}/{GROUP}'}, False))
        self.assertTrue(missing[1])
        self.assertEqual(result['tools'], ['memory_search', 'shuttle_query', 'memory_search', 'echo_tool',
                                           'missing_tool'])
        self.assertEqual(result['tool_calls'], 5)
        self.assertEqual(result['usage'], {'totalTokens': 3})

    async def test_agent_markdown_is_flattened_for_qq_except_code(self):
        self.omp.reply = '## 结论\n明天 **会下雨**，记得带伞。\n```py\nprint(2 ** 3)  # **raw**\n```'
        result = await self.execute('嘟嘟哒 明天下雨吗')
        self.assertEqual(result['text'], '【结论】\n明天 会下雨，记得带伞。\n```py\nprint(2 ** 3)  # **raw**\n```')
        self.assertIn('QQ 不渲染 Markdown', self.omp.last['config']['system_prompt'].read_text())

    async def test_agent_images_become_actions_and_empty_reply_has_none(self):
        self.omp.reply = '画好啦'
        self.omp.images = [{'data': 'aW1n', 'mimeType': 'image/webp'}]
        drawn = await self.execute('嘟嘟哒 画一只猫')
        self.assertEqual(drawn['actions'], [{'type': 'text', 'text': '画好啦'},
                                            {'type': 'image', 'data': 'aW1n', 'mime': 'image/webp'}])
        self.assertEqual(drawn['text'], '画好啦\n[图片]')
        self.omp.reply, self.omp.images = '', []
        empty = await self.execute('嘟嘟哒 沉默')
        self.assertEqual((empty['status'], empty['actions']), ('completed', []))
        with self.assertRaisesRegex(ValueError, 'cannot be delivered'):
            self.runtime.store.delivery(empty['run_id'], 'sending')

    async def test_agent_once_is_ephemeral_and_uses_service_model(self):
        self.omp.reply = '一只橘猫'
        images = [{'data': 'aW1n', 'mimeType': 'image/png'}]
        result = await Toolkit(self.runtime).agent_once('描述图片', service='vision', images=images,
                                                       builtin_tools=('generate_image',), system='只描述图片')
        self.assertEqual(result.text, '一只橘猫')
        config = self.omp.last['config']
        self.assertEqual(config['spec'], ModelSpec('openai-codex/gpt-5.6-luna', 'low'))
        self.assertIsNone(config['session_dir'])
        self.assertNotIn('tools', config)
        self.assertEqual(config['builtin_tools'], ('generate_image',))
        self.assertEqual(config['system_prompt'].read_text(encoding='utf-8'), '只描述图片')
        self.assertEqual(self.omp.last['images'], images)

    async def test_same_session_serializes_and_global_concurrency_is_bounded(self):
        self.omp.gate.clear()
        runs = [await self.runtime.submit(self.request('嘟嘟哒 A1')),
                await self.runtime.submit(self.request('嘟嘟哒 A2')),
                await self.runtime.submit(self.request('嘟嘟哒 B', conversation_id=GROUP2)),
                await self.runtime.submit(self.request('C', conversation_id=PRIVATE, user_id='42'))]
        for _ in range(2):
            await asyncio.wait_for(self.omp.started.get(), 30)
        await asyncio.sleep(0.1)
        self.assertEqual(len(self.omp.calls), 2)
        self.assertIn('内容：A1', self.omp.calls[0]['text'])
        self.assertIn('内容：B', self.omp.calls[1]['text'])
        self.omp.gate.set()
        results = await asyncio.gather(*(self.runtime.wait(run['run_id']) for run in runs))
        self.assertTrue(all(result['status'] == 'completed' for result in results))
        self.assertEqual(self.omp.max_active, 2)
        self.assertEqual(results[0]['thread_id'], results[1]['thread_id'])
        self.assertNotEqual(results[0]['thread_id'], results[2]['thread_id'])

    async def test_failure_keeps_session_without_fallback(self):
        first = await self.execute('嘟嘟哒 第一问')
        session_dir = self.omp.last['config']['session_dir']
        self.omp.error = OmpError('resume unavailable')
        failed = await self.execute('嘟嘟哒 继续')
        self.assertEqual((failed['status'], failed['route']), ('failed', 'agent'))
        self.assertIn('resume unavailable', failed['error'])
        self.assertEqual(len(self.omp.instances), 2)
        self.assertEqual(self.session_for()['thread_id'], first['thread_id'])
        self.omp.error = None
        await self.execute('嘟嘟哒 再试')
        self.assertEqual(self.omp.last['config']['session_dir'], session_dir)

    async def test_cancel_interrupts_agent_and_new_starts_fresh_session(self):
        self.omp.gate.clear()
        active = await self.runtime.submit(self.request('嘟嘟哒 长任务'))
        client = await asyncio.wait_for(self.omp.started.get(), 30)
        cancelled = await self.execute('/cancel')
        self.assertEqual((cancelled['route'], cancelled['text']), ('rule', '已取消当前会话任务。'))
        self.assertTrue(client.cancelled)
        self.assertEqual(self.runtime.store.get(active['run_id'])['status'], 'cancelled')
        old_dir = client.config['session_dir']
        await self.execute('/new')
        self.omp.gate.set()
        await self.execute('嘟嘟哒 换个话题')
        self.assertNotEqual(self.omp.last['config']['session_dir'], old_dir)

    async def test_migrated_proactive_limits_are_retained(self):
        scope = f'{ACCOUNT}/{GROUP}'
        self.settings.proactive_scopes = (scope,)
        self.settings.proactive_policies = {scope: {'probabilityPercent': 100, 'cooldownSeconds': 5,
                                                  'maximumPerHour': 1, 'minimumMessages': 2}}
        first = await self.execute('first background')
        self.assertEqual(first['status'], 'ignored')
        second = await self.execute('second background')
        self.assertEqual((second['status'], second['route']), ('completed', 'agent'))
        self.runtime.last_proactive[scope] -= 10
        third = await self.execute('hour limit')
        self.assertEqual(third['status'], 'ignored')
        mentioned = await self.execute('explicit request', mentioned=True)
        self.assertEqual(mentioned['status'], 'completed')

    async def test_proactive_turn_can_decline_without_delivery(self):
        scope = f'{ACCOUNT}/{GROUP}'
        self.settings.proactive_scopes = (scope,)
        self.settings.proactive_policies = {scope: {'probabilityPercent': 100, 'cooldownSeconds': 5,
                                                  'maximumPerHour': 5, 'minimumMessages': 1}}
        self.omp.reply = '[SKIP]'
        declined = await self.execute('今天食堂好挤')
        self.assertEqual((declined['status'], declined.get('reason'), declined['actions']),
                         ('ignored', 'proactive_skip', []))
        self.assertIn('【主动插话机会】', self.omp.last['text'])
        self.runtime.last_proactive[scope] -= 10
        self.omp.reply = '我也觉得！'
        joined = await self.execute('又排了二十分钟')
        self.assertEqual((joined['status'], joined['text']), ('completed', '我也觉得！'))
        self.omp.reply = '[SKIP]'
        addressed = await self.execute('嘟嘟哒 [SKIP] 原样说一遍')
        self.assertEqual(addressed['status'], 'completed')

    async def test_memory_delete_requires_scope_and_owner(self):
        await self.execute('/remember 茶偏好')
        session = self.session_for()
        memory_id = self.runtime.store.memories(session['id'])[0]['id']
        denied = await self.execute(f'/forget {memory_id}', user_id='bob')
        self.assertIn('未找到', denied['text'])
        hidden = await self.execute('/memory', conversation_id=GROUP2)
        self.assertNotIn('茶偏好', hidden['text'])
        cross_scope = await self.execute(f'/forget {memory_id}', conversation_id=GROUP2)
        self.assertIn('未找到', cross_scope['text'])
        deleted = await self.execute(f'/forget {memory_id}')
        self.assertEqual(deleted['text'], '已删除。')
        self.assertEqual(self.runtime.store.memories(session['id']), [])
        self.assertEqual(self.omp.instances, [])

    async def test_jobs_record_success_and_failure(self):
        calls = []

        async def good(ctx):
            calls.append(ctx.settings is self.settings)

        async def bad(ctx):
            raise RuntimeError('feed down')

        registry = self.runtime.registry
        registry.task(Task('good-job', '好任务', '成功'))
        registry.task(Task('bad-job', '坏任务', '失败'))
        registry.task(Task('off-job', '关闭的任务', '不运行', default=False))
        registry.job(Job('good-job', 3600, good, initial_delay_seconds=0))
        registry.job(Job('bad-job', 3600, bad, initial_delay_seconds=0))
        registry.job(Job('off-job', 3600, good, initial_delay_seconds=0))
        self.runtime.start_jobs()
        for _ in range(300):
            if self.runtime.store.kv_get('jobs', 'bad-job') and self.runtime.store.kv_get('jobs', 'good-job'):
                break
            await asyncio.sleep(0.1)
        self.assertEqual(calls, [True])
        self.assertTrue(self.runtime.store.kv_get('jobs', 'good-job')['ok'])
        failed = self.runtime.store.kv_get('jobs', 'bad-job')
        self.assertEqual((failed['ok'], failed['error']), (False, 'RuntimeError: feed down'))
        self.assertIsNone(self.runtime.store.kv_get('jobs', 'off-job'))

    # ------------------------------------------------------------ delivery and outbox

    async def test_delivery_claim_requires_actions_and_observes_bot_message(self):
        ignored = await self.execute('普通聊天')
        with self.assertRaisesRegex(ValueError, 'cannot be delivered'):
            self.runtime.store.delivery(ignored['run_id'], 'sending')
        result = await self.execute('嘟嘟哒 规则问候')
        run_id = result['run_id']
        self.assertTrue(self.runtime.store.delivery(run_id, 'sending')['claimed'])
        self.assertFalse(self.runtime.store.delivery(run_id, 'sending')['claimed'])
        self.assertEqual(self.runtime.store.delivery(run_id, 'sent', 'qq-msg-1'), {
            'runtime': RUNTIME, 'claimed': True, 'state': 'sent'})
        bot_rows = [row for row in self.runtime.store.recent(self.session_for()['id'], 30) if row['bot']]
        self.assertEqual([(row['sender'], row['text'], row['message_id']) for row in bot_rows],
                         [(BOT, '规则回答', 'qq-msg-1')])
        with self.assertRaises(ValueError):
            self.runtime.store.delivery(run_id, 'bogus')
        await self.execute('嘟嘟哒 刚才你说了什么')
        self.assertIn('嘟嘟哒(你自己): 规则回答', self.omp.last['text'])

    async def test_delivery_claim_cannot_reopen_or_misreport_terminal_state(self):
        run_id = (await self.execute('/ping'))['run_id']
        self.assertTrue(self.runtime.store.delivery(run_id, 'sending')['claimed'])
        self.assertTrue(self.runtime.store.delivery(run_id, 'unknown')['claimed'])
        refused = self.runtime.store.delivery(run_id, 'sent', 'unexpected-id')
        self.assertFalse(refused['claimed'])
        self.assertEqual(refused['state'], 'unknown')
        self.assertFalse(self.runtime.store.delivery(run_id, 'sending')['claimed'])
        self.assertFalse(any(row['bot'] for row in self.runtime.store.recent(self.session_for()['id'], 30)))

    async def test_outbox_push_claim_and_result(self):
        toolkit = Toolkit(self.runtime)
        scope = f'{ACCOUNT}/{GROUP}'
        self.assertTrue(toolkit.push(scope, Reply.of_text('提醒'), dedupe='alert-1'))
        self.assertFalse(toolkit.push(scope, Reply.of_text('重复提醒'), dedupe='alert-1'))
        self.assertTrue(toolkit.push(scope, Reply().face('66')))
        with self.assertRaises(ValueError):
            toolkit.push(scope, Reply())
        items = self.runtime.store.outbox_claim(1)
        self.assertEqual(items, [{'id': items[0]['id'], 'account_id': ACCOUNT, 'conversation_id': GROUP,
                                  'actions': [{'type': 'text', 'text': '提醒'}]}])
        second = self.runtime.store.outbox_claim(10)
        self.assertEqual([item['actions'] for item in second], [[{'type': 'face', 'id': '66'}]])
        self.assertEqual(self.runtime.store.outbox_claim(10), [])
        self.assertTrue(self.runtime.store.outbox_result(items[0]['id'], 'sent', 'qq-1'))
        self.assertFalse(self.runtime.store.outbox_result(items[0]['id'], 'unknown'))
        with self.assertRaises(ValueError):
            self.runtime.store.outbox_result(second[0]['id'], 'pending')
        self.runtime.store.recover()  # An in-flight send cannot be retried after restart.
        self.assertFalse(self.runtime.store.outbox_result(second[0]['id'], 'sent'))
        self.assertEqual(self.runtime.store.outbox_claim(10), [])

    async def test_restart_marks_inflight_work_failed_without_replay(self):
        completed = await self.execute('/ping')
        self.runtime.store.delivery(completed['run_id'], 'sending')
        session = self.session_for()
        queued, _ = self.runtime.store.create_run(session['id'], {'message_id': 'orphan-queued'})
        running, _ = self.runtime.store.create_run(session['id'], {'message_id': 'orphan-running'})
        self.runtime.store.update(running['run_id'], status='running')
        restarted = Runtime(self.settings, client_factory=self.omp)
        try:
            # Recovery runs only after the CLI acquires the state lock; constructing Runtime changes nothing.
            self.assertEqual(restarted.store.get(queued['run_id'])['status'], 'queued')
            restarted.store.recover()
            self.assertEqual(restarted.store.get(queued['run_id'])['status'], 'failed')
            self.assertEqual(restarted.store.get(running['run_id'])['status'], 'failed')
            self.assertEqual(restarted.store.get(completed['run_id'])['status'], 'completed')
            self.assertEqual(restarted.store.delivery(completed['run_id'], 'sending')['state'], 'unknown')
            self.assertEqual(restarted.tasks, {})
            self.assertEqual(self.omp.instances, [])
        finally:
            await restarted.close()

    async def test_cli_check_does_not_recover_running_work_or_require_host_lock(self):
        session = self.session_for()
        running, _ = self.runtime.store.create_run(session['id'], {'message_id': 'cli-check-active'})
        self.runtime.store.update(running['run_id'], status='running')
        env = {**os.environ, 'DUDUDA_REPOSITORY': str(ROOT), 'DUDUDA_V3_STATE_DIR': str(self.state),
               'DUDUDA_V3_OMP_BINARY': sys.executable,
               'PYTHONPATH': str(ROOT / 'packages/dududa-runtime/src')}
        with state_lock(self.settings):
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'dududa_v3', 'check', env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
        self.assertEqual(process.returncode, 0, stderr.decode())
        report = json.loads(stdout)
        self.assertEqual(report['runtime'], RUNTIME)
        self.assertTrue(report['omp_available'])
        self.assertIn('Python', report['omp_version'])
        self.assertEqual(self.runtime.store.get(running['run_id'])['status'], 'running')

    async def test_http_auth_runs_delivery_and_outbox(self):
        server = create_server(self.runtime, asyncio.get_running_loop(), '127.0.0.1', 0, 'test-token')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        headers = {'Authorization': 'Bearer test-token'}

        def call(method, path, body=None, extra=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
            try:
                payload = body if isinstance(body, (str, bytes)) or body is None else json.dumps(body)
                connection.request(method, path, body=payload, headers=extra if extra is not None else headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        async def request(*args):
            return await asyncio.to_thread(call, *args)

        try:
            self.assertEqual((await request('GET', '/v3/health', None, {}))[0], 401)
            self.assertEqual((await request('GET', '/v3/health', None, {'Authorization': 'Bearer wrong'}))[0], 401)
            status, health = await request('GET', '/v3/health')
            self.assertEqual((status, health['runtime'], health['harness']), (200, RUNTIME, 'omp'))
            for length in ('262145', '-1'):
                status, _ = await request('POST', '/v3/runs', b'', {**headers, 'Content-Length': length})
                self.assertEqual(status, 400)
            self.assertEqual((await request('POST', '/v3/runs', '[]'))[0], 400)
            self.assertEqual((await request('GET', '/v3/unknown'))[0], 404)
            self.assertEqual((await request('GET', '/v3/runs/missing'))[0], 404)
            forbidden = self.request('/ping', conversation_id=ACCOUNT + ':group:999')
            self.assertEqual((await request('POST', '/v3/runs', forbidden))[0], 403)
            status, submitted = await request('POST', '/v3/runs', self.request('/ping'))
            self.assertEqual(status, 200)
            await self.runtime.wait(submitted['run_id'])
            status, result = await request('GET', f"/v3/runs/{submitted['run_id']}")
            self.assertEqual((status, result['route'], result['actions']),
                             (200, 'rule', [{'type': 'text', 'text': '在呢～'}]))
            status, claim = await request('POST', f"/v3/runs/{submitted['run_id']}/delivery", {'state': 'sending'})
            self.assertEqual((status, claim['claimed']), (200, True))
            status, sent = await request('POST', f"/v3/runs/{submitted['run_id']}/delivery",
                                         {'state': 'sent', 'message_id': 'qq-9'})
            self.assertEqual((status, sent['state']), (200, 'sent'))
            self.assertEqual(self.omp.instances, [])
            item = {'account_id': ACCOUNT, 'conversation_id': GROUP, 'actions': [{'type': 'text', 'text': '订阅更新'}],
                    'dedupe': 'feed:1'}
            self.assertEqual(await request('POST', '/v3/outbox', item), (200, {'runtime': RUNTIME, 'queued': True}))
            self.assertEqual((await request('POST', '/v3/outbox', item))[1]['queued'], False)
            self.assertEqual((await request('POST', '/v3/outbox', {**item, 'conversation_id': 'x'}))[0], 403)
            self.assertEqual((await request('POST', '/v3/outbox', {**item, 'actions': 'text'}))[0], 400)
            self.assertEqual((await request('POST', '/v3/outbox', {**item, 'actions': [], 'dedupe': None}))[0], 400)
            status, claimed = await request('POST', '/v3/outbox/claim', {'limit': 10})
            self.assertEqual(status, 200)
            self.assertEqual([entry['actions'] for entry in claimed['items']], [item['actions']])
            self.assertEqual((await request('POST', '/v3/outbox/claim', {}))[1]['items'], [])
            path = f"/v3/outbox/{claimed['items'][0]['id']}/result"
            self.assertEqual((await request('POST', path, {'state': 'sent', 'message_id': 'qq-10'}))[1]['updated'], True)
            self.assertEqual((await request('POST', path, {'state': 'unknown'}))[1]['updated'], False)
            self.assertEqual((await request('POST', path, {'state': 'pending'}))[0], 400)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(timeout=3)



if __name__ == '__main__':
    unittest.main()
