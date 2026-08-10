from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import ConversationScope
from dududa.domain.primitives import DigestString
from dududa.errors import validation_error

if TYPE_CHECKING:
    from .contracts import (
        ConversationOpportunitySnapshot,
        DispatchClaim,
        InitiatedRunRequest,
        LocalTimeWindow,
        PreparedDispatch,
        ProactiveAuthorizationGrant,
        ProactiveAuthorizationGrantRef,
        ProactivePolicyDecision,
        ProactivePreviewMetadata,
        ProactivePreviewRequest,
        ProactivePreviewResult,
        ProactiveQuotaLease,
        ProactiveRunReceipt,
        ProactiveSubscription,
        ProactiveTargetPolicy,
        ProactiveTargetPolicyRef,
        ProactiveTrigger,
        ProactiveTriggerKind,
        ScheduleClaimReceipt,
        ScheduleLedgerRecord,
        ScheduleMaterializationReceipt,
        ScheduleOccurrence,
        ScheduleSpec,
        ScheduleTriggerClaim,
        SourceBatch,
        SourceFailure,
        SourceItem,
        SubscriptionMutationReceipt,
    )


_CONTRACT_DIGESTS = {
    "ProactiveAuthorizationGrant": (
        "grant_digest",
        "proactive:authorization-grant:v1",
    ),
    "ProactiveTargetPolicy": (
        "target_policy_digest",
        "proactive:target-policy:v1",
    ),
    "ProactiveSubscription": (
        "subscription_digest",
        "proactive:subscription:v1",
    ),
    "ScheduleOccurrence": (
        "occurrence_digest",
        "proactive:schedule-occurrence:v1",
    ),
    "ScheduleTriggerClaim": (
        "claim_digest",
        "proactive:schedule-trigger-claim:v1",
    ),
    "ScheduleLedgerRecord": (
        "record_digest",
        "proactive:schedule-ledger-record:v1",
    ),
    "ScheduleMaterializationReceipt": (
        "receipt_digest",
        "proactive:schedule-materialization-receipt:v1",
    ),
    "ScheduleClaimReceipt": (
        "receipt_digest",
        "proactive:schedule-claim-receipt:v1",
    ),
    "SubscriptionMutationReceipt": (
        "receipt_digest",
        "proactive:subscription-mutation-receipt:v1",
    ),
    "ConversationOpportunitySnapshot": (
        "snapshot_digest",
        "proactive:opportunity-snapshot:v1",
    ),
    "ProactiveTrigger": ("trigger_digest", "proactive:trigger:v1"),
    "InitiatedRunRequest": (
        "start_digest",
        "proactive:initiated-run-request:v1",
    ),
    "ProactivePreviewRequest": (
        "request_digest",
        "proactive:preview-request:v1",
    ),
    "ProactivePreviewResult": (
        "result_digest",
        "proactive:preview-result:v1",
    ),
    "ProactivePreviewMetadata": (
        "metadata_digest",
        "proactive:preview-metadata:v1",
    ),
    "SourceItem": ("content_digest", "proactive:source-item:v1"),
    "SourceBatch": ("batch_digest", "proactive:source-batch:v1"),
    "ProactivePolicyDecision": (
        "decision_digest",
        "proactive:policy-decision:v1",
    ),
    "PreparedDispatch": (
        "prepared_dispatch_digest",
        "proactive:prepared-dispatch:v1",
    ),
    "DispatchClaim": ("claim_digest", "proactive:dispatch-claim:v1"),
    "ProactiveRunReceipt": (
        "receipt_digest",
        "proactive:run-receipt:v1",
    ),
    "ProactiveQuotaLease": ("lease_digest", "proactive:quota-lease:v1"),
}


def seal_proactive_contract(value: object, digest_field: str) -> DigestString:
    """Set an omitted self digest or reject a caller-supplied mismatched digest."""

    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("proactive contract must be a dataclass instance")
    identity = type(value).__name__
    expected_contract = _CONTRACT_DIGESTS.get(identity)
    if expected_contract is None or expected_contract[0] != digest_field:
        raise TypeError("unknown proactive contract digest field")
    expected = _digest_without(
        value,
        digest_field,
        domain=expected_contract[1],
    )
    actual = getattr(value, digest_field)
    if actual:
        if actual != expected:
            raise validation_error("proactive_contract_digest_mismatch", identity)
        return expected
    object.__setattr__(value, digest_field, expected)
    return expected


