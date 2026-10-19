"""Emoji argument parsing and metadata index reduction."""

import json
import unittest

from dududa_v3.features import emoji_kitchen as ek
from dududa_v3.features.base import FeatureError

PREFIX = ek.URL_PREFIX


def combo(left, right, date, latest=True):
    return {'gStaticUrl': f'{PREFIX}{date}/u{left}/u{left}_u{right}.png', 'alt': 'x', 'leftEmoji': '?',
            'leftEmojiCodepoint': left, 'rightEmoji': '?', 'rightEmojiCodepoint': right, 'date': date,
            'isLatest': latest, 'gBoardOrder': 1}


METADATA = json.dumps({
    'knownSupportedEmoji': ['1f600', '1f62d', '2764-fe0f', '1f636-200d-1f32b-fe0f'],
    'data': {
        '1f600': {'alt': 'grin', 'keywords': ['a', 'b'], 'emojiCodepoint': '1f600', 'combinations': {
            '1f62d': [combo('1f600', '1f62d', '20200101', latest=False), combo('1f600', '1f62d', '20230301')],
            '2764-fe0f': [combo('1f600', '2764-fe0f', '20201001')],
        }},
        '1f636-200d-1f32b-fe0f': {'alt': 'fog', 'keywords': [], 'combinations': {
            '1f62d': [combo('1f636-200d-1f32b-fe0f', '1f62d', '20220101')],
        }},
    },
})


class SplitTests(unittest.TestCase):
    def test_separators(self):
        for text in ('😀 😭', '😀+😭', '😀😭', ' 😀 ＋ 😭 ', '😀，😭'):
            self.assertEqual(ek.parse_pair(text), ('😀', '😭'), text)

    def test_clusters_keep_modifiers_and_zwj(self):
        self.assertEqual(ek.split_emoji('❤️😶‍🌫️'), ['❤️', '😶‍🌫️'])
        self.assertEqual(ek.split_emoji('👍🏽+🐱'), ['👍🏽', '🐱'])
        self.assertEqual(ek.split_emoji('❤️‍🔥🐱'), ['❤️‍🔥', '🐱'])

    def test_usage_errors(self):
        for text in ('', '😀', '😀 😭 🐱'):
            with self.assertRaises(FeatureError):
                ek.parse_pair(text)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.kitchen = ek.Kitchen(ek.build_index(METADATA), 0)

    def test_only_latest_and_both_orders(self):
        index = ek.build_index(METADATA)
        self.assertEqual(index['pairs']['1f600|1f62d'], '20230301/u1f600/u1f600_u1f62d.png')
        self.assertEqual(len(index['pairs']), 3)
        self.assertEqual(self.kitchen.url('1f62d', '1f600'), PREFIX + '20230301/u1f600/u1f600_u1f62d.png')

    def test_variation_selectors_are_optional(self):
        self.assertEqual(self.kitchen.codepoint('❤'), '2764-fe0f')
        self.assertEqual(self.kitchen.codepoint('❤️'), '2764-fe0f')
        self.assertEqual(self.kitchen.codepoint('😶‍🌫'), '1f636-200d-1f32b-fe0f')
        self.assertIsNone(self.kitchen.codepoint('🐱'))

    def test_missing_pair(self):
        self.assertIsNone(self.kitchen.url('2764-fe0f', '1f62d'))

    def test_invalid_metadata(self):
        with self.assertRaises(ValueError):
            ek.build_index('{"data": {}}')


if __name__ == '__main__':
    unittest.main()
