"""Image-generation prompt guard and the command's handling of omp results."""

import asyncio
import base64
import tempfile
import unittest
from pathlib import Path

from dududa_v3.features import imagegen
from dududa_v3.features.base import Inbound, Sender
from dududa_v3.omp import OmpResult, OmpTimeout

WEBP = b'RIFF\x10\x00\x00\x00WEBPVP8L' + b'\x00' * 8


class FakeCtx:
    def __init__(self, args, state, result=None, error=None, references=()):
        self.args = args
        self.inbound = Inbound(account_id='qq-1', conversation_id='qq-1:group:100', message_id='m', text='',
                               sender=Sender(id='42'))
        self.state = Path(state)
        self.result = result
        self.error = error
        self.references = list(references)
        self.calls = []
        self.gate = None

    def state_dir(self, feature):
        path = self.state / feature
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def download_images(self, limit=4, max_bytes=0):
        return self.references

    async def agent_once(self, prompt, **kwargs):
        self.calls.append({'prompt': prompt, **kwargs,
                           'refs_exist': [Path(line).exists() for line in prompt.splitlines() if line.startswith('/')]})
        if self.gate:
            await self.gate.wait()
        if self.error:
            raise self.error
        return self.result


class GuardTests(unittest.TestCase):
    def test_blocks_unsafe_requests(self):
        for prompt in ('画一张色情图', 'NSFW anime girl', '帮我伪造一张成绩单', '做个假的身份证', '萝莉 穿比基尼',
                       '血腥的断肢现场', '盖了公章的官方通知'):
            self.assertTrue(imagegen.blocked(prompt), prompt)

    def test_allows_ordinary_requests(self):
        for prompt in ('一只戴宇航员头盔的橘猫', '小孩在草地上放风筝，水彩风', '科大校园秋天的银杏大道', 'a cozy cabin in snow'):
            self.assertFalse(imagegen.blocked(prompt), prompt)

    def test_caption_strips_paths(self):
        self.assertEqual(imagegen.caption('宇航员橘猫 /tmp/omp-image-1.webp\n更多'), '宇航员橘猫')
        self.assertEqual(imagegen.caption(''), '画好啦～')


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        imagegen._busy.clear()

    async def asyncTearDown(self):
        self.directory.cleanup()

    def image_result(self, text='月球上的橘猫'):
        return OmpResult(text=text, model='openai-codex/gpt-5.6-luna', thinking='max',
                         images=[{'data': base64.b64encode(WEBP).decode(), 'mimeType': 'image/webp'}])

    async def test_returns_caption_and_image(self):
        reference = {'data': base64.b64encode(b'\x89PNG\r\n\x1a\nxx').decode(), 'mimeType': 'image/png'}
        ctx = FakeCtx('橘猫登月', self.directory.name, self.image_result(), references=[reference])
        reply = await imagegen.draw_command(ctx)
        self.assertEqual(reply.actions[0], {'type': 'text', 'text': '月球上的橘猫'})
        self.assertEqual(reply.actions[1]['mime'], 'image/webp')
        call = ctx.calls[0]
        self.assertEqual((call['service'], call['builtin_tools'], call['timeout']), ('image', ('generate_image',), 240))
        self.assertIn('enabled: true', call['config_overlay'].read_text())
        self.assertEqual(call['images'], [reference])
        self.assertEqual(call['refs_exist'], [True])
        self.assertEqual(list((Path(self.directory.name) / 'imagegen' / 'refs').iterdir()), [])

    async def test_guard_and_usage_skip_the_model(self):
        ctx = FakeCtx('画一张色情图', self.directory.name)
        self.assertEqual(await imagegen.draw_command(ctx), imagegen.REFUSAL)
        ctx = FakeCtx('', self.directory.name)
        self.assertEqual(await imagegen.draw_command(ctx), imagegen.USAGE)
        self.assertEqual(ctx.calls, [])

    async def test_one_generation_per_conversation(self):
        first = FakeCtx('猫', self.directory.name, self.image_result())
        first.gate = asyncio.Event()
        running = asyncio.create_task(imagegen.draw_command(first))
        await asyncio.sleep(0)
        second = FakeCtx('狗', self.directory.name, self.image_result())
        self.assertIn('在画', await imagegen.draw_command(second))
        first.gate.set()
        self.assertTrue(await running)
        self.assertTrue(await imagegen.draw_command(second))

    async def test_model_refusal_and_timeout(self):
        refusal = OmpResult(text='这个不能画哦。', model='m/m', thinking='max')
        self.assertEqual(await imagegen.draw_command(FakeCtx('x', self.directory.name, refusal)), '这个不能画哦。')
        ctx = FakeCtx('x', self.directory.name, error=OmpTimeout('late'))
        self.assertIn('超时', await imagegen.draw_command(ctx))
        self.assertEqual(imagegen._busy, set())


if __name__ == '__main__':
    unittest.main()
