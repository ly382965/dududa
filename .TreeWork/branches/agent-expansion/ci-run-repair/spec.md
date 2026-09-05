# Branch Spec

Branch: ci-run-repair
Parent: agent-expansion

## Design

Repair the failures recorded by GitHub run 33897997167 on the current main
code. The Python suite cannot import the corpus student tests because CI does
not install the existing locked corpus dependency group. Install that group
for repository-test jobs; keep corpus packages out of runtime dependencies and
retain all tests.
The current MCP/preview entrypoints also import Python 3.11's tomllib although
3.10 remains in the supported CI matrix. Use tomli only below Python 3.11,
declare it for the plugin and development environment, and lock its resolution.

The S09 bundle checker reproduces artifact drift locally. Compare generated
and committed artifacts to identify whether a generator regression or a stale
derived report caused the drift before changing either. Commit 8228da9 added
the fixed task-conflict diagnostic to current SocialDecision; its independent
annotation still expects only the former generic code. Require both exact
codes for those ten conflict cases and regenerate derived bundle metadata.
Preserve source cases, action/tier labels, assertions and exact artifact checks.
Fix any subsequent failures that
these initial blockers expose using the same evidence-driven approach.

Synchronize existing fixtures with the current strict reference Schema,
default-LONG tool answers, enabled MCP catalog, Builtin shuttle provider, and
RuleOnlyRuntimePerception public export. Preserve exact equality assertions and
all original security, revocation, round-trip and answer-semantic checks.

Current query planning must distinguish retrieval size from answer size for
ranking. A request to rank activities and show three needs the provider's
existing bounded candidate set before ranking; applying a limit of three to
the unsorted retrieval can discard the true winners. Keep the configured
retrieval bound for explicit ranking, with the requested output count still
present in the response context. Plain listing continues to narrow retrieval.

Run both Python versions and committed bundles with the actual CI commands,
then push one consolidated repair and inspect GitHub checks. Private downloaded
logs stay in temporary storage. Production services and notification preferences
are outside this CI repair.
