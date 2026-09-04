# Current Arc Compatibility Release

Parent: bot-release-convergence

The operator requested all remaining gaps repaired, including retiring active
legacy Arc. Preserve currently deployed useful QQ query commands rather than
silently deleting them or enabling a different default-off capability. Inspect
only the legacy plugin's code and structural configuration names, never secrets,
member records or private payloads. Port the necessary compatibility behavior
into the canonical versioned plugin with sanitized configuration and tests.
Do not copy private URLs/tokens/records into Git. Use externally configured
endpoints/SecretRefs, existing authorization and bounded read-only requests.

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
