from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from dududa.capabilities import (
    CapabilityProviderKind,
    CapabilitySchemaDocument,
    McpCapabilityMapping,
    capability_definition_digest,
    mcp_capability_mapping_digest,
)
from dududa.contracts.canonical import canonical_digest, canonical_schema_digest
from dududa.domain.capability import (
    CapabilityDefinition,
    CostHint,
    Idempotency,
    LatencyHint,
    ProviderRef,
)
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    PrivacyLevel,
    RiskLevel,
    SchemaRef,
    SideEffect,
)
from dududa.mcp import McpOperationSemantics

ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = Path("configs/capabilities")

MCP_SCHEMA_DIGESTS = {
    "icourse_public_query": (
        (
            "dududa-c14n-v1:schema:mcp.icourse.icourse_public_query.input:v1:sha-256:"
            "d09687a2302978a6c10ae61c6608f1dd2b1a5f114db649f62d14454fb5306f57"
        ),
        (
            "dududa-c14n-v1:schema:mcp.icourse.icourse_public_query.output:v1:sha-256:"
            "1727a4da37920ad2f4004b50e553e763684b8865d35b01ff07a27bc32f683974"
        ),
    ),
    "icourse_stats": (
        (
            "dududa-c14n-v1:schema:mcp.icourse.icourse_stats.input:v1:sha-256:"
            "1b2e282ec8683d1a8aeb23e007bbe6d29b208311a5c50d7059861b8657c1c635"
        ),
        (
            "dududa-c14n-v1:schema:mcp.icourse.icourse_stats.output:v1:sha-256:"
            "d4402cf4143aba39683d2dd3e6967d058255f8ec1f557e7b69137a4f21dc4731"
        ),
    ),
    "search_courses": (
        (
            "dududa-c14n-v1:schema:mcp.icourse.search_courses.input:v1:sha-256:"
            "eb5a25abf393fa95b8fe53389989ceac191ff71f43c3221e0c914abc32c4cae9"
        ),
        (
            "dududa-c14n-v1:schema:mcp.icourse.search_courses.output:v1:sha-256:"
            "98b28997e3dda127d134ac6b859c6c284e0eab4f24cb171285410dec3ee9a945"
        ),
    ),
    "get_course": (
        (
            "dududa-c14n-v1:schema:mcp.icourse.get_course.input:v1:sha-256:"
            "a5522c2fabc11ea6ebdf9f572a0ad40d689b2530da67be89bb77fc3a588525d4"
        ),
        (
            "dududa-c14n-v1:schema:mcp.icourse.get_course.output:v1:sha-256:"
            "fd38765657a7abd4ade4b321e15fa0755049627cab66c93e8095d3fbfa1bc740"
        ),
    ),
    "get_reviews": (
        (
            "dududa-c14n-v1:schema:mcp.icourse.get_reviews.input:v1:sha-256:"
            "85d3f1c43cc1c8d8e0785a26c44b706d449901b43c9d329dd40f8aeb13e53140"
        ),
        (
            "dududa-c14n-v1:schema:mcp.icourse.get_reviews.output:v1:sha-256:"
            "c7fe6448be89eb3d10a736fdfac33227af1d3e1610ffde1d9c2ea403590263b5"
        ),
    ),
}


def _nullable_string(maximum: int) -> dict[str, object]:
    return {"type": ["string", "null"], "maxLength": maximum}


def _nullable_integer(*, minimum: int = 0) -> dict[str, object]:
    return {"type": ["integer", "null"], "minimum": minimum}


def _nullable_number(*, minimum: int = 0) -> dict[str, object]:
    return {"type": ["number", "null"], "minimum": minimum}


def _teacher_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "id": _nullable_integer(),
            "name": {"type": "string", "maxLength": 200},
            "dept": _nullable_string(300),
        },
        "required": ["id", "name", "dept"],
        "additionalProperties": False,
    }


