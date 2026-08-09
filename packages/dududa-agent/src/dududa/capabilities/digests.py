from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields, is_dataclass

from dududa.contracts.canonical import canonical_digest, canonical_schema_digest
from dududa.domain.capability import capability_definition_digest
from dududa.domain.primitives import DigestString, JsonValue

from .contracts import (
    ArgumentBindingRequest,
    ArgumentBindingResult,
    CapabilityCandidate,
    CapabilityCatalogPublishReceipt,
    CapabilityCatalogSnapshot,
    CapabilityCatalogUpdate,
    CapabilityHealthSnapshot,
    CapabilityProviderDescriptor,
    CapabilityProviderHealth,
    CapabilityQuery,
    CapabilityResult,
    CapabilityRetrievalRequest,
    CapabilityRetrievalResult,
    CapabilityRunReceipt,
    CapabilityRunRequest,
    CapabilitySchemaDocument,
    McpCapabilityMapping,
    ProviderInvocation,
    ToolExecutionRequest,
    ToolInvocationClaim,
    ToolInvocationClaimRequest,
    ToolInvocationReceipt,
    ToolObservation,
    ToolPlan,
    ToolPlanningRequest,
    ToolPlanValidationRequest,
    ToolPlanValidationResult,
    ToolValidationRequest,
    ToolValidationResult,
)


def capability_schema_document_digest(
    document: CapabilitySchemaDocument,
) -> DigestString:
    return canonical_schema_digest(
        document.document,
        schema_id=document.schema_ref.schema_id,
        schema_version=document.schema_ref.schema_version,
    )


def capability_provider_descriptor_digest(
    descriptor: CapabilityProviderDescriptor,
) -> DigestString:
    return _digest_without(
        descriptor,
        "descriptor_digest",
        domain="capability.provider-descriptor:v1",
    )


def capability_provider_health_digest(
    health: CapabilityProviderHealth,
) -> DigestString:
    return _digest_without(
        health,
        "health_digest",
        domain="capability.provider-health:v1",
    )


def capability_health_snapshot_digest(
    snapshot: CapabilityHealthSnapshot,
) -> DigestString:
    return _digest_without(
        snapshot,
        "snapshot_id",
        "snapshot_digest",
        domain="capability.health-snapshot:v1",
    )


def mcp_capability_mapping_digest(mapping: McpCapabilityMapping) -> DigestString:
    return _digest_without(
        mapping,
        "mapping_digest",
        domain="capability.mcp-mapping:v1",
    )


def capability_catalog_digest(snapshot: CapabilityCatalogSnapshot) -> DigestString:
    return _digest_without(
        snapshot,
        "snapshot_id",
        "catalog_digest",
        "acquired_at",
        domain="capability.catalog:v1",
    )


def capability_catalog_update_digest(update: CapabilityCatalogUpdate) -> DigestString:
    return _digest_without(
        update,
        "update_digest",
        domain="capability.catalog-update:v1",
    )


def capability_catalog_publish_receipt_digest(
    receipt: CapabilityCatalogPublishReceipt,
) -> DigestString:
    return _digest_without(
        receipt,
        "receipt_digest",
        domain="capability.catalog-publish-receipt:v1",
    )


def capability_query_digest(query: CapabilityQuery) -> DigestString:
    return _digest_without(query, "query_digest", domain="capability.query:v1")


def capability_candidate_digest(candidate: CapabilityCandidate) -> DigestString:
    return _digest_without(
        candidate,
        "candidate_digest",
        domain="capability.candidate:v1",
    )


def capability_retrieval_request_digest(
    request: CapabilityRetrievalRequest,
) -> DigestString:
    return _digest_without(
        request,
        "request_digest",
        domain="capability.retrieval-request:v1",
    )


def capability_retrieval_result_digest(
    result: CapabilityRetrievalResult,
) -> DigestString:
    return _digest_without(
        result,
        "result_digest",
        domain="capability.retrieval-result:v1",
    )


def tool_plan_digest(plan: ToolPlan) -> DigestString:
    return _digest_without(plan, "plan_digest", domain="capability.tool-plan:v1")


def tool_planning_request_digest(request: ToolPlanningRequest) -> DigestString:
    return _digest_without(
        request,
        "request_digest",
        domain="capability.tool-planning-request:v1",
    )


def tool_plan_validation_request_digest(
    request: ToolPlanValidationRequest,
) -> DigestString:
    return _digest_without(
        request,
        "request_digest",
        domain="capability.tool-plan-validation-request:v1",
    )


