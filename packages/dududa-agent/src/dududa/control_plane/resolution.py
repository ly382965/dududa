from __future__ import annotations

from dududa.errors import validation_error

from .contracts import (
    GroupServiceProfile,
    ServiceCatalogSnapshot,
    ServiceResolution,
)


def resolve_profile_services(
    profile: GroupServiceProfile,
    catalog: ServiceCatalogSnapshot,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[ServiceResolution, ...]]:
    if not isinstance(profile, GroupServiceProfile):
        raise validation_error("invalid_group_service_profile")
    if not isinstance(catalog, ServiceCatalogSnapshot):
        raise validation_error("invalid_service_catalog_snapshot")
    definitions = {item.service_id: item for item in catalog.definitions}
    facts = {item.service_id: item for item in catalog.eligibility}
    desired = profile.requested_service_ids
    effective: list[str] = []
    resolutions: list[ServiceResolution] = []
    for service_id in desired:
        reasons: list[str] = []
        if service_id not in definitions:
            reasons.append("service_definition_missing")
        fact = facts.get(service_id)
        if fact is None:
            reasons.append("service_fact_missing")
        else:
            if not fact.installed:
                reasons.append("service_not_installed")
            if not fact.healthy:
                reasons.append("service_unhealthy")
            if not fact.granted:
                reasons.append("service_not_granted")
            if not fact.rollout_eligible:
                reasons.append("service_rollout_ineligible")
        eligible = not reasons
        if eligible:
            effective.append(service_id)
        resolutions.append(ServiceResolution(1, service_id, eligible, tuple(reasons)))
    return desired, tuple(effective), tuple(resolutions)


__all__ = ["resolve_profile_services"]