def _review_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "minimum": 1},
            "course_id": {"type": "integer", "minimum": 1},
            "url": {"type": "string", "maxLength": 2_048},
            "author_display": _nullable_string(200),
            "is_anonymous": {"type": "boolean"},
            "term": _nullable_string(100),
            "rating_10": _nullable_integer(),
            "difficulty": _nullable_string(100),
            "homework": _nullable_string(100),
            "grading": _nullable_string(100),
            "gain": _nullable_string(100),
            "content_text": _nullable_string(20_000),
            "publish_time": _nullable_string(64),
            "update_time": _nullable_string(64),
            "upvote_count": _nullable_integer(),
            "comment_count": _nullable_integer(),
        },
        "required": [
            "id",
            "course_id",
            "url",
            "author_display",
            "is_anonymous",
            "term",
            "rating_10",
            "difficulty",
            "homework",
            "grading",
            "gain",
            "content_text",
            "publish_time",
            "update_time",
            "upvote_count",
            "comment_count",
        ],
        "additionalProperties": False,
    }


def _course_summary_properties() -> dict[str, object]:
    return {
        "id": {"type": "integer", "minimum": 1},
        "name": {"type": "string", "maxLength": 300},
        "url": {"type": "string", "maxLength": 2_048},
        "teachers": {
            "type": "array",
            "maxItems": 32,
            "items": _teacher_schema(),
        },
        "term_text": _nullable_string(300),
        "courseries": _nullable_string(300),
        "dept": _nullable_string(300),
        "course_type": _nullable_string(200),
        "join_type": _nullable_string(100),
        "teaching_type": _nullable_string(100),
        "course_level": _nullable_string(100),
        "credit": _nullable_number(),
        "rating_average": _nullable_number(),
        "review_count_site": _nullable_integer(),
        "visible_review_count": _nullable_integer(),
        "missing_review_count_estimate": _nullable_integer(),
        "difficulty": _nullable_string(100),
        "homework": _nullable_string(100),
        "grading": _nullable_string(100),
        "gain": _nullable_string(100),
    }


def _course_summary_schema() -> dict[str, object]:
    properties = _course_summary_properties()
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _course_detail_schema() -> dict[str, object]:
    properties = {
        **_course_summary_properties(),
        "term_ids": {
            "type": "array",
            "maxItems": 64,
            "items": {"type": "string", "maxLength": 100},
        },
        "homepage": _nullable_string(2_048),
        "introduction_text": _nullable_string(20_000),
        "summary_text": _nullable_string(20_000),
        "reviews": {
            "type": "array",
            "maxItems": 200,
            "items": _review_schema(),
        },
    }
    required = [name for name in properties if name != "reviews"]
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _public_query_course_schema() -> dict[str, object]:
    properties = {
        **_course_summary_properties(),
        "normalized_rating": _nullable_number(),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": [],
        "additionalProperties": False,
    }


def _public_query_review_schema() -> dict[str, object]:
    properties = {
        **_review_schema()["properties"],
        "course_name": _nullable_string(300),
        "course_url": _nullable_string(2_048),
        "course_teachers": {
            "type": "array",
            "maxItems": 32,
            "items": _teacher_schema(),
        },
        "course_rating_average": _nullable_number(),
        "content_length": {"type": "integer", "minimum": 0},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": [],
        "additionalProperties": False,
    }


def _public_query_review_evidence_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "course_id": {"type": "integer", "minimum": 1},
            "course_name": _nullable_string(300),
            "course_teachers": {
                "type": "array",
                "maxItems": 32,
                "items": _teacher_schema(),
            },
            "course_rating_average": _nullable_number(),
            "samples": {
                "type": "array",
                "maxItems": 2,
                "items": _public_query_review_schema(),
            },
        },
        "required": ["samples"],
        "additionalProperties": False,
    }


