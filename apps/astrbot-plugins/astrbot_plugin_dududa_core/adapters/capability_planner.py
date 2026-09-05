from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dududa.capabilities import (
    TOOL_COMPLETION_ALL_STEPS,
    ArgumentTemplate,
    ToolPlan,
    ToolPlanningRequest,
    ToolStep,
    tool_plan_digest,
)
from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision, DigestString, JsonValue
from dududa.errors import validation_error
from dududa.ports.capabilities import CapabilityRegistry
from dududa.ports.context import PortCallContext

ICOURSE_PUBLIC_QUERY_CAPABILITY_ID = "icourse.public-query.v2"
ICOURSE_INTENT_OPERATIONS = {
    "icourse.course.search": "course",
    "icourse.review.search": "review",
    "icourse.teacher.search": "teacher",
    "icourse.ranking.read": "ranking",
    "icourse.stats.read": "stats",
}
_ICOURSE_DEFAULT_LIMIT = 10
CURRICULUM_PUBLIC_QUERY_CAPABILITY_ID = "ustc.curriculum.public-query.v1"
CURRICULUM_INTENT_OPERATIONS = {
    "ustc.curriculum.overview.read": "overview",
    "ustc.curriculum.program.read": "program",
    "ustc.curriculum.course.read": "course",
    "ustc.curriculum.change.read": "change",
    "ustc.curriculum.comparison.read": "comparison",
    "ustc.curriculum.substitution.read": "substitution",
    "ustc.curriculum.shared.read": "shared",
    "ustc.curriculum.history.read": "history",
}
_CURRICULUM_DEFAULT_LIMIT = 6
_CURRICULUM_QUERY_MODIFIERS = frozenset(
    {
        "专业核心",
        "专业基础",
        "专业选修",
        "通修",
        "毕业论文",
        "必修",
        "选修",
        "普通主修",
        "少年班",
        "强基",
        "辅修",
        "双学位",
        "英才班",
    }
)
ACADEMIC_SEMESTERS_CAPABILITY_ID = "ustc.academic.semesters.list.v1"
ACADEMIC_LESSONS_CAPABILITY_ID = "ustc.academic.lessons.search.v1"
ACADEMIC_EXAMS_CAPABILITY_ID = "ustc.academic.exams.search.v1"
ACADEMIC_CALENDAR_CAPABILITY_ID = "ustc.academic.calendar.get.v1"
ACADEMIC_INTENT_CAPABILITIES = {
    "ustc.academic.semesters.list": ACADEMIC_SEMESTERS_CAPABILITY_ID,
    "ustc.academic.lesson.search": ACADEMIC_LESSONS_CAPABILITY_ID,
    "ustc.academic.exam.search": ACADEMIC_EXAMS_CAPABILITY_ID,
    "ustc.academic.calendar.read": ACADEMIC_CALENDAR_CAPABILITY_ID,
}
ACADEMIC_RUNTIME_CAPABILITY_IDS = frozenset(ACADEMIC_INTENT_CAPABILITIES.values())
_ACADEMIC_GENERIC_TERMS = frozenset(
    {
        "中国科大",
        "科大",
        "教务处",
        "教务系统",
        "学期",
        "开课",
        "开课信息",
        "课程表",
        "考试",
        "考试安排",
        "教学日历",
        "校历",
    }
)
_ACADEMIC_SEMESTER_ID_RE = re.compile(
    r"(?:学期\s*)?(?:id|编号)\s*(?:为|是|[:：#])?\s*(\d{1,8})",
    re.IGNORECASE,
)
_ACADEMIC_SEMESTER_TERM_RE = re.compile(r"20\d{2}\s*年?\s*[春夏秋](?:季)?(?:学期)?")
_ACADEMIC_DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
NOTIFAI_SEARCH_CAPABILITY_ID = "notifai.notices.search.v1"
NOTIFAI_GET_CAPABILITY_ID = "notifai.notices.get.v1"
NOTIFAI_CALENDAR_CAPABILITY_ID = "notifai.notices.calendar.v1"
NOTIFAI_DEADLINES_CAPABILITY_ID = "notifai.notices.deadlines.v1"
NOTIFAI_SOURCES_CAPABILITY_ID = "notifai.sources.list.v1"
NOTIFAI_CATEGORIES_CAPABILITY_ID = "notifai.categories.list.v1"
NOTIFAI_STATS_CAPABILITY_ID = "notifai.stats.read.v1"
NOTIFAI_INTENT_CAPABILITIES = {
    "notifai.notice.search": NOTIFAI_SEARCH_CAPABILITY_ID,
    "notifai.notice.get": NOTIFAI_GET_CAPABILITY_ID,
    "notifai.notice.calendar": NOTIFAI_CALENDAR_CAPABILITY_ID,
    "notifai.notice.deadlines": NOTIFAI_DEADLINES_CAPABILITY_ID,
    "notifai.source.list": NOTIFAI_SOURCES_CAPABILITY_ID,
    "notifai.category.list": NOTIFAI_CATEGORIES_CAPABILITY_ID,
    "notifai.stats.read": NOTIFAI_STATS_CAPABILITY_ID,
}
NOTIFAI_RUNTIME_CAPABILITY_IDS = frozenset(NOTIFAI_INTENT_CAPABILITIES.values())
_NOTIFAI_GENERIC_TERMS = frozenset(
    {
        "校园通知",
        "通知查询",
        "通知",
        "公告",
        "校园公告",
        "截止提醒",
        "来源",
        "分类",
        "统计",
    }
)
_NOTIFAI_NOTICE_ID_RE = re.compile(
    r"(?:通知\s*(?:id|编号)|notice[-_\s]?id)\s*(?:为|是|[:：#])?\s*([A-Za-z0-9][A-Za-z0-9._:-]{2,199})",
    re.IGNORECASE,
)
_NOTIFAI_MONTH_RE = re.compile(r"20\d{2}-\d{2}")
_NOTIFAI_WEEK_RE = re.compile(r"20\d{2}-W\d{2}", re.IGNORECASE)
YOUNG_SEARCH_CAPABILITY_ID = "ustc.young.activities.search.v1"
YOUNG_ACTIVITY_CAPABILITY_ID = "ustc.young.activity.get.v1"
YOUNG_FACETS_CAPABILITY_ID = "ustc.young.facets.list.v1"
YOUNG_STATUS_CAPABILITY_ID = "ustc.young.connection.status.v1"
YOUNG_INTENT_CAPABILITIES = {
    "ustc.young.activity.search": YOUNG_SEARCH_CAPABILITY_ID,
    "ustc.young.activity.get": YOUNG_ACTIVITY_CAPABILITY_ID,
    "ustc.young.facets.list": YOUNG_FACETS_CAPABILITY_ID,
    "ustc.young.connection.status": YOUNG_STATUS_CAPABILITY_ID,
}
YOUNG_RUNTIME_CAPABILITY_IDS = frozenset(YOUNG_INTENT_CAPABILITIES.values())
SHUTTLE_PUBLIC_QUERY_CAPABILITY_ID = "ustc.shuttle.public-query.v1"
_YOUNG_DEFAULT_LIMIT = 8
_YOUNG_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_YOUNG_GENERIC_TERMS = frozenset(
    {
        "二课",
        "第二课堂",
        "活动",
        "德智体美劳",
        "德育",
        "智育",
        "体育",
        "美育",
        "劳育",
        "今天",
        "明天",
        "后天",
        "本周",
        "周末",
    }
)
_ACTIVITY_ID_RE = re.compile(
    r"(?:活动\s*(?:id|编号)|\bid)\s*(?:为|是|[:：#])?\s*([A-Za-z0-9][A-Za-z0-9_-]{1,127})",
    re.IGNORECASE,
)
_RESULT_LIMIT_RE = re.compile(
    r"(?:最多(?:列(?:出)?)?|只列(?:出)?|列(?:出)?前|(?<!当)前)\s*"
    r"(?P<count>\d{1,2}|[一二两三四五六七八九十])\s*"
    r"(?:个|项|条|门|场|份)?"
)


