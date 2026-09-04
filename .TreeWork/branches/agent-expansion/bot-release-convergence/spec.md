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

The proactive participation card exposes an accessible group-only enable switch
for the existing `social.proactive_talk` Scope plugin policy. Enable selects
`auto`; disable selects `off`. Existing `on`/`locked` values display as enabled
until explicitly changed. Use the normal draft/update and Save Configuration
flow, with a visible save-required hint. Preserve all rate limits, other plugin
settings, account/conversation identity and global delivery controls. Disable
the switch while policy is absent/loading/saving or the conversation is private.
Adding the control does not itself enable any production group or send QQ.

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
if incorrectly marked stable by a release API. Build changed Dududa components
from a tested source revision; phased hotfixes may preserve unchanged services
at their verified revision, with exact component identities recorded. Preserve existing login state, external data,
private credentials, network aliases and authorization policy. Pin release
artifacts and freeze the old images/configuration privately before each
cutover; do not delete historical data or create a second NapCat instance.
Upgrade sequentially and validate each dependent connection. Schema changes
require compatible backups before activation. Never upload runtime snapshots,
database backups, image exports, sessions or credentials to GitHub.

## MCP Workbench Activation (2026-09-04)

Complete the five existing cache-backed public read-only services: campus-events,
college-notice, library, local-recs and training-plan. Supply production paths,
bounded operator-refreshed public caches and one governed capability per service.
Keep these additions in a console-only catalog so existing automatic Runtime
provider discovery, group permissions and planner categories do not expand.
No refresh/write tool, arbitrary URL, CAS credential or QQ delivery is exposed.
Curated local recommendations are explicitly non-live, unverified reference data.

Catalog reads must not launch sessions. Show disabled, unmapped, missing-secret,
unverified, connected and failed states truthfully. A same-origin, registered-ID
connection check performs bounded discovery only, not business queries. Display
the real check timestamp, not the catalog polling timestamp. Successful discovery
does not attest to cache freshness; query results expose source/cache provenance.
Refresh official pages with bounded existing operator CLIs, preserving caches on
empty/failed parses. Verify actual nonempty queries before public deployment.

Acceptance includes source/parser tests, five generated schema/mapping contracts,
unchanged shared Runtime catalog, sanitized connection failures, same-origin and
UI checks, deployed discovery/query counts and public auth. The pre-existing
model-upstream/Arc decisions remain outside this MCP acceptance.

## DeepSeek Migration Intake (operator approval, 2026-09-04)

Operator explicitly approved applying the saved official DeepSeek pools, enabling
Sonnet and setting reasoning tiers. Verify synthetic requests with Flash low,
Flash high and Pro max before applying. Keep GPT effort mapping unchanged; map
DeepSeek maximum to max and provide a bounded visible-output health probe.
The existing no-retention requirement must not be silently weakened: any
provider-managed retention policy requires separate informed operator approval.
Preserve provider evidence truth, source-specific model bindings, private rollback
files and current group policies. No manual QQ test message is authorized.

The operator subsequently explicitly approved provider-managed retention for all
three DeepSeek tiers. Apply CN/provider_managed only to these endpoints, preserve
unrelated Provider/Source records and group policy, and cold-recreate AstrBot to
replace retained Provider instances. Prepare private candidate command/Core files
and fresh model-bound evidence, then install while AstrBot is stopped with exact
previous files retained for rollback. Do not publish keys or private evidence.

Actual AstrBot 4.27.5 has SDK and outer recovery retries beneath Dududa's one-call
contract. Patch only the explicitly bounded non-streaming request path to disable
SDK retries and bypass outer recovery; sanitize completion/Key logs. Prove the
real patched class with mock HTTP success/failure/deadline/cancellation tests,
then each real DeepSeek tier with its output cap and effort. Evidence combines
these distinct proofs with the official residency/retention policy and approval,
not a blanket success flag copied from GPT. Use a reasoning reserve within the
saved tier caps and validate a real no-send/no-memory-write Runtime preview.
Keep the retained legacy Arc functional without first-start dependency downloads:
pin its already installed public OpenCV/pyparsing distributions in the canonical
image. A bounded hotfix may copy only those public package paths from the frozen
compatibility image onto the verified current base; never copy its private data.

## General Verification

Focused tests cover missing corpus configuration with a live Runtime, actual
unreachable/auth-failed Runtime, honest status messages, no-send preview and
scope isolation. Run frontend/server tests, type/build and affected Python
contracts. Verify deployed service health, actual source/image identities,
NapCat reconnection and public authentication protection. Preserve any unknown
live model-quality or user-message acceptance gap explicitly. Publish code,
tests, example configuration and sanitized deployment/rollback documentation
after reviewing staged changes for sensitive data.
