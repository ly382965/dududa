from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr
import asyncio
import re
from datetime import datetime

from .catalog import CatalogClient, fetched_at
from .schedule import (
    ROOM_WITH_SUFFIX,
    format_course_answer,
    format_exam_answer,
    format_room_answer,
    filter_exams,
    parse_exams,
    parse_occupancies,
    resolve_day_offset,
    resolve_periods,
    search_course_schedule,
    teaching_week,
)
from .reviews import REVIEW_INTENT_RE, format_review_answer, search_reviews

ROOM_QUERY_RE = r"(空闲|空着|被占|占用|占用着|有人|没人|没有人|上不上课|有没有课|教室|自习|课表|课程表|在不在|几个班|排课)"
ROOM_WEAK_INTENT_RE = r"(查|看|查询|查下|有没有)"
EXAM_QUERY_RE = r"(考试|在哪考|什么时候考|考哪里|安排在)"
EXAM_NAME_RE = r"([\u4e00-\u9fa5A-Za-z0-9]{2,20}?)(?:的)?(?:考试|在哪考|什么时候考)"
COURSE_QUERY_RE = r"(老师|在哪|在哪上|哪上|地点|哪里|哪开|上课|什么课|教什么|学期)"
CHAT_SKIP_RE = r"(哈哈|嘿嘿|hh|233|笑死|无语|卧槽|妈呀|绝了|绷|抽象|典|小丑|杂鱼|哭|难过|吃饭|睡觉|起床|晚安|拜拜|886|什么|啊这|属实|我去|牛啊|我|你|他|她|它|我们|你们|他们|早上|中午|晚上|今天|明天|昨天|现在|可能|应该|非常|特别|确实)"
COURSE_DIRECT_RE = r"^[\u4e00-\u9fa5A-Za-z0-9()（）\.\-]{2,14}$"