def local_time_window_digest(
    window: LocalTimeWindow | Mapping[str, object],
) -> DigestString:
    return _digest_without(window, domain="proactive:local-time-window:v1")


def proactive_authorization_grant_ref_digest(
    reference: ProactiveAuthorizationGrantRef | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        reference,
        domain="proactive:authorization-grant-ref:v1",
    )


def proactive_authorization_grant_digest(
    grant: ProactiveAuthorizationGrant | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        grant,
        "grant_digest",
        domain="proactive:authorization-grant:v1",
    )


def proactive_target_policy_digest(
    policy: ProactiveTargetPolicy | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        policy,
        "target_policy_digest",
        domain="proactive:target-policy:v1",
    )


def proactive_target_policy_ref_digest(
    reference: ProactiveTargetPolicyRef | Mapping[str, object],
) -> DigestString:
    return _digest_without(reference, domain="proactive:target-policy-ref:v1")


def schedule_spec_digest(
    schedule: ScheduleSpec | Mapping[str, object],
) -> DigestString:
    return _digest_without(schedule, domain="proactive:schedule-spec:v1")


def proactive_subscription_digest(
    subscription: ProactiveSubscription | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        subscription,
        "subscription_digest",
        domain="proactive:subscription:v1",
    )


def schedule_occurrence_digest(
    occurrence: ScheduleOccurrence | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        occurrence,
        "occurrence_digest",
        domain="proactive:schedule-occurrence:v1",
    )


def schedule_trigger_claim_digest(
    claim: ScheduleTriggerClaim | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        claim,
        "claim_digest",
        domain="proactive:schedule-trigger-claim:v1",
    )


def schedule_ledger_record_digest(
    record: ScheduleLedgerRecord | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        record,
        "record_digest",
        domain="proactive:schedule-ledger-record:v1",
    )


def schedule_materialization_receipt_digest(
    receipt: ScheduleMaterializationReceipt | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        receipt,
        "receipt_digest",
        domain="proactive:schedule-materialization-receipt:v1",
    )


def schedule_claim_receipt_digest(
    receipt: ScheduleClaimReceipt | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        receipt,
        "receipt_digest",
        domain="proactive:schedule-claim-receipt:v1",
    )


def subscription_mutation_receipt_digest(
    receipt: SubscriptionMutationReceipt | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        receipt,
        "receipt_digest",
        domain="proactive:subscription-mutation-receipt:v1",
    )


def conversation_opportunity_snapshot_digest(
    snapshot: ConversationOpportunitySnapshot | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        snapshot,
        "snapshot_digest",
        domain="proactive:opportunity-snapshot:v1",
    )


def proactive_trigger_digest(
    trigger: ProactiveTrigger | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        trigger,
        "trigger_digest",
        domain="proactive:trigger:v1",
    )


def initiated_run_request_digest(
    request: InitiatedRunRequest | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        request,
        "start_digest",
        domain="proactive:initiated-run-request:v1",
    )


def proactive_preview_request_digest(
    request: ProactivePreviewRequest | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        request,
        "request_digest",
        domain="proactive:preview-request:v1",
    )


def proactive_preview_result_digest(
    result: ProactivePreviewResult | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        result,
        "result_digest",
        domain="proactive:preview-result:v1",
    )


def proactive_preview_metadata_digest(
    metadata: ProactivePreviewMetadata | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        metadata,
        "metadata_digest",
        domain="proactive:preview-metadata:v1",
    )


def source_failure_digest(
    failure: SourceFailure | Mapping[str, object],
) -> DigestString:
    return _digest_without(failure, domain="proactive:source-failure:v1")


def source_item_digest(
    item: SourceItem | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        item,
        "content_digest",
        domain="proactive:source-item:v1",
    )


def source_batch_digest(
    batch: SourceBatch | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        batch,
        "batch_digest",
        domain="proactive:source-batch:v1",
    )


def proactive_policy_decision_digest(
    decision: ProactivePolicyDecision | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        decision,
        "decision_digest",
        domain="proactive:policy-decision:v1",
    )


def prepared_dispatch_digest(
    dispatch: PreparedDispatch | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        dispatch,
        "prepared_dispatch_digest",
        domain="proactive:prepared-dispatch:v1",
    )


def dispatch_claim_digest(
    claim: DispatchClaim | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        claim,
        "claim_digest",
        domain="proactive:dispatch-claim:v1",
    )


