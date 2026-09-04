# Current Arc Compatibility Release

Parent: bot-release-convergence

The operator requested all remaining gaps repaired, including retiring active
legacy Arc. Preserve currently deployed useful QQ query commands rather than
silently deleting them or enabling a different default-off capability. Inspect
only the legacy plugin's code and structural configuration names, never secrets,
member records or private payloads. Port the necessary compatibility behavior
into the canonical versioned plugin with sanitized configuration and tests.
Do not copy private URLs/tokens/records into Git. Use externally configured
identities and asset/state paths, preserving the existing group authorization.
The compatibility `/arc b50` command explicitly retains the original side effects:
unbind/rebind/query messages to one configured upstream Bot and image delivery to
the requesting group. It is not a read-only Capability. Only an explicit command
from an allowlisted group may enqueue this flow; startup, migration and health
inspection never bind accounts or send messages. Tests use fake events only.

The upstream protocol has no request correlation identifier. A timeout or uncertain
send therefore pauses B50 for the plugin process and clears queued requests, rather
than risking a late reply being delivered to the next user. An operator must first
confirm the upstream is idle before reloading the plugin. Normal completion retains
the original two-second duplicate-result grace, not a guarantee against arbitrarily
late duplicates. Queue size, active-request duration and sends are bounded.

Keep the newer local capability's public contract/default-off behavior intact;
provide explicit compatibility configuration for existing commands as needed.
Retain the old release outside active mounts for rollback after verified cutover.
Do not remove Arc commands without mapping them to the current implementation
or explicitly reporting an unavailable upstream dependency. No real third-party
query, game-account binding, QQ send or credential reset during implementation.

Own only apps/astrbot-plugins/astrbot_plugin_arc_proxy, its tests and relevant
Arc docs/examples. Lead owns deployment, container changes and private config.

Acceptance: old/current command inventory and migration map; positive and
negative fake-client tests including auth, bad input and exception redaction;
current canonical plugin can load and replace legacy code while preserving
configured command behavior; no private material committed.
