from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from dududa.domain.primitives import ConversationType
from dududa.persona.contracts import (
    PersonaChannelStyle,
    PersonaDefinition,
    PersonaRendererMode,
    PersonaSentenceLength,
    PersonaVoiceRules,
    build_persona_definition,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
ASSET_ROOT = Path(__file__).parents[3] / "configs" / "personas" / "registry-v1"


def definition(
    persona_id: str = "dududa",
    version: str = "1.0.0",
) -> PersonaDefinition:
    channel_rules = {
        kind: PersonaChannelStyle(
            schema_version=1,
            tone_tags=("clear", kind.value),
            emoji_budget=0,
            prefer_short_sentences=kind is ConversationType.GROUP,
        )
        for kind in ConversationType
    }
    return build_persona_definition(
        persona_id=persona_id,
        version=version,
        display_name=persona_id.title(),
        default_locale="zh-CN",
        voice=PersonaVoiceRules(
            schema_version=1,
            tone_tags=("clear", "bounded"),
            sentence_length=PersonaSentenceLength.BALANCED,
            preferred_language="zh-CN",
            emoji_budget=0,
            avoid_patterns=("role_lore",),
            technical_style="conclusion_then_steps",
            uncertainty_style="state_limits",
            instructions=("Preserve facts.",),
        ),
        channel_rules=channel_rules,
        renderer_mode=PersonaRendererMode.DETERMINISTIC,
        safety_note_ids=("baseline-content-safety",),
    )
