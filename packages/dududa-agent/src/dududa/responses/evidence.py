from __future__ import annotations

import re
import unicodedata

from dududa.domain.primitives import ComponentRevision
from dududa.errors import validation_error

from .contracts import AnswerProfile, DetailPreferenceEvidence

_PATTERNS = {
    AnswerProfile.SHORT: (
        re.compile(
            r"(?:(?:请|麻烦|能否|可以|也请|但也请)(?:用)?|^用)一句话(?:回答|说明|概括)"
        ),
        re.compile(
            r"(?:请|麻烦|回答时|也请|但也请)(?:尽量)?简(?:短|洁)(?:回答|说明|一点|点|些)?"
        ),
        re.compile(
            r"\b(?:please (?:answer )?briefly|please give (?:a )?short answer|answer in one sentence)\b"
        ),
    ),
    AnswerProfile.MEDIUM: (
        re.compile(r"(?:请(?:按)?|^按?)(?:中等长度|适中长度|正常详细度)(?:回答|说明)"),
        re.compile(r"\b(?:please use medium length|answer with moderate detail)\b"),
    ),
    AnswerProfile.LONG: (
        re.compile(
            r"(?:请|麻烦|能否|也请|但也请)(?:详细|深入|完整)(?:地)?(?:回答|解释|说明|分析|展开)(?:一下)?"
        ),
        re.compile(r"(?:请|麻烦|也请|但也请)展开(?:说说|说明|分析|回答)"),
        re.compile(
            r"\b(?:please (?:answer|explain) in detail|please give (?:a )?detailed answer|please provide (?:a )?deep dive|please give (?:a )?comprehensive answer)\b"
        ),
    ),
}

_HISTORY_SUMMARY_PATTERNS = (
    re.compile(
        r"^(?:@\S+\s+)?(?:(?:请|麻烦|帮我|帮忙|能否|可以)\s*)*"
        r"(?:总结|汇总|概括)(?:一下)?[^。！？\n：‘’“”\"']{0,80}"
        r"(?:本群|这个群|群聊|群里|讨论|聊天|消息|记录)"
    ),
    re.compile(
        r"^(?:@\S+\s+)?(?:please\s+)?summari[sz]e\b"
        r"[^.!?\n:\"'‘’“”]{0,100}\b(?:group|chat|conversation|discussion|messages|history)\b"
    ),
)


def is_history_summary_request(text: str) -> bool:
    """Only the leading request, not a summary instruction quoted as data."""
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    normalized = re.sub(r"(?<=\w)['’](?=\w)", "", normalized)
    return any(pattern.search(normalized) for pattern in _HISTORY_SUMMARY_PATTERNS)


def detect_detail_preference(
    message_ref: str,
    text: str,
    *,
    detector_revision: ComponentRevision,
) -> DetailPreferenceEvidence:
    if not isinstance(message_ref, str) or not message_ref.strip():
        raise validation_error("invalid_detail_evidence_message_ref")
    if not isinstance(text, str):
        raise validation_error("invalid_detail_evidence_text")
    if not isinstance(detector_revision, ComponentRevision):
        raise validation_error("invalid_detail_detector_revision")
    normalized = unicodedata.normalize("NFKC", text).casefold()
    matched = tuple(
        profile
        for profile, patterns in _PATTERNS.items()
        if any(pattern.search(normalized) is not None for pattern in patterns)
    )
    if len(matched) == 1:
        requested = matched[0]
        reasons = (f"explicit_{requested.value}_requested",)
    elif matched:
        requested = None
        reasons = ("conflicting_detail_preferences",)
    else:
        requested = None
        reasons = ("no_explicit_detail_preference",)
    return DetailPreferenceEvidence(
        schema_version=1,
        message_ref=message_ref,
        requested_profile=requested,
        reason_codes=reasons,
        detector_revision=detector_revision,
    )


__all__ = ["detect_detail_preference", "is_history_summary_request"]
