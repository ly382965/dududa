from __future__ import annotations

import json
import random
import tempfile
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Any

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString
from dududa.errors import validation_error

from .contracts import (
    BanditActionProbability,
    BanditFeedbackDisposition,
    BanditOpePolicy,
    BanditOpeReport,
    BanditOpeSample,
    BanditRoundingMode,
)
from .digests import bandit_ope_policy_digest, bandit_ope_sample_set_digest
from .validation import require_valid_ope_samples

_SHUFFLE_SEED = 20260810
_FILES = frozenset({"samples.json", "manifest.json", "report.json", "DATA_CARD.md"})
_CLAIMS = {
    "dataset_kind": "synthetic",
    "quality_claim": "offline_estimator_arithmetic_only",
    "network_allowed": False,
    "real_endpoint_claimed": False,
    "real_model_call_count": 0,
    "user_data_record_count": 0,
    "policy_training_performed": False,
    "production_hook_present": False,
    "release_ready": False,
}
_EXPECTED = {
    "ips": Decimal("0.812500000000"),
    "snips": Decimal("0.650000000000"),
    "doubly_robust": Decimal("0.787500000000"),
    "effective_sample_size": Decimal("3.846153846154"),
}


def evaluate_ope(
    samples: tuple[BanditOpeSample, ...],
    policy: BanditOpePolicy,
) -> BanditOpeReport:
    validation = require_valid_ope_samples(samples, policy)
    ordered = tuple(sorted(samples, key=lambda item: item.sample_id))
    rounding = _rounding(policy.rounding_mode)
    quantum = Decimal(1).scaleb(-policy.decimal_places)
    with localcontext() as context:
        context.prec = max(64, policy.decimal_places * 4 + 16)
        context.rounding = rounding
        weights = tuple(
            sample.evaluation_probability / sample.behavior_propensity
            for sample in ordered
        )
        weight_sum = sum(weights, Decimal(0))
        if weight_sum == 0:
            raise validation_error("bandit_snips_zero_denominator")
        weighted_reward = sum(
            (
                weight * _required(sample.reward, "reward")
                for sample, weight in zip(ordered, weights)
            ),
            Decimal(0),
        )
        count = Decimal(len(ordered))
        ips = weighted_reward / count
        snips = weighted_reward / weight_sum
        doubly_robust = (
            sum(
                (
                    _required(
                        sample.evaluation_expected_prediction,
                        "evaluation_expected_prediction",
                    )
                    + weight
                    * (
                        _required(sample.reward, "reward")
                        - _required(
                            sample.logged_action_prediction,
                            "logged_action_prediction",
                        )
                    )
                    for sample, weight in zip(ordered, weights)
                ),
                Decimal(0),
            )
            / count
        )
        squared_weight_sum = sum((weight * weight for weight in weights), Decimal(0))
        if squared_weight_sum == 0:
            raise validation_error("bandit_ess_zero_denominator")
        ess = (weight_sum * weight_sum) / squared_weight_sum
        values = {
            "support_coverage": validation.support_coverage,
            "reward_coverage": validation.reward_coverage,
            "minimum_behavior_propensity": min(
                item.behavior_propensity for item in ordered
            ),
            "maximum_importance_weight": max(weights),
            "ips": ips,
            "snips": snips,
            "doubly_robust": doubly_robust,
            "effective_sample_size": ess,
        }
        rounded = {
            key: value.quantize(quantum, rounding=rounding)
            for key, value in values.items()
        }
    return BanditOpeReport(
        schema_version=1,
        policy_id=policy.policy_id,
        policy_revision=policy.policy_revision,
        policy_digest=bandit_ope_policy_digest(policy),
        sample_set_digest=bandit_ope_sample_set_digest(ordered),
        sample_count=len(ordered),
        **rounded,
    )


def generate_bandit_offline_bundle(output_dir: Path | str) -> dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    samples = _samples_document()
    manifest = _manifest(samples)
    _write_json(output / "samples.json", samples)
    _write_json(output / "manifest.json", manifest)
    report = run_bandit_offline_eval(output)
    _write_json(output / "report.json", report)
    (output / "DATA_CARD.md").write_text(_data_card(), encoding="utf-8")
    return report


