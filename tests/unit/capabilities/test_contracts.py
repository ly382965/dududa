from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.capabilities import (
    TOOL_COMPLETION_ALL_STEPS,
    ArgumentTemplate,
    CapabilityCandidate,
    CapabilityCatalogSnapshot,
    CapabilityDefinition,
    CapabilityExecutionContext,
    CapabilityProviderDescriptor,
    CapabilityProviderKind,
    CapabilityQuery,
    CapabilityRetrievalResult,
    CapabilityRunReceipt,
    CapabilityRunRequest,
    CapabilityRunStatus,
    CapabilitySchemaDocument,
    CostHint,
    Idempotency,
    LatencyHint,
    McpCapabilityMapping,
    ObservationBinding,
    ProviderRef,
    ToolExecutionRequest,
    ToolExecutionStatus,
    ToolObservation,
    ToolPlan,
    ToolPlanValidationRequest,
    ToolPlanValidationResult,
    ToolStep,
    ToolValidationRequest,
    ToolValidationResult,
    ValidationAction,
    capability_candidate_digest,
    capability_catalog_digest,
    capability_catalog_revision,
    capability_definition_digest,
    capability_mapping_revision,
    capability_provider_descriptor_digest,
    capability_provider_registry_revision,
    capability_query_digest,
    capability_retrieval_result_digest,
    capability_run_receipt_digest,
    capability_run_request_digest,
    mcp_capability_mapping_digest,
    tool_execution_request_digest,
    tool_observation_digest,
    tool_plan_digest,
    tool_plan_validation_request_digest,
    tool_plan_validation_result_digest,
    tool_validation_request_digest,
    tool_validation_result_digest,
)
from dududa.contracts.canonical import canonical_digest, canonical_schema_digest
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    PrivacyLevel,
    ResourceUsage,
    RiskLevel,
    RoleId,
    SchemaRef,
    SideEffect,
)
from dududa.errors import DududaError
from dududa.mcp import McpOperationSemantics

NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def revision(name: str) -> ComponentRevision:
    return ComponentRevision(name, "1.0.0", "cfg-v1", DigestString("artifact-v1"))


def schema(schema_id: str) -> CapabilitySchemaDocument:
    document = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"query": {"type": "string", "maxLength": 100}},
    }
    reference = SchemaRef(
        schema_id,
        1,
        canonical_schema_digest(document, schema_id=schema_id, schema_version=1),
    )
    return CapabilitySchemaDocument(1, reference, document)


def provider_ref() -> ProviderRef:
    return ProviderRef("mcp.icourse", revision("provider.icourse"))


def definition(
    input_schema: SchemaRef,
    output_schema: SchemaRef,
) -> CapabilityDefinition:
    values = {
        "schema_version": 1,
        "capability_id": "icourse.courses.search.v1",
        "name": "Search cached courses",
        "description": "Search the approved public iCourse cache.",
        "category": "campus.course-review",
        "provider": provider_ref(),
        "input_schema": input_schema,
        "output_schema": output_schema,
        "risk_level": RiskLevel.LOW,
        "privacy_level": PrivacyLevel.PUBLIC,
        "allowed_contexts": frozenset(
            {ConversationType.PRIVATE, ConversationType.GROUP}
        ),
        "required_permissions": frozenset({"capability.icourse.read"}),
        "cost_hint": CostHint(1),
        "latency_hint": LatencyHint(10, 100),
        "tags": frozenset({"course", "search"}),
        "idempotency": Idempotency.READ_ONLY,
        "side_effects": frozenset({SideEffect.NONE}),
        "enabled": True,
    }
    return CapabilityDefinition(
        definition_digest=capability_definition_digest(values),
        **values,
    )


def provider_descriptor(item: CapabilityDefinition) -> CapabilityProviderDescriptor:
    values = {
        "schema_version": 1,
        "provider": item.provider,
        "kind": CapabilityProviderKind.MCP,
        "capability_ids": frozenset({item.capability_id}),
    }
    return CapabilityProviderDescriptor(
        descriptor_digest=capability_provider_descriptor_digest(values),
        **values,
    )


