from __future__ import annotations

import unicodedata

from dududa.domain.primitives import ComponentRevision
from dududa.errors import validation_error


class UnicodeVisibleTokenCounter:
    """Stable policy units, deliberately independent of provider tokenizers."""

    def __init__(self, revision: ComponentRevision) -> None:
        if not isinstance(revision, ComponentRevision):
            raise TypeError("invalid visible token counter revision")
        self._revision = revision

    @property
    def revision(self) -> ComponentRevision:
        return self._revision

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise validation_error("invalid_visible_text")
        normalized = unicodedata.normalize("NFC", text)
        count = 0
        in_word = False
        for character in normalized:
            if character.isspace():
                in_word = False
                continue
            if _is_cjk(character):
                count += 1
                in_word = False
                continue
            category = unicodedata.category(character)
            if category[0] in {"L", "N"} or character == "_":
                if not in_word:
                    count += 1
                    in_word = True
                continue
            count += 1
            in_word = False
        return count


def visible_character_count(text: str) -> int:
    if not isinstance(text, str):
        raise validation_error("invalid_visible_text")
    return len(unicodedata.normalize("NFC", text))


def estimate_delivery_parts(texts: tuple[str, ...], character_limit: int) -> int:
    if type(character_limit) is not int or character_limit < 1:
        raise validation_error("invalid_delivery_part_character_limit")
    if isinstance(texts, (str, bytes)) or any(
        not isinstance(text, str) for text in texts
    ):
        raise validation_error("invalid_delivery_part_texts")
    characters = sum(visible_character_count(text) for text in texts)
    if characters == 0:
        return 0
    return (characters + character_limit - 1) // character_limit


def _is_cjk(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x3134F
    )


__all__ = [
    "UnicodeVisibleTokenCounter",
    "estimate_delivery_parts",
    "visible_character_count",
]
