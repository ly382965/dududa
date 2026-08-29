from __future__ import annotations

import csv
import io
import json
import re
import time
from typing import Any

import httpx

from .common import fetched_at

CURRICULUM_OPERATIONS = (
    "overview",
    "program",
    "course",
    "change",
    "comparison",
    "substitution",
    "shared",
    "history",
)

_DIMENSIONS = {
    "通修": "generalEducation",
    "专业基础": "majorFoundation",
    "专业核心": "majorCore",
    "专业选修": "majorElective",
    "毕业论文": "graduationThesis",
}
_DIMENSION_NAMES = {value: key for key, value in _DIMENSIONS.items()}
_GENERIC_QUERY_TERMS = (
    "中科大",
    "中国科大",
    "培养方案",
    "培养计划",
    "课程体系",
    "课程要求",
    "帮我查",
    "查询",
    "看一下",
    "有哪些",
    "是什么",
    "怎么样",
    "级",
)


class CurriculumClient:
    """Query the public curriculum research snapshot, never the live SIS."""

    def __init__(
        self,
        base_url: str = "https://docs.mmdustc.top/curriculum/data",
        *,
        cache_ttl_seconds: float = 600.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._cache_ttl_seconds = cache_ttl_seconds
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0),
            follow_redirects=True,
            transport=transport,
        )
        self._cache: dict[str, tuple[float, object]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def public_query(
        self,
        query: str,
        goal: str = "",
        operation: str = "program",
        limit: int = 6,
    ) -> dict[str, Any]:
        operation = operation.casefold().strip()
        if operation not in CURRICULUM_OPERATIONS:
            raise ValueError("unsupported curriculum operation")
        if not 1 <= limit <= 12:
            raise ValueError("limit must be between 1 and 12")
        query = query.strip()
        goal = goal.strip() or query
        manifest = await self._json("manifest.json")
        if not isinstance(manifest, dict):
            raise RuntimeError(  # noqa: TRY004 - upstream shape failure
                "curriculum_manifest_shape_changed"
            )
        handlers = {
            "overview": self._overview,
            "program": self._program,
            "course": self._course,
            "change": self._change,
            "comparison": self._comparison,
            "substitution": self._substitution,
            "shared": self._shared,
            "history": self._history,
        }
        items, total, truncated, data_file = await handlers[operation](
            query,
            goal,
            limit,
            manifest,
        )
        snapshot = manifest.get("snapshot")
        counts = manifest.get("counts")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        counts = counts if isinstance(counts, dict) else {}
        return {
            "schema_version": 1,
            "operation": operation,
            "query": query,
            "public_only": True,
            "snapshot_date": str(snapshot.get("snapshotDate") or ""),
            "snapshot_scope": str(snapshot.get("scope") or ""),
            "dataset_schema_version": str(manifest.get("schemaVersion") or ""),
            "unofficial_notice": (
                "非官方研究快照；选课、课程替代和毕业审核以学校实时规定为准。"
            ),
            "identity_rule": str(
                manifest.get("identityRule") or "课程身份只由课程号确定。"
            ),
            "result": {
                "items": items,
                "total": total,
                "truncated": truncated,
                "dataset_counts": [
                    {"name": str(name), "value": _number(value)}
                    for name, value in counts.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                ],
            },
            "source_url": f"{self.base_url}/{data_file}",
            "fetched_at": fetched_at(),
        }

    async def _overview(self, query, goal, limit, manifest):
        del query, goal, limit
        snapshot = manifest.get("snapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        return (
            [
                _item(
                    kind="overview",
                    title="中科大培养方案研究快照",
                    summary=str(snapshot.get("scope") or "2015-2026 主修方案"),
                    evidence_refs=(
                        f"snapshot:{snapshot.get('snapshotDate') or 'unknown'}",
                        f"schema:{manifest.get('schemaVersion') or 'unknown'}",
                    ),
                )
            ],
            1,
            False,
            "manifest.json",
        )

    async def _program(self, query, goal, limit, manifest):
        del manifest
        rows = await self._csv("programs.csv")
        grade = _years(goal)
        candidates = [
            row
            for row in rows
            if (not grade or str(row.get("grade")) == grade[-1])
            and _matches_row(row, query or goal, ("majorName", "majorCode", "departmentName", "departmentCode", "planName", "sourceProgramId"))
        ]
        candidates.sort(
            key=lambda row: (
                _program_score(row, query or goal),
                str(row.get("departmentCode") or "") != "000",
                str(row.get("grade") or ""),
            ),
            reverse=True,
        )
        selected = candidates[:limit]
        detail_requested = any(
            marker in goal
            for marker in (*_DIMENSIONS, "要学", "学什么", "必修", "选修", "课程有哪些", "课程要求")
        )
        research = await self._json("research.json") if detail_requested else {}
        comparison = research.get("programComparisons") if isinstance(research, dict) else None
        plans = comparison.get("plans") if isinstance(comparison, dict) and isinstance(comparison.get("plans"), dict) else {}
        names = _course_names(research)
        items = []
        for row in selected:
            course_codes: list[dict[str, Any]] = []
            detail = plans.get(str(row.get("sourceProgramId") or ""))
            if isinstance(detail, dict):
                dimension_groups = detail.get("courseDimensionCodes")
                requested_dimensions = tuple(
                    dimension
                    for marker, dimension in _DIMENSIONS.items()
                    if marker in goal
                )
                if not requested_dimensions:
                    requested_dimensions = tuple(_DIMENSION_NAMES)
                include_electives = "选修" in goal
                if isinstance(dimension_groups, dict):
                    for dimension in requested_dimensions:
                        groups = dimension_groups.get(dimension)
                        if not isinstance(groups, dict):
                            continue
                        states = (
                            ("requiredOnly", "required"),
                            ("mixed", "mixed"),
                            *(((("electiveOnly", "elective"),)) if include_electives else ()),
                        )
                        for key, state in states:
                            codes = groups.get(key)
                            if not isinstance(codes, list):
                                continue
                            for code in codes:
                                course_codes.append(
                                    _course_entry(
                                        str(code),
                                        names,
                                        dimension=dimension,
                                        state=state,
                                    )
                                )
                                if len(course_codes) >= 30:
                                    break
                            if len(course_codes) >= 30:
                                break
                        if len(course_codes) >= 30:
                            break
            summary = (
                f"{row.get('programType')}，要求 {row.get('requiredCredits') or '未知'} 学分，"
                f"观测到 {row.get('courseCodeCount') or 0} 个课程号。"
            )
            if course_codes:
                summary += f" 本次按问题所需维度返回 {len(course_codes)} 个课程号。"
            items.append(
                _item(
                    kind="program",
                    title=f"{row.get('grade')}级 {row.get('planName')}",
                    summary=summary,
                    source_program_id=str(row.get("sourceProgramId") or ""),
                    grade=str(row.get("grade") or ""),
                    department_code=str(row.get("departmentCode") or ""),
                    department_name=str(row.get("departmentName") or ""),
                    major_code=str(row.get("majorCode") or ""),
                    major_name=str(row.get("majorName") or ""),
                    major_track_key=str(row.get("majorTrackKey") or ""),
                    program_type=str(row.get("programType") or ""),
                    required_credits=_number(row.get("requiredCredits")),
                    course_codes=course_codes,
                    counts=(
                        {"name": "course_code_count", "value": _number(row.get("courseCodeCount"))},
                        {"name": "required_only_count", "value": _number(row.get("requiredOnlyCount"))},
                        {"name": "elective_only_count", "value": _number(row.get("electiveOnlyCount"))},
                    ),
                    evidence_refs=(f"program:{row.get('sourceProgramId')}",),
                )
            )
        return (
            items,
            len(candidates),
            len(candidates) > len(selected),
            "programs.csv",
        )

    async def _course(self, query, goal, limit, manifest):
        del manifest
        rows = await self._csv("courses.csv")
        term = query or goal
        candidates = [
            row
            for row in rows
            if _matches_row(row, term, ("courseCode", "nameZh", "nameEn", "department"))
        ]
        candidates.sort(
            key=lambda row: (
                _course_score(row, term),
                _integer(row.get("planCount")),
                str(row.get("courseCode") or ""),
            ),
            reverse=True,
        )
        selected = candidates[:limit]
        return (
            [
                _item(
                    kind="course",
                    title=f"{row.get('courseCode')} {row.get('nameZh')}",
                    summary=(
                        f"{row.get('credit') or '未知'} 学分，{row.get('hour') or '未知'} 学时；"
                        f"在 {row.get('planCount') or 0} 份主修方案中出现。"
                    ),
                    course_code=str(row.get("courseCode") or ""),
                    course_name=str(row.get("nameZh") or ""),
                    from_grade=str(row.get("firstGrade") or ""),
                    to_grade=str(row.get("lastGrade") or ""),
                    counts=(
                        {"name": "credit", "value": _number(row.get("credit"))},
                        {"name": "hour", "value": _number(row.get("hour"))},
                        {"name": "plan_count", "value": _number(row.get("planCount"))},
                        {"name": "major_track_count", "value": _number(row.get("majorTrackCount"))},
                    ),
                    evidence_refs=(f"course:{row.get('courseCode')}",),
                )
                for row in selected
            ],
            len(candidates),
            len(candidates) > len(selected),
            "courses.csv",
        )

    async def _change(self, query, goal, limit, manifest):
        del manifest
        research = await self._json("research.json")
        transitions = _nested_list(research, "majorYearRequirementChanges", "transitions")
        years = _years(goal)
        selected = [
            row
            for row in transitions
            if isinstance(row, dict)
            and _matches_row(row, query or goal, ("majorName", "majorCode", "departmentName", "departmentCode", "majorTrackKey"))
            and _transition_years_match(row, years)
        ]
        selected.sort(
            key=lambda row: (
                _program_score(row, query or goal),
                str(row.get("departmentCode") or "") != "000",
                str(row.get("toGrade") or ""),
                str(row.get("fromGrade") or ""),
            ),
            reverse=True,
        )
        programs = {str(row.get("sourceProgramId")): row for row in await self._csv("programs.csv")}
        names = _course_names(research)
        items = []
        for row in selected[:limit]:
            changes = _transition_courses(row, names, maximum=30)
            before = programs.get(str(row.get("fromSourceProgramId") or ""), {})
            after = programs.get(str(row.get("toSourceProgramId") or ""), {})
            requirement_change_count = len(row.get("requirementTransitions") or [])
            dimension_change_count = len(row.get("courseDimensionTransitions") or [])
            items.append(
                _item(
                    kind="change",
                    title=f"{row.get('majorName')}：{row.get('fromGrade')} → {row.get('toGrade')}",
                    summary=(
                        f"课程号新增 {len(row.get('addedCourseCodes') or [])} 个、移出 {len(row.get('removedCourseCodes') or [])} 个；"
                        f"必选性质变化 {requirement_change_count} 个、五维归类变化 {dimension_change_count} 个；"
                        f"总学分 {before.get('requiredCredits') or '未知'} → {after.get('requiredCredits') or '未知'}。"
                    ),
                    from_grade=str(row.get("fromGrade") or ""),
                    to_grade=str(row.get("toGrade") or ""),
                    department_code=str(row.get("departmentCode") or ""),
                    department_name=str(row.get("departmentName") or ""),
                    major_code=str(row.get("majorCode") or ""),
                    major_name=str(row.get("majorName") or ""),
                    major_track_key=str(row.get("majorTrackKey") or ""),
                    course_codes=changes,
                    counts=(
                        {"name": "from_required_credits", "value": _number(before.get("requiredCredits"))},
                        {"name": "to_required_credits", "value": _number(after.get("requiredCredits"))},
                        {"name": "added_course_count", "value": len(row.get("addedCourseCodes") or [])},
                        {"name": "removed_course_count", "value": len(row.get("removedCourseCodes") or [])},
                        {"name": "requirement_change_count", "value": requirement_change_count},
                        {"name": "dimension_change_count", "value": dimension_change_count},
                    ),
                    evidence_refs=(
                        f"program:{row.get('fromSourceProgramId')}",
                        f"program:{row.get('toSourceProgramId')}",
                    ),
                )
            )
        return items, len(selected), len(selected) > len(items), "research.json"

    async def _comparison(self, query, goal, limit, manifest):
        del manifest
        research = await self._json("research.json")
        comparison = research.get("programComparisons") if isinstance(research, dict) else None
        comparison = comparison if isinstance(comparison, dict) else {}
        plans = comparison.get("plans") if isinstance(comparison.get("plans"), dict) else {}
        matches = comparison.get("matches") if isinstance(comparison.get("matches"), list) else []
        years = _years(goal)
        ordinary = [
            plan
            for plan in plans.values()
            if isinstance(plan, dict)
            and str(plan.get("programType") or "") == "主修"
            and str(plan.get("departmentCode") or "") != "000"
            and (not years or str(plan.get("grade") or "") == years[-1])
            and _matches_row(plan, query or goal, ("majorName", "majorCode", "departmentName", "majorTrackKey"))
        ]
        ordinary.sort(key=lambda row: (_program_score(row, query or goal), str(row.get("grade") or "")), reverse=True)
        if not ordinary:
            return [], 0, False, "research.json"
        baseline = ordinary[0]
        match = next(
            (row for row in matches if isinstance(row, dict) and str(row.get("ordinarySourceProgramId")) == str(baseline.get("sourceProgramId"))),
            None,
        )
        groups = match.get("groups") if isinstance(match, dict) and isinstance(match.get("groups"), dict) else {}
        group_names = {"young": "少年班", "minor": "辅修/双学位", "strongFoundation": "强基", "talent": "英才班"}
        requested_groups = _comparison_groups(f"{query} {goal}")
        names = _course_names(research)
        items = []
        baseline_codes = _plan_code_set(baseline)
        total = sum(
            len(ids)
            for group, ids in groups.items()
            if isinstance(ids, list)
            and (not requested_groups or group in requested_groups)
        )
        for group, ids in groups.items():
            if not isinstance(ids, list) or (requested_groups and group not in requested_groups):
                continue
            for target_id in ids:
                target = plans.get(str(target_id))
                if not isinstance(target, dict):
                    continue
                target_codes = _plan_code_set(target)
                changes = [
                    _course_entry(code, names, change="target_only")
                    for code in sorted(target_codes - baseline_codes)[:20]
                ] + [
                    _course_entry(code, names, change="ordinary_only")
                    for code in sorted(baseline_codes - target_codes)[:20]
                ]
                items.append(
                    _item(
                        kind="comparison",
                        title=f"{baseline.get('grade')}级 {baseline.get('majorName')}普通主修 vs {group_names.get(group, group)}",
                        summary=(
                            f"对照方案 {target.get('planName')}；目标方案独有 {len(target_codes - baseline_codes)} 个课程号，"
                            f"普通主修独有 {len(baseline_codes - target_codes)} 个课程号。"
                        ),
                        source_program_id=str(target.get("sourceProgramId") or ""),
                        grade=str(target.get("grade") or ""),
                        major_name=str(target.get("majorName") or ""),
                        course_codes=changes,
                        counts=(
                            {"name": "target_only_course_count", "value": len(target_codes - baseline_codes)},
                            {"name": "ordinary_only_course_count", "value": len(baseline_codes - target_codes)},
                        ),
                        evidence_refs=(
                            f"program:{baseline.get('sourceProgramId')}",
                            f"program:{target.get('sourceProgramId')}",
                        ),
                    )
                )
                if len(items) >= limit:
                    return items, total, total > len(items), "research.json"
        return items, total, total > len(items), "research.json"

    async def _substitution(self, query, goal, limit, manifest):
        del manifest
        relations = await self._csv("official-substitutions.csv")
        courses = await self._csv("courses.csv")
        names = {str(row.get("courseCode") or ""): str(row.get("nameZh") or "") for row in courses}
        codes = set(_course_codes(query or goal))
        if not codes:
            codes.update(
                str(row.get("courseCode") or "")
                for row in courses
                if _matches_row(row, query or goal, ("courseCode", "nameZh", "nameEn"))
            )
        selected = []
        for row in relations:
            substitute = _json_list(row.get("substituteCourseCodes"))
            original = _json_list(row.get("originalCourseCodes"))
            if codes and codes.isdisjoint({*substitute, *original}):
                continue
            selected.append((row, substitute, original))
        selected.sort(
            key=lambda value: (
                len(codes.intersection({*value[1], *value[2]})),
                not _boolean(value[0].get("isHyperedge")),
                _integer(value[0].get("sourceRelationId")),
            ),
            reverse=True,
        )
        items = [
            _item(
                kind="substitution",
                title=f"替代关系 {row.get('sourceRelationId')}",
                summary=(
                    f"{_codes_with_names(substitute, names)} 可以替代 {_codes_with_names(original, names)}；"
                    f"{'可互换' if _boolean(row.get('interchangeable')) else '单向'}，"
                    f"{'组合替代' if _boolean(row.get('isHyperedge')) else '单课程关系'}。"
                ),
                substitute_course_codes=tuple(substitute),
                original_course_codes=tuple(original),
                interchangeable=_boolean(row.get("interchangeable")),
                is_hyperedge=_boolean(row.get("isHyperedge")),
                evidence_refs=(f"substitution:{row.get('sourceRelationId')}",),
            )
            for row, substitute, original in selected[:limit]
        ]
        return items, len(selected), len(selected) > len(items), "official-substitutions.csv"

    async def _shared(self, query, goal, limit, manifest):
        del goal, manifest
        rows = await self._csv("professional-shared-courses.csv")
        selected = [
            row
            for row in rows
            if not query
            or _shared_ranking_query(query)
            or _matches_row(row, query, ("courseCode", "nameZh", "nameEn"))
        ]
        selected.sort(key=lambda row: _integer(row.get("majorCodeCount")), reverse=True)
        items = [
            _item(
                kind="shared",
                title=f"{row.get('courseCode')} {row.get('nameZh')}",
                summary=(
                    f"在 {row.get('majorCodeCount') or 0} 个专业代码、{row.get('majorTrackCount') or 0} 条专业轨道、"
                    f"{row.get('programCount') or 0} 份方案的专业模块中出现。"
                ),
                course_code=str(row.get("courseCode") or ""),
                course_name=str(row.get("nameZh") or ""),
                from_grade=str(row.get("firstGrade") or ""),
                to_grade=str(row.get("lastGrade") or ""),
                counts=(
                    {"name": "major_code_count", "value": _number(row.get("majorCodeCount"))},
                    {"name": "major_track_count", "value": _number(row.get("majorTrackCount"))},
                    {"name": "program_count", "value": _number(row.get("programCount"))},
                ),
                evidence_refs=(f"course:{row.get('courseCode')}",),
            )
            for row in selected[:limit]
        ]
        return items, len(selected), len(selected) > len(items), "professional-shared-courses.csv"

    async def _history(self, query, goal, limit, manifest):
        del manifest
        rows = await self._csv("major-code-history.csv")
        selected = [
            row
            for row in rows
            if _matches_row(row, query or goal, ("majorTrackKey", "majorCode", "departmentCode", "departmentName", "nameVariants"))
        ]
        selected.sort(key=lambda row: str(row.get("lastGrade") or ""), reverse=True)
        items = [
            _item(
                kind="history",
                title=f"{row.get('majorTrackKey')} 专业轨道",
                summary=(
                    f"数据集中首次出现于 {row.get('firstGrade')} 级，最后出现于 {row.get('lastGrade')} 级；"
                    f"共观测 {row.get('planCount') or 0} 份方案。"
                ),
                from_grade=str(row.get("firstGrade") or ""),
                to_grade=str(row.get("lastGrade") or ""),
                department_code=str(row.get("departmentCode") or ""),
                department_name=str(row.get("departmentName") or ""),
                major_code=str(row.get("majorCode") or ""),
                major_track_key=str(row.get("majorTrackKey") or ""),
                evidence_refs=(f"major-track:{row.get('majorTrackKey')}",),
            )
            for row in selected[:limit]
        ]
        return items, len(selected), len(selected) > len(items), "major-code-history.csv"

    async def _json(self, name: str) -> object:
        value = await self._cached(name)
        if isinstance(value, (dict, list)):
            return value
        parsed = json.loads(str(value))
        self._cache[name] = (time.monotonic() + self._cache_ttl_seconds, parsed)
        return parsed

    async def _csv(self, name: str) -> list[dict[str, str]]:
        value = await self._cached(name)
        if isinstance(value, list):
            return value
        parsed = list(csv.DictReader(io.StringIO(str(value))))
        self._cache[name] = (time.monotonic() + self._cache_ttl_seconds, parsed)
        return parsed

    async def _cached(self, name: str) -> object:
        cached = self._cache.get(name)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]
        response = await self._client.get(f"{self.base_url}/{name}")
        response.raise_for_status()
        self._cache[name] = (now + self._cache_ttl_seconds, response.text)
        return response.text


