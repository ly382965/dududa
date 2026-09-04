# Verification

Branch: preview-context-repair

## Latest Verification

- Recorded: 2026-09-04, isolated worktree, Ready for Lead Review only.
- Result: focused tests and browser acceptance passed. Unified integration and
  production deployment remain Lead-owned.

## Commands And Results

From this worktree, using the parent's existing Python environment with
PYTHONPATH=packages/dududa-agent/src:apps/astrbot-plugins:

```text
python -B -m unittest tests.unit.runtime.test_preview_context tests.unit.runtime.test_s10_context_budget tests.unit.runtime.test_direct_chat tests.unit.perception.test_merge tests.unit.perception.test_rules tests.unit.perception.test_social tests.contracts.test_astrbot_web_runtime tests.contracts.test_astrbot_rollout -q
```

59 tests passed: both model inputs, correction/reply/date metadata, scope
rejection, untrusted-history separation, bounded long JSON records, monotone
verification and narrow task aliases, terminal outcomes and no-send/no-memory.

From apps/web, temporarily using the parent's installed node_modules:

```text
npm test
npm run build
npx vitest run --config vitest.server.config.ts server/agent-runtime.spec.ts server/dududa-runtime.spec.ts server/internal-test-routes.spec.ts
npm run typecheck
npx playwright test e2e/workspace.spec.ts --grep 'preview explains empty'
```

- Full suite: 22 frontend files / 101 tests and 13 server files / 114 tests passed.
- Build passed; the existing Vite chunk-size advisory remains nonfatal.
- Final focused server rerun: 3 files / 17 tests passed; both type checks passed.
- Browser: 2 tests passed, 1280px and 390px, fake Hub and mocked Runtime. Zero
  send actions, no browser history submitted, non-success empty preview, partial
  context and saved/draft zero probability asserted. Screenshots visually checked:
  test-results/workspace-preview-explains-5e867-y-without-sending-at-1280px/
  and test-results/workspace-preview-explains-62382-ty-without-sending-at-390px/.
- git diff --check passed. Ruff passed for the new preview-context test and
  modified Core context/direct-chat files; unrelated existing adapter findings
  were not swept into this branch.

## Additional Integration Attempt And Prerequisite

Production-composition/source-guards ran 38 tests with 65 fixture subtest failures:
expected MCP results degraded to existing unavailable-service replies. This
worktree has no services/mcp/unified-worker/.venv, which the fixture factory
explicitly requires. The sibling independently confirmed this same issue and
restored a passing single iCourse case after installing the locked environment:

```text
uv sync --project services/mcp/unified-worker --locked --no-dev --python 3.12
```

Lead requested no duplicate full rerun here; its parent worktree already has
that environment for unified verification. This attempt is neither recorded
as an application regression nor claimed as a passing suite.

## Coverage Gaps

No live model/API, real group transcript, QQ send, credentials or real memory
write was used. Synthetic fake-provider summaries prove propagation, not live
answer quality. Lead owns combined changes, separately authorized model
acceptance, production deployment and protected branch completion.
