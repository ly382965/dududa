"""嘟嘟哒私聊通知：学术报告、研究生作业 PDF 草稿与提交、全课程任务/课件日报、助教空周汇报。

Port of the AstrBot plugin ``astrbot_plugin_dududa_notify``. The Host-side services
(``notifications``, ``homework``, ``course_tasks``, ``weekly``) keep the plugin's SQLite layout under
``state_dir("notify")`` so ``ops/cli/migrate_notify_state.sh`` can copy existing state in unchanged.
Campus access, PDF/PNG rendering and course readers run in a separate worker venv
(``worker-requirements.txt``, ``ops/cli/install_notify_worker.sh``) through ``worker.py`` and
``assignment_worker.py``; those worker-side modules are never imported by the Host.

Notifications go only to configured private recipients; extra BB accounts have separate state.
``notify_auto_submit`` gates the original school writers; BB subscriptions never submit.
"""

from __future__ import annotations

import asyncio
import base64
import contextvars
import hashlib
import itertools
import json
import logging
import re
import time
import weakref
from pathlib import Path
from typing import Any

from ...router import strip_prefix
from ..base import (
    Command,
    Ctx,
    Delegate,
    FeatureError,
    Job,
    JobCtx,
    Registry,
    Reply,
    Task,
    Toolkit,
)
from .course_catalog import DEFAULT_COURSES, validate_courses
from .course_tasks import CourseService
from .homework import HomeworkService, current_time, timestamp
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

FEATURE = "notify"
SEMINAR, HOMEWORK, COURSES, WEEKLY, AUTO_SUBMIT = (
    "notify_seminar", "notify_homework", "notify_courses", "notify_weekly", "notify_auto_submit")
BLACKBOARD = "notify_blackboard"
HEALTH_LABELS = {
    "homework": "作业", "courses": "课程", "course_reports": "课件日报", "weekly": "周汇报",
    "blackboard": "BB课程", "blackboard_reports": "BB课件日报",
}
HOMEWORK_ERRORS = {
    "homework_already_submitted": "学校系统已有提交记录，不会覆盖。",
    "homework_requirements_changed": "作业要求已更新，请等待新草稿并确认新版本。",
    "homework_submission_closed": "学校系统已关闭该作业的提交入口。",
    "homework_file_type_rejected": "学校不接受当前文件格式，未上传文件。",
    "homework_owner_mismatch": "作业身份核对失败，已停止操作。",
    "homework_not_found": "学校系统中未找到该作业。",
}

log = logging.getLogger(__name__)
# Message id of the owner command being handled; sends made under it get per-command dedupe keys.
_command_origin: contextvars.ContextVar[str | None] = contextvars.ContextVar("notify_command", default=None)
_services: weakref.WeakKeyDictionary[Any, Notify] = weakref.WeakKeyDictionary()


def _int(cfg: dict, key: str, default: int, low: int, high: int) -> int:
    value = int(cfg.get(key, default))
    if not low <= value <= high:
        raise FeatureError(f"通知配置 {key} 超出范围 {low}–{high}")
    return value