def _public_query_item_schema() -> dict[str, object]:
    teacher_course = {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "minimum": 1},
            "name": {"type": "string", "maxLength": 300},
            "url": {"type": "string", "maxLength": 2_048},
            "term_text": _nullable_string(300),
            "rating_average": _nullable_number(),
            "review_count_site": _nullable_integer(),
            "difficulty": _nullable_string(100),
            "homework": _nullable_string(100),
            "grading": _nullable_string(100),
            "gain": _nullable_string(100),
        },
        "required": [],
        "additionalProperties": False,
    }
    properties = {
        **_public_query_course_schema()["properties"],
        **_public_query_review_schema()["properties"],
        "teacher_id": _nullable_integer(),
        "departments": {
            "type": "array",
            "maxItems": 32,
            "items": {"type": "string", "maxLength": 300},
        },
        "course_count": {"type": "integer", "minimum": 0},
        "review_count": {"type": "integer", "minimum": 0},
        "courses": {
            "type": "array",
            "maxItems": 20,
            "items": teacher_course,
        },
    }
    return {
        "type": "object",
        "properties": properties,
        "required": [],
        "additionalProperties": False,
    }


def _public_cache_coverage_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "courses": {"type": "integer", "minimum": 0},
            "courses_with_detail": {"type": "integer", "minimum": 0},
            "public_reviews": {"type": "integer", "minimum": 0},
            "last_detail_crawled_at": _nullable_string(64),
            "last_list_crawled_at": _nullable_string(64),
        },
        "required": [
            "courses",
            "courses_with_detail",
            "public_reviews",
            "last_detail_crawled_at",
            "last_list_crawled_at",
        ],
        "additionalProperties": False,
    }


def _public_query_result_schema() -> dict[str, object]:
    distribution_item = {
        "type": "object",
        "properties": {
            "bucket": _nullable_integer(),
            "rating": _nullable_integer(),
            "month": _nullable_string(16),
            "count": {"type": "integer", "minimum": 0},
        },
        "required": ["count"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "total": {"type": "integer", "minimum": 0},
            "items": {
                "type": "array",
                "maxItems": 30,
                "items": _public_query_item_schema(),
            },
            "review_evidence": {
                "type": "array",
                "maxItems": 7,
                "items": _public_query_review_evidence_schema(),
            },
            "review_sampled_course_count": {
                "type": "integer",
                "minimum": 0,
                "maximum": 7,
            },
            "aggregates": {
                "type": "object",
                "properties": {
                    "distinct_courses": {"type": "integer", "minimum": 0},
                    "total_upvotes": {"type": "integer", "minimum": 0},
                    "average_rating": {"type": "number", "minimum": 0},
                    "average_length": {"type": "number", "minimum": 0},
                },
                "required": [
                    "distinct_courses",
                    "total_upvotes",
                    "average_rating",
                    "average_length",
                ],
                "additionalProperties": False,
            },
            "source": {"type": "string", "maxLength": 100},
            "coverage": _public_cache_coverage_schema(),
            "formula": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 100},
                    "global_average": {"type": "number", "minimum": 0},
                    "prior_review_count": {"type": "number", "minimum": 0},
                },
                "required": ["name", "global_average", "prior_review_count"],
                "additionalProperties": False,
            },
            "top_courses": {
                "type": "array",
                "maxItems": 30,
                "items": _public_query_course_schema(),
            },
            "low_courses": {
                "type": "array",
                "maxItems": 30,
                "items": _public_query_course_schema(),
            },
            "popular_courses": {
                "type": "array",
                "maxItems": 30,
                "items": _public_query_course_schema(),
            },
            "top_reviews": {
                "type": "array",
                "maxItems": 30,
                "items": _public_query_review_schema(),
            },
            "longest_reviews": {
                "type": "array",
                "maxItems": 30,
                "items": _public_query_review_schema(),
            },
            "average_review_rating": _nullable_number(),
            "course_rating_distribution": {
                "type": "array",
                "maxItems": 32,
                "items": distribution_item,
            },
            "review_rating_distribution": {
                "type": "array",
                "maxItems": 32,
                "items": distribution_item,
            },
            "review_timeline": {
                "type": "array",
                "maxItems": 1_000,
                "items": distribution_item,
            },
        },
        "required": [],
        "additionalProperties": False,
    }


