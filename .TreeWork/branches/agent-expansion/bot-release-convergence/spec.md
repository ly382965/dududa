# Bot Runtime Repair And Stable Release

Branch: bot-release-convergence
Parent: agent-expansion

## Scope And Ownership

The operator authorized repair, public deployment, container restarts, stable
Bot-service upgrades and sanitized GitHub publication. The final clarified
scope is only Dududa Web, AstrBot, the existing NapCat instance, MCP and Dududa
plugins. Other sites, LLM proxies, Authentik, Caddy and databases are excluded.
This is a production maintenance successor to the completed API Key work, not
the paused S23 human-quality or real-message acceptance milestone.

## Control Plane

The Agent Console must not depend on historical-corpus files or personal Codex
credentials. Keep the corpus evaluation adapter isolated. Use the existing
authenticated AstrBot plugin API for live readiness and allowlisted runtime
controls, and the existing no-send Runtime preview for operator requests.
Report configuration readiness, actual live connection and delivery authority
separately; NO BANDIT is a capability boundary, never a connection error.
Scope policy remains account/conversation isolated and consumed by the current
Runtime. Do not make raw root-owned configuration readable by the browser/Web
or widen rollout, tool, Memory or QQ-send authority to fix a status banner.

## Credential Workflow

Make the shared per-tier Provider/Base URL/model settings discoverable from the
Key dialog. Keys remain write-only and stored outside Git. Show saved versus
applied state honestly. Any controlled application must use the existing
private snapshot projection and preserve unaffected providers, model contract
checks and last-known-good configuration; an arbitrary model name is not
conformance evidence. Never synthesize green health or import personal keys.

## Release And Recovery

Inspect actual containers rather than relying on mutable local tags or stale
worktree mounts. Select upstream stable releases excluding beta/RC tags even
if incorrectly marked stable by a release API. Build Dududa components from
one tested source revision. Preserve existing login state, external data,
private credentials, network aliases and authorization policy. Pin release
artifacts and freeze the old images/configuration privately before each
cutover; do not delete historical data or create a second NapCat instance.
Upgrade sequentially and validate each dependent connection. Schema changes
require compatible backups before activation. Never upload runtime snapshots,
database backups, image exports, sessions or credentials to GitHub.

## Verification

Focused tests cover missing corpus configuration with a live Runtime, actual
unreachable/auth-failed Runtime, honest status messages, no-send preview and
scope isolation. Run frontend/server tests, type/build and affected Python
contracts. Verify deployed service health, actual source/image identities,
NapCat reconnection and public authentication protection. Preserve any unknown
live model-quality or user-message acceptance gap explicitly. Publish code,
tests, example configuration and sanitized deployment/rollback documentation
after reviewing staged changes for sensitive data.