def proactive_run_receipt_digest(
    receipt: ProactiveRunReceipt | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        receipt,
        "receipt_digest",
        domain="proactive:run-receipt:v1",
    )


def proactive_quota_lease_digest(
    lease: ProactiveQuotaLease | Mapping[str, object],
) -> DigestString:
    return _digest_without(
        lease,
        "lease_digest",
        domain="proactive:quota-lease:v1",
    )


def proactive_delivery_idempotency_key(
    *,
    trigger_kind: ProactiveTriggerKind,
    trigger_source_digest: DigestString,
    target_scope: ConversationScope,
    item_set_digest: DigestString | None,
    validated_response_digest: DigestString,
) -> str:
    if not isinstance(target_scope, ConversationScope):
        raise validation_error("invalid_proactive_idempotency_scope")
    if not isinstance(trigger_source_digest, str) or not trigger_source_digest:
        raise validation_error("invalid_proactive_idempotency_trigger_digest")
    if not isinstance(validated_response_digest, str) or not validated_response_digest:
        raise validation_error("invalid_proactive_idempotency_response_digest")
    if item_set_digest is not None and (
        not isinstance(item_set_digest, str) or not item_set_digest
    ):
        raise validation_error("invalid_proactive_idempotency_item_set_digest")
    return str(
        canonical_digest(
            {
                "trigger_kind": trigger_kind,
                "trigger_source_digest": trigger_source_digest,
                "target_scope": target_scope,
                "item_set_digest": item_set_digest,
                "validated_response_digest": validated_response_digest,
            },
            domain="proactive:delivery-idempotency-key:v1",
        )
    )


def proactive_business_idempotency_key(
    *,
    trigger: object,
    target_scope: ConversationScope,
    item_set_digest: DigestString | None,
    validated_response_digest: DigestString,
) -> str:
    if not hasattr(trigger, "kind") or not hasattr(trigger, "source_digest"):
        raise validation_error("invalid_proactive_idempotency_trigger")
    if getattr(trigger, "target_scope", None) != target_scope:
        raise validation_error("proactive_idempotency_scope_mismatch")
    return proactive_delivery_idempotency_key(
        trigger_kind=trigger.kind,
        trigger_source_digest=trigger.source_digest,
        target_scope=target_scope,
        item_set_digest=item_set_digest,
        validated_response_digest=validated_response_digest,
    )


def _digest_without(value: object, *excluded: str, domain: str) -> DigestString:
    if isinstance(value, Mapping):
        payload = {key: item for key, item in value.items() if key not in excluded}
    elif is_dataclass(value) and not isinstance(value, type):
        payload = {
            item.name: getattr(value, item.name)
            for item in fields(value)
            if item.name not in excluded
        }
    else:
        raise TypeError("digest value must be a dataclass or mapping")
    return canonical_digest(_normalize_local_values(payload), domain=domain)


def _normalize_local_values(value: object) -> object:
    if isinstance(value, datetime):
        return value
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="microseconds")
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _normalize_local_values(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {key: _normalize_local_values(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_normalize_local_values(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_normalize_local_values(item) for item in value)
    return value


__all__: Iterable[str] = (
    "conversation_opportunity_snapshot_digest",
    "dispatch_claim_digest",
    "initiated_run_request_digest",
    "local_time_window_digest",
    "prepared_dispatch_digest",
    "proactive_authorization_grant_digest",
    "proactive_authorization_grant_ref_digest",
    "proactive_business_idempotency_key",
    "proactive_delivery_idempotency_key",
    "proactive_policy_decision_digest",
    "proactive_preview_metadata_digest",
    "proactive_preview_request_digest",
    "proactive_preview_result_digest",
    "proactive_quota_lease_digest",
    "proactive_run_receipt_digest",
    "proactive_subscription_digest",
    "proactive_target_policy_digest",
    "proactive_target_policy_ref_digest",
    "proactive_trigger_digest",
    "schedule_claim_receipt_digest",
    "schedule_ledger_record_digest",
    "schedule_materialization_receipt_digest",
    "schedule_occurrence_digest",
    "schedule_spec_digest",
    "schedule_trigger_claim_digest",
    "seal_proactive_contract",
    "source_batch_digest",
    "source_failure_digest",
    "source_item_digest",
    "subscription_mutation_receipt_digest",
)