def tool_plan_validation_result_digest(
    result: ToolPlanValidationResult,
) -> DigestString:
    return _digest_without(
        result,
        "result_digest",
        domain="capability.tool-plan-validation-result:v1",
    )


def argument_binding_request_digest(request: ArgumentBindingRequest) -> DigestString:
    return _digest_without(
        request,
        "request_digest",
        domain="capability.argument-binding-request:v1",
    )


def argument_binding_result_digest(result: ArgumentBindingResult) -> DigestString:
    return _digest_without(
        result,
        "result_digest",
        domain="capability.argument-binding-result:v1",
    )


def tool_execution_request_digest(request: ToolExecutionRequest) -> DigestString:
    return _digest_without(
        request,
        "request_digest",
        domain="capability.tool-execution-request:v1",
    )


def provider_invocation_digest(invocation: ProviderInvocation) -> DigestString:
    return _digest_without(
        invocation,
        "invocation_digest",
        domain="capability.provider-invocation:v1",
    )


def capability_result_digest(result: CapabilityResult) -> DigestString:
    return _digest_without(
        result,
        "result_digest",
        domain="capability.result:v1",
    )


def tool_observation_digest(observation: ToolObservation) -> DigestString:
    return _digest_without(
        observation,
        "observation_digest",
        domain="capability.tool-observation:v1",
    )


def tool_validation_request_digest(request: ToolValidationRequest) -> DigestString:
    return _digest_without(
        request,
        "request_digest",
        domain="capability.tool-validation-request:v1",
    )


def tool_validation_result_digest(result: ToolValidationResult) -> DigestString:
    return _digest_without(
        result,
        "result_digest",
        domain="capability.tool-validation-result:v1",
    )


def tool_invocation_claim_request_digest(
    request: ToolInvocationClaimRequest,
) -> DigestString:
    return _digest_without(
        request,
        "request_digest",
        domain="capability.tool-invocation-claim-request:v1",
    )


def tool_invocation_claim_digest(claim: ToolInvocationClaim) -> DigestString:
    return _digest_without(
        claim,
        "claim_digest",
        domain="capability.tool-invocation-claim:v1",
    )


def tool_invocation_receipt_digest(receipt: ToolInvocationReceipt) -> DigestString:
    return _digest_without(
        receipt,
        "receipt_digest",
        domain="capability.tool-invocation-receipt:v1",
    )


def capability_run_request_digest(request: CapabilityRunRequest) -> DigestString:
    return _digest_without(
        request,
        "request_digest",
        domain="capability.run-request:v1",
    )


def capability_run_receipt_digest(receipt: CapabilityRunReceipt) -> DigestString:
    return _digest_without(
        receipt,
        "receipt_digest",
        domain="capability.run-receipt:v1",
    )


def tool_idempotency_key(
    *,
    run_id: str,
    logical_operation_id: str,
    capability_id: str,
    definition_digest: DigestString,
    normalized_arguments: Mapping[str, JsonValue],
) -> str:
    return str(
        canonical_digest(
            {
                "run_id": run_id,
                "logical_operation_id": logical_operation_id,
                "capability_id": capability_id,
                "definition_digest": definition_digest,
                "normalized_arguments": normalized_arguments,
            },
            domain="capability.tool-idempotency-key:v1",
        )
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
    return canonical_digest(payload, domain=domain)


__all__: Iterable[str] = (
    "argument_binding_request_digest",
    "argument_binding_result_digest",
    "capability_candidate_digest",
    "capability_catalog_digest",
    "capability_catalog_publish_receipt_digest",
    "capability_catalog_update_digest",
    "capability_definition_digest",
    "capability_health_snapshot_digest",
    "capability_provider_descriptor_digest",
    "capability_provider_health_digest",
    "capability_query_digest",
    "capability_result_digest",
    "capability_retrieval_request_digest",
    "capability_retrieval_result_digest",
    "capability_run_receipt_digest",
    "capability_run_request_digest",
    "capability_schema_document_digest",
    "mcp_capability_mapping_digest",
    "provider_invocation_digest",
    "tool_execution_request_digest",
    "tool_idempotency_key",
    "tool_invocation_claim_digest",
    "tool_invocation_claim_request_digest",
    "tool_invocation_receipt_digest",
    "tool_observation_digest",
    "tool_plan_digest",
    "tool_plan_validation_request_digest",
    "tool_plan_validation_result_digest",
    "tool_planning_request_digest",
    "tool_validation_request_digest",
    "tool_validation_result_digest",
)
