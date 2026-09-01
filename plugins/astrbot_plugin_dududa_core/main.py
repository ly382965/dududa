import base64
import random
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .audit import AuditLog
from .config import (
    ASTRBOT_CONFIG_PATH,
    PLUGIN_DATA_DIR,
    ensure_dirs,
    load_astrbot_config,
    load_plugin_config,
    load_json,
    save_astrbot_config,
    save_json,
    save_plugin_config,
    str_set,
)
from .course import ICourseClient, format_review, format_search, format_stats
from .campus_mcp import (
    academic_calendar_client,
    campus_events_client,
    college_notice_client,
    format_calendar_events,
    format_calendar_stats,
    format_college_notices,
    format_college_stats,
    format_current_term,
    format_events,
    format_event_stats,
    format_library_stats,
    format_majors,
    format_opening_hours,
    format_plan_stats,
    format_terms,
    library_client,
    training_plan_client,
)
from .help_menu import admin_help, module_help, user_help
from .permissions import PermissionManager


@dataclass
class PendingAction:
    action: str
    requester: str
    expires_at: float
    payload: dict[str, Any]


class ImageGenerationError(RuntimeError):
    def __init__(self, user_message: str, log_message: str | None = None):
        super().__init__(log_message or user_message)
        self.user_message = user_message


