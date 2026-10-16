from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Callable, cast

from dududa.contracts.canonical import canonical_digest, canonical_json_bytes
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    JsonValue,
    PrivacyLevel,
    freeze_json,
)
from dududa.perception.contracts import (
    PerceptionContext,
    PerceptionIdentity,
    PerceptionLimits,
    PerceptionMessage,
    ReferenceKind,
)
from dududa.perception.digests import perception_context_digest
from dududa.perception.schema import decode_model_projection
from dududa.perception.semantic import (
    ReferenceLinkSource,
    SemanticDecisionAction,
    VersionedModelPerceptionProjection,
    normalized_text,
)
from dududa.perception.semantic_schema import (
    decode_versioned_model_projection,
    encode_versioned_model_projection,
    model_projection_v2_schema,
    model_projection_v2_schema_ref,
)
from dududa.perception.semantic_validation import (
    validate_versioned_model_projection,
)


_BUNDLE_VERSION = "s09-semantic-schema-pilot-v2"
_REQUIRED_TAGS = frozenset(
    {
        "3_turn",
        "6_turn",
        "12_turn",
        "ambiguity",
        "chinese",
        "decomposed_unicode",
        "emoji",
        "linguistic_pronoun",
        "missing_slot",
        "oos",
        "structural_mention",
        "structural_reply",
    }
)


SchemaValidator = Callable[[object, object], None]


def run_semantic_schema_pilot(
    bundle: Path,
    *,
    validate_schema: SchemaValidator,
) -> dict[str, JsonValue]:
    document = _load_json(bundle / "cases.json")
    root = _object(document, "cases")
    _exact_keys(
        root,
        {"schema_version", "bundle_version", "quality_claim", "cases"},
        "cases",
    )
    if _integer(root["schema_version"], "schema_version") != 2:
        raise RuntimeError("unsupported semantic pilot schema version")
    if _string(root["bundle_version"], "bundle_version") != _BUNDLE_VERSION:
        raise RuntimeError("unexpected semantic pilot bundle version")
    if _string(root["quality_claim"], "quality_claim") != "schema_only":
        raise RuntimeError("semantic pilot must not claim real quality")

    cases = _sequence(root["cases"], "cases")
    if not cases:
        raise RuntimeError("semantic pilot has no cases")
    limits = _pilot_limits()
    schema_document = json.loads(
        canonical_json_bytes(model_projection_v2_schema(limits)).decode("utf-8")
    )
    seen_case_ids: set[str] = set()
    covered_tags: set[str] = set()
    turn_counts: dict[str, int] = {}
    normalized_input_case_count = 0
    decision_counts = {"accept": 0, "clarify": 0, "abstain": 0}

    for raw_case in cases:
        case = _object(raw_case, "case")
        _exact_keys(
            case,
            {"case_id", "tags", "context", "projection", "expected"},
            "case",
        )
        case_id = _string(case["case_id"], "case_id")
        if case_id in seen_case_ids:
            raise RuntimeError(f"duplicate semantic pilot case: {case_id}")
        seen_case_ids.add(case_id)

        tags = {_string(item, "tag") for item in _sequence(case["tags"], "tags")}
        context = _decode_context(case_id, case["context"], limits)
        turn_count = len(context.messages)
        if turn_count not in {3, 6, 12} or f"{turn_count}_turn" not in tags:
            raise RuntimeError(f"invalid semantic pilot window: {case_id}")
        turn_counts[str(turn_count)] = turn_counts.get(str(turn_count), 0) + 1
        if any(
            message.text != normalized_text(message.text)
            for message in context.messages
        ):
            normalized_input_case_count += 1

        payload = _object(case["projection"], "projection")
        validate_schema(
            schema_document,
            json.loads(canonical_json_bytes(payload).decode("utf-8")),
        )
        revisions = _pilot_revisions()
        projection = decode_versioned_model_projection(
            freeze_json(payload),
            context_digest=perception_context_digest(context),
            projection_id=f"projection:{case_id}",
            request_fingerprint=DigestString(f"request:{case_id}"),
            route_receipt_digest=DigestString(f"route:{case_id}"),
            component_revision=revisions["model"],
            semantic_component_revision=revisions["semantic"],
            taxonomy_revision=revisions["taxonomy"],
            calibration_revision=revisions["calibration"],
            threshold_policy_revision=revisions["threshold"],
        )
        validate_versioned_model_projection(context, projection)
        derived_tags = _derived_tags(context, projection)
        if not tags <= derived_tags:
            raise RuntimeError(
                f"semantic pilot tags lack matching facts: {case_id}: "
                f"{sorted(tags - derived_tags)}"
            )
        covered_tags.update(tags)

        if canonical_json_bytes(
            encode_versioned_model_projection(projection)
        ) != canonical_json_bytes(payload):
            raise RuntimeError(f"non-canonical semantic round trip: {case_id}")
        legacy_payload = dict(payload)
        legacy_payload.pop("semantic")
        legacy_payload["schema_version"] = 1
        legacy = decode_model_projection(
            freeze_json(legacy_payload),
            context_digest=perception_context_digest(context),
            projection_id=f"projection:{case_id}",
            request_fingerprint=DigestString(f"request:{case_id}"),
            route_receipt_digest=DigestString(f"route:{case_id}"),
            component_revision=revisions["model"],
        )
        if projection.base_projection != legacy:
            raise RuntimeError(f"non-exact v1 downgrade: {case_id}")

        expected = _object(case["expected"], "expected")
        _exact_keys(expected, {"decision"}, "expected")
        expected_decision = _string(expected["decision"], "expected_decision")
        semantic = projection.semantic
        if semantic is None or semantic.decision.action.value != expected_decision:
            raise RuntimeError(f"unexpected semantic decision: {case_id}")
        decision_counts[expected_decision] += 1

    missing_tags = _REQUIRED_TAGS - covered_tags
    if missing_tags:
        raise RuntimeError(f"semantic pilot coverage missing: {sorted(missing_tags)}")
    if normalized_input_case_count < 1:
        raise RuntimeError("semantic pilot lacks normalized Unicode input")

    cases_digest = canonical_digest(
        root,
        domain="eval:perception-semantic-schema-pilot:v2",
    )
    schema_ref = model_projection_v2_schema_ref(limits)
    return cast(
        dict[str, JsonValue],
        {
            "schema_version": 2,
            "bundle_version": _BUNDLE_VERSION,
            "dataset_kind": "synthetic",
            "quality_claim": "schema_only",
            "technical_pass": True,
            "release_ready": False,
            "real_chinese_quality_claimed": False,
            "human_review_complete": False,
            "real_model_call_count": 0,
            "user_data_record_count": 0,
            "case_count": len(cases),
            "cases_digest": str(cases_digest),
            "schema_ref": {
                "schema_id": schema_ref.schema_id,
                "schema_version": schema_ref.schema_version,
                "digest": str(schema_ref.digest),
            },
            "schema_valid_count": len(cases),
            "whole_envelope_valid_count": len(cases),
            "exact_v1_downgrade_count": len(cases),
            "canonical_round_trip_count": len(cases),
            "normalized_input_case_count": normalized_input_case_count,
            "turn_counts": dict(sorted(turn_counts.items())),
            "decision_counts": decision_counts,
            "coverage": {tag: tag in covered_tags for tag in sorted(_REQUIRED_TAGS)},
            "external_gates": (
                "authorized_conversation_cluster_data",
                "independent_annotation_and_adjudication",
                "held_out_chinese_quality_evaluation",
                "calibrated_product_thresholds",
            ),
        },
    )


