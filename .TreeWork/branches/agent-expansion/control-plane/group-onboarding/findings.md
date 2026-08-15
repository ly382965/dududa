# Findings

Branch: group-onboarding

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- SQLite persists revision evidence bound into Preview/Assignment plus complete
  assignment history; it does not duplicate the mutable Catalog/Profile objects
  as a second source of truth.
- Pending-only discovery is insufficient: activation intentionally removes a
  group from the pending query. A separate authorized managed-group projection
  restores current Assignment and onboarding revision after restart.
- Preview execution returns the committed onboarding revision. Revision
  arithmetic remains server-owned rather than being inferred by Vue.
- Python owns an explicit, narrow Web DTO projection. Generic recursive casing
  conversion would miss flattened `ProfileRef` and
  `receipt.result_digest -> previewDigest` semantics.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added `ManagedGroupsQuery/Projection`, repository assignment listing and
  `ControlPlaneApi.managed_groups()`.
- Added SQLite lifecycle persistence, immutable Runtime snapshot provider and
  Profile/Catalog/Preview/Lifecycle contracts under `dududa.control_plane`.
- Added Web routes for pending, managed, profiles, preview and lifecycle
  commands; `DUDUDA_CONTROL_PLANE_URL` selects the upstream Core adapter and is
  explicitly unavailable when absent.
- Added `/control-plane` to the existing Vue workspace. The page consumes
  Desired/Effective, Assignment and Receipt projections and never calls NapCat
  for Agent behavior.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- A production operator identity resolver and HTTP binding are intentionally
  absent; deployment must implement the existing session/API contracts before
  the page can mutate real state.
- Real Profile choices, service health/grants and administrator role mappings
  are external product/deployment inputs. Fake evidence proves mechanics, not
  real service readiness or group experience.
