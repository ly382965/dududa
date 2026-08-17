import asyncio
from collections import deque
from typing import TypedDict


class MsgRecord(TypedDict):
    send_id: str
    fp: str


class GroupState:
    def __init__(self, thresholds: dict[str, int]):
        self.lock = asyncio.Lock()
        self.messages: dict[str, deque[MsgRecord]] = {
            seg_type: deque(maxlen=limit) for seg_type, limit in thresholds.items()
        }
        self.last_repeated_fingerprint: str | None = None

    def clear_if_same_sender(
        self,
        seg_type: str,
        send_id: str,
        need_different: bool,
    ) -> None:
        if not need_different:
            return
        messages = self.messages[seg_type]
        if messages and messages[-1]["send_id"] == send_id:
            messages.clear()

    def push_message(self, seg_type: str, send_id: str, fp: str) -> None:
        self.messages[seg_type].append({"send_id": send_id, "fp": fp})

    def get_messages(self, seg_type: str) -> deque[MsgRecord]:
        return self.messages[seg_type]

    def clear_all(self) -> None:
        for messages in self.messages.values():
            messages.clear()

    def is_same_as_last_repeat(self, fingerprint: str) -> bool:
        return self.last_repeated_fingerprint == fingerprint

    def mark_repeated(self, fingerprint: str) -> None:
        self.last_repeated_fingerprint = fingerprint
        self.clear_all()


class StateManager:
    _group_states: dict[str, GroupState] = {}

    def __init__(self, thresholds: dict[str, int]):
        self.thresholds = thresholds

    def get_state(self, group_id: str) -> GroupState:
        if group_id not in self._group_states:
            self._group_states[group_id] = GroupState(self.thresholds)
        return self._group_states[group_id]