def check_semantic_schema_pilot(
    bundle: Path,
    *,
    validate_schema: SchemaValidator,
) -> dict[str, JsonValue]:
    actual = run_semantic_schema_pilot(
        bundle,
        validate_schema=validate_schema,
    )
    committed = _object(_load_json(bundle / "report.json"), "report")
    if actual != committed:
        raise RuntimeError("committed semantic pilot report is stale")
    return actual


def _decode_context(
    case_id: str,
    value: JsonValue,
    limits: PerceptionLimits,
) -> PerceptionContext:
    root = _object(value, "context")
    _exact_keys(
        root,
        {
            "conversation_type",
            "identities",
            "messages",
            "current_message_ref",
            "bot_identity_ref",
        },
        "context",
    )
    identities = []
    for raw_identity in _sequence(root["identities"], "identities"):
        identity = _object(raw_identity, "identity")
        _exact_keys(identity, {"identity_ref", "is_bot"}, "identity")
        is_bot = identity["is_bot"]
        if type(is_bot) is not bool:
            raise RuntimeError("invalid synthetic identity bot flag")
        identities.append(
            PerceptionIdentity(
                1,
                _string(identity["identity_ref"], "identity_ref"),
                is_bot,
            )
        )

    messages = []
    for raw_message in _sequence(root["messages"], "messages"):
        message = _object(raw_message, "message")
        _exact_keys(
            message,
            {
                "message_ref",
                "author_identity_ref",
                "text",
                "reply_to_message_ref",
                "mentioned_identity_refs",
                "is_bot_authored",
            },
            "message",
        )
        reply = message["reply_to_message_ref"]
        if reply is not None:
            reply = _string(reply, "reply_to_message_ref")
        is_bot_authored = message["is_bot_authored"]
        if type(is_bot_authored) is not bool:
            raise RuntimeError("invalid synthetic message bot flag")
        messages.append(
            PerceptionMessage(
                1,
                _string(message["message_ref"], "message_ref"),
                _string(message["author_identity_ref"], "author_identity_ref"),
                _string(message["text"], "message_text"),
                reply,
                tuple(
                    _string(item, "mentioned_identity_ref")
                    for item in _sequence(
                        message["mentioned_identity_refs"],
                        "mentioned_identity_refs",
                    )
                ),
                is_bot_authored,
            )
        )

    try:
        conversation_type = ConversationType(
            _string(root["conversation_type"], "conversation_type")
        )
    except ValueError as exc:
        raise RuntimeError("invalid synthetic conversation type") from exc
    return PerceptionContext(
        schema_version=1,
        context_id=f"context:{case_id}",
        scope_digest=canonical_digest(
            {"case_id": case_id},
            domain="eval:perception-semantic-scope:v1",
        ),
        conversation_type=conversation_type,
        identities=tuple(identities),
        messages=tuple(messages),
        current_message_ref=_string(
            root["current_message_ref"],
            "current_message_ref",
        ),
        bot_identity_ref=_string(root["bot_identity_ref"], "bot_identity_ref"),
        limits=limits,
        available_capability_categories=(),
        degraded_components=(),
        content_input_tokens_upper_bound=max(
            1,
            sum(len(message.text) for message in messages),
        ),
        data_classification=PrivacyLevel.CONVERSATION,
    )


