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

### Remaining Repairs Intake (2026-09-04)

The operator now requests all six reported remaining items. The accepted child
branches own group-history/preview outcomes and demonstrated perception defects,
explicit external model configuration application, and Arc compatibility migration.
This replaces the earlier pending Arc product choice: preserve the four deployed
QQ commands in the canonical compatibility implementation, with the old behavior
explicitly enabled only for the existing authorized groups. Migration and startup
must not send messages or bind upstream accounts. The local Capability contract
remains separate and default-off. Freeze the prior implementation privately after
cutover rather than deleting command support or user data.

The operator subsequently explicitly deferred Arc score lookup. Keep B50 disabled
behind its separate flag in this release; no upstream binding/query or live B50
acceptance is required or authorized. Preserve the implemented compatibility code
for a later explicit enablement, and migrate the remaining local Arc commands.

Lead integration verifies the newly authored 100-question Markdown separately
from the older deterministic 100-message fixture. Record synthetic model-preview,
isolated fault/proactive checks and live delivery evidence separately; do not
claim scripted answers or HTTP success establish model-quality acceptance.
No bulk production-group test messages are authorized. The latest saved target
group policy has its participation switch on but probability zero. Preserve
that current operator setting and show its effective non-triggering state; a
real autonomous-delivery acceptance remains unavailable while that policy holds.

The model apply boundary owns a Dududa-only Provider generation, leaving shared
AstrBot Provider instances alive for other consumers until normal host shutdown.
Use bounded candidate validation, a serialized apply and active-call admission
boundary before swapping the Dududa assembly; preserve external configurations
and rollback on failed preparation. This does not authorize a generic host
restart endpoint or browser access to credentials/Docker.

Live integration follow-ups remain within the same repair: a historical context
must survive Runtime checkpoint validation using the existing bounded builder,
not a second history schema. Production SHORT output keeps its existing 180
visible-character hard cap; its Unicode policy-unit cap is aligned to 180 so a
Chinese response already inside that display bound is not rejected by a hidden
128-unit limit. Do not truncate generated facts or increase reasoning budgets.
Production perception instructions name the existing canonical transformation
task kind for summarizing/rewriting untrusted quoted data. Preserve conflicting
intent decisions and report only four fixed conflict-field reason codes, never
raw model projections or prompt/configuration contents.

An actual retained multi-message group-summary request may select the existing
MEDIUM response profile through existing detail evidence. Explicit short/long,
locked preferences, one-message summaries and non-summary transformations retain
their behavior. This does not raise response hard limits, change model tiers or
authorize tool/QQ actions. Record failed and partial model-quality cases without
hardcoding the acceptance table into the framework.

### MCP Frontend Layout Follow-up

Repair only the workbench presentation: explicitly style the connection-check
button and pending/disabled/focus states, separate wrapping status text from
timestamps and actions, and adapt columns to the actual panel width. Keep the
workbench toolbar visible within its scrolling section without covering the
Agent tabs. Preserve connection checks, expiry semantics and authorization;
do not automatically probe servers or change Runtime/history behavior. Verify
real browser layout at narrow and desktop panel widths with synthetic data,
then release only Web using the existing private rollback manifest.

Focused tests cover missing corpus configuration with a live Runtime, actual
unreachable/auth-failed Runtime, honest status messages, no-send preview and
scope isolation. Run frontend/server tests, type/build and affected Python
contracts. Verify deployed service health, actual source/image identities,
NapCat reconnection and public authentication protection. Preserve any unknown
live model-quality or user-message acceptance gap explicitly. Publish code,
tests, example configuration and sanitized deployment/rollback documentation
after reviewing staged changes for sensitive data.
