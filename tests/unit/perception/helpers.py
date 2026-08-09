from __future__ import annotations

from datetime import datetime, timezone

from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    PrivacyLevel,
)
from dududa.perception.contracts import (
    PerceptionContext,
    PerceptionIdentity,
    PerceptionLimits,
    PerceptionMessage,
)
from dududa.perception.semantic import semantic_text_digest


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def revision(component_id: str) -> ComponentRevision:
    return ComponentRevision(
        component_id=component_id,
        implementation_version="1.0.0",
        config_revision="config-v1",
        artifact_digest=DigestString(f"artifact-{component_id}"),
    )


def limits(**overrides: int) -> PerceptionLimits:
    values = {
        "schema_version": 1,
        "max_messages": 16,
        "max_identities": 16,
        "max_characters_per_message": 1_000,
        "max_total_characters": 8_000,
        "max_capability_categories": 8,
        "max_degraded_components": 8,
        "max_candidates_per_kind": 16,
        "max_evidence_refs_per_item": 8,
    }
    values.update(overrides)
    return PerceptionLimits(**values)


def context(**overrides: object) -> PerceptionContext:
    values: dict[str, object] = {
        "schema_version": 1,
        "context_id": "context-1",
        "scope_digest": DigestString("scope-digest"),
        "conversation_type": ConversationType.GROUP,
        "identities": (
            PerceptionIdentity(1, "identity:bot", True),
            PerceptionIdentity(1, "identity:user", False),
        ),
        "messages": (
            PerceptionMessage(
                1,
                "message:bot",
                "identity:bot",
                "Earlier response",
                None,
                (),
                True,
            ),
            PerceptionMessage(
                1,
                "message:current",
                "identity:user",
                "Can you compare these constraints?",
                "message:bot",
                ("identity:bot",),
                False,
            ),
        ),
        "current_message_ref": "message:current",
        "bot_identity_ref": "identity:bot",
        "limits": limits(),
        "available_capability_categories": ("search", "code"),
        "degraded_components": (),
        "content_input_tokens_upper_bound": 128,
        "data_classification": PrivacyLevel.CONVERSATION,
    }
    values.update(overrides)
    return PerceptionContext(**values)


def model_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "schema_version": 1,
        "target_identity_refs": ["identity:user"],
        "speech_acts": ["question", "request"],
        "topics": [
            {
                "topic_id": "topic:constraints",
                "label": "constraint comparison",
                "confidence": 0.9,
                "evidence_refs": ["message:current"],
            }
        ],
        "intents": [
            {
                "intent_id": "general.compare",
                "confidence": 0.9,
                "evidence_refs": ["message:current"],
            }
        ],
        "entities": [],
        "references": [
            {
                "reference_id": "reference:reply",
                "kind": "message",
                "target_ref": "message:bot",
                "confidence": 1.0,
                "evidence_refs": ["message:current"],
            }
        ],
        "ambiguities": [],
        "need_tools": False,
        "capability_categories": [],
        "task_kind": "comparison",
        "reasoning_depth": "multi_step",
        "expected_tool_steps": 0,
        "verification_required": True,
        "complexity_signals": [
            {
                "code": "independent_verification",
                "confidence": 0.85,
                "evidence_refs": ["message:current"],
            },
            {
                "code": "multi_constraint_synthesis",
                "confidence": 0.9,
                "evidence_refs": ["message:current"],
            },
        ],
        "confidence": 0.85,
    }
    values.update(overrides)
    return values


def model_payload_v2(**overrides: object) -> dict[str, object]:
    current = context().current_message
    values = model_payload(schema_version=2)
    values["semantic"] = {
        "schema_version": 2,
        "entities": [],
        "references": [
            {
                "reference_id": "reference:reply",
                "kind": "message",
                "mention_span": {
                    "message_ref": current.message_ref,
                    "start": 16,
                    "end": 21,
                    "surface": "these",
                    "text_digest": str(semantic_text_digest(current.text)),
                },
                "target_ref": "message:bot",
                "link_source": "structural",
                "confidence": 1.0,
                "evidence_refs": [current.message_ref],
            }
        ],
        "intents": [
            {
                "intent_id": "general.compare",
                "slot_entity_refs": [],
                "confidence": 0.9,
                "evidence_refs": [current.message_ref],
            }
        ],
        "decision": {
            "action": "accept",
            "reason_codes": ["synthetic_schema_accept"],
        },
    }
    values.update(overrides)
    return values