def _pilot_limits() -> PerceptionLimits:
    return PerceptionLimits(
        schema_version=1,
        max_messages=16,
        max_identities=16,
        max_characters_per_message=1_000,
        max_total_characters=8_000,
        max_capability_categories=8,
        max_degraded_components=8,
        max_candidates_per_kind=16,
        max_evidence_refs_per_item=8,
    )


def _derived_tags(
    context: PerceptionContext,
    projection: VersionedModelPerceptionProjection,
) -> set[str]:
    if not isinstance(projection, VersionedModelPerceptionProjection):
        raise RuntimeError("invalid semantic pilot projection")
    semantic = projection.semantic
    if semantic is None:
        raise RuntimeError("semantic pilot unexpectedly decoded v1")

    tags = {f"{len(context.messages)}_turn"}
    if any(
        "\u4e00" <= character <= "\u9fff"
        for message in context.messages
        for character in message.text
    ):
        tags.add("chinese")
    if any(
        message.text != normalized_text(message.text) for message in context.messages
    ):
        tags.add("decomposed_unicode")
    if any(
        ord(character) > 0xFFFF
        for message in context.messages
        for character in message.text
    ):
        tags.add("emoji")

    messages = {message.message_ref: message for message in context.messages}
    for reference in semantic.references:
        source = messages[reference.mention_span.message_ref]
        if (
            reference.link_source is ReferenceLinkSource.STRUCTURAL
            and reference.kind is ReferenceKind.MESSAGE
            and source.reply_to_message_ref == reference.target_ref
        ):
            tags.add("structural_reply")
        if (
            reference.link_source is ReferenceLinkSource.STRUCTURAL
            and reference.kind is ReferenceKind.IDENTITY
            and reference.target_ref in source.mentioned_identity_refs
        ):
            tags.add("structural_mention")
        if (
            reference.link_source is ReferenceLinkSource.LINGUISTIC
            and reference.mention_span.surface in {"它", "他", "她", "这个", "那个"}
        ):
            tags.add("linguistic_pronoun")

    if projection.base_projection.ambiguities:
        tags.add("ambiguity")
    if semantic.decision.action is SemanticDecisionAction.CLARIFY and any(
        not intent.slot_entity_refs for intent in semantic.intents
    ):
        tags.add("missing_slot")
    if (
        semantic.decision.action is SemanticDecisionAction.ABSTAIN
        and not semantic.intents
    ):
        tags.add("oos")
    return tags


def _pilot_revisions() -> dict[str, ComponentRevision]:
    return {
        key: ComponentRevision(
            component_id=f"semantic-pilot-{key}",
            implementation_version="1.0.0",
            config_revision=_BUNDLE_VERSION,
            artifact_digest=DigestString(f"synthetic:{key}"),
        )
        for key in ("model", "semantic", "taxonomy", "calibration", "threshold")
    }


def _load_json(path: Path) -> JsonValue:
    try:
        return freeze_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"invalid semantic pilot artifact: {path}") from exc


def _object(value: JsonValue, field_name: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"invalid semantic pilot object: {field_name}")
    return dict(value)


def _sequence(value: JsonValue, field_name: str) -> tuple[JsonValue, ...]:
    if not isinstance(value, tuple):
        raise RuntimeError(f"invalid semantic pilot sequence: {field_name}")
    return value


def _string(value: JsonValue, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"invalid semantic pilot string: {field_name}")
    return value


def _integer(value: JsonValue, field_name: str) -> int:
    if type(value) is not int:
        raise RuntimeError(f"invalid semantic pilot integer: {field_name}")
    return value


def _exact_keys(
    value: dict[str, JsonValue],
    expected: set[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise RuntimeError(f"invalid semantic pilot keys: {field_name}")