def mapping(item: CapabilityDefinition) -> McpCapabilityMapping:
    values = {
        "schema_version": 1,
        "capability_id": item.capability_id,
        "capability_definition_digest": item.definition_digest,
        "server_id": "icourse",
        "tool_name": "search_courses",
        "expected_input_schema_digest": canonical_digest(
            {}, domain="fixture.mcp-input-schema:v1"
        ),
        "expected_output_schema_digest": canonical_digest(
            {}, domain="fixture.mcp-output-schema:v1"
        ),
        "semantics": McpOperationSemantics.READ_ONLY,
        "fixed_arguments": {"limit": 20},
        "argument_mapping_revision": "arguments-v1",
        "result_mapping_revision": "results-v1",
        "enabled": True,
    }
    return McpCapabilityMapping(
        mapping_digest=mcp_capability_mapping_digest(values),
        **values,
    )


def catalog_values(
    definitions,
    schema_documents,
    provider_descriptors,
    mcp_mappings,
):
    definitions = tuple(definitions)
    schema_documents = tuple(schema_documents)
    provider_descriptors = tuple(provider_descriptors)
    mcp_mappings = tuple(mcp_mappings)
    return {
        "schema_version": 1,
        "catalog_revision": capability_catalog_revision(
            definitions,
            schema_documents,
            provider_descriptors,
            mcp_mappings,
        ),
        "mapping_revision": capability_mapping_revision(mcp_mappings),
        "provider_registry_revision": capability_provider_registry_revision(
            provider_descriptors
        ),
        "definitions": definitions,
        "schema_documents": schema_documents,
        "provider_descriptors": provider_descriptors,
        "mcp_mappings": mcp_mappings,
    }


def query() -> CapabilityQuery:
    values = {
        "schema_version": 1,
        "intent_ids": ("course.search",),
        "natural_language_goal": "search cached course reviews",
        "entity_terms": ("database",),
        "required_output_schema": None,
        "preferred_categories": ("campus.course-review",),
        "excluded_side_effects": frozenset(
            {SideEffect.EXTERNAL_WRITE, SideEffect.MESSAGE_SEND}
        ),
        "maximum_risk_level": RiskLevel.LOW,
    }
    return CapabilityQuery(query_digest=capability_query_digest(values), **values)


def candidate(item: CapabilityDefinition, score: int = 100) -> CapabilityCandidate:
    values = {
        "schema_version": 1,
        "capability_id": item.capability_id,
        "definition_digest": item.definition_digest,
        "name": item.name,
        "description": item.description,
        "category": item.category,
        "provider": item.provider,
        "input_schema": item.input_schema,
        "output_schema": item.output_schema,
        "risk_level": item.risk_level,
        "privacy_level": item.privacy_level,
        "cost_hint": item.cost_hint,
        "latency_hint": item.latency_hint,
        "idempotency": item.idempotency,
        "side_effects": item.side_effects,
        "rank_score": score,
        "reason_codes": ("eligible",),
    }
    return CapabilityCandidate(
        candidate_digest=capability_candidate_digest(values),
        **values,
    )


def retrieval(item: CapabilityDefinition) -> CapabilityRetrievalResult:
    selected = candidate(item)
    values = {
        "schema_version": 1,
        "request_digest": canonical_digest({}, domain="fixture.retrieval-request:v1"),
        "query_digest": query().query_digest,
        "candidates": (selected,),
        "catalog_snapshot_id": "catalog-v1",
        "catalog_digest": canonical_digest({}, domain="fixture.catalog:v1"),
        "policy_revision": "policy-v1",
        "health_snapshot_id": "health-v1",
        "health_snapshot_digest": canonical_digest({}, domain="fixture.health:v1"),
        "retriever_revision": revision("capability.retriever"),
        "reason_codes": ("eligible_candidates",),
    }
    return CapabilityRetrievalResult(
        result_digest=capability_retrieval_result_digest(values),
        **values,
    )


