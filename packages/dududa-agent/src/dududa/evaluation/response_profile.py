from __future__ import annotations

import json
import random
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision, ConversationType, DigestString
from dududa.domain.task import TaskComplexityLevel, TaskReasoningDepth
from dududa.perception.contracts import SocialAction
from dududa.responses.contracts import ResponseProfileSelectionRequest
from dududa.responses.evidence import detect_detail_preference
from dududa.responses.policy import (
    DeterministicResponseProfilePolicy,
    pilot_response_profile_policy_config,
)

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
_SHUFFLE_SEED = 20260809
_FILES = frozenset(
    {"cases.json", "gold.json", "manifest.json", "report.json", "DATA_CARD.md"}
)
_CLAIMS = {
    "dataset_kind": "synthetic",
    "quality_claim": "mechanical_contract_only",
    "human_review_complete": False,
    "real_chinese_quality_claimed": False,
    "persona_style_quality_claimed": False,
    "provider_tokenizer_equivalence_claimed": False,
    "pilot_budgets_calibrated": False,
    "network_allowed": False,
    "real_model_call_count": 0,
    "user_data_record_count": 0,
}
_LIMITS = {
    "short": {
        "visible_token_limit": 128,
        "visible_character_limit": 180,
        "delivery_part_limit": 1,
        "delivery_part_character_limit": 500,
        "generated_token_limit": 128,
    },
    "medium": {
        "visible_token_limit": 512,
        "visible_character_limit": 720,
        "delivery_part_limit": 2,
        "delivery_part_character_limit": 500,
        "generated_token_limit": 512,
    },
    "long": {
        "visible_token_limit": 1536,
        "visible_character_limit": 2400,
        "delivery_part_limit": 5,
        "delivery_part_character_limit": 500,
        "generated_token_limit": 1536,
    },
}


def generate_response_profile_bundle(output_dir: Path | str) -> dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cases = _case_document()
    gold = _gold_document()
    manifest = _manifest(cases, gold)
    _write_json(output / "cases.json", cases)
    _write_json(output / "gold.json", gold)
    _write_json(output / "manifest.json", manifest)
    report = run_response_profile_eval(output)
    _write_json(output / "report.json", report)
    (output / "DATA_CARD.md").write_text(_data_card(), encoding="utf-8")
    return report


def run_response_profile_eval(bundle_dir: Path | str) -> dict[str, object]:
    bundle = Path(bundle_dir)
    cases = _read_json(bundle / "cases.json")
    gold = _read_json(bundle / "gold.json")
    manifest = _read_json(bundle / "manifest.json")
    expected_cases = _case_document()
    expected_gold = _gold_document()
    expected_manifest = _manifest(expected_cases, expected_gold)
    if cases != expected_cases:
        raise RuntimeError("Response Profile Eval cases mismatch")
    if gold != expected_gold:
        raise RuntimeError("Response Profile Eval gold mismatch")
    if manifest != expected_manifest:
        raise RuntimeError("Response Profile Eval manifest mismatch")
    case_rows = list(cases["cases"])
    canonical = _evaluate(case_rows)
    reverse = _evaluate(list(reversed(case_rows)))
    shuffled_rows = list(case_rows)
    random.Random(_SHUFFLE_SEED).shuffle(shuffled_rows)
    shuffled = _evaluate(shuffled_rows)
    return _report(manifest, gold, canonical, reverse, shuffled)


def check_response_profile_bundle(bundle_dir: Path | str) -> dict[str, object]:
    bundle = Path(bundle_dir)
    report = run_response_profile_eval(bundle)
    if _read_json(bundle / "report.json") != report:
        raise RuntimeError("Response Profile Eval report mismatch")
    if {path.name for path in bundle.iterdir() if path.is_file()} != _FILES:
        raise RuntimeError("Response Profile Eval file set mismatch")
    with tempfile.TemporaryDirectory(prefix="dududa-response-profile-eval-") as temp:
        generated = Path(temp)
        generate_response_profile_bundle(generated)
        for name in _FILES:
            if (bundle / name).read_bytes() != (generated / name).read_bytes():
                raise RuntimeError(f"Response Profile Eval artifact drift: {name}")
    return report


