import random

from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import BaseMessageComponent, Face, Image, Plain
from astrbot.core.platform import AstrMessageEvent
from astrbot.core.star.filter.event_message_type import EventMessageType

from .core.config import PluginConfig
from .core.state import StateManager


class RereadPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config, context)
        self.state_mgr = StateManager(self.cfg.thresholds)

    @staticmethod
    def make_fingerprint(segment: BaseMessageComponent) -> str:
        if isinstance(segment, Plain):
            return f"text:{segment.text}"
        if isinstance(segment, Image):
            return f"image:{segment.file or segment.url or segment.path}"
        if isinstance(segment, Face):
            return f"face:{segment.id}"
        return f"unknown:{segment.type}"

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def reread_handle(self, event: AstrMessageEvent):
        if not self.cfg.enabled:
            return
        if event.is_at_or_wake_command:
            return

        chain = event.get_messages()
        if len(chain) != 1:
            return

        segment = chain[0]
        segment_type = str(segment.type).split(".")[-1]
        if not self.cfg.is_supported_type(segment_type):
            return

        group_id = event.get_group_id()
        sender_id = event.get_sender_id()
        if self.cfg.group_whitelist and not self.cfg.is_white_group(group_id):
            return

        state = self.state_mgr.get_state(group_id)
        async with state.lock:
            state.clear_if_same_sender(
                segment_type,
                sender_id,
                self.cfg.need_different,
            )
            fingerprint = self.make_fingerprint(segment)
            state.push_message(segment_type, sender_id, fingerprint)
            messages = state.get_messages(segment_type)
            if len(messages) < self.cfg.get_threshold(segment_type):
                return
            if any(message["fp"] != messages[0]["fp"] for message in messages):
                return
            if state.is_same_as_last_repeat(fingerprint):
                return
            if random.random() >= self.cfg.reread_prob:
                return

            state.mark_repeated(fingerprint)
            output = (
                Plain("打断！")
                if random.random() < self.cfg.interrupt_prob
                else segment
            )

        await event.send(event.chain_result([output]))
        event.stop_event()
