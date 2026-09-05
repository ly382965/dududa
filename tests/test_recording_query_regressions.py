import unittest

from astrbot_plugin_dududa_core.adapters.capability_planner import (
    NOTIFAI_SEARCH_CAPABILITY_ID,
    NOTIFAI_SOURCES_CAPABILITY_ID,
    _notifai_capability_from_goal,
)


class RecordingQueryRegressions(unittest.TestCase):
    def test_source_links_do_not_turn_notice_search_into_source_dictionary(self):
        for question in (
            "查询最近三条校园通知，带标题、日期和来源链接。",
            "搜索奖学金通知，只要教务来源。",
        ):
            self.assertEqual(
                _notifai_capability_from_goal(question), NOTIFAI_SEARCH_CAPABILITY_ID
            )
        self.assertEqual(
            _notifai_capability_from_goal("当前有哪些通知来源，各自有多少条？"),
            NOTIFAI_SOURCES_CAPABILITY_ID,
        )
