"""Pure compatibility behavior retained while legacy plugins remain active."""

from .reply_polish import split_long_piece, split_text
from .target_talk import TargetUser, clean_reply, load_targets, should_handle_message

__all__ = [
    "TargetUser",
    "clean_reply",
    "load_targets",
    "should_handle_message",
    "split_long_piece",
    "split_text",
]