@register(
    "astrbot_plugin_ustc_classroom",
    "mmdustc",
    "USTC 教室空闲与考试安排查询（catalog.ustc.edu.cn）",
    "0.1.0",
)
class UstcClassroomPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        data_root = context.get_config().get("data_dir", "") or ""
        from pathlib import Path

        plugin_data = Path(__file__).resolve().parents[2] / "plugin_data" / "astrbot_plugin_ustc_classroom"
        self.client = CatalogClient(cache_dir=plugin_data)
        self._occupancy_index: dict[str, list] = {}
        self._exam_list: list = []
        self._loaded_semester: str = ""
        logger.info("USTC Classroom plugin loaded")

    async def _ensure_data(self) -> tuple[dict[str, list], list, str]:
        semester_id, semester_name = await self.client.current_semester()
        if self._loaded_semester != f"{semester_id}":
            raw_lessons = await self.client.lessons()
            self._occupancy_index = parse_occupancies(raw_lessons)
            raw_exams = await self.client.exams()
            self._exam_list = parse_exams(raw_exams)
            self._loaded_semester = f"{semester_id}"
            logger.info(
                "USTC Classroom data loaded: semester=%s(%s) rooms=%s exams=%s",
                semester_name,
                semester_id,
                len(self._occupancy_index),
                len(self._exam_list),
            )
        return self._occupancy_index, self._exam_list, semester_name

    @filter.command("教室", alias={"教室查询", "查教室"})
    async def classroom_command(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """查询教室是否空闲：/教室 2304 今天下午"""
        query = (query or "").strip()
        if not query:
            yield event.plain_result("用法：/教室 2304 [今天|明天|周X|星期X] [上午|下午|晚上|全天]")
            event.stop_event()
            return
        reply = await self._answer_room_query(query, event)
        yield event.plain_result(reply)
        event.stop_event()

    @filter.command("考试", alias={"考试查询", "查考试"})
    async def exam_command(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """查询考试安排：/考试 概率论"""
        query = (query or "").strip()
        if not query:
            yield event.plain_result("用法：/考试 课程名（如：/考试 概率论）")
            event.stop_event()
            return
        reply = await self._answer_exam_query(query, event)
        yield event.plain_result(reply)
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=300)
    async def classroom_listen(self, event: AstrMessageEvent):
        """@bot 的教室空闲/考试安排自然语言查询。"""
        if not getattr(event, "is_at_or_wake_command", False):
            return
        text = (event.message_str or "").strip()
        if not text or text.startswith("/"):
            return

        routed_intent = event.get_extra("routed_intent", None)
        if routed_intent in ("room_query", "course_query", "review_query", "exam_query"):
            args = event.get_extra("routed_args", {}) or {}
            room = str(args.get("room") or "").strip()
            course = str(args.get("course") or "").strip()
            teacher = str(args.get("teacher") or "").strip()
            if routed_intent == "room_query" and room:
                reply = await self._answer_room_query(room, event)
                yield event.plain_result(reply)
                event.stop_event()
                return
            if routed_intent == "course_query":
                query = " ".join([v for v in (teacher, course) if v])
                if not query:
                    query = text
                reply = await self._answer_course_query(query, event)
                yield event.plain_result(reply)
                event.stop_event()
                return
            if routed_intent == "review_query":
                query = " ".join([v for v in (teacher, course) if v]) or text
                reply = await self._answer_review_query(query, event)
                yield event.plain_result(reply)
                event.stop_event()
                return
            if routed_intent == "exam_query" and course:
                reply = await self._answer_exam_query(course, event)
                yield event.plain_result(reply)
                event.stop_event()
                return

        room_match = ROOM_WITH_SUFFIX.search(text) or _bare_room(text)
        if room_match:
            room = _extract_room(text, room_match)
            room_with_alpha = bool(room and re.search(r"[A-Za-z]", room))
            if room:
                if _contains(text, ROOM_QUERY_RE):
                    reply = await self._answer_room_query(f"{room} {text}", event)
                    yield event.plain_result(reply)
                    event.stop_event()
                    return
                if room_with_alpha and (_contains(text, ROOM_WEAK_INTENT_RE) or len(text) <= 12):
                    reply = await self._answer_room_query(f"{room} {text}", event)
                    yield event.plain_result(reply)
                    event.stop_event()
                    return
                if not room_with_alpha and _messages_is_just_room(text, room):
                    reply = await self._answer_room_query(f"{room} {text}", event)
                    yield event.plain_result(reply)
                    event.stop_event()
                    return

        if _contains(text, EXAM_QUERY_RE):
            name_match = _exam_name(text)
            if name_match:
                reply = await self._answer_exam_query(name_match, event)
                yield event.plain_result(reply)
                event.stop_event()
                return

        if _contains(text, COURSE_QUERY_RE):
            reply = await self._answer_course_query(text, event)
            yield event.plain_result(reply)
            event.stop_event()
            return

        if _course_name_direct(text):
            reply = await self._answer_course_query(text, event)
            if reply and not reply.startswith("没有查到"):
                yield event.plain_result(reply)
                event.stop_event()
                return

        if _contains(text, REVIEW_INTENT_RE):
            review_query = _course_query_term(text)
            if review_query:
                reply = await self._answer_review_query(review_query, event)
                yield event.plain_result(reply)
                event.stop_event()
                return

    async def _answer_review_query(self, query: str, event: AstrMessageEvent) -> str:
        try:
            results = await asyncio.to_thread(search_reviews, query)
        except Exception as exc:
            logger.warning("Review search failed: %s", exc)
            return "评课数据暂时读不出来，稍后再试试？"
        return format_review_answer(results, query)

    async def _answer_course_query(self, text: str, event: AstrMessageEvent) -> str:
        try:
            lessons = await self.client.lessons()
        except Exception as exc:
            logger.warning("Course data fetch failed: %s", exc)
            return "课程数据暂时拉取失败，稍后再试试？"
        query = _course_query_term(text)
        if not query:
            return "没看懂要查什么课。可以说「吴天数学分析」或「数学分析在哪上」。"
        matches = search_course_schedule(lessons, query)
        return format_course_answer(matches, query)

    async def _answer_room_query(self, query: str, event: AstrMessageEvent) -> str:
        try:
            index, _, semester_name = await self._ensure_data()
        except Exception as exc:
            logger.warning("Classroom data fetch failed: %s", exc)
            return "教室数据暂时拉取失败，稍后再试试？"
        room_match = ROOM_WITH_SUFFIX.search(query) or _bare_room(query)
        if not room_match:
            return "没看懂教室号。可以说「2304教室今天下午空闲吗」。"
        room = _extract_room(query, room_match)
        if not room:
            return "没看懂教室号。可以说「2304教室今天下午空闲吗」。"
        records = index.get(room)
        now = datetime.now()
        today = now.date()
        day_result = resolve_day_offset(query, today)
        if day_result is None:
            day, day_label = today, "今天"
        else:
            day, day_label = day_result
        periods = resolve_periods(query, now)
        if periods is None:
            start_p, end_p, period_label = 1, 11, "全天"
        else:
            start_p, end_p, period_label = periods
        week = teaching_week(day, await self._semester_start())
        return format_room_answer(
            room,
            day,
            day_label,
            week,
            (start_p, end_p),
            period_label,
            records or [],
        )

    async def _answer_exam_query(self, query: str, event: AstrMessageEvent) -> str:
        try:
            _, exams, _ = await self._ensure_data()
        except Exception as exc:
            logger.warning("Exam data fetch failed: %s", exc)
            return "考试数据暂时拉取失败，稍后再试试？"
        matches = filter_exams(exams, query)
        return format_exam_answer(matches, query)

    async def _semester_start(self) -> str:
        semester_id, _ = await self.client.current_semester()
        cached = self.client._read_cache(f"lessons_{semester_id}.json")
        semesters = await self.client._json("/api/teach/semester/list")
        selected = next(
            (item for item in semesters if item.get("isLast")), semesters[-1]
        )
        return str(selected.get("start") or "")

    async def terminate(self):
        await self.client.close()


def _bare_room(text: str):
    from .schedule import ROOM_RE

    match = ROOM_RE.search(text)
    return match.group(0) if match else None


def _extract_room(text: str, room_match) -> str | None:
    if hasattr(room_match, "group"):
        match = ROOM_WITH_SUFFIX.search(text)
        if match is not None:
            value = match.group(1) or match.group(2)
            if value:
                return str(value).upper()
        return str(room_match.group(0)).upper()
    return str(room_match).upper()


def _course_query_term(text: str) -> str | None:
    import re

    cleaned = re.sub(r"[\s，。！？、；:：()（）*·]+", " ", text.strip())
    remove_words = (
        "在哪上", "在哪教", "上什么", "查一下", "查下", "怎么样", "什么课", "属性",
        "查看", "查询", "上课", "在哪", "哪上", "地点", "哪里", "哪开", "老师",
        "教什么", "学期", "开课", "评价", "评课", "口碑", "推荐",
    )
    value = cleaned
    for word in remove_words:
        value = value.replace(word, " ")
    parts = [p for p in re.sub(r"\s+", " ", value).strip().split(" ") if p]
    if not parts:
        parts = [p for p in re.sub(r"\s+", " ", cleaned).strip().split(" ") if p]
        parts = [p for p in parts if len(p) >= 2]
    if not parts:
        return None
    return " ".join(parts[:4])


def _course_name_direct(text: str) -> bool:
    """纯课程名词短语（如"数学分析"）→ 触发课程查询；闲聊词排除。"""
    import re

    value = re.sub(r"[\s\u3000]+", "", text.strip())
    if not (2 <= len(value) <= 14):
        return False
    if "怎么样" in value or "评价" in value:
        return False
    if re.search(CHAT_SKIP_RE, value):
        return False
    return bool(re.fullmatch(COURSE_DIRECT_RE, value))


def _messages_is_just_room(text: str, room: str) -> bool:
    """消息整体就一个教室号（如 '5506'/'3C103'），排除公式/长句。"""
    import re

    value = re.sub(r"[\s\u3000#@：:，。；、]+", "", text.strip())
    if value.upper() == room.upper():
        return True
    if value.upper() == room.upper() + "教室":
        return True
    return False


def _contains(text: str, pattern: str) -> bool:
    import re

    return re.search(pattern, text) is not None


def _exam_name(text: str) -> str | None:
    import re

    match = re.search(EXAM_NAME_RE, text)
    if not match:
        return None
    name = match.group(1).strip()
    if len(name) < 2:
        return None
    return name
