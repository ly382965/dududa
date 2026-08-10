from __future__ import annotations

from collections.abc import Iterable

from dududa.contracts.canonical import canonical_digest


def capability_catalog_revision(
    definitions: Iterable[object],
    schema_documents: Iterable[object],
    provider_descriptors: Iterable[object],
    mcp_mappings: Iterable[object],
) -> str:
    return _revision(
        "catalog",
        {
            "definitions": tuple(definitions),
            "schema_documents": tuple(schema_documents),
            "provider_descriptors": tuple(provider_descriptors),
            "mcp_mappings": tuple(mcp_mappings),
        },
        domain="capability.catalog-revision:v1",
    )


def capability_mapping_revision(mappings: Iterable[object]) -> str:
    return _revision(
        "mapping",
        tuple(mappings),
        domain="capability.mapping-revision:v1",
    )


def capability_provider_registry_revision(
    descriptors: Iterable[object],
) -> str:
    return _revision(
        "providers",
        tuple(descriptors),
        domain="capability.provider-registry-revision:v1",
    )


def _revision(prefix: str, value: object, *, domain: str) -> str:
    digest = str(canonical_digest(value, domain=domain))
    return f"{prefix}-{digest.rsplit(':', maxsplit=1)[1]}"


__all__ = [
    "capability_catalog_revision",
    "capability_mapping_revision",
    "capability_provider_registry_revision",
]