def _evaluate(cases: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    predictions: dict[str, dict[str, object]] = {}
    for case in cases:
        case_id = _string(case["case_id"], "case_id")
        revision = _revision("response-profile-policy")
        config = pilot_response_profile_policy_config(revision)
        cap = case["conversation_cap"]
        if cap is not None:
            caps = dict(config.conversation_caps)
            caps[
                ConversationType(
                    _string(case["conversation_type"], "conversation_type")
                )
            ] = _answer_profile(cap)
            config = replace(config, conversation_caps=caps)
        policy = DeterministicResponseProfilePolicy(
            config,
            id_factory=lambda value=case_id: f"plan:{value}",
        )
        message_ref = f"message:{case_id}"
        request = ResponseProfileSelectionRequest(
            schema_version=1,
            selection_id=f"selection:{case_id}",
            actor_digest=DigestString("actor:synthetic"),
            scope_digest=DigestString("scope:synthetic"),
            persona_id="dududa",
            conversation_type=ConversationType(
                _string(case["conversation_type"], "conversation_type")
            ),
            current_message_ref=message_ref,
            complexity_level=TaskComplexityLevel(
                _string(case["complexity"], "complexity")
            ),
            reasoning_depth=TaskReasoningDepth(
                _string(case["reasoning_depth"], "reasoning_depth")
            ),
            expected_tool_steps=_integer(
                case["expected_tool_steps"], "expected_tool_steps"
            ),
            verification_required=_boolean(
                case["verification_required"], "verification_required"
            ),
            social_action=SocialAction(_string(case["social_action"], "social_action")),
            assessment_digest=DigestString(f"assessment:{case_id}"),
            social_decision_digest=DigestString(f"social:{case_id}"),
            detail_evidence=detect_detail_preference(
                message_ref,
                _string(case["text"], "text"),
                detector_revision=_revision("detail-detector"),
            ),
            persistent_preference=None,
            available_generated_tokens=_integer(
                case["available_generated_tokens"],
                "available_generated_tokens",
            ),
            maximum_response_characters=_optional_integer(
                case["maximum_response_characters"],
                "maximum_response_characters",
            ),
            maximum_delivery_parts=_optional_integer(
                case["maximum_delivery_parts"],
                "maximum_delivery_parts",
            ),
        )
        plan = policy.select(request, now=_NOW)
        projection = {
            "case_id": case_id,
            "requested_profile": (
                plan.requested_profile.value
                if plan.requested_profile is not None
                else None
            ),
            "uncapped_profile": plan.uncapped_profile.value,
            "selected_profile": plan.selected_profile.value,
            "visible_token_limit": plan.visible_token_limit,
            "visible_character_limit": plan.visible_character_limit,
            "delivery_part_limit": plan.delivery_part_limit,
            "delivery_part_character_limit": plan.delivery_part_character_limit,
            "generated_token_limit": plan.generated_token_limit,
            "reason_codes": list(plan.reason_codes),
            "selection_fingerprint": str(plan.selection_fingerprint),
        }
        projection["prediction_digest"] = str(
            canonical_digest(projection, domain="eval:response-profile-prediction:v1")
        )
        predictions[case_id] = projection
    return predictions


def _report(
    manifest: dict[str, object],
    gold_document: dict[str, object],
    canonical: dict[str, dict[str, object]],
    reverse: dict[str, dict[str, object]],
    shuffled: dict[str, dict[str, object]],
) -> dict[str, object]:
    gold = {row["case_id"]: row for row in gold_document["records"]}
    mismatches: list[str] = []
    confusion = {profile: {other: 0 for other in _LIMITS} for profile in _LIMITS}
    cross_two = 0
    explicit_total = 0
    explicit_match = 0
    for case_id, expected in gold.items():
        actual = canonical[case_id]
        comparable = {key: actual[key] for key in expected if key != "case_id"}
        expected_values = {
            key: value for key, value in expected.items() if key != "case_id"
        }
        if comparable != expected_values:
            mismatches.append(case_id)
        expected_profile = _string(expected["selected_profile"], "selected_profile")
        actual_profile = _string(actual["selected_profile"], "selected_profile")
        confusion[expected_profile][actual_profile] += 1
        if (
            abs(
                tuple(_LIMITS).index(expected_profile)
                - tuple(_LIMITS).index(actual_profile)
            )
            >= 2
        ):
            cross_two += 1
        if expected["requested_profile"] is not None:
            explicit_total += 1
            if expected["requested_profile"] == actual["requested_profile"]:
                explicit_match += 1
    order_reproducible = canonical == reverse == shuffled
    report: dict[str, object] = {
        "schema_version": 1,
        **_CLAIMS,
        "manifest_digest": manifest["manifest_digest"],
        "case_count": len(gold),
        "matrix_cell_count": 9,
        "profile_confusion": confusion,
        "cross_two_profile_error_count": cross_two,
        "explicit_request_total": explicit_total,
        "explicit_request_satisfied": explicit_match,
        "hard_limit_mismatch_count": len(mismatches),
        "protected_content_eval_opportunity_count": 0,
        "protected_content_drift_count": None,
        "protected_content_invariant_gate": "unit_and_contract_tests",
        "order_reproducible": order_reproducible,
        "mismatch_case_ids": sorted(mismatches),
        "prediction_set_digest": str(
            canonical_digest(
                tuple(canonical[key] for key in sorted(canonical)),
                domain="eval:response-profile-prediction-set:v1",
            )
        ),
        "technical_pass": not mismatches and order_reproducible and cross_two == 0,
        "release_ready": False,
        "external_gates": [
            "human_profile_fit",
            "persona_style_quality",
            "real_provider_tokenizer",
            "pilot_budget_calibration",
            "real_qq_delivery",
        ],
    }
    report["report_digest"] = str(
        canonical_digest(report, domain="eval:response-profile-report:v1")
    )
    return report


def _case_document() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    texts = {
        "short": "请简短回答：解释这个问题。",
        "medium": "请按中等长度回答：解释这个问题。",
        "long": "请详细说明一下这个问题。",
    }
    depths = {"low": "shallow", "medium": "multi_step", "high": "deep"}
    for complexity in ("low", "medium", "high"):
        for profile in ("short", "medium", "long"):
            rows.append(
                _case(
                    f"matrix-{complexity}-{profile}",
                    texts[profile],
                    complexity,
                    depths[complexity],
                )
            )
    rows.extend(
        (
            _case("default-low", "Explain the topic.", "low", "shallow"),
            _case("default-medium", "Explain the topic.", "medium", "multi_step"),
            _case("default-high", "Explain the topic.", "high", "deep"),
            _case(
                "conflicting-medium",
                "请简短回答，但也请详细说明一下。",
                "medium",
                "multi_step",
            ),
            _case(
                "group-cap",
                texts["long"],
                "high",
                "deep",
                conversation_type="group",
                conversation_cap="medium",
            ),
            _case(
                "runtime-cap",
                texts["long"],
                "high",
                "deep",
                available_generated_tokens=300,
                maximum_response_characters=400,
                maximum_delivery_parts=1,
            ),
            _case(
                "clarification",
                texts["long"],
                "high",
                "deep",
                social_action="ask_clarification",
            ),
            _case(
                "tool-medium",
                "Use the approved course lookup.",
                "low",
                "shallow",
                social_action="use_tools",
                expected_tool_steps=1,
            ),
        )
    )
    return {"schema_version": 1, "cases": rows}


def _case(
    case_id: str,
    text: str,
    complexity: str,
    reasoning_depth: str,
    *,
    conversation_type: str = "private",
    conversation_cap: str | None = None,
    social_action: str = "direct_reply",
    expected_tool_steps: int = 0,
    available_generated_tokens: int = 2000,
    maximum_response_characters: int | None = 3000,
    maximum_delivery_parts: int | None = 5,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "text": text,
        "complexity": complexity,
        "reasoning_depth": reasoning_depth,
        "social_action": social_action,
        "expected_tool_steps": expected_tool_steps,
        "verification_required": complexity == "high",
        "conversation_type": conversation_type,
        "conversation_cap": conversation_cap,
        "available_generated_tokens": available_generated_tokens,
        "maximum_response_characters": maximum_response_characters,
        "maximum_delivery_parts": maximum_delivery_parts,
    }


def _gold_document() -> dict[str, object]:
    records: list[dict[str, object]] = []
    for complexity in ("low", "medium", "high"):
        for profile in ("short", "medium", "long"):
            records.append(
                _gold(
                    f"matrix-{complexity}-{profile}",
                    profile,
                    profile,
                    profile,
                    (
                        "current_message_preference_selected",
                        f"explicit_{profile}_requested",
                    ),
                )
            )
    records.extend(
        (
            _gold(
                "default-low",
                None,
                "short",
                "short",
                (
                    "configured_complexity_default_selected",
                    "no_explicit_detail_preference",
                ),
            ),
            _gold(
                "default-medium",
                None,
                "medium",
                "medium",
                ("no_explicit_detail_preference", "task_requires_medium_response"),
            ),
            _gold(
                "default-high",
                None,
                "long",
                "long",
                ("no_explicit_detail_preference", "task_requires_long_response"),
            ),
            _gold(
                "conflicting-medium",
                None,
                "medium",
                "medium",
                ("conflicting_detail_preferences", "task_requires_medium_response"),
            ),
            _gold(
                "group-cap",
                "long",
                "long",
                "medium",
                (
                    "conversation_profile_cap_applied",
                    "current_message_preference_selected",
                    "explicit_long_requested",
                ),
            ),
            _gold(
                "runtime-cap",
                "long",
                "long",
                "long",
                (
                    "current_message_preference_selected",
                    "delivery_part_cap_applied",
                    "explicit_long_requested",
                    "response_character_cap_applied",
                    "runtime_generated_token_cap_applied",
                ),
                limits={
                    "visible_token_limit": 300,
                    "visible_character_limit": 400,
                    "delivery_part_limit": 1,
                    "delivery_part_character_limit": 500,
                    "generated_token_limit": 300,
                },
            ),
            _gold(
                "clarification",
                "long",
                "short",
                "short",
                (
                    "clarification_short_selected",
                    "detail_preference_not_applicable_to_clarification",
                    "explicit_long_requested",
                ),
            ),
            _gold(
                "tool-medium",
                None,
                "medium",
                "medium",
                ("no_explicit_detail_preference", "task_requires_medium_response"),
            ),
        )
    )
    return {"schema_version": 1, "records": records}


def _gold(
    case_id: str,
    requested: str | None,
    uncapped: str,
    selected: str,
    reason_codes: tuple[str, ...],
    *,
    limits: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "requested_profile": requested,
        "uncapped_profile": uncapped,
        "selected_profile": selected,
        **(limits or _LIMITS[selected]),
        "reason_codes": list(reason_codes),
    }


def _manifest(cases: dict[str, object], gold: dict[str, object]) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": 1,
        **_CLAIMS,
        "generation_revision": "response-profile-eval-v1",
        "fixed_time": _NOW.isoformat(),
        "fixed_shuffle_seed": _SHUFFLE_SEED,
        "case_count": len(cases["cases"]),
        "matrix_cell_count": 9,
        "cases_digest": str(
            canonical_digest(cases, domain="eval:response-profile-case-set:v1")
        ),
        "gold_digest": str(
            canonical_digest(gold, domain="eval:response-profile-gold-set:v1")
        ),
    }
    manifest["dataset_digest"] = str(
        canonical_digest(
            {"cases": cases, "gold": gold},
            domain="eval:response-profile-dataset:v1",
        )
    )
    manifest["manifest_digest"] = str(
        canonical_digest(manifest, domain="eval:response-profile-manifest:v1")
    )
    return manifest


