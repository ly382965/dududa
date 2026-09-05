# Findings

Branch: ci-run-repair

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- GitHub run 33897997167 failed the two repository-test jobs and offline-eval;
  Web and secret scanning succeeded. The suite receipt deliberately reports
  bounded errors, so direct local invocation was required to expose details.
- Test discovery first fails on missing corpus dependencies; Python 3.10 also
  lacks tomllib in current plugin and preview entrypoints. Neither failure is
  a reason to disable a test or remove a supported CI job.
- Current SocialDecision added a fixed task-conflict reason in 8228da9, but
  ten independent S09 annotations still required the previous reason set.
- Schema commit 8503385 constrained unresolved reference targets. The semantic
  pilot and exact Schema test still recorded the earlier digest.
- The response fixture still expected MEDIUM for an unqualified tool response;
  current policy explicitly selects LONG. Update the fixture, not the policy.
- Mixed-catalog setup treated the current Builtin shuttle descriptor as MCP;
  use its real local provider while preserving the fake-only execution checks.
- Young case 38 exposed early candidate truncation before ranking, compounded
  by interpreting the text '当前二课' as an explicit count of two. Preserve the
  existing retrieval bound for ranking and exclude that non-count phrase.
- Python 3.10 rejects Docker's nine-digit fractional timestamp. Normalize to
  datetime's six-digit precision before parsing, matching Python 3.12, and
  assert the exact UTC timestamp in the existing replay test.
- Follow-up run 33941400500 passed Web, offline-eval and secret scanning. Its
  Python release-audit tests require HEAD^, absent from checkout's default
  depth of one. Reproduced both errors in a fresh shallow clone; fetching
  depth two makes all five audit tests pass on both supported Python versions.
  Set only the Python job's checkout depth to two; preserve the audit tests.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- No tests, jobs or assertions are removed; exact expectations now describe
  current production definitions. Source cases, permission boundaries and
  quality-claim limitations remain unchanged.
- Only current CI and Runtime query planning are repaired. Legacy features,
  production service deployment and account notification settings are excluded.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)
