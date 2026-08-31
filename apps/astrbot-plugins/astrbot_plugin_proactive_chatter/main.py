from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .storage import ChatterStore

_NAME = "astrbot_plugin_proactive_chatter"


def _sender(event: AstrMessageEvent) -> str:
    try:
        return str(event.message_obj.sender.user_id)
    except Exception:
        return ""


def _group(event: AstrMessageEvent) -> str:
    try:
        return str(event.message_obj.group_id)
    except Exception:
        return ""


def _nick(event: AstrMessageEvent) -> str:
    try:
        sender = event.message_obj.sender
        return sender.card or sender.nickname or ""
    except Exception:
        return ""


def _text(event: AstrMessageEvent) -> str:
    try:
        return event.message_str or event.get_message_outline() or ""
    except Exception:
        return ""


@register(_NAME, "mmdustc", "择机闲聊：检测群热闹度，低频率主动发言", "0.1.0")
class ProactiveChatter(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", False))

        # data dir: /AstrBot/data/plugin_data/astrbot_plugin_proactive_chatter
        DATA_ROOT = Path(__file__).resolve().parents[2]
        data_dir = DATA_ROOT / "plugin_data" / _NAME
        data_dir.mkdir(parents=True, exist_ok=True)
        self.store = ChatterStore(data_dir / "chatter.sqlite3")

        self.window_seconds = float(self.config.get("window_seconds", 900))
        self.activity_threshold = int(self.config.get("activity_threshold", 1))
        self.trigger_probability = float(self.config.get("trigger_probability", 0.3))
        self.global_cooldown_seconds = float(self.config.get("global_cooldown_seconds", 1800))
        self.group_cooldown_seconds = float(self.config.get("group_cooldown_seconds", 1800))
        self.style_history_target = int(self.config.get("style_history_target", 250))
        self.require_style_n = int(self.config.get("require_style_n", 200))

        # 高活跃动态调整：2分钟内3-6条消息时，概率提高、间隔缩短
        self.high_activity_window = float(self.config.get("high_activity_window", 120))
        self.high_activity_min = int(self.config.get("high_activity_min", 3))
        self.high_activity_max = int(self.config.get("high_activity_max", 6))
        self.high_activity_probability = float(self.config.get("high_activity_probability", 0.6))
        self.high_activity_cooldown = float(self.config.get("high_activity_cooldown", 300))

        self.group_exclude = self._str_set(self.config.get("group_whitelist", []))
        self.global_last_sent = 0.0
        self.group_last_sent: dict[str, float] = {}
        self.last_style_compute: dict[str, tuple[str, float]] = {}
        self.pending_style: dict[str, str] = {}

        self.legend = (
            "嘟嘟哒是一个可爱、聪明、认真又有点早熟的小小 USTC 预备役，喜欢数学和计算机，"
            "说话亲切、轻松、偶尔用小玩笑，不刷屏、不机械，像个活泼小妹妹。"
        )

        logger.info("ProactiveChatter loaded: enabled=%s", self.enabled)

    @staticmethod
    def _str_set(value: Any) -> set[str]:
        if isinstance(value, str):
            return {value.strip()} if value.strip() else set()
        if isinstance(value, (list, tuple, set)):
            return {str(x).strip() for x in value if str(x).strip()}
        return set()

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AiocqhttpMessageEvent):
        if not self.enabled:
            return
        group = _group(event)
        sender = _sender(event)
        text = _text(event)

        # skip bot's own messages
        if not group or not sender or not text:
            return
        self.store.add(group, sender, _nick(event), text)

        if self.group_exclude and group not in self.group_exclude:
            return

        # check activity + cooldown
        if not self._should_speak(group):
            return
        asyncio.create_task(self._maybe_talk(event))

    def _is_high_activity(self, group: str) -> bool:
        """某群短时间内(默认2分钟)消息数在 min~max(3-6) 之间，视为高活跃。"""
        n = self.store.recent_activity_count(group, self.high_activity_window)
        return self.high_activity_min <= n <= self.high_activity_max

    def _should_speak(self, group: str) -> bool:
        now = time.time()
        high = self._is_high_activity(group)
        global_cd = self.high_activity_cooldown if high else self.global_cooldown_seconds
        group_cd = self.high_activity_cooldown if high else self.group_cooldown_seconds
        if now - self.global_last_sent < global_cd:
            return False
        if now - self.group_last_sent.get(group, 0.0) < group_cd:
            return False
        active = self.store.recent_activity_count(group, self.window_seconds)
        if active < self.activity_threshold:
            return False
        return True

    async def _maybe_talk(self, event: AiocqhttpMessageEvent) -> None:
        group = _group(event)
        high = self._is_high_activity(group)
        prob = self.high_activity_probability if high else self.trigger_probability
        if random.random() > prob:
            return
        recent = self.store.recent_by_group(group, self.window_seconds, limit=60)
        if not recent:
            return
        # 复读/+1/群接龙场景：不触发择机闲聊，交给复读插件
        if self._is_echo_flood(recent):
            return
        # 其他机器人互动（打卡/运势等命令）：不参与
        if self._is_bot_interaction(recent):
            return
        context_text = self._build_context(recent)

        # 检测当前是否在明显讨论课程（选课/难度/老师）
        course_blurb = await self._course_topic_context(context_text)
        content = await self._generate_speech(context_text, course_blurb)
        if not content:
            return
        chain = [Plain(content)]
        try:
            await event.send(event.chain_result(chain))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Proactive chatter send failed: %s", exc)
            return
        now = time.time()
        self.global_last_sent = now
        self.group_last_sent[group] = now

    def _is_echo_flood(self, recent: list[dict[str, Any]]) -> bool:
        """检测最近消息是否全是复读/+1/群接龙，是则返回 True（择机闲聊不触发）。"""
        import re as _re
        sample = [m.get("text") or "" for m in recent[-10:] if (m.get("text") or "").strip()]
        if len(sample) < 3:
            return False
        # 归一化：去掉空白
        norm = [_re.sub(r"\s+", "", t) for t in sample]
        # 统计最常出现的内容占比
        from collections import Counter
        counter = Counter(norm)
        top, top_n = counter.most_common(1)[0]
        # 复读：同一内容占比 >= 60%
        if top_n / len(norm) >= 0.6:
            return True
        # +1/接龙 类短内容占比 >= 60%
        echo_words = ("+1", "＋1", "1", "接龙", "同上", "同", "赞", "收到", "哦", "嗯", "好", "对", "是的")
        echo_n = sum(1 for t in norm if any(t == w for w in echo_words) or t in echo_words)
        if echo_n / len(norm) >= 0.6:
            return True
        return False

    def _is_bot_interaction(self, recent: list[dict[str, Any]]) -> bool:
        """检测最近消息是否像其他机器人的互动（命令/打卡/运势等），是则返回 True（不参与）。"""
        bot_signals = (
            "/打卡", "打卡", "签到", "/签到", "/运势", "运势", "抽签", "/抽签", "塔罗",
            "/塔罗", "今日运势", "/今日运势", "占卜", "/占卜", "骰子", "/骰子", "猜拳",
            "/猜拳", "点歌", "/点歌", "答题", "/答题", "解签", "/解签", "许愿", "/许愿",
            "/help", "/菜单", "菜单", "功能", "/功能",
        )
        sample = [m.get("text") or "" for m in recent[-8:] if (m.get("text") or "").strip()]
        if not sample:
            return False
        n_bot = sum(1 for t in sample if any(sig in t for sig in bot_signals))
        # 最近消息中命令式互动占比高，视为机器人互动场景
        return n_bot / len(sample) >= 0.5

    def _build_context(self, recent: list[dict[str, Any]]) -> str:
        lines = []
        for m in recent[:50][::-1]:
            nick = m.get("nick") or m.get("user_id") or "?"
            lines.append(f"{nick}: {m.get('text')}")
        return "\n".join(lines[-40:])

    _COURSE_SIGNALS = (
        "选课", "选什么课", "哪个老师", "哪位老师", "老师好", "老师怎么样", "推荐老师",
        "好难", "太难", "难度", "给分", "作业多", "作业少", "怎么学", "这门课", "这门",
        "课好过", "挂科", "卷", "绩点", "学分", "学分高", "谁教", "教得",
    )
    _COURSE_NAME_HINT = (
        "分析", "物理", "数学", "化学", "英语", "力学", "结构", "概论", "导论", "原理",
        "方法", "程序", "语言", "统计", "概率", "方程", "实验", "生物", "经济", "管理",
        "电路", "信号", "线代", "代数", "电磁", "光学", "复变", "常微分", "偏微分",
        "数据结构", "操作系统", "编译", "离散", "数值", "微积分", "高数",
    )

    def _detect_course_topic(self, context_text: str) -> str | None:
        """明显在讨论课程（选课/难度/老师）时，提取课程关键词；否则返回 None。"""
        if not any(w in context_text for w in self._COURSE_SIGNALS):
            return None
        import re as _re
        # 从最近几句里找含课程特征词的候选
        for line in reversed(context_text.split("\n")):
            if any(w in line for w in self._COURSE_SIGNALS):
                for hint in self._COURSE_NAME_HINT:
                    if hint in line:
                        m = _re.search(
                            rf"[\u4e00-\u9fffA-Za-z0-9]*{hint}[\u4e00-\u9fffA-Za-z0-9]*", line
                        )
                        if m:
                            word = m.group(0)
                            # 去掉尾部疑问/评价尾巴，只留课程名主体
                            word = _re.sub(
                                r"(好难啊|好难|太难了|太难|给分咋样|怎么样|咋样|如何|难不难|难吗|好不好|谁教得好|谁教|哪个老师|老师|怎么学|怎么考|挂科|卷不卷|课好|求推荐|推荐|选课|学不会|不懂)$",
                                "", word,
                            )
                            word = word.strip("的了吗是都")
                            if 2 <= len(word) <= 12:
                                return word
        return None

    async def _course_topic_context(self, context_text: str) -> str | None:
        """课程话题时，查评课+开课数据，返回给 LLM 的参考文本。"""
        keyword = self._detect_course_topic(context_text)
        if not keyword:
            return None
        try:
            data = await self._fetch_course_data(keyword)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chatter course data fetch failed for %s: %s", keyword, exc)
            return None
        if not data:
            return None
        return f"检测到大家在讨论课程「{keyword}」，以下是可参考的公开评课/开课数据：\n{data}"

    async def _fetch_course_data(self, keyword: str) -> str:
        """通过 MCP 查 icourse 评课 + catalog 开课，拼成简短的参考文本。"""
        import json as _json
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def call(mcp_args: list[str], tool: str, args: dict) -> dict:
            params = StdioServerParameters(
                command="/usr/local/bin/python", args=mcp_args, env=dict(__import__("os").environ)
            )
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    res = await s.call_tool(tool, args)
            return _json.loads("\n".join(getattr(i, "text", "") for i in res.content))

        icourse_args = [
            "/AstrBot/data/icourse-mcp/run_icourse_mcp.py",
            "--db-path", "/AstrBot/data/icourse-cache/icourse.sqlite3", "--request-delay", "0",
        ]
        catalog_args = [
            "/AstrBot/data/catalog-mcp/run_catalog_mcp.py",
            "--db-path", "/AstrBot/data/catalog-cache/catalog.sqlite3", "--request-delay", "0",
        ]

        lines: list[str] = []
        try:
            search = await call(icourse_args, "search_site_courses",
                                {"query": keyword, "pages": 1, "detail": False})
            items = (search.get("items") or [])[:5]
            if items:
                lines.append("评课社区（课程/老师口碑）：")
                for it in items:
                    teachers = "、".join(it.get("teachers") or []) or "教师未知"
                    rating = it.get("rating_average")
                    rating_txt = f"{rating:.1f}" if isinstance(rating, float) else str(rating or "暂无")
                    lines.append(f"- {it.get('name')}｜{teachers}｜评分{rating_txt}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chatter icourse fetch failed: %s", exc)

        try:
            catalog = await call(catalog_args, "catalog_open", {"query": keyword, "limit": 4})
            results = (catalog.get("results") or [])[:4]
            if results:
                lines.append("开课信息（时间/容量/老师）：")
                for it in results:
                    cap = it.get("limit_count")
                    std = it.get("std_count")
                    cap_txt = f"{std}/{cap}" if cap is not None else "容量未知"
                    t = (it.get("date_time_place_text") or "时间未公布").replace(";", "；")
                    lines.append(
                        f"- {it.get('name_zh')}｜{t}｜{it.get('campus_zh') or ''}｜{cap_txt}｜{it.get('teachers_zh') or ''}"
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chatter catalog fetch failed: %s", exc)

        return "\n".join(lines) if lines else ""

    async def _generate_speech(self, context_text: str, course_blurb: str | None = None) -> str | None:
        prompt = (
            "下面是某 QQ 群里最近的一小段聊天记录，你是群里一个叫嘟嘟哒的成员，想自然接一句话。\n"
            f"群消息：\n{context_text}\n"
            "请以嘟嘟哒的身份，自然、像真的人一样地接一句话参与当前讨论。要求：\n"
            "1. 严格贴合当前正在聊的话题（谁说的、在聊什么），不要跑题、不要面面俱到地总结；\n"
            f"2. 语气：{self.legend}\n"
            "3. 说得像随口插的一句话，有真实感（可以轻轻认同、补充一点、轻问一句、或幽默一下），"
            "像真人插话，不要官方、不要机械、不要报菜名式列举；\n"
        )
        if course_blurb:
            prompt += (
                f"{course_blurb}\n"
                "4. 大家正在讨论课程，你可以结合上面这些公开数据，自然地给点参考（比如哪个老师口碑好、"
                "难度给分怎么样、上课时间），但一定要自然融入对话、贴合语境，不要变成生硬的汇报；\n"
                "5. 可以稍微多说一两句，但不要长篇大论；只讲数据里有的，别编造；\n"
            )
        else:
            prompt += (
                "4. 很短（1-2 句，<=60 字），只在你说得合时宜时接；\n"
            )
        prompt += (
            "6. 如果你觉得现在插话会唐突（比如大家在说私事、只是在玩梗刷屏、或你没什么好说的），就直接回复空串。\n"
            "只输出要说的那句话本身，不要解释、引号、@ 或前缀。"
        )
        try:
            provider = self.context.get_using_provider()
            if not provider:
                return self._fallback()
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是嘟嘟哒，一个可爱、聪明、认真又有点早熟的小小 USTC 预备役，喜欢数学和计算机，说话亲切轻松，只在适合时短暂插话，不 @ 别人、不模仿别人。",
                max_tokens=300,
                temperature=0.9,
            )
            content = (getattr(response, "completion_text", "") or "").strip().strip('"“”')
            if not content or len(content) < 2:
                return None
            return content[:300]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Proactive chatter LLM failed: %s", exc)
            return self._fallback()

    def _fallback(self) -> str | None:
        replies = [
            "诶，就这个话题我也想说两句~",
            "哈哈感觉你们聊得挺热闹的w",
            "对呀对呀，我也有同感！",
            "这个我最近也在想呢～",
        ]
        return random.choice(replies)
