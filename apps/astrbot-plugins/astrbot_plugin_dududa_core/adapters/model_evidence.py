from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.models.contracts import ModelProviderDescriptor, ModelRetentionMode

from .model import AstrBotProviderBindingEvidence


class AstrBotProviderEvidenceStore:
    """Resolve private AstrBot conformance evidence without extending Context."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        try:
            document = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("AstrBot provider evidence file is unavailable") from exc
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise ValueError("AstrBot provider evidence document is invalid")
        providers = document.get("providers")
        if not isinstance(providers, list):
            raise TypeError("AstrBot provider evidence providers must be an array")

        evidence_by_binding: dict[tuple[str, str], AstrBotProviderBindingEvidence] = {}
        for index, value in enumerate(providers):
            evidence = _parse_evidence(value, index)
            key = (evidence.astrbot_provider_id, evidence.verified_model_id)
            if key in evidence_by_binding:
                raise ValueError("duplicate AstrBot provider evidence binding")
            evidence_by_binding[key] = evidence
        self._evidence_by_binding = evidence_by_binding

    def resolve(
        self,
        astrbot_provider_id: str,
        descriptor: ModelProviderDescriptor,
    ) -> AstrBotProviderBindingEvidence | None:
        if not isinstance(astrbot_provider_id, str) or not astrbot_provider_id.strip():
            raise ValueError("AstrBot provider ID must be non-empty")
        if not isinstance(descriptor, ModelProviderDescriptor):
            raise TypeError("descriptor must be ModelProviderDescriptor")
        if len(descriptor.endpoints) != 1:
            return None
        return self._evidence_by_binding.get(
            (astrbot_provider_id.strip(), descriptor.endpoints[0].model_id)
        )


def _parse_evidence(
    value: object,
    index: int,
) -> AstrBotProviderBindingEvidence:
    if not isinstance(value, Mapping):
        raise TypeError(f"AstrBot provider evidence {index} must be an object")
    item = dict(value)
    revision_value = item.get("conformance_revision")
    if not isinstance(revision_value, Mapping):
        raise TypeError(
            f"AstrBot provider evidence {index} has invalid conformance_revision"
        )
    revision = dict(revision_value)
    try:
        return AstrBotProviderBindingEvidence(
            schema_version=item["schema_version"],
            astrbot_provider_id=item["astrbot_provider_id"],
            host_version=item["host_version"],
            conformance_revision=ComponentRevision(
                component_id=revision["component_id"],
                implementation_version=revision["implementation_version"],
                config_revision=revision["config_revision"],
                artifact_digest=DigestString(revision["artifact_digest"]),
            ),
            verified_model_id=item["verified_model_id"],
            verified_max_output_tokens=item["verified_max_output_tokens"],
            verified_data_residencies=frozenset(
                _string_array(item["verified_data_residencies"], "residencies")
            ),
            verified_retention_modes=frozenset(
                ModelRetentionMode(mode)
                for mode in _string_array(
                    item["verified_retention_modes"],
                    "retention_modes",
                )
            ),
            single_request_verified=item["single_request_verified"],
            model_binding_verified=item["model_binding_verified"],
            output_limit_verified=item["output_limit_verified"],
            residency_verified=item["residency_verified"],
            retention_verified=item["retention_verified"],
            sanitized_logging_verified=item["sanitized_logging_verified"],
            deadline_enforcement_verified=item["deadline_enforcement_verified"],
            cancellation_enforcement_verified=item["cancellation_enforcement_verified"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"AstrBot provider evidence {index} is invalid") from exc


def _string_array(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"AstrBot provider evidence {field} must be an array")
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"AstrBot provider evidence {field} contains invalid text")
    return result
