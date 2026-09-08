import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/astrbot-plugins/astrbot_plugin_ustc_classroom"))

from astrbot_plugin_ustc_classroom import schedule as schedule_module  # noqa: E402
from astrbot_plugin_ustc_classroom.schedule import (  # noqa: E402
    filter_exams,
    format_room_answer,
    parse_occupancies,
    parse_exams,
    resolve_day_offset,
    resolve_periods,
    teaching_week,
)


LESSON_SAMPLE = {
    "id": 177346,
    "code": "022063.01",
    "dateTimePlaceText": "2304: 2(3,4);2304: 4(6,7)",
    "dateTimePlacePersonText": {
        "cn": "1~15周 2304 :2(3,4) 何志成\n1~15周 2304 :4(6,7) 何志成"
    },
    "teacherAssignmentList": ["何志成"],
    "course": {"code": "022063", "cn": "热力学与统计物理B", "en": "T"},
    "openDepartment": {"code": "203", "cn": "物理学院"},
    "campus": {"cn": "东区"},
}

EXAM_SAMPLE = {
    "id": 1,
    "examType": 2,
    "examDate": "2026-10-20",
    "startTime": "14:30",
    "endTime": "16:30",
    "examRooms": [{"room": "5101", "count": 30}],
    "lesson": {
        "course": {"code": "022063", "cn": "热力学与统计物理B"},
        "openDepartment": {"cn": "物理学院"},
    },
}


class ScheduleTests(unittest.TestCase):
    def test_parse_occupancies(self) -> None:
        index = parse_occupancies([LESSON_SAMPLE])
        self.assertIn("2304", index)
        records = index["2304"]
        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first.weekday, 1)
        self.assertEqual((first.start_period, first.end_period), (3, 4))
        self.assertEqual(first.week_start, 1)
        self.assertEqual(first.week_end, 15)
        self.assertEqual(first.teacher, "何志成")
        self.assertEqual(first.course_name, "热力学与统计物理B")

    def test_parse_exams(self) -> None:
        exams = parse_exams([EXAM_SAMPLE])
        self.assertEqual(len(exams), 1)
        exam = exams[0]
        self.assertEqual(exam.course_name, "热力学与统计物理B")
        self.assertEqual(exam.exam_type, "期末")
        self.assertEqual(exam.rooms, ("5101",))
        hits = filter_exams(exams, "统计物理")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].rooms, ("5101",))

    def test_teaching_week(self) -> None:
        self.assertEqual(teaching_week(date(2026, 9, 6), "2026-09-01"), 1)
        self.assertEqual(teaching_week(date(2026, 8, 30), "2026-09-01"), 0)
        self.assertEqual(teaching_week(date(2026, 10, 12), "2026-09-01"), 7)

    def test_resolve_day_offset(self) -> None:
        today = date(2026, 9, 6)
        day, label = resolve_day_offset("2304教室今天下午空闲吗", today)
        self.assertEqual((day, label), (date(2026, 9, 6), "今天"))
        day, label = resolve_day_offset("明天上午呢", today)
        self.assertEqual((day, label), (date(2026, 9, 7), "明天"))
        day, label = resolve_day_offset("周一下午有人吗", today)
        self.assertEqual(label, "星期一")
        self.assertEqual(day.weekday(), 0)
        self.assertGreater(day, today)

    def test_resolve_periods(self) -> None:
        now = datetime(2026, 9, 6, 15, 0)
        self.assertEqual(resolve_periods("今天下午空闲吗", now), (5, 8, "下午"))
        self.assertEqual(resolve_periods("上午有人吗", now), (1, 4, "上午"))
        self.assertEqual(resolve_periods("晚上呢", now), (9, 11, "晚上"))
        self.assertEqual(resolve_periods("三点有人吗", now), (1, 4, "上午"))
        self.assertEqual(resolve_periods("15点呢", now), (5, 8, "下午"))

    def test_format_room_answer_occupied(self) -> None:
        index = parse_occupancies([LESSON_SAMPLE])
        answer = format_room_answer(
            "2304",
            date(2026, 9, 8),
            "星期二",
            1,
            (1, 4),
            "上午",
            index["2304"],
        )
        self.assertIn("被占用", answer)
        self.assertIn("热力学与统计物理B", answer)
        self.assertIn("何志成", answer)

    def test_format_room_answer_free(self) -> None:
        index = parse_occupancies([LESSON_SAMPLE])
        answer = format_room_answer(
            "2304",
            date(2026, 9, 6),
            "今天",
            1,
            (5, 8),
            "下午",
            index["2304"],
        )
        self.assertIn("空闲", answer)

    def test_format_room_answer_week_out_of_range(self) -> None:
        index = parse_occupancies([LESSON_SAMPLE])
        answer = format_room_answer(
            "2304",
            date(2026, 9, 8),
            "星期二",
            20,
            (3, 4),
            "上午",
            index["2304"],
        )
        self.assertIn("空闲", answer)


if __name__ == "__main__":
    unittest.main()
