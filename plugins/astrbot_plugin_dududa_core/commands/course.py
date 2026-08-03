from __future__ import annotations

import re
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr

from ..course import format_review, format_stats
from ..help_menu import module_help


class CoreCourseCommands:
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
    def _extract_course_query(self, text: str) -> str | None:
        if not text or text.startswith("/"):
            return None
        if CoreCourseCommands._is_icourse_site_meta_question(text):
            return None
        trigger = re.search(
            r"评课社区[\s，。！？、；：,.!?;:（）()【】\[\]\"'“”‘’]*搜索",
            text,
        )
        if not trigger:
            return None

        query = CoreCourseCommands._clean_course_query_text(text[trigger.end() :])
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
        reviews = CoreCourseCommands._course_review_count(item) or 0
        return rating, reviews

    @staticmethod
    def _course_item_line(item: dict[str, Any]) -> str:
        teachers = CoreCourseCommands._teacher_names(item) or "教师未知"
        return (
            f"{item.get('id')} | {item.get('name')} | {teachers} | "
            f"评分 {item.get('rating_average') or '无'} | 点评 {CoreCourseCommands._course_review_count(item) or 0}"
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
            text = CoreCourseCommands._review_excerpt(review, limit=limit)
            if text and text != "无正文":
                return text
        return ""

    async def course_stats(self, event: AstrMessageEvent):
        """查看课程缓存规模"""
        try:
            stats = await self.icourse.call("icourse_stats", {})
            yield event.plain_result(format_stats(stats))
        except Exception as exc:
            yield event.plain_result(f"评课 MCP 调用失败：{type(exc).__name__}")
        event.stop_event()

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
