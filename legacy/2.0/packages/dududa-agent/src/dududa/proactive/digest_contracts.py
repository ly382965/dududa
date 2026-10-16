from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from dududa.domain.primitives import ComponentRevision, DigestString, require_aware
from dududa.errors import validation_error
from dududa.responses.contracts import AnswerProfile, ResponseProfileLimits

from .contracts import ProactiveDisposition, ProactiveRunMode
from .digests import seal_proactive_contract
from .source_contracts import SourceFetchStatus

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


@dataclass(frozen=True, slots=True)
class DigestCompositionPolicySnapshot:
    schema_version: int
    snapshot_id: str
    source_policy_id: str
    source_policy_revision: str
    source_policy_digest: DigestString
    source_ids: tuple[str, ...]
    response_policy_revision: str
    persona_catalog_snapshot_id: str
    persona_catalog_digest: DigestString
    persona_id: str
    persona_version: str | None
    maximum_profile: AnswerProfile
    short_limits: ResponseProfileLimits
    medium_limits: ResponseProfileLimits
    delivery_part_character_limit: int
    component_revision: ComponentRevision
    policy_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "snapshot_id",
            "source_policy_id",
            "persona_catalog_snapshot_id",
            "persona_id",
        ):
            _identifier(getattr(self, field_name), field_name)
        for field_name in ("source_policy_revision", "response_policy_revision"):
            _revision(getattr(self, field_name), field_name)
        for field_name in ("source_policy_digest", "persona_catalog_digest"):
            _digest(getattr(self, field_name), field_name)
        source_ids = tuple(self.source_ids)
        if (
            not source_ids
            or any(
                not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None
                for value in source_ids
            )
            or source_ids != tuple(sorted(set(source_ids)))
        ):
            raise validation_error("invalid_digest_source_ids")
        if self.persona_version is not None:
            _revision(self.persona_version, "persona_version")
        if self.maximum_profile is not AnswerProfile.MEDIUM:
            raise validation_error("digest_profile_cap_must_be_medium")
        if not isinstance(self.short_limits, ResponseProfileLimits) or not isinstance(
            self.medium_limits,
            ResponseProfileLimits,
        ):
            raise validation_error("invalid_digest_profile_limits")
        if type(self.delivery_part_character_limit) is not int or not (
            1 <= self.delivery_part_character_limit <= 10_000
        ):
            raise validation_error("invalid_digest_part_character_limit")
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_digest_component_revision")
        object.__setattr__(self, "source_ids", source_ids)
        seal_proactive_contract(self, "policy_digest")

    def limits_for(self, profile: AnswerProfile) -> ResponseProfileLimits:
        if profile is AnswerProfile.SHORT:
            return self.short_limits
        if profile is AnswerProfile.MEDIUM:
            return self.medium_limits
        raise validation_error("digest_long_profile_not_selectable")


@dataclass(frozen=True, slots=True)
class DigestShadowMetadata:
    schema_version: int
    run_id: str
    origin_digest: DigestString
    target_scope_digest: DigestString
    subscription_id: str
    subscription_revision: int
    mode: ProactiveRunMode
    disposition: ProactiveDisposition
    policy_digest: DigestString
    source_fetch_status: SourceFetchStatus | None
    source_fetch_receipt_digest: DigestString | None
    source_batch_digest: DigestString | None
    item_set_digest: DigestString | None
    response_plan_digest: DigestString | None
    candidate_response_digest: DigestString | None
    persona_catalog_digest: DigestString | None
    persona_source_digest: DigestString | None
    reason_codes: tuple[str, ...]
    completed_at: datetime
    metadata_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in ("run_id", "subscription_id"):
            _identifier(getattr(self, field_name), field_name)
        for field_name in (
            "origin_digest",
            "target_scope_digest",
            "policy_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        if (
            type(self.subscription_revision) is not int
            or self.subscription_revision < 1
        ):
            raise validation_error("invalid_digest_subscription_revision")
        if self.mode not in {ProactiveRunMode.COLLECT, ProactiveRunMode.SHADOW}:
            raise validation_error("invalid_digest_shadow_mode")
        if self.disposition not in {
            ProactiveDisposition.DENIED,
            ProactiveDisposition.COLLECTED,
            ProactiveDisposition.SHADOWED,
            ProactiveDisposition.FAILED,
        }:
            raise validation_error("invalid_digest_shadow_disposition")
        if self.source_fetch_status is not None and not isinstance(
            self.source_fetch_status,
            SourceFetchStatus,
        ):
            raise validation_error("invalid_digest_source_fetch_status")
        if (self.source_fetch_status is None) != (
            self.source_fetch_receipt_digest is None
        ):
            raise validation_error("incomplete_digest_source_fetch_evidence")
        for field_name in (
            "source_fetch_receipt_digest",
            "source_batch_digest",
            "item_set_digest",
            "response_plan_digest",
            "candidate_response_digest",
            "persona_catalog_digest",
            "persona_source_digest",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _digest(value, field_name)
        if self.source_batch_digest is not None and self.source_fetch_status is None:
            raise validation_error("digest_batch_without_fetch")
        candidate_fields = (
            self.item_set_digest,
            self.response_plan_digest,
            self.candidate_response_digest,
            self.persona_catalog_digest,
            self.persona_source_digest,
        )
        if any(value is not None for value in candidate_fields) and not all(
            value is not None for value in candidate_fields
        ):
            raise validation_error("incomplete_digest_candidate_evidence")
        if (
            self.candidate_response_digest is not None
            and self.source_batch_digest is None
        ):
            raise validation_error("digest_candidate_without_batch")
        if self.disposition is ProactiveDisposition.COLLECTED:
            if self.mode is not ProactiveRunMode.COLLECT or any(
                value is not None
                for value in (
                    self.source_fetch_receipt_digest,
                    self.source_batch_digest,
                    *candidate_fields,
                )
            ):
                raise validation_error("invalid_collected_digest_metadata")
        elif self.disposition is ProactiveDisposition.SHADOWED:
            if (
                self.mode is not ProactiveRunMode.SHADOW
                or self.source_fetch_receipt_digest is None
            ):
                raise validation_error("invalid_shadowed_digest_metadata")
        elif self.disposition is ProactiveDisposition.DENIED and any(
            value is not None
            for value in (
                self.source_fetch_receipt_digest,
                self.source_batch_digest,
                *candidate_fields,
            )
        ):
            raise validation_error("denied_digest_metadata_has_candidate")
        reasons = _reason_codes(self.reason_codes)
        require_aware(self.completed_at, "digest_shadow_completed_at")
        object.__setattr__(self, "reason_codes", reasons)
        seal_proactive_contract(self, "metadata_digest")

    @property
    def candidate_built(self) -> bool:
        return self.candidate_response_digest is not None


def _v1(value: object) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise validation_error("invalid_digest_identifier", field_name)
    return value


def _revision(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise validation_error("invalid_digest_revision", field_name)
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_digest_evidence", field_name)
    return value


def _reason_codes(values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_digest_reason_codes")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError:
        raise validation_error("invalid_digest_reason_codes") from None
    if (
        not result
        or len(result) > 32
        or len(result) != len(set(result))
        or any(not isinstance(value, str) or not value.strip() for value in result)
    ):
        raise validation_error("invalid_digest_reason_codes")
    return result


__all__ = ["DigestCompositionPolicySnapshot", "DigestShadowMetadata"]
