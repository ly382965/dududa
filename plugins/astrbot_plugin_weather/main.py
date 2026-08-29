from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .weather import fetch_weather, format_broadcast

_NAME = "astrbot_plugin_weather"


def _group(event: AstrMessageEvent) -> str:
    try:
        return str(event.message_obj.group_id)
    except Exception:
        return ""


@register(_NAME, "mmdustc", "每天早上8点播报当天天气（合肥/梅州兴宁）", "0.1.0")
class WeatherBroadcast(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))

        DATA_ROOT = Path(__file__).resolve().parents[2]
        data_dir = DATA_ROOT / "plugin_data" / _NAME
        data_dir.mkdir(parents=True, exist_ok=True)
        self.groups_path = data_dir / "known_groups.json"
        self.known_groups: set[str] = set()
        self._load_groups()

        # special: 兴宁播报群(可多个)
        single = str(self.config.get("xingning_group", "") or "")
        groups_cfg = self.config.get("xingning_groups", []) or []
        xn = [str(g) for g in groups_cfg if str(g)]
        if single and single not in xn:
            xn.insert(0, single)
        if not xn:
            xn = ["901226396"]
        self.xingning_groups = set(xn)

        self.bot_client: Any | None = None

        self.scheduler = AsyncIOScheduler()
        self._started = False

        logger.info("WeatherBroadcast loaded: enabled=%s", self.enabled)

    def _load_groups(self) -> None:
        try:
            if self.groups_path.exists():
                data = json.loads(self.groups_path.read_text(encoding="utf-8"))
                self.known_groups = set(data.get("groups", []))
        except Exception:
            self.known_groups = set()

    def _save_groups(self) -> None:
        try:
            self.groups_path.write_text(
                json.dumps({"groups": sorted(self.known_groups)}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weather save groups failed: %s", exc)

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            trigger = CronTrigger(hour=8, minute=0, second=0)
            self.scheduler.add_job(self._on_broadcast_time, trigger=trigger, id="weather_daily_8")
            self.scheduler.start()
            logger.info("WeatherBroadcast scheduler started (08:00 Asia/Shanghai)")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weather scheduler start failed: %s", exc)

    def shutdown(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AiocqhttpMessageEvent):
        if not self.enabled:
            return
        gid = _group(event)
        if gid:
            self.known_groups.add(gid)
            if self.bot_client is None:
                self.bot_client = getattr(event, "bot", None)
            # refresh the full joined-group list so weather reaches every group
            await self._refresh_group_list()
            self._save_groups()
            self.start()

    async def _refresh_group_list(self) -> None:
        client = self.bot_client
        if client is None:
            return
        try:
            result = await client.call_action("get_group_list")
            groups = result if isinstance(result, list) else (result.get("data") or [])
            for g in groups:
                gid = str(g.get("group_id", ""))
                if gid:
                    self.known_groups.add(gid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weather refresh group list failed: %s", exc)

    async def _on_broadcast_time(self) -> None:
        if not self.enabled:
            return
        if not self.bot_client:
            logger.warning("Weather no bot client yet, skip broadcast")
            return
        groups = set(self.known_groups) | set(self.config.get("extra_groups", []))
        if not groups:
            logger.warning("Weather no target groups, skip broadcast")
            return
        # fetch once per city
        hefei = None
        xingning = None
        for gid in sorted(groups):
            try:
                if str(gid) in self.xingning_groups:
                    weather = xingning if xingning else (await self._fetch("xingning"))
                    xingning = weather
                else:
                    weather = hefei if hefei else (await self._fetch("hefei"))
                    hefei = weather
                if not weather:
                    continue
                text = format_broadcast(weather)
                await self._send_group(str(gid), text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Weather broadcast to %s failed: %s", gid, exc)

    async def _fetch(self, city: str) -> dict[str, Any] | None:
        try:
            return await asyncio.to_thread(fetch_weather, city)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weather fetch %s failed: %s", city, exc)
            return None

    async def _send_group(self, gid: str, text: str) -> None:
        client = self.bot_client
        try:
            await client.call_action("send_group_msg", group_id=int(gid), message=text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weather send_group_msg to %s failed: %s", gid, exc)
