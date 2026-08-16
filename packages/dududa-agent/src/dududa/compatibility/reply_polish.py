from __future__ import annotations

import re


ANSWER_PROFILE_EVENT_KEY = "dududa.answer_profile"


def should_merge_forward(
    answer_profile: object,
    text_length: int,
    min_chars: int,
) -> bool:
    """Return whether the legacy hook may turn a reply into merged forwarding.

    AnswerProfile is authoritative. Character count only decides whether an
    explicitly LONG answer is large enough to benefit from merged forwarding.
    """

    if type(text_length) is not int or type(min_chars) is not int:
        return False
    if text_length <= min_chars:
        return False
    return isinstance(answer_profile, str) and answer_profile.strip().lower() == "long"


def split_text(text: str, chunk_chars: int, max_nodes: int) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = split_long_piece(paragraph, chunk_chars)
        for piece in pieces:
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if len(candidate) <= chunk_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)

    if len(chunks) <= max_nodes:
        return chunks

    kept = chunks[: max_nodes - 1]
    tail = "\n\n".join(chunks[max_nodes - 1 :])
    kept.append(tail[: chunk_chars * 2])
    return kept


def split_long_piece(text: str, chunk_chars: int) -> list[str]:
    if len(text) <= chunk_chars:
        return [text]

    sentences = re.findall(r".+?[。！？!?；;]\s*|.+$", text, re.S)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > chunk_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(
                sentence[index : index + chunk_chars]
                for index in range(0, len(sentence), chunk_chars)
            )
            continue
        candidate = f"{current}{sentence}" if current else sentence
        if len(candidate) <= chunk_chars:
            current = candidate
        else:
            pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces
