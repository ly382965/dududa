# Branch Spec

Branch: plugin-group-controls
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

Merge the exact PR12 head (Emoji Kitchen) into current main without replacing
newer Runtime fixes. Repair demonstrated request/permission defects before the
integrated release. Retain PR ancestry so GitHub recognizes the requested merge.

The existing account/conversation Scope Policy remains the sole group control
store, with the existing authenticated same-origin save route and atomic writes.
Expose obvious group-only on/off switches beside the existing advanced plugin
modes. Enabling selects on (auto for passive behavior), disabling selects off;
changing a draft does not send a message or save implicitly. Core uses the
existing conversation master switch; Shuttle/Sub2API retain existing policy
paths. Add catalog entries for Arc compatibility and Emoji Kitchen and connect
Reread, Arc and Emoji execution to exact account/group policy checks. New
unmanaged groups remain off when the Web policy store is configured. Honor
conversation disable, malformed/missing policy and non-group inputs. Standalone
plugin installations without a Dududa policy path retain their existing global
configuration behavior. No new framework/host-wide plugin unload endpoint.

Check policy before network/state/output and recheck after await before an
observable response. Preserve existing sensitive Sub2API access restrictions,
Arc allowlists and separately disabled B50. No new live test messages or score
lookup. Preserve existing per-group settings; if needed, migrate only already
explicit legacy-enabled scopes and absent new fields with a private backup.

Only existing Dududa Web/AstrBot/MCP Console/NapCat are deployment targets, not
the separate docs website, other sites/proxies/auth/databases. Build all changed
components from the integrated revision and use immutable source mounts;
unchanged current stable components may retain their verified images. Inspect
actual containers/processes/listeners and retire any duplicate old Bot service
only after confirming its exact identity. Keep stopped private rollback images
and data, never publish runtime configuration or credentials.

Verify scoped UI draft/save and group switching, two-account/two-group command
authorization, no fetch/send when disabled, mid-flight disable, exact PR tests,
Web type/build/tests and real image loading. Live checks inspect health,
authenticated configuration and no-send fixtures; they do not enable every
plugin in a production group to manufacture success.
