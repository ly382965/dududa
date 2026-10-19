"""Cat-heart observer: eligibility, verdict cache and per-group hourly budget."""

import struct
import unittest

from dududa_v3.features import cats
from dududa_v3.features.base import Inbound, Sender
from dududa_v3.omp import OmpResult

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + struct.pack('>II', 640, 480) + b'\x08\x02\x00\x00\x00'
TINY_PNG = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + struct.pack('>II', 120, 120) + b'\x08\x02\x00\x00\x00'


class FakeCtx:
    def __init__(self, inbound, verdict='CAT', body=PNG, config=None):
        self.inbound = inbound
        self.verdict = verdict
        self.body = body
        self._config = config or {}
        self.calls = []
        self.fetches = []

    def config(self, feature):
        return self._config

    async def fetch(self, url, **kwargs):
        self.fetches.append(url)
        return self.body, {'content-type': 'image/png'}, url

    async def agent_once(self, prompt, **kwargs):
        self.calls.append(kwargs)
        return OmpResult(text=self.verdict, model='fake/model', thinking='low')


def photo(name, **extra):
    return {'url': f'https://gchat.qpic.cn/{name}?rkey=1', 'resource_id': f'{name}.jpg', 'sticker': False, **extra}


def message(images, group='100', message_id='m1'):
    return Inbound(account_id='qq-1', conversation_id=f'qq-1:group:{group}', message_id=message_id, text='',
                   sender=Sender(id='7'), images=images)


class CatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cats._verdicts.clear()
        cats._budgets.clear()

    async def test_cat_gets_heart_and_is_cached(self):
        ctx = FakeCtx(message([photo('a')]))
        reply = await cats.cat_observer(ctx)
        self.assertEqual(reply.actions, [{'type': 'reaction', 'message_id': 'm1', 'emoji_id': '66'}])
        self.assertEqual(ctx.calls[0]['service'], 'vision')
        self.assertEqual(len(ctx.calls[0]['images']), 1)
        again = FakeCtx(message([photo('a')], message_id='m2'), verdict='NO')
        reply = await cats.cat_observer(again)
        self.assertEqual(reply.actions[0]['message_id'], 'm2')
        self.assertEqual(again.calls, [])

    async def test_no_verdict_cached(self):
        ctx = FakeCtx(message([photo('b')]), verdict='NO')
        self.assertIsNone(await cats.cat_observer(ctx))
        repeat = FakeCtx(message([photo('b')]))
        self.assertIsNone(await cats.cat_observer(repeat))
        self.assertEqual(repeat.calls, [])

    async def test_one_classification_per_message(self):
        ctx = FakeCtx(message([photo('c'), photo('d'), photo('e')]), verdict='NO')
        await cats.cat_observer(ctx)
        self.assertEqual(len(ctx.calls), 1)
        # The next message with the same images classifies the first image not judged yet.
        follow = FakeCtx(message([photo('c'), photo('d')]), verdict='CAT')
        self.assertIsNotNone(await cats.cat_observer(follow))
        self.assertEqual(follow.fetches, ['https://gchat.qpic.cn/d?rkey=1'])

    async def test_skips_stickers_small_and_private(self):
        ctx = FakeCtx(message([photo('s', sticker=True), photo('t', width=150, height=900)]))
        self.assertIsNone(await cats.cat_observer(ctx))
        private = Inbound(account_id='qq-1', conversation_id='qq-1:private:7', message_id='p', text='',
                          sender=Sender(id='7'), images=[photo('u')])
        self.assertIsNone(await cats.cat_observer(FakeCtx(private)))
        tiny = FakeCtx(message([photo('v')]), body=TINY_PNG)
        self.assertIsNone(await cats.cat_observer(tiny))
        self.assertEqual(ctx.calls + tiny.calls, [])

    async def test_hourly_budget_per_group(self):
        config = {'max_per_hour': 2}
        results = []
        for index in range(3):
            ctx = FakeCtx(message([photo(f'g{index}')]), config=config)
            results.append(await cats.cat_observer(ctx))
        self.assertEqual([bool(item) for item in results], [True, True, False])
        other = FakeCtx(message([photo('h')], group='200'), config=config)
        self.assertIsNotNone(await cats.cat_observer(other))

    def test_budget_window_expires(self):
        self.assertTrue(cats.take_budget('s', 1, 0.0))
        self.assertFalse(cats.take_budget('s', 1, 3599.0))
        self.assertTrue(cats.take_budget('s', 1, 3600.0))

    def test_image_size_headers(self):
        self.assertEqual(cats.image_size(PNG), (640, 480))
        gif = b'GIF89a' + struct.pack('<HH', 300, 200) + b'\x00' * 8
        self.assertEqual(cats.image_size(gif), (300, 200))
        jpeg = (b'\xff\xd8' + b'\xff\xe0' + struct.pack('>H', 4) + b'\x00\x00'
                + b'\xff\xc0' + struct.pack('>HBHH', 17, 8, 240, 320) + b'\x00' * 12)
        self.assertEqual(cats.image_size(jpeg), (320, 240))
        self.assertIsNone(cats.image_size(b'not an image'))


if __name__ == '__main__':
    unittest.main()
