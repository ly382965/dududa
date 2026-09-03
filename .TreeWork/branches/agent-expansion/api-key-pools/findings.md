# Findings

Branch: api-key-pools

## Decisions

- AstrBot's native `provider_sources.key` list is the downstream compatibility
  shape; Sub2API-style per-key metadata belongs in the Dududa control surface,
  not in the Core tier decision contract.
- A raw secret is write-only at the Web API boundary. Masked values and a
  SecretRef are sufficient for operator confirmation and avoid a second secret
  reader in the browser.

## Interface Or Contract Effects

- Adds the versioned Web `/api/api-keys` contract and an external secret-store
  path configured by environment.
- Does not modify `ModelTier`, `TierPolicy`, `ModelEndpointDescriptor` or
  Control Plane group profiles.
