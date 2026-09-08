from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .catalog import text

# USTC 教室号：2304、5101、N210、GF103、3A102、2106、西校区等
ROOM_TOKEN = r"(?:GF|NF|SF|N|S|W)?(?:[A-Z]?\d{3,4}[A-Z]?|\d[A-Z]\d{3,4})"
ROOM_RE = re.compile(ROOM_TOKEN)
ROOM_WITH_SUFFIX = re.compile(rf"(?:({ROOM_TOKEN})\s*教室|教室\s*({ROOM_TOKEN}))")

# 排课行："1~15周 2304 :2(3,4) 何志成" / "2304: 2(3,4)"
SCHEDULE_ROW = re.compile(
    r"(?:(\d+)\s*[~\-—]\s*(\d+)\s*周|(第?\s*(\d+)\s*周))"
    r"\s*("
    + ROOM_TOKEN
    + r")\s*[:：]?\s*(\d)\s*[（(]\s*(\d+)\s*[,，]\s*(\d+)\s*[)）]"
    r"\s*(.*)"
)

# 简单行（无周次）："2304: 2(3,4)"
BARE_ROW = re.compile(
    r"("
    + ROOM_TOKEN
    + r")\s*[:：]?\s*(\d)\s*[（(]\s*(\d+)\s*[,，]\s*(\d+)\s*[)）]"
)

WEEKDAY_WORDS = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
}

CN_HOURS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
    "十三": 13, "十四": 14, "十五": 15, "十六": 16, "十七": 17, "十八": 18,
    "十九": 19, "二十": 20, "二十一": 21, "二十二": 22, "二十三": 23,
}

PERIOD_LABELS = {
    1: "1-2节(上午)", 2: "1-2节(上午)", 3: "3-4节(上午)", 4: "3-4节(上午)",
    5: "5-6节(下午)", 6: "5-6节(下午)", 7: "7-8节(下午)", 8: "7-8节(下午)",
    9: "9-10节(晚上)", 10: "9-10节(晚上)", 11: "11节(晚上)",
}


@dataclass(frozen=True, slots=True)
class Occupancy:
    room: str
    weekday: int
    start_period: int
    end_period: int
    week_start: int
    week_end: int
    course_name: str
    teacher: str
    department: str


@dataclass(frozen=True, slots=True)
class Exam:
    course_name: str
    course_code: str
    exam_type: str
    exam_date: str
    start_time: str
    end_time: str
    rooms: tuple[str, ...]