def fingerprint(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()[:24]


def message_key(kind: str, recipient: str, data: str | bytes, day: str, origin: str | None, sequence: int) -> str:
    """Outbox dedupe key: owner commands are unique per request; proactive messages once per day.

    The services' own SQLite state decides *whether* to notify; this key only stops the same
    proactive text (or file/image) from being queued twice in one Beijing day.
    """
    if origin:
        return f"notify:cmd:{origin}:{sequence}"
    return f"notify:{kind}:{recipient}:{fingerprint(data)}:{day}"


def poll_due(last: float | None, now: float, minutes: int) -> bool:
    """Interval counted from the previous poll's start, as the plugin did."""
    return last is None or now - last >= minutes * 60 - 1


def weekly_due(last_wall: float | None, now_wall: float, minutes: int, hour: int) -> bool:
    """Regular interval, plus an early wake-up when the submission hour has just been crossed."""
    if poll_due(last_wall, now_wall, minutes):
        return True
    now = current_time()
    mark = now.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()
    return last_wall < mark <= now_wall


class Notify:
    """Per-runtime services, poll health and send glue (one instance per Runtime)."""

    def __init__(self, runtime: Any):
        self.tk = JobCtx(runtime)
        cfg = self.tk.config(FEATURE)
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", False))
        self.dry_run = bool(cfg.get("dry_run", False))
        self.account = str(cfg.get("account_id") or "")
        if self.enabled and not self.account.startswith("qq-"):
            raise FeatureError("notify.account_id 必须填写机器人账号，例如 qq-<机器人QQ号>")
        self.platform_id = str(cfg.get("platform_id") or "dududa")
        recipients = cfg.get("recipients", [])
        if not isinstance(recipients, list):
            raise FeatureError("notify.recipients 必须是 QQ 号列表")
        self.recipients = tuple(dict.fromkeys(str(value).strip() for value in recipients))
        if any(not value.isascii() or not value.isdigit() or int(value) <= 0 for value in self.recipients):
            raise FeatureError("notify.recipients 只能填写 QQ 号")
        self.owner = str(cfg.get("homework_recipient", "")).strip()
        self.interval = _int(cfg, "interval_minutes", 3, 1, 1440)
        self.limit = _int(cfg, "max_messages_per_poll", 5, 1, 20)
        self.timeout = float(cfg.get("request_timeout_seconds", 45))
        if not 0 < self.timeout <= 300:
            raise FeatureError("notify.request_timeout_seconds 超出范围")
        self.root = self.tk.state_dir(FEATURE)
        configured = str(cfg.get("worker_python", "")).strip()
        self.python = Path(configured) if configured else self.root / "worker-venv/bin/python"
        self.credentials = str(cfg.get("credentials_file", ""))
        self.proxy = self.tk.settings.proxy_url
        self.health: dict[str, dict] = {}
        self.last_run: dict[str, float] = {}
        self.homework_started = False
        self.sequence = itertools.count(1)
        self.store: DeliveryStore | None = None
        self.homework: HomeworkService | None = None
        self.courses: CourseService | None = None
        self.weekly: WeeklyService | None = None
        self.blackboard_accounts: dict[str, CourseService] = {}
        self.blackboard_intervals: dict[str, int] = {}
        owned = [flag for flag in ("homework_enabled", "courses_enabled", "weekly_enabled") if cfg.get(flag)]
        if self.enabled and owned and self.owner not in self.recipients:
            raise FeatureError("notify.homework_recipient 必须在 recipients 中")
        if not self.enabled:
            return
        if cfg.get("seminar_enabled", True):
            self.store = DeliveryStore(self.root / "deliveries.sqlite3")
        if cfg.get("homework_enabled"):
            self.homework_interval = _int(cfg, "homework_interval_minutes", 3, 1, 1440)
            self.homework = HomeworkService(
                self.root, self.owner, self.query, self.generate,
                lambda text: self.send_text(self.owner, text, "homework"),
                lambda path: self.send_file(self.owner, path),
                render_pdf=self.render_pdf, auto_submit=self.auto_submit_allowed(),
                deadline_minutes=_int(cfg, "homework_auto_submit_minutes", 3, 1, 60), dry_run=self.dry_run)
        if cfg.get("courses_enabled"):
            sources = [{k: v for k, v in course.items() if not str(k).startswith("__")}
                       for course in cfg.get("course_sources") or DEFAULT_COURSES if isinstance(course, dict)]
            try:
                validate_courses(sources)
            except ValueError as exc:
                raise FeatureError(f"notify.course_sources 无效：{exc}") from None
            self.course_interval = _int(cfg, "courses_interval_minutes", 3, 1, 1440)
            self.courses = CourseService(
                self.root, self.owner, sources, self.course_query, self.generate, self.course_image,
                lambda text: self.send_text(self.owner, text, "courses"),
                lambda path: self.send_image(self.owner, path),
                summary_hour=_int(cfg, "courses_summary_hour", 20, 0, 23))
        if cfg.get("weekly_enabled"):
            self.weekly_interval = _int(cfg, "weekly_interval_minutes", 3, 1, 1440)
            policy = str(cfg.get("weekly_report_day", "first"))
            if policy not in ("first", "last"):
                raise FeatureError("notify.weekly_report_day 只能是 first 或 last")
            self.weekly = WeeklyService(
                self.root, self.owner, self.query, lambda text: self.send_text(self.owner, text, "weekly"),
                hour=_int(cfg, "weekly_submit_hour", 20, 0, 23), policy=policy,
                submit_allowed=self.auto_submit_allowed(), dry_run=self.dry_run)
        accounts = cfg.get("blackboard_accounts", [])
        if not isinstance(accounts, list):
            raise FeatureError("notify.blackboard_accounts 必须是账号列表")
        for account in accounts:
            if not isinstance(account, dict):
                raise FeatureError("BB 账号配置必须是对象")
            if not account.get("enabled", True):
                continue
            profile = account.get("id", "")
            recipient = str(account.get("recipient", "")).strip()
            credentials = account.get("credentials_file", "")
            term = account.get("term", "")
            if not isinstance(profile, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile):
                raise FeatureError("BB 账号 id 必须是安全的学号标识")
            if profile in self.blackboard_accounts:
                raise FeatureError("BB 账号 id 不能重复")
            if self.scope(recipient) not in self.tk.settings.allowed_scopes:
                raise FeatureError("BB 账号收件人必须在私聊白名单中")
            if not isinstance(credentials, str) or not credentials or not Path(credentials).is_absolute():
                raise FeatureError("BB 账号必须配置独立凭据文件的绝对路径")
            if not isinstance(term, str) or not re.fullmatch(r"20\d{2}[A-Z]{2}", term):
                raise FeatureError("BB 学期格式应为 2026FA")
            self.blackboard_intervals[profile] = _int(
                account, "interval_minutes", _int(cfg, "courses_interval_minutes", 3, 1, 1440), 1, 1440)
            self.blackboard_accounts[profile] = CourseService(
                self.root, recipient, [],
                lambda request, path=credentials, pid=profile, semester=term: self.blackboard_query(
                    request, credentials_file=path, profile=pid, term=semester),
                self.generate, self.course_image,
                lambda text, target=recipient, pid=profile: self.send_text(target, text, f"blackboard:{pid}"),
                lambda path, target=recipient: self.send_image(target, path),
                summary_hour=_int(account, "summary_hour", _int(cfg, "courses_summary_hour", 20, 0, 23), 0, 23),
                profile=profile, label=profile, discover=True, nonempty_only=True, analyze_materials=True,
            )


    # ------------------------------------------------------------ gates

    def auto_submit_allowed(self) -> bool:
        """``notify_auto_submit``: an explicit task switch wins; otherwise the plugin config decides."""
        if self.dry_run:
            return False
        switches = self.tk.store.switches()
        return switches.get(AUTO_SUBMIT, bool(self.cfg.get("homework_auto_submit_enabled", False)))

    def refresh_gates(self) -> None:
        allowed = self.auto_submit_allowed()
        if self.homework:
            self.homework.auto_submit = allowed
        if self.weekly:
            self.weekly.submit_allowed = allowed

    # ------------------------------------------------------------ sending

    def scope(self, recipient: str) -> str:
        return f"{self.account}/{self.account}:private:{recipient}"

    def push(self, recipient: str, reply: Reply, kind: str, data: str | bytes, key: str | None = None) -> str:
        if recipient not in self.recipients and not any(
            course.owner == recipient for course in self.blackboard_accounts.values()
        ):
            raise FeatureError("通知收件人未授权")
        key = key or message_key(kind, recipient, data, current_time().date().isoformat(),
                                 _command_origin.get(), next(self.sequence))
        queued = self.tk.push(self.scope(recipient), reply, dedupe=key)
        log.info("notify %s queued=%s dry_run=%s", kind, queued, self.dry_run)
        return "outbox:" + key

    async def send_text(self, recipient: str, text: str, kind: str = "text", key: str | None = None) -> str:
        return self.push(recipient, Reply.of_text(text), kind, text, key)

    async def send_file(self, recipient: str, path: Path) -> str:
        body = path.read_bytes()
        action = {"type": "file", "name": path.name, "data": base64.b64encode(body).decode("ascii"),
                  "mime": "application/pdf" if path.suffix.lower() == ".pdf" else "application/octet-stream"}
        return self.push(recipient, Reply(action), "file", body)

    async def send_image(self, recipient: str, path: Path) -> str:
        body = path.read_bytes()
        return self.push(recipient, Reply().image(body, mime="image/png"), "image", body)

    # ------------------------------------------------------------ worker / model

    async def query(self, request: dict) -> dict:
        return await assignment_request(
            self.python, {**request, "credentials_file": self.credentials, "timeout": self.timeout}, self.proxy)

    async def render_pdf(self, content: str) -> bytes:
        result = await assignment_request(self.python, {"operation": "render_pdf", "content": content}, self.proxy)
        return base64.b64decode(result["content"], validate=True)

    async def course_image(self, report: dict) -> bytes:
        result = await assignment_request(self.python, {"operation": "render_course_report", "report": report},
                                          self.proxy)
        return base64.b64decode(result["content"], validate=True)

    async def blackboard_query(self, request: dict, *, credentials_file: str, profile: str, term: str) -> dict:
        if request.get("operation") != "courses":
            raise FeatureError("BB 订阅仅允许读取课程")
        return await assignment_request(
            self.python, {**request, "credentials_file": credentials_file, "expected_username": profile,
                          "blackboard_term": term, "timeout": self.timeout}, self.proxy)

    async def generate(self, system: str, question: str) -> tuple[str, str]:
        concise = "作答方式：小测简答。" in question
        result = await self.tk.agent_once(question, service="qa", system=system, timeout=300 if concise else 600)
        if result.status != "completed" or not result.text.strip():
            raise ValueError("模型回答未完成，未生成可提交草稿；下轮重试。")
        return result.text, result.model

    async def course_query(self, request: dict) -> dict:
        result = await self.query(request)
        for course in request["courses"]:
            if course["kind"] != "graduate":
                continue
            health = self.health.get("homework", {})
            if self.homework is None or not health.get("last_success") or health.get("failures"):
                result["courses"].append({"id": course["id"], "status": "error", "error": "研究生作业同步未成功，保留缓存"})
                continue
            snapshot = self.homework.db.execute("SELECT value FROM homework_meta WHERE key='snapshot'").fetchone()
            submitted_ids = set(json.loads(snapshot[0]).get("submitted_ids", [])) if snapshot else set()
            tasks = []
            for row in self.homework.db.execute("SELECT * FROM assignments"):
                item = json.loads(row["payload"])
                if item["course"] != course["name"] or (not row["active"] and item["id"] not in submitted_ids):
                    continue
                tasks.append({"id": item["id"], "title": f"H{row['number']} {item['title']}",
                              "description": item["description"], "url": course["url"],
                              "deadline": item.get("deadline"), "precision": "minute",
                              "submitted": item.get("submitted", False)})
            result["courses"].append({"id": course["id"], "status": "ok", "tasks": tasks, "materials": []})
        return result

    # ------------------------------------------------------------ poll health

    async def record_poll(self, source: str, recipients: tuple[str, ...], error: BaseException | None = None) -> None:
        health = self.health.setdefault(source, {"failures": 0, "alerted": set(), "last_success": None, "error": ""})
        kind, _, profile = source.partition(":")
        label = HEALTH_LABELS.get(kind, "讲座") + (f"（{profile}）" if profile else "")
        if error is None:
            health.update(failures=0, last_success=timestamp(), error="")
        else:
            health["failures"] += 1
            health["error"] = query_error_reason(error)
        for recipient in recipients:
            if error is not None and health["failures"] >= 3 and recipient not in health["alerted"]:
                text = (f"【{label}通知异常】连续检查失败（{health['error']}），暂时无法获取学校最新信息。"
                        "会继续重试，恢复后通知你。")
            elif error is None and recipient in health["alerted"]:
                text = f"【{label}通知已恢复】学校查询成功，已恢复自动检查。"
            else:
                continue
            await self.send_text(recipient, text, "health", key=f"notify:health:{source}:{recipient}:{time.time_ns()}")
            if error is None:
                health["alerted"].discard(recipient)
            else:
                health["alerted"].add(recipient)

    def homework_status(self) -> str:
        health = self.health.get("homework", {})
        last = health.get("last_success") or "本次启动后尚未成功"
        if health.get("failures"):
            return f"自动检查异常：{health['error']}\n最近成功：{last}\n以下是缓存列表，不代表学校当前状态。\n\n"
        if not health.get("last_success"):
            return "正在等待首次作业检查，以下是缓存列表。\n\n"
        assert self.homework is not None
        policy = (f"截止前 {self.homework.deadline_seconds // 60} 分钟自动提交最新 PDF。"
                  if self.homework.auto_submit else "确认后提交 PDF。")
        return f"自动检查正常，每 {self.homework_interval} 分钟一次。\n{policy}\n最近成功：{last}\n\n"

    def due(self, name: str, minutes: int, force: bool) -> bool:
        now = time.time()
        if force or poll_due(self.last_run.get(name), now, minutes):
            self.last_run[name] = now
            return True
        return False

    # ------------------------------------------------------------ pollers

    async def poll_seminar(self, force: bool = False) -> None:
        if self.store is None or not self.due("seminar", self.interval, force):
            return
        try:
            snapshot = await fetch_snapshot(self.python, self.credentials, self.timeout, self.proxy)
        except Exception as exc:  # noqa: BLE001 - keep polling; never log school payloads
            log.warning("SeminarRadar poll failed (%s)", query_error_reason(exc))
            await self.record_poll("seminar", self.recipients, exc)
            return
        await self.record_poll("seminar", self.recipients)
        items = seminar_notifications(snapshot, preferred_only=self.cfg.get("preferred_only", True),
                                      interval=self.interval)
        ids = {item.text: item.id for item in items}
        for recipient in self.recipients:
            async def send(target: str, text: str) -> str:
                return await self.send_text(target, text, "seminar",
                                            key=f"notify:seminar-radar:{target}:{ids[text]}")
            count = await deliver(self.store, send, source="seminar-radar", platform_id=self.platform_id,
                                  recipient=recipient, notifications=items, limit=self.limit)
            log.info("SeminarRadar poll: total=%s available=%s recommended=%s queued=%s", snapshot["total"],
                     snapshot["available_count"], snapshot["recommended_count"], count)

    async def poll_homework(self, force: bool = False) -> None:
        if self.homework is None or not self.due("homework", self.homework_interval, force):
            return
        self.refresh_gates()
        try:
            await self.homework.poll(startup=not self.homework_started)
        except Exception as exc:  # noqa: BLE001 - preserve the job without private payloads
            log.warning("Homework poll failed (%s)", query_error_reason(exc))
            await self.record_poll("homework", (self.owner,), exc)
            return
        self.homework_started = True
        await self.record_poll("homework", (self.owner,))

    async def check_deadlines(self) -> None:
        if self.homework is None:
            return
        self.refresh_gates()
        if self.homework.auto_submit:
            await self.homework.check_deadlines()

    async def poll_courses(self, force: bool = False) -> None:
        if self.courses is None:
            return
        if self.due("courses", self.course_interval, force):
            try:
                await self.courses.poll()
                await self.record_poll("courses", (self.owner,))
            except Exception as exc:  # noqa: BLE001 - leave cached course data intact on a failed read
                log.warning("Course poll failed (%s)", query_error_reason(exc))
                await self.record_poll("courses", (self.owner,), exc)
        # Daily reports wait for this process's first successful course read.
        if self.health.get("courses", {}).get("last_success"):
            try:
                await self.courses.daily()
                await self.record_poll("course_reports", (self.owner,))
            except Exception as exc:  # noqa: BLE001 - delivery progress is persisted per chunk and image
                log.warning("Course report failed (%s)", query_error_reason(exc))
                await self.record_poll("course_reports", (self.owner,), exc)

    async def poll_blackboard(self, force: bool = False) -> None:
        await asyncio.gather(*(self._poll_blackboard(profile, course, force)
                               for profile, course in self.blackboard_accounts.items()))

    async def _poll_blackboard(self, profile: str, course: CourseService, force: bool) -> None:
        source, reports = f"blackboard:{profile}", f"blackboard_reports:{profile}"
        recipients = (course.owner,)
        if self.due(source, self.blackboard_intervals[profile], force):
            try:
                await course.poll()
                await self.record_poll(source, recipients)
            except Exception as exc:  # noqa: BLE001 - account failures must not affect another account
                log.warning("BB course poll failed for %s (%s)", profile, query_error_reason(exc))
                await self.record_poll(source, recipients, exc)
        if self.health.get(source, {}).get("last_success"):
            try:
                await course.daily()
                await self.record_poll(reports, recipients)
            except Exception as exc:  # noqa: BLE001 - persisted delivery progress prevents duplicate chunks
                log.warning("BB course report failed for %s (%s)", profile, query_error_reason(exc))
                await self.record_poll(reports, recipients, exc)

    async def poll_weekly(self, force: bool = False) -> None:
        if self.weekly is None:
            return
        now = time.time()
        if not force and not weekly_due(self.last_run.get("weekly"), now, self.weekly_interval, self.weekly.hour):
            return
        self.last_run["weekly"] = now
        self.refresh_gates()
        try:
            await self.weekly.poll()
        except Exception as exc:  # noqa: BLE001 - keep retrying reads without repeating uncertain writes
            log.warning("Weekly report poll failed (%s)", query_error_reason(exc))
            await self.record_poll("weekly", (self.owner,), exc)
            return
        await self.record_poll("weekly", (self.owner,))


def service(tk: Toolkit) -> Notify:
    notify = _services.get(tk.runtime)
    if notify is None:
        notify = _services[tk.runtime] = Notify(tk.runtime)
    return notify


# ---------------------------------------------------------------- jobs


async def seminar_job(ctx: JobCtx) -> None:
    await service(ctx).poll_seminar()


async def homework_job(ctx: JobCtx) -> None:
    await service(ctx).poll_homework()


async def deadline_job(ctx: JobCtx) -> None:
    await service(ctx).check_deadlines()


async def courses_job(ctx: JobCtx) -> None:
    await service(ctx).poll_courses()


async def blackboard_job(ctx: JobCtx) -> None:
    await service(ctx).poll_blackboard()


async def weekly_job(ctx: JobCtx) -> None:
    await service(ctx).poll_weekly()


# ---------------------------------------------------------------- owner commands


def _owner_body(ctx: Ctx, task: str, part: str, pattern: str) -> tuple[Notify, re.Match] | Delegate:
    """Owner private commands; anything else (other people, groups, chatter) goes to the agent."""
    body = strip_prefix(ctx.inbound.text, ctx.settings.bot_names)[0]
    match = re.fullmatch(pattern, body.strip(), re.IGNORECASE)
    if match is None or ctx.inbound.kind != "private" or not ctx.enabled(task):
        return Delegate(body)
    try:
        notify = service(ctx)
    except FeatureError as exc:
        log.warning("notify unavailable: %s", exc)
        return Delegate(body)
    if not notify.enabled or getattr(notify, part) is None or ctx.inbound.sender.id != notify.owner:
        return Delegate(body)
    return notify, match


def _chunks(text: str, size: int) -> Reply:
    return Reply(*({"type": "text", "text": text[start:start + size]} for start in range(0, len(text), size)))


async def homework_command(ctx: Ctx) -> Reply | Delegate:
    owned = _owner_body(ctx, HOMEWORK, "homework", r"(?:作业|homework)(?:\s+([\s\S]*))?")
    if isinstance(owned, Delegate):
        return owned
    notify, match = owned
    assert notify.homework is not None
    notify.refresh_gates()
    token = _command_origin.set(ctx.inbound.message_id)
    try:
        argument = (match.group(1) or "").strip()
        result = await notify.homework.command(argument)
        if argument in {"", "列表", "状态"}:
            result = notify.homework_status() + result
    except ValueError as exc:
        result = HOMEWORK_ERRORS.get(str(exc), query_error_reason(exc) if isinstance(exc, QueryError) else str(exc))
    except Exception as exc:  # noqa: BLE001 - never send raw API exceptions to QQ
        log.warning("Homework command failed (%s)", type(exc).__name__)
        result = "作业操作失败，请查看状态；提交结果未确认时不会自动重复提交。"
    finally:
        _command_origin.reset(token)
    return _chunks(result, 1800)


async def course_command(ctx: Ctx) -> Reply | Delegate:
    body = strip_prefix(ctx.inbound.text, ctx.settings.bot_names)[0]
    match = re.fullmatch(r"课程(?:\s+([\s\S]*))?", body.strip(), re.IGNORECASE)
    if match is None or ctx.inbound.kind != "private":
        return Delegate(body)
    try:
        notify = service(ctx)
    except FeatureError:
        return Delegate(body)
    if not notify.enabled:
        return Delegate(body)
    argument = (match.group(1) or "").strip()
    fields = argument.split(maxsplit=2)
    profile = fields[0] if fields and fields[0] in notify.blackboard_accounts else None
    if profile is not None:
        argument = argument[len(profile):].strip()
    elif len(fields) >= 2 and ":" in fields[1]:
        profile = fields[1].partition(":")[0]
    if profile is not None:
        course = notify.blackboard_accounts.get(profile)
        if course is None or course.owner != ctx.inbound.sender.id or not ctx.enabled(BLACKBOARD):
            return Delegate(body)
    elif ctx.inbound.sender.id == notify.owner and notify.courses is not None and ctx.enabled(COURSES):
        course = notify.courses
    else:
        choices = [item for item in notify.blackboard_accounts.values() if item.owner == ctx.inbound.sender.id]
        if not ctx.enabled(BLACKBOARD) or not choices:
            return Delegate(body)
        if len(choices) != 1:
            names = [name for name, item in notify.blackboard_accounts.items() if item.owner == ctx.inbound.sender.id]
            return Reply.of_text("请指定课程账号：课程 <学号> 列表\n可用账号：" + "、".join(names))
        course = choices[0]
    token = _command_origin.set(ctx.inbound.message_id)
    try:
        result = await course.command(argument)
    except Exception as exc:  # noqa: BLE001 - no raw model or school payloads in error messages
        log.warning("Course command failed (%s)", type(exc).__name__)
        result = "课程操作暂未完成，请稍后重试；已保存的通知记录不会清空。"
    finally:
        _command_origin.reset(token)
    return _chunks(result, 1700)


async def weekly_command(ctx: Ctx) -> Reply | Delegate:
    owned = _owner_body(ctx, WEEKLY, "weekly", r"周汇报(?:\s+(?:状态|列表))?")
    if isinstance(owned, Delegate):
        return owned
    notify, _ = owned
    assert notify.weekly is not None
    prefix = "以下为缓存，最近学校检查失败。\n" if notify.health.get("weekly", {}).get("failures") else ""
    return Reply.of_text(prefix + notify.weekly.status())


def register(registry: Registry) -> None:
    registry.task(Task(SEMINAR, "学术报告通知", "私聊推送可报名的研究生学术报告（B 站直播/高新校区优先）"))
    registry.task(Task(HOMEWORK, "作业通知", "研究生系统新作业私聊提醒，并生成 PDF 草稿供确认"))
    registry.task(Task(COURSES, "课程监控", "全课程任务、DDL 提醒与每日课件日报（list + 图片）"))
    registry.task(Task(BLACKBOARD, "BB课程订阅", "独立账号的BB课程更新、课件内作业与日报（只读）"))
    registry.task(Task(WEEKLY, "助教周报", "按汇报日检查助教空周汇报，状态变化私聊通知"))
    registry.task(Task(AUTO_SUBMIT, "自动提交",
                       "作业截止前自动提交最新 PDF、助教空周汇报自动提交；未手动设置时跟随配置 "
                       "homework_auto_submit_enabled"))
    registry.job(Job(SEMINAR, 30, seminar_job, initial_delay_seconds=15))
    registry.job(Job(HOMEWORK, 30, homework_job, initial_delay_seconds=15))
    registry.job(Job(AUTO_SUBMIT, 10, deadline_job, initial_delay_seconds=15))
    registry.job(Job(COURSES, 30, courses_job, initial_delay_seconds=25))
    registry.job(Job(BLACKBOARD, 30, blackboard_job, initial_delay_seconds=30))
    registry.job(Job(WEEKLY, 30, weekly_job, initial_delay_seconds=20))
    registry.command(Command(("作业", "homework"), homework_command,
                             "作业 列表/要求 H1/草稿 H1/评论 H1 1 内容/改稿 H1 意见/确认 H1 v1（仅主人私聊）"))
    registry.command(Command(("课程",), course_command,
                             "课程 [学号] 列表/今日/状态；课程 完成/恢复 <学号>:C1（仅授权私聊；主人原C1编号不变）"))
    registry.command(Command(("周汇报",), weekly_command, "周汇报 状态（仅主人私聊）"))