def _item(**values: Any) -> dict[str, Any]:
    item = {
        "kind": "",
        "title": "",
        "summary": "",
        "source_program_id": None,
        "grade": None,
        "department_code": None,
        "department_name": None,
        "major_code": None,
        "major_name": None,
        "major_track_key": None,
        "program_type": None,
        "required_credits": None,
        "course_code": None,
        "course_name": None,
        "from_grade": None,
        "to_grade": None,
        "course_codes": [],
        "substitute_course_codes": [],
        "original_course_codes": [],
        "interchangeable": None,
        "is_hyperedge": None,
        "counts": [],
        "evidence_refs": [],
    }
    item.update(values)
    for key in ("course_codes", "substitute_course_codes", "original_course_codes", "counts", "evidence_refs"):
        item[key] = list(item[key])
    return item


def _normalize(value: object) -> str:
    return "".join(str(value or "").split()).casefold()


def _query_fragments(value: str) -> tuple[str, ...]:
    cleaned = value
    for generic in _GENERIC_QUERY_TERMS:
        cleaned = cleaned.replace(generic, " ")
    cleaned = re.sub(r"20\d{2}", " ", cleaned)
    return tuple(
        fragment
        for fragment in re.findall(r"[\u4e00-\u9fffA-Za-z0-9*:+.-]+", cleaned)
        if len(_normalize(fragment)) >= 2
    )