@register(
    "astrbot_plugin_dududa_core",
    "mmdustc",
    "嘟嘟哒统一命令、权限、课程查询和管理骨架",
    "0.1.0",
)
class DududaCorePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        ensure_dirs()
        self.perms = PermissionManager(self.config)
        self.audit = AuditLog()
        self.icourse = ICourseClient()
        self.college_notice = college_notice_client()
        self.training_plan = training_plan_client()
        self.library = library_client()
        self.campus_events = campus_events_client()
        self.academic_calendar = academic_calendar_client()
        self.pending: dict[str, PendingAction] = {}
        self.course_refresh_at: dict[str, float] = {}
        self.user_state_path = PLUGIN_DATA_DIR / "user_state.json"
        self.group_state_path = PLUGIN_DATA_DIR / "group_state.json"
        self.user_state = load_json(self.user_state_path, {})
        self.group_state = load_json(self.group_state_path, {})
        logger.info("DududaCore loaded: enabled=%s", self.enabled)

    def _blocked(self, event: AstrMessageEvent) -> str | None:
        if not self.enabled:
            return "嘟嘟哒核心插件暂时关闭。"
        if self.perms.is_muted(event):
            return "你现在不能调用嘟嘟哒。"
        group_muted = str_set(self._group_record(event).get("muted_users", []))
        if self._sender(event) in group_muted:
            return "你在本群暂时不能调用嘟嘟哒。"
        return None

    def _sender(self, event: AstrMessageEvent) -> str:
        return str(event.get_sender_id() or "")

    def _group(self, event: AstrMessageEvent) -> str:
        return str(event.get_group_id() or "")

    def _require_admin(self, event: AstrMessageEvent) -> str | None:
        blocked = self._blocked(event)
        if blocked:
            return blocked
        if not self.perms.is_admin(event):
            return "这个指令需要管理员权限。"
        return None

    def _require_owner(self, event: AstrMessageEvent) -> str | None:
        blocked = self._blocked(event)
        if blocked:
            return blocked
        if not self.perms.is_owner(event):
            return "这个指令需要 owner 权限。"
        return None

    def _save_user_state(self) -> None:
        save_json(self.user_state_path, self.user_state)

    def _save_group_state(self) -> None:
        save_json(self.group_state_path, self.group_state)

    def _reload_permissions(self) -> None:
        disk_config = load_plugin_config()
        if disk_config:
            self.config = disk_config
            self.perms = PermissionManager(self.config)

    def _user_record(self, event: AstrMessageEvent) -> dict[str, Any]:
        user_id = self._sender(event)
        return self.user_state.setdefault(
            user_id,
            {"memory_enabled": True, "memories": [], "style": ""},
        )

    def _group_record(self, event: AstrMessageEvent) -> dict[str, Any]:
        group_id = self._group(event) or "private"
        return self.group_state.setdefault(
            group_id,
            {"mode": "normal", "reply_rate": 100, "meme_rate": 20},
        )

    def _new_confirmation(self, event: AstrMessageEvent, action: str, payload: dict[str, Any]) -> str:
        token = secrets.token_hex(3).upper()
        self.pending[token] = PendingAction(
            action=action,
            requester=self._sender(event),
            expires_at=time.time() + 300,
            payload=payload,
        )
        self.audit.write(event, "confirm_requested", {"action": action})
        return token

    @filter.event_message_type(filter.EventMessageType.ALL, priority=8)
    async def natural_course_query(self, event: AstrMessageEvent):
        """把明确的自然语言评课请求路由到 icourse MCP。"""
        blocked = self._blocked(event)
        if blocked:
            return
        text = (event.message_str or event.get_message_outline() or "").strip()
        course_command_text = self._extract_course_command_text(text)
        if course_command_text == "":
            yield event.plain_result(module_help("course"))
            event.stop_event()
            return
        if course_command_text is not None:
            query = await self._understand_course_command_query(course_command_text, event)
            if not query:
                yield event.plain_result("我没提取到课程关键词。可以说：/course 推荐一个数学分析老师")
                event.stop_event()
                return
            try:
                reply = await self._answer_natural_course_query(query, course_command_text, event)
            except Exception as exc:
                logger.warning("Course command query failed: %s", exc)
                yield event.plain_result(f"评课搜索失败：{type(exc).__name__}")
                event.stop_event()
                return
            self.audit.write(event, "course_command_query", {"query": query[:60]})
            yield event.plain_result(reply)
            event.stop_event()
            return

        query = self._extract_course_query(text)
        if not query:
            return
        try:
            reply = await self._answer_natural_course_query(query, text, event)
        except Exception as exc:
            logger.warning("Natural icourse query failed: %s", exc)
            yield event.plain_result(f"评课社区查询失败：{type(exc).__name__}")
            event.stop_event()
            return
        self.audit.write(event, "natural_course_query", {"query": query[:60]})
        yield event.plain_result(reply)
        event.stop_event()

    @filter.command("help")
    async def help(self, event: AstrMessageEvent, module: str | None = None):
        """查看嘟嘟哒帮助"""
        if self._blocked(event):
            return
        if (module or "").strip().lower() == "admin" and not self.perms.is_admin(event):
            yield event.plain_result("管理员菜单需要 admin 权限。")
        else:
            yield event.plain_result(module_help(module or ""))
        event.stop_event()

    def _extract_course_query(self, text: str) -> str | None:
        if not text or text.startswith("/"):
            return None
        if DududaCorePlugin._is_icourse_site_meta_question(text):
            return None
        trigger = re.search(
            r"评课社区[\s，。！？、；：,.!?;:（）()【】\[\]\"'“”‘’]*搜索",
            text,
        )
        if not trigger:
            return None

        query = DududaCorePlugin._clean_course_query_text(text[trigger.end() :])
        if len(query) < 2:
            return None
        return query[:80]

    @staticmethod
    def _extract_course_command_text(text: str) -> str | None:
        if not text:
            return None
        normalized = re.sub(r"\s+", " ", text.strip())
        if normalized == "/course":
            return ""
        if not normalized.startswith("/course "):
            return None
        rest = normalized[len("/course ") :].strip()
        if not rest:
            return ""
        subcommand = rest.split(" ", 1)[0].strip().lower()
        if subcommand in {"help", "帮助"}:
            return ""
        if subcommand in {"stats", "search", "review", "compare", "refresh"}:
            return None
        return rest

    async def _understand_course_command_query(self, text: str, event: AstrMessageEvent | None = None) -> str | None:
        fallback = self._clean_course_query_text(text)
        try:
            provider = self.context.get_using_provider(
                umo=getattr(event, "unified_msg_origin", None) if event else None
            )
            if not provider:
                return fallback or None
            prompt = (
                "[UserCourseRequest]\n"
                f"{text}\n"
                "[/UserCourseRequest]\n\n"
                "请判断这是否是在查询 USTC 评课社区里的课程/老师评价或选课推荐。"
                "如果是，只抽取最适合用于站内搜索的课程关键词；如果不是，intent 写 other。\n"
                "输出严格 JSON：{\"intent\":\"course_review_search\",\"query\":\"数学分析\"}。\n"
                "例子：\n"
                "推荐一个数学分析老师 -> {\"intent\":\"course_review_search\",\"query\":\"数学分析\"}\n"
                "数学分析A哪个老师好 -> {\"intent\":\"course_review_search\",\"query\":\"数学分析A\"}\n"
                "查一下数据结构A课程评价 -> {\"intent\":\"course_review_search\",\"query\":\"数据结构A\"}\n"
                "不要解释，不要 Markdown。"
            )
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是嘟嘟哒的课程评课指令解析器，只抽取课程搜索关键词。",
                max_tokens=120,
                temperature=0,
            )
            parsed = self._parse_course_query_json(getattr(response, "completion_text", ""))
            if parsed:
                return self._clean_course_query_text(parsed)[:80] or fallback or None
        except Exception as exc:
            logger.warning("Course command understanding failed: %s", exc)
        return fallback or None

    @staticmethod
    def _clean_course_query_text(query: str) -> str:
        query = re.sub(r"(?i)icourse(\.club)?", " ", query)
        query = re.sub(r"[\s，。！？、；：,.!?;:（）()【】\[\]\"'“”‘’]+", " ", query).strip()
        for phrase in (
            "一下",
            "帮我",
            "帮忙",
            "帮我看看",
            "给我",
            "我说",
            "请问",
            "关于",
            "推荐一个",
            "推荐一位",
            "推荐下",
            "推荐一下",
            "推荐",
            "列举",
            "排序",
            "最后给出推荐",
            "给出推荐",
            "搜索一下",
            "搜一下",
            "查一下",
            "查询一下",
            "这门课",
            "这课",
            "选择哪个老师",
            "选哪个老师",
            "选哪位老师",
            "哪个老师好",
            "哪位老师好",
            "推荐哪个老师",
            "推荐哪位老师",
            "老师怎么选",
            "怎么选老师",
            "怎么样",
            "是什么评价",
            "什么评价",
            "评价如何",
            "评价",
            "避雷吗",
            "避雷",
        ):
            query = query.replace(phrase, " ")
        query = re.sub(r"\s+", " ", query).strip()
        noise_words = (
            "搜索",
            "搜",
            "查询",
            "查",
            "推荐",
            "选择",
            "选",
            "看看",
            "看",
            "了解",
            "老师",
            "课程",
        )
        changed = True
        while changed:
            old = query
            for word in noise_words:
                query = re.sub(rf"^{re.escape(word)}\s*", "", query).strip()
                query = re.sub(rf"\s*{re.escape(word)}$", "", query).strip()
            query = re.sub(r"[吗嘛么呢呀啊]$", "", query).strip()
            changed = query != old
        return query.strip()

    async def _answer_natural_course_query(
        self,
        query: str,
        original_text: str,
        event: AstrMessageEvent | None = None,
    ) -> str:
        result = await self._search_course_expanded(query)
        items = result.get("items") or []
        if not items:
            return (
                f"我用评课社区站内搜索查了「{query}」，暂时没命中公开课程。\n"
                "我不会拿泛网页结果硬凑结论；你可以换个课程全名、老师名，或给课程 ID。"
            )

        ranked = sorted(items, key=self._course_rank_key, reverse=True)
        cards = await self._load_ranked_course_cards(ranked[:8])
        summaries = await self._summarize_course_cards(cards, event)
        return self._format_natural_course_cards(
            query,
            cards,
            self._looks_like_teacher_choice(original_text),
            summaries,
        )

    async def _search_course_expanded(self, query: str) -> dict[str, Any]:
        online = await self.icourse.call(
            "search_site_courses",
            {
                "query": query,
                "pages": 2,
                "max_courses": 20,
                "detail": False,
                "detail_limit": 0,
                "sort_by": "upvote",
            },
        )
        if online.get("items"):
            return online

        fallback_query = self._fallback_course_query(query)
        if fallback_query and fallback_query != query:
            online = await self.icourse.call(
                "search_site_courses",
                {
                    "query": fallback_query,
                    "pages": 2,
                    "max_courses": 20,
                    "detail": False,
                    "detail_limit": 0,
                    "sort_by": "upvote",
                },
            )
            if online.get("items"):
                online["query"] = fallback_query
                return online

        return await self.icourse.call("search_courses", {"query": query, "limit": 20})

    async def _load_ranked_course_cards(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for item in items:
            course = item
            reviews: list[dict[str, Any]] = []
            course_id = item.get("id")
            if course_id:
                try:
                    course_result = await self.icourse.call(
                        "get_course",
                        {"course_id": course_id, "include_reviews": True, "refresh": True},
                    )
                    course = course_result.get("course") or item
                    reviews = course.get("reviews") or []
                    if not reviews:
                        review_result = await self.icourse.call(
                            "get_reviews",
                            {"course_id": course_id, "limit": 8, "sort_by": "upvote"},
                        )
                        reviews = review_result.get("reviews") or []
                except Exception as exc:
                    logger.warning("Failed to refresh icourse detail %s: %s", course_id, exc)
            cards.append({"course": course, "reviews": reviews})
        cards.sort(key=lambda card: self._course_rank_key(card["course"]), reverse=True)
        return cards

    async def _summarize_course_cards(
        self,
        cards: list[dict[str, Any]],
        event: AstrMessageEvent | None = None,
    ) -> dict[int, str]:
        records = []
        for index, card in enumerate(cards, start=1):
            course = card["course"]
            reviews = card["reviews"]
            review_lines = []
            for review in reviews[:5]:
                text = self._review_excerpt(review, limit=220)
                if not text or text == "无正文":
                    continue
                meta = []
                if review.get("rating_10"):
                    meta.append(f"{review['rating_10']}/10")
                if review.get("term"):
                    meta.append(str(review["term"]))
                review_lines.append(f"- {' '.join(meta) or '评论'}：{text}")
            if not review_lines:
                continue
            course_line = (
                f"{index}. {course.get('name') or '未知课程'}｜"
                f"{self._teacher_names(course) or '教师未知'}｜"
                f"{course.get('term_text') or '学期未知'}｜"
                f"评分 {course.get('rating_average') or '暂无'}"
            )
            records.append(course_line + "\n" + "\n".join(review_lines))

        if not records:
            return {}

        prompt = (
            "[ReviewData]\n"
            + "\n\n".join(records)
            + "\n[/ReviewData]\n\n"
            "请只根据 [ReviewData] 中的公开评课内容，为每个编号输出一个短总结。\n"
            "输出必须是 JSON 数组，每项格式为 {\"index\": 1, \"summary\": \"...\"}。\n"
            "summary 用中文，不超过 90 字，风格类似："
            "“徐小华的评课多数认为作业少、给分友好；但也有人认为课堂容量偏低、线下验收体验一般。”\n"
            "如果材料里没有明显反方观点，写“可见评论主要认为...，暂未看到明显相反意见”。\n"
            "不要编造老师、课程、分数或评论里没有的信息；不要输出 Markdown。"
        )
        try:
            provider = self.context.get_using_provider(
                umo=getattr(event, "unified_msg_origin", None) if event else None
            )
            if not provider:
                return {}
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是嘟嘟哒的评课评论总结器，只做忠实归纳，不添加站外信息。",
                max_tokens=900,
                temperature=0.2,
            )
            return self._parse_summary_json(getattr(response, "completion_text", ""))
        except Exception as exc:
            logger.warning("Natural icourse summary LLM failed: %s", exc)
            return {}

    def _format_natural_course_cards(
        self,
        query: str,
        cards: list[dict[str, Any]],
        include_recommendation: bool,
        summaries: dict[int, str] | None = None,
    ) -> str:
        summaries = summaries or {}
        lines = [f"我在评课社区查到「{query}」这些公开记录，按评分降序："]
        for index, card in enumerate(cards, start=1):
            course = card["course"]
            reviews = card["reviews"]
            teachers = self._teacher_names(course) or "教师未知"
            name = course.get("name") or query
            term = course.get("term_text") or "学期未知"
            rating = course.get("rating_average")
            rating_text = f"{rating:.1f}" if isinstance(rating, float) else str(rating or "暂无评分")
            review_count = self._course_review_count(course)
            count_text = f"{review_count}条" if review_count is not None else "点评数未知"
            tags = self._course_tag_text(course)

            lines.append("")
            lines.append(f"{index}. {name}｜{teachers}｜{term}｜{rating_text}｜{count_text}")
            if tags:
                lines.append(f"   标签：{tags}")
            if summaries.get(index):
                lines.append(f"   AI总结：{summaries[index]}")
                excerpt = self._first_review_excerpt(reviews)
                if excerpt:
                    lines.append(f"   代表评论：{excerpt}")
            elif reviews:
                lines.append("   具体评论：")
                for review in reviews[:2]:
                    meta_parts = []
                    rating_10 = review.get("rating_10")
                    if rating_10:
                        meta_parts.append(f"{rating_10}/10")
                    if review.get("term"):
                        meta_parts.append(str(review["term"]))
                    if review.get("upvote_count") is not None:
                        meta_parts.append(f"赞{review['upvote_count']}")
                    prefix = "｜".join(meta_parts) or "评论"
                    lines.append(f"   - {prefix}：{self._review_excerpt(review)}")
            else:
                lines.append("   具体评论：暂无可见正文。")

        if include_recommendation and cards:
            top = [self._teacher_names(card["course"]) for card in cards[:2]]
            top = [name for name in top if name]
            if top:
                lines.append("")
                lines.append(f"推荐：优先考虑 {'、'.join(top)}。具体还要结合开课学期、作业量、给分标签和评论样本数。")
        lines.append("")
        lines.append("来源：icourse.club 公开页面；不登录、不读取非公开内容。")
        return "\n".join(lines)

    @staticmethod
    def _is_icourse_site_meta_question(text: str) -> bool:
        lower = text.lower()
        has_site = any(key in lower for key in ("评课社区", "icourse", "icourse.club", "ustc评课"))
        if not has_site:
            return False
        hard_meta_terms = (
            "谁开发",
            "开发者",
            "谁做",
            "谁写",
            "作者",
            "维护者",
            "谁维护",
            "运营",
            "团队",
            "属于谁",
            "源码",
            "开源",
            "github",
            "历史",
            "什么时候上线",
            "功能",
            "怎么做",
            "如何实现",
            "实现原理",
            "登录",
            "注册",
            "账号",
            "密码",
            "隐私",
            "条款",
            "联系",
        )
        if any(term in lower for term in hard_meta_terms):
            return True
        soft_meta_terms = ("这个网站", "这个平台", "是什么", "介绍", "怎么用", "使用方法")
        course_intent_terms = (
            "搜索",
            "搜",
            "查询",
            "查",
            "课程",
            "老师",
            "评价",
            "推荐",
            "给分",
            "作业",
            "难度",
            "收获",
            "避雷",
            "点名",
            "怎么样",
            "选",
        )
        return any(term in lower for term in soft_meta_terms) and not any(
            term in lower for term in course_intent_terms
        )

    @staticmethod
    def _parse_summary_json(text: str) -> dict[int, str]:
        import json

        raw = (text or "").strip()
        if not raw:
            return {}
        fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.S | re.I)
        if fence:
            raw = fence.group(1).strip()
        else:
            match = re.search(r"\[[\s\S]*\]", raw)
            if match:
                raw = match.group(0)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        summaries: dict[int, str] = {}
        if not isinstance(data, list):
            return summaries
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            summary = str(item.get("summary") or "").strip()
            summary = re.sub(r"\s+", " ", summary)
            if summary:
                summaries[index] = summary[:140]
        return summaries

    @staticmethod
    def _parse_course_query_json(text: str) -> str:
        import json

        raw = (text or "").strip()
        if not raw:
            return ""
        fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.S | re.I)
        if fence:
            raw = fence.group(1).strip()
        else:
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                raw = match.group(0)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        if not isinstance(data, dict):
            return ""
        intent = str(data.get("intent") or "").strip()
        if intent and intent != "course_review_search":
            return ""
        query = str(data.get("query") or "").strip()
        query = re.sub(r"\s+", " ", query)
        return query

    @staticmethod
    def _fallback_course_query(query: str) -> str:
        text = query.strip()
        text = re.sub(r"([A-Za-z])$", "", text).strip()
        text = re.sub(r"[上下ⅠⅡⅢIV]+$", "", text).strip()
        return text

    @staticmethod
    def _looks_like_teacher_choice(text: str) -> bool:
        return any(key in text for key in ("老师", "选", "推荐", "避雷", "给分", "点名", "怎么样", "评价"))

    @staticmethod
    def _course_rank_key(item: dict[str, Any]) -> tuple[float, int]:
        try:
            rating = float(item.get("rating_average") or 0)
        except (TypeError, ValueError):
            rating = 0.0
        reviews = DududaCorePlugin._course_review_count(item) or 0
        return rating, reviews

    @staticmethod
    def _course_item_line(item: dict[str, Any]) -> str:
        teachers = DududaCorePlugin._teacher_names(item) or "教师未知"
        return (
            f"{item.get('id')} | {item.get('name')} | {teachers} | "
            f"评分 {item.get('rating_average') or '无'} | 点评 {DududaCorePlugin._course_review_count(item) or 0}"
        )

    @staticmethod
    def _teacher_names(item: dict[str, Any]) -> str:
        teachers = item.get("teachers") or []
        names: list[str] = []
        if isinstance(teachers, list):
            for teacher in teachers:
                if isinstance(teacher, dict) and teacher.get("name"):
                    names.append(str(teacher["name"]))
                elif isinstance(teacher, str) and teacher:
                    names.append(teacher)
        if not names and item.get("teacher_names"):
            names.append(str(item["teacher_names"]))
        return " / ".join(names)

    @staticmethod
    def _course_review_count(item: dict[str, Any]) -> int | None:
        for key in ("review_count_site", "review_count", "visible_review_count"):
            try:
                value = item.get(key)
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _course_tag_text(course: dict[str, Any]) -> str:
        tags = []
        for key, label in (
            ("difficulty", "难度"),
            ("homework", "作业"),
            ("grading", "给分"),
            ("gain", "收获"),
        ):
            value = course.get(key)
            if value and str(value) not in {"你猜", "未知"}:
                tags.append(f"{label}{value}")
        return "、".join(tags)

    @staticmethod
    def _review_excerpt(review: dict[str, Any], limit: int = 130) -> str:
        text = (review.get("content_text") or "").strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            return "无正文"
        if len(text) > limit:
            return text[:limit] + "..."
        return text

    @staticmethod
    def _first_review_excerpt(reviews: list[dict[str, Any]], limit: int = 90) -> str:
        for review in reviews:
            text = DududaCorePlugin._review_excerpt(review, limit=limit)
            if text and text != "无正文":
                return text
        return ""

    @filter.command_group("dududa", alias={"嘟嘟哒"})
    def dududa(self):
        """嘟嘟哒核心命令组"""
        pass

    @dududa.command("help")
    async def dududa_help(self, event: AstrMessageEvent, module: str | None = None):
        """查看嘟嘟哒帮助"""
        if self._blocked(event):
            return
        yield event.plain_result(module_help(module or ""))
        event.stop_event()

    @filter.command("about")
    async def about(self, event: AstrMessageEvent):
        """查看嘟嘟哒介绍"""
        if self._blocked(event):
            return
        yield event.plain_result(
            "嘟嘟哒是萌萌哒维护的 QQ 群聊 Agent，会聊天、查评课、做提醒入口、整理记忆，也会守住隐私和边界。"
        )
        event.stop_event()

    @filter.command("ping")
    async def ping(self, event: AstrMessageEvent):
        """测试在线状态"""
        if self._blocked(event):
            return
        yield event.plain_result("pong，嘟嘟哒在线。")
        event.stop_event()

    @filter.command("status")
    async def status(self, event: AstrMessageEvent):
        """查看可见运行状态"""
        if self._blocked(event):
            return
        cfg = load_astrbot_config()
        default_provider = cfg.get("provider_settings", {}).get("default_provider_id", "未知")
        role = self.perms.role(event)
        group = self._group_record(event)
        yield event.plain_result(
            "嘟嘟哒状态\n"
            f"角色：{role}\n"
            f"默认模型：{default_provider}\n"
            "多模态：支持，gpt-image-2 可用但较慢\n"
            f"群模式：{group.get('mode')}\n"
            "评课 MCP：icourse 已接入"
        )
        event.stop_event()

    @filter.command("privacy")
    async def privacy(self, event: AstrMessageEvent):
        """查看隐私说明"""
        yield event.plain_result(
            "隐私边界：不跨群泄露，不公开个人课表/成绩/考试，不保存明文密码。"
            "你可以用 /memory 查看、/forget 删除自己在嘟嘟哒核心插件里的记忆。"
        )
        event.stop_event()

    @filter.command("remember")
    async def remember(self, event: AstrMessageEvent, content: GreedyStr):
        """让嘟嘟哒记住一件事"""
        if self._blocked(event):
            return
        rec = self._user_record(event)
        if not rec.get("memory_enabled", True):
            yield event.plain_result("你的个性化记忆当前是关闭的。")
            event.stop_event()
            return
        text = str(content).strip()
        if not text:
            yield event.plain_result("要记住什么呀？")
            event.stop_event()
            return
        rec.setdefault("memories", []).append({"text": text, "time": int(time.time())})
        self._save_user_state()
        self.audit.write(event, "remember", {"chars": len(text)})
        yield event.plain_result("记住啦。")
        event.stop_event()

    @filter.command("forget")
    async def forget(self, event: AstrMessageEvent, keyword: GreedyStr):
        """删除自己的相关记忆"""
        rec = self._user_record(event)
        key = str(keyword).strip()
        memories = rec.get("memories", [])
        kept = [item for item in memories if key not in item.get("text", "")]
        removed = len(memories) - len(kept)
        rec["memories"] = kept
        self._save_user_state()
        self.audit.write(event, "forget", {"removed": removed})
        yield event.plain_result(f"已删除 {removed} 条相关记忆。")
        event.stop_event()

    @filter.command("memory")
    async def memory(self, event: AstrMessageEvent, action: str | None = None):
        """查看或管理自己的记忆"""
        rec = self._user_record(event)
        act = (action or "").strip().lower()
        if act == "off":
            rec["memory_enabled"] = False
            self._save_user_state()
            yield event.plain_result("已关闭你的个性化记忆。")
        elif act == "on":
            rec["memory_enabled"] = True
            self._save_user_state()
            yield event.plain_result("已开启你的个性化记忆。")
        elif act == "export":
            memories = [item.get("text", "") for item in rec.get("memories", [])]
            yield event.plain_result("你的记忆摘要：\n" + ("\n".join(f"- {m}" for m in memories) if memories else "暂无。"))
        else:
            memories = [item.get("text", "") for item in rec.get("memories", [])][-5:]
            style = rec.get("style") or "未设置"
            yield event.plain_result(
                f"记忆开关：{'开' if rec.get('memory_enabled', True) else '关'}\n"
                f"回复偏好：{style}\n"
                + ("最近记忆：\n" + "\n".join(f"- {m}" for m in memories) if memories else "最近记忆：暂无。")
            )
        event.stop_event()

    @filter.command("style")
    async def style(self, event: AstrMessageEvent, mode: str):
        """设置回复偏好"""
        if mode not in {"简洁", "详细", "可爱", "认真"}:
            yield event.plain_result("可选风格：简洁、详细、可爱、认真。")
            event.stop_event()
            return
        rec = self._user_record(event)
        rec["style"] = mode
        self._save_user_state()
        yield event.plain_result(f"好，以后我会更偏向「{mode}」一点。")
        event.stop_event()

    @filter.command_group("course")
    def course(self):
        """课程与评课命令组"""
        pass

    @course.command("stats")
    async def course_stats(self, event: AstrMessageEvent):
        """查看课程缓存规模"""
        try:
            stats = await self.icourse.call("icourse_stats", {})
            yield event.plain_result(format_stats(stats))
        except Exception as exc:
            yield event.plain_result(f"评课 MCP 调用失败：{type(exc).__name__}")
        event.stop_event()

    @course.command("search")
    async def course_search(self, event: AstrMessageEvent, query: GreedyStr):
        """搜索课程"""
        q = str(query).strip()
        if not q:
            yield event.plain_result("用法：/course search <关键词>")
            event.stop_event()
            return
        try:
            reply = await self._answer_natural_course_query(q, f"/course search {q}", event)
        except Exception as exc:
            logger.warning("Course search failed: %s", exc)
            yield event.plain_result(f"评课搜索失败：{type(exc).__name__}")
            event.stop_event()
            return
        yield event.plain_result(reply)
        event.stop_event()

    @course.command("review")
    async def course_review(self, event: AstrMessageEvent, query: GreedyStr):
        """总结公开评课"""
        q = str(query).strip()
        search = await self.icourse.call("search_courses", {"query": q, "limit": 1})
        items = search.get("items") or []
        if not items:
            yield event.plain_result(f"本地缓存里没找到：{q}")
            event.stop_event()
            return
        course_id = items[0].get("id")
        course_result = await self.icourse.call("get_course", {"course_id": course_id, "include_reviews": True})
        course = course_result.get("course") or {}
        reviews = course.get("reviews") or []
        if not reviews:
            review_result = await self.icourse.call("get_reviews", {"course_id": course_id, "limit": 5})
            reviews = review_result.get("reviews") or []
        yield event.plain_result(format_review(course, reviews))
        event.stop_event()

    @course.command("compare")
    async def course_compare(self, event: AstrMessageEvent, query: GreedyStr):
        """比较两个课程或老师"""
        text = str(query)
        parts = [part.strip() for part in text.replace(" vs ", "|").replace(" VS ", "|").split("|") if part.strip()]
        if len(parts) != 2:
            yield event.plain_result("用法：/course compare 课程A | 课程B")
            event.stop_event()
            return
        summaries = []
        for part in parts:
            result = await self.icourse.call("search_courses", {"query": part, "limit": 1})
            items = result.get("items") or []
            if not items:
                summaries.append(f"{part}：未命中缓存")
                continue
            item = items[0]
            summaries.append(
                f"{item.get('name')}：评分 {item.get('rating_average') or '无'}，点评 {item.get('review_count_site') or 0}，ID {item.get('id')}"
            )
        yield event.plain_result("课程比较\n" + "\n".join(f"- {line}" for line in summaries))
        event.stop_event()

    @course.command("refresh")
    async def course_refresh(self, event: AstrMessageEvent, course_id: int):
        """刷新单门课程缓存"""
        if not self.perms.is_trusted(event):
            yield event.plain_result("刷新课程缓存需要 trusted/admin 权限。")
            event.stop_event()
            return
        now = time.monotonic()
        key = str(course_id)
        cooldown = int(self.config.get("course_refresh_cooldown_seconds", 600))
        if now - self.course_refresh_at.get(key, 0) < cooldown:
            yield event.plain_result("这门课刚刷新过，稍等一会儿再试。")
            event.stop_event()
            return
        self.course_refresh_at[key] = now
        result = await self.icourse.call("crawl_course", {"course_id": course_id})
        self.audit.write(event, "course_refresh", {"course_id": course_id})
        yield event.plain_result(f"刷新完成：{result.get('ok', True)}")
        event.stop_event()

    @filter.command_group("notice")
    def notice(self):
        """学院通知命令组"""
        pass

    @notice.command("stats")
    async def notice_stats(self, event: AstrMessageEvent):
        """查看学院通知缓存规模"""
        try:
            stats = await self.college_notice.call("college_notice_stats", {})
            yield event.plain_result(format_college_stats(stats))
        except Exception as exc:
            yield event.plain_result(f"MCP 调用失败：{type(exc).__name__}")
        event.stop_event()

    @notice.command("list")
    async def notice_list(self, event: AstrMessageEvent, college: str | None = None):
        """查看某个学院的通知，可指定学院名"""
        key = str(college or "").strip()
        args: dict[str, Any] = {"limit": 10}
        if key:
            args["college_key"] = key
        result = await self.college_notice.call("get_notices", args)
        yield event.plain_result(format_college_notices(result))
        event.stop_event()

    @notice.command("search")
    async def notice_search(self, event: AstrMessageEvent, query: GreedyStr):
        """按关键词搜索学院通知"""
        q = str(query).strip()
        if not q:
            yield event.plain_result("用法：/notice search <关键词>")
            event.stop_event()
            return
        result = await self.college_notice.call("search_notices", {"query": q, "limit": 10})
        yield event.plain_result(format_college_notices(result))
        event.stop_event()

    @filter.command_group("plan")
    def plan(self):
        """培养方案命令组"""
        pass

    @plan.command("stats")
    async def plan_stats(self, event: AstrMessageEvent):
        """查看培养方案缓存规模"""
        try:
            stats = await self.training_plan.call("plan_stats", {})
            yield event.plain_result(format_plan_stats(stats))
        except Exception as exc:
            yield event.plain_result(f"MCP 调用失败：{type(exc).__name__}")
        event.stop_event()

    @plan.command("colleges")
    async def plan_colleges(self, event: AstrMessageEvent):
        """列出培养方案覆盖的学院"""
        result = await self.training_plan.call("list_colleges", {})
        colleges = result.get("colleges") or []
        if not colleges:
            yield event.plain_result("暂无培养方案数据。")
            event.stop_event()
            return
        lines = [f"培养方案覆盖学院（{len(colleges)}）："]
        for item in colleges:
            lines.append(f"- {item.get('college') or item.get('name') or '?'}")
        yield event.plain_result("\n".join(lines))
        event.stop_event()

    @plan.command("college")
    async def plan_college(self, event: AstrMessageEvent, college: str, year: str | None = None):
        """查看某学院的培养方案（可指定年份）"""
        c = str(college).strip()
        y = int(str(year).strip()) if year and str(year).strip().isdigit() else None
        args: dict[str, Any] = {"college": c}
        if y:
            args["year"] = y
        result = await self.training_plan.call("get_college_majors", args)
        yield event.plain_result(format_majors(result))
        event.stop_event()

    @plan.command("search")
    async def plan_search(self, event: AstrMessageEvent, query: GreedyStr):
        """按关键词搜索培养方案"""
        q = str(query).strip()
        if not q:
            yield event.plain_result("用法：/plan search <专业关键词>")
            event.stop_event()
            return
        result = await self.training_plan.call("search_majors", {"query": q, "limit": 10})
        yield event.plain_result(format_majors(result))
        event.stop_event()

    @filter.command_group("library")
    def library(self):
        """图书馆命令组"""
        pass

    @library.command("stats")
    async def library_stats(self, event: AstrMessageEvent):
        """查看图书馆缓存规模"""
        try:
            stats = await self.library.call("library_stats", {})
            yield event.plain_result(format_library_stats(stats))
        except Exception as exc:
            yield event.plain_result(f"MCP 调用失败：{type(exc).__name__}")
        event.stop_event()

    @library.command("hours")
    async def library_hours(self, event: AstrMessageEvent, campus: str | None = None):
        """查看图书馆开放时间（可指定校区）"""
        args: dict[str, Any] = {}
        c = str(campus or "").strip()
        if c:
            args["campus"] = c
        result = await self.library.call("get_opening_hours", args)
        yield event.plain_result(format_opening_hours(result))
        event.stop_event()

    @library.command("search")
    async def library_search(self, event: AstrMessageEvent, query: GreedyStr):
        """按关键词搜索图书馆服务"""
        q = str(query).strip()
        if not q:
            yield event.plain_result("用法：/library search <关键词>")
            event.stop_event()
            return
        result = await self.library.call("search_hours", {"query": q, "limit": 10})
        yield event.plain_result(format_opening_hours(result))
        event.stop_event()

    @filter.command_group("events")
    def events(self):
        """校园通知命令组"""
        pass

    @events.command("stats")
    async def events_stats(self, event: AstrMessageEvent):
        """查看校园通知缓存规模"""
        try:
            stats = await self.campus_events.call("event_stats", {})
            yield event.plain_result(format_event_stats(stats))
        except Exception as exc:
            yield event.plain_result(f"MCP 调用失败：{type(exc).__name__}")
        event.stop_event()

    @events.command("list")
    async def events_list(self, event: AstrMessageEvent, category: str | None = None, limit: int = 10):
        """查看校园通知，可按类别过滤"""
        key = str(category or "").strip()
        args: dict[str, Any] = {"limit": max(1, min(int(limit or 10), 20))}
        if key:
            args["category"] = key
        result = await self.campus_events.call("get_events", args)
        yield event.plain_result(format_events(result, key or None))
        event.stop_event()

    @events.command("search")
    async def events_search(self, event: AstrMessageEvent, query: GreedyStr):
        """按关键词搜索校园通知"""
        q = str(query).strip()
        if not q:
            yield event.plain_result("用法：/events search <关键词>")
            event.stop_event()
            return
        result = await self.campus_events.call("search_events", {"query": q, "limit": 10})
        yield event.plain_result(format_events(result))
        event.stop_event()

    @filter.command_group("calendar")
    def calendar(self):
        """教学日历命令组"""
        pass

    @calendar.command("today")
    async def calendar_today(self, event: AstrMessageEvent):
        """查看当前学期与今日安排"""
        try:
            result = await self.academic_calendar.call("get_current_term", {})
            if result.get("ok"):
                yield event.plain_result(format_current_term(result))
                event.stop_event()
                return
            terms = await self.academic_calendar.call("list_terms", {})
            term_list = terms.get("terms") or []
            if not term_list:
                yield event.plain_result("教学日历暂无数据，可让管理员用 /admin mcp refresh calendar 拉取。")
                event.stop_event()
                return
            name = term_list[0].get("name") or term_list[0].get("term_name") or "?"
            detail = await self.academic_calendar.call("get_term", {"term_name": name})
            if not detail.get("ok") or not detail.get("term"):
                yield event.plain_result("教学日历已连接但当前学期未缓存，可让管理员用 /admin mcp refresh calendar 拉取。")
                event.stop_event()
                return
            term = detail["term"]
            notes = term.get("notes") or []
            events = term.get("events") or []
            lines = [f"教学日历：{term.get('name') or name}", f"学期说明：{notes[0] if notes else '无'}"]
            upcoming = sorted(events, key=lambda e: e.get("date") or "")[:6]
            if upcoming:
                lines.append("近期安排：")
                for item in upcoming:
                    title = (item.get("event_name") or "").strip()
                    lines.append(f"- {item.get('date')} {title}")
            lines.append("（学期尚未开始或未在进行中，以上为日历内容）")
            yield event.plain_result("\n".join(lines))
        except Exception as exc:
            yield event.plain_result(f"教学日历 MCP 调用失败：{type(exc).__name__}")
        event.stop_event()

    @calendar.command("terms")
    async def calendar_terms(self, event: AstrMessageEvent):
        """列出已知学期"""
        try:
            result = await self.academic_calendar.call("list_terms", {})
            yield event.plain_result(format_terms(result))
        except Exception as exc:
            yield event.plain_result(f"教学日历 MCP 调用失败：{type(exc).__name__}")
        event.stop_event()

    @calendar.command("date")
    async def calendar_date(self, event: AstrMessageEvent, date: str | None = None):
        """查看某天的教学安排，如 /calendar date 2026-08-22"""
        target = str(date or "").strip() or "today"
        result = await self.academic_calendar.call("get_events", {"date": target})
        yield event.plain_result(format_calendar_events(result))
        event.stop_event()

    @calendar.command("search")
    async def calendar_search(self, event: AstrMessageEvent, query: GreedyStr):
        """按关键词搜索教学安排，如 /calendar search 考试"""
        q = str(query).strip()
        if not q:
            yield event.plain_result("用法：/calendar search <关键词>")
            event.stop_event()
            return
        result = await self.academic_calendar.call("search_events", {"query": q, "limit": 15})
        events = result.get("events") or []
        if not events:
            yield event.plain_result("没有找到匹配的教学安排，可让管理员刷新缓存后再试。")
            event.stop_event()
            return
        lines = [f"教学安排搜索：{q}", f"共 {len(events)} 条："]
        for item in events[:15]:
            term_name = item.get("term_name") or ""
            week = item.get("week_label") or ""
            title = (item.get("event_name") or "").strip()
            lines.append(f"- [{term_name}] {week} {title}".rstrip())
        yield event.plain_result("\n".join(lines))
        event.stop_event()

    @calendar.command("stats")
    async def calendar_stats(self, event: AstrMessageEvent):
        """查看教学日历缓存规模"""
        try:
            stats = await self.academic_calendar.call("calendar_stats", {})
            yield event.plain_result(format_calendar_stats(stats))
        except Exception as exc:
            yield event.plain_result(f"教学日历 MCP 调用失败：{type(exc).__name__}")
        event.stop_event()

    @filter.command_group("admin")
    def admin(self):
        """管理员命令组"""
        pass

    @admin.command("status")
    async def admin_status(self, event: AstrMessageEvent):
        """查看管理状态"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        cfg = load_astrbot_config()
        mcp_names = ["icourse", "college_notice", "training_plan", "library", "campus_events", "academic_calendar"]
        yield event.plain_result(
            "管理状态\n"
            f"default_provider_id: {cfg.get('provider_settings', {}).get('default_provider_id')}\n"
            f"owner_count: {len(self.perms.owners)}\n"
            f"global_admin_count: {len(self.perms.global_admins)}\n"
            f"pending_confirmations: {len(self.pending)}\n"
            f"audit_log: {self.audit.path}\n"
            f"mcp_clients: {', '.join(mcp_names)}"
        )
        event.stop_event()

    @admin.command("plugins")
    async def admin_plugins(self, event: AstrMessageEvent):
        """查看插件列表"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        plugins_dir = Path(__file__).resolve().parents[1]
        names = sorted(p.name for p in plugins_dir.iterdir() if p.is_dir())
        yield event.plain_result("已安装插件：\n" + "\n".join(f"- {name}" for name in names))
        event.stop_event()

    @admin.command("mcp")
    async def admin_mcp(self, event: AstrMessageEvent, action: str = "list", name: str | None = None):
        """管理 MCP"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        clients = {
            "icourse": (self.icourse, "icourse-mcp"),
            "college_notice": (self.college_notice, "college-notice-mcp"),
            "training_plan": (self.training_plan, "training-plan-mcp"),
            "library": (self.library, "library-mcp"),
            "campus_events": (self.campus_events, "campus-events-mcp"),
            "academic_calendar": (self.academic_calendar, "academic-calendar-mcp"),
        }
        if action == "list":
            lines = ["MCP 列表："]
            for key, (client, root_name) in clients.items():
                try:
                    tools = await client.list_tools()
                    lines.append(f"- {key}：已接入（{len(tools)} 个工具）")
                except Exception as exc:
                    lines.append(f"- {key}：异常（{type(exc).__name__}）")
            yield event.plain_result("\n".join(lines))
        elif action == "test":
            key = (name or "icourse").strip()
            client, _ = clients.get(key, (None, None))
            if client is None:
                yield event.plain_result(f"未知 MCP：{key}。可用：{', '.join(clients)}")
                event.stop_event()
                return
            try:
                tools = await client.list_tools()
                yield event.plain_result(f"MCP {key} 可用工具：\n" + "\n".join(f"- {tool}" for tool in tools))
            except Exception as exc:
                yield event.plain_result(f"MCP {key} 测试失败：{type(exc).__name__}：{exc}")
        elif action == "refresh":
            key = (name or "").strip()
            refresh_ops = {
                "icourse": ("crawl_latest_reviews", {"pages": 1, "per_page": 10}),
                "college_notice": ("refresh_lists", {"college_key": None}),
                "training_plan": ("refresh_programs", {}),
                "library": ("refresh_hours", {}),
                "campus_events": ("refresh_lists", {"only_refresh": False}),
                "academic_calendar": ("get_current_term", {"refresh": True}),
            }
            if key not in refresh_ops:
                yield event.plain_result(f"未知 MCP：{key}。可用 refresh：{', '.join(refresh_ops)}")
                event.stop_event()
                return
            client, _ = clients[key]
            try:
                tool, args = refresh_ops[key]
                result = await client.call(tool, args)
                ok = result.get("ok", True)
                yield event.plain_result(f"MCP {key} 刷新完成（ok={ok}）：\n{result}")
            except Exception as exc:
                yield event.plain_result(f"MCP {key} 刷新失败：{type(exc).__name__}：{exc}")
        else:
            yield event.plain_result("用法：/admin mcp list | /admin mcp test <name> | /admin mcp refresh <name>")
        event.stop_event()

    @admin.command("group")
    async def admin_group(self, event: AstrMessageEvent, action: str, value: str | None = None):
        """设置群模式和概率"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        rec = self._group_record(event)
        if action == "mode" and value in {"quiet", "normal", "active"}:
            rec["mode"] = value
        elif action == "reply-rate" and value and value.isdigit():
            rec["reply_rate"] = max(0, min(100, int(value)))
        elif action == "meme-rate" and value and value.isdigit():
            rec["meme_rate"] = max(0, min(100, int(value)))
        else:
            yield event.plain_result("用法：/admin group mode <quiet|normal|active> 或 reply-rate/meme-rate <0-100>")
            event.stop_event()
            return
        self._save_group_state()
        self.audit.write(event, "admin_group", {"action": action, "value": value})
        yield event.plain_result(f"已更新本群设置：{rec}")
        event.stop_event()

    @admin.command("user")
    async def admin_user(self, event: AstrMessageEvent, action: str, qq: str):
        """限制或解除用户"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        group_id = self._group(event)
        if not group_id:
            yield event.plain_result("群级禁用请在群聊中执行；全局禁用请由 owner 使用 /admin permission grant <QQ> muted。")
            event.stop_event()
            return
        rec = self._group_record(event)
        muted = str_set(rec.get("muted_users", []))
        if action == "mute":
            muted.add(str(qq))
            msg = f"已在本群限制 {qq} 调用嘟嘟哒。"
        elif action == "unmute":
            muted.discard(str(qq))
            msg = f"已解除 {qq} 在本群的调用限制。"
        else:
            yield event.plain_result("用法：/admin user mute <QQ> 或 /admin user unmute <QQ>")
            event.stop_event()
            return
        rec["muted_users"] = sorted(muted)
        self._save_group_state()
        self.audit.write(event, "admin_user", {"action": action, "target": qq, "group_scope": group_id})
        yield event.plain_result(msg)
        event.stop_event()

    @admin.command("memory")
    async def admin_memory(self, event: AstrMessageEvent, action: str):
        """管理记忆"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        if action == "summary":
            total = sum(len(v.get("memories", [])) for v in self.user_state.values() if isinstance(v, dict))
            yield event.plain_result(f"嘟嘟哒核心轻量记忆：用户 {len(self.user_state)} 个，条目 {total} 条。Iris 记忆请在 Iris 面板查看。")
        elif action == "clear-short":
            token = self._new_confirmation(event, "memory_clear_short", {})
            yield event.plain_result(f"该操作会清理嘟嘟哒核心临时确认队列。请回复 /confirm {token}")
        else:
            yield event.plain_result("用法：/admin memory summary 或 /admin memory clear-short")
        event.stop_event()

    @admin.command("logs")
    async def admin_logs(self, event: AstrMessageEvent, action: str = "errors", value: str | None = None):
        """查看脱敏日志摘要"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        limit = 10
        if action == "tail":
            owner_err = self._require_owner(event)
            if owner_err:
                yield event.plain_result(owner_err)
                event.stop_event()
                return
            if value and value.isdigit():
                limit = max(1, min(50, int(value)))
        elif action != "errors":
            yield event.plain_result("用法：/admin logs errors 或 /admin logs tail <行数>")
            event.stop_event()
            return
        records = self.audit.tail(limit)
        if not records:
            yield event.plain_result("审计日志暂无记录。")
        else:
            lines = [f"- {r.get('time')} {r.get('action')} sender={r.get('sender')} group={r.get('group')}" for r in records]
            yield event.plain_result("最近审计：\n" + "\n".join(lines))
        event.stop_event()

    @admin.command("backup")
    async def admin_backup(self, event: AstrMessageEvent, action: str = "create"):
        """创建配置备份"""
        err = self._require_owner(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        token = self._new_confirmation(event, "backup_create", {"action": action})
        yield event.plain_result(f"将备份 AstrBot 主配置。请回复 /confirm {token}")
        event.stop_event()

    @admin.command("restart")
    async def admin_restart(self, event: AstrMessageEvent, service: str):
        """重启服务提示"""
        err = self._require_owner(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        if service not in {"astrbot", "napcat"}:
            yield event.plain_result("只能申请重启 astrbot 或 napcat。NapCat 不会由 QQ 命令直接重启。")
            event.stop_event()
            return
        token = self._new_confirmation(event, "restart", {"service": service})
        yield event.plain_result(f"重启 {service} 是高风险操作。请回复 /confirm {token}")
        event.stop_event()

    @admin.command("model")
    async def admin_model(
        self,
        event: AstrMessageEvent,
        action: str = "route",
        scene: str | None = None,
        model: str | None = None,
    ):
        """查看模型路由"""
        if action == "set":
            err = self._require_owner(event)
            if err:
                yield event.plain_result(err)
                event.stop_event()
                return
            if not scene or not model:
                yield event.plain_result("用法：/admin model set <default|image> <模型ID>")
                event.stop_event()
                return
            if scene not in {"default", "image"}:
                yield event.plain_result("当前只支持设置 default 或 image 场景。")
                event.stop_event()
                return
            token = self._new_confirmation(event, "model_set", {"scene": scene, "model": model})
            yield event.plain_result(f"切换 {scene} 模型到 {model} 需要确认。请回复 /confirm {token}")
            event.stop_event()
            return
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        cfg = load_astrbot_config()
        yield event.plain_result(
            "模型路由\n"
            f"默认：{cfg.get('provider_settings', {}).get('default_provider_id')}\n"
            "文本/工具：openai/gpt-5.5\n"
            "图像生成：gpt-image-2，可用但较慢。"
        )
        event.stop_event()

    @admin.command("permission")
    async def admin_permission(self, event: AstrMessageEvent, action: str, qq: str, role: str):
        """修改全局权限"""
        err = self._require_owner(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        role_key = role.strip().lower()
        if action not in {"grant", "revoke"} or role_key not in {"owner", "admin", "trusted", "muted"}:
            yield event.plain_result("用法：/admin permission <grant|revoke> <QQ> <owner|admin|trusted|muted>")
            event.stop_event()
            return
        token = self._new_confirmation(
            event,
            "permission_change",
            {"action": action, "qq": str(qq), "role": role_key},
        )
        yield event.plain_result(f"全局权限变更需要确认。请回复 /confirm {token}")
        event.stop_event()

    @admin.command("broadcast")
    async def admin_broadcast(self, event: AstrMessageEvent, content: GreedyStr):
        """申请群发"""
        err = self._require_owner(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        text = str(content).strip()
        if not text:
            yield event.plain_result("用法：/admin broadcast <内容>")
            event.stop_event()
            return
        token = self._new_confirmation(event, "broadcast", {"chars": len(text)})
        yield event.plain_result(f"群发是高风险操作，已记录摘要但不会回显原文。请回复 /confirm {token}")
        event.stop_event()

    @filter.command("confirm")
    async def confirm(self, event: AstrMessageEvent, token: str):
        """确认高风险操作"""
        pending = self.pending.get(token.upper())
        if not pending:
            yield event.plain_result("没有找到这个确认 token。")
            event.stop_event()
            return
        if pending.requester != self._sender(event):
            yield event.plain_result("只有操作发起者可以确认。")
            event.stop_event()
            return
        if time.time() > pending.expires_at:
            self.pending.pop(token.upper(), None)
            yield event.plain_result("确认 token 已过期。")
            event.stop_event()
            return
        msg = self._execute_pending(event, pending)
        self.pending.pop(token.upper(), None)
        self.audit.write(event, "confirm_executed", {"action": pending.action})
        yield event.plain_result(msg)
        event.stop_event()

    @filter.command("cancel")
    async def cancel(self, event: AstrMessageEvent, token: str):
        """取消高风险操作"""
        pending = self.pending.get(token.upper())
        if not pending:
            yield event.plain_result("没有找到这个确认 token。")
        elif pending.requester != self._sender(event):
            yield event.plain_result("只有操作发起者可以取消。")
        else:
            self.pending.pop(token.upper(), None)
            self.audit.write(event, "confirm_cancelled", {"action": pending.action})
            yield event.plain_result("已取消。")
        event.stop_event()

    def _execute_pending(self, event: AstrMessageEvent, pending: PendingAction) -> str:
        if pending.action == "memory_clear_short":
            self.pending.clear()
            return "已清理嘟嘟哒核心临时确认队列。"
        if pending.action == "backup_create":
            backup = ASTRBOT_CONFIG_PATH.with_suffix(f".json.bak_dududa_{int(time.time())}")
            backup.write_bytes(ASTRBOT_CONFIG_PATH.read_bytes())
            return f"已创建配置备份：{backup.name}"
        if pending.action == "permission_change":
            return self._apply_permission_change(pending.payload)
        if pending.action == "model_set":
            return self._apply_model_set(pending.payload)
        if pending.action == "broadcast":
            return "群发确认已记录。为避免误发，当前 QQ 指令不会直接群发；请在后台按审计记录人工执行。"
        if pending.action == "restart":
            service = pending.payload.get("service")
            return f"重启 {service} 的确认已记录。容器重启需要宿主机执行 ./manage.sh restart {service}，不会在 QQ 内直接执行。"
        return "确认完成，但该动作还没有执行器。"

    def _apply_permission_change(self, payload: dict[str, Any]) -> str:
        action = str(payload.get("action") or "")
        qq = str(payload.get("qq") or "")
        role = str(payload.get("role") or "")
        key_by_role = {
            "owner": "owners",
            "admin": "global_admins",
            "trusted": "trusted_users",
            "muted": "muted_users",
        }
        key = key_by_role.get(role)
        if action not in {"grant", "revoke"} or not qq or not key:
            return "权限变更参数无效，未执行。"
        cfg = load_plugin_config() or dict(self.config)
        values = str_set(cfg.get(key, []))
        if action == "grant":
            values.add(qq)
        else:
            values.discard(qq)
        cfg[key] = sorted(values)
        save_plugin_config(cfg)
        self._reload_permissions()
        label = "授予" if action == "grant" else "撤销"
        return f"已{label} {qq} 的 {role} 权限。"

    def _apply_model_set(self, payload: dict[str, Any]) -> str:
        scene = str(payload.get("scene") or "")
        model = str(payload.get("model") or "")
        if scene == "image" and model:
            cfg = load_plugin_config() or dict(self.config)
            cfg["image_model_id"] = model
            save_plugin_config(cfg)
            self.config = cfg
            return f"已将 image 场景模型记录为 {model}。"
        if scene == "default" and model:
            astrbot_cfg = load_astrbot_config()
            provider_ids = {
                str(item.get("id"))
                for item in astrbot_cfg.get("provider", [])
                if isinstance(item, dict) and item.get("id")
            }
            if model not in provider_ids:
                return f"未找到 provider：{model}，未切换默认模型。"
            backup = ASTRBOT_CONFIG_PATH.with_suffix(f".json.bak_model_set_{int(time.time())}")
            backup.write_bytes(ASTRBOT_CONFIG_PATH.read_bytes())
            astrbot_cfg.setdefault("provider_settings", {})["default_provider_id"] = model
            save_astrbot_config(astrbot_cfg)
            cfg = load_plugin_config() or dict(self.config)
            cfg["default_model_id"] = model
            save_plugin_config(cfg)
            self.config = cfg
            return f"已将默认模型配置为 {model}；如未即时生效，请重启 AstrBot。"
        return "模型切换参数无效，未执行。"

    @filter.command("remind")
    async def remind(self, event: AstrMessageEvent, text: GreedyStr):
        """提醒入口"""
        yield event.plain_result("提醒能力由 Better Reminder 处理。请直接说：提醒我 <时间> <内容>。")
        event.stop_event()

    @filter.command("reminders")
    async def reminders(self, event: AstrMessageEvent):
        """查看提醒入口"""
        yield event.plain_result("查看提醒请使用现有命令：/提醒列表 或 /查看提醒。后续会接入统一列表。")
        event.stop_event()

    @filter.command("summary")
    async def summary(self, event: AstrMessageEvent, scope: str | None = None):
        """群聊总结入口"""
        yield event.plain_result("群聊总结由 ChatSummary v2 提供。当前统一入口已登记，后续会接入原插件命令映射。")
        event.stop_event()

    @filter.command("meme")
    async def meme(self, event: AstrMessageEvent, keyword: str | None = None):
        """表情包入口"""
        yield event.plain_result("表情包能力由 Meme Manager 提供。可继续使用现有表情包命令；/meme 统一入口已预留。")
        event.stop_event()

    @filter.command("image")
    async def image(self, event: AstrMessageEvent, prompt: GreedyStr):
        """生成图片"""
        if not self.perms.is_trusted(event):
            yield event.plain_result("gpt-image-2 可用但较慢，当前只开放给 trusted/admin。")
            event.stop_event()
            return
        text = str(prompt).strip()
        if not text:
            yield event.plain_result("请给我一段图片描述。")
            event.stop_event()
            return
        blocked = self._image_prompt_block_reason(text)
        if blocked:
            yield event.plain_result(blocked)
            event.stop_event()
            return
        yield event.plain_result("开始生成图片，gpt-image-2 可能会慢一点。")
        try:
            image_component = await self._generate_image(text)
        except ImageGenerationError as exc:
            logger.warning("Dududa image generation failed: %s", exc)
            yield event.plain_result(f"图片生成失败：{exc.user_message}")
            event.stop_event()
            return
        except httpx.TimeoutException as exc:
            logger.warning("Dududa image generation timed out: %s", exc)
            yield event.plain_result("图片生成超时：gpt-image-2 这次等太久了，可以稍后重试，或把描述写短一点。")
            event.stop_event()
            return
        except Exception as exc:
            logger.warning("Dududa image generation failed unexpectedly: %s", exc)
            yield event.plain_result(f"图片生成失败：{type(exc).__name__}")
            event.stop_event()
            return
        self.audit.write(event, "image_generate", {"chars": len(text)})
        yield event.chain_result([image_component])
        event.stop_event()

    @filter.command("fortune")
    async def fortune(self, event: AstrMessageEvent):
        """今日运势"""
        choices = ["适合写代码", "适合补觉", "适合查评课", "适合把 TODO 拆小", "适合先喝水"]
        yield event.plain_result("今日建议：" + random.choice(choices))
        event.stop_event()

    @filter.command("draw")
    async def draw(self, event: AstrMessageEvent, topic: GreedyStr):
        """抽签"""
        options = ["可以", "再想想", "先做最小版本", "交给明天的自己", "值得认真试试"]
        yield event.plain_result(f"{topic}：{random.choice(options)}")
        event.stop_event()

    @filter.command("poke")
    async def poke(self, event: AstrMessageEvent):
        """戳一戳入口"""
        yield event.plain_result("戳一戳能力由 PokePro 提供，统一入口已预留。")
        event.stop_event()

    @filter.command("reread")
    async def reread(self, event: AstrMessageEvent):
        """复读入口"""
        yield event.plain_result("复读能力由 Reread 提供，统一入口已预留。")
        event.stop_event()

    def _openai_source(self) -> tuple[str, str, dict[str, str]]:
        cfg = load_astrbot_config()
        for source in cfg.get("provider_sources", []):
            if source.get("id") != "openai":
                continue
            raw_key = source.get("key")
            if isinstance(raw_key, list):
                keys = [str(item) for item in raw_key if str(item).strip()]
            elif raw_key:
                keys = [str(raw_key)]
            else:
                keys = []
            if not keys:
                raise RuntimeError("openai provider has no api key")
            custom_headers = {
                str(key): str(value)
                for key, value in (source.get("custom_headers") or {}).items()
                if str(key).strip() and str(value).strip()
            }
            return str(source.get("api_base", "")).rstrip("/"), keys[0], custom_headers
        raise RuntimeError("openai provider source not found")

    async def _generate_image(self, prompt: str) -> Image:
        base_url, api_key, custom_headers = self._openai_source()
        model = str(self.config.get("image_model_id", "gpt-image-2") or "gpt-image-2")
        timeout_seconds = self._clamp_int(self.config.get("image_timeout_seconds", 420), 420, 60, 900)
        payload = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", **custom_headers}
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(f"{base_url}/images/generations", headers=headers, json=payload)
        if response.status_code >= 400:
            raise self._image_api_error(response)
        data = response.json()
        item = (data.get("data") or [{}])[0]
        if item.get("b64_json"):
            raw = item["b64_json"]
            base64.b64decode(raw)
            return Image.fromBase64(raw)
        if item.get("url"):
            return Image.fromURL(item["url"])
        raise RuntimeError("image api returned no image data")

    @staticmethod
    def _image_api_error(response: httpx.Response) -> ImageGenerationError:
        status = response.status_code
        code = ""
        message = response.text[:200]
        try:
            data = response.json()
        except ValueError:
            data = {}
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code") or "")
            message = str(error.get("message") or message).strip()
        log_message = f"image api status {status}: {code or 'unknown'}: {message[:200]}"
        if code == "content_policy_violation":
            return ImageGenerationError(
                "请求被图像模型安全策略拒绝。当前服务商对低龄角色、性化、暴力和伪造类描述很敏感；"
                "可以把“小女孩/小男孩”改成“Q版小精灵/卡通角色”后重试。",
                log_message,
            )
        if status in {401, 403}:
            return ImageGenerationError("图像模型鉴权失败，请检查 openai 账号组和图像模型权限。", log_message)
        if status == 429:
            return ImageGenerationError("图像模型当前限流了，稍后再试。", log_message)
        if status >= 500:
            return ImageGenerationError("图像模型服务端暂时异常，稍后再试。", log_message)
        return ImageGenerationError(f"图像模型返回 {status}，这次请求没有被接受。", log_message)

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _image_prompt_block_reason(prompt: str) -> str | None:
        lowered = prompt.lower()
        unsafe_terms = [
            "色情",
            "裸",
            "nsfw",
            "性化",
            "擦边",
            "未成年",
            "儿童",
            "孩子",
            "小孩",
            "小女孩",
            "小男孩",
            "幼女",
            "萝莉",
            "正太",
            "证件",
            "成绩单",
            "官方通知",
            "伪造",
        ]
        if any(term in lowered for term in unsafe_terms):
            return "这个图片请求不适合生成，我不能帮忙做色情、低龄角色、擦边或伪造证件/成绩单/官方通知类图片。可以改成 Q版小精灵、卡通角色或原创吉祥物。"
        return None