def _schemas() -> dict[str, tuple[dict[str, object], dict[str, object]]]:
    public_query_input = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 200},
            "goal": _nullable_string(4_000),
            "operation": {
                "type": "string",
                "enum": ["course", "review", "teacher", "ranking", "stats"],
                "maxLength": 16,
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 30},
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    public_query_output = {
        "type": "object",
        "properties": {
            "schema_version": {"type": "integer", "const": 1},
            "operation": {
                "type": "string",
                "enum": ["course", "review", "teacher", "ranking", "stats"],
                "maxLength": 16,
            },
            "query": {"type": "string", "maxLength": 4_000},
            "public_only": {"type": "boolean", "const": True},
            "result": _public_query_result_schema(),
        },
        "required": [
            "schema_version",
            "operation",
            "query",
            "public_only",
            "result",
        ],
        "additionalProperties": False,
    }
    stats_input = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    stats_output = {
        "type": "object",
        "properties": {
            "courses": {"type": "integer", "minimum": 0},
            "courses_with_detail": {"type": "integer", "minimum": 0},
            "public_reviews": {"type": "integer", "minimum": 0},
            "last_detail_crawled_at": _nullable_string(64),
            "last_list_crawled_at": _nullable_string(64),
        },
        "required": [
            "courses",
            "courses_with_detail",
            "public_reviews",
            "last_detail_crawled_at",
            "last_list_crawled_at",
        ],
        "additionalProperties": False,
    }
    search_input = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 200},
            "teacher": _nullable_string(200),
            "dept": _nullable_string(300),
            "course_type": _nullable_string(200),
            "min_rating": {
                "type": ["number", "null"],
                "minimum": 0,
                "maximum": 10,
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "offset": {"type": "integer", "minimum": 0, "maximum": 10_000},
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    search_output = {
        "type": "object",
        "properties": {
            "total": {"type": "integer", "minimum": 0},
            "items": {
                "type": "array",
                "maxItems": 100,
                "items": _course_summary_schema(),
            },
        },
        "required": ["total", "items"],
        "additionalProperties": False,
    }
    course_input = {
        "type": "object",
        "properties": {
            "course_id": {"type": "integer", "minimum": 1},
            "include_reviews": {"type": "boolean"},
            "refresh": {"type": "boolean", "const": False},
        },
        "required": ["course_id", "refresh"],
        "additionalProperties": False,
    }
    course_output = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean", "const": True},
            "course": _course_detail_schema(),
            "public_only": {"type": "boolean", "const": True},
        },
        "required": ["ok", "course", "public_only"],
        "additionalProperties": False,
    }
    reviews_input = {
        "type": "object",
        "properties": {
            "course_id": {"type": "integer", "minimum": 1},
            "term": _nullable_string(100),
            "rating": {
                "type": ["integer", "null"],
                "minimum": 1,
                "maximum": 5,
            },
            "sort_by": {
                "type": "string",
                "enum": [
                    "upvote",
                    "pubtime_desc",
                    "pubtime",
                    "score_desc",
                    "score",
                ],
                "maxLength": 20,
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "required": ["course_id"],
        "additionalProperties": False,
    }
    reviews_output = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean", "const": True},
            "course_id": {"type": "integer", "minimum": 1},
            "reviews": {
                "type": "array",
                "maxItems": 200,
                "items": _review_schema(),
            },
            "public_only": {"type": "boolean", "const": True},
        },
        "required": ["ok", "course_id", "reviews", "public_only"],
        "additionalProperties": False,
    }
    return {
        "icourse.public-query.v2": (public_query_input, public_query_output),
        "icourse.stats.read.v1": (stats_input, stats_output),
        "icourse.courses.search.v1": (search_input, search_output),
        "icourse.course.get.v1": (course_input, course_output),
        "icourse.reviews.get.v1": (reviews_input, reviews_output),
    }


def _provider() -> ProviderRef:
    artifact = canonical_digest(
        {
            "adapter": "dududa.capabilities.McpCapabilityProvider",
            "argument_mapping": "identity-v1",
            "result_mapping": "schema-project-v1",
        },
        domain="capability.provider-artifact:v1",
    )
    return ProviderRef(
        "mcp.icourse",
        ComponentRevision(
            "capability-provider.mcp",
            "1.0.0",
            "icourse-public-read-v1",
            DigestString(str(artifact)),
        ),
    )