def _revision(name: str) -> ComponentRevision:
    return ComponentRevision(
        name, "1.0.0", "config-v1", DigestString(f"artifact:{name}")
    )


def _answer_profile(value: object):
    from dududa.responses.contracts import AnswerProfile

    return AnswerProfile(_string(value, "answer_profile"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as failure:
        raise RuntimeError(
            f"Response Profile Eval read failed: {path.name}"
        ) from failure
    if not payload or len(payload) > 1_048_576:
        raise RuntimeError(f"Response Profile Eval invalid size: {path.name}")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as failure:
        raise RuntimeError(
            f"Response Profile Eval invalid JSON: {path.name}"
        ) from failure
    if not isinstance(value, dict):
        raise RuntimeError(  # noqa: TRY004 - bundle failures share one public type.
            f"Response Profile Eval root is not an object: {path.name}"
        )
    return value


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(value)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Response Profile Eval invalid string: {field}")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise RuntimeError(f"Response Profile Eval invalid integer: {field}")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    return None if value is None else _integer(value, field)


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise RuntimeError(f"Response Profile Eval invalid boolean: {field}")
    return value


def _data_card() -> str:
    return """# Response Profile Eval v1

This frozen dataset contains only synthetic messages. It verifies deterministic
SHORT/MEDIUM/LONG selection, hard-limit projection and order reproducibility.
It does not establish human profile fit, Persona style quality, real Chinese
quality, Provider tokenizer equivalence, calibrated budgets or QQ delivery quality.

Network access, real model calls and user records are all zero.
"""


__all__ = [
    "check_response_profile_bundle",
    "generate_response_profile_bundle",
    "run_response_profile_eval",
]