class EntityQueryToolPlanner:
    """Turn model-extracted entities into one bounded schema-bound read query.

    Standard iCourse and curriculum intents select one high-level public query
    operation. Second-class intents select one existing read Capability and
    project its simple filters. The existing deterministic validator still owns
    membership and argument validity.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        ignored_entity_terms: frozenset[str] = frozenset(),
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        revision: ComponentRevision | None = None,
    ) -> None:
        if not isinstance(registry, CapabilityRegistry):
            raise TypeError("registry does not implement CapabilityRegistry")
        ignored = frozenset(_normalize_term(value) for value in ignored_entity_terms)
        if "" in ignored:
            raise ValueError("ignored_entity_terms must contain non-empty strings")
        self._registry = registry
        self._ignored_entity_terms = ignored
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._revision = revision or ComponentRevision(
            "astrbot.entity-query-tool-planner",
            "1.2.0",
            "single-step-campus-public-query-v1",
            DigestString(
                str(
                    canonical_digest(
                        {"planner": "entity-query-single-step-campus-public-query"},
                        domain="astrbot:tool-planner-artifact:v1",
                    )
                )
            ),
        )

    async def plan(
        self,
        request: ToolPlanningRequest,
        *,
        call: PortCallContext,
    ) -> ToolPlan:
        if not isinstance(request, ToolPlanningRequest):
            raise validation_error("invalid_tool_planning_request")
        self._validate_call(call)
        catalog = self._registry.snapshot_by_id(
            request.retrieval.catalog_snapshot_id,
            expected_digest=request.retrieval.catalog_digest,
        )
        icourse_operation = _icourse_operation(request.query.intent_ids)
        curriculum_operation = _curriculum_operation(request.query.intent_ids)
        young_capability_id = _young_capability(request.query.intent_ids)
        academic_capability_id = _academic_capability(request.query.intent_ids)
        notifai_capability_id = _notifai_capability(request.query.intent_ids)
        shuttle_requested = (
            "campus.shuttle" in request.query.preferred_categories
            or any(
                intent_id.startswith("ustc.shuttle.")
                for intent_id in request.query.intent_ids
            )
        )
        if (
            young_capability_id is None
            and icourse_operation is None
            and curriculum_operation is None
            and "campus.second-class" in request.query.preferred_categories
        ):
            young_capability_id = YOUNG_SEARCH_CAPABILITY_ID
        if (
            curriculum_operation is None
            and young_capability_id is None
            and academic_capability_id is None
            and notifai_capability_id is None
            and icourse_operation is None
            and "campus.curriculum" in request.query.preferred_categories
        ):
            curriculum_operation = _curriculum_operation_from_goal(
                request.query.natural_language_goal
            )
        if (
            academic_capability_id is None
            and young_capability_id is None
            and curriculum_operation is None
            and icourse_operation is None
            and "campus.academic" in request.query.preferred_categories
        ):
            academic_capability_id = _academic_capability_from_goal(
                request.query.natural_language_goal
            )
        if (
            academic_capability_id is None
            and notifai_capability_id is None
            and young_capability_id is None
            and curriculum_operation is None
            and icourse_operation is None
            and "campus.notifications" in request.query.preferred_categories
        ):
            notifai_capability_id = _notifai_capability_from_goal(
                request.query.natural_language_goal
            )
        candidates = request.retrieval.candidates
        if shuttle_requested:
            candidates = tuple(
                item
                for item in candidates
                if item.capability_id == SHUTTLE_PUBLIC_QUERY_CAPABILITY_ID
            )
        elif young_capability_id is not None:
            candidates = tuple(
                item
                for item in candidates
                if item.capability_id == young_capability_id
            )
        elif academic_capability_id is not None:
            candidates = tuple(
                item
                for item in candidates
                if item.capability_id == academic_capability_id
            )
        elif notifai_capability_id is not None:
            candidates = tuple(
                item
                for item in candidates
                if item.capability_id == notifai_capability_id
            )
        elif curriculum_operation is not None:
            candidates = tuple(
                item
                for item in candidates
                if item.capability_id == CURRICULUM_PUBLIC_QUERY_CAPABILITY_ID
            )
        elif icourse_operation is not None:
            public_query_candidates = tuple(
                item
                for item in candidates
                if item.capability_id == ICOURSE_PUBLIC_QUERY_CAPABILITY_ID
            )
            legacy_course_candidates = (
                tuple(
                    item
                    for item in candidates
                    if item.capability_id != ICOURSE_PUBLIC_QUERY_CAPABILITY_ID
                )
                if icourse_operation == "course"
                else ()
            )
            candidates = public_query_candidates + legacy_course_candidates

        selected = None
        arguments: Mapping[str, JsonValue] | None = None
        for candidate in candidates:
            if candidate.capability_id == SHUTTLE_PUBLIC_QUERY_CAPABILITY_ID:
                schema = self._registry.get_schema(catalog, candidate.input_schema)
                goal = request.query.natural_language_goal.strip()
                if not shuttle_requested or not goal:
                    continue
                projected = _query_arguments(
                    schema.document,
                    goal,
                    goal=goal,
                )
                if projected is not None:
                    selected = candidate
                    arguments = projected
                    break
                continue
            if candidate.capability_id in YOUNG_RUNTIME_CAPABILITY_IDS:
                if candidate.capability_id != young_capability_id:
                    continue
                schema = self._registry.get_schema(catalog, candidate.input_schema)
                projected = _young_arguments(
                    candidate.capability_id,
                    schema.document,
                    request,
                    self._ignored_entity_terms,
                    self._clock(),
                )
                if projected is not None:
                    selected = candidate
                    arguments = projected
                    break
                continue
            if candidate.capability_id in ACADEMIC_RUNTIME_CAPABILITY_IDS:
                if candidate.capability_id != academic_capability_id:
                    continue
                schema = self._registry.get_schema(catalog, candidate.input_schema)
                projected = _academic_arguments(
                    candidate.capability_id,
                    schema.document,
                    request,
                    self._ignored_entity_terms,
                )
                if projected is not None:
                    selected = candidate
                    arguments = projected
                    break
                continue
            if candidate.capability_id in NOTIFAI_RUNTIME_CAPABILITY_IDS:
                if candidate.capability_id != notifai_capability_id:
                    continue
                schema = self._registry.get_schema(catalog, candidate.input_schema)
                projected = _notifai_arguments(
                    candidate.capability_id,
                    schema.document,
                    request,
                    self._ignored_entity_terms,
                )
                if projected is not None:
                    selected = candidate
                    arguments = projected
                    break
                continue
            is_icourse_public_query = (
                candidate.capability_id == ICOURSE_PUBLIC_QUERY_CAPABILITY_ID
            )
            is_curriculum_public_query = (
                candidate.capability_id == CURRICULUM_PUBLIC_QUERY_CAPABILITY_ID
            )
            if is_icourse_public_query and icourse_operation is None:
                continue
            if is_curriculum_public_query and curriculum_operation is None:
                continue
            term = (
                _curriculum_query_term(
                    request,
                    self._ignored_entity_terms,
                    curriculum_operation,
                )
                if is_curriculum_public_query
                else _primary_query_term(
                    request,
                    self._ignored_entity_terms,
                    operation=icourse_operation,
                )
            )
            schema = self._registry.get_schema(catalog, candidate.input_schema)
            projected = _query_arguments(
                schema.document,
                term,
                goal=(
                    request.query.natural_language_goal
                    if is_icourse_public_query or is_curriculum_public_query
                    else None
                ),
                operation=(
                    icourse_operation
                    if is_icourse_public_query
                    else curriculum_operation
                    if is_curriculum_public_query
                    else None
                ),
                limit=(
                    _requested_result_limit(
                        request.query.natural_language_goal,
                        _ICOURSE_DEFAULT_LIMIT,
                    )
                    if is_icourse_public_query
                    else _requested_result_limit(
                        request.query.natural_language_goal,
                        _CURRICULUM_DEFAULT_LIMIT,
                    )
                    if is_curriculum_public_query
                    else None
                ),
            )
            if projected is not None:
                selected = candidate
                arguments = projected
                break
        if selected is None or arguments is None:
            raise validation_error("tool_planning_query_candidate_unavailable")

        operation_suffix = str(
            canonical_digest(
                {
                    "query_digest": request.query.query_digest,
                    "capability_id": selected.capability_id,
                    "definition_digest": selected.definition_digest,
                    "arguments": arguments,
                },
                domain="capability.logical-operation:v1",
            )
        ).rsplit(":", maxsplit=1)[1][:32]
        step = ToolStep(
            schema_version=1,
            step_id=f"step:{operation_suffix}",
            logical_operation_id=f"operation:{operation_suffix}",
            capability_id=selected.capability_id,
            definition_digest=selected.definition_digest,
            arguments=ArgumentTemplate(1, arguments, ()),
            purpose="answer_with_approved_read_query",
            depends_on=(),
            expected_output_schema=selected.output_schema,
        )
        values = {
            "schema_version": 1,
            "plan_id": f"tool-plan:{self._new_id()}",
            "query_digest": request.query.query_digest,
            "retrieval_result_digest": request.retrieval.result_digest,
            "steps": (step,),
            "completion_criteria": (TOOL_COMPLETION_ALL_STEPS,),
            "planner_revision": self._revision,
        }
        return ToolPlan(plan_digest=tool_plan_digest(values), **values)

    def _validate_call(self, call: PortCallContext) -> None:
        if not isinstance(call, PortCallContext):
            raise validation_error("invalid_tool_planning_call")
        now = self._clock()
        if call.cancellation.is_cancelled or call.deadline <= now:
            raise validation_error("tool_planning_call_inactive")

    def _new_id(self) -> str:
        value = self._id_factory()
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(character.isspace() for character in value)
        ):
            raise validation_error("invalid_tool_planner_id")
        return value


def _primary_query_term(
    request: ToolPlanningRequest,
    ignored_entity_terms: frozenset[str],
    *,
    operation: str | None = None,
) -> str:
    terms = tuple(
        value.strip()
        for value in request.query.entity_terms
        if value.strip() and _normalize_term(value) not in ignored_entity_terms
    )
    if operation == "teacher":
        teacher = _teacher_query_term(terms, request.query.natural_language_goal)
        if teacher is not None:
            return teacher
    if operation == "review":
        subject = _goal_first_query_term(
            terms,
            request.query.natural_language_goal,
        )
        if subject is not None:
            return subject
    if terms:
        return terms[0]
    goal = request.query.natural_language_goal.strip()
    if not goal:
        raise validation_error("tool_planning_query_term_missing")
    return goal


def _teacher_query_term(terms: tuple[str, ...], goal: str) -> str | None:
    compact_goal = _normalize_term(goal)
    for value in terms:
        compact = _normalize_term(value)
        if f"{compact}老师" in compact_goal or f"{compact}教师" in compact_goal:
            return value
    return None


def _goal_first_query_term(terms: tuple[str, ...], goal: str) -> str | None:
    compact_goal = _normalize_term(goal)
    candidates = tuple(value for value in terms if not _is_year_term(value)) or terms
    positioned = tuple(
        (position, index, value)
        for index, value in enumerate(candidates)
        if (position := compact_goal.find(_normalize_term(value))) >= 0
    )
    return min(positioned)[2] if positioned else None


def _is_year_term(value: str) -> bool:
    normalized = _normalize_term(value)
    if normalized.endswith(("年", "级")):
        normalized = normalized[:-1]
    if not normalized.isdigit():
        return False
    if len(normalized) == 4:
        return normalized.startswith("20")
    return len(normalized) == 2 and 15 <= int(normalized) <= 26


def _query_arguments(
    document: Mapping[str, JsonValue],
    term: str,
    *,
    goal: str | None = None,
    operation: str | None = None,
    limit: int | None = None,
) -> Mapping[str, JsonValue] | None:
    properties = document.get("properties")
    required = document.get("required")
    if not isinstance(properties, Mapping) or not isinstance(required, (list, tuple)):
        return None
    if "query" not in properties or set(required) != {"query"}:
        return None
    arguments: dict[str, JsonValue] = {"query": term}
    optional = {"goal": goal, "operation": operation, "limit": limit}
    for name, value in optional.items():
        if name in properties and value is not None:
            arguments[name] = value
    return arguments


def supports_entity_query_schema(document: Mapping[str, JsonValue]) -> bool:
    return (
        _query_arguments(
            document,
            "query",
            goal="query",
            operation="course",
            limit=_ICOURSE_DEFAULT_LIMIT,
        )
        is not None
    )


def supports_production_query_schema(
    capability_id: str,
    document: Mapping[str, JsonValue],
) -> bool:
    if supports_entity_query_schema(document):
        return True
    expected_required = {
        ACADEMIC_SEMESTERS_CAPABILITY_ID: frozenset(),
        ACADEMIC_LESSONS_CAPABILITY_ID: frozenset(),
        ACADEMIC_EXAMS_CAPABILITY_ID: frozenset(),
        ACADEMIC_CALENDAR_CAPABILITY_ID: frozenset(),
        NOTIFAI_SEARCH_CAPABILITY_ID: frozenset(),
        NOTIFAI_GET_CAPABILITY_ID: frozenset({"notice_id"}),
        NOTIFAI_CALENDAR_CAPABILITY_ID: frozenset(),
        NOTIFAI_DEADLINES_CAPABILITY_ID: frozenset(),
        NOTIFAI_SOURCES_CAPABILITY_ID: frozenset(),
        NOTIFAI_CATEGORIES_CAPABILITY_ID: frozenset(),
        NOTIFAI_STATS_CAPABILITY_ID: frozenset(),
        YOUNG_SEARCH_CAPABILITY_ID: frozenset(),
        YOUNG_ACTIVITY_CAPABILITY_ID: frozenset({"activity_id"}),
        YOUNG_FACETS_CAPABILITY_ID: frozenset({"facet"}),
        YOUNG_STATUS_CAPABILITY_ID: frozenset(),
    }.get(capability_id)
    if expected_required is None:
        return False
    properties = document.get("properties")
    required = document.get("required", ())
    return (
        isinstance(properties, Mapping)
        and isinstance(required, (list, tuple))
        and set(required) == set(expected_required)
        and expected_required <= set(properties)
    )


def _young_capability(intent_ids: tuple[str, ...]) -> str | None:
    for intent_id in intent_ids:
        capability_id = YOUNG_INTENT_CAPABILITIES.get(intent_id)
        if capability_id is not None:
            return capability_id
    return None


def _academic_capability(intent_ids: tuple[str, ...]) -> str | None:
    for intent_id in intent_ids:
        capability_id = ACADEMIC_INTENT_CAPABILITIES.get(intent_id)
        if capability_id is not None:
            return capability_id
    return None


def _academic_capability_from_goal(goal: str) -> str:
    compact = _normalize_term(goal)
    if any(value in compact for value in ("教学日历", "校历", "开学日期", "放假")):
        return ACADEMIC_CALENDAR_CAPABILITY_ID
    if any(value in compact for value in ("考试", "考场", "期末")):
        return ACADEMIC_EXAMS_CAPABILITY_ID
    if any(value in compact for value in ("开课", "教学班", "课程表", "任课老师")):
        return ACADEMIC_LESSONS_CAPABILITY_ID
    return ACADEMIC_SEMESTERS_CAPABILITY_ID


def _notifai_capability(intent_ids: tuple[str, ...]) -> str | None:
    for intent_id in intent_ids:
        capability_id = NOTIFAI_INTENT_CAPABILITIES.get(intent_id)
        if capability_id is not None:
            return capability_id
    if any(intent_id.startswith("notifai.") for intent_id in intent_ids):
        return NOTIFAI_SEARCH_CAPABILITY_ID
    return None


def _notifai_capability_from_goal(goal: str) -> str:
    compact = _normalize_term(goal)
    if any(value in compact for value in ("统计", "数量", "总数")):
        return NOTIFAI_STATS_CAPABILITY_ID
    if "来源" in compact:
        return NOTIFAI_SOURCES_CAPABILITY_ID
    if "分类" in compact:
        return NOTIFAI_CATEGORIES_CAPABILITY_ID
    if any(value in compact for value in ("截止", "到期")):
        return NOTIFAI_DEADLINES_CAPABILITY_ID
    if "通知日历" in compact or "通知月历" in compact:
        return NOTIFAI_CALENDAR_CAPABILITY_ID
    if _NOTIFAI_NOTICE_ID_RE.search(goal):
        return NOTIFAI_GET_CAPABILITY_ID
    return NOTIFAI_SEARCH_CAPABILITY_ID


def _notifai_arguments(
    capability_id: str,
    document: Mapping[str, JsonValue],
    request: ToolPlanningRequest,
    ignored_entity_terms: frozenset[str],
) -> Mapping[str, JsonValue] | None:
    goal = request.query.natural_language_goal.strip()
    if capability_id in {
        NOTIFAI_SOURCES_CAPABILITY_ID,
        NOTIFAI_CATEGORIES_CAPABILITY_ID,
        NOTIFAI_STATS_CAPABILITY_ID,
    }:
        return _declared_arguments(document, {})
    if capability_id == NOTIFAI_CALENDAR_CAPABILITY_ID:
        values: dict[str, JsonValue] = {}
        month = _NOTIFAI_MONTH_RE.search(goal)
        week = _NOTIFAI_WEEK_RE.search(goal)
        if month:
            values["month"] = month.group(0)
        elif week:
            values["week"] = week.group(0).upper()
        else:
            return None
        return _declared_arguments(document, values)
    if capability_id == NOTIFAI_DEADLINES_CAPABILITY_ID:
        match = re.search(r"(?:未来|最近|接下来)\s*(\d{1,3})\s*天", goal)
        days = max(1, min(int(match.group(1)), 365)) if match else 7
        return _declared_arguments(document, {"days": days, "page_size": 10})
    if capability_id == NOTIFAI_GET_CAPABILITY_ID:
        match = _NOTIFAI_NOTICE_ID_RE.search(goal)
        if match is None:
            return None
        return _declared_arguments(document, {"notice_id": match.group(1)})
    if capability_id != NOTIFAI_SEARCH_CAPABILITY_ID:
        return None
    terms = tuple(
        value.strip()
        for value in request.query.entity_terms
        if value.strip()
        and _normalize_term(value) not in ignored_entity_terms
        and _normalize_term(value) not in _NOTIFAI_GENERIC_TERMS
        and not _is_year_term(value)
    )
    keyword = terms[0] if terms else ""
    return _declared_arguments(
        document,
        {
            "keyword": keyword,
            "light": True,
            "page_size": _requested_result_limit(goal, 10),
        },
    )


def _academic_arguments(
    capability_id: str,
    document: Mapping[str, JsonValue],
    request: ToolPlanningRequest,
    ignored_entity_terms: frozenset[str],
) -> Mapping[str, JsonValue] | None:
    goal = request.query.natural_language_goal.strip()
    if capability_id == ACADEMIC_SEMESTERS_CAPABILITY_ID:
        return _declared_arguments(
            document,
            {
                "include_future": True,
                "limit": _requested_result_limit(goal, 20),
            },
        )
    if capability_id == ACADEMIC_CALENDAR_CAPABILITY_ID:
        dates = _ACADEMIC_DATE_RE.findall(goal)
        values: dict[str, JsonValue] = {}
        if dates:
            values["start_date"] = dates[0]
        if len(dates) > 1:
            values["end_date"] = dates[1]
        return _declared_arguments(document, values)
    if capability_id not in {ACADEMIC_LESSONS_CAPABILITY_ID, ACADEMIC_EXAMS_CAPABILITY_ID}:
        return None

    terms = tuple(
        value.strip()
        for value in request.query.entity_terms
        if value.strip()
        and _normalize_term(value) not in ignored_entity_terms
        and _normalize_term(value) not in _ACADEMIC_GENERIC_TERMS
        and not _is_year_term(value)
        and _ACADEMIC_SEMESTER_TERM_RE.fullmatch(value.strip()) is None
    )
    values = {
        "query": terms[0] if terms else "",
        "semester": goal,
        "limit": _requested_result_limit(goal, 10),
    }
    if match := _ACADEMIC_SEMESTER_ID_RE.search(goal):
        values["semester_id"] = int(match.group(1))
    return _declared_arguments(document, values)


def _young_arguments(
    capability_id: str,
    document: Mapping[str, JsonValue],
    request: ToolPlanningRequest,
    ignored_entity_terms: frozenset[str],
    now: datetime,
) -> Mapping[str, JsonValue] | None:
    goal = request.query.natural_language_goal.strip()
    if capability_id == YOUNG_STATUS_CAPABILITY_ID:
        return _declared_arguments(document, {})
    if capability_id == YOUNG_FACETS_CAPABILITY_ID:
        compact = _normalize_term(goal)
        facet = (
            "label"
            if "标签" in compact
            else "department"
            if any(value in compact for value in ("部门", "单位", "学院", "组织"))
            else "module"
        )
        return _declared_arguments(document, {"facet": facet})
    if capability_id == YOUNG_ACTIVITY_CAPABILITY_ID:
        match = _ACTIVITY_ID_RE.search(goal)
        if match is None:
            return None
        return _declared_arguments(
            document,
            {
                "activity_id": match.group(1),
                "include_children": any(
                    value in goal for value in ("子活动", "所有场次", "第一场")
                ),
            },
        )
    if capability_id != YOUNG_SEARCH_CAPABILITY_ID:
        return None

    terms = tuple(
        value.strip()
        for value in request.query.entity_terms
        if value.strip()
        and _normalize_term(value) not in ignored_entity_terms
        and _normalize_term(value) not in _YOUNG_GENERIC_TERMS
        and not _is_year_term(value)
    )
    arguments: dict[str, JsonValue] = {
        "query": terms[0] if len(terms) == 1 else "",
        "state": _young_state(goal),
        "limit": _requested_result_limit(goal, _YOUNG_DEFAULT_LIMIT),
    }
    window = _young_time_window(goal, now)
    if window is not None:
        arguments["start_time"], arguments["end_time"] = window
    return _declared_arguments(document, arguments)


def _declared_arguments(
    document: Mapping[str, JsonValue],
    values: Mapping[str, JsonValue],
) -> Mapping[str, JsonValue] | None:
    properties = document.get("properties")
    required = document.get("required", ())
    if not isinstance(properties, Mapping) or not isinstance(required, (list, tuple)):
        return None
    required_names = set(required)
    if not required_names <= set(values) or not required_names <= set(properties):
        return None
    return {name: value for name, value in values.items() if name in properties}


def _young_state(goal: str) -> str:
    compact = _normalize_term(goal)
    return (
        "history"
        if any(value in compact for value in ("历史", "过去", "最近一周", "已结束", "结束的"))
        else "applying"
    )


def _young_time_window(goal: str, now: datetime) -> tuple[str, str] | None:
    compact = _normalize_term(goal)
    if any(value in compact for value in ("报名截止", "截止报名")):
        return None
    local_now = now.astimezone(_YOUNG_LOCAL_TIMEZONE)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start.replace(hour=23, minute=59, second=59)
    start: datetime | None = None
    end: datetime | None = None
    if "最近一周" in compact:
        start, end = local_now - timedelta(days=7), local_now
    elif "今晚" in compact:
        start, end = day_start.replace(hour=18), day_end
    elif "后天" in compact:
        start, end = day_start + timedelta(days=2), day_end + timedelta(days=2)
    elif "明天" in compact:
        start, end = day_start + timedelta(days=1), day_end + timedelta(days=1)
    elif "今天" in compact:
        start, end = day_start, day_end
    elif "周末" in compact:
        if local_now.weekday() == 6:
            start = day_start
        else:
            start = day_start + timedelta(days=(5 - local_now.weekday()) % 7)
        end = start + timedelta(days=(0 if local_now.weekday() == 6 else 1), hours=23, minutes=59, seconds=59)
    elif "本周" in compact:
        start = local_now
        end = day_end + timedelta(days=6 - local_now.weekday())
    else:
        match = re.search(r"未来([一二两三四五六七]|\d+)天", compact)
        if match is not None:
            count = _small_day_count(match.group(1))
            start, end = local_now, day_end + timedelta(days=count - 1)
    if start is None or end is None:
        return None
    return _local_iso(start), _local_iso(end)


def _small_day_count(value: str) -> int:
    names = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
    result = names.get(value, int(value) if value.isdigit() else 1)
    return max(1, min(result, 7))


def _requested_result_limit(goal: str, default: int) -> int:
    """Bound plain listings while retaining candidates for later ranking."""

    normalized = _normalize_term(goal)
    if re.search(r"排序|排名|排行|从高到低|从低到高|最高|最低|最大|最小", normalized):
        return default
    match = _RESULT_LIMIT_RE.search(normalized)
    if match is None:
        return default
    raw = match.group("count")
    names = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    requested = int(raw) if raw.isdigit() else names[raw]
    return max(1, min(requested, default))


def _local_iso(value: datetime) -> str:
    return value.replace(tzinfo=None).isoformat(timespec="seconds")


def _icourse_operation(intent_ids: tuple[str, ...]) -> str | None:
    for intent_id in intent_ids:
        operation = ICOURSE_INTENT_OPERATIONS.get(intent_id)
        if operation is not None:
            return operation
    if any(intent_id.startswith("icourse.") for intent_id in intent_ids):
        return "course"
    return None


def _curriculum_operation(intent_ids: tuple[str, ...]) -> str | None:
    for intent_id in intent_ids:
        operation = CURRICULUM_INTENT_OPERATIONS.get(intent_id)
        if operation is not None:
            return operation
    if any(intent_id.startswith("ustc.curriculum.") for intent_id in intent_ids):
        return "program"
    return None


def _curriculum_operation_from_goal(goal: str) -> str:
    compact = _normalize_term(goal)
    operation_markers = (
        ("substitution", ("替代", "互换", "顶替", "等价课程")),
        ("change", ("变化", "变动", "改了", "新增", "移出", "调整")),
        (
            "comparison",
            ("对比", "比较", "区别", "差别", "少年班", "强基", "辅修", "双学位", "英才班"),
        ),
        (
            "shared",
            (
                "共享课程",
                "共同课程",
                "共同使用",
                "共用",
                "最多专业",
                "哪些专业都",
                "覆盖专业",
                "多少个专业代码",
            ),
        ),
        ("history", ("历年", "历史", "沿革", "最早", "首次出现")),
        ("overview", ("数据范围", "快照", "多少份方案", "更新时间", "是否官方")),
    )
    for operation, markers in operation_markers:
        if any(marker in compact for marker in markers):
            return operation
    if re.search(r"(?i)\b(?:[A-Z]{2,}\d[A-Z0-9*.-]*|\d{6}[A-Z]?)\b", goal):
        return "course"
    return "program"


def _curriculum_query_term(
    request: ToolPlanningRequest,
    ignored_entity_terms: frozenset[str],
    operation: str | None,
) -> str:
    if operation == "overview":
        return ""
    terms = tuple(
        value.strip()
        for value in request.query.entity_terms
        if value.strip()
        and _normalize_term(value) not in ignored_entity_terms
        and _normalize_term(value) not in _CURRICULUM_QUERY_MODIFIERS
        and not _is_year_term(value)
    )
    if operation == "substitution":
        return " ".join(terms) if terms else request.query.natural_language_goal.strip()
    if operation == "comparison" and terms:
        return " ".join(terms[:2])
    if terms:
        return terms[0]
    if operation == "shared":
        return ""
    goal = request.query.natural_language_goal.strip()
    if not goal:
        raise validation_error("tool_planning_query_term_missing")
    return goal


def _normalize_term(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("entity term must be str")
    return "".join(value.split()).casefold()


__all__ = [
    "ACADEMIC_INTENT_CAPABILITIES",
    "ACADEMIC_RUNTIME_CAPABILITY_IDS",
    "CURRICULUM_INTENT_OPERATIONS",
    "CURRICULUM_PUBLIC_QUERY_CAPABILITY_ID",
    "ICOURSE_INTENT_OPERATIONS",
    "NOTIFAI_INTENT_CAPABILITIES",
    "NOTIFAI_RUNTIME_CAPABILITY_IDS",
    "YOUNG_INTENT_CAPABILITIES",
    "YOUNG_RUNTIME_CAPABILITY_IDS",
    "EntityQueryToolPlanner",
    "supports_entity_query_schema",
    "supports_production_query_schema",
]