def run_bandit_offline_eval(bundle_dir: Path | str) -> dict[str, object]:
    bundle = Path(bundle_dir)
    samples_document = _read_json(bundle / "samples.json")
    manifest = _read_json(bundle / "manifest.json")
    expected_samples = _samples_document()
    expected_manifest = _manifest(expected_samples)
    if samples_document != expected_samples:
        raise RuntimeError("Bandit offline samples mismatch")
    if manifest != expected_manifest:
        raise RuntimeError("Bandit offline manifest mismatch")
    samples = _parse_samples(samples_document)
    policy = _policy()
    normal = evaluate_ope(samples, policy)
    reverse = evaluate_ope(tuple(reversed(samples)), policy)
    shuffled_values = list(samples)
    random.Random(_SHUFFLE_SEED).shuffle(shuffled_values)
    shuffled = evaluate_ope(tuple(shuffled_values), policy)
    order_reproducible = normal == reverse == shuffled
    technical_pass = order_reproducible and all(
        getattr(normal, field_name) == expected
        for field_name, expected in _EXPECTED.items()
    )
    report: dict[str, object] = {
        "schema_version": 1,
        **_CLAIMS,
        "manifest_digest": manifest["manifest_digest"],
        "policy_digest": str(normal.policy_digest),
        "sample_set_digest": str(normal.sample_set_digest),
        "sample_count": normal.sample_count,
        "support_coverage": _decimal_text(normal.support_coverage, policy),
        "reward_coverage": _decimal_text(normal.reward_coverage, policy),
        "minimum_behavior_propensity": _decimal_text(
            normal.minimum_behavior_propensity,
            policy,
        ),
        "maximum_importance_weight": _decimal_text(
            normal.maximum_importance_weight,
            policy,
        ),
        "ips": _decimal_text(normal.ips, policy),
        "snips": _decimal_text(normal.snips, policy),
        "doubly_robust": _decimal_text(normal.doubly_robust, policy),
        "effective_sample_size": _decimal_text(
            normal.effective_sample_size,
            policy,
        ),
        "order_reproducible": order_reproducible,
        "technical_pass": technical_pass,
        "offending_sample_ids": [],
    }
    report["report_digest"] = str(
        canonical_digest(report, domain="eval:bandit-offline-report:v1")
    )
    return report


def check_bandit_offline_bundle(bundle_dir: Path | str) -> dict[str, object]:
    bundle = Path(bundle_dir)
    report = run_bandit_offline_eval(bundle)
    if _read_json(bundle / "report.json") != report:
        raise RuntimeError("Bandit offline report mismatch")
    if {path.name for path in bundle.iterdir() if path.is_file()} != _FILES:
        raise RuntimeError("Bandit offline file set mismatch")
    with tempfile.TemporaryDirectory(prefix="dududa-bandit-offline-") as temp:
        generated = Path(temp)
        generate_bandit_offline_bundle(generated)
        for name in _FILES:
            if (bundle / name).read_bytes() != (generated / name).read_bytes():
                raise RuntimeError(f"Bandit offline artifact drift: {name}")
    return report


def _policy() -> BanditOpePolicy:
    return BanditOpePolicy(
        schema_version=1,
        policy_id="synthetic-ope-v1",
        policy_revision="2026-08-10",
        minimum_behavior_propensity=Decimal("0.10"),
        maximum_importance_weight=Decimal(10),
        decimal_places=12,
        rounding_mode=BanditRoundingMode.HALF_EVEN,
    )


def _samples_document() -> dict[str, object]:
    rows = (
        _sample_row(
            "sample-1", "decision-1", "action-a", "0.5", "0.75", "1", "0.6", "0.7"
        ),
        _sample_row(
            "sample-2", "decision-2", "action-b", "0.25", "0.25", "0", "0.2", "0.3"
        ),
        _sample_row(
            "sample-3", "decision-3", "action-a", "0.5", "0.75", "0.5", "0.4", "0.5"
        ),
        _sample_row(
            "sample-4", "decision-4", "action-b", "0.25", "0.25", "1", "0.7", "0.8"
        ),
    )
    return {"schema_version": 1, "samples": list(rows)}


def _sample_row(
    sample_id: str,
    decision_id: str,
    action_id: str,
    behavior: str,
    evaluation: str,
    reward: str,
    logged_prediction: str,
    evaluation_prediction: str,
) -> dict[str, object]:
    behavior_a = "0.5" if behavior == "0.5" else "0.75"
    evaluation_a = "0.75"
    return {
        "schema_version": 1,
        "sample_id": sample_id,
        "decision_id": decision_id,
        "decision_digest": f"synthetic:{decision_id}:digest",
        "action_id": action_id,
        "feedback_disposition": "observed",
        "behavior_distribution": [
            {"action_id": "action-a", "probability": behavior_a},
            {
                "action_id": "action-b",
                "probability": str(Decimal(1) - Decimal(behavior_a)),
            },
        ],
        "evaluation_distribution": [
            {"action_id": "action-a", "probability": evaluation_a},
            {"action_id": "action-b", "probability": "0.25"},
        ],
        "behavior_propensity": behavior,
        "evaluation_probability": evaluation,
        "reward": reward,
        "logged_action_prediction": logged_prediction,
        "evaluation_expected_prediction": evaluation_prediction,
    }


