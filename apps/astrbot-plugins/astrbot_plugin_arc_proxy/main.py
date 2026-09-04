"""Explicit legacy QQ commands, separate from the local B50 Capability."""

# This QQ/vendor boundary must not propagate exceptions containing private data.
# ruff: noqa: BLE001

import asyncio
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import At, Image, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.command import GreedyStr

from .catalog import SongStore, format_song_info
from .chart_renderer import (
    DIFFICULTY_NAMES,
    ChartRenderer,
    UnsupportedChartError,
    parse_chart_query,
    resolve_rating_class,
)
from .logic import (
    SHANGHAI,
    command_after_reply,
    estimated_completion_time,
    is_query_queue_ack,
    normalize_argument,
    quota_release_time,
)
from .storage import BindingStore

PLUGIN_ID = "astrbot_plugin_arc_proxy"
PLUGIN_VERSION = "2.1.0"
USAGE = "用法：/arc bind 九位好友码、/arc b50、/arc info 曲目 或 /arc chart 曲目 [难度]"
CHART_USAGE = "用法：/arc chart 曲目 [pst/prs/ftr/byd/etr]（省略时使用最高难度）"
_ID = re.compile(r"[0-9]{1,20}")
_FRIEND_CODE = re.compile(r"[0-9]{9}")
_COMMAND = re.compile(r"^/?arc\s+(bind|b50|info|chart)(?:\s|$)", re.IGNORECASE)
_UPSTREAM_FAILURE = re.compile(
    r"失败|错误|出错|无效|不存在|不正确|异常|超时|拒绝|禁止|error|failed|invalid|not found",
    re.IGNORECASE,
)
_PAUSED = "B50 已暂停：上游状态不确定，请管理员确认上游空闲后重新加载插件。"


def _bounded_int(config, name, default, low, high):
    try:
        return max(low, min(high, int(config.get(name, default))))
    except (TypeError, ValueError, OverflowError):
        return default


@dataclass(slots=True, repr=False)
class QueryRequest:
    event: AstrMessageEvent
    user_id: str
    friend_code: str


