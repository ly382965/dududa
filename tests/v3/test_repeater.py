"""Repeater chain semantics on normalized QQ segments."""

import unittest
from unittest.mock import patch

from dududa_v3.features import repeater
from dududa_v3.features.base import Inbound, Sender


class FakeCtx:
    def __init__(self, inbound, config=None):
        self.inbound = inbound
        self.settings = type('S', (), {'bot_names': ('嘟嘟哒', 'dududa')})()
        self._config = config or {}

    def config(self, feature):
        return self._config


def message(user, segments, text='', group='100', images=()):
    return Inbound(account_id='qq-1', conversation_id=f'qq-1:group:{group}', message_id=f'm-{user}',
                   text=text, sender=Sender(id=user), segments=segments, images=list(images))


def text(user, value, **kwargs):
    return message(user, [{'type': 'text', 'text': value}], text=value, **kwargs)


class RepeaterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        repeater._chains.clear()
        self.roll = patch.object(repeater.random, 'random', return_value=0.0)
        self.roll.start()

    def tearDown(self):
        self.roll.stop()

    async def feed(self, inbound, config=None):
        reply = await repeater.repeater_observer(FakeCtx(inbound, config))
        return reply.actions if reply else None

    async def test_two_different_users_trigger_once(self):
        self.assertIsNone(await self.feed(text('1', '草')))
        self.assertEqual(await self.feed(text('2', '草')), [{'type': 'text', 'text': '草'}])
        # The same content is never repeated twice in a row.
        self.assertIsNone(await self.feed(text('3', '草')))
        self.assertIsNone(await self.feed(text('4', '草')))

    async def test_same_user_does_not_count_when_need_different(self):
        self.assertIsNone(await self.feed(text('1', '+1')))
        self.assertIsNone(await self.feed(text('1', '+1')))
        self.assertIsNone(await self.feed(text('1', '+1')))
        self.assertEqual(await self.feed(text('2', '+1')), [{'type': 'text', 'text': '+1'}])

    async def test_same_user_counts_without_need_different(self):
        config = {'need_different': False}
        self.assertIsNone(await self.feed(text('1', '哈'), config))
        self.assertEqual(await self.feed(text('1', '哈'), config), [{'type': 'text', 'text': '哈'}])

    async def test_threshold_and_interruption(self):
        config = {'thresholds': {'text': 3}}
        await self.feed(text('1', 'a'), config)
        await self.feed(text('2', 'a'), config)
        await self.feed(text('3', 'b'), config)  # breaks the chain
        self.assertIsNone(await self.feed(text('4', 'a'), config))
        self.assertIsNone(await self.feed(text('5', 'a'), config))
        self.assertEqual(await self.feed(text('6', 'a'), config), [{'type': 'text', 'text': 'a'}])

    async def test_new_content_can_repeat_after_other_repeat(self):
        await self.feed(text('1', 'x'))
        self.assertTrue(await self.feed(text('2', 'x')))
        await self.feed(text('1', 'y'))
        self.assertTrue(await self.feed(text('2', 'y')))
        await self.feed(text('1', 'x'))
        self.assertTrue(await self.feed(text('2', 'x')))

    async def test_probability_gate(self):
        with patch.object(repeater.random, 'random', return_value=0.9):
            await self.feed(text('1', 'p'))
            self.assertIsNone(await self.feed(text('2', 'p')))
        self.assertTrue(await self.feed(text('3', 'p')))

    async def test_image_fingerprint_prefers_resource_id(self):
        first = {'type': 'image', 'url': 'https://gchat.qpic.cn/a?rkey=1', 'resource_id': 'ABC.png'}
        second = {'type': 'image', 'url': 'https://gchat.qpic.cn/a?rkey=2', 'resource_id': 'ABC.png'}
        self.assertIsNone(await self.feed(message('1', [first])))
        self.assertEqual(await self.feed(message('2', [second])),
                         [{'type': 'image', 'url': 'https://gchat.qpic.cn/a?rkey=2'}])

    async def test_images_without_segments(self):
        image = {'url': 'https://gchat.qpic.cn/z', 'resource_id': 'Z.png'}
        await self.feed(message('1', [], images=[image]))
        self.assertTrue(await self.feed(message('2', [], images=[image])))

    async def test_face(self):
        await self.feed(message('1', [{'type': 'face', 'id': '178'}]))
        self.assertEqual(await self.feed(message('2', [{'type': 'face', 'id': '178'}])), [{'type': 'face', 'id': '178'}])

    async def test_ignored_messages(self):
        for value in ('/help', '嘟嘟哒 你好', 'x' * 300):
            await self.feed(text('1', value))
            self.assertIsNone(await self.feed(text('2', value)), value)
        mixed = [{'type': 'reply', 'message_id': '9'}, {'type': 'text', 'text': '对'}]
        await self.feed(message('1', mixed, text='对'))
        self.assertIsNone(await self.feed(message('2', mixed, text='对')))
        mention = [{'type': 'mention', 'id': '5', 'name': 'a'}]
        await self.feed(message('1', mention))
        self.assertIsNone(await self.feed(message('2', mention)))

    async def test_groups_are_independent_and_private_ignored(self):
        await self.feed(text('1', 'g', group='100'))
        self.assertIsNone(await self.feed(text('2', 'g', group='200')))
        private = Inbound(account_id='qq-1', conversation_id='qq-1:private:1', message_id='p', text='g',
                          sender=Sender(id='1'), segments=[{'type': 'text', 'text': 'g'}])
        self.assertIsNone(await self.feed(private))


if __name__ == '__main__':
    unittest.main()