def parse_occupancies(lessons: list[dict[str, Any]]) -> dict[str, list[Occupancy]]:
    """把课程列表解析成 教室 -> 占用记录 的索引。"""
    index: dict[str, list[Occupancy]] = {}
    for raw in lessons:
        if not isinstance(raw, dict):
            continue
        course = raw.get("course") if isinstance(raw.get("course"), dict) else {}
        department = (
            raw.get("openDepartment")
            if isinstance(raw.get("openDepartment"), dict)
            else {}
        )
        course_name = text(course.get("cn"))
        teacher = text(raw.get("teacherAssignmentList"))
        dept_name = text(department.get("cn"))
        rich = raw.get("dateTimePlacePersonText")
        rich_text = rich.get("cn") if isinstance(rich, dict) else text(rich)
        plain_text = text(raw.get("dateTimePlaceText"))
        seen: set[tuple] = set()
        rich_hits = 0
        for line in (rich_text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            for match in SCHEDULE_ROW.finditer(line):
                week_start = int(match.group(1) or match.group(4) or 0)
                week_end = int(match.group(2) or match.group(4) or 0)
                room = match.group(5)
                weekday = int(match.group(6)) - 1
                start_p = int(match.group(7))
                end_p = int(match.group(8))
                teacher_part = (match.group(9) or "").strip()
                occupant = teacher_part or teacher
                key = (room, weekday, start_p, end_p, week_start, week_end)
                if key in seen:
                    continue
                seen.add(key)
                rich_hits += 1
                index.setdefault(room.upper(), []).append(
                    Occupancy(
                        room=room,
                        weekday=weekday,
                        start_period=start_p,
                        end_period=end_p,
                        week_start=week_start,
                        week_end=week_end,
                        course_name=course_name,
                        teacher=occupant,
                        department=dept_name,
                    )
                )
        if rich_hits:
            continue
        for match in BARE_ROW.finditer(plain_text):
            room = match.group(1)
            weekday = int(match.group(2)) - 1
            start_p = int(match.group(3))
            end_p = int(match.group(4))
            key = (room, weekday, start_p, end_p, 0, 0)
            if key in seen:
                continue
            seen.add(key)
            index.setdefault(room.upper(), []).append(
                Occupancy(
                    room=room,
                    weekday=weekday,
                    start_period=start_p,
                    end_period=end_p,
                    week_start=0,
                    week_end=0,
                    course_name=course_name,
                    teacher=teacher,
                    department=dept_name,
                )
            )
    for records in index.values():
        records.sort(key=lambda o: (o.weekday, o.start_period))
    return index


def search_course_schedule(
    lessons: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """按教师名和/或课程名搜索开课排课（正向查询）。"""
    compact_q = re.sub(r"[\s，。！？、；:：()（）*·]+", "", query)
    if not compact_q or len(compact_q) < 2:
        return []
    teacher_pool = _collect_teacher_pool(lessons)
    query_teachers = [
        name for name in teacher_pool if name and name in compact_q
    ]
    strict: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for raw in lessons:
        if not isinstance(raw, dict):
            continue
        course = raw.get("course") if isinstance(raw.get("course"), dict) else {}
        cn = str(course.get("cn") or "")
        code = str(course.get("code") or "")
        person = raw.get("dateTimePlacePersonText")
        ptext = str(person.get("cn")) if isinstance(person, dict) else str(person or "")
        teacher_list = raw.get("teacherAssignmentList")
        teacher_text = ""
        if isinstance(teacher_list, list):
            for item in teacher_list:
                if isinstance(item, dict):
                    teacher_text += str(item.get("cn") or "") + " "
        haystack = (cn + code + teacher_text + ptext)
        hay = re.sub(r"[\s，。！？、；:：()（）*·]+", "", haystack).casefold()
        teacher_low = re.sub(r"[\s，。！？、；:：()（）*·]+", "", teacher_text).casefold()
        course_low = re.sub(r"[\s，。！？、；:：()（）*·]+", "", cn).casefold()
        if compact_q.casefold() in hay:
            strict.append(_lesson_hit(cn, code, teacher_text, ptext))
            continue
        teacher_hit = query_teachers and any(t.casefold() in teacher_low for t in query_teachers)
        course_part = compact_q
        for t in query_teachers:
            course_part = course_part.replace(t, "")
        course_hit = course_part and course_part.casefold() in course_low
        if teacher_hit and course_hit:
            strict.append(_lesson_hit(cn, code, teacher_text, ptext))
            continue
        if teacher_hit or course_hit:
            candidates.append(_lesson_hit(cn, code, teacher_text, ptext))
            continue
        ngrams = _ngrams(compact_q, 2, 4)
        covered = set()
        for gram, start in ngrams:
            if gram.casefold() in hay:
                covered.update(range(start, start + len(gram)))
        if len(covered) >= max(2, int(len(compact_q) * 0.8)):
            candidates.append(_lesson_hit(cn, code, teacher_text, ptext))
    chosen = strict if strict else candidates
    chosen.sort(key=lambda h: _match_score(h, compact_q), reverse=True)
    return chosen[:10]


def _collect_teacher_pool(lessons: list[dict[str, Any]]) -> list[str]:
    pool: set[str] = set()
    for raw in lessons:
        if not isinstance(raw, dict):
            continue
        teacher_list = raw.get("teacherAssignmentList")
        if isinstance(teacher_list, list):
            for item in teacher_list:
                if isinstance(item, dict):
                    name = str(item.get("cn") or "")
                    if name:
                        pool.add(name)
    return sorted(pool, key=len, reverse=True)


def _lesson_hit(cn: str, code: str, teacher_text: str, ptext: str) -> dict[str, Any]:
    return {
        "course_name": cn,
        "course_code": code,
        "teacher": teacher_text.strip(),
        "schedule": ptext.strip(),
    }


def _match_score(hit: dict[str, Any], query: str) -> tuple[int, int, int]:
    """排序：教师名全命中(2) > 课程名全命中(2,0) > 部分词命中(1) > 弱匹配(0)。"""
    name = hit["course_name"].replace(" ", "")
    teacher = hit["teacher"].replace(" ", "")
    query = query.casefold()
    name_low = name.casefold()
    teacher_low = teacher.casefold()
    score = 0
    if query and (query in name_low or query in teacher_low):
        if query in teacher_low:
            score = 3
        else:
            score = 2
    else:
        for size in (4, 3, 2):
            for i in range(0, len(query) - size + 1):
                part = query[i : i + size]
                if part in teacher_low:
                    score = max(score, 2)
                elif part in name_low:
                    score = max(score, 1)
    return (score, len(hit.get("schedule", "")), len(name))


def _query_parts(query: str) -> list[str]:
    parts: list[str] = []
    for size in (4, 3, 2):
        for i in range(0, len(query) - size + 1):
            parts.append(query[i : i + size])
    return parts


def _ngrams(text: str, low: int, high: int) -> list[tuple[str, int]]:
    values: list[tuple[str, int]] = []
    for size in range(low, high + 1):
        for index in range(0, len(text) - size + 1):
            values.append((text[index : index + size], index))
    return values


def parse_exams(raw_exams: list[dict[str, Any]]) -> list[Exam]:
    exams: list[Exam] = []
    type_names = {1: "期中", 2: "期末", 21: "期末", 3: "补考", 4: "缓考"}
    for raw in raw_exams:
        if not isinstance(raw, dict):
            continue
        lesson = raw.get("lesson") if isinstance(raw.get("lesson"), dict) else {}
        course = lesson.get("course") if isinstance(lesson.get("course"), dict) else {}
        general = not lesson and "courseName" in raw
        raw_type = raw.get("examType")
        batch = raw.get("batch") or text(raw.get("examBatch"))
        rooms_raw = raw.get("examRooms", []) if isinstance(raw.get("examRooms"), list) else []
        if general and raw.get("room"):
            rooms_raw = [{"room": raw.get("room")}]
        room_names = tuple(
            str(room.get("room") or "")
            for room in rooms_raw
            if isinstance(room, dict) and room.get("room")
        )
        name = text(raw.get("courseName")) if general else text(course.get("cn"))
        code = text(raw.get("courseCode")) if general else text(course.get("code"))
        exams.append(
            Exam(
                course_name=name,
                course_code=code,
                exam_type=batch or type_names.get(raw_type, f"类型{raw_type}"),
                exam_date=text(raw.get("examDate")),
                start_time=text(raw.get("startTime")),
                end_time=text(raw.get("endTime")),
                rooms=room_names,
            )
        )
    return exams


def teaching_week(today: date, semester_start: str) -> int:
    """教学周次：第一周周一 = 学期起始日所在周的周一。"""
    start = date.fromisoformat(semester_start[:10])
    first_monday = start - timedelta(days=start.weekday())
    if today < first_monday:
        return 0
    return (today - first_monday).days // 7 + 1


def resolve_day_offset(text_input: str, today: date) -> tuple[date, str] | None:
    """解析 今天/明天/后天/周X/星期X/下周X -> (日期, 描述)。"""
    if "后天" in text_input:
        return today + timedelta(days=2), "后天"
    if "明天" in text_input:
        return today + timedelta(days=1), "明天"
    if "今天" in text_input or "今日" in text_input:
        return today, "今天"
    match = re.search(r"(?:下?)(?:周|星期|礼拜)([一二三四五六日天])", text_input)
    if match:
        weekday = WEEKDAY_WORDS[match.group(1)]
        is_next_week = text_input[match.start():].startswith(("下周", "下星期"))
        candidate = today + timedelta(days=(weekday - today.weekday()) % 7)
        if candidate == today and not is_next_week:
            return candidate, f"本周星期{match.group(1)}"
        if candidate <= today or is_next_week:
            candidate += timedelta(days=7)
        return candidate, f"星期{match.group(1)}"
    return None


def resolve_periods(text_input: str, now: datetime) -> tuple[int, int, str] | None:
    """解析 上午/下午/晚上/X点/全天 -> (起始节, 结束节, 描述)。"""
    if "全天" in text_input or "一天" in text_input:
        return 1, 11, "全天"
    if "上午" in text_input or "早上" in text_input or "早晨" in text_input:
        return 1, 4, "上午"
    if "下午" in text_input or "午后" in text_input:
        return 5, 8, "下午"
    if "晚上" in text_input or "夜里" in text_input or "晚自习" in text_input:
        return 9, 11, "晚上"
    hour = now.hour
    if "中午" in text_input:
        return 4, 5, "中午"
    match = re.search(r"(\d{1,2})\s*[点:：]", text_input)
    if match:
        hour = int(match.group(1))
    else:
        cn_match = re.search(
            r"([零〇一二两三四五六七八九十]{1,3})\s*[点:：]", text_input
        )
        if cn_match:
            hour = CN_HOURS.get(cn_match.group(1), hour)
    if hour < 12:
        return 1, 4, "上午"
    if hour < 13:
        return 4, 5, "中午"
    if hour < 18:
        return 5, 8, "下午"
    return 9, 11, "晚上"


def describe_periods(start: int, end: int) -> str:
    return f"第{start}-{end}节"


def format_room_answer(
    room: str,
    day: date,
    day_label: str,
    week: int,
    periods: tuple[int, int],
    period_label: str,
    records: list[Occupancy],
) -> str:
    weekday = day.weekday()
    start_p, end_p = periods
    hits = [
        o
        for o in records
        if o.weekday == weekday
        and o.start_period <= end_p
        and o.end_period >= start_p
        and (o.week_end == 0 or (o.week_start <= week <= o.week_end))
    ]
    head = f"{room} {day_label}（{day.month}月{day.day}日 第{week}周 {period_label}）"
    if not records:
        return f"{head}：本学期没有任何排课，全天空闲。"
    if not hits:
        return f"{head}：这个时段没有排课，空闲。"
    lines = [f"{head}：被占用（{len(hits)} 门课）"]
    for o in hits[:6]:
        weeks = (
            f"第{o.week_start}-{o.week_end}周"
            if o.week_start and o.week_end
            else "全学期"
        )
        lines.append(
            f"· {describe_periods(o.start_period, o.end_period)}《{o.course_name}》"
            f"{o.teacher or '教师未排'}（{o.department or '未知院系'}，{weeks}）"
        )
    if len(hits) > 6:
        lines.append(f"…等共 {len(hits)} 门课")
    return "\n".join(lines)


def format_exam_answer(matches: list[Exam], query: str) -> str:
    if not matches:
        return f"没有查到「{query}」相关的考试安排。"
    lines: list[str] = []
    for exam in matches[:5]:
        rooms = "、".join(exam.rooms) if exam.rooms else "地点未公布"
        time_text = (
            f"{exam.exam_date} {exam.start_time}-{exam.end_time}"
            if exam.start_time
            else f"{exam.exam_date}（具体时间未公布）"
        )
        lines.append(
            f"·《{exam.course_name}》{exam.exam_type}：{time_text}，地点：{rooms}"
        )
    if len(matches) > 5:
        lines.append(f"…共 {len(matches)} 场相关考试")
    return "查到以下考试安排：\n" + "\n".join(lines)


def filter_exams(exams: list[Exam], query: str) -> list[Exam]:
    query = query.strip().casefold()
    if not query:
        return []
    compact = query.replace(" ", "")
    hits: list[Exam] = []
    for exam in exams:
        searchable = (
            f"{exam.course_name}{exam.course_code}{exam.exam_type}"
            f"{exam.exam_date}{exam.rooms and ''.join(exam.rooms)}"
        ).casefold().replace(" ", "")
        if compact in searchable:
            hits.append(exam)
    hits.sort(key=lambda e: (e.exam_date, e.start_time))
    return hits


def format_course_answer(matches: list[dict[str, Any]], query: str) -> str:
    if not matches:
        return "没有查到「" + query + "」相关的开课排课。"
    lines: list[str] = []
    for match in matches[:4]:
        teacher = match["teacher"] or ""
        course = match["course_name"]
        schedule = match["schedule"]
        entries: list[str] = []
        if schedule:
            for line in schedule.splitlines():
                line = line.strip()
                if not line:
                    continue
                week_part, rest = _split_schedule_line(line)
                formatted = _format_schedule(rest)
                if week_part:
                    entries.append(week_part + " " + formatted)
                else:
                    entries.append(formatted)
        if entries:
            lines.append(
                "【" + course + "】" + teacher + "老师："
            )
            for entry in entries[:5]:
                lines.append(entry)
        else:
            lines.append("【" + course + "】" + teacher + "老师：本周暂无排课")
    if len(matches) > 4:
        lines.append("…等共 " + str(len(matches)) + " 条匹配")
    return "\n".join(lines)


def _split_schedule_line(line: str) -> tuple[str, str]:
    """'2~18周 2105 :1(3,4) 罗罗' -> ('2~18周', '2105 :1(3,4) 罗罗')"""
    match = re.match(r"^(.{1,12}?周)\s*(.*)$", line)
    if match:
        return match.group(1), match.group(2)
    return "", line


_WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")


def _format_schedule(rest: str) -> str:
    """'2105 :1(3,4) 罗罗' -> '周一第3,4节 2105教室'"""
    text = re.sub(r"\s+", " ", rest.strip())
    match = re.match(
        r"^.*?([A-Za-z0-9]+)\s*[:：]?\s*(\d)\s*\((\d+(?:,\d+)*)\)\s*(.*)$",
        text,
    )
    if not match:
        return text
    room = match.group(1)
    weekday = int(match.group(2))
    periods = match.group(3)
    teacher = match.group(4)
    weekday_name = _WEEKDAY_NAMES[weekday - 1] if 1 <= weekday <= 7 else str(weekday)
    result = "周" + weekday_name + "第" + periods.replace(",", ",") + "节"
    result += " " + room + "教室"
    if teacher:
        result += " " + teacher
    return result


__all__ = [
    "Occupancy",
    "Exam",
    "parse_occupancies",
    "parse_exams",
    "teaching_week",
    "resolve_day_offset",
    "resolve_periods",
    "describe_periods",
    "format_room_answer",
    "format_exam_answer",
    "filter_exams",
    "search_course_schedule",
    "format_course_answer",
    "ROOM_RE",
    "ROOM_WITH_SUFFIX",
]