def _schema_document(schema_id: str, value: dict[str, object]):
    reference = SchemaRef(
        schema_id,
        1,
        canonical_schema_digest(value, schema_id=schema_id, schema_version=1),
    )
    return CapabilitySchemaDocument(1, reference, value)


def _definition(
    capability_id: str,
    *,
    name: str,
    description: str,
    tags: frozenset[str],
    cost_units: int,
    input_schema: CapabilitySchemaDocument,
    output_schema: CapabilitySchemaDocument,
) -> CapabilityDefinition:
    values = {
        "schema_version": 1,
        "capability_id": capability_id,
        "name": name,
        "description": description,
        "category": "campus.course-review",
        "provider": _provider(),
        "input_schema": input_schema.schema_ref,
        "output_schema": output_schema.schema_ref,
        "risk_level": RiskLevel.LOW,
        # Public results may still be queried with conversation-scoped input text.
        "privacy_level": PrivacyLevel.CONVERSATION,
        "allowed_contexts": frozenset(
            {ConversationType.PRIVATE, ConversationType.GROUP}
        ),
        "required_permissions": frozenset({"capability.icourse.read"}),
        "cost_hint": CostHint(cost_units),
        "latency_hint": LatencyHint(20, 2_000),
        "tags": tags,
        "idempotency": Idempotency.READ_ONLY,
        "side_effects": frozenset({SideEffect.NONE}),
        "enabled": True,
    }
    return CapabilityDefinition(
        definition_digest=capability_definition_digest(values),
        **values,
    )


def _mapping(
    definition: CapabilityDefinition,
    *,
    tool_name: str,
    fixed_arguments: Mapping[str, object],
) -> McpCapabilityMapping:
    input_digest, output_digest = MCP_SCHEMA_DIGESTS[tool_name]
    values = {
        "schema_version": 1,
        "capability_id": definition.capability_id,
        "capability_definition_digest": definition.definition_digest,
        "server_id": "icourse",
        "tool_name": tool_name,
        "expected_input_schema_digest": DigestString(input_digest),
        "expected_output_schema_digest": DigestString(output_digest),
        "semantics": McpOperationSemantics.READ_ONLY,
        "fixed_arguments": fixed_arguments,
        "argument_mapping_revision": "identity-v1",
        "result_mapping_revision": "schema-project-v1",
        "enabled": True,
    }
    return McpCapabilityMapping(
        mapping_digest=mcp_capability_mapping_digest(values),
        **values,
    )


def _plain(value):
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _schema_config(document: CapabilitySchemaDocument) -> dict[str, object]:
    reference = document.schema_ref
    return {
        "schema_id": reference.schema_id,
        "schema_version": reference.schema_version,
        "digest": str(reference.digest),
        "document": _plain(document.document),
    }


def _definition_config(
    definition: CapabilityDefinition,
    input_schema: CapabilitySchemaDocument,
    output_schema: CapabilitySchemaDocument,
) -> dict[str, object]:
    revision = definition.provider.revision
    return {
        "schema_version": definition.schema_version,
        "capability_id": definition.capability_id,
        "definition_digest": str(definition.definition_digest),
        "name": definition.name,
        "description": definition.description,
        "category": definition.category,
        "provider": {
            "provider_id": definition.provider.provider_id,
            "revision": {
                "component_id": revision.component_id,
                "implementation_version": revision.implementation_version,
                "config_revision": revision.config_revision,
                "artifact_digest": str(revision.artifact_digest),
            },
        },
        "provider_kind": CapabilityProviderKind.MCP.value,
        "input_schema": _schema_config(input_schema),
        "output_schema": _schema_config(output_schema),
        "risk_level": definition.risk_level.value,
        "privacy_level": definition.privacy_level.value,
        "allowed_contexts": sorted(item.value for item in definition.allowed_contexts),
        "required_permissions": sorted(definition.required_permissions),
        "cost_hint_units": definition.cost_hint.units,
        "latency_hint": {
            "expected_ms": definition.latency_hint.expected_ms,
            "maximum_ms": definition.latency_hint.maximum_ms,
        },
        "tags": sorted(definition.tags),
        "idempotency": definition.idempotency.value,
        "side_effects": sorted(item.value for item in definition.side_effects),
        "enabled": definition.enabled,
    }


