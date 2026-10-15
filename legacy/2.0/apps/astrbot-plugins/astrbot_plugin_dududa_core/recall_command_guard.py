"""Keep gateway-owned recall commands out of AstrBot's chat/LLM pipeline."""
from collections.abc import Mapping


COMMANDS = frozenset({"/开启防撤回", "/关闭防撤回"})


def consume_gateway_recall_command(event: object) -> bool:
    """Use original OneBot segments, matching the gateway's strict command parser.

    Authorization, persistence and the single confirmation belong to the gateway.
    Even unauthorized exact commands must not be answered by the language model.
    """
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    if not isinstance(raw, Mapping) or raw.get("message_type") != "group":
        return False
    segments = raw.get("message")
    if not isinstance(segments, list):
        return False
    if any(not isinstance(item, Mapping) or item.get("type") not in {"text", "at"} for item in segments):
        return False
    if any(not isinstance(item.get("data", {}), Mapping) for item in segments):
        return False
    mentions = [item for item in segments if item.get("type") == "at"]
    self_id = str(event.get_self_id())
    if len(mentions) != 1 or str(mentions[0].get("data", {}).get("qq", "")) != self_id:
        return False
    text = "".join(str(item.get("data", {}).get("text", "")) for item in segments if item.get("type") == "text").strip()
    if text not in COMMANDS:
        return False
    event.stop_event()
    return True
