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
from astrbot.api.message_components import At, Image
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
from .catalog import CatalogClient, format_open_result
from .course import ICourseClient, format_review, format_search, format_stats
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
        self.catalog = CatalogClient()
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

        open_query = self._extract_open_query(text)
        if open_query:
            # AI 审查：确认真的是在查询开课信息，而不是"我们班还没开课"这类陈述
            if not await self._ai_confirm_course_intent(text):
                return
            try:
                reply = await self._catalog_open(open_query)
            except Exception as exc:
                logger.warning("Natural catalog open query failed: %s", exc)
                yield event.plain_result(f"开课信息查询失败：{type(exc).__name__}")
                event.stop_event()
                return
            self.audit.write(event, "natural_catalog_open", {"query": open_query[:80]})
            yield event.plain_result(reply)
            event.stop_event()
            return

        query = self._extract_course_query(text)
        if not query:
            if self._is_at_bot(event):
                tc = self._extract_teacher_course(text)
                if tc and self._looks_like_course_intent(text, tc):
                    try:
                        # 意图判断已合并进整合查询的 LLM 分析中（一次调用完成）
                        reply = await self._answer_teacher_course_integrated(tc, text)
                    except Exception as exc:
                        logger.warning("At-bot teacher/course failed: %s", exc)
                        yield event.plain_result(f"课程查询失败：{type(exc).__name__}")
                        event.stop_event()
                        return
                    if reply is None:
                        # LLM 判定这不是课程查询（陈述/闲聊），放行给普通聊天
                        return
                    self.audit.write(event, "at_bot_course", {"query": tc[:60]})
                    yield event.plain_result(reply)
                    event.stop_event()
                    return
            return
        try:
            if self._looks_like_specific_lookup(text):
                reply = await self._answer_teacher_course_integrated(query, text)
                if reply is None:
                    return
            else:
                reply = await self._answer_natural_course_query(query, text, event)
        except Exception as exc:
            logger.warning("Natural icourse query failed: %s", exc)
            yield event.plain_result(f"评课社区查询失败：{type(exc).__name__}")
            event.stop_event()
            return
        self.audit.write(event, "natural_course_query", {"query": query[:60]})
        yield event.plain_result(reply)
        event.stop_event()

    @filter.command("open")
    async def open_lesson(self, event: AstrMessageEvent, query: GreedyStr):
        """查询公开开课信息：课堂时间、容量、老师、校区。

        用法：/open <课程名或课程代码>  ；/open sync [学期id] ；/open semester
        """
        if self._blocked(event):
            return
        text = str(query).strip()
        if text == "":
            yield event.plain_result("用法：/open <课程名或代码>  例如 /open 热力学  、/open 022063")
            event.stop_event()
            return
        sub, _, rest = text.partition(" ")
        try:
            if sub == "sync":
                semester = int(rest.strip()) if rest.strip().isdigit() else None
                reply = await self._catalog_sync(semester)
            elif sub == "semester":
                reply = await self._catalog_semester_help()
            else:
                reply = await self._catalog_open(text)
        except Exception as exc:
            logger.warning("Catalog open query failed: %s", exc)
            yield event.plain_result(f"开课查询失败：{type(exc).__name__}")
            event.stop_event()
            return
        self.audit.write(event, "catalog_open", {"query": text[:80]})
        yield event.plain_result(reply)
        event.stop_event()

    async def _catalog_semester_help(self) -> str:
        result = await self.catalog.call("catalog_semesters", {"limit": 8})
        sems = result.get("semesters") or []
        lines = ["可同步的开课学期："]
        for s in sems:
            lines.append(f"  {s.get('id')} | {s.get('name')} | {s.get('start')}")
        lines.append("同步：/open sync <学期id>  （会下载该学期全部公开开课并缓存）")
        return "\n".join(lines)

    async def _catalog_sync(self, semester: int | None) -> str:
        if semester:
            result = await self.catalog.call("catalog_sync", {"semester": semester})
            return f"已同步学期 {result.get('semester')}：缓存 {result.get('cached_lessons')} 门开课。"
        sems = await self.catalog.call("catalog_semesters", {"limit": 1})
        first = (sems.get("semesters") or [{}])[0]
        sid = first.get("id")
        if not sid:
            return "无法获取最新学期，请指定 /open sync <学期id>。"
        result = await self.catalog.call("catalog_sync", {"semester": sid})
        return f"已同步最新学期 {result.get('semester')}（{first.get('name')}）：缓存 {result.get('cached_lessons')} 门开课。"

    async def _catalog_open(self, query: str) -> str:
        result = await self.catalog.call("catalog_open", {"query": query, "limit": 6})
        if not result.get("ok"):
            return "开课查询失败：" + str(result.get("error") or result)
        return format_open_result(result, query)

    _OPEN_TRIGGERS = (
        "开课",
        "课堂容量",
        "上课时间",
        "上课安排",
        "授课时间",
        "几点上",
        "什么时候上课",
        "课表",
        "容量",
        "招生人数",
        "选课人数",
    )

    @staticmethod
    def _extract_open_query(text: str) -> str | None:
        if not text or text.startswith("/"):
            return None
        if not any(word in text for word in DududaCorePlugin._OPEN_TRIGGERS):
            return None
        cleaned = DududaCorePlugin._clean_course_query_text(text)
        cleaned = re.sub(r"(?i)开课|课堂容量|上课时间|上课安排|授课时间|几点上|什么时候上课|课表|容量|招生人数|选课人数", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip().strip("？！:：。，,;；")
        return cleaned[:80] or None

    @staticmethod
    def _is_at_bot(event: AstrMessageEvent) -> bool:
        """可靠判断消息是否 @ 了 bot 自己（遍历消息组件里的 At）。"""
        try:
            self_id = str(event.get_self_id())
        except Exception:
            self_id = ""
        try:
            for msg in event.get_messages() or []:
                if isinstance(msg, At):
                    qq = str(getattr(msg, "qq", "") or "")
                    if qq == self_id or qq == "all":
                        return True
        except Exception:
            pass
        return False

    @staticmethod
    def _extract_teacher_course(text: str) -> str | None:
        """从 @bot 消息里提取 老师名/课程名 作为查询词。"""
        if not text or text.startswith("/"):
            return None
        pure = re.sub(r"[\s，。！？、；：,.!?;:（）()【】\[\]\"'“”‘’@～~]+", "", text)
        if not pure or len(pure) > 40:
            return None
        # 排除纯问候/表情/管理话术
        if re.fullmatch(r"(你好|在吗|嗨|哈喽|hi|hello|早上好|晚上好|在不在|help|帮助|谢谢|再见|拜拜)[！!。？?，,~]?", pure, re.IGNORECASE):
            return None
        if re.search(r"(admin|管理|插件|日志|重启|配置|权限|天气|气温|多少度|几点起床|几点睡|帮我|能不能|可以吗|说说看|讲个)", pure, re.IGNORECASE):
            return None
        cleaned = DududaCorePlugin._clean_course_query_text(text)
        # 剥离疑问/请求话术，只留下课程名/老师名
        for phrase in (
            "怎么学", "学谁", "谁比较好", "谁最好", "哪位老师好", "哪个老师好", "哪个好",
            "推荐", "求推荐", "应该", "怎么样", "什么时候上", "什么时候上课", "什么时候",
            "难不难", "难吗", "好不好", "如何", "给分", "作业多不多", "作业多吗", "在哪上",
            "在哪上课", "在哪个教室", "上课时间", "课表", "怎么样学", "该不该选", "值得选吗",
            "值不值得", "想选", "选课", "考试难不难", "考试", "怎么复习", "复习", "学得怎么样",
            "比较好", "比较", "咋样", "咋学", "咋选", "呢", "呀",
        ):
            cleaned = cleaned.replace(phrase, " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) < 2 or len(cleaned) > 30:
            return None
        # 老师名 + 课程名：返回完整清理串作为查询
        return cleaned[:80]

    @staticmethod
    def _looks_like_course_intent(text: str, tc: str) -> bool:
        """判断 @bot 消息是否像在问课程/老师，避免干扰其他功能。"""
        if not text:
            return False
        # 精准信号：双字以上的课程查询意图词（去掉单个"课"字，避免"课表/上课/下课"误触发）
        signals = (
            "选课", "选什么课", "哪门课", "这门课", "那个课", "评课", "评价",
            "给分", "作业多", "作业少", "难度", "难不难", "怎么学", "什么时候上",
            "上课时间", "考试", "学分", "学时", "哪位老师", "哪个老师", "老师好",
            "老师怎么样", "推荐老师", "班型", "系列", "教材", "先修", "好不好过",
            "学谁", "谁教", "谁教得好", "怎么样",
        )
        if any(w in text for w in signals):
            return True
        # 提取词像课程名（含课程特征字）
        if re.search(r"(分析|物理|数学|化学|英语|力学|结构|概论|导论|原理|方法|程序|语言|统计|概率|方程|实验|生物|经济|管理|哲学|历史|电路|信号|线代|代数)", tc):
            return True
        # 提取词像人名：2-3个汉字且以常见姓氏开头，才视为老师查询
        surnames = (
            "陈王李张刘罗吴徐孙程赵周黄杨朱何郑谢冯宋唐许邓韩曹彭肖田董袁潘蒋蔡余杜叶苏魏吕丁沈任姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤胡郭林梁马高宋唐侯郑"
        )
        if re.fullmatch(r"[\u4e00-\u9fff]{2,3}", tc) and tc[0] in surnames:
            return True
        return False

    async def _ai_confirm_course_intent(self, text: str) -> bool:
        """AI 审查：确认消息真的是在问课程/老师，而不是闲聊。"""
        prompt = (
            f'用户消息："{text}"\n\n'
            "请判断这条消息是不是在向机器人查询课程相关信息（例如：问某门课怎么样、"
            "选哪位老师好、上课时间地点、课程难度给分、某位老师的评价、某门课什么时候开课等）。\n"
            "注意区分查询和陈述：\n"
            "- 查询：用户在问机器人要答案（如\"数学分析什么时候上课\"\"XX课在哪上\"\"查一下XX老师\"）；\n"
            "- 陈述：用户只是在陈述自己的情况（如\"我们班还没开课\"\"我今天有课\"\"我们课表出来了\"），并不是在问机器人。\n"
            "如果是查询，只回复「是」；如果是陈述、闲聊、寒暄、或与课程查询无关的内容，只回复「否」。\n"
            "只回复一个字。"
        )
        try:
            provider = self.context.get_using_provider()
            if not provider:
                return True
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是意图判断器，只回复「是」或「否」。",
                max_tokens=10,
                temperature=0,
            )
            result = (getattr(response, "completion_text", "") or "").strip()
            return result.startswith("是")
        except Exception as exc:
            logger.warning("Course intent AI review failed: %s", exc)
            return True

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

    _RECOMMEND_WORDS = (
        "推荐",
        "哪个老师好",
        "哪位老师好",
        "怎么选",
        "如何选",
        "选择",
        "选哪个",
        "推荐一个",
        "推荐一位",
        "避雷",
        "排序",
        "列举",
        "谁更好",
        "哪个好",
        "好不好",
    )

    @staticmethod
    def _looks_like_specific_lookup(text: str) -> bool:
        if not text:
            return False
        return not any(word in text for word in DududaCorePlugin._RECOMMEND_WORDS)

    async def _best_single_course(
        self,
        query: str,
        teacher_hint: str | None = None,
        max_items: int = 12,
    ) -> dict[str, Any] | None:
        result = await self._search_course_expanded(query)
        items = result.get("items") or []
        if not items:
            return None
        items = sorted(items, key=self._course_rank_key, reverse=True)
        if teacher_hint:
            hint = DududaCorePlugin._teacher_normalize(teacher_hint)
            for item in items:
                if hint and hint in DududaCorePlugin._teacher_normalize(
                    DududaCorePlugin._teacher_names(item)
                ):
                    return item
        return items[0]

    @staticmethod
    def _teacher_normalize(name: str) -> str:
        return (name or "").replace(" ", "").replace("老师", "").strip()

    async def _load_single_course_card(self, course_id: int) -> dict[str, Any] | None:
        try:
            course_result = await self.icourse.call(
                "get_course",
                {"course_id": course_id, "include_reviews": True, "refresh": True},
            )
            course = course_result.get("course")
            if not course:
                review_result = await self.icourse.call(
                    "get_reviews", {"course_id": course_id, "limit": 8, "sort_by": "upvote"}
                )
                course = {"id": course_id, "reviews": review_result.get("reviews") or []}
            return course
        except Exception as exc:
            logger.warning("Failed to load single icourse card %s: %s", course_id, exc)
            return None

    async def _answer_teacher_course_integrated(
        self,
        query: str,
        original_text: str,
    ) -> str | None:
        """@bot 查询课程/老师时，聚合评课社区评价 + 开课数据，用 LLM 按用户语义自由回答。

        返回 None 表示这不是课程查询（LLM 判定为陈述/闲聊），调用方应放行给普通聊天。
        """
        result = await self._search_course_expanded(query)
        items = result.get("items") or []
        if not items:
            # 清理后关键词仍可能带疑问残余，用更短的前缀再试
            for frag in (query[:4], query[:3], query[:2]):
                if len(frag) >= 2 and frag != query:
                    result = await self._search_course_expanded(frag)
                    items = result.get("items") or []
                    if items:
                        break
        if not items:
            return f"没在评课社区找到「{query}」，换个课程全名或老师名试试~"

        # 加载前几门课的详情和评论
        cards: list[dict[str, Any]] = []
        for item in sorted(items, key=self._course_rank_key, reverse=True)[:8]:
            cid = item.get("id")
            card = await self._load_single_course_card(cid) if cid else item
            if card is None:
                card = item
            cards.append(card)

        analysis = await self._analyze_course_cards(query, original_text, cards)
        if analysis is None:
            return None
        return analysis

    async def _analyze_course_cards(
        self,
        query: str,
        original_text: str,
        cards: list[dict[str, Any]],
    ) -> str | None:
        """把用户完整问句 + 评课数据 + 开课数据交给 LLM，按语义自由理解并回答。"""
        records: list[str] = []
        for idx, card in enumerate(cards, start=1):
            name = card.get("name") or "未知课程"
            teachers = self._teacher_names(card) or "教师未知"
            rating = card.get("rating_average")
            rating_txt = f"{rating:.1f}" if isinstance(rating, float) else str(rating or "暂无")
            diff = self._course_field(card, "difficulty")
            hw = self._course_field(card, "homework")
            grading = self._course_field(card, "grading")
            gain = self._course_field(card, "gain")
            term = card.get("term_text") or "学期未知"
            tags = "、".join([x for x in [diff, hw, grading, gain] if x]) or "无标签"
            reviews = card.get("reviews") or []
            review_lines = []
            for r in reviews[:6]:
                text = self._review_excerpt(r, limit=180)
                if not text or text == "无正文":
                    continue
                meta = []
                if r.get("rating_10"):
                    meta.append(f"{r['rating_10']}/10")
                if r.get("term"):
                    meta.append(str(r["term"]))
                review_lines.append(f"({' '.join(meta) or '评论'}) {text}")
            records.append(
                f"[{idx}] {name}｜{teachers}｜{term}｜评分{rating_txt}｜标签:{tags}\n"
                + ("\n".join(review_lines) if review_lines else "（暂无可见评论正文）")
            )

        # 开课数据并入数据块
        catalog_lines: list[str] = []
        for card in cards[:6]:
            name = card.get("name") or ""
            if not name:
                continue
            cam = await self._catalog_lookup(name)
            if cam:
                cap = cam.get("limit_count")
                std = cam.get("std_count")
                cap_txt = f"{std}/{cap}" if cap is not None else "容量未知"
                t = self._catalog_time_text(cam)
                loc = cam.get("campus_zh") or ""
                catalog_lines.append(f"{name}：{t}｜{loc}｜已选/容量 {cap_txt}")

        user_sentence = (original_text or query).strip()
        prompt = (
            "[CourseData]\n" + "\n\n".join(records) + "\n[/CourseData]\n"
        )
        if catalog_lines:
            prompt += "[OpenData]\n" + "\n".join(catalog_lines) + "\n[/OpenData]\n"
        prompt += (
            f"\n用户消息：{user_sentence}\n\n"
            "第一步，先判断：用户这句话是不是真的在向机器人查询课程/老师信息？\n"
            "如果用户只是陈述自己的情况（如\"我们班还没开课\"\"我今天有课\"）、闲聊、或与课程查询无关，"
            "请只回复特殊标记「NOT_COURSE_QUERY」，不要输出任何其他内容。\n"
            "如果确实是课程查询（问某门课、某位老师、选课、上课时间等），再继续下面的任务。\n\n"
            "第二步，像一个熟悉评课的学长/学姐一样，理解用户想问什么，再只根据上面两段数据回答。\n"
            "根据用户问法，你可能需要回答下面一种或几种内容（由你自己判断，不用每种都答）：\n"
            "- 选谁比较好：对比不同老师的评价，给出明确推荐和理由；\n"
            "- 怎么学/难不难：结合难度、给分、作业等，给学习方法和建议（如先修课、平时练习、注意事项）；\n"
            "- 什么时候上/在哪上/容量：客观给出上课时间地点和选课容量信息，不要臆测“有没有人抢”“还来不来得及”等；\n"
            "- 某位老师怎么样：综合这位老师各门课的评价，总结教学风格、给分、作业量和口碑；\n"
            "- 给分/作业/考试：针对用户关心的维度重点回答；\n"
            "- 课程总体情况：综合评价、适合人群等。\n\n"
            "重要注意：\n"
            "- [CourseData] 是评课社区的历史评价（可能跨多个学期、多个班型），[OpenData] 是当前学期的开课信息；\n"
            "  两者里的老师和班型可能对不上，这是正常的。回答时分别说明：评价上谁口碑好、这学期实际开课的有谁；\n"
            "  不要推断“其他老师这学期没开课”或“只有某一位老师能选”这种结论，除非开课数据确实只列了一位。\n"
            "- 老师名字要写全，不要省略或合并班型（A1/B3 等是不同班，别混为一谈）。\n"
            "要求：\n"
            "1. 只根据上面的公开数据回答，不要编造数据里没有的信息；数据不足就诚实说“公开评价还不多”；\n"
            "2. 用嘟嘟哒的口吻（可爱、轻松、聪明、认真，偶尔带点小俏皮），像给群友分享经验一样自然；\n"
            "3. 内容可以丰富一些，把该讲清楚的地方讲清楚，但不要啰嗦重复；\n"
            "4. 输出纯文字，可以分段，不要 Markdown 符号，不要堆叠 emoji。"
        )
        try:
            provider = self.context.get_using_provider()
            if not provider:
                return None
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是嘟嘟哒，一个可爱、聪明、认真又有点早熟的小小 USTC 预备役，帮群友分析评课和选课。",
                max_tokens=900,
                temperature=0.5,
            )
            text = (getattr(response, "completion_text", "") or "").strip()
            if not text:
                return None
            # 非课程查询：返回 None，由调用方放行给普通聊天
            if text.startswith("NOT_COURSE_QUERY"):
                return None
            return text
        except Exception as exc:
            logger.warning("Course analysis LLM failed: %s", exc)
            return None

    def _format_simple_integrated(self, query: str, cards: list[dict[str, Any]]) -> str:
        lines = [f"查了下「{query}」，这些是公开记录："]
        for idx, card in enumerate(cards[:5], start=1):
            name = card.get("name") or "未知课程"
            teachers = self._teacher_names(card) or "教师未知"
            rating = card.get("rating_average")
            rating_txt = f"{rating:.1f}" if isinstance(rating, float) else str(rating or "暂无")
            lines.append(f"{idx}. {name}｜{teachers}｜评分 {rating_txt}")
        lines.append("（评课数据较多，AI 总结暂时不可用，先给你列出来~）")
        return "\n".join(lines)

    @staticmethod
    def _course_field(card: dict[str, Any], key: str) -> str:
        value = card.get(key)
        if value is None or value in ("未知", None, ""):
            return ""
        text = str(value)
        return text if len(text) < 20 else ""

    async def _catalog_lookup(self, course_name: str) -> dict[str, Any] | None:
        try:
            result = await self.catalog.call("catalog_open", {"query": course_name, "limit": 6})
            results = result.get("results") or []
            return results[0] if results else None
        except Exception as exc:
            logger.warning("Catalog lookup failed for %s: %s", course_name, exc)
            return None

    @staticmethod
    def _catalog_time_text(item: dict[str, Any]) -> str:
        t = item.get("date_time_place_text") or ""
        return t.replace(";", "；") if t else "时间未公布"

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
        yield event.plain_result(
            "管理状态\n"
            f"default_provider_id: {cfg.get('provider_settings', {}).get('default_provider_id')}\n"
            f"owner_count: {len(self.perms.owners)}\n"
            f"global_admin_count: {len(self.perms.global_admins)}\n"
            f"pending_confirmations: {len(self.pending)}\n"
            f"audit_log: {self.audit.path}"
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
        if action == "test":
            tools = await self.icourse.list_tools()
            yield event.plain_result(f"MCP {name or 'icourse'} 可用工具：\n" + "\n".join(f"- {tool}" for tool in tools))
        else:
            yield event.plain_result("MCP 列表：\n- icourse：已接入")
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