def _mapping_config(mapping: McpCapabilityMapping) -> dict[str, object]:
    return {
        "schema_version": mapping.schema_version,
        "capability_id": mapping.capability_id,
        "capability_definition_digest": str(mapping.capability_definition_digest),
        "server_id": mapping.server_id,
        "tool_name": mapping.tool_name,
        "expected_input_schema_digest": str(mapping.expected_input_schema_digest),
        "expected_output_schema_digest": str(mapping.expected_output_schema_digest),
        "semantics": mapping.semantics.value,
        "fixed_arguments": _plain(mapping.fixed_arguments),
        "argument_mapping_revision": mapping.argument_mapping_revision,
        "result_mapping_revision": mapping.result_mapping_revision,
        "enabled": mapping.enabled,
        "mapping_digest": str(mapping.mapping_digest),
    }


def rendered_documents() -> dict[Path, str]:
    metadata = {
        "icourse.public-query.v2": (
            "Query public iCourse data",
            (
                "Run one bounded public course, review, teacher, ranking or "
                "statistics query."
            ),
            frozenset(
                {
                    "course",
                    "course-review",
                    "icourse",
                    "ranking",
                    "review",
                    "statistics",
                    "teacher",
                }
            ),
            2,
            "icourse_public_query",
            {},
        ),
        "icourse.stats.read.v1": (
            "Read live iCourse public statistics",
            "Read current public iCourse site counts without using the local cache.",
            frozenset({"course", "icourse", "live", "statistics"}),
            1,
            "icourse_stats",
            {},
        ),
        "icourse.courses.search.v1": (
            "Search live iCourse courses",
            "Search current public course-review data on icourse.club.",
            frozenset({"course", "course-review", "icourse", "live", "search"}),
            1,
            "search_courses",
            {},
        ),
        "icourse.course.get.v1": (
            "Read one live iCourse course",
            "Read one current public course page from icourse.club.",
            frozenset({"course", "course-review", "detail", "icourse", "live"}),
            2,
            "get_course",
            {"refresh": False},
        ),
        "icourse.reviews.get.v1": (
            "Read live iCourse reviews",
            "Read current public reviews from one icourse.club course page.",
            frozenset({"course", "course-review", "icourse", "live", "review"}),
            1,
            "get_reviews",
            {},
        ),
    }
    documents: dict[Path, str] = {}
    for capability_id, (input_value, output_value) in _schemas().items():
        input_schema = _schema_document(
            f"capability.{capability_id}.input",
            input_value,
        )
        output_schema = _schema_document(
            f"capability.{capability_id}.output",
            output_value,
        )
        name, description, tags, cost, tool_name, fixed = metadata[capability_id]
        definition = _definition(
            capability_id,
            name=name,
            description=description,
            tags=tags,
            cost_units=cost,
            input_schema=input_schema,
            output_schema=output_schema,
        )
        mapping = _mapping(
            definition,
            tool_name=tool_name,
            fixed_arguments=fixed,
        )
        documents[CONFIG_ROOT / "definitions" / f"{capability_id}.json"] = _json(
            _definition_config(definition, input_schema, output_schema)
        )
        documents[CONFIG_ROOT / "mappings" / f"{capability_id}.json"] = _json(
            _mapping_config(mapping)
        )
    return documents


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _write(root: Path) -> None:
    for relative, content in rendered_documents().items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _check(root: Path) -> bool:
    mismatches = []
    for relative, expected in rendered_documents().items():
        target = root / relative
        try:
            actual = target.read_text(encoding="utf-8")
        except OSError:
            actual = None
        if actual != expected:
            mismatches.append(str(relative))
    if mismatches:
        print("outdated iCourse Capability configuration:")
        for item in mismatches:
            print(f"- {item}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.write:
        _write(args.root)
        return 0
    return 0 if _check(args.root) else 1


if __name__ == "__main__":
    raise SystemExit(main())