@register(
    PLUGIN_ID, "mmdustc", "Arcaea 显式命令兼容与独立本地 B50 资产", PLUGIN_VERSION
)
class ArcB50AssetPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        config = config or {}
        # This existing switch remains exclusively about the local Capability.
        self.enabled = config.get("enabled", False) is True
        self.compatibility_enabled = config.get("compatibility_enabled", False) is True
        groups = config.get("allowed_group_ids", [])
        self.allowed_group_ids = (
            frozenset(str(value) for value in groups if _ID.fullmatch(str(value)))
            if isinstance(groups, (list, tuple))
            else frozenset()
        )
        self.upstream_bot_id = str(config.get("upstream_bot_id", "") or "").strip()
        state = str(config.get("state_root", "") or "").strip()
        self.state_root = Path(state) if state and Path(state).is_absolute() else None
        self.assets_root = self._path(config, "assets_root", "import")
        self.catalog_root = self._path(config, "catalog_root", "catalog")
        self.renderer_assets_root = self._path(
            config, "renderer_assets_root", "renderer-assets"
        )
        self.queue_capacity = _bounded_int(config, "queue_capacity", 8, 1, 32)
        self.request_timeout = _bounded_int(
            config, "request_timeout_seconds", 600, 30, 3600
        )
        self.transport_timeout = _bounded_int(
            config, "transport_timeout_seconds", 15, 3, 60
        )
        self.bindings = None
        self.songs = None
        self.chart_renderer = None
        self._pending: deque[QueryRequest] = deque()
        self._active: QueryRequest | None = None
        self._phase: str | None = None
        self._tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()
        self._paused = False
        self._closed = False
        logger.info(
            "Arc loaded: local_enabled=%s compatibility_enabled=%s",
            self.enabled,
            self.compatibility_enabled,
        )

    def _path(self, config, field, child):
        value = str(config.get(field, "") or "").strip()
        if value:
            return Path(value) if Path(value).is_absolute() else None
        return self.state_root / child if self.state_root else None

    def _authorized(self, event, command):
        match = _COMMAND.match((event.message_str or "").strip())
        return (
            not self._closed
            and self.compatibility_enabled
            and isinstance(event, AiocqhttpMessageEvent)
            and str(event.get_group_id() or "") in self.allowed_group_ids
            and bool(_ID.fullmatch(str(event.get_sender_id() or "")))
            and str(event.get_sender_id()) != str(event.get_self_id())
            and bool(match and match.group(1).lower() == command)
        )

    def _bindings(self):
        if self.bindings is None:
            if self.state_root is None:
                raise ValueError("arc_state_unconfigured")
            self.bindings = BindingStore(self.state_root / "bindings.sqlite3")
        return self.bindings

    def _songs(self):
        if self.songs is None:
            if (
                self.state_root is None
                or self.assets_root is None
                or self.catalog_root is None
            ):
                raise ValueError("arc_catalog_unconfigured")
            self.songs = SongStore(
                self.state_root / "songs.sqlite3", self.assets_root, self.catalog_root
            )
        return self.songs

    def _renderer(self):
        if self.chart_renderer is None:
            if (
                self.state_root is None
                or self.assets_root is None
                or self.renderer_assets_root is None
            ):
                raise ValueError("arc_renderer_unconfigured")
            self.chart_renderer = ChartRenderer(
                self.assets_root,
                self.renderer_assets_root,
                self.state_root / "rendered",
            )
        return self.chart_renderer

    @staticmethod
    def _valid_query(query):
        return (
            bool(query)
            and len(query) <= 200
            and not any(ord(char) < 32 or ord(char) == 127 for char in query)
        )

    @filter.command_group("arc")
    def arc(self):
        """Arcaea 查询命令。"""

    @arc.command("bind")
    async def arc_bind(self, event: AstrMessageEvent, friend_code: str = ""):
        if not self._authorized(event, "bind"):
            return
        event.stop_event()
        value = normalize_argument(friend_code)
        if not _FRIEND_CODE.fullmatch(value):
            yield event.plain_result(USAGE)
            return
        try:
            self._bindings().set(str(event.get_sender_id()), value)
        except Exception:
            yield event.plain_result(
                "好友码保存失败（arc_binding_unavailable），请联系管理员。"
            )
        else:
            yield event.plain_result("好友码已保存。")

    @arc.command("b50")
    async def arc_b50(self, event: AstrMessageEvent):
        if not self._authorized(event, "b50"):
            return
        event.stop_event()
        if not _ID.fullmatch(self.upstream_bot_id) or self.upstream_bot_id == str(
            event.get_self_id()
        ):
            yield event.plain_result("B50 上游未配置（arc_upstream_unconfigured）。")
            return
        try:
            friend_code = self._bindings().get(str(event.get_sender_id()))
        except Exception:
            yield event.plain_result(
                "好友码读取失败（arc_binding_unavailable），请联系管理员。"
            )
            return
        if not isinstance(friend_code, str) or not _FRIEND_CODE.fullmatch(friend_code):
            yield event.plain_result("请先使用 /arc bind 九位好友码。")
            return
        async with self._lock:
            if self._paused:
                notice = _PAUSED
            elif len(self._pending) + (1 if self._active else 0) >= self.queue_capacity:
                notice = "B50 队列已满，请稍后重试。"
            elif any(
                request.user_id == str(event.get_sender_id())
                for request in [
                    *self._pending,
                    *([self._active] if self._active else []),
                ]
            ):
                notice = "你已有 B50 请求在排队，请等待结果。"
            else:
                ahead = len(self._pending) + (1 if self._active else 0)
                self._pending.append(
                    QueryRequest(event, str(event.get_sender_id()), friend_code)
                )
                try:
                    await self._start_next()
                    notice = (
                        f"已排队，前面有 {ahead} 个请求。"
                        if ahead
                        else "已排队，正在获取预计查分时间。"
                    )
                except Exception:
                    await self._pause()
                    notice = _PAUSED
        yield event.plain_result(notice)

    @arc.command("info")
    async def arc_info(self, event: AstrMessageEvent, query: GreedyStr = ""):
        if not self._authorized(event, "info"):
            return
        event.stop_event()
        text = normalize_argument(query)
        if not self._valid_query(text):
            yield event.plain_result(USAGE)
            return
        try:
            matches = self._songs().search(text)
            if not matches:
                result = event.plain_result("未找到曲目。")
            elif len(matches) > 1:
                result = event.plain_result(self._candidates(matches))
            else:
                song = matches[0]
                result = event.chain_result(
                    [
                        Image.fromFileSystem(str(song.cover_path)),
                        Plain(format_song_info(song)),
                    ]
                )
        except Exception:
            result = event.plain_result(
                "曲目查询不可用（arc_catalog_unavailable），请检查本地资产。"
            )
        yield result

    @arc.command("chart")
    async def arc_chart(self, event: AstrMessageEvent, query: GreedyStr = ""):
        if not self._authorized(event, "chart"):
            return
        event.stop_event()
        text = normalize_argument(query)
        if not self._valid_query(text):
            yield event.plain_result(CHART_USAGE)
            return
        try:
            query_text, requested = parse_chart_query(text)
            matches = self._songs().search(query_text)
            if not matches:
                result = event.plain_result("未找到曲目。")
            elif len(matches) > 1:
                result = event.plain_result(self._candidates(matches))
            else:
                song = matches[0]
                rating_class = resolve_rating_class(song.charts, requested)
                chart = next(
                    (item for item in song.charts if item.rating_class == rating_class),
                    None,
                )
                if chart is None:
                    result = event.plain_result("该曲目没有对应的难度。")
                else:
                    image_path = await self._renderer().render(song, chart)
                    result = event.chain_result(
                        [
                            Image.fromFileSystem(str(image_path)),
                            Plain(
                                f"[Arcaea Chart]\n{song.title} [{DIFFICULTY_NAMES[rating_class]}]"
                            ),
                        ]
                    )
        except UnsupportedChartError:
            result = event.plain_result("该谱面为加密格式，暂不支持本地渲染。")
        except Exception:
            result = event.plain_result(
                "谱面渲染不可用（arc_chart_unavailable），请检查本地资产。"
            )
        yield result

    @staticmethod
    def _candidates(matches):
        return "找到多个曲目，请使用曲目 ID：" + " / ".join(
            f"{song.title} ({song.song_id})" for song in matches[:6]
        )

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=1000)
    async def watch_upstream(self, event: AstrMessageEvent):
        if (
            self._closed
            or not self.compatibility_enabled
            or not isinstance(event, AiocqhttpMessageEvent)
            or event.get_group_id()
            or not _ID.fullmatch(self.upstream_bot_id)
            or str(event.get_sender_id() or "") != self.upstream_bot_id
        ):
            return
        # Keep the original interception even when idle: unsolicited upstream
        # private replies must not fall through into a conversational auto-reply.
        event.stop_event()
        async with self._lock:
            request = self._active
            if request is None or str(event.get_self_id()) != str(
                request.event.get_self_id()
            ):
                return
            if self._paused or self._phase in ("quota_wait", "result_grace"):
                return
            try:
                await self._receive(request, event)
            except Exception:
                await self._pause()

    async def _receive(self, request, event):
        message = event.message_str or ""
        if _UPSTREAM_FAILURE.search(message):
            await self._pause()
            return
        components = getattr(getattr(event, "message_obj", None), "message", [])
        images = [component for component in components if isinstance(component, Image)]
        command = command_after_reply(self._phase, request.friend_code)
        if command:
            # A delayed image is not an acknowledgement of unbind/bind.
            # Legacy upstream has no correlation ID or documented success
            # payload. Preserve its text acknowledgement, but never advance
            # through a reported failure and query a previous user's binding.
            if not message.strip() or images:
                return
            self._phase = "bind" if self._phase == "unbind" else "b50"
            await self._send_upstream(request.event, command)
            return
        release_at = quota_release_time(message)
        if release_at is not None:
            self._phase = "quota_wait"
            self._spawn(self._retry_at(request, release_at))
            await self._notify(
                request, f"已排队，预计可查分时间：{release_at:%Y-%m-%d %H:%M:%S}。"
            )
        elif is_query_queue_ack(message):
            self._phase = "result_wait"
            completion = estimated_completion_time(message, datetime.now(SHANGHAI))
            notice = (
                f"已排队，预计完成时间：{completion:%Y-%m-%d %H:%M:%S}。"
                if completion
                else "已进入上游查询队列。"
            )
            await self._notify(request, notice)
        elif images and self._phase in ("b50", "result_wait"):
            self._phase = "result_grace"
            await asyncio.wait_for(
                request.event.send(MessageChain([At(qq=request.user_id), *images])),
                self.transport_timeout,
            )
            self._spawn(self._finish_after_result(request))

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _start_next(self):
        if (
            self._closed
            or self._paused
            or self._active is not None
            or not self._pending
        ):
            return
        self._active = self._pending.popleft()
        self._phase = "unbind"
        self._spawn(self._expire(self._active))
        await self._send_upstream(self._active.event, "/a unbind")

    async def _expire(self, request):
        await asyncio.sleep(self.request_timeout)
        async with self._lock:
            if self._active is request and self._phase != "result_grace":
                await self._pause()

    async def _finish_after_result(self, request):
        await asyncio.sleep(2)
        async with self._lock:
            if self._active is request and self._phase == "result_grace":
                self._active = None
                self._phase = None
                self._cancel_background()
                try:
                    await self._start_next()
                except Exception:
                    await self._pause()

    async def _retry_at(self, request, release_at):
        await asyncio.sleep(
            max(0.0, (release_at - datetime.now(SHANGHAI)).total_seconds())
        )
        async with self._lock:
            if (
                self._active is not request
                or self._phase != "quota_wait"
                or self._paused
            ):
                return
            self._phase = "b50"
            try:
                await self._send_upstream(request.event, "/ab50")
            except Exception:
                await self._pause()

    async def _send_upstream(self, event, command):
        await asyncio.wait_for(
            AiocqhttpMessageEvent.send_message(
                bot=event.bot,
                message_chain=MessageChain([Plain(command)]),
                is_group=False,
                session_id=self.upstream_bot_id,
            ),
            self.transport_timeout,
        )

    async def _notify(self, request, message):
        await asyncio.wait_for(
            request.event.send(MessageChain([At(qq=request.user_id), Plain(message)])),
            self.transport_timeout,
        )

    def _cancel_background(self):
        current = asyncio.current_task()
        for task in tuple(self._tasks):
            if task is not current:
                task.cancel()

    async def _pause(self):
        self._paused = True
        requests = [*([self._active] if self._active else []), *self._pending]
        self._active = None
        self._phase = None
        self._pending.clear()
        self._cancel_background()
        logger.warning("Arc B50 paused: arc_upstream_state_uncertain")
        for request in requests:
            try:
                await self._notify(request, _PAUSED)
            except Exception:
                logger.warning("Arc notification failed: arc_delivery_unavailable")

    async def terminate(self):
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._pending.clear()
        self._active = None
        self._phase = None
