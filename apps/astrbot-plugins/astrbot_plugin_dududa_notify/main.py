from __future__ import annotations

import asyncio
import base64
import json
import re
from contextlib import suppress
from pathlib import Path

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .course_catalog import DEFAULT_COURSES, validate_courses
from .course_tasks import CourseService
from .homework import HomeworkService, timestamp
from .notifications import (
    DeliveryStore,
    QueryError,
    assignment_request,
    deliver,
    fetch_snapshot,
    query_error_reason,
    seminar_notifications,
)
from .weekly import WeeklyService
from .weekly import current_time as weekly_time

PLUGIN_NAME = "astrbot_plugin_dududa_notify"


@register(PLUGIN_NAME, "mmdustc", "全课程任务通知、课件日报与周汇报助手", "0.5.3")
class DududaNotifyPlugin(Star):
    def __init__(self, context: Context, config: dict) -> None:
        super().__init__(context)
        self.config = config
        self.task: asyncio.Task | None = None
        self.store: DeliveryStore | None = None
        self.homework: HomeworkService | None = None
        self.homework_task: asyncio.Task | None = None
        self.deadline_task: asyncio.Task | None = None
        self.courses: CourseService | None = None
        self.course_task: asyncio.Task | None = None
        self.course_report_task: asyncio.Task | None = None
        self.weekly: WeeklyService | None = None
        self.weekly_task: asyncio.Task | None = None
        self.poll_health = {}

    async def initialize(self) -> None:
        if not self.config.get("enabled", False):
            return
        self.platform_id = str(self.config.get("platform_id", "")).strip()
        recipients = self.config.get("recipients", [])
        if not isinstance(recipients, list):
            raise TypeError("notification_recipients_must_be_a_list")
        self.recipients = tuple(
            dict.fromkeys(str(value).strip() for value in recipients)
        )
        if (
            not self.platform_id
            or not self.recipients
            or any(
                not value.isascii() or not value.isdigit() or int(value) <= 0
                for value in self.recipients
            )
        ):
            raise ValueError("notification_platform_and_private_recipients_required")
        self.interval = int(self.config.get("interval_minutes", 3))
        self.limit = int(self.config.get("max_messages_per_poll", 5))
        self.timeout = float(self.config.get("request_timeout_seconds", 45))
        if (
            not 1 <= self.interval <= 1440
            or not 1 <= self.limit <= 20
            or not 0 < self.timeout <= 300
        ):
            raise ValueError("invalid_notification_poll_settings")
        data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        configured_python = str(self.config.get("worker_python", "")).strip()
        self.worker_python = (
            Path(configured_python)
            if configured_python
            else data_dir / "worker-venv/bin/python"
        )
        if not self.worker_python.is_file():
            raise ValueError("notification_worker_not_installed: run install_worker.sh")
        if self.config.get("homework_enabled", False):
            owner = str(self.config.get("homework_recipient", "")).strip()
            if owner not in self.recipients:
                raise ValueError("homework_owner_must_be_an_authorized_recipient")
            self.homework_interval = int(
                self.config.get("homework_interval_minutes", 3)
            )
            deadline_minutes = int(self.config.get("homework_auto_submit_minutes", 3))
            if (
                not 1 <= self.homework_interval <= 1440
                or not 1 <= deadline_minutes <= 60
            ):
                raise ValueError("invalid_homework_interval")
            self.homework = HomeworkService(
                data_dir,
                owner,
                self._homework_query,
                self._homework_generate,
                lambda text: self._send_private(owner, text),
                lambda path: self._send_private_file(owner, path),
                render_pdf=self._homework_pdf,
                auto_submit=self.config.get("homework_auto_submit_enabled", False),
                deadline_minutes=deadline_minutes,
            )
            self.homework_task = asyncio.create_task(
                self._poll_homework(), name="dududa-homework-notifications"
            )
            if self.homework.auto_submit:
                self.deadline_task = asyncio.create_task(
                    self._watch_homework_deadlines(), name="dududa-homework-deadlines"
                )
            self.logger.info(
                "Homework notifications enabled, interval=%s minutes, auto_submit=%s, deadline_window=%s minutes, format=pdf",
                self.homework_interval,
                self.homework.auto_submit,
                deadline_minutes,
            )
        if self.config.get("courses_enabled", False):
            owner = str(self.config.get("homework_recipient", "")).strip()
            if owner not in self.recipients:
                raise ValueError("course_owner_must_be_an_authorized_recipient")
            sources = validate_courses(
                self.config.get("course_sources") or DEFAULT_COURSES
            )
            self.course_interval = int(self.config.get("courses_interval_minutes", 3))
            summary_hour = int(self.config.get("courses_summary_hour", 20))
            if not 1 <= self.course_interval <= 1440 or not 0 <= summary_hour <= 23:
                raise ValueError("invalid_course_schedule")
            self.courses = CourseService(
                data_dir,
                owner,
                sources,
                self._course_query,
                self._homework_generate,
                self._course_image,
                lambda text: self._send_private(owner, text),
                lambda path: self._send_private_image(owner, path),
                summary_hour=summary_hour,
            )
            self.course_task = asyncio.create_task(
                self._poll_courses(), name="dududa-course-notifications"
            )
            self.course_report_task = asyncio.create_task(
                self._poll_course_reports(), name="dududa-course-reports"
            )
            self.logger.info(
                "Course notifications enabled, interval=%s minutes, summary_hour=%s, courses=%s, format=list+png",
                self.course_interval,
                summary_hour,
                len(sources),
            )
        if self.config.get("weekly_enabled", False):
            owner = str(self.config.get("homework_recipient", "")).strip()
            if owner not in self.recipients:
                raise ValueError("weekly_owner_must_be_an_authorized_recipient")
            if not 1 <= int(self.config.get("weekly_interval_minutes", 3)) <= 1440:
                raise ValueError("invalid_weekly_interval")
            self.weekly = WeeklyService(
                data_dir,
                owner,
                self._homework_query,
                lambda text: self._send_private(owner, text),
                hour=int(self.config.get("weekly_submit_hour", 20)),
                policy=self.config.get("weekly_report_day", "first"),
            )
            self.weekly_task = asyncio.create_task(
                self._poll_weekly(), name="dududa-weekly-reports"
            )
            self.logger.info(
                "Weekly reports enabled, day=%s, hour=%s, timezone=Asia/Shanghai, empty_only=True, interval=%s minutes",
                self.weekly.policy,
                self.weekly.hour,
                self.config.get("weekly_interval_minutes", 3),
            )
        if self.config.get("seminar_enabled", True):
            self.store = DeliveryStore(data_dir / "deliveries.sqlite3")
            self.task = asyncio.create_task(
                self._poll(), name="dududa-seminar-notifications"
            )
            self.logger.info(
                "SeminarRadar private notifications enabled, interval=%s minutes",
                self.interval,
            )

    async def _send_private(self, recipient: str, text: str) -> str:
        platform = self._private_platform(recipient)
        result = await asyncio.wait_for(
            platform.get_client().call_action(
                "send_private_msg",
                user_id=int(recipient),
                message=[{"type": "text", "data": {"text": text}}],
            ),
            timeout=30,
        )
        if not isinstance(result, dict) or not result.get("message_id"):
            raise RuntimeError("private_message_not_acknowledged")
        return str(result["message_id"])

    def _private_platform(self, recipient: str):
        if recipient not in self.recipients:
            raise ValueError("notification_recipient_not_authorized")
        platform = next(
            (
                value
                for value in self.context.platform_manager.get_insts()
                if value.meta().id == self.platform_id
                and value.meta().name == "aiocqhttp"
            ),
            None,
        )
        if platform is None:
            raise RuntimeError("notification_qq_platform_unavailable")
        return platform

    async def _send_private_file(self, recipient: str, path: Path):
        platform = self._private_platform(recipient)
        try:
            await asyncio.wait_for(
                platform.get_client().call_action(
                    "upload_private_file",
                    user_id=int(recipient),
                    file="base64://"
                    + base64.b64encode(path.read_bytes()).decode("ascii"),
                    name=path.name,
                ),
                timeout=120,
            )
        except Exception as exc:
            self.logger.warning(
                "Homework private file delivery failed (%s, retcode=%s)",
                type(exc).__name__,
                getattr(exc, "retcode", None),
            )
            raise

    async def _homework_query(self, request):
        return await assignment_request(
            self.worker_python,
            {
                **request,
                "credentials_file": str(self.config.get("credentials_file", "")),
                "timeout": self.timeout,
            },
        )

    async def _send_private_image(self, recipient, path):
        platform = self._private_platform(recipient)
        result = await asyncio.wait_for(
            platform.get_client().call_action(
                "send_private_msg",
                user_id=int(recipient),
                message=[
                    {
                        "type": "image",
                        "data": {
                            "file": "base64://"
                            + base64.b64encode(path.read_bytes()).decode("ascii")
                        },
                    }
                ],
            ),
            timeout=60,
        )
        if not isinstance(result, dict) or not result.get("message_id"):
            raise RuntimeError("private_image_not_acknowledged")
        return str(result["message_id"])

    async def _course_query(self, request):
        result = await self._homework_query(request)
        for course in request["courses"]:
            if course["kind"] != "graduate":
                continue
            health = self.poll_health.get("homework", {})
            if (
                self.homework is None
                or not health.get("last_success")
                or health.get("failures")
            ):
                result["courses"].append(
                    {
                        "id": course["id"],
                        "status": "error",
                        "error": "研究生作业同步未成功，保留缓存",
                    }
                )
                continue
            tasks = []
            snapshot = self.homework.db.execute(
                "SELECT value FROM homework_meta WHERE key='snapshot'"
            ).fetchone()
            submitted_ids = (
                set(json.loads(snapshot[0]).get("submitted_ids", []))
                if snapshot
                else set()
            )
            for row in self.homework.db.execute("SELECT * FROM assignments"):
                item = json.loads(row["payload"])
                if item["course"] != course["name"] or (
                    not row["active"] and item["id"] not in submitted_ids
                ):
                    continue
                tasks.append(
                    {
                        "id": item["id"],
                        "title": f"H{row['number']} {item['title']}",
                        "description": item["description"],
                        "url": course["url"],
                        "deadline": item.get("deadline"),
                        "precision": "minute",
                        "submitted": item.get("submitted", False),
                    }
                )
            result["courses"].append(
                {"id": course["id"], "status": "ok", "tasks": tasks, "materials": []}
            )
        return result

    async def _course_image(self, report):
        result = await assignment_request(
            self.worker_python, {"operation": "render_course_report", "report": report}
        )
        return base64.b64decode(result["content"], validate=True)

    async def _poll_courses(self):
        await asyncio.sleep(25)
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await self.courses.poll()
                await self._record_poll("courses", (self.courses.owner,))
                self.logger.info(
                    "Course poll complete; course tasks and materials synchronized"
                )
            except Exception as exc:  # noqa: BLE001 - leave cached course data intact on a failed read
                self.logger.warning("Course poll failed (%s)", query_error_reason(exc))
                await self._record_poll("courses", (self.courses.owner,), exc)
            await asyncio.sleep(
                max(
                    1,
                    self.course_interval * 60
                    - (asyncio.get_running_loop().time() - started),
                )
            )

    async def _poll_course_reports(self):
        await asyncio.sleep(30)
        while True:
            try:
                if self.poll_health.get("courses", {}).get("last_success"):
                    await self.courses.daily()
                    await self._record_poll("course_reports", (self.courses.owner,))
            except Exception as exc:  # noqa: BLE001 - delivery progress is persisted per text chunk and image
                self.logger.warning(
                    "Course report failed (%s)", query_error_reason(exc)
                )
                await self._record_poll("course_reports", (self.courses.owner,), exc)
            await asyncio.sleep(30)

    async def _homework_generate(self, system, question):
        concise = "作答方式：小测简答。" in question
        provider_id = str(self.config.get("homework_provider_id", "")).strip()
        if not provider_id:
            provider_id = await self.context.get_current_chat_provider_id(
                f"{self.platform_id}:FriendMessage:{self.config.get('homework_recipient', '')}"
            )
        response = await asyncio.wait_for(
            self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=system,
                prompt=question,
                contexts=[],
                max_tokens=1200 if concise else 6000,
                thinking={"type": "disabled"},
                request_max_retries=1,
            ),
            timeout=90 if concise else 180,
        )
        raw = getattr(response, "raw_completion", None)
        if (
            any(
                getattr(choice, "finish_reason", None) == "length"
                for choice in (getattr(raw, "choices", None) or [])
            )
            or getattr(raw, "stop_reason", None) == "max_tokens"
            or getattr(raw, "status", None) == "incomplete"
        ):
            raise ValueError("模型回答被截断，未生成可提交草稿；请缩短作答范围后重试。")
        model = getattr(raw, "model", None) or provider_id
        return response.completion_text, model

    async def _homework_pdf(self, content):
        result = await assignment_request(
            self.worker_python, {"operation": "render_pdf", "content": content}
        )
        return base64.b64decode(result["content"], validate=True)

    async def _watch_homework_deadlines(self):
        await asyncio.sleep(15)
        while True:
            try:
                await self.homework.check_deadlines()
            except Exception as exc:  # noqa: BLE001 - retry status checks, never blind-repeat a submission
                self.logger.warning(
                    "Homework deadline check failed (%s)", query_error_reason(exc)
                )
            await asyncio.sleep(10)

    async def _poll_homework(self):
        await asyncio.sleep(15)
        startup = True
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await self.homework.poll(startup=startup)
                startup = False
                await self._record_poll("homework", (self.homework.owner,))
                self.logger.info(
                    "Homework poll complete; owner notifications and drafts processed"
                )
            except Exception as exc:  # noqa: BLE001 - preserve the periodic task without private payloads
                self.logger.warning(
                    "Homework poll failed (%s)", query_error_reason(exc)
                )
                await self._record_poll("homework", (self.homework.owner,), exc)
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(1, self.homework_interval * 60 - elapsed))

    async def _poll_weekly(self):
        await asyncio.sleep(20)
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await self.weekly.poll()
                await self._record_poll("weekly", (self.weekly.owner,))
                self.logger.info(
                    "Weekly report poll complete; submission states checked"
                )
            except Exception as exc:  # noqa: BLE001 - keep retrying reads without repeating uncertain writes
                self.logger.warning(
                    "Weekly report poll failed (%s)", query_error_reason(exc)
                )
                await self._record_poll("weekly", (self.weekly.owner,), exc)
            delay = max(
                1,
                int(self.config.get("weekly_interval_minutes", 3)) * 60
                - (asyncio.get_running_loop().time() - started),
            )
            now = weekly_time()
            until_submission = (
                now.replace(hour=self.weekly.hour, minute=0, second=0, microsecond=0)
                - now
            ).total_seconds()
            if until_submission > 0:
                delay = min(delay, until_submission)
            await asyncio.sleep(delay)

    async def _record_poll(self, source, recipients, error=None):
        health = self.poll_health.setdefault(
            source, {"failures": 0, "alerted": set(), "last_success": None, "error": ""}
        )
        label = {
            "homework": "作业",
            "courses": "课程",
            "course_reports": "课件日报",
            "weekly": "周汇报",
        }.get(source, "讲座")
        if error is None:
            health.update(failures=0, last_success=timestamp(), error="")
        else:
            health["failures"] += 1
            health["error"] = query_error_reason(error)
        for recipient in recipients:
            if (
                error is not None
                and health["failures"] >= 3
                and recipient not in health["alerted"]
            ):
                text = f"【{label}通知异常】连续检查失败（{health['error']}），暂时无法获取学校最新信息。会继续重试，恢复后通知你。"
            elif error is None and recipient in health["alerted"]:
                text = f"【{label}通知已恢复】学校查询成功，已恢复自动检查。"
            else:
                continue
            try:
                await self._send_private(recipient, text)
            except Exception as exc:  # noqa: BLE001 - retry only the undelivered status notification
                self.logger.warning(
                    "Poll status delivery failed (%s)", type(exc).__name__
                )
                continue
            if error is None:
                health["alerted"].discard(recipient)
            else:
                health["alerted"].add(recipient)

    def _homework_status(self):
        health = self.poll_health.get("homework", {})
        last = health.get("last_success") or "本次启动后尚未成功"
        if health.get("failures"):
            return f"自动检查异常：{health['error']}\n最近成功：{last}\n以下是缓存列表，不代表学校当前状态。\n\n"
        if not health.get("last_success"):
            return "正在等待首次作业检查，以下是缓存列表。\n\n"
        automatic = getattr(self.homework, "auto_submit", False)
        policy = (
            f"截止前 {self.homework.deadline_seconds // 60} 分钟自动提交最新 PDF。"
            if automatic
            else "确认后提交 PDF。"
        )
        return f"自动检查正常，每 {self.homework_interval} 分钟一次。\n{policy}\n最近成功：{last}\n\n"

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=110)
    async def weekly_message(self, event: AstrMessageEvent):
        if self.weekly is None or not event.is_private_chat():
            return
        if (
            str(event.get_sender_id()) != self.weekly.owner
            or event.get_platform_id() != self.platform_id
            or str(event.get_sender_id()) == str(event.get_self_id())
        ):
            return
        if not re.fullmatch(
            r"/?周汇报(?:\s+(?:状态|列表))?", event.message_str.strip()
        ):
            return
        event.stop_event()
        health = self.poll_health.get("weekly", {})
        prefix = "以下为缓存，最近学校检查失败。\n" if health.get("failures") else ""
        await self._send_private(self.weekly.owner, prefix + self.weekly.status())

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=110)
    async def course_message(self, event: AstrMessageEvent):
        if self.courses is None or not event.is_private_chat():
            return
        if (
            str(event.get_sender_id()) != self.courses.owner
            or event.get_platform_id() != self.platform_id
            or str(event.get_sender_id()) == str(event.get_self_id())
        ):
            return
        match = re.fullmatch(r"/?课程(?:\s+([\s\S]*))?", event.message_str.strip())
        if not match:
            return
        event.stop_event()
        try:
            result = await self.courses.command((match.group(1) or "").strip())
        except Exception as exc:  # noqa: BLE001 - no raw model or school payloads in error messages
            self.logger.warning("Course command failed (%s)", type(exc).__name__)
            result = "课程操作暂未完成，请稍后重试；已保存的通知记录不会清空。"
        for start in range(0, len(result), 1700):
            await self._send_private(self.courses.owner, result[start : start + 1700])

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=110)
    async def homework_message(self, event: AstrMessageEvent):
        if self.homework is None or not event.is_private_chat():
            return
        if (
            str(event.get_sender_id()) != self.homework.owner
            or event.get_platform_id() != self.platform_id
        ):
            return
        if str(event.get_sender_id()) == str(event.get_self_id()):
            return
        match = re.fullmatch(
            r"/?(?:作业|homework)(?:\s+([\s\S]*))?",
            event.message_str.strip(),
            re.IGNORECASE,
        )
        if not match:
            return
        event.stop_event()
        try:
            argument = (match.group(1) or "").strip()
            result = await self.homework.command(argument)
            if argument in {"", "列表", "状态"}:
                result = self._homework_status() + result
        except ValueError as exc:
            result = {
                "homework_already_submitted": "学校系统已有提交记录，不会覆盖。",
                "homework_requirements_changed": "作业要求已更新，请等待新草稿并确认新版本。",
                "homework_submission_closed": "学校系统已关闭该作业的提交入口。",
                "homework_file_type_rejected": "学校不接受当前文件格式，未上传文件。",
                "homework_owner_mismatch": "作业身份核对失败，已停止操作。",
                "homework_not_found": "学校系统中未找到该作业。",
            }.get(
                str(exc),
                query_error_reason(exc) if isinstance(exc, QueryError) else str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - never send raw API exceptions to QQ
            self.logger.warning("Homework command failed (%s)", type(exc).__name__)
            result = "作业操作失败，请查看状态；提交结果未确认时不会自动重复提交。"
        if result:
            for start in range(0, len(result), 1800):
                await self._send_private(
                    self.homework.owner, result[start : start + 1800]
                )

    async def _poll(self) -> None:
        # Plugin initialization can precede the OneBot connection on a full host start.
        await asyncio.sleep(15)
        while True:
            started = asyncio.get_running_loop().time()
            try:
                snapshot = await fetch_snapshot(
                    self.worker_python,
                    str(self.config.get("credentials_file", "")),
                    self.timeout,
                )
                await self._record_poll("seminar", self.recipients)
                items = seminar_notifications(
                    snapshot,
                    preferred_only=self.config.get("preferred_only", True),
                    interval=self.interval,
                )
                for recipient in self.recipients:
                    try:
                        count = await deliver(
                            self.store,
                            self._send_private,
                            source="seminar-radar",
                            platform_id=self.platform_id,
                            recipient=recipient,
                            notifications=items,
                            limit=self.limit,
                        )
                        self.logger.info(
                            "SeminarRadar poll complete: total=%s available=%s recommended=%s sent=%s",
                            snapshot["total"],
                            snapshot["available_count"],
                            snapshot["recommended_count"],
                            count,
                        )
                    except Exception as exc:  # noqa: BLE001 - keep polling, without logging QQ payloads
                        self.logger.warning(
                            "SeminarRadar private delivery failed (%s)",
                            type(exc).__name__,
                        )
            except Exception as exc:  # noqa: BLE001 - isolate failures in the periodic worker
                self.logger.warning(
                    "SeminarRadar poll failed (%s)", query_error_reason(exc)
                )
                await self._record_poll("seminar", self.recipients, exc)
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(1, self.interval * 60 - elapsed))

    async def terminate(self) -> None:
        if self.weekly_task is not None:
            self.weekly_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.weekly_task
        if self.weekly is not None:
            self.weekly.close()
        for task in (self.course_task, self.course_report_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if self.courses is not None:
            self.courses.close()
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if self.store is not None:
            self.store.close()
        if self.deadline_task is not None:
            self.deadline_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.deadline_task
        if self.homework_task is not None:
            self.homework_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.homework_task
        if self.homework is not None:
            self.homework.close()
