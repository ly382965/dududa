from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.message_components import At
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import asyncio
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any

@register("reminder", "Sarit", "个性化日程提醒插件", "1.0.0")
class ReminderPlugin(Star):
    PLUGIN_NAME = "astrbot_plugin_better_reminder"
    CN_NUMBERS = {
        "零": 0,
        "〇": 0,
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
    }
    WEEKDAYS = {
        "一": 0,
        "二": 1,
        "三": 2,
        "四": 3,
        "五": 4,
        "六": 5,
        "日": 6,
        "天": 6,
        "1": 0,
        "2": 1,
        "3": 2,
        "4": 3,
        "5": 4,
        "6": 5,
        "7": 6,
    }

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        # 存储定时任务的字典
        self.timers: Dict[str, asyncio.Task] = {}
        # 存储提醒信息的字典
        self.reminder_info: Dict[str, Dict[str, Any]] = {}
        data_root = Path(__file__).resolve().parents[2]
        self.data_dir = data_root / "plugin_data" / self.PLUGIN_NAME
        self.db_path = self.data_dir / "reminders.sqlite3"
        
        # 插件配置
        self.config = config or {}
        logger.info(f"日程提醒插件配置: {self.config}")

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        self.init_storage()
        await self.restore_pending_reminders()
        logger.info("日程提醒插件已初始化")

    @filter.command("提醒列表", alias={"日程列表", "查看提醒", "我的提醒"})
    async def list_reminders_command(self, event: AstrMessageEvent, scope: str | None = None):
        """列出当前会话未触发提醒。管理员可用：/提醒列表 全部"""
        show_all = (scope or "").strip() in {"全部", "全局", "all"}
        if show_all and not self.is_event_admin(event):
            yield event.plain_result("只有管理员可以查看全局提醒列表哦。")
            event.stop_event()
            return

        rows = self.list_pending_reminders(
            umo=None if show_all else event.unified_msg_origin,
        )
        if not rows:
            yield event.plain_result("当前没有待提醒的日程。")
            event.stop_event()
            return

        yield event.plain_result(self.format_reminder_list(rows, show_all=show_all))
        event.stop_event()

    @filter.command("取消提醒", alias={"删除提醒", "移除提醒"})
    async def cancel_reminder_command(self, event: AstrMessageEvent, target: str | None = None):
        """取消当前会话提醒。用法：/取消提醒 1 或 /取消提醒 全部"""
        target = (target or "").strip()
        if not target:
            yield event.plain_result("请指定要取消的提醒序号，例如：/取消提醒 1；或使用 /取消提醒 全部。")
            event.stop_event()
            return

        rows = self.list_pending_reminders(umo=event.unified_msg_origin)
        if not rows:
            yield event.plain_result("当前没有可取消的待提醒日程。")
            event.stop_event()
            return

        if target in {"全部", "全清", "all"}:
            count = 0
            for row in rows:
                if self.cancel_reminder(row["id"]):
                    count += 1
            yield event.plain_result(f"已取消当前会话的 {count} 个提醒。")
            event.stop_event()
            return

        reminder_id = ""
        if target.isdigit():
            index = int(target)
            if not (1 <= index <= len(rows)):
                yield event.plain_result(f"序号不对哦，当前只有 {len(rows)} 个待提醒日程。")
                event.stop_event()
                return
            reminder_id = rows[index - 1]["id"]
        else:
            matches = [row for row in rows if row["id"].startswith(target)]
            if len(matches) == 1:
                reminder_id = matches[0]["id"]
            elif len(matches) > 1:
                yield event.plain_result("这个 ID 前缀匹配到多个提醒，请用列表里的序号取消。")
                event.stop_event()
                return

        if not reminder_id or not self.cancel_reminder(reminder_id):
            yield event.plain_result("没有找到这个提醒。")
            event.stop_event()
            return

        yield event.plain_result("已取消这个提醒。")
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """监听所有消息事件，判断是否触发日程设定"""
        # 获取用户消息
        message_str = event.message_str
        management_response = self.handle_management_message(event, message_str)
        if management_response:
            yield event.plain_result(management_response)
            event.stop_event()
            return
        logger.info(f"收到用户消息: {message_str}")
        
        # 第一步：交由LLM判断是否触发日程制定动作
        is_schedule_trigger = await self.is_schedule_trigger(message_str, event)
        logger.info(f"是否触发日程设定: {is_schedule_trigger}")
        
        if not is_schedule_trigger:
            # 不是日程设定请求，不终止事件传播，让其他插件或LLM处理
            return
            
        # 第二步：提取关键信息
        schedule_info = await self.extract_schedule_info(message_str, event)
        logger.info(f"提取到的日程信息: {schedule_info}")
        
        if not schedule_info:
            # 缺少关键信息
            yield event.plain_result("缺少关键信息，请提供完整的时间和事件内容。")
            # 终止事件传播
            event.stop_event()
            return
            
        # 第三步：设置提醒计时器
        timer_set = await self.set_reminder_timer(event, schedule_info)
        
        if not timer_set:
            # 如果设置失败（例如达到最大提醒数量），发送错误消息
            max_reminders = self.config.get("max_reminders", 10)
            yield event.plain_result(f"设置提醒失败，已达到最大提醒数量 ({max_reminders})。请先清除一些提醒再试。")
            event.stop_event()
            return
        
        # 第四步：发送确认回复
        response = await self.generate_reminder_response(schedule_info, event)
        yield event.plain_result(response)
        
        # 终止事件传播
        event.stop_event()

    async def is_schedule_trigger(self, message: str, event: AstrMessageEvent) -> bool:
        """判断是否触发日程设定动作"""
        # 对于非常明显的日程设定请求，直接返回True
        trigger_keywords = ["提醒我", "设置提醒", "定时提醒", "日程提醒"]
        if any(keyword in message for keyword in trigger_keywords):
            logger.info(f"通过关键词匹配触发日程设定: {message}")
            return True
            
        # 检查是否配置了专用的日程检测LLM提供商
        schedule_detection_provider_id = self.config.get("schedule_detection_llm")
        provider = None
        
        if schedule_detection_provider_id:
            # 使用指定的专用提供商
            provider = self.context.get_provider_by_id(schedule_detection_provider_id)
            logger.info(f"使用日程检测专用提供商: {schedule_detection_provider_id}")
        else:
            # 使用主LLM提供商
            provider_id = self.config.get("llm_provider")
            if provider_id:
                provider = self.context.get_provider_by_id(provider_id)
            else:
                provider = self.context.get_using_provider(umo=event.unified_msg_origin)
            
        if not provider:
            logger.error("未找到可用的LLM提供商")
            return False
            
        # 构造提示词，让LLM判断是否是日程设定请求
        prompt = f"""
        请判断以下用户消息是否是日程设定请求：
        用户消息："{message}"
        
        如果是日程设定请求，请回复"是"，否则回复"否"。
        只需回复"是"或"否"，不要包含其他内容。
        """
        
        try:
            # 调用LLM进行判断
            response = await provider.text_chat(prompt=prompt)
            result = response.completion_text.strip().lower()
            is_trigger = result == "是" or result == "是的" or result == "yes" or result == "true"
            logger.info(f"LLM判断结果: {is_trigger}")
            return is_trigger
        except Exception as e:
            logger.error(f"调用LLM判断日程触发时出错: {e}")
            return False

    async def extract_schedule_info(self, message: str, event: AstrMessageEvent) -> dict:
        """提取日程关键信息"""
        # 获取配置中的LLM提供商或使用当前使用的LLM提供商
        provider_id = self.config.get("llm_provider")
        if provider_id:
            provider = self.context.get_provider_by_id(provider_id)
        else:
            provider = self.context.get_using_provider(umo=event.unified_msg_origin)
            
        if not provider:
            logger.error("未找到可用的LLM提供商")
            return {}
            
        # 构造提示词，让LLM提取关键信息并以JSON格式返回
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mentioned_users = self.extract_mentioned_users(event)
        mentioned_text = "无"
        if mentioned_users:
            mentioned_text = "\n".join(
                f"- QQ:{item['qq']} 昵称:{item['name'] or item['qq']}"
                for item in mentioned_users
            )
        prompt = f"""
        请从以下用户消息中提取日程关键信息，并以JSON格式返回：
        用户消息："{message}"
        当前时间：{now}
        消息里显式 @ 的候选对象：
        {mentioned_text}
        
        请提取以下信息：
        1. time：提醒时间（如：明天下午3点、12月20日上午10点等）
        2. event：提醒事件（如：开会、提交报告等）
        3. person：提醒对象（如：张三、团队成员、被 @ 的人等；如果用户没有明确说提醒谁，必须填"我"）

        规则：
        - “提醒我”“我到点做某事”表示提醒发起人本人，person 填"我"。
        - “提醒 @某人”“提醒张三”表示提醒该对象，person 填对象昵称、QQ号或被 @ 候选里的名字。
        - 不要把事件内容误判成提醒对象。
        
        请严格按照以下JSON格式返回，不要包含其他内容：
        {{
            "time": "提醒时间",
            "event": "提醒事件",
            "person": "提醒人物"
        }}
        """
        
        try:
            # 调用LLM提取信息
            response = await provider.text_chat(prompt=prompt)
            result_text = response.completion_text.strip()
            
            # 尝试解析JSON
            import json
            try:
                schedule_info = json.loads(result_text)
                # 验证关键字段是否存在
                if "time" in schedule_info and "event" in schedule_info:
                    return schedule_info
                else:
                    logger.warning(f"提取的信息缺少关键字段: {result_text}")
                    return {}
            except json.JSONDecodeError:
                logger.error(f"LLM返回的不是有效的JSON格式: {result_text}")
                return {}
        except Exception as e:
            logger.error(f"调用LLM提取日程信息时出错: {e}")
            return {}

    async def generate_reminder_response(self, schedule_info: dict, event: AstrMessageEvent) -> str:
        """根据人格和关键信息生成回复"""
        time = schedule_info.get("time", "某个时间")
        event_content = schedule_info.get("event", "某件事")
        person = schedule_info.get("person", "您")
        
        # 检查是否启用人格化回复
        enable_personality = self.config.get("enable_personality", True)
        
        if not enable_personality:
            # 不启用人格化回复，使用简单模板
            return f"好的，我会在{time}提醒{person}关于{event_content}的事情。"
        
        # 获取默认人格
        system_prompt = ""
        try:
            persona_manager = self.context.persona_manager
            # 修复：正确await异步方法
            default_persona = await persona_manager.get_default_persona_v3(umo=event.unified_msg_origin)
            system_prompt = default_persona["prompt"] if default_persona else ""
            logger.info(f"成功获取人格设定，提示: {system_prompt[:50]}..." if system_prompt else "使用默认空提示")
        except Exception as e:
            logger.warning(f"获取默认人格时出错，将使用默认提示: {e}")
            system_prompt = "你是一个贴心的助手"
        
        # 获取当前使用的LLM提供商
        provider = self.context.get_using_provider(umo=event.unified_msg_origin)
        if not provider:
            logger.error("未找到可用的LLM提供商")
            # 使用简单模板生成回复
            return f"好的，我会在{time}提醒{person}关于{event_content}的事情。"
        
        # 构造生成回复的提示词
        prompt = f"""
        基于以下信息生成一条个性化的日程提醒确认消息：
        
        提醒时间：{time}
        提醒事件：{event_content}
        提醒人物：{person}
        
        请根据以下角色设定生成回复：
        {system_prompt}
        
        请生成一条友好、自然的确认消息，确认已设置提醒。
        """
        
        try:
            # 调用LLM生成回复
            response = await provider.text_chat(prompt=prompt)
            return response.completion_text.strip()
        except Exception as e:
            logger.error(f"调用LLM生成回复时出错，使用默认回复: {e}")
            # 使用简单模板生成回复
            return f"好的，我会在{time}提醒{person}关于{event_content}的事情。"

    async def terminate(self):
        '''插件被卸载/停用时调用'''
        # 取消所有进行中的定时任务
        for timer_task in self.timers.values():
            if not timer_task.done():
                timer_task.cancel()
        self.timers.clear()
        self.reminder_info.clear()
        logger.info("日程提醒插件已取消内存计时任务，未触发日程仍保留在 SQLite 中")

    def parse_time_string(self, time_str: str) -> float:
        """解析时间字符串，返回距离现在的时间（秒）"""
        remind_at = self.parse_remind_datetime(time_str)
        return max(0.0, (remind_at - datetime.now()).total_seconds())

    def parse_remind_datetime(self, time_str: str) -> datetime:
        """解析中文时间描述，返回精确到分钟的本地时间。"""
        text = (time_str or "").strip()
        now = datetime.now()
        if not text:
            return self.parse_default_datetime(now)

        relative = self.parse_relative_datetime(text, now)
        if relative:
            return relative

        parsed_time = self.extract_clock_time(text)
        parsed_date, date_kind = self.extract_calendar_date(text, now)

        if parsed_time:
            hour, minute = parsed_time
            candidate = datetime.combine(parsed_date, datetime.min.time()).replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
            if candidate <= now:
                if date_kind == "weekday":
                    candidate += timedelta(days=7)
                elif date_kind == "none":
                    candidate += timedelta(days=1)
            return candidate

        if date_kind != "none":
            default_dt = self.parse_default_datetime(now)
            return datetime.combine(parsed_date, datetime.min.time()).replace(
                hour=default_dt.hour,
                minute=default_dt.minute,
                second=0,
                microsecond=0,
            )

        return self.parse_default_datetime(now)

    def parse_relative_datetime(self, text: str, now: datetime) -> datetime | None:
        if "一会儿" in text or "稍后" in text or "待会" in text:
            return now + timedelta(minutes=1)
        if "半小时" in text:
            return now + timedelta(minutes=30)

        match = re.search(
            r"(?P<num>\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百]+)\s*"
            r"(?:个)?(?P<unit>分钟|分|小时|钟头|天|日)\s*(?P<suffix>后|之后|以后)?",
            text,
        )
        if not match:
            return None

        value = self.parse_number(match.group("num"))
        if value is None:
            return None

        unit = match.group("unit")
        if unit in {"分钟", "分"}:
            return now + timedelta(minutes=value)
        if unit in {"小时", "钟头"}:
            return now + timedelta(hours=value)
        if unit in {"天", "日"}:
            if not match.group("suffix"):
                return None
            return now + timedelta(days=value)
        return None

    def extract_clock_time(self, text: str) -> tuple[int, int] | None:
        pattern = re.compile(
            r"(?P<period>凌晨|清晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里|今晚|今早|明早|明晚)?\s*"
            r"(?P<hour>\d{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*"
            r"(?P<sep>点|时|:|：)\s*"
            r"(?:(?P<minute>\d{1,2}|[零〇一二两三四五六七八九十]{1,3})\s*分?)?\s*"
            r"(?P<quarter>半|一刻|三刻)?"
        )
        match = pattern.search(text)
        if not match:
            return None

        hour_value = self.parse_number(match.group("hour"))
        if hour_value is None:
            return None
        hour = int(hour_value)
        minute = 0

        minute_text = match.group("minute")
        if minute_text:
            minute_value = self.parse_number(minute_text)
            if minute_value is None:
                return None
            minute = int(minute_value)

        quarter = match.group("quarter")
        if quarter == "半":
            minute = 30
        elif quarter == "一刻":
            minute = 15
        elif quarter == "三刻":
            minute = 45

        period = match.group("period") or ""
        hour = self.apply_period(hour, period)

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour, minute

    def extract_calendar_date(self, text: str, now: datetime) -> tuple[Any, str]:
        if "大后天" in text:
            return (now + timedelta(days=3)).date(), "relative_date"
        if "后天" in text:
            return (now + timedelta(days=2)).date(), "relative_date"
        if any(word in text for word in ("明天", "明早", "明晚", "tomorrow")):
            return (now + timedelta(days=1)).date(), "relative_date"
        if any(word in text for word in ("今天", "今晚", "今早")):
            return now.date(), "relative_date"

        weekday = re.search(r"(?:周|星期|礼拜)([一二三四五六日天1-7])", text)
        if weekday:
            target = self.WEEKDAYS.get(weekday.group(1))
            if target is not None:
                days = (target - now.weekday()) % 7
                return (now + timedelta(days=days)).date(), "weekday"

        md = re.search(
            r"(?:(?P<year>\d{4})\s*年)?\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*[日号]?",
            text,
        )
        if not md:
            md = re.search(
                r"(?P<month>\d{1,2})\s*[-/]\s*(?P<day>\d{1,2})",
                text,
            )
        if md:
            year = int(md.groupdict().get("year") or now.year)
            month = int(md.group("month"))
            day = int(md.group("day"))
            try:
                parsed = datetime(year, month, day).date()
                if "year" not in md.groupdict() or not md.groupdict().get("year"):
                    if parsed < now.date():
                        parsed = datetime(year + 1, month, day).date()
                return parsed, "absolute_date"
            except ValueError:
                logger.warning(f"无法解析日期: {text}")

        return now.date(), "none"

    def parse_default_datetime(self, now: datetime) -> datetime:
        default_time = self.config.get("default_reminder_time", "10分钟")
        relative = self.parse_relative_datetime(str(default_time), now)
        if relative:
            return relative
        return now + timedelta(minutes=10)

    def parse_number(self, raw: str) -> float | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            pass

        if raw in self.CN_NUMBERS:
            return float(self.CN_NUMBERS[raw])
        if raw == "十":
            return 10.0
        if "十" in raw:
            left, _, right = raw.partition("十")
            tens = self.CN_NUMBERS.get(left, 1) if left else 1
            ones = self.CN_NUMBERS.get(right, 0) if right else 0
            return float(tens * 10 + ones)
        return None

    def apply_period(self, hour: int, period: str) -> int:
        if period in {"下午", "傍晚", "晚上", "夜里", "今晚", "明晚"} and hour < 12:
            return hour + 12
        if period == "中午" and 1 <= hour <= 10:
            return hour + 12
        if period in {"凌晨", "清晨"} and hour == 12:
            return 0
        return hour

    def init_storage(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY,
                    event TEXT NOT NULL,
                    person TEXT NOT NULL,
                    time_desc TEXT NOT NULL,
                    unified_msg_origin TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    remind_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_status_time ON reminders(status, remind_at)"
            )
            existing_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()
            }
            migrations = {
                "requester_id": "ALTER TABLE reminders ADD COLUMN requester_id TEXT DEFAULT ''",
                "requester_name": "ALTER TABLE reminders ADD COLUMN requester_name TEXT DEFAULT ''",
                "target_user_id": "ALTER TABLE reminders ADD COLUMN target_user_id TEXT DEFAULT ''",
                "target_user_name": "ALTER TABLE reminders ADD COLUMN target_user_name TEXT DEFAULT ''",
            }
            for column, sql in migrations.items():
                if column not in existing_columns:
                    conn.execute(sql)

    async def restore_pending_reminders(self):
        rows = self.load_pending_reminders()
        now = time.time()
        for row in rows:
            reminder_id = row["id"]
            self.reminder_info[reminder_id] = row
            delay_seconds = max(3.0, row["remind_at"] - now)
            self.timers[reminder_id] = asyncio.create_task(
                self.reminder_timer(delay_seconds, reminder_id)
            )
        if rows:
            logger.info(f"已从 SQLite 恢复 {len(rows)} 个未触发提醒")

    def load_pending_reminders(self) -> list[dict]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM reminders WHERE status = 'pending' ORDER BY remind_at ASC"
            ).fetchall()
        return [self.normalize_reminder_row(dict(row)) for row in rows]

    def list_pending_reminders(self, umo: str | None = None) -> list[dict]:
        query = "SELECT * FROM reminders WHERE status = 'pending'"
        params: list[Any] = []
        if umo:
            query += " AND unified_msg_origin = ?"
            params.append(umo)
        query += " ORDER BY remind_at ASC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [self.normalize_reminder_row(dict(row)) for row in rows]

    def normalize_reminder_row(self, row: dict) -> dict:
        if "time" not in row:
            row["time"] = row.get("time_desc", "")
        row.setdefault("requester_id", "")
        row.setdefault("requester_name", "")
        row.setdefault("target_user_id", "")
        row.setdefault("target_user_name", "")
        return row

    def format_reminder_list(self, rows: list[dict], *, show_all: bool = False) -> str:
        lines = ["待提醒列表："]
        for index, row in enumerate(rows, start=1):
            remind_at = datetime.fromtimestamp(float(row["remind_at"])).strftime(
                "%m-%d %H:%M"
            )
            event_content = str(row.get("event", "某件事")).strip()
            person = str(
                row.get("target_user_name") or row.get("person", "我")
            ).strip()
            time_desc = str(row.get("time", row.get("time_desc", ""))).strip()
            short_id = str(row.get("id", ""))[:8]
            line = f"{index}. {remind_at}｜{event_content}"
            if person:
                line += f"｜提醒：{person}"
            if time_desc:
                line += f"｜原文时间：{time_desc}"
            if show_all:
                line += f"｜会话：{row.get('unified_msg_origin', '')}"
            line += f"｜ID:{short_id}"
            lines.append(line)
        lines.append("取消提醒：/取消提醒 序号")
        return "\n".join(lines)

    def save_reminder(self, reminder_id: str, reminder_data: dict):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reminders (
                    id, event, person, time_desc, unified_msg_origin, created_at, remind_at,
                    requester_id, requester_name, target_user_id, target_user_name, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    reminder_id,
                    reminder_data["event"],
                    reminder_data["person"],
                    reminder_data["time"],
                    reminder_data["unified_msg_origin"],
                    reminder_data["created_at"],
                    reminder_data["remind_at"],
                    reminder_data.get("requester_id", ""),
                    reminder_data.get("requester_name", ""),
                    reminder_data.get("target_user_id", ""),
                    reminder_data.get("target_user_name", ""),
                ),
            )

    def delete_reminder(self, reminder_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

    def cancel_reminder(self, reminder_id: str) -> bool:
        exists = reminder_id in self.reminder_info
        self.reminder_info.pop(reminder_id, None)

        task = self.timers.pop(reminder_id, None)
        if task and not task.done():
            task.cancel()
            exists = True

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            if cursor.rowcount:
                exists = True
        return exists

    def is_event_admin(self, event: AstrMessageEvent) -> bool:
        try:
            return bool(event.is_admin())
        except Exception:
            return False

    def is_management_message(self, message: str) -> bool:
        text = self.clean_management_text(message)
        return text.startswith(("提醒列表", "日程列表", "查看提醒", "我的提醒", "取消提醒", "删除提醒", "移除提醒"))

    def clean_management_text(self, message: str) -> str:
        text = (message or "").strip()
        text = re.sub(r"^\[At:[^\]]+\]\s*", "", text).strip()
        text = text.lstrip("/!！#＃").strip()
        return text

    def handle_management_message(self, event: AstrMessageEvent, message: str) -> str:
        text = self.clean_management_text(message)
        if not self.is_management_message(text):
            return ""

        parts = text.split(maxsplit=1)
        command = parts[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command in {"提醒列表", "日程列表", "查看提醒", "我的提醒"}:
            show_all = arg in {"全部", "全局", "all"}
            if show_all and not self.is_event_admin(event):
                return "只有管理员可以查看全局提醒列表哦。"
            rows = self.list_pending_reminders(
                umo=None if show_all else event.unified_msg_origin,
            )
            if not rows:
                return "当前没有待提醒的日程。"
            return self.format_reminder_list(rows, show_all=show_all)

        if command in {"取消提醒", "删除提醒", "移除提醒"}:
            return self.cancel_reminder_by_text(event, arg)

        return ""

    def cancel_reminder_by_text(self, event: AstrMessageEvent, target: str) -> str:
        target = (target or "").strip()
        if not target:
            return "请指定要取消的提醒序号，例如：/取消提醒 1；或使用 /取消提醒 全部。"

        rows = self.list_pending_reminders(umo=event.unified_msg_origin)
        if not rows:
            return "当前没有可取消的待提醒日程。"

        if target in {"全部", "全清", "all"}:
            count = 0
            for row in rows:
                if self.cancel_reminder(row["id"]):
                    count += 1
            return f"已取消当前会话的 {count} 个提醒。"

        reminder_id = ""
        if target.isdigit():
            index = int(target)
            if not (1 <= index <= len(rows)):
                return f"序号不对哦，当前只有 {len(rows)} 个待提醒日程。"
            reminder_id = rows[index - 1]["id"]
        else:
            matches = [row for row in rows if row["id"].startswith(target)]
            if len(matches) == 1:
                reminder_id = matches[0]["id"]
            elif len(matches) > 1:
                return "这个 ID 前缀匹配到多个提醒，请用列表里的序号取消。"

        if not reminder_id or not self.cancel_reminder(reminder_id):
            return "没有找到这个提醒。"
        return "已取消这个提醒。"

    def get_sender_identity(self, event: AstrMessageEvent) -> dict:
        sender_id = ""
        sender_name = ""
        try:
            sender_id = str(event.get_sender_id() or "")
        except Exception:
            pass
        try:
            sender_name = str(event.get_sender_name() or "").strip()
        except Exception:
            pass
        return {
            "id": sender_id,
            "name": sender_name or sender_id or "我",
        }

    def extract_mentioned_users(self, event: AstrMessageEvent) -> list[dict]:
        self_id = ""
        try:
            self_id = str(event.get_self_id() or "")
        except Exception:
            pass

        users: list[dict] = []
        seen: set[str] = set()
        try:
            messages = event.get_messages()
        except Exception:
            messages = []

        for seg in messages:
            if not isinstance(seg, At):
                continue
            qq = str(getattr(seg, "qq", "") or "").strip()
            if not qq.isdigit() or qq == self_id or qq in seen:
                continue
            seen.add(qq)
            users.append(
                {
                    "qq": qq,
                    "name": str(getattr(seg, "name", "") or "").strip(),
                }
            )
        return users

    async def resolve_reminder_target(
        self, event: AstrMessageEvent, schedule_info: dict
    ) -> dict:
        requester = self.get_sender_identity(event)
        person_text = str(schedule_info.get("person", "") or "").strip()
        mentioned_users = self.extract_mentioned_users(event)

        if self.is_self_reference(person_text):
            return {
                "id": requester["id"],
                "name": requester["name"],
                "source": "requester",
            }

        if mentioned_users:
            matched = self.match_mentioned_user(person_text, mentioned_users)
            target = matched or mentioned_users[0]
            return {
                "id": target["qq"],
                "name": target["name"] or target["qq"],
                "source": "mention",
            }

        if person_text.isdigit():
            return {
                "id": person_text,
                "name": person_text,
                "source": "qq",
            }

        member = await self.find_group_member_by_name(event, person_text)
        if member:
            return {
                "id": member["qq"],
                "name": member["name"] or member["qq"],
                "source": "group_member",
            }

        return {
            "id": requester["id"],
            "name": requester["name"],
            "source": "fallback_requester",
        }

    def is_self_reference(self, text: str) -> bool:
        normalized = self.normalize_name(text)
        return normalized in {
            "",
            "我",
            "自己",
            "我自己",
            "本人",
            "发起人",
            "发送者",
            "用户",
            "您",
        }

    def match_mentioned_user(self, person_text: str, users: list[dict]) -> dict | None:
        target = self.normalize_name(person_text)
        if not target:
            return None
        for user in users:
            candidates = [user.get("qq", ""), user.get("name", "")]
            for candidate in candidates:
                normalized = self.normalize_name(candidate)
                if normalized and normalized == target:
                    return user
        for user in users:
            name = self.normalize_name(user.get("name", ""))
            if name and (target in name or name in target):
                return user
        return None

    async def find_group_member_by_name(
        self, event: AstrMessageEvent, person_text: str
    ) -> dict | None:
        target = self.normalize_name(person_text)
        if not target or self.is_self_reference(person_text):
            return None

        try:
            group_id = event.get_group_id()
        except Exception:
            group_id = None
        if not group_id:
            return None

        try:
            members = await event.bot.get_group_member_list(group_id=int(group_id))
        except Exception as exc:
            logger.warning(f"获取群成员列表失败，无法按昵称匹配提醒对象: {exc}")
            return None

        exact_match = None
        fuzzy_match = None
        for member in members or []:
            qq = str(member.get("user_id", "") or "")
            names = [
                str(member.get("card", "") or ""),
                str(member.get("nickname", "") or ""),
                str(member.get("remark", "") or ""),
                qq,
            ]
            cleaned_names = [self.normalize_name(name) for name in names if name]
            if target in cleaned_names:
                exact_match = {
                    "qq": qq,
                    "name": names[0] or names[1] or qq,
                }
                break
            if not fuzzy_match and any(
                name and (target in name or name in target) for name in cleaned_names
            ):
                fuzzy_match = {
                    "qq": qq,
                    "name": names[0] or names[1] or qq,
                }

        return exact_match or fuzzy_match

    def normalize_name(self, value: str) -> str:
        return re.sub(r"[\s@＠:：,，。.!！?？]+", "", str(value or "")).lower()

    async def set_reminder_timer(self, event: AstrMessageEvent, schedule_info: dict):
        """设置提醒计时器"""
        # 检查是否超过最大提醒数量
        max_reminders = self.config.get("max_reminders", 10)
        if len(self.reminder_info) >= max_reminders:
            logger.warning(f"已达到最大提醒数量 {max_reminders}，无法设置新的提醒")
            return False
        
        # 生成唯一的提醒ID
        reminder_id = uuid.uuid4().hex
        
        # 解析时间字符串为精确提醒时间
        remind_at_dt = self.parse_remind_datetime(schedule_info.get("time", "10分钟"))
        remind_at = remind_at_dt.timestamp()
        delay_seconds = max(0.0, remind_at - time.time())
        requester = self.get_sender_identity(event)
        target = await self.resolve_reminder_target(event, schedule_info)
        schedule_info["person"] = target["name"]
        
        # 存储提醒信息
        self.reminder_info[reminder_id] = {
            "event": schedule_info.get("event", "某件事"),
            "person": target["name"],
            "time": schedule_info.get("time", "某个时间"),
            "unified_msg_origin": event.unified_msg_origin,
            "created_at": time.time(),
            "remind_at": remind_at,
            "requester_id": requester["id"],
            "requester_name": requester["name"],
            "target_user_id": target["id"],
            "target_user_name": target["name"],
        }
        self.save_reminder(reminder_id, self.reminder_info[reminder_id])
        
        # 创建计时任务
        timer_task = asyncio.create_task(self.reminder_timer(delay_seconds, reminder_id))
        self.timers[reminder_id] = timer_task
        
        logger.info(
            f"已设置提醒任务 {reminder_id}，将在 {remind_at_dt.strftime('%Y-%m-%d %H:%M:%S')} 触发，提醒对象={target['name']}({target['id']}) source={target['source']}"
        )
        return True
        
    async def reminder_timer(self, delay_seconds: float, reminder_id: str):
        """计时器任务"""
        try:
            # 等待指定的时间
            await asyncio.sleep(delay_seconds)
            
            # 时间到了，触发提醒
            if reminder_id in self.reminder_info:
                reminder_data = self.reminder_info[reminder_id]
                await self.send_reminder_message(reminder_data, reminder_id)
                
                # 清理已触发的提醒
                del self.reminder_info[reminder_id]
                self.delete_reminder(reminder_id)
                if reminder_id in self.timers:
                    del self.timers[reminder_id]
        except asyncio.CancelledError:
            # 任务被取消
            logger.info(f"提醒任务 {reminder_id} 已被取消")
            # 仅清理内存状态，不删除 SQLite。重启/重载后仍会恢复未触发提醒。
            if reminder_id in self.reminder_info:
                del self.reminder_info[reminder_id]
            if reminder_id in self.timers:
                del self.timers[reminder_id]
        except Exception as e:
            logger.error(f"提醒任务 {reminder_id} 执行出错: {e}")
            # 清理，避免失败任务反复触发
            if reminder_id in self.reminder_info:
                del self.reminder_info[reminder_id]
            self.delete_reminder(reminder_id)
            if reminder_id in self.timers:
                del self.timers[reminder_id]
                
    async def send_reminder_message(self, reminder_data: dict, reminder_id: str):
        """发送提醒消息"""
        try:
            # 获取目标会话信息
            umo = reminder_data["unified_msg_origin"]
            event_content = reminder_data["event"]
            person = reminder_data["person"]
            time_desc = reminder_data["time"]
            target_user_id = str(reminder_data.get("target_user_id", "") or "").strip()
            target_user_name = str(
                reminder_data.get("target_user_name", "") or person or target_user_id
            ).strip()
            
            # 检查是否启用人格化回复
            enable_personality = self.config.get("enable_personality", True)
            
            # 获取人设信息
            system_prompt = ""
            if enable_personality:
                try:
                    persona_manager = self.context.persona_manager
                    # 获取默认人格
                    default_persona = await persona_manager.get_default_persona_v3(umo=umo)
                    system_prompt = default_persona["prompt"] if default_persona else ""
                    logger.info(f"成功获取人格设定，提示: {system_prompt[:50]}..." if system_prompt else "使用默认空提示")
                except Exception as e:
                    logger.warning(f"获取默认人格时出错，将使用默认提示: {e}")
                    system_prompt = "你是一个贴心的助手"
            else:
                # 不使用人格化回复
                system_prompt = ""
            
            # 构造生成提醒消息的提示词
            if enable_personality:
                prompt = f"""
                你现在需要提醒用户关于之前设置的事情。
                
                提醒内容：
                - 事件：{event_content}
                - 时间：{time_desc}
                - 人物：{person}
                
                请根据以下角色设定生成一条友好、自然的提醒消息：
                {system_prompt}
                
                请以自然、友好的方式提醒用户，不要过于生硬。
                """
            else:
                # 不使用人格化提示词
                prompt = ""
            
            # 获取当前使用的LLM提供商
            provider = self.context.get_using_provider(umo=umo)
            if not provider or not enable_personality or not prompt:
                logger.info("未找到可用的LLM提供商或未启用人格化回复，使用简单模板生成回复")
                # 使用简单模板生成回复
                message = f"提醒：{person}，您之前设置的提醒时间到了！关于{event_content}的事情，请记得处理哦～"
            else:
                try:
                    # 调用LLM生成提醒消息
                    response = await provider.text_chat(prompt=prompt)
                    message = response.completion_text.strip()
                except Exception as e:
                    logger.error(f"调用LLM生成提醒消息时出错，使用默认回复: {e}")
                    # 使用简单模板生成回复
                    message = f"提醒：{person}，您之前设置的提醒时间到了！关于{event_content}的事情，请记得处理哦～"
            
            # 发送消息
            message_chain = MessageChain()
            if target_user_id.isdigit():
                message_chain.at(target_user_name or target_user_id, target_user_id)
                message_chain.message(" ")
            message_chain.message(message)
            await self.context.send_message(umo, message_chain)
            logger.info(f"已发送提醒消息: {message}")
        except Exception as e:
            logger.error(f"发送提醒消息时出错: {e}")