def _parse_samples(document: dict[str, Any]) -> tuple[BanditOpeSample, ...]:
    rows = document.get("samples")
    if not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004 - bundle failures share one public type.
            "Bandit offline samples must be a list"
        )
    return tuple(
        BanditOpeSample(
            schema_version=_integer(row["schema_version"], "schema_version"),
            sample_id=_string(row["sample_id"], "sample_id"),
            decision_id=_string(row["decision_id"], "decision_id"),
            decision_digest=DigestString(
                _string(row["decision_digest"], "decision_digest")
            ),
            action_id=_string(row["action_id"], "action_id"),
            feedback_disposition=BanditFeedbackDisposition(
                _string(row["feedback_disposition"], "feedback_disposition")
            ),
            behavior_distribution=_distribution(row["behavior_distribution"]),
            evaluation_distribution=_distribution(row["evaluation_distribution"]),
            behavior_propensity=_decimal(
                row["behavior_propensity"],
                "behavior_propensity",
            ),
            evaluation_probability=_decimal(
                row["evaluation_probability"],
                "evaluation_probability",
            ),
            reward=_decimal(row["reward"], "reward"),
            logged_action_prediction=_decimal(
                row["logged_action_prediction"],
                "logged_action_prediction",
            ),
            evaluation_expected_prediction=_decimal(
                row["evaluation_expected_prediction"],
                "evaluation_expected_prediction",
            ),
        )
        for row in rows
        if isinstance(row, dict)
    )


def _distribution(value: object) -> tuple[BanditActionProbability, ...]:
    if not isinstance(value, list):
        raise RuntimeError(  # noqa: TRY004 - bundle failures share one public type.
            "Bandit offline distribution must be a list"
        )
    rows: list[BanditActionProbability] = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeError(  # noqa: TRY004 - bundle failures share one public type.
                "Bandit offline distribution item must be an object"
            )
        rows.append(
            BanditActionProbability(
                schema_version=1,
                action_id=_string(item.get("action_id"), "action_id"),
                probability=_decimal(item.get("probability"), "probability"),
            )
        )
    return tuple(rows)


def _manifest(samples: dict[str, object]) -> dict[str, object]:
    policy = _policy()
    policy_document = {
        "schema_version": 1,
        "policy_id": policy.policy_id,
        "policy_revision": policy.policy_revision,
        "minimum_behavior_propensity": str(policy.minimum_behavior_propensity),
        "maximum_importance_weight": str(policy.maximum_importance_weight),
        "decimal_places": policy.decimal_places,
        "rounding_mode": policy.rounding_mode.value,
    }
    manifest: dict[str, object] = {
        "schema_version": 1,
        **_CLAIMS,
        "generation_revision": "bandit-offline-v1",
        "fixed_shuffle_seed": _SHUFFLE_SEED,
        "sample_count": len(samples["samples"]),
        "samples_digest": str(
            canonical_digest(samples, domain="eval:bandit-offline-samples:v1")
        ),
        "ope_policy": policy_document,
        "ope_policy_digest": str(bandit_ope_policy_digest(policy)),
        "expected": {key: f"{value:.12f}" for key, value in _EXPECTED.items()},
    }
    manifest["dataset_digest"] = str(
        canonical_digest(
            {"samples": samples, "policy": policy_document},
            domain="eval:bandit-offline-dataset:v1",
        )
    )
    manifest["manifest_digest"] = str(
        canonical_digest(manifest, domain="eval:bandit-offline-manifest:v1")
    )
    return manifest


def _data_card() -> str:
    return """# S20 Offline Bandit Golden

This bundle contains four synthetic logged-action samples with complete behavior
and evaluation distributions. It verifies deterministic Decimal IPS, SNIPS,
doubly robust and effective-sample-size arithmetic plus action-support checks.

- No user, QQ, prompt, answer or Memory data is present.
- No network or real model Endpoint is called or claimed.
- No policy is trained and no production Router/Runtime hook is installed.
- The results are arithmetic contract evidence, not an online quality claim.
"""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as failure:
        raise RuntimeError(f"Bandit offline read failed: {path.name}") from failure
    if not payload or len(payload) > 1_048_576:
        raise RuntimeError(f"Bandit offline invalid size: {path.name}")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as failure:
        raise RuntimeError(f"Bandit offline invalid JSON: {path.name}") from failure
    if not isinstance(value, dict):
        raise RuntimeError(  # noqa: TRY004 - bundle failures share one public type.
            f"Bandit offline root is not an object: {path.name}"
        )
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(value)


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise RuntimeError(  # noqa: TRY004 - bundle failures share one public type.
            f"Bandit offline {field} must be a decimal string"
        )
    try:
        parsed = Decimal(value)
    except Exception as failure:
        raise RuntimeError(f"Bandit offline invalid decimal: {field}") from failure
    if not parsed.is_finite():
        raise RuntimeError(f"Bandit offline non-finite decimal: {field}")
    return parsed


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Bandit offline invalid string: {field}")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise RuntimeError(f"Bandit offline invalid integer: {field}")
    return value


def _required(value: Decimal | None, field: str) -> Decimal:
    if value is None:
        raise validation_error("bandit_ope_value_missing", field)
    return value


def _rounding(mode: BanditRoundingMode) -> str:
    if mode is not BanditRoundingMode.HALF_EVEN:
        raise validation_error("unsupported_bandit_rounding_mode")
    return ROUND_HALF_EVEN


def _decimal_text(value: Decimal, policy: BanditOpePolicy) -> str:
    return f"{value:.{policy.decimal_places}f}"


__all__ = [
    "check_bandit_offline_bundle",
    "evaluate_ope",
    "generate_bandit_offline_bundle",
    "run_bandit_offline_eval",
]