def _matches_row(row: dict[str, Any], query: str, fields: tuple[str, ...]) -> bool:
    normalized = _normalize(query)
    if not normalized:
        return True
    values = tuple(str(row.get(field) or "") for field in fields)
    haystack = _normalize(" ".join(values))
    if normalized in haystack:
        return True
    if any(len(_normalize(value)) >= 2 and _normalize(value) in normalized for value in values):
        return True
    return any(_normalize(fragment) in haystack for fragment in _query_fragments(query))


def _program_score(row: dict[str, Any], query: str) -> int:
    normalized = _normalize(query)
    name = _normalize(row.get("majorName"))
    plan = _normalize(row.get("planName"))
    return (4 if name and name in normalized else 0) + (2 if normalized and normalized in plan else 0)


def _course_score(row: dict[str, Any], query: str) -> int:
    normalized = _normalize(query)
    code = _normalize(row.get("courseCode"))
    name = _normalize(row.get("nameZh"))
    return (8 if normalized == code else 0) + (6 if normalized == name else 0) + (2 if normalized in name else 0)


def _years(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"20(?:1[5-9]|2[0-6])", value)))


def _transition_years_match(row: dict[str, Any], years: tuple[str, ...]) -> bool:
    if not years:
        return True
    observed = {str(row.get("fromGrade") or ""), str(row.get("toGrade") or "")}
    return set(years) <= observed if len(years) > 1 else years[0] in observed