def plan(item: CapabilityDefinition) -> ToolPlan:
    arguments = ArgumentTemplate(
        1,
        {"query": "database"},
        (
            ObservationBinding(
                1,
                "lookup",
                "/items/0/course_id",
                "/course_id",
            ),
        ),
    )
    step = ToolStep(
        1,
        "reviews",
        "reviews-operation",
        item.capability_id,
        item.definition_digest,
        arguments,
        "Read cached public reviews",
        ("lookup",),
        item.output_schema,
    )
    values = {
        "schema_version": 1,
        "plan_id": "plan-v1",
        "query_digest": query().query_digest,
        "retrieval_result_digest": retrieval(item).result_digest,
        "steps": (step,),
        "completion_criteria": (TOOL_COMPLETION_ALL_STEPS,),
        "planner_revision": revision("capability.planner"),
    }
    return ToolPlan(plan_digest=tool_plan_digest(values), **values)


def observation(item: CapabilityDefinition, tool_plan: ToolPlan) -> ToolObservation:
    values = {
        "schema_version": 1,
        "execution_request_digest": canonical_digest(
            {}, domain="fixture.execution-request:v1"
        ),
        "provider_invocation_digest": canonical_digest(
            {}, domain="fixture.provider-invocation:v1"
        ),
        "provider_result_digest": canonical_digest(
            {}, domain="fixture.provider-result:v1"
        ),
        "invocation_id": "invocation-v1",
        "plan_id": tool_plan.plan_id,
        "plan_digest": tool_plan.plan_digest,
        "step_id": tool_plan.steps[0].step_id,
        "logical_operation_id": tool_plan.steps[0].logical_operation_id,
        "capability_id": item.capability_id,
        "definition_digest": item.definition_digest,
        "catalog_snapshot_id": "catalog-v1",
        "catalog_digest": canonical_digest({}, domain="fixture.catalog:v1"),
        "provider": item.provider,
        "mapping_digest": mapping(item).mapping_digest,
        "policy_revision": "policy-v1",
        "idempotency_key": "tool-key-v1",
        "attempt": 1,
        "status": ToolExecutionStatus.SUCCEEDED,
        "data": {"items": [{"course_id": 1, "text": "untrusted text"}]},
        "error": None,
        "source_refs": ("icourse-cache",),
        "observed_at": NOW,
        "latency_ms": 10,
        "cache_status": "hit",
        "sensitivity": PrivacyLevel.PUBLIC,
        "usage": ResourceUsage(1, tool_steps=1, cost_units=Decimal(1)),
        "truncated": False,
        "untrusted": True,
    }
    return ToolObservation(
        observation_digest=tool_observation_digest(values),
        **values,
    )


class CapabilityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.input_document = schema("capability.icourse.search.input")
        self.output_document = schema("capability.icourse.search.output")
        self.definition = definition(
            self.input_document.schema_ref,
            self.output_document.schema_ref,
        )

    def test_definition_is_digest_bound_and_classification_is_not_mutable(self) -> None:
        self.assertEqual(
            self.definition.definition_digest,
            capability_definition_digest(self.definition),
        )
        with self.assertRaises(DududaError):
            replace(self.definition, risk_level=RiskLevel.CRITICAL)
        with self.assertRaises(FrozenInstanceError):
            self.definition.name = "changed"  # type: ignore[misc]
        with self.assertRaises(DududaError):
            replace(
                self.definition,
                idempotency=Idempotency.READ_ONLY,
                side_effects=frozenset({SideEffect.EXTERNAL_WRITE}),
            )

    def test_schema_and_mapping_are_deeply_frozen_and_digest_bound(self) -> None:
        with self.assertRaises(TypeError):
            self.input_document.document["type"] = "array"  # type: ignore[index]
        formal_mapping = mapping(self.definition)
        with self.assertRaises(TypeError):
            formal_mapping.fixed_arguments["limit"] = 100  # type: ignore[index]
        with self.assertRaises(DududaError):
            replace(formal_mapping, tool_name="crawl_course")

    def test_catalog_binds_definition_schema_provider_and_mcp_mapping(self) -> None:
        descriptor = provider_descriptor(self.definition)
        formal_mapping = mapping(self.definition)
        values = catalog_values(
            (self.definition,),
            (self.input_document, self.output_document),
            (descriptor,),
            (formal_mapping,),
        )
        snapshot = CapabilityCatalogSnapshot(
            snapshot_id="snapshot-v1",
            catalog_digest=capability_catalog_digest(values),
            acquired_at=NOW,
            **values,
        )
        self.assertEqual(snapshot.definitions, (self.definition,))
        with self.assertRaises(DududaError):
            replace(snapshot, mcp_mappings=())

    def test_catalog_rejects_ghost_surfaces_and_semantic_drift(self) -> None:
        descriptor = provider_descriptor(self.definition)
        descriptor_values = {
            "schema_version": 1,
            "provider": descriptor.provider,
            "kind": descriptor.kind,
            "capability_ids": frozenset(
                {self.definition.capability_id, "fixture.ghost.read.v1"}
            ),
        }
        ghost_descriptor = CapabilityProviderDescriptor(
            descriptor_digest=capability_provider_descriptor_digest(descriptor_values),
            **descriptor_values,
        )
        formal_mapping = mapping(self.definition)
        base = catalog_values(
            (self.definition,),
            (self.input_document, self.output_document),
            (ghost_descriptor,),
            (formal_mapping,),
        )
        with self.assertRaises(DududaError):
            CapabilityCatalogSnapshot(
                snapshot_id="snapshot-ghost",
                catalog_digest=capability_catalog_digest(base),
                acquired_at=NOW,
                **base,
            )

        mapping_values = {
            "schema_version": formal_mapping.schema_version,
            "capability_id": formal_mapping.capability_id,
            "capability_definition_digest": (
                formal_mapping.capability_definition_digest
            ),
            "server_id": formal_mapping.server_id,
            "tool_name": formal_mapping.tool_name,
            "expected_input_schema_digest": (
                formal_mapping.expected_input_schema_digest
            ),
            "expected_output_schema_digest": (
                formal_mapping.expected_output_schema_digest
            ),
            "semantics": McpOperationSemantics.IDEMPOTENT,
            "fixed_arguments": formal_mapping.fixed_arguments,
            "argument_mapping_revision": formal_mapping.argument_mapping_revision,
            "result_mapping_revision": formal_mapping.result_mapping_revision,
            "enabled": formal_mapping.enabled,
        }
        drifted_mapping = McpCapabilityMapping(
            mapping_digest=mcp_capability_mapping_digest(mapping_values),
            **mapping_values,
        )
        semantic_drift = catalog_values(
            (self.definition,),
            (self.input_document, self.output_document),
            (descriptor,),
            (drifted_mapping,),
        )
        with self.assertRaises(DududaError):
            CapabilityCatalogSnapshot(
                snapshot_id="snapshot-semantic-drift",
                catalog_digest=capability_catalog_digest(semantic_drift),
                acquired_at=NOW,
                **semantic_drift,
            )

    def test_candidate_and_retrieval_order_are_stable_and_tamper_evident(self) -> None:
        result = retrieval(self.definition)
        self.assertEqual(
            result.candidates[0].capability_id, self.definition.capability_id
        )
        with self.assertRaises(DududaError):
            replace(result.candidates[0], rank_score=101)

    def test_plan_observation_validation_and_run_receipt_are_bound(self) -> None:
        tool_plan = plan(self.definition)
        accepted = observation(self.definition, tool_plan)
        retrieved = retrieval(self.definition)
        plan_validation_values = {
            "schema_version": 1,
            "query": query(),
            "retrieval": retrieved,
            "plan": tool_plan,
            "maximum_attempts": 4,
            "maximum_cost_units": 4,
        }
        plan_validation_request = ToolPlanValidationRequest(
            request_digest=tool_plan_validation_request_digest(plan_validation_values),
            **plan_validation_values,
        )
        plan_validation_result_values = {
            "schema_version": 1,
            "request_digest": plan_validation_request.request_digest,
            "plan_digest": tool_plan.plan_digest,
            "valid": True,
            "reason_codes": ("plan_valid",),
            "validator_revision": revision("capability.plan-validator"),
        }
        plan_validation_result = ToolPlanValidationResult(
            result_digest=tool_plan_validation_result_digest(
                plan_validation_result_values
            ),
            **plan_validation_result_values,
        )
        result_validation_values = {
            "schema_version": 1,
            "retrieval": retrieved,
            "plan": tool_plan,
            "plan_validation_request": plan_validation_request,
            "plan_validation_result": plan_validation_result,
            "observations": (accepted,),
            "output_schemas": (self.output_document,),
            "maximum_attempts": 4,
        }
        result_validation_request = ToolValidationRequest(
            request_digest=tool_validation_request_digest(result_validation_values),
            **result_validation_values,
        )
        validation_values = {
            "schema_version": 1,
            "request_digest": result_validation_request.request_digest,
            "action": ValidationAction.FINISH,
            "accepted_observations": (accepted,),
            "retry_step_id": None,
            "clarification_key": None,
            "reason_codes": ("completion_satisfied",),
            "validator_revision": revision("capability.validator"),
        }
        validation = ToolValidationResult(
            result_digest=tool_validation_result_digest(validation_values),
            **validation_values,
        )
        actor = Actor("qq", "bot", "user", frozenset({RoleId("member")}))
        scope = ConversationScope(
            "qq",
            "bot",
            ConversationType.GROUP,
            "group",
            "group",
            "dududa",
        )
        run_request_values = {
            "schema_version": 1,
            "query": query(),
            "actor": actor,
            "conversation_scope": scope,
            "data_classification": PrivacyLevel.PUBLIC,
            "available_input_schemas": (self.input_document.schema_ref,),
            "maximum_attempts": 4,
        }
        run_request = CapabilityRunRequest(
            request_digest=capability_run_request_digest(run_request_values),
            **run_request_values,
        )
        receipt_values = {
            "schema_version": 1,
            "run_id": "run-v1",
            "request": run_request,
            "request_digest": run_request.request_digest,
            "status": CapabilityRunStatus.COMPLETED,
            "retrieval": retrieved,
            "plan": tool_plan,
            "observations": (accepted,),
            "unobserved_attempts": (),
            "validation_request": result_validation_request,
            "validation": validation,
            "usage": ResourceUsage(1, tool_steps=1, cost_units=Decimal(1)),
            "reason_codes": ("completed",),
            "completed_at": NOW + timedelta(seconds=1),
        }
        receipt = CapabilityRunReceipt(
            receipt_digest=capability_run_receipt_digest(receipt_values),
            **receipt_values,
        )
        self.assertIs(receipt.status, CapabilityRunStatus.COMPLETED)
        self.assertTrue(receipt.observations[0].untrusted)
        with self.assertRaises(DududaError):
            replace(receipt, observations=())
        with self.assertRaises(DududaError):
            replace(
                receipt,
                usage=ResourceUsage(1, tool_steps=1, cost_units=Decimal(2)),
            )

        duplicate_values = {
            name: getattr(accepted, name)
            for name in accepted.__dataclass_fields__
            if name != "observation_digest"
        }
        duplicate_values.update(
            {
                "execution_request_digest": canonical_digest(
                    {"attempt": 2}, domain="fixture.execution-request:v1"
                ),
                "provider_invocation_digest": canonical_digest(
                    {"attempt": 2}, domain="fixture.provider-invocation:v1"
                ),
                "provider_result_digest": canonical_digest(
                    {"attempt": 2}, domain="fixture.provider-result:v1"
                ),
                "invocation_id": "invocation-v2",
                "attempt": 2,
                "usage": ResourceUsage(
                    1,
                    tool_steps=1,
                    retries=1,
                    cost_units=Decimal(1),
                ),
            }
        )
        duplicate = ToolObservation(
            observation_digest=tool_observation_digest(duplicate_values),
            **duplicate_values,
        )
        duplicate_request_values = {
            **result_validation_values,
            "observations": (accepted, duplicate),
        }
        duplicate_request = ToolValidationRequest(
            request_digest=tool_validation_request_digest(duplicate_request_values),
            **duplicate_request_values,
        )
        duplicate_validation_values = {
            **validation_values,
            "request_digest": duplicate_request.request_digest,
            "accepted_observations": (accepted, duplicate),
        }
        duplicate_validation = ToolValidationResult(
            result_digest=tool_validation_result_digest(duplicate_validation_values),
            **duplicate_validation_values,
        )
        duplicate_receipt_values = {
            **receipt_values,
            "observations": (accepted, duplicate),
            "validation_request": duplicate_request,
            "validation": duplicate_validation,
            "usage": ResourceUsage(
                1,
                tool_steps=2,
                retries=1,
                cost_units=Decimal(2),
            ),
        }
        with self.assertRaises(DududaError):
            CapabilityRunReceipt(
                receipt_digest=capability_run_receipt_digest(
                    duplicate_receipt_values
                ),
                **duplicate_receipt_values,
            )

    def test_execution_context_reuses_actor_and_exact_conversation_scope(self) -> None:
        actor = Actor("qq", "bot", "user", frozenset({RoleId("member")}))
        scope = ConversationScope(
            "qq",
            "bot",
            ConversationType.GROUP,
            "group",
            "group",
            "dududa",
        )
        context = CapabilityExecutionContext(1, actor, scope, PrivacyLevel.PUBLIC)
        self.assertEqual(context.conversation_scope, scope)
        with self.assertRaises(DududaError):
            CapabilityExecutionContext(
                1,
                replace(actor, bot_id="other"),
                scope,
                PrivacyLevel.PUBLIC,
            )

    def test_execution_and_result_validation_carry_full_plan_evidence(self) -> None:
        tool_plan = plan(self.definition)
        retrieved = retrieval(self.definition)
        validation_request_values = {
            "schema_version": 1,
            "query": query(),
            "retrieval": retrieved,
            "plan": tool_plan,
            "maximum_attempts": 4,
            "maximum_cost_units": 4,
        }
        validation_request = ToolPlanValidationRequest(
            request_digest=tool_plan_validation_request_digest(
                validation_request_values
            ),
            **validation_request_values,
        )
        validation_result_values = {
            "schema_version": 1,
            "request_digest": validation_request.request_digest,
            "plan_digest": tool_plan.plan_digest,
            "valid": True,
            "reason_codes": ("plan_valid",),
            "validator_revision": revision("capability.plan-validator"),
        }
        validation_result = ToolPlanValidationResult(
            result_digest=tool_plan_validation_result_digest(validation_result_values),
            **validation_result_values,
        )
        actor = Actor("qq", "bot", "user", frozenset({RoleId("member")}))
        scope = ConversationScope(
            "qq",
            "bot",
            ConversationType.GROUP,
            "group",
            "group",
            "dududa",
        )
        step = tool_plan.steps[0]
        execution_values = {
            "schema_version": 1,
            "invocation_id": "invocation-v1",
            "plan_id": tool_plan.plan_id,
            "plan_digest": tool_plan.plan_digest,
            "plan_validation_request": validation_request,
            "plan_validation_result": validation_result,
            "step_id": step.step_id,
            "logical_operation_id": step.logical_operation_id,
            "capability_id": step.capability_id,
            "definition_digest": step.definition_digest,
            "catalog_snapshot_id": retrieved.catalog_snapshot_id,
            "catalog_digest": retrieved.catalog_digest,
            "provider": self.definition.provider,
            "mapping_digest": mapping(self.definition).mapping_digest,
            "resolved_arguments": {"query": "database"},
            "source_invocation_ids": (),
            "idempotency_key": "tool-key-v1",
            "attempt": 1,
            "context": CapabilityExecutionContext(
                1,
                actor,
                scope,
                PrivacyLevel.PUBLIC,
            ),
        }
        execution = ToolExecutionRequest(
            request_digest=tool_execution_request_digest(execution_values),
            **execution_values,
        )
        self.assertEqual(
            execution.plan_validation_result,
            validation_result,
        )
        with self.assertRaises(DududaError):
            replace(execution, step_id="foreign-step")

        accepted = observation(self.definition, tool_plan)
        result_validation_values = {
            "schema_version": 1,
            "retrieval": retrieved,
            "plan": tool_plan,
            "plan_validation_request": validation_request,
            "plan_validation_result": validation_result,
            "observations": (accepted,),
            "output_schemas": (self.output_document,),
            "maximum_attempts": 4,
        }
        result_validation = ToolValidationRequest(
            request_digest=tool_validation_request_digest(result_validation_values),
            **result_validation_values,
        )
        self.assertEqual(result_validation.maximum_attempts, 4)
        with self.assertRaises(DududaError):
            replace(result_validation, maximum_attempts=0)


if __name__ == "__main__":
    unittest.main()
