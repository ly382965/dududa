from __future__ import annotations

import base64
import os
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image
from astrbot.core.star.filter.command import GreedyStr

from .config import PLUGIN_DATA_DIR
from .emoji_kitchen import (
    DEFAULT_METADATA_TTL_SECONDS,
    EmojiKitchenError,
    EmojiKitchenService,
    EmojiKitchenUnavailableError,
    EmojiKitchenUnsupportedError,
    EmojiKitchenUsageError,
)


class EmojiKitchenCommands:
    @staticmethod
    def _emoji_group_enabled(event) -> bool:
        if not os.environ.get("DUDUDA_AGENT_POLICY_PATH", "").strip():
            return True
        try:
            from dududa.control_plane.plugin_policy import group_plugin_enabled
        except ImportError:
            return False
        return group_plugin_enabled("emoji.kitchen", bot_id=str(event.get_self_id() or ""), group_id=str(event.get_group_id() or ""))

    async def emoji(self, event: AstrMessageEvent, arguments: GreedyStr):
        if not self._emoji_group_enabled(event):
            return
        async for result in self._emoji_response(event, arguments):
            if not self._emoji_group_enabled(event):
                return
            yield result

    async def _emoji_response(self, event: AstrMessageEvent, arguments: GreedyStr):
        """合成两个 Unicode Emoji。"""
        if not self._emoji_kitchen_enabled():
            return

        try:
            result = await self._emoji_kitchen_service().compose(str(arguments))
        except EmojiKitchenUsageError:
            yield event.plain_result(
                "用法：/emoji <Emoji1> <Emoji2>，例如 /emoji 😀 😭"
            )
            event.stop_event()
            return
        except EmojiKitchenUnsupportedError as exc:
            if exc.left and exc.right:
                yield event.plain_result(
                    f"暂时没有 {exc.left} + {exc.right} 的官方合成表情。"
                )
            else:
                yield event.plain_result(str(exc))
            event.stop_event()
            return
        except EmojiKitchenUnavailableError as exc:
            logger.warning("Emoji Kitchen unavailable: %s", type(exc).__name__)
            yield event.plain_result("表情合成数据暂时不可用，请稍后重试。")
            event.stop_event()
            return
        except EmojiKitchenError as exc:
            logger.warning("Emoji Kitchen failed: %s", type(exc).__name__)
            yield event.plain_result("表情合成失败，请稍后重试。")
            event.stop_event()
            return
        except Exception as exc:  # noqa: BLE001 - command boundary must not leak failures
            logger.warning("Emoji Kitchen failed unexpectedly: %s", type(exc).__name__)
            yield event.plain_result("表情合成失败，请稍后重试。")
            event.stop_event()
            return

        encoded = base64.b64encode(result.image_bytes).decode("ascii")
        yield event.chain_result([Image.fromBase64(encoded)])
        event.stop_event()

    def _emoji_kitchen_enabled(self) -> bool:
        config = getattr(self, "config", {}) or {}
        return config.get("enabled", True) is not False

    def _emoji_kitchen_service(self) -> EmojiKitchenService:
        service = getattr(self, "_emoji_kitchen_service_instance", None)
        if service is not None:
            return service
        config: dict[str, Any] = getattr(self, "config", {}) or {}
        raw_ttl = config.get(
            "metadata_ttl_seconds", DEFAULT_METADATA_TTL_SECONDS
        )
        try:
            ttl = int(raw_ttl)
        except (TypeError, ValueError):
            ttl = DEFAULT_METADATA_TTL_SECONDS
        service = EmojiKitchenService(
            PLUGIN_DATA_DIR / "emoji-kitchen",
            metadata_ttl_seconds=ttl,
        )
        self._emoji_kitchen_service_instance = service
        return service