def _nested_list(value: object, *keys: str) -> list[Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    return current if isinstance(current, list) else []


def _course_names(research: object) -> dict[str, str]:
    if not isinstance(research, dict):
        return {}
    comparison = research.get("programComparisons")
    names = comparison.get("courseNames") if isinstance(comparison, dict) else None
    return {str(key): str(value) for key, value in names.items()} if isinstance(names, dict) else {}


def _transition_courses(row: dict[str, Any], names: dict[str, str], *, maximum: int) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    dimensions = row.get("dimensionChanges")
    if not isinstance(dimensions, dict):
        dimensions = {}

    for transition in row.get("requirementTransitions") or []:
        if not isinstance(transition, dict):
            continue
        code = str(transition.get("courseCode") or "")
        before = _string_list(transition.get("from"))
        after = _string_list(transition.get("to"))
        values.append(
            _course_entry(
                code,
                names,
                dimension=_transition_dimensions(dimensions, code, "requirementTransitions"),
                state=f"{'+'.join(before) or '未知'} -> {'+'.join(after) or '未知'}",
                change="requirement_changed",
            )
        )
        if len(values) >= maximum:
            return values

    for transition in row.get("courseDimensionTransitions") or []:
        if not isinstance(transition, dict):
            continue
        before = [_DIMENSION_NAMES.get(value, value) for value in _string_list(transition.get("from"))]
        after = [_DIMENSION_NAMES.get(value, value) for value in _string_list(transition.get("to"))]
        values.append(
            _course_entry(
                str(transition.get("courseCode") or ""),
                names,
                dimension=f"{'+'.join(before) or '未知'} -> {'+'.join(after) or '未知'}",
                change="dimension_changed",
            )
        )
        if len(values) >= maximum:
            return values

    for field, change in (("addedCourseCodes", "added"), ("removedCourseCodes", "removed")):
        for code_value in row.get(field) or []:
            code = str(code_value)
            values.append(
                _course_entry(
                    code,
                    names,
                    dimension=_transition_dimensions(dimensions, code, field),
                    change=change,
                )
            )
            if len(values) >= maximum:
                return values
    return values


def _transition_dimensions(dimensions: dict[str, Any], code: str, field: str) -> str:
    matched = []
    for dimension, changes in dimensions.items():
        if not isinstance(changes, dict):
            continue
        values = changes.get(field)
        if field == "requirementTransitions" and isinstance(values, list):
            present = any(
                isinstance(item, dict) and str(item.get("courseCode") or "") == code
                for item in values
            )
        else:
            present = isinstance(values, list) and code in {str(item) for item in values}
        if present:
            matched.append(_DIMENSION_NAMES.get(str(dimension), str(dimension)))
    return "+".join(matched)


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _course_entry(code: str, names: dict[str, str], *, dimension: str = "", state: str = "", change: str = "") -> dict[str, Any]:
    return {
        "code": code,
        "name": names.get(code),
        "dimension": _DIMENSION_NAMES.get(dimension, dimension) or None,
        "state": state or None,
        "change": change or None,
    }


def _plan_code_set(plan: dict[str, Any]) -> set[str]:
    groups = plan.get("courseCodes")
    if not isinstance(groups, dict):
        return set()
    return {
        str(code)
        for values in groups.values()
        if isinstance(values, list)
        for code in values
    }


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _course_codes(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            re.findall(
                r"(?i)(?<![A-Z0-9])(?:THESIS|[A-Z][A-Z0-9]*\d[A-Z0-9*.+-]*|\d{2,}[A-Z][A-Z0-9*.+-]*|\d{6}[A-Z0-9*.+-]*)(?![A-Z0-9])",
                value,
            )
        )
    )


def _comparison_groups(value: str) -> set[str]:
    markers = {
        "young": ("少年班", "少院"),
        "minor": ("辅修", "双学位"),
        "strongFoundation": ("强基",),
        "talent": ("英才班", "科技英才", "英才"),
    }
    return {
        group
        for group, aliases in markers.items()
        if any(alias in value for alias in aliases)
    }


def _shared_ranking_query(value: str) -> bool:
    return any(
        marker in value
        for marker in ("最多", "排名", "排行", "榜单", "最广泛", "最常见", "共同使用")
    )


def _codes_with_names(codes: list[str], names: dict[str, str]) -> str:
    return " + ".join(f"{code} {names.get(code, '')}".strip() for code in codes)


def _number(value: object) -> int | float:
    if isinstance(value, bool) or value in (None, ""):
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _integer(value: object) -> int:
    return int(_number(value))


def _boolean(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes"}


__all__ = ["CURRICULUM_OPERATIONS", "CurriculumClient"]
