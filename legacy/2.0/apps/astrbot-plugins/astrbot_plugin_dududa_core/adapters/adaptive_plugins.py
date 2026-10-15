"""Select an optional read-only capability from a developing group discussion."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdaptivePluginRequest:
    plugin_id: str
    reason: str
    question: str


_TOPICS = (
    (
        "icourse.read",
        r"评课|选课|课程评价|课程推荐|数学分析|线性代数|高等代数",
        "课程评价与选课讨论",
    ),
    ("ustc.young.read", r"二课|第二课堂|学术活动", "第二课堂活动讨论"),
    ("ustc.academic.read", r"考试安排|考试时间|教学日历|开课查询|教务", "教务安排讨论"),
    ("ustc.curriculum.read", r"培养方案|毕业学分|专业必修", "培养方案讨论"),
    ("notifai.read", r"校园通知|学校通知|通知截止|通知日历", "校园通知讨论"),
    ("ustc.shuttle.read", r"校车|班车|太湖路园区", "校车出行讨论"),
)
_QUESTION = re.compile(
    r"查|看看|建议|推荐|怎么选|如何选|哪个好|哪位|几点|什么时候|[?？]"
)


def select_adaptive_plugin(
    lines: tuple[str, ...],
    allowed: frozenset[str],
) -> AdaptivePluginRequest | None:
    """Require a shared topic and a current request, not a lone keyword."""
    if len(lines) < 8:
        return None
    speakers = {re.split(r"[：:]", line, maxsplit=1)[0] for line in lines}
    if len(speakers) < 3:
        return None
    question = re.split(r"[：:]", lines[-1], maxsplit=1)[-1].strip()
    if not _QUESTION.search(question):
        return None
    for plugin_id, pattern, reason in _TOPICS:
        if plugin_id not in allowed:
            continue
        relevant = sum(bool(re.search(pattern, line)) for line in lines[-20:])
        if relevant >= 3 and re.search(pattern, "\n".join(lines[-4:])):
            return AdaptivePluginRequest(plugin_id, reason, question)
    return None


def adaptive_history(lines: tuple[str, ...], *, bot_id: str, group_id: str) -> dict:
    """Keep conversation context separate from the query sent to a tool."""
    speakers: dict[str, str] = {}
    messages = []
    for index, line in enumerate(lines):
        parts = re.split(r"[：:]", line, maxsplit=1)
        name, content = (parts[0], parts[1]) if len(parts) == 2 else ("群友", line)
        sender = speakers.setdefault(name, f"adaptive-member-{len(speakers) + 1}")
        messages.append(
            {
                "id": f"adaptive-history-{index + 1}",
                "senderId": sender,
                "senderName": name,
                "content": content,
            }
        )
    return {
        "accountId": f"qq-{bot_id}",
        "conversationId": f"qq-{bot_id}:group:{group_id}",
        "source": "server_recent",
        "truncated": True,
        "messages": messages,
    }
